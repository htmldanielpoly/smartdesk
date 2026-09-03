"""Reverse proxy for the internal forum service.

The api-service is the only publicly exposed service. The forum-service stays
unexposed on the private Docker network, and all forum traffic flows through
this catch-all route, which forwards the method, path, query string, JSON body
and Authorization header verbatim and relays the forum-service's response.
Auth itself is enforced by the forum-service (same JWT secret). Abuse
protection happens here, at the edge: reads are metered against the general
per-user budget and writes (threads, posts, messages) against the stricter
write budget, and oversized bodies are refused by the gateway-wide body
size limit before anything is forwarded.
"""
import httpx
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.rate_limit import rate_limit_by_method

router = APIRouter(prefix="/api/forums", tags=["forums"])

_FORWARDED_HEADERS = ("authorization", "content-type")


@router.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def proxy(
    path: str, request: Request, _: None = Depends(rate_limit_by_method)
) -> JSONResponse:
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
