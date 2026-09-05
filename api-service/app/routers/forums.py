"""Reverse proxy for the internal forum service.

The api-service is the only publicly exposed service. The forum-service stays
unexposed on the private Docker network, and all forum traffic flows through
this catch-all route, which forwards the method, path, query string, JSON body
and Authorization header verbatim and relays the forum-service's response.
Auth itself is enforced by the forum-service (same JWT secret).
"""
import contextlib
import httpx
import asyncio
import websockets
from fastapi import APIRouter, Request, status ,WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse


from app.config import settings

router = APIRouter(prefix="/api/forums", tags=["forums"])

_FORWARDED_HEADERS = ("authorization", "content-type")


@router.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> JSONResponse:
    url = f"{settings.forum_service_url}/{path}"
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _FORWARDED_HEADERS
    }
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=settings.forum_timeout_seconds) as client:
            resp = await client.request(
                request.method,
                url,
                params=str(request.url.query),
                content=body or None,
                headers=headers,
            )
    except httpx.HTTPError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Forum service is unavailable."},
        )

    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            content = resp.json()
        except ValueError:
            content = None
        return JSONResponse(status_code=resp.status_code, content=content)
    else:
        # Binary response (images, videos) — stream bytes directly
        from fastapi.responses import Response
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=content_type,
        )


@router.websocket("/ws")
async def websocket_proxy(websocket: WebSocket, token: str = Query(None)):
    target_ws_url = f"{settings.forum_service_url.replace('http', 'ws')}/ws?token={token}"

    # Forward Origin for CORS and inject the Authorization header
    forwarded_headers = {}
    if token:
        forwarded_headers["Authorization"] = f"Bearer {token}"
    if "origin" in websocket.headers:
        forwarded_headers["Origin"] = websocket.headers["origin"]

    try:
        # Connect to the forum-service FIRST
        async with websockets.connect(target_ws_url, additional_headers=forwarded_headers) as backend_ws:

            # Accept the frontend client ONLY if the backend handshake succeeds
            await websocket.accept()

            async def to_backend():
                while True:
                    data = await websocket.receive_text()
                    await backend_ws.send(data)

            async def to_frontend():
                while True:
                    data = await backend_ws.recv()
                    await websocket.send_text(data)

            pump_to_backend = asyncio.create_task(to_backend())
            pump_to_frontend = asyncio.create_task(to_frontend())
            pumps = {pump_to_backend, pump_to_frontend}

            # Whichever side disconnects (or errors) first ends the pair:
            # cancel the other pump immediately instead of leaving it awaiting
            # forever, then let this `async with` exit so backend_ws actually
            # closes. Previously the sibling task just hung, keeping the
            # outbound connection to forum-service (and its ConnectionManager
            # entry) open forever.
            done, pending = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(
                    exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)
                ):
                    raise exc

        # backend_ws is closed by now (the `async with` above exited). Make
        # sure the frontend socket isn't left open with nothing pumping into
        # it if the backend side was what ended the pair.
        with contextlib.suppress(RuntimeError):
            await websocket.close()

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"🔥 WEBSOCKET PROXY CRASH: Upstream rejected with status {e.status_code}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        # A normal disconnect that happened before the pump loop above even
        # started (e.g. the frontend vanished during/just after accept()) —
        # not a crash, nothing to alarm about.
        print("WebSocket proxy connection closed.")
        with contextlib.suppress(RuntimeError):
            await websocket.close()
    except Exception as e:
        print(f"🔥 WEBSOCKET PROXY CRASH: {repr(e)}")
        with contextlib.suppress(RuntimeError):
            await websocket.close()