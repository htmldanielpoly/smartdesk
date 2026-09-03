"""Integration tests for long-term memory (automated resolution).

Once an agent has resolved a ticket, an identical ticket from another client
is answered by the AI with no human in the loop. These run over the real app
and an in-memory Mongo; the ai-service is faked so we exercise the
orchestration: what memory is offered to the AI, what happens on a match,
the race with agents, and the customer's reopen path.
"""
import pytest

from app.config import settings
from app.security import create_access_token
from app.services import ai_client
from tests.conftest import auth_header, register

VPN = {
    "title": "VPN will not connect",
    "description": "The corporate VPN client fails to connect since this morning",
}
SOLUTION = "Switch the VPN client to TCP mode under Settings > Protocol and reconnect."


def _fake_ai(resolved=True, similarity=0.99):
    """Stand-in for the ai-service /auto-resolve call.

    Records every request and, when ``resolved``, matches the first
    candidate offered (the api-service orders memory newest-first)."""
    calls = []

    async def fake(title, description, candidates):
        calls.append({"title": title, "description": description, "candidates": candidates})
        if resolved and candidates:
            best = candidates[0]
            return {
                "resolved": True,
                "match": {
                    "ticket_id": best["ticket_id"],
                    "title": best["title"],
                    "similarity": similarity,
                },
                "draft_response": (
                    "Hi,\n\nHere is the solution that worked:\n\n"
                    f"{best['resolution']}\n\nReopen the ticket if this does not help."
                ),
                "threshold": 0.95,
                "source": "local",
                "flags": [],
            }
        return {
            "resolved": False, "match": None, "draft_response": None,
            "threshold": 0.95, "source": "local", "flags": ["below_threshold"],
        }

    fake.calls = calls
    return fake


@pytest.fixture
async def agent(db):
    """Auth header of an AGENT (inserted directly, JWT minted locally)."""
    result = await db.users.insert_one(
        {
            "email": "agent@example.com", "passwordHash": "x", "displayName": "Agent",
            "role": "AGENT", "department": None,
        }
    )
    return auth_header(create_access_token(str(result.inserted_id), "AGENT"))


def _user(client, email):
    return auth_header(register(client, email).json()["access_token"])


def _create(client, headers, **overrides):
    r = client.post("/api/tickets", json={**VPN, **overrides}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _resolved_by_agent(client, agent, owner_headers):
    """The canonical way memory is formed: agent replies publicly, then resolves."""
    ticket = _create(client, owner_headers)
    r = client.post(
        f"/api/tickets/{ticket['id']}/comments", json={"body": SOLUTION}, headers=agent
    )
    assert r.status_code == 201
    r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "RESOLVED"}, headers=agent)
    assert r.status_code == 200, r.text
    return r.json()


# --- forming the memory --------------------------------------------------------

def test_resolving_snapshots_the_agents_last_public_reply(client, agent):
    alice = _user(client, "alice@example.com")
    ticket = _create(client, alice)
    tid = ticket["id"]

    client.post(f"/api/tickets/{tid}/comments", json={"body": "Looking into it."}, headers=agent)
    client.post(f"/api/tickets/{tid}/comments", json={"body": SOLUTION}, headers=agent)
    # Internal notes and the customer's own messages are never the resolution.
    client.post(
        f"/api/tickets/{tid}/comments",
        json={"body": "customer is on the old client", "internal": True},
        headers=agent,
    )
    client.post(f"/api/tickets/{tid}/comments", json={"body": "thanks!!"}, headers=alice)

    r = client.patch(f"/api/tickets/{tid}", json={"status": "RESOLVED"}, headers=agent)
    assert r.status_code == 200
    assert r.json()["resolution"] == SOLUTION


def test_public_staff_reply_after_resolving_becomes_the_resolution(client, agent):
    """Agents sometimes resolve first and write the answer afterwards."""
    bob = _user(client, "bob@example.com")
    tid = _create(client, bob)["id"]

    r = client.patch(f"/api/tickets/{tid}", json={"status": "RESOLVED"}, headers=agent)
    assert r.json()["resolution"] is None  # nothing to remember yet

    client.post(f"/api/tickets/{tid}/comments", json={"body": SOLUTION}, headers=agent)
    assert client.get(f"/api/tickets/{tid}", headers=agent).json()["resolution"] == SOLUTION


def test_explicit_resolution_is_staff_only(client, agent):
    carol = _user(client, "carol@example.com")
    tid = _create(client, carol)["id"]

    denied = client.patch(f"/api/tickets/{tid}", json={"resolution": "I fixed it"}, headers=carol)
    assert denied.status_code == 403

    r = client.patch(
        f"/api/tickets/{tid}", json={"status": "RESOLVED", "resolution": SOLUTION}, headers=agent
    )
    assert r.status_code == 200
    assert r.json()["resolution"] == SOLUTION


def test_customer_resolving_own_ticket_is_not_remembered(client):
    """A customer's own words are not a trusted answer for other customers."""
    dan = _user(client, "dan@example.com")
    tid = _create(client, dan)["id"]
    client.post(f"/api/tickets/{tid}/comments", json={"body": "never mind"}, headers=dan)
    r = client.patch(f"/api/tickets/{tid}", json={"status": "RESOLVED"}, headers=dan)
    assert r.status_code == 200
    assert r.json()["resolution"] is None


# --- answering from memory ----------------------------------------------------

def test_identical_ticket_is_answered_by_the_ai_without_an_agent(client, agent, monkeypatch):
    alice = _user(client, "alice@example.com")
    original = _resolved_by_agent(client, agent, alice)

    fake = _fake_ai()
    monkeypatch.setattr(ai_client, "auto_resolve", fake)

    # A different client submits the exact same problem.
    eve = _user(client, "eve@example.com")
    created = _create(client, eve)
    # The response itself never waits for the AI...
    assert created["status"] == "OPEN"

    # ...but the background task has run by the time TestClient returns.
    ticket = client.get(f"/api/tickets/{created['id']}", headers=eve).json()
    assert ticket["status"] == "RESOLVED"
    assert ticket["assigned_agent"] is None
    assert ticket["resolution"] == SOLUTION
    assert ticket["auto_resolved"]["source_ticket_id"] == original["id"]
    assert ticket["auto_resolved"]["similarity"] == 0.99
    assert ticket["auto_resolved"]["reopened_at"] is None

    # The customer got a reply, authored by the AI, containing the solution.
    comments = client.get(f"/api/tickets/{created['id']}/comments", headers=eve).json()
    assert len(comments) == 1
    assert comments[0]["author_type"] == "ai"
    assert comments[0]["author_id"] is None
    assert SOLUTION in comments[0]["body"]

    # It never reached the agent queue.
    queue = client.get("/api/queue", headers=agent).json()
    assert created["id"] not in {q["id"] for q in queue}

    # The AI was only offered real memory: the resolved ticket with its answer.
    assert len(fake.calls) == 1
    offered = fake.calls[0]["candidates"]
    assert [c["ticket_id"] for c in offered] == [original["id"]]
    assert offered[0]["resolution"] == SOLUTION


async def test_auto_resolution_is_logged_as_a_system_action(client, agent, db, monkeypatch):
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    monkeypatch.setattr(ai_client, "auto_resolve", _fake_ai())

    created = _create(client, _user(client, "eve@example.com"))
    entries = [
        e async for e in db.activity_log.find({"action": "auto_resolved"})
    ]
    assert len(entries) == 1
    assert str(entries[0]["ticketId"]) == created["id"]
    assert entries[0]["actorId"] is None  # no human in the loop
    assert entries[0]["details"]["similarity"] == 0.99


def test_answered_tickets_become_memory_too(client, agent, monkeypatch):
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    fake = _fake_ai()
    monkeypatch.setattr(ai_client, "auto_resolve", fake)

    second = _create(client, _user(client, "eve@example.com"))
    _create(client, _user(client, "frank@example.com"))

    offered = {c["ticket_id"] for c in fake.calls[1]["candidates"]}
    assert second["id"] in offered
    assert all(c["resolution"] == SOLUTION for c in fake.calls[1]["candidates"])


def test_no_match_leaves_the_ticket_for_a_human(client, agent, monkeypatch):
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    monkeypatch.setattr(ai_client, "auto_resolve", _fake_ai(resolved=False))

    eve = _user(client, "eve@example.com")
    created = _create(client, eve, title="Printer jam", description="paper stuck in tray 2")

    ticket = client.get(f"/api/tickets/{created['id']}", headers=eve).json()
    assert ticket["status"] == "OPEN"
    assert ticket["auto_resolved"] is None
    assert client.get(f"/api/tickets/{created['id']}/comments", headers=eve).json() == []
    assert created["id"] in {q["id"] for q in client.get("/api/queue", headers=agent).json()}


def test_ai_unavailable_leaves_the_ticket_for_a_human(client, agent):
    # conftest patches ai_client.auto_resolve to return None (service down).
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    eve = _user(client, "eve@example.com")
    created = _create(client, eve)
    assert client.get(f"/api/tickets/{created['id']}", headers=eve).json()["status"] == "OPEN"


def test_resolved_tickets_without_an_answer_are_not_memory(client, agent, monkeypatch):
    """Resolved-but-never-answered tickets cannot answer anyone."""
    alice = _user(client, "alice@example.com")
    tid = _create(client, alice)["id"]
    client.patch(f"/api/tickets/{tid}", json={"status": "RESOLVED"}, headers=agent)

    fake = _fake_ai()
    monkeypatch.setattr(ai_client, "auto_resolve", fake)
    eve = _user(client, "eve@example.com")
    created = _create(client, eve)

    assert fake.calls == []  # nothing to offer, the AI is not even asked
    assert client.get(f"/api/tickets/{created['id']}", headers=eve).json()["status"] == "OPEN"


def test_can_be_disabled_by_configuration(client, agent, monkeypatch):
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    fake = _fake_ai()
    monkeypatch.setattr(ai_client, "auto_resolve", fake)
    monkeypatch.setattr(settings, "auto_resolve_enabled", False)

    eve = _user(client, "eve@example.com")
    created = _create(client, eve)
    assert fake.calls == []
    assert client.get(f"/api/tickets/{created['id']}", headers=eve).json()["status"] == "OPEN"


def test_can_close_outright_by_configuration(client, agent, monkeypatch):
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    monkeypatch.setattr(ai_client, "auto_resolve", _fake_ai())
    monkeypatch.setattr(settings, "auto_resolve_close_ticket", True)

    eve = _user(client, "eve@example.com")
    created = _create(client, eve)
    assert client.get(f"/api/tickets/{created['id']}", headers=eve).json()["status"] == "CLOSED"


# --- races and the human override --------------------------------------------

async def test_agent_who_claims_first_wins_the_race(client, agent, db, monkeypatch):
    """If an agent grabs the ticket while the AI is thinking, the AI backs off."""
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    agent_doc = await db.users.find_one({"email": "agent@example.com"})

    inner = _fake_ai()

    async def slow_ai_with_concurrent_claim(title, description, candidates):
        # Simulate an agent claiming the ticket during the AI round-trip.
        await db.tickets.update_one(
            {"title": title, "status": "OPEN", "assignedAgent": None},
            {"$set": {"assignedAgent": agent_doc["_id"]}},
        )
        return await inner(title, description, candidates)

    monkeypatch.setattr(ai_client, "auto_resolve", slow_ai_with_concurrent_claim)

    eve = _user(client, "eve@example.com")
    created = _create(client, eve)
    ticket = client.get(f"/api/tickets/{created['id']}", headers=eve).json()
    assert ticket["status"] == "OPEN"
    assert ticket["assigned_agent"] == str(agent_doc["_id"])
    assert ticket["auto_resolved"] is None
    assert client.get(f"/api/tickets/{created['id']}/comments", headers=eve).json() == []


def test_customer_can_reopen_and_the_ticket_goes_to_the_queue(client, agent, monkeypatch):
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    monkeypatch.setattr(ai_client, "auto_resolve", _fake_ai())

    eve = _user(client, "eve@example.com")
    created = _create(client, eve)
    assert client.get(f"/api/tickets/{created['id']}", headers=eve).json()["status"] == "RESOLVED"

    # "This didn't help" -> back to a human.
    r = client.patch(f"/api/tickets/{created['id']}", json={"status": "IN_PROGRESS"}, headers=eve)
    assert r.status_code == 200
    ticket = r.json()
    assert ticket["status"] == "IN_PROGRESS"
    assert ticket["auto_resolved"]["reopened_at"] is not None
    assert created["id"] in {q["id"] for q in client.get("/api/queue", headers=agent).json()}

    # An agent then resolves it for real; the fresh human answer is remembered.
    better = "Reinstall the VPN client from the portal, version 5.2 or newer."
    client.post(f"/api/tickets/{created['id']}/comments", json={"body": better}, headers=agent)
    r = client.patch(f"/api/tickets/{created['id']}", json={"status": "RESOLVED"}, headers=agent)
    assert r.json()["resolution"] == better


def test_customer_can_confirm_the_ai_answer_by_closing(client, agent, monkeypatch):
    alice = _user(client, "alice@example.com")
    _resolved_by_agent(client, agent, alice)
    monkeypatch.setattr(ai_client, "auto_resolve", _fake_ai())

    eve = _user(client, "eve@example.com")
    created = _create(client, eve)
    r = client.patch(f"/api/tickets/{created['id']}", json={"status": "CLOSED"}, headers=eve)
    assert r.status_code == 200
    assert r.json()["status"] == "CLOSED"
    assert r.json()["auto_resolved"]["reopened_at"] is None
