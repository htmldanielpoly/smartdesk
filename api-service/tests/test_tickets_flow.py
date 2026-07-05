"""Integration tests over the real app + in-memory Mongo."""
from tests.conftest import auth_header, register


def test_register_and_duplicate_email(client):
    r = register(client, "alice@example.com")
    assert r.status_code == 201
    assert r.json()["role"] == "USER"

    dup = register(client, "alice@example.com")
    assert dup.status_code == 409


def test_login_returns_token(client):
    register(client, "bob@example.com", password="password123")
    r = client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["access_token"]

    bad = client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": "wrong"},
    )
    assert bad.status_code == 401


def test_create_ticket_works_when_ai_unavailable(client):
    token = register(client, "carol@example.com").json()["access_token"]
    r = client.post(
        "/api/tickets",
        json={"title": "Cannot login", "description": "I get a 500 error on login"},
        headers=auth_header(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "OPEN"
    # Classification is asynchronous: the response never waits for the AI.
    assert body["ai_suggested"]["status"] == "pending"

    # The background task has run by now (TestClient executes background
    # tasks before returning) and recorded that the AI was unavailable —
    # core ticketing succeeded anyway.
    r2 = client.get(f"/api/tickets/{body['id']}", headers=auth_header(token))
    assert r2.json()["ai_suggested"]["status"] == "unavailable"


def test_user_cannot_view_others_ticket(client):
    t1 = register(client, "dan@example.com").json()["access_token"]
    ticket_id = client.post(
        "/api/tickets",
        json={"title": "Printer broken", "description": "no output"},
        headers=auth_header(t1),
    ).json()["id"]

    t2 = register(client, "eve@example.com").json()["access_token"]
    r = client.get(f"/api/tickets/{ticket_id}", headers=auth_header(t2))
    assert r.status_code == 403


def test_protected_endpoint_requires_auth(client):
    assert client.get("/api/tickets").status_code == 403  # no bearer token


def test_admin_only_endpoint_forbidden_for_user(client):
    token = register(client, "frank@example.com").json()["access_token"]
    r = client.get("/api/admin/users", headers=auth_header(token))
    assert r.status_code == 403
