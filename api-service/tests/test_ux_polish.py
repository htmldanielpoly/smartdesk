"""People, not ids: tickets and comments carry display names, and the
ticket list is paginated with a total count."""
from datetime import datetime

from bson import ObjectId

from app.security import create_access_token
from tests.conftest import auth_header, register


async def _agent(db, name="Dana Levi"):
    result = await db.users.insert_one(
        {"email": "dana@example.com", "passwordHash": "x", "displayName": name,
         "role": "AGENT", "department": None}
    )
    return result.inserted_id, auth_header(create_access_token(str(result.inserted_id), "AGENT"))


async def test_tickets_and_comments_show_display_names(client, db):
    agent_id, agent = await _agent(db)
    token = register(client, "alice@example.com", name="Alice Cohen").json()["access_token"]
    alice = auth_header(token)
    ticket = client.post(
        "/api/tickets", json={"title": "Printer", "description": "jam"}, headers=alice
    ).json()
    assert ticket["created_by_name"] == "Alice Cohen"
    assert ticket["assigned_agent_name"] is None

    assigned = client.post(
        f"/api/tickets/{ticket['id']}/assign", json={"agent_id": str(agent_id)}, headers=agent
    ).json()
    assert assigned["assigned_agent_name"] == "Dana Levi"

    listed = client.get("/api/tickets", headers=agent).json()
    assert listed[0]["created_by_name"] == "Alice Cohen"
    assert listed[0]["assigned_agent_name"] == "Dana Levi"

    posted = client.post(
        f"/api/tickets/{ticket['id']}/comments", json={"body": "On it"}, headers=agent
    ).json()
    assert posted["author_name"] == "Dana Levi"
    comments = client.get(f"/api/tickets/{ticket['id']}/comments", headers=alice).json()
    assert comments[0]["author_name"] == "Dana Levi"


async def test_ai_authored_comments_are_named(client, db):
    _, agent = await _agent(db)
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    tid = client.post(
        "/api/tickets", json={"title": "t", "description": "d"}, headers=alice
    ).json()["id"]
    await db.comments.insert_one(
        {"ticketId": ObjectId(tid), "authorId": None, "authorType": "ai", "body": "Try TCP mode.",
         "internal": False, "createdAt": datetime.now()}
    )
    comments = client.get(f"/api/tickets/{tid}/comments", headers=agent).json()
    assert comments[0]["author_name"] == "SmartDesk AI"
    assert comments[0]["author_id"] is None


def test_ticket_list_is_paginated_with_a_total(client):
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    for i in range(7):
        client.post("/api/tickets", json={"title": f"t{i}", "description": "d"}, headers=alice)

    page1 = client.get("/api/tickets?limit=3", headers=alice)
    assert page1.status_code == 200
    assert page1.headers["X-Total-Count"] == "7"
    assert [t["title"] for t in page1.json()] == ["t6", "t5", "t4"]  # newest first

    page3 = client.get("/api/tickets?limit=3&skip=6", headers=alice)
    assert [t["title"] for t in page3.json()] == ["t0"]

    assert client.get("/api/tickets?limit=0", headers=alice).status_code == 422
    assert client.get("/api/tickets?limit=201", headers=alice).status_code == 422


def test_ticket_list_can_filter_by_status(client):
    alice = auth_header(register(client, "alice@example.com").json()["access_token"])
    open_ticket = client.post(
        "/api/tickets", json={"title": "open", "description": "d"}, headers=alice
    ).json()
    done = client.post(
        "/api/tickets", json={"title": "done", "description": "d"}, headers=alice
    ).json()
    client.patch(f"/api/tickets/{done['id']}", json={"status": "RESOLVED"}, headers=alice)

    r = client.get("/api/tickets?status=RESOLVED", headers=alice)
    assert [t["id"] for t in r.json()] == [done["id"]]
    assert r.headers["X-Total-Count"] == "1"
    r = client.get("/api/tickets?status=OPEN", headers=alice)
    assert [t["id"] for t in r.json()] == [open_ticket["id"]]
    assert client.get("/api/tickets?status=BOGUS", headers=alice).status_code == 422
