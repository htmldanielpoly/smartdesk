from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import Role, TicketStatus
from app.rate_limit import rate_limit_writes
from app.routers.uploads import upload_exists
from app.schemas.comment import CommentCreate, CommentOut
from app.services import activity
from app.services.serializers import serialize_comment

router = APIRouter(prefix="/api/tickets/{ticket_id}/comments", tags=["comments"])

_DONE = {TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value}


async def _load_ticket(ticket_id: str) -> dict:
    if not ObjectId.is_valid(ticket_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    ticket = await get_db().tickets.find_one({"_id": ObjectId(ticket_id)})
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def _is_staff(user: dict) -> bool:
    return user["role"] in (Role.AGENT.value, Role.ADMIN.value)


@router.get("", response_model=list[CommentOut])
async def list_comments(ticket_id: str, user: dict = Depends(get_current_user)):
    ticket = await _load_ticket(ticket_id)
    is_owner = ticket["createdBy"] == user["_id"]
    if not (_is_staff(user) or is_owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    query: dict = {"ticketId": ticket["_id"]}
    if not _is_staff(user):
        query["internal"] = False  # hide internal agent notes from the owner

    cursor = get_db().comments.find(query).sort("createdAt", 1)
    return [serialize_comment(c) async for c in cursor]


@router.post("", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(
    ticket_id: str,
    payload: CommentCreate,
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit_writes),
):
    ticket = await _load_ticket(ticket_id)
    is_owner = ticket["createdBy"] == user["_id"]
    if not (_is_staff(user) or is_owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    internal = payload.internal and _is_staff(user)  # only staff may post internal notes
    # Media must be something this gateway stored: no external or scripted URLs.
    for url in payload.media_urls:
        if not await upload_exists(url):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="media_urls must reference files uploaded via /api/uploads",
            )
    now = datetime.now(UTC)
    doc = {
        "ticketId": ticket["_id"],
        "authorId": user["_id"],
        "authorType": "user",
        "body": payload.body,
        "internal": internal,
        "mediaUrls": list(dict.fromkeys(payload.media_urls)),
        "createdAt": now,
    }
    result = await get_db().comments.insert_one(doc)
    doc["_id"] = result.inserted_id
    await activity.log(ticket["_id"], user["_id"], "comment_added")

    # A public staff reply on an already-resolved ticket is (the latest
    # version of) its resolution — remember it for identical future tickets.
    if _is_staff(user) and not internal and ticket["status"] in _DONE:
        await get_db().tickets.update_one(
            {"_id": ticket["_id"]},
            {"$set": {"resolution": payload.body.strip(), "updatedAt": now}},
        )
    return serialize_comment(doc)
