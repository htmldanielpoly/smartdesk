"""Security test — DM media attachments are served with no access control.

Verifies a real vulnerability: GET /api/forums/media/{filename} (forum-service/
app/routers/forum.py: serve_media) has no auth dependency at all, unlike every
other forum/DM endpoint in the file. Once a filename is known — leaked via a
shared link, browser history, a referrer header, anything — anyone can fetch
it forever, including a DM attachment that was only ever meant for its two
participants. The filename is an unguessable UUID, but that's obscurity, not
access control.

PASS means: fetching a DM attachment's media URL requires (a) being
authenticated at all, and (b) being a participant in that DM.
FAIL means either check is missing — which is the case today: the endpoint
returns 200 to a completely anonymous request, and to any other logged-in
user who was never part of the conversation.

Requires the live stack (real network topology: api-service's proxy +
forum-service's actual upload/media-serving code) — skips automatically if no
stack is reachable at SMARTDESK_URL. Bring one up with `docker compose up -d`.
"""
import base64
import io
import json
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


def _decode_jwt_sub(token: str) -> str:
    """Pull the 'sub' claim out locally, no signature verification needed —
    we trust our own server's token."""
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["sub"]


def _register(email: str) -> tuple[str, str]:
    r = httpx.post(
        f"{BASE}/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    assert r.status_code == 201, f"registration failed: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    return token, _decode_jwt_sub(token)


def test_dm_media_requires_participant(live_stack):
    run_id = str(int(time.time()))
    token_a, _ = _register(f"dm-media-a-{run_id}@example.com")
    token_b, user_b_id = _register(f"dm-media-b-{run_id}@example.com")
    token_c, _ = _register(f"dm-media-c-{run_id}@example.com")

    # User A uploads an attachment and sends it to User B in a DM.
    upload = httpx.post(
        f"{BASE}/api/forums/upload",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("secret.png", io.BytesIO(b"not-a-real-png-but-nonempty"), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    media_url = upload.json()["url"]  # e.g. "/media/<uuid>.png"

    dm = httpx.post(
        f"{BASE}/api/forums/messages",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "recipient_id": user_b_id,
            "content": "here's the file, just for you",
            "media_urls": [media_url],
        },
    )
    assert dm.status_code == 201, dm.text

    media_endpoint = f"{BASE}/api/forums{media_url}"

    # A completely unauthenticated request must be blocked.
    anon = httpx.get(media_endpoint)
    assert anon.status_code in (401, 403), (
        "expected an unauthenticated request for a DM attachment to be "
        f"blocked (401/403), got {anon.status_code} — the file was served "
        "with zero access control"
    )

    # A logged-in user who isn't a participant in this DM must also be blocked.
    outsider = httpx.get(media_endpoint, headers={"Authorization": f"Bearer {token_c}"})
    assert outsider.status_code in (401, 403), (
        "expected a non-participant to be blocked from a DM attachment "
        f"(401/403), got {outsider.status_code} — any authenticated user "
        "can read anyone else's DM attachments"
    )
