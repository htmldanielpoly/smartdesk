"""Sliding-window rate limiter for the forum service.

In-memory, single-process only. Adequate for a single-instance course
deployment; swap for Redis if scaled horizontally.

Keyed on the authenticated user's id, not the caller's IP: every forum
request arrives via api-service's reverse proxy, so request.client.host is
always api-service's own address — keying on it collapsed every user onto
one shared bucket. All endpoints that apply these dependencies already
require get_current_user, so a per-user key is available everywhere they're
used.
"""
import time
from collections import defaultdict, deque
from fastapi import Depends, HTTPException, status

from app.deps import get_current_user

# Conservative limits for forum actions — tighter than the api-service
# gateway because forum endpoints are cheaper to abuse (no AI calls).
_WINDOW_SECONDS = 60
_MAX_REQUESTS = 30          # general endpoints
_MAX_POSTS = 10             # posting/replying (stricter)
_MAX_MESSAGES = 20          # DMs

_hits: dict[str, deque[float]] = defaultdict(deque)


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


async def rate_limit(user: dict = Depends(get_current_user)) -> None:
    """General rate limit dependency — 30 req/60s per user."""
    _check(user["id"], _MAX_REQUESTS)


async def rate_limit_post(user: dict = Depends(get_current_user)) -> None:
    """Strict rate limit for creating posts/threads — 10/60s per user."""
    _check(f"post:{user['id']}", _MAX_POSTS)


async def rate_limit_message(user: dict = Depends(get_current_user)) -> None:
    """Rate limit for direct messages — 20/60s per user."""
    _check(f"msg:{user['id']}", _MAX_MESSAGES)


def reset() -> None:
    """Clear all counters (used by tests)."""
    _hits.clear()