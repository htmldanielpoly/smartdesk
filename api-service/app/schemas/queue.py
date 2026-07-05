from datetime import datetime

from pydantic import BaseModel

from app.models.enums import TicketStatus


class QueueEntryOut(BaseModel):
    id: str
    title: str
    status: TicketStatus
    effective_priority: str
    score: float
    sla_deadline: datetime
    sla_breached: bool
    created_at: datetime
    category: str | None = None
    department: str | None = None


class QueueStatsOut(BaseModel):
    total_waiting: int
    breached: int
    by_priority: dict[str, int]
