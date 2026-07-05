"""Smart ticket queueing: priority scoring, SLA aging, and race-safe claiming.

Design
------
Every unassigned OPEN/IN_PROGRESS ticket gets a numeric *score*:

    score = PRIORITY_WEIGHT[priority]
          + age_hours * AGING_POINTS_PER_HOUR
          + (SLA_BREACH_BONUS if past its SLA deadline)

* The base weight orders tickets by effective priority (agent-set priority
  wins over the AI suggestion, with a safe MEDIUM fallback).
* Aging means waiting tickets steadily gain score, so LOW tickets cannot
  starve forever behind a stream of fresh MEDIUM ones.
* Tickets that breach their SLA deadline get a large bonus and jump the
  queue outright.

Claiming and race-condition safety (parallel-programming showcase)
------------------------------------------------------------------
Multiple agents may press "claim next ticket" at the same instant. A naive
read-then-write ("find the top ticket, then set assignedAgent") has a
time-of-check-to-time-of-use race: two agents can both read the same top
ticket and both assign it. ``claim_next`` instead uses *optimistic
concurrency*: it ranks candidates, then attempts an **atomic**
``find_one_and_update`` whose filter re-checks ``assignedAgent is None``.
MongoDB executes filter+update as one indivisible operation on a single
document, so exactly one concurrent claimer can win each ticket; losers
simply move on to the next candidate. No locks required.
"""
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from pymongo import ReturnDocument

from app.database import get_db
from app.services import activity

# Hours an agent has to pick up a ticket before its SLA is breached.
SLA_HOURS = {"URGENT": 4, "HIGH": 24, "MEDIUM": 72, "LOW": 168}

# Base score contribution per priority level.
PRIORITY_WEIGHT = {"URGENT": 100, "HIGH": 60, "MEDIUM": 30, "LOW": 10}

# Waiting tickets gain score over time so LOW tickets can't starve forever.
AGING_POINTS_PER_HOUR = 2.0

# Tickets past their SLA deadline jump the queue.
SLA_BREACH_BONUS = 500.0

_VALID_PRIORITIES = set(PRIORITY_WEIGHT)
_QUEUEABLE_STATUSES = ["OPEN", "IN_PROGRESS"]


def _as_utc(dt: datetime) -> datetime:
    """Normalize a datetime to aware UTC.

    Mongo drivers commonly return naive datetimes that are UTC by
    convention; treat naive values as UTC rather than local time.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def effective_priority(ticket: dict) -> str:
    """Resolve the priority used for scoring.

    Agent-set ``priority`` wins; otherwise fall back to the AI suggestion;
    otherwise MEDIUM. Values are validated against the known set — stored
    strings are never trusted blindly (junk/unknown values -> MEDIUM).
    """
    agent_set = ticket.get("priority")
    if agent_set in _VALID_PRIORITIES:
        return agent_set

    ai = ticket.get("aiSuggested") or {}
    suggested = ai.get("priority")
    if suggested in _VALID_PRIORITIES:
        return suggested

    return "MEDIUM"


def sla_deadline(ticket: dict, priority: str) -> datetime:
    """Deadline by which the ticket should be picked up (createdAt + SLA)."""
    created = _as_utc(ticket["createdAt"])
    return created + timedelta(hours=SLA_HOURS[priority])


def priority_score(ticket: dict, now: datetime) -> float:
    """Compute the ranking score for a ticket at time ``now``."""
    priority = effective_priority(ticket)
    created = _as_utc(ticket["createdAt"])
    age_hours = max((now - created).total_seconds(), 0.0) / 3600.0

    score = PRIORITY_WEIGHT[priority] + age_hours * AGING_POINTS_PER_HOUR
    if now > sla_deadline(ticket, priority):
        score += SLA_BREACH_BONUS
    return score


def build_queue_entry(ticket: dict, now: datetime) -> dict:
    """Return the ticket enriched with queue metadata (score, SLA, ...)."""
    priority = effective_priority(ticket)
    deadline = sla_deadline(ticket, priority)
    return {
        **ticket,
        "score": priority_score(ticket, now),
        "effective_priority": priority,
        "sla_deadline": deadline,
        "sla_breached": now > deadline,
        "waiting": ticket.get("assignedAgent") is None,
    }


async def get_queue(now: datetime | None = None) -> list[dict]:
    """All claimable tickets (OPEN/IN_PROGRESS, unassigned), ranked by score.

    Scoring and sorting happen in Python rather than in an aggregation
    pipeline: it keeps the logic unit-testable, works with mongomock in
    tests, and is perfectly fine at course scale (hundreds of tickets).
    """
    if now is None:
        now = datetime.now(UTC)

    cursor = get_db().tickets.find(
        {"status": {"$in": _QUEUEABLE_STATUSES}, "assignedAgent": None}
    )
    entries = [build_queue_entry(t, now) async for t in cursor]
    entries.sort(key=lambda e: e["score"], reverse=True)
    return entries


async def claim_next(agent_id: ObjectId) -> dict | None:
    """Atomically claim the highest-scored ticket for ``agent_id``.

    Optimistic-concurrency loop: rank the queue, then walk candidates in
    order attempting an atomic ``find_one_and_update`` whose filter
    re-checks that the ticket is *still* unassigned and claimable. Because
    MongoDB applies the filter and the update to a single document
    atomically, two concurrent claimers can never both match the
    ``assignedAgent: None`` condition for the same ticket — exactly one
    wins, the other gets ``None`` back and retries on the next candidate.
    This guarantees no double assignment without any explicit locking.

    Returns the claimed ticket document (post-update), or ``None`` if the
    queue is empty / every candidate was snatched by concurrent claimers.
    """
    now = datetime.now(UTC)
    ranked = await get_queue(now)

    for candidate in ranked:
        claimed = await get_db().tickets.find_one_and_update(
            {
                "_id": candidate["_id"],
                "assignedAgent": None,
                "status": {"$in": _QUEUEABLE_STATUSES},
            },
            {"$set": {"assignedAgent": agent_id, "updatedAt": now}},
            return_document=ReturnDocument.AFTER,
        )
        if claimed is not None:
            await activity.log(claimed["_id"], agent_id, "claimed_from_queue")
            return claimed
        # Another agent won the race for this ticket; try the next one.

    return None
