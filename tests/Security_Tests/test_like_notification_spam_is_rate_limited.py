"""Security test — repeated likes must not send unlimited notification spam.

Investigation (see conversation): POST /posts/{id}/like (forum-service/app/
routers/forum.py: like_post) uses $addToSet for the like itself, which is
correctly idempotent. But the like_notification sent to the post's owner via
manager.send_personal_message fires unconditionally on every call, with no
check on whether $addToSet actually changed anything. So one user clicking
"like" on someone else's post N times sends N separate notifications to the
owner, even though the like state never changes after the first click — and
unlike create_post/create_thread/create_direct_message, like_post has no
rate_limit dependency at all.

PASS means: rapid repeated likes from one user against another user's post
eventually get rate-limited (429), the same way post/thread/DM creation
already are.
FAIL means every call succeeds (200) — which is the case today, since no
limit exists on this endpoint.

The threshold below (30) mirrors forum-service/app/rate_limit.py's existing
general-endpoint limit (_MAX_REQUESTS = 30 req/60s) — the closest existing
analog for a lightweight per-user action, absent a dedicated "likes" limit.

Requires the live stack — skips automatically if no stack is reachable at
SMARTDESK_URL. Bring one up with `docker compose up -d`.
"""
import os
import time

import httpx
import pytest

BASE = os.environ.get("SMARTDESK_URL", "http://localhost:8080")

# forum-service/app/rate_limit.py: _MAX_REQUESTS = 30 requests / 60s window,
# the general-endpoint limit — no likes-specific limit exists yet.
GENERAL_LIMIT = 30


def _stack_is_up() -> bool:
    try:
        return httpx.get(f"{BASE}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def live_stack():
    if not _stack_is_up():
        pytest.skip(
            f"No SmartDesk stack reachable at {BASE}. "
            "Start it with `docker compose up -d` (or set SMARTDESK_URL)."
        )


def _register(email: str) -> str:
    r = httpx.post(
        f"{BASE}/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    assert r.status_code == 201, f"registration failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def test_repeated_likes_are_eventually_rate_limited(live_stack):
    run_id = str(int(time.time()))
    owner_token = _register(f"like-spam-owner-{run_id}@example.com")
    liker_token = _register(f"like-spam-liker-{run_id}@example.com")

    thread = httpx.post(
        f"{BASE}/api/forums/boards/account/threads",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"title": "like spam target", "body": "please don't spam me"},
    )
    assert thread.status_code == 201, thread.text
    thread_detail = httpx.get(
        f"{BASE}/api/forums/threads/{thread.json()['id']}",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()
    post_id = thread_detail["posts"][0]["id"]

    like_url = f"{BASE}/api/forums/posts/{post_id}/like"
    liker_headers = {"Authorization": f"Bearer {liker_token}"}

    statuses = [httpx.post(like_url, headers=liker_headers).status_code for _ in range(GENERAL_LIMIT)]
    assert all(s == 200 for s in statuses), (
        f"expected the first {GENERAL_LIMIT} likes to succeed, got {statuses}"
    )

    over_limit = httpx.post(like_url, headers=liker_headers)
    assert over_limit.status_code == 429, (
        f"expected the {GENERAL_LIMIT + 1}th rapid like from the same user "
        f"to be rate-limited (429), got {over_limit.status_code} — nothing "
        "currently caps how many like_notification pushes one user can "
        "trigger against another user's post"
    )
