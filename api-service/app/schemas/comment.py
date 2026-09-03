from datetime import datetime

from pydantic import BaseModel, Field


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    internal: bool = False  # agent-only note, hidden from the ticket owner


class CommentOut(BaseModel):
    id: str
    ticket_id: str
    author_id: str | None  # None for AI-authored replies
    author_type: str = "user"  # "user" | "ai"
    body: str
    internal: bool
    created_at: datetime
