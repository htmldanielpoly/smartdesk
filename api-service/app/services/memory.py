"""Long-term memory: remember how tickets were resolved and let the AI answer
exact repeats with no human in the loop.

Flow (runs in the background right after a ticket is created, *before*
classification - embeddings are cheap, so a repeat is answered in seconds):

1. Build the memory: recently RESOLVED/CLOSED tickets that carry a stored
   ``resolution``. The resolution is snapshotted from the agent's final
   public reply when a ticket is resolved (routers/tickets.py), from a public
   staff reply posted after resolving (routers/comments.py), or set
   explicitly by staff via ``PATCH /api/tickets/{id}`` ``resolution``.
2. Ask the ai-service (``POST /auto-resolve``) whether the new ticket is a
   near-verbatim repeat of one of them (cosine >= 0.95 by default; the
   ai-service also refuses on suspected prompt injection).
3. If so: atomically take the ticket out of the agent queue - only if it is
   still OPEN and unassigned, so an agent who already claimed it wins - post
   the drafted reply as an AI-authored comment, store the reused resolution
   (the answered ticket becomes memory too) plus an audit trail, and log it.

Everything is best-effort: any failure leaves the ticket in the queue for a
human, exactly as if the feature did not exist. The customer can reopen an
auto-resolved ticket at any time, which sends it to the agent queue.
"""
import logging
from datetime import UTC, datetime

from bson import ObjectId
from pymongo import ReturnDocument

from app.config import settings
from app.database import get_db
from app.models.enums import Role, TicketStatus
from app.services import activity, ai_client

logger = logging.getLogger(__name__)

_RESOLVED_STATUSES = [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]
_STAFF_ROLES = [Role.AGENT.value, Role.ADMIN.value]


async def latest_staff_reply(ticket_id: ObjectId) -> str | None:
    """The most recent public reply written by a human agent/admin, or None.

    Internal notes and AI-authored replies are never used as a resolution:
    the remembered answer must be something a human actually told a customer.
    """
    db = get_db()
    comments = [
        c
        async for c in db.comments.find(
            {"ticketId": ticket_id, "internal": False, "authorType": {"$ne": "ai"}}
        ).sort("createdAt", -1)
    ]
    author_ids = {c["authorId"] for c in comments if c.get("authorId")}
    if not author_ids:
        return None
    staff_ids = {
        u["_id"]
        async for u in db.users.find(
            {"_id": {"$in": list(author_ids)}, "role": {"$in": _STAFF_ROLES}}
        )
    }
    for comment in comments:
        if comment.get("authorId") in staff_ids and comment["body"].strip():
            return comment["body"].strip()
    return None


async def memory_candidates(exclude_id: ObjectId) -> list[dict]:
    """Resolved tickets with a stored resolution, most recently updated first."""
    cursor = (
        get_db()
        .tickets.find(
            {
                "_id": {"$ne": exclude_id},
                "status": {"$in": _RESOLVED_STATUSES},
                "resolution": {"$nin": [None, ""]},
            }
        )
        .sort("updatedAt", -1)
        .limit(settings.auto_resolve_candidate_limit)
    )
    return [
        {
            "ticket_id": str(t["_id"]),
            "title": t["title"],
            "description": t["description"],
            "resolution": t["resolution"],
        }
        async for t in cursor
        if isinstance(t.get("resolution"), str) and t["resolution"].strip()
    ]


async def try_auto_resolve(ticket_id: ObjectId) -> bool:
    """Answer ``ticket_id`` from memory if it repeats a resolved ticket.

    Returns True when the ticket was resolved by the AI, False when it was
    left for a human (no match, AI unavailable, disabled, or an agent got
    there first).
    """
    if not settings.auto_resolve_enabled:
        return False

    db = get_db()
    ticket = await db.tickets.find_one({"_id": ticket_id})
    if (
        ticket is None
        or ticket["status"] != TicketStatus.OPEN.value
        or ticket.get("assignedAgent") is not None
    ):
        return False

    candidates = await memory_candidates(ticket_id)
    if not candidates:
        return False

    ai = await ai_client.auto_resolve(ticket["title"], ticket["description"], candidates)
    if not ai or not ai.get("resolved") or not ai.get("match") or not ai.get("draft_response"):
        return False

    match = ai["match"]
    source = next((c for c in candidates if c["ticket_id"] == match.get("ticket_id")), None)
    if source is None:
        return False

    now = datetime.now(UTC)
    target = TicketStatus.CLOSED if settings.auto_resolve_close_ticket else TicketStatus.RESOLVED
    audit = {
        "sourceTicketId": ObjectId(source["ticket_id"]),
        "similarity": float(match.get("similarity", 0.0)),
        "threshold": ai.get("threshold"),
        "source": ai.get("source", "ai"),
        "at": now,
    }

    # Atomic guard: the ticket must *still* be unclaimed. If an agent picked
    # it from the queue while we were thinking, the human wins and nothing is
    # posted.
    updated = await db.tickets.find_one_and_update(
        {"_id": ticket_id, "status": TicketStatus.OPEN.value, "assignedAgent": None},
        {
            "$set": {
                "status": target.value,
                "resolution": source["resolution"],
                "autoResolved": audit,
                "updatedAt": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        logger.info("Ticket %s was claimed by an agent before auto-resolve; skipping", ticket_id)
        return False

    await db.comments.insert_one(
        {
            "ticketId": ticket_id,
            "authorId": None,
            "authorType": "ai",
            "body": ai["draft_response"],
            "internal": False,
            "createdAt": now,
        }
    )
    await activity.log(
        ticket_id,
        None,
        "auto_resolved",
        source_ticket=source["ticket_id"],
        similarity=audit["similarity"],
        threshold=audit["threshold"],
        source=audit["source"],
        status=target.value,
    )
    logger.info(
        "Ticket %s auto-resolved from %s (similarity %.3f, %s)",
        ticket_id, source["ticket_id"], audit["similarity"], audit["source"],
    )
    return True
