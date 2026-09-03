"""AI endpoints. Every request is a job on the priority scheduler: the
endpoint enqueues it (priority from the job kind and the ticket priority the
gateway sends along) and awaits the result while the event loop stays free.
A saturated engine answers 503 and a stuck job 504 — the gateway treats both
as "AI unavailable" and uses its rule-based path, so nothing ever blocks."""
from fastapi import APIRouter, HTTPException, status

from app.schemas import (
    AutoResolveRequest,
    AutoResolveResponse,
    ClassifyRequest,
    ClassifyResponse,
    ClusterRequest,
    ClusterResponse,
    CopilotRequest,
    CopilotResponse,
    DuplicatesRequest,
    DuplicatesResponse,
)
from app.services import classifier, clustering, copilot, duplicates, memory
from app.services.scheduler import Overloaded, scheduler

router = APIRouter(tags=["ai"])


async def _run(kind: str, fn, req, ticket_priority: str | None = None):
    try:
        return await scheduler.submit(kind, fn, req, ticket_priority=ticket_priority)
    except Overloaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI engine is saturated; retry shortly.",
            headers={"Retry-After": "5"},
        ) from None
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI job timed out.",
        ) from None


@router.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest):
    return await _run("classify", classifier.classify, req, req.priority)


@router.post("/copilot", response_model=CopilotResponse)
async def agent_copilot(req: CopilotRequest):
    return await _run("copilot", copilot.assist, req, req.priority)


@router.post("/duplicates", response_model=DuplicatesResponse)
async def detect_duplicates(req: DuplicatesRequest):
    return await _run("duplicates", duplicates.find, req, req.priority)


@router.post("/auto-resolve", response_model=AutoResolveResponse)
async def auto_resolve(req: AutoResolveRequest):
    """Long-term memory: answer a ticket that repeats an already-resolved one."""
    return await _run("auto_resolve", memory.auto_resolve, req, req.priority)


@router.post("/cluster", response_model=ClusterResponse)
async def cluster_tickets(req: ClusterRequest):
    return await _run("cluster", clustering.cluster, req, req.priority)
