from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import TicketStatus


class AISuggestion(BaseModel):
    category: str | None = None
    priority: str | None = None
    department: str | None = None
    status: str = "pending"  # pending | ok | unavailable
    source: str | None = None  # "local" (LLM) | "fallback" (rules)
    confidence: float | None = None
    # Guardrail annotations from classification, e.g. ["injection_suspected"]:
    # the ticket text tried to manipulate the AI and was handled by rules.
    flags: list[str] = Field(default_factory=list)


class AutoResolvedInfo(BaseModel):
    """Audit trail of an AI answer from long-term memory."""

    source_ticket_id: str  # the resolved ticket whose answer was reused
    similarity: float
    threshold: float | None = None
    source: str  # "local" (embeddings) | "fallback" (lexical)
    at: datetime
    reopened_at: datetime | None = None  # set when the customer said it did not help


class TicketCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=5000)


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    status: TicketStatus | None = None
    category: str | None = None
    priority: str | None = None
    department: str | None = None
    # Staff only: the answer that resolved the ticket. Remembered and reused
    # by the AI for identical future tickets (long-term memory).
    resolution: str | None = Field(default=None, min_length=1, max_length=5000)


class AssignRequest(BaseModel):
    agent_id: str


class TicketOut(BaseModel):
    id: str
    title: str
    description: str
    status: TicketStatus
    created_by: str
    assigned_agent: str | None = None
    category: str | None = None
    priority: str | None = None
    department: str | None = None
    resolution: str | None = None
    ai_suggested: AISuggestion | None = None
    auto_resolved: AutoResolvedInfo | None = None
    created_at: datetime
    updated_at: datetime
