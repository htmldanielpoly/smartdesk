"""Integration tests for the incident-overview endpoint.

The clustering call to the ai-service is mocked: one test drives the
embedding-model path (AI returns groups), another the lexical fallback (AI
unavailable). Both run against the real app + in-memory Mongo.
"""
from datetime import UTC, datetime

from bson import ObjectId

from app.security import create_access_token
from app.services import ai_client
from tests.conftest import auth_header, register


async def _seed_agent(db, email="agent@example.com"):
    result = await db.users.insert_one({
        "email": email, "passwordHash": "x", "displayName": "Agent",
        "role": "AGENT", "department": None, "createdAt": datetime.now(UTC),
    })
    return create_access_token(str(result.inserted_id), "AGENT")


async def _seed_ticket(db, title, description, priority=None):
    now = datetime.now(UTC)
    result = await db.tickets.insert_one({
        "title": title, "description": description, "status": "OPEN",
        "createdBy": ObjectId(), "assignedAgent": None, "category": None,
        "priority": priority, "department": None,
        "aiSuggested": {"status": "pending"}, "createdAt": now, "updatedAt": now,
    })
    return str(result.inserted_id)


async def _none(*args, **kwargs):
    return None


def test_overview_requires_staff(client):
    token = register(client, "user@example.com").json()["access_token"]
    assert client.get("/api/incidents", headers=auth_header(token)).status_code == 403
    assert client.get("/api/incidents").status_code == 403  # no token


async def test_overview_lexical_fallback_when_ai_unavailable(client, db, monkeypatch):
    monkeypatch.setattr(ai_client, "cluster", _none)  # AI down -> lexical fallback
    token = await _seed_agent(db)

    for i in range(4):
        await _seed_ticket(db, f"Power outage Westbrook {i}",
                           "no electricity downtown, total blackout", priority="URGENT")
    for i in range(3):
        await _seed_ticket(db, f"Brownout Riverton {i}",
                           "lights flickering, voltage sag since the storm", priority="HIGH")
    await _seed_ticket(db, "Billing question", "my monthly invoice is too high")

    r = client.get("/api/incidents", headers=auth_header(token))
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "fallback"
    assert data["total_complaints"] == 8
    assert data["incident_count"] == 2
    severities = {inc["severity"] for inc in data["incidents"]}
    assert severities == {"URGENT", "HIGH"}
    # URGENT incident is ranked first.
    assert data["incidents"][0]["severity"] == "URGENT"
    # The lone billing ticket is noise, not an incident.
    assert data["noise_count"] == 1


async def test_overview_uses_ai_groups_when_available(client, db, monkeypatch):
    token = await _seed_agent(db)
    westbrook = [await _seed_ticket(db, f"WB {i}", "outage", priority="URGENT") for i in range(3)]
    riverton = [await _seed_ticket(db, f"RV {i}", "brownout", priority="HIGH") for i in range(3)]

    async def fake_cluster(items):
        return {"groups": [westbrook, riverton], "source": "local"}

    monkeypatch.setattr(ai_client, "cluster", fake_cluster)

    r = client.get("/api/incidents", headers=auth_header(token))
    data = r.json()
    assert data["source"] == "local"
    assert data["incident_count"] == 2
    assert data["clustered"] == 6
    assert {inc["report_count"] for inc in data["incidents"]} == {3}


async def test_overview_empty(client, db, monkeypatch):
    monkeypatch.setattr(ai_client, "cluster", _none)
    token = await _seed_agent(db)
    data = client.get("/api/incidents", headers=auth_header(token)).json()
    assert data["total_complaints"] == 0
    assert data["incidents"] == []
