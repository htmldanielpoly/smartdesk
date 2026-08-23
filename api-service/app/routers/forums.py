"""Reverse proxy for the internal forum service.

The api-service is the only publicly exposed service. The forum-service stays
unexposed on the private Docker network, and all forum traffic flows through
this catch-all route, which forwards the method, path, query string, JSON body
and Authorization header verbatim and relays the forum-service's response.
Auth itself is enforced by the forum-service (same JWT secret).
"""
import httpx
import asyncio
import websockets
from fastapi import APIRouter, Request, status ,WebSocket, WebSocketDisconnect
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

    try:
        content = resp.json()
    except ValueError:
        content = None
    return JSONResponse(status_code=resp.status_code, content=content)


@router.websocket("/ws")
async def websocket_proxy(websocket: WebSocket, token: str):
    await websocket.accept()
    # Convert the internal HTTP url to a WS url
    target_ws_url = f"{settings.forum_service_url.replace('http', 'ws')}/ws?token={token}"

    try:
        async with websockets.connect(target_ws_url) as backend_ws:
            async def to_backend():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await backend_ws.send(data)
                except WebSocketDisconnect:
                    pass

            async def to_frontend():
                try:
                    while True:
                        data = await backend_ws.recv()
                        await websocket.send_text(data)
                except websockets.exceptions.ConnectionClosed:
                    pass

            # Run both relay tasks concurrently
            await asyncio.gather(to_backend(), to_frontend())
    except Exception:
        await websocket.close()