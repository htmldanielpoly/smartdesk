from fastapi import APIRouter

from app.schemas import (
    ClassifyRequest,
    ClassifyResponse,
    ClusterRequest,
    ClusterResponse,
    CopilotRequest,
    CopilotResponse,
    DuplicatesRequest,
    DuplicatesResponse,
)
from app.services import classifier, clustering, copilot, duplicates

router = APIRouter(tags=["ai"])


@router.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest):
    return classifier.classify(req)


@router.post("/copilot", response_model=CopilotResponse)
def agent_copilot(req: CopilotRequest):
    return copilot.assist(req)


@router.post("/duplicates", response_model=DuplicatesResponse)
def detect_duplicates(req: DuplicatesRequest):
    return duplicates.find(req)


@router.post("/cluster", response_model=ClusterResponse)
def cluster_tickets(req: ClusterRequest):
    return clustering.cluster(req)
