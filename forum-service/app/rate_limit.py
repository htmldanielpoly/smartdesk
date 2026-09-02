"""Sliding-window rate limiter for the forum service.

In-memory, single-process only. Adequate for a single-instance course
deployment; swap for Redis if scaled horizontally.
"""
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request, status

# Conservative limits for forum actions — tighter than the api-service
# gateway because forum endpoints are cheaper to abuse (no AI calls).
_WINDOW_SECONDS = 60
_MAX_REQUESTS = 30          # general endpoints
_MAX_POSTS = 10             # posting/replying (stricter)
_MAX_MESSAGES = 20          # DMs

_hits: dict[str, deque[float]] = defaultdict(deque)


def _key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check(key: str, limit: int) -> None:
    now = time.monotonic()
    hits = _hits[key]
    while hits and hits[0] <= now - _WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again shortly.",
        )
    hits.append(now)


async def rate_limit(request: Request) -> None:
    """General rate limit dependency — 30 req/60s per IP."""
    _check(_key(request), _MAX_REQUESTS)


async def rate_limit_post(request: Request) -> None:
    """Strict rate limit for creating posts/threads — 10/60s per IP."""
    _check(f"post:{_key(request)}", _MAX_POSTS)


async def rate_limit_message(request: Request) -> None:
    """Rate limit for direct messages — 20/60s per IP."""
    _check(f"msg:{_key(request)}", _MAX_MESSAGES)


def reset() -> None:
    """Clear all counters (used by tests)."""
    _hits.clear()