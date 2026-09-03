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


class ClusterItem(BaseModel):
    id: str
    title: str
    description: str


class ClusterRequest(BaseModel):
    items: list[ClusterItem] = Field(default_factory=list)


class ClusterResponse(BaseModel):
    # Each group is a list of item ids that form one incident/cluster.
    groups: list[list[str]] = Field(default_factory=list)
    source: str  # "local" | "fallback"


# --- Long-term memory: automated resolution ---------------------------------

class MemoryCandidate(BaseModel):
    """A previously resolved ticket together with the answer that resolved it."""

    ticket_id: str
    title: str
    description: str
    resolution: str


class AutoResolveRequest(BaseModel):
    title: str
    description: str
    candidates: list[MemoryCandidate] = Field(default_factory=list)


class AutoResolveMatch(BaseModel):
    ticket_id: str
    title: str
    similarity: float


class AutoResolveResponse(BaseModel):
    # True when a stored resolution can be applied without a human.
    resolved: bool
    match: AutoResolveMatch | None = None
    # Customer-facing reply drafted from the matched ticket's resolution.
    draft_response: str | None = None
    # The threshold that applied (depends on the similarity path used).
    threshold: float
    source: str  # "local" | "fallback"
    # Why nothing was resolved, e.g. ["injection_suspected"], ["below_threshold"].
    flags: list[str] = Field(default_factory=list)
