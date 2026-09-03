from pydantic import BaseModel, Field


class AssistQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Earlier turns of this chat, oldest first (kept short on purpose).
    conversation: list[str] = Field(default_factory=list, max_length=10)


class AssistAnswer(BaseModel):
    answer: str
    # "memory" | "kb" | "refused" | "no_answer"
    source: str
    citations: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    suggest_ticket: bool = False
    matched_ticket_id: str | None = None
    similarity: float | None = None
