"""Security/robustness test — a WebSocket disconnect must free its connection.

Verifies CRITICAL finding #2 from the code review: api-service's WebSocket
proxy (api-service/app/routers/forums.py: websocket_proxy) runs two pumping
coroutines under asyncio.gather() — one forwarding frontend->backend, one
backend->frontend. When the frontend (browser) closes its socket, only the
frontend->backend coroutine sees that and returns; the backend->frontend
coroutine stays blocked on backend_ws.recv() forever, because nothing ever
closes the outbound connection to forum-service. So forum-service's own
websocket_endpoint (forum-service/app/routers/forum.py) never sees a
WebSocketDisconnect either, and the dead entry is never removed from
ConnectionManager.active_connections (forum-service/app/websockets.py).

This can only be observed by going through the real proxy path a browser
takes (in-process ASGI testing of forum-service alone would not reproduce
it, since forum-service's own disconnect handling is correct in isolation).
So this test drives the live stack, connecting through api-service exactly
like static/app.js's connectWebSocket() does, then reads forum-service's
connection count via a test-only introspection route
(GET /debug/ws-connections/{user_id}, gated behind ENABLE_TEST_ENDPOINTS —
see tests/README.md and docker-compose.test.yml).

PASS means: after the client-side socket closes and a short grace period
passes, the connection count for that user drops to 0.
FAIL means: the count is still >= 1 — the connection leaked.

Requires the live stack, brought up with the test-only override so the
introspection route responds:
    docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build
Skips automatically if no stack is reachable at SMARTDESK_URL, or if the
introspection route isn't enabled (i.e. the override wasn't used).
"""
import asyncio
import base64
import json
import os
import time
import urllib.error
import urllib.request

import pytest
import websockets

BASE = os.environ.get("SMARTDESK_URL", "http://localhost:8080")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")

# Grace period given to the server to notice the disconnect and clean up,
# before we consider the leak proven.
CLEANUP_GRACE_SECONDS = 3


def _stack_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


def _call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None


def _introspection_available() -> bool:
    # Any user id works here — we only care whether the route 404s (disabled)
    # or answers with a count (enabled).
    status, _ = _call("GET", "/api/forums/debug/ws-connections/probe")
    return status == 200


@pytest.fixture(scope="module")
def live_stack():
    if not _stack_is_up():
        pytest.skip(
            f"No SmartDesk stack reachable at {BASE}. "
            "Start it with `docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build`."
        )
    if not _introspection_available():
        pytest.skip(
            "forum-service's debug introspection route is not enabled "
            "(ENABLE_TEST_ENDPOINTS != 'true'). Bring the stack up with "
            "`docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build`."
        )


def _decode_jwt_sub(token: str) -> str:
    """Pull the 'sub' claim out locally, exactly like static/app.js's
    decodeJwt() — no signature verification needed, we trust our own server."""
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    return payload["sub"]


def _register(email: str) -> tuple[str, str]:
    status, body = _call(
        "POST",
        "/api/auth/register",
        body={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    assert status == 201, f"registration failed: {status} {body}"
    token = body["access_token"]
    return token, _decode_jwt_sub(token)


def _connection_count(user_id: str) -> int:
    status, body = _call("GET", f"/api/forums/debug/ws-connections/{user_id}")
    assert status == 200, f"introspection route unexpectedly returned {status}: {body}"
    return body["count"]


async def _connect_then_hard_close(token: str) -> None:
    """Open a WebSocket through api-service's proxy (the real browser path),
    confirm it's live, then close it exactly like a tab being closed."""
    ws = await websockets.connect(f"{WS_BASE}/api/forums/ws?token={token}")
    await ws.close()


def test_websocket_disconnect_cleans_up_connection(live_stack):
    run_id = str(int(time.time()))
    token, user_id = _register(f"ws-cleanup-{run_id}@example.com")

    assert _connection_count(user_id) == 0, "user should start with no live connections"

    asyncio.run(_connect_then_hard_close(token))

    # Give the server a moment to notice the disconnect, if it ever will.
    time.sleep(CLEANUP_GRACE_SECONDS)

    count_after_disconnect = _connection_count(user_id)
    assert count_after_disconnect == 0, (
        f"expected the connection to be cleaned up after disconnect, but "
        f"ConnectionManager still reports {count_after_disconnect} live "
        f"connection(s) for this user — the api-service WebSocket proxy "
        f"leaked the backend connection instead of closing it"
    )
