"""Gateway tests for the forum reverse proxy.

Mounts ONLY the forums router on a fresh FastAPI app (app.main is never
imported) and fakes httpx so no network is involved.
"""
import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.routers import forums


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; records the forwarded request."""

    captured: dict = {}
    response = _FakeResponse(200, {"ok": True})
    error: Exception | None = None

    def __init__(self, *args, **kwargs):
        _FakeAsyncClient.captured["client_kwargs"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kwargs):
        if _FakeAsyncClient.error is not None:
            raise _FakeAsyncClient.error
        _FakeAsyncClient.captured.update({"method": method, "url": url, **kwargs})
        return _FakeAsyncClient.response


@pytest.fixture
def client(monkeypatch):
    _FakeAsyncClient.captured = {}
    _FakeAsyncClient.response = _FakeResponse(200, {"ok": True})
    _FakeAsyncClient.error = None
    monkeypatch.setattr(forums.httpx, "AsyncClient", _FakeAsyncClient)

    app = FastAPI()
    app.include_router(forums.router)
    return TestClient(app)


def test_get_forwards_method_path_query_and_auth(client):
    r = client.get(
        "/api/forums/boards/general/threads?page=2",
        headers={"Authorization": "Bearer some-token"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    captured = _FakeAsyncClient.captured
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/boards/general/threads")
    assert captured["params"] == "page=2"
    assert captured["headers"]["authorization"] == "Bearer some-token"


def test_post_forwards_json_body_and_relays_status(client):
    _FakeAsyncClient.response = _FakeResponse(201, {"id": "abc"})
    r = client.post(
        "/api/forums/boards/general/threads",
        json={"title": "Hi", "body": "First"},
        headers={"Authorization": "Bearer some-token"},
    )
    assert r.status_code == 201
    assert r.json() == {"id": "abc"}

    captured = _FakeAsyncClient.captured
    assert captured["method"] == "POST"
    assert b'"title"' in captured["content"] and b'"Hi"' in captured["content"]
    assert captured["headers"]["content-type"] == "application/json"


def test_delete_and_patch_methods_forwarded(client):
    client.patch(
        "/api/forums/threads/t1",
        json={"locked": True},
        headers={"Authorization": "Bearer some-token"},
    )
    assert _FakeAsyncClient.captured["method"] == "PATCH"
    assert _FakeAsyncClient.captured["url"].endswith("/threads/t1")

    client.delete("/api/forums/posts/p1", headers={"Authorization": "Bearer some-token"})
    assert _FakeAsyncClient.captured["method"] == "DELETE"
    assert _FakeAsyncClient.captured["url"].endswith("/posts/p1")


def test_connection_error_yields_503(client):
    _FakeAsyncClient.error = httpx.ConnectError("connection refused")
    r = client.get("/api/forums/boards", headers={"Authorization": "Bearer some-token"})
    assert r.status_code == 503
    assert r.json() == {"detail": "Forum service is unavailable."}
