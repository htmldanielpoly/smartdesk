from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import TicketStatus


class AISuggestion(BaseModel):
    category: str | None = None
    priority: str | None = None
    department: str | None = None
    status: str = "pending"  # pending | ok | unavailable


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
    ai_suggested: AISuggestion | None = None
    created_at: datetime
    updated_at: datetime
