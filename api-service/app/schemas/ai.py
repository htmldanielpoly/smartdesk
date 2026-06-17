from pydantic import BaseModel


class CopilotResponse(BaseModel):
    suggested_solution: str
    draft_response: str
    source: str  # "ai" | "fallback"


class DuplicateCandidate(BaseModel):
    ticket_id: str
    similarity: float
    title: str


class DuplicatesResponse(BaseModel):
    candidates: list[DuplicateCandidate]
    source: str  # "ai" | "fallback"
