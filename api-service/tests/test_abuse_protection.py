"""Abuse protection: spam throttling metered per user, and oversized bodies
refused at the edge. These are the "1000 messages in a short time" and
"huge file to overload the database" defences from the forum guideline."""
from app import rate_limit
from app.config import settings
from tests.conftest import auth_header, register


def _ticket(client, headers):
    r = client.post(
        "/api/tickets", json={"title": "Spam target", "description": "x"}, headers=headers
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_comment_spam_is_throttled_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_writes", 5)
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    tid = _ticket(client, alice)

    codes = [
        client.post(f"/api/tickets/{tid}/comments", json={"body": f"msg {i}"}, headers=alice)
        .status_code
        for i in range(7)
    ]
    assert codes == [201] * 5 + [429, 429]
    last = client.post(f"/api/tickets/{tid}/comments", json={"body": "again"}, headers=alice)
    assert last.status_code == 429
    assert int(last.headers["Retry-After"]) >= 1
    assert "Rate limit" in last.json()["detail"]

    # Only 5 comments were actually stored.
    assert len(client.get(f"/api/tickets/{tid}/comments", headers=alice).json()) == 5


def test_limits_are_per_user_not_per_address(client, monkeypatch):
    """Every TestClient request comes from the same address; a spammer must
    not lock out the neighbour behind the same NAT."""
    monkeypatch.setattr(settings, "rate_limit_writes", 3)
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    bob = auth_header(register(client, "bob@example.com").json()["access_token"])
    tid_a = _ticket(client, alice)
    tid_b = _ticket(client, bob)

    for _ in range(3):
        client.post(f"/api/tickets/{tid_a}/comments", json={"body": "spam"}, headers=alice)
    blocked = client.post(f"/api/tickets/{tid_a}/comments", json={"body": "spam"}, headers=alice)
    assert blocked.status_code == 429

    ok = client.post(f"/api/tickets/{tid_b}/comments", json={"body": "hello"}, headers=bob)
    assert ok.status_code == 201


def test_unauthenticated_requests_are_metered_per_address(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_requests", 3)
    codes = [
        register(client, f"user{i}@example.com").status_code for i in range(4)
    ]
    assert codes == [201, 201, 201, 429]


def test_write_budget_does_not_consume_the_read_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_writes", 1)
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    tid = _ticket(client, alice)
    client.post(f"/api/tickets/{tid}/comments", json={"body": "one"}, headers=alice)
    assert client.post(
        f"/api/tickets/{tid}/comments", json={"body": "two"}, headers=alice
    ).status_code == 429
    # Reading is still fine: the general budget is separate.
    assert client.get(f"/api/tickets/{tid}/comments", headers=alice).status_code == 200
    assert client.get("/api/tickets", headers=alice).status_code == 200


def test_client_key_prefers_user_id_over_address(client):
    token = register(client, "carol@example.com").json()["access_token"]

    class Req:
        def __init__(self, headers):
            self.headers = headers
            self.client = type("C", (), {"host": "10.0.0.7"})()

    assert rate_limit.client_key(Req({"authorization": f"Bearer {token}"})).startswith("user:")
    assert rate_limit.client_key(Req({})) == "ip:10.0.0.7"
    assert rate_limit.client_key(Req({"authorization": "Bearer not-a-jwt"})) == "ip:10.0.0.7"


def test_forwarded_address_is_only_trusted_when_configured(client, monkeypatch):
    class Req:
        headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.1"})()

    assert rate_limit.client_key(Req()) == "ip:10.0.0.1"
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    assert rate_limit.client_key(Req()) == "ip:203.0.113.9"


def test_oversized_body_is_refused_before_it_is_read(client, monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 10_000)
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    huge = {"title": "big", "description": "A" * 50_000}
    r = client.post("/api/tickets", json=huge, headers=alice)
    assert r.status_code == 413
    assert "too large" in r.json()["detail"]
    # Nothing was created.
    assert client.get("/api/tickets", headers=alice).json() == []


def test_oversized_chunked_body_is_cut_off_while_streaming(client, monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 10_000)
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])

    def chunks():
        for _ in range(20):
            yield b'{"title": "big", "description": "' + b"A" * 1000

    r = client.post(
        "/api/tickets",
        content=chunks(),
        headers={**alice, "content-type": "application/json"},
    )
    assert r.status_code == 413


def test_normal_sized_bodies_are_unaffected(client):
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    r = client.post(
        "/api/tickets",
        json={"title": "ok", "description": "B" * 4_000},
        headers=alice,
    )
    assert r.status_code == 201


def test_idle_keys_are_swept(client, monkeypatch):
    rate_limit.reset()
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    _ticket(client, alice)
    assert any(k.startswith("all:user:") for k in rate_limit._hits)

    # Pretend a full window plus the sweep interval has passed.
    import time as _time

    later = _time.monotonic() + settings.rate_limit_window_seconds + 120
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: later)
    monkeypatch.setattr(rate_limit, "_last_sweep", 0.0)
    rate_limit._check("all", "ip:probe", 100)
    assert not any(k.startswith("all:user:") for k in rate_limit._hits)
