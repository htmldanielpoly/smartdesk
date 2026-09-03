from pydantic import BaseModel, Field


class CopilotResponse(BaseModel):
    suggested_solution: str
    draft_response: str
    source: str  # "local" | "fallback"
    # KB article ids the draft is grounded in (empty for template fallbacks).
    citations: list[str] = Field(default_factory=list)
    # Guardrail annotations the agent should see: injection_suspected,
    # coercion_suspected, no_kb_match, output_rejected.
    flags: list[str] = Field(default_factory=list)


class DuplicateCandidate(BaseModel):
    ticket_id: str
    similarity: float
    title: str


class DuplicatesResponse(BaseModel):
    candidates: list[DuplicateCandidate]
    source: str  # "ai" | "fallback"
