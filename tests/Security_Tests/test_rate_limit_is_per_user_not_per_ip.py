"""Security test — forum rate limiting must be scoped per user, not per IP.

Verifies CRITICAL finding #3 from the code review: forum-service/app/
rate_limit.py keys its sliding-window limiter on ``request.client.host``.
All forum traffic reaches forum-service via api-service's reverse proxy
(api-service/app/routers/forums.py: proxy()), which forwards only the
Authorization/Content-Type headers — never the original client's IP (no
X-Forwarded-For, nothing). So every distinct end user's requests arrive at
forum-service looking like they came from api-service's own container
address, and they all collapse onto ONE shared rate-limit bucket.

PASS means: User A exhausting their own create-post quota (rate_limit_post,
10 requests/60s — see forum-service/app/rate_limit.py) does NOT prevent
User B — a different authenticated user making their first request of the
window — from posting immediately afterwards.

FAIL means User B's very first post is rejected with 429 purely because of
User A's activity, i.e. a single user can accidentally (or deliberately)
lock every other user out of posting for the rest of the window.

This bug only exists in the real network topology (api-service and
forum-service as separate processes talking over the docker network), so
this test drives the actual live stack through the public gateway, exactly
the path a browser would take. It skips automatically if no stack is
reachable at SMARTDESK_URL (default http://localhost:8080) — bring one up
with `docker compose up -d` (see tests/System_Tests/test_end_to_end.py for
the same convention).
"""
import json
import os
import time
import urllib.error
import urllib.request

import pytest

BASE = os.environ.get("SMARTDESK_URL", "http://localhost:8080")

# forum-service/app/rate_limit.py: _MAX_POSTS = 10 requests / 60s window,
# applied to thread/post creation via the rate_limit_post dependency.
POSTS_PER_WINDOW = 10


def _stack_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


@pytest.fixture(scope="module")
def live_stack():
    if not _stack_is_up():
        pytest.skip(
            f"No SmartDesk stack reachable at {BASE}. "
            "Start it with `docker compose up -d` (or set SMARTDESK_URL)."
        )


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
        return exc.code, json.loads(exc.read() or b"null")


def _register(email: str) -> str:
    status, body = _call(
        "POST",
        "/api/auth/register",
        body={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    assert status == 201, f"registration failed: {status} {body}"
    return body["access_token"]


def _post_thread(token: str, i: int):
    # Board slug seeded by forum-service/app/seed.py at startup.
    return _call(
        "POST",
        "/api/forums/boards/account/threads",
        token=token,
        body={"title": f"rate-limit probe {i}", "body": f"probing shared bucket #{i}"},
    )


def test_rate_limit_is_scoped_per_user_not_shared_ip(live_stack):
    run_id = str(int(time.time()))
    token_a = _register(f"ratelimit-a-{run_id}@example.com")
    token_b = _register(f"ratelimit-b-{run_id}@example.com")

    # User A uses up their own quota.
    statuses_a = [_post_thread(token_a, i)[0] for i in range(POSTS_PER_WINDOW)]
    assert statuses_a == [201] * POSTS_PER_WINDOW, (
        f"expected all of User A's first {POSTS_PER_WINDOW} posts to succeed, got {statuses_a}"
    )

    over_limit_status, _ = _post_thread(token_a, POSTS_PER_WINDOW)
    assert over_limit_status == 429, (
        "expected User A's own request beyond the quota to be rate-limited "
        f"(got {over_limit_status}) — if this isn't 429, the limiter isn't "
        "engaging at all and the real bug can't be observed here"
    )

    # User B's FIRST request in the same window must succeed. Today it
    # doesn't, because forum-service sees both users as the same IP
    # (api-service's), so User B inherits User A's exhausted bucket.
    user_b_status, user_b_body = _post_thread(token_b, 0)
    assert user_b_status == 201, (
        "User B's first-ever post was rate-limited "
        f"(status {user_b_status}: {user_b_body}) purely because of User A's "
        "activity — the forum-service rate limiter is keyed on the shared "
        "proxy IP instead of per authenticated user"
    )
