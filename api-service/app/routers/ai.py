from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.deps import require_roles
from app.models.enums import Role
from app.schemas.ai import (
    CopilotResponse,
    DuplicateCandidate,
    DuplicatesResponse,
)
from app.services import ai_client

router = APIRouter(prefix="/api/tickets/{ticket_id}/ai", tags=["ai"])


async def _load_ticket(ticket_id: str) -> dict:
    if not ObjectId.is_valid(ticket_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    ticket = await get_db().tickets.find_one({"_id": ObjectId(ticket_id)})
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


@router.post("/copilot", response_model=CopilotResponse)
async def copilot(
    ticket_id: str,
    user: dict = Depends(require_roles(Role.AGENT, Role.ADMIN)),
):
    """Agent-only: AI-drafted solution + response for the agent to review/edit."""
    ticket = await _load_ticket(ticket_id)

    comments = [
        c["body"]
        async for c in get_db().comments.find({"ticketId": ticket["_id"]}).sort("createdAt", 1)
    ]
    ai = await ai_client.copilot(ticket["title"], ticket["description"], comments)
    if ai is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is unavailable. Please respond manually.",
        )
    return CopilotResponse(
        suggested_solution=ai.get("suggested_solution", ""),
        draft_response=ai.get("draft_response", ""),
        source=ai.get("source", "ai"),
        citations=[c for c in ai.get("citations", []) if isinstance(c, str)],
        flags=[f for f in ai.get("flags", []) if isinstance(f, str)],
    )


@router.get("/duplicates", response_model=DuplicatesResponse)
async def duplicates(
    ticket_id: str,
    user: dict = Depends(require_roles(Role.AGENT, Role.ADMIN)),
):
    """Agent-only: flag other tickets that look like the same incident."""
    ticket = await _load_ticket(ticket_id)

    # Candidate pool: other tickets that are not closed.
    candidates = [
        {"ticket_id": str(t["_id"]), "title": t["title"], "description": t["description"]}
        async for t in get_db().tickets.find(
            {"_id": {"$ne": ticket["_id"]}, "status": {"$ne": "CLOSED"}}
        ).limit(200)
    ]

    ai = await ai_client.duplicates(ticket["title"], ticket["description"], candidates)
    if ai is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is unavailable.",
        )
    return DuplicatesResponse(
        candidates=[DuplicateCandidate(**c) for c in ai.get("candidates", [])],
        source=ai.get("source", "ai"),
    )
