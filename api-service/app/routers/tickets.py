from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models.enums import Role, TicketStatus, can_transition
from app.rate_limit import rate_limit
from app.schemas.ticket import AssignRequest, TicketCreate, TicketOut, TicketUpdate
from app.services import activity, ai_client
from app.services.serializers import serialize_ticket

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


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


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit),
):
    now = datetime.now(timezone.utc)
    doc = {
        "title": payload.title,
        "description": payload.description,
        "status": TicketStatus.OPEN.value,
        "createdBy": user["_id"],
        "assignedAgent": None,
        "category": None,
        "priority": None,
        "department": None,
        "aiSuggested": {"status": "pending"},
        "createdAt": now,
        "updatedAt": now,
    }
    result = await get_db().tickets.insert_one(doc)
    doc["_id"] = result.inserted_id

    # Best-effort AI classification. Never blocks ticket creation success.
    ai = await ai_client.classify(payload.title, payload.description)
    suggestion = (
        {**ai, "status": "ok"}
        if ai
        else {"status": "unavailable"}
    )
    await get_db().tickets.update_one(
        {"_id": result.inserted_id}, {"$set": {"aiSuggested": suggestion}}
    )
    doc["aiSuggested"] = suggestion

    await activity.log(result.inserted_id, user["_id"], "ticket_created")
    return serialize_ticket(doc)


@router.get("", response_model=list[TicketOut])
async def list_tickets(user: dict = Depends(get_current_user)):
    # Users see only their own tickets; agents and admins see all.
    query: dict = {}
    if user["role"] == Role.USER.value:
        query["createdBy"] = user["_id"]

    cursor = get_db().tickets.find(query).sort("createdAt", -1)
    return [serialize_ticket(t) async for t in cursor]


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    ticket = await _get_ticket_or_404(ticket_id)
    if not _can_view(ticket, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return serialize_ticket(ticket)


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

    if any(v is not None for v in (payload.category, payload.priority, payload.department)):
        if not is_staff:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only agents/admins can set ticket metadata",
            )
        for field in ("category", "priority", "department"):
            value = getattr(payload, field)
            if value is not None:
                updates[field] = value

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

    if updates:
        updates["updatedAt"] = datetime.now(timezone.utc)
        await get_db().tickets.update_one({"_id": ticket["_id"]}, {"$set": updates})

    return serialize_ticket(await _get_ticket_or_404(ticket_id))


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target is not an agent")

    await get_db().tickets.update_one(
        {"_id": ticket["_id"]},
        {"$set": {"assignedAgent": agent["_id"], "updatedAt": datetime.now(timezone.utc)}},
    )
    await activity.log(ticket["_id"], user["_id"], "assigned", agent=str(agent["_id"]))
    return serialize_ticket(await _get_ticket_or_404(ticket_id))
