import logging
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models.enums import Role, TicketStatus, can_transition
from app.rate_limit import rate_limit
from app.schemas.ticket import AssignRequest, TicketCreate, TicketOut, TicketUpdate
from app.services import activity, ai_client, memory
from app.services.names import display_names
from app.services.serializers import serialize_ticket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

_DONE = {TicketStatus.RESOLVED, TicketStatus.CLOSED}


def _oid(ticket_id: str) -> ObjectId:
    if not ObjectId.is_valid(ticket_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ObjectId(ticket_id)


async def _get_ticket_or_404(ticket_id: str) -> dict:
    ticket = await get_db().tickets.find_one({"_id": _oid(ticket_id)})
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def _can_view(ticket: dict, user: dict) -> bool:
    if user["role"] in (Role.AGENT.value, Role.ADMIN.value):
        return True
    return ticket["createdBy"] == user["_id"]


async def _classify_in_background(ticket_id: ObjectId, title: str, description: str) -> None:
    """Best-effort AI classification, run after the response is sent.

    Local LLM inference can take tens of seconds on CPU; the client gets its
    ticket immediately with aiSuggested.status == "pending" and the suggestion
    lands on the document when ready ("ok") or not ("unavailable").
    """
    try:
        ai = await ai_client.classify(title, description)
    except Exception:  # noqa: BLE001 - never leave a ticket stuck at "pending"
        logger.exception("Classification of ticket %s crashed", ticket_id)
        ai = None
    suggestion = {**ai, "status": "ok"} if ai else {"status": "unavailable"}
    await get_db().tickets.update_one(
        {"_id": ticket_id}, {"$set": {"aiSuggested": suggestion}}
    )


async def _process_new_ticket(ticket_id: ObjectId, title: str, description: str) -> None:
    """All AI work for a fresh ticket, after the response is sent.

    Long-term memory runs first (embeddings are cheap, so an exact repeat of
    a resolved ticket is answered within seconds and never reaches the
    queue); classification follows. Each step is independent and
    best-effort.
    """
    try:
        await memory.try_auto_resolve(ticket_id)
    except Exception:  # noqa: BLE001 - a failure here just leaves the ticket for a human
        logger.exception("Auto-resolve of ticket %s crashed", ticket_id)
    await _classify_in_background(ticket_id, title, description)


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit),
):
    now = datetime.now(UTC)
    doc = {
        "title": payload.title,
        "description": payload.description,
        "status": TicketStatus.OPEN.value,
        "createdBy": user["_id"],
        "assignedAgent": None,
        "category": None,
        "priority": None,
        "department": None,
        "resolution": None,
        "aiSuggested": {"status": "pending"},
        "createdAt": now,
        "updatedAt": now,
    }
    result = await get_db().tickets.insert_one(doc)
    doc["_id"] = result.inserted_id

    # Never block ticket creation on AI availability or speed.
    background_tasks.add_task(
        _process_new_ticket, result.inserted_id, payload.title, payload.description
    )

    await activity.log(result.inserted_id, user["_id"], "ticket_created")
    return serialize_ticket(doc, {user["_id"]: user.get("displayName") or user["email"]})


async def _with_names(tickets: list[dict]) -> list[dict]:
    ids = [t["createdBy"] for t in tickets] + [t.get("assignedAgent") for t in tickets]
    names = await display_names(ids)
    return [serialize_ticket(t, names) for t in tickets]


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    response: Response,
    user: dict = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
):
    """Newest first, paginated (``limit``/``skip``); the total number of
    matching tickets is in the ``X-Total-Count`` header. Users see only
    their own tickets; agents and admins see all."""
    query: dict = {}
    if user["role"] == Role.USER.value:
        query["createdBy"] = user["_id"]
    if status_filter is not None:
        query["status"] = status_filter.value

    db = get_db()
    response.headers["X-Total-Count"] = str(await db.tickets.count_documents(query))
    cursor = (
        db.tickets.find(query).sort([("createdAt", -1), ("_id", -1)]).skip(skip).limit(limit)
    )
    return await _with_names([t async for t in cursor])


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    ticket = await _get_ticket_or_404(ticket_id)
    if not _can_view(ticket, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return (await _with_names([ticket]))[0]


@router.patch("/{ticket_id}", response_model=TicketOut)
async def update_ticket(
    ticket_id: str,
    payload: TicketUpdate,
    user: dict = Depends(get_current_user),
):
    ticket = await _get_ticket_or_404(ticket_id)
    is_staff = user["role"] in (Role.AGENT.value, Role.ADMIN.value)
    is_owner = ticket["createdBy"] == user["_id"]
    if not (is_staff or is_owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    updates: dict = {}

    # Owners may edit the text of their own ticket; only staff change metadata.
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.description is not None:
        updates["description"] = payload.description

    staff_fields = (payload.category, payload.priority, payload.department, payload.resolution)
    if any(v is not None for v in staff_fields):
        if not is_staff:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only agents/admins can set ticket metadata",
            )
        for field in ("category", "priority", "department"):
            value = getattr(payload, field)
            if value is not None:
                updates[field] = value
        if payload.resolution is not None:
            # The remembered answer, reused by the AI for identical tickets.
            updates["resolution"] = payload.resolution.strip()

    if payload.status is not None:
        current = TicketStatus(ticket["status"])
        if not can_transition(current, payload.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot move ticket from {current.value} to {payload.status.value}",
            )
        updates["status"] = payload.status.value
        await activity.log(
            ticket["_id"], user["_id"], "status_changed",
            **{"from": current.value, "to": payload.status.value},
        )

        # Resolving: remember the agent's final public reply as the resolution
        # (long-term memory) unless one was given explicitly.
        if (
            is_staff
            and payload.status in _DONE
            and current not in _DONE
            and "resolution" not in updates
        ):
            snapshot = await memory.latest_staff_reply(ticket["_id"])
            if snapshot:
                updates["resolution"] = snapshot

        # Reopening an AI-answered ticket: the remembered answer did not help.
        # Keep the audit trail but mark it, so the ticket reads as "back with
        # a human" and the next resolution is recorded afresh.
        auto = ticket.get("autoResolved")
        reopening = current in _DONE and payload.status not in _DONE
        if reopening and auto and not auto.get("reopenedAt"):
            updates["autoResolved.reopenedAt"] = datetime.now(UTC)
            await activity.log(
                ticket["_id"], user["_id"], "auto_resolution_rejected",
                source_ticket=str(auto.get("sourceTicketId")),
            )

    if updates:
        updates["updatedAt"] = datetime.now(UTC)
        await get_db().tickets.update_one({"_id": ticket["_id"]}, {"$set": updates})

    return (await _with_names([await _get_ticket_or_404(ticket_id)]))[0]


@router.post("/{ticket_id}/assign", response_model=TicketOut)
async def assign_ticket(
    ticket_id: str,
    payload: AssignRequest,
    user: dict = Depends(require_roles(Role.AGENT, Role.ADMIN)),
):
    ticket = await _get_ticket_or_404(ticket_id)

    if not ObjectId.is_valid(payload.agent_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent id")
    agent = await get_db().users.find_one({"_id": ObjectId(payload.agent_id)})
    if agent is None or agent["role"] not in (Role.AGENT.value, Role.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Target is not an agent"
        )

    await get_db().tickets.update_one(
        {"_id": ticket["_id"]},
        {"$set": {"assignedAgent": agent["_id"], "updatedAt": datetime.now(UTC)}},
    )
    await activity.log(ticket["_id"], user["_id"], "assigned", agent=str(agent["_id"]))
    return (await _with_names([await _get_ticket_or_404(ticket_id)]))[0]
