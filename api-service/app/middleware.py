"""Request body size limit (abuse protection).

Every endpoint on this gateway takes small JSON documents (a ticket body is
capped at 5000 characters), so a request body of megabytes is never
legitimate - it is either a mistake or an attempt to exhaust memory ("sending
huge video files to overload the database"). Oversized requests are refused
with 413 before the body is buffered:

* if the client declares ``Content-Length``, the check costs nothing;
* if it streams without one (chunked), bytes are counted as they arrive and
  the request is aborted the moment the cap is crossed.

The cap is read from settings on every request so tests (and operators) can
tune MAX_REQUEST_BODY_BYTES without rebuilding the app.
"""
import json

from fastapi import HTTPException, status

from app.config import settings

_EXEMPT_PREFIXES = ("/api/uploads",)


def _too_large(limit: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail=f"Request body too large (limit {limit} bytes).",
    )


class BodySizeLimitMiddleware:
    """Pure ASGI middleware; no Starlette BaseHTTPMiddleware overhead."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(_EXEMPT_PREFIXES):
            # Media uploads enforce their own, larger, per-type caps while
            # streaming to disk (see routers/uploads.py).
            await self.app(scope, receive, send)
            return

        limit = settings.max_request_body_bytes
        declared = next(
            (value for name, value in scope.get("headers", []) if name == b"content-length"),
            None,
        )
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._reject(send, limit)
                    return
            except ValueError:
                pass  # malformed header: let the counting path decide

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Raised inside the app's request handling, so FastAPI's
                    # HTTPException handler turns it into a proper 413 response.
                    raise _too_large(limit)
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _reject(send, limit: int) -> None:
        body = json.dumps({"detail": _too_large(limit).detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
