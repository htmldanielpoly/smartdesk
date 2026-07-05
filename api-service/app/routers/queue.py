from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import require_roles
from app.models.enums import Role
from app.schemas.queue import QueueEntryOut, QueueStatsOut
from app.schemas.ticket import TicketOut
from app.services import queueing
from app.services.serializers import serialize_ticket

router = APIRouter(prefix="/api/queue", tags=["queue"])

_staff_only = require_roles(Role.AGENT, Role.ADMIN)


def _serialize_entry(entry: dict) -> dict:
    return {
        "id": str(entry["_id"]),
        "title": entry["title"],
        "status": entry["status"],
        "effective_priority": entry["effective_priority"],
        "score": entry["score"],
        "sla_deadline": entry["sla_deadline"],
        "sla_breached": entry["sla_breached"],
        "created_at": entry["createdAt"],
        "category": entry.get("category"),
        "department": entry.get("department"),
    }


@router.get("", response_model=list[QueueEntryOut])
async def list_queue(user: dict = Depends(_staff_only)):
    """Ranked queue of unassigned tickets (highest score first)."""
    return [_serialize_entry(e) for e in await queueing.get_queue()]


@router.get("/stats", response_model=QueueStatsOut)
async def queue_stats(user: dict = Depends(_staff_only)):
    entries = await queueing.get_queue()
    by_priority: dict[str, int] = {}
    for entry in entries:
        by_priority[entry["effective_priority"]] = (
            by_priority.get(entry["effective_priority"], 0) + 1
        )
    return {
        "total_waiting": len(entries),
        "breached": sum(1 for e in entries if e["sla_breached"]),
        "by_priority": by_priority,
    }


@router.post("/claim", response_model=TicketOut)
async def claim_next_ticket(user: dict = Depends(_staff_only)):
    """Claim the highest-scored ticket for the calling agent (race-safe)."""
    ticket = await queueing.claim_next(user["_id"])
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue is empty")
    return serialize_ticket(ticket)
