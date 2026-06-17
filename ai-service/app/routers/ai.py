from fastapi import APIRouter

from app.schemas import (
    ClassifyRequest,
    ClassifyResponse,
    CopilotRequest,
    CopilotResponse,
    DuplicatesRequest,
    DuplicatesResponse,
)
from app.services import classifier, copilot, duplicates

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
