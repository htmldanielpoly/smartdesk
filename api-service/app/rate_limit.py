"""Abuse protection: sliding-window rate limits, metered per user.

Two limiters share one clock:

* ``rate_limit``        - general budget (RATE_LIMIT_REQUESTS per window) for
                          every metered endpoint.
* ``rate_limit_writes`` - a stricter budget (RATE_LIMIT_WRITES per window) for
                          anything that creates content: ticket comments,
                          forum threads/posts/messages. This is the defence
                          against "a user sending 1000 messages in a short
                          time to overload the server".

Keying: an authenticated request is metered **per user** (the id is read
from the JWT, no database round-trip), so one abusive customer cannot lock
out everyone behind the same NAT or reverse-proxy address, and a load test
with many virtual users on one host is metered per virtual user.
Unauthenticated requests (register/login) are metered per client address;
with TRUST_PROXY_HEADERS=true the address is taken from X-Forwarded-For (only
enable this behind a reverse proxy you control, otherwise it can be spoofed).

In-memory and single-process like the rest of the gateway. Idle keys are
swept periodically so memory does not grow with every address ever seen.
"""
import time
from collections import defaultdict, deque

import jwt
from fastapi import HTTPException, Request, status

from app.config import settings
from app.security import decode_access_token

_hits: dict[str, deque[float]] = defaultdict(deque)
_last_sweep = 0.0
_SWEEP_EVERY_SECONDS = 60.0

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def client_key(request: Request) -> str:
    """``user:<id>`` for a valid bearer token, else ``ip:<address>``."""
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        try:
            subject = decode_access_token(auth[7:].strip()).get("sub")
        except jwt.PyJWTError:
            subject = None
        if subject:
            return f"user:{subject}"

    host = request.client.host if request.client else "unknown"
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        first_hop = forwarded.split(",")[0].strip()
        if first_hop:
            host = first_hop
    return f"ip:{host}"


def _sweep(now: float) -> None:
    """Drop keys that have been idle for a full window (bounded memory)."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_EVERY_SECONDS:
        return
    _last_sweep = now
    horizon = now - settings.rate_limit_window_seconds
    for key in [k for k, hits in _hits.items() if not hits or hits[-1] <= horizon]:
        del _hits[key]


def _check(bucket: str, key: str, limit: int) -> None:
    now = time.monotonic()
    _sweep(now)
    window = settings.rate_limit_window_seconds

    hits = _hits[f"{bucket}:{key}"]
    while hits and hits[0] <= now - window:
        hits.popleft()

    if len(hits) >= limit:
        retry_after = max(1, int(window - (now - hits[0])) + 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    hits.append(now)


async def rate_limit(request: Request) -> None:
    """FastAPI dependency: general per-user (or per-address) budget."""
    _check("all", client_key(request), settings.rate_limit_requests)


async def rate_limit_writes(request: Request) -> None:
    """FastAPI dependency: the stricter budget for content creation."""
    _check("write", client_key(request), settings.rate_limit_writes)


async def rate_limit_by_method(request: Request) -> None:
    """Reads count against the general budget, writes against the strict one
    (used by the forum proxy, which handles every method on one route)."""
    if request.method.upper() in _WRITE_METHODS:
        await rate_limit_writes(request)
    else:
        await rate_limit(request)


def reset() -> None:
    """Clear all counters (used by tests)."""
    global _last_sweep
    _hits.clear()
    _last_sweep = 0.0
