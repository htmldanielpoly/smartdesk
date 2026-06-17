import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings

# Simple in-memory sliding-window limiter keyed by client IP. Adequate for a
# single-instance course deployment; swap for Redis if scaled horizontally.
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def rate_limit(request: Request) -> None:
    """FastAPI dependency that throttles abusive callers (spam protection)."""
    now = time.monotonic()
    window = settings.rate_limit_window_seconds
    key = _client_key(request)

    hits = _hits[key]
    while hits and hits[0] <= now - window:
        hits.popleft()

    if len(hits) >= settings.rate_limit_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again shortly.",
        )

    hits.append(now)


def reset() -> None:
    """Clear all counters (used by tests)."""
    _hits.clear()
