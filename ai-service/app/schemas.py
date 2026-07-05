from pydantic import BaseModel, Field


class ClassifyRequest(BaseModel):
    title: str
    description: str


class ClassifyResponse(BaseModel):
    category: str
    priority: str
    department: str
    confidence: float
    source: str  # "local" | "fallback"
    # Guardrail annotations, e.g. ["injection_suspected"].
    flags: list[str] = Field(default_factory=list)


class CopilotRequest(BaseModel):
    title: str
    description: str
    conversation: list[str] = Field(default_factory=list)


class CopilotResponse(BaseModel):
    suggested_solution: str
    draft_response: str
    source: str  # "local" | "fallback"
    # KB article ids the answer is grounded in (empty for template fallbacks).
    citations: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class DuplicateInput(BaseModel):
    ticket_id: str
    title: str
    description: str


class DuplicatesRequest(BaseModel):
    title: str
    description: str
    candidates: list[DuplicateInput] = Field(default_factory=list)


class DuplicateCandidate(BaseModel):
    ticket_id: str
    title: str
    similarity: float


class DuplicatesResponse(BaseModel):
    candidates: list[DuplicateCandidate]
    source: str  # "local" | "fallback"
