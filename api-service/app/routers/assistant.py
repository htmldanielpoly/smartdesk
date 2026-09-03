"""Customer-facing AI assistant.

``POST /api/assistant/ask`` lets any signed-in user ask a support question
before opening a ticket. The gateway offers the AI service the same
long-term memory the auto-resolver uses (recently resolved tickets with
their stored resolutions); the AI answers only from that memory or from the
curated knowledge base, refuses jailbreak/coercion attempts, and says so
when it has nothing documented. The assistant never creates, changes or
closes anything: the customer decides what to do with the answer.
"""
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_current_user
from app.rate_limit import rate_limit_writes
from app.schemas.assistant import AssistAnswer, AssistQuestion
from app.services import ai_client, memory

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/ask", response_model=AssistAnswer)
async def ask(
    payload: AssistQuestion,
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit_writes),
):
    candidates = await memory.memory_candidates(exclude_id=ObjectId())
    ai = await ai_client.assist(payload.question, payload.conversation, candidates)
    if ai is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is unavailable right now. Please open a ticket.",
        )
    match = ai.get("match") or None
    return AssistAnswer(
        answer=ai.get("answer", ""),
        source=ai.get("source", "no_answer"),
        citations=[c for c in ai.get("citations", []) if isinstance(c, str)],
        flags=[f for f in ai.get("flags", []) if isinstance(f, str)],
        suggest_ticket=bool(ai.get("suggest_ticket", False)),
        matched_ticket_id=match.get("ticket_id") if isinstance(match, dict) else None,
        similarity=match.get("similarity") if isinstance(match, dict) else None,
    )
