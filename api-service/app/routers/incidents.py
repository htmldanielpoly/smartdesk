from fastapi import APIRouter, Depends

from app.deps import require_roles
from app.models.enums import Role
from app.schemas.incident import IncidentOverviewOut
from app.services import incidents

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=IncidentOverviewOut)
async def incident_overview(user: dict = Depends(require_roles(Role.AGENT, Role.ADMIN))):
    """Staff-only: group active complaints into incidents (local embedding
    model, with a lexical fallback) and return a manager rollup."""
    return await incidents.overview()
