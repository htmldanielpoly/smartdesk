"""API + concurrency tests for the queue router.

The queue router is not yet wired into ``app.main`` (the orchestrator does
that), so these tests mount it on a standalone FastAPI app. The db fixture
from conftest.py injects an in-memory mongomock database via
``database.set_db``, exactly like the main integration tests.
"""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers import queue as queue_router
from app.security import create_access_token
from app.services import queueing

NOW = datetime.now(UTC)


@pytest.fixture
def queue_app(db):
    """Standalone app containing ONLY the queue router (app.main untouched)."""
    app = FastAPI()
    app.include_router(queue_router.router)
    return app


@pytest.fixture
async def client(queue_app):
    transport = ASGITransport(app=queue_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def make_user(db, email, role="AGENT"):
    """Insert a user directly and mint a matching JWT."""
    result = await db.users.insert_one(
        {
            "email": email,
            "passwordHash": "irrelevant",
            "displayName": email.split("@")[0],
            "role": role,
            "department": None,
            "createdAt": NOW,
        }
    )
    token = create_access_token(str(result.inserted_id), role)
    return result.inserted_id, token


async def make_ticket(db, title, priority=None, ai_priority=None, age_hours=0.0,
                      status="OPEN", assigned=None):
    doc = {
        "title": title,
        "description": "desc",
        "status": status,
        "createdBy": ObjectId(),
        "assignedAgent": assigned,
        "category": None,
        "priority": priority,
        "department": None,
        "aiSuggested": {"priority": ai_priority, "status": "ok"},
        "createdAt": NOW - timedelta(hours=age_hours),
        "updatedAt": NOW - timedelta(hours=age_hours),
    }
    result = await db.tickets.insert_one(doc)
    return result.inserted_id


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_user_role_gets_403(db, client):
    _, token = await make_user(db, "user@example.com", role="USER")
    assert (await client.get("/api/queue", headers=auth(token))).status_code == 403
    assert (await client.get("/api/queue/stats", headers=auth(token))).status_code == 403
    assert (await client.post("/api/queue/claim", headers=auth(token))).status_code == 403


async def test_agent_sees_ranked_queue(db, client):
    _, token = await make_user(db, "agent@example.com")

    low = await make_ticket(db, "low", priority="LOW")
    urgent = await make_ticket(db, "urgent", priority="URGENT")
    medium = await make_ticket(db, "medium", ai_priority="MEDIUM")  # AI fallback
    # Assigned / closed tickets never appear in the queue.
    await make_ticket(db, "taken", priority="URGENT", assigned=ObjectId())
    await make_ticket(db, "done", priority="URGENT", status="CLOSED")

    r = await client.get("/api/queue", headers=auth(token))
    assert r.status_code == 200
    entries = r.json()
    assert [e["id"] for e in entries] == [str(urgent), str(medium), str(low)]
    scores = [e["score"] for e in entries]
    assert scores == sorted(scores, reverse=True)
    assert entries[0]["effective_priority"] == "URGENT"
    assert entries[1]["effective_priority"] == "MEDIUM"


async def test_queue_stats(db, client):
    _, token = await make_user(db, "agent2@example.com")

    await make_ticket(db, "u", priority="URGENT")
    await make_ticket(db, "u-breached", priority="URGENT", age_hours=5)  # SLA 4h
    await make_ticket(db, "l", priority="LOW")

    r = await client.get("/api/queue/stats", headers=auth(token))
    assert r.status_code == 200
    stats = r.json()
    assert stats["total_waiting"] == 3
    assert stats["breached"] == 1
    assert stats["by_priority"] == {"URGENT": 2, "LOW": 1}


async def test_claim_assigns_to_caller_and_removes_from_queue(db, client):
    agent_id, token = await make_user(db, "claimer@example.com")

    top = await make_ticket(db, "top", priority="URGENT")
    rest = await make_ticket(db, "rest", priority="LOW")

    r = await client.post("/api/queue/claim", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(top)
    assert body["assigned_agent"] == str(agent_id)

    # The claimed ticket is gone from the queue; the other remains.
    queue = (await client.get("/api/queue", headers=auth(token))).json()
    assert [e["id"] for e in queue] == [str(rest)]

    # An activity log entry records the claim.
    log = await db.activity_log.find_one({"ticketId": top})
    assert log is not None
    assert log["action"] == "claimed_from_queue"
    assert log["actorId"] == agent_id


async def test_claim_on_empty_queue_returns_404(db, client):
    _, token = await make_user(db, "idle@example.com")
    r = await client.post("/api/queue/claim", headers=auth(token))
    assert r.status_code == 404
    assert r.json() == {"detail": "Queue is empty"}


async def test_concurrent_claims_never_double_assign(db):
    """Concurrency stress test (course: parallel programming / race conditions).

    A naive "read the top ticket, then write assignedAgent" implementation
    has a check-then-act race: two agents claiming at the same time can both
    read the same top ticket and both assign it. ``claim_next`` avoids this
    with an atomic ``find_one_and_update`` that re-checks
    ``assignedAgent: None`` in its filter — the filter and update apply to a
    single document atomically, so exactly one concurrent claimer wins each
    ticket and the losers fall through to the next candidate.

    Here 8 agents hammer the queue concurrently (asyncio.gather), round
    after round, until it is empty; every ticket must end up assigned to
    exactly one agent, with no double assignments and no lost tickets.
    """
    n_tickets, n_agents = 20, 8
    ticket_ids = set()
    for i in range(n_tickets):
        priority = ["URGENT", "HIGH", "MEDIUM", "LOW"][i % 4]
        ticket_ids.add(await make_ticket(db, f"t{i}", priority=priority, age_hours=i))

    agent_ids = [ObjectId() for _ in range(n_agents)]

    claims: list[tuple[ObjectId, dict]] = []  # (agent_id, claimed ticket doc)
    while True:
        results = await asyncio.gather(
            *(queueing.claim_next(agent_id) for agent_id in agent_ids)
        )
        round_claims = [(a, t) for a, t in zip(agent_ids, results, strict=False) if t is not None]
        claims.extend(round_claims)
        if not round_claims:  # a full round of Nones -> queue drained
            break

    # Every ticket was claimed exactly once — no double assignment, no loss.
    claimed_ids = [t["_id"] for _, t in claims]
    assert len(claimed_ids) == n_tickets
    assert len(set(claimed_ids)) == n_tickets
    assert set(claimed_ids) == ticket_ids

    # The database agrees with what each claimer was told it won.
    for agent_id, ticket in claims:
        stored = await db.tickets.find_one({"_id": ticket["_id"]})
        assert stored["assignedAgent"] == agent_id

    # Queue is empty and further claims yield nothing.
    assert await queueing.get_queue() == []
    assert await queueing.claim_next(agent_ids[0]) is None

    # One activity log entry per successful claim, never more.
    n_logs = await db.activity_log.count_documents({"action": "claimed_from_queue"})
    assert n_logs == n_tickets
