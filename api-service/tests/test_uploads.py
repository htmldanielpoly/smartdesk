"""Media uploads: real type detection, hard size caps enforced while
streaming, serving by unguessable id, and media attached to comments."""
import io

import pytest

from app.config import settings
from tests.conftest import auth_header, register

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _tmp_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "uploads_dir", str(tmp_path / "uploads"))


def _user(client, email="uploader@example.com"):
    return auth_header(register(client, email).json()["access_token"])


def _upload(client, headers, data, name="pic.png", claimed="image/png"):
    return client.post(
        "/api/uploads", files={"file": (name, io.BytesIO(data), claimed)}, headers=headers
    )


def test_requires_authentication(client):
    r = client.post("/api/uploads", files={"file": ("a.png", io.BytesIO(PNG), "image/png")})
    assert r.status_code == 403


def test_png_upload_is_stored_and_served_with_its_real_type(client):
    headers = _user(client)
    r = _upload(client, headers, PNG)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "image" and body["content_type"] == "image/png"
    assert body["size"] == len(PNG)
    assert body["url"].startswith("/uploads/") and len(body["id"]) == 32

    served = client.get(body["url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert served.content == PNG
    assert "immutable" in served.headers["cache-control"]
    assert served.headers["x-content-type-options"] == "nosniff"


def test_type_comes_from_magic_bytes_not_the_claim(client):
    headers = _user(client)
    # Claims PNG, is JPEG -> stored as JPEG.
    r = _upload(client, headers, JPEG, name="x.png", claimed="image/png")
    assert r.status_code == 201 and r.json()["content_type"] == "image/jpeg"
    # Claims PNG, is an executable-looking blob -> refused.
    r = _upload(client, headers, b"MZ\x90\x00" + b"\x00" * 64, name="x.png", claimed="image/png")
    assert r.status_code == 415
    # Plain text / HTML never gets in, whatever it is called.
    r = _upload(client, headers, b"<script>alert(1)</script>", name="x.jpg", claimed="image/jpeg")
    assert r.status_code == 415


def test_video_is_accepted_and_capped_separately(client, monkeypatch):
    monkeypatch.setattr(settings, "max_video_bytes", 2000)
    headers = _user(client)
    r = _upload(client, headers, MP4, name="clip.mp4", claimed="video/mp4")
    assert r.status_code == 201 and r.json()["kind"] == "video"

    huge = MP4 + b"\x00" * 5000
    r = _upload(client, headers, huge, name="huge.mp4", claimed="video/mp4")
    assert r.status_code == 413
    assert "limited to" in r.json()["detail"]


def test_oversized_image_is_rejected_and_nothing_is_left_behind(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "max_image_bytes", 1000)
    headers = _user(client)
    r = _upload(client, headers, PNG + b"\x00" * 5000)
    assert r.status_code == 413
    assert not list((tmp_path / "uploads").glob("*"))
    assert client.get("/uploads/" + "a" * 32).status_code == 404


def test_uploads_bypass_the_json_body_cap_but_not_their_own(client, monkeypatch):
    # The gateway-wide 1 MiB JSON cap must not block a 3 MB image...
    monkeypatch.setattr(settings, "max_request_body_bytes", 10_000)
    monkeypatch.setattr(settings, "max_image_bytes", 5 << 20)
    headers = _user(client)
    r = _upload(client, headers, PNG + b"\x00" * 3_000_000)
    assert r.status_code == 201


def test_uploads_count_against_the_write_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_writes", 2)
    headers = _user(client)
    codes = [_upload(client, headers, PNG).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


def test_unknown_or_malformed_ids_are_404(client):
    assert client.get("/uploads/" + "f" * 32).status_code == 404
    assert client.get("/uploads/..%2F..%2Fetc%2Fpasswd").status_code == 404


# --- media on ticket comments ------------------------------------------------------

def test_comment_can_attach_uploaded_media(client):
    headers = _user(client)
    tid = client.post(
        "/api/tickets", json={"title": "Screen", "description": "see attached"}, headers=headers
    ).json()["id"]
    url = _upload(client, headers, PNG).json()["url"]

    r = client.post(
        f"/api/tickets/{tid}/comments",
        json={"body": "Here is the screenshot", "media_urls": [url]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["media_urls"] == [url]
    listed = client.get(f"/api/tickets/{tid}/comments", headers=headers).json()
    assert listed[0]["media_urls"] == [url]


def test_comment_rejects_media_that_was_not_uploaded_here(client):
    headers = _user(client)
    tid = client.post(
        "/api/tickets", json={"title": "x", "description": "y"}, headers=headers
    ).json()["id"]
    for bad in ["https://evil.example.com/a.png", "/uploads/" + "0" * 32, "javascript:alert(1)"]:
        r = client.post(
            f"/api/tickets/{tid}/comments", json={"body": "x", "media_urls": [bad]}, headers=headers
        )
        assert r.status_code == 422, bad
