"""Integration tests — features wired together, exercised through the HTTP API
exactly like a real user would (lecture: Integration testing).

Runs the real api-service app against an in-memory MongoDB via the shared
`client` fixture (../conftest.py) — no Docker, no Mongo, no model files. The
full integration suite also lives per-service; these are representative
examples in the taxonomy layout.
"""


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, email):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "User"},
    )


def test_register_login_create_and_view_ticket(client):
    # 1. sign up
    reg = register(client, "journey@example.com")
    assert reg.status_code == 201
    token = reg.json()["access_token"]

    # 2. sign in
    login = client.post(
        "/api/auth/login",
        json={"email": "journey@example.com", "password": "password123"},
    )
    assert login.status_code == 200 and login.json()["access_token"]

    # 3. open a ticket — AI classification is async, so it comes back "pending"
    created = client.post(
        "/api/tickets",
        json={"title": "Cannot login", "description": "I get a 500 on login"},
        headers=auth(token),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "OPEN"
    assert body["ai_suggested"]["status"] == "pending"

    # 4. read it back
    got = client.get(f"/api/tickets/{body['id']}", headers=auth(token))
    assert got.status_code == 200 and got.json()["id"] == body["id"]


def test_duplicate_registration_is_rejected(client):
    assert register(client, "dupe@example.com").status_code == 201
    assert register(client, "dupe@example.com").status_code == 409


def test_ticket_is_private_to_its_owner(client):
    owner = register(client, "owner@example.com").json()["access_token"]
    ticket_id = client.post(
        "/api/tickets",
        json={"title": "private", "description": "secret details"},
        headers=auth(owner),
    ).json()["id"]

    intruder = register(client, "intruder@example.com").json()["access_token"]
    assert client.get(f"/api/tickets/{ticket_id}", headers=auth(intruder)).status_code == 403
