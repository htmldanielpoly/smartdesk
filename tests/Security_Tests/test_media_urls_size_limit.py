"""Security test — media_urls has no length or per-item size cap.

Verifies a real gap: ThreadCreate/PostCreate/DirectMessageCreate in
forum-service/app/schemas.py all cap title/body/content with max_length, but
media_urls: list[str] = Field(default_factory=list) has no cap on the list's
length or on any individual string's length. Every accepted post/thread gets
broadcast verbatim to every connected client via ConnectionManager.broadcast()
(forum-service/app/websockets.py), so an oversized media_urls list is a direct
resource/spam vector — unlike body/title/content, which are all bounded.

Uses thread creation (POST /api/forums/boards/{slug}/threads) since it only
needs one user and a pre-seeded board ("account"), the simplest of the three
media_urls-carrying endpoints to exercise.

PASS means: an excessively large media_urls list — either many entries or a
few very long ones — is rejected with 422 (FastAPI/Pydantic validation).
FAIL means it's accepted (201) — which is the case today, since neither cap
exists.

Requires the live stack — skips automatically if no stack is reachable at
SMARTDESK_URL. Bring one up with `docker compose up -d`.
"""
import os
import time

import httpx
import pytest

BASE = os.environ.get("SMARTDESK_URL", "http://localhost:8080")


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


def _create_thread(token: str, media_urls: list[str]):
    return httpx.post(
        f"{BASE}/api/forums/boards/account/threads",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "media flood", "body": "abusive payload", "media_urls": media_urls},
        timeout=30,
    )


def test_thread_rejects_media_urls_list_with_too_many_entries(live_stack):
    token = _register(f"media-count-{int(time.time())}@example.com")
    media_urls = [f"/media/{i}.png" for i in range(10_000)]

    r = _create_thread(token, media_urls)
    assert r.status_code == 422, (
        f"expected a 10,000-entry media_urls list to be rejected (422), got "
        f"{r.status_code}: {r.text[:300]}"
    )


def test_thread_rejects_media_urls_entry_that_is_too_long(live_stack):
    token = _register(f"media-length-{int(time.time())}@example.com")
    media_urls = ["/media/" + ("a" * 500_000) + ".png"]

    r = _create_thread(token, media_urls)
    assert r.status_code == 422, (
        f"expected a single 500,000-char media_urls entry to be rejected "
        f"(422), got {r.status_code}: {r.text[:300]}"
    )
