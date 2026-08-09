from fastapi import APIRouter

from app.api.dependencies import SessionDependency, SystemAdministrator
from app.schemas.maintenance import RetentionCleanupResponse
from app.services.retention import RetentionCleanupService

router = APIRouter(prefix="/maintenance")


@router.post("/retention-cleanup", response_model=RetentionCleanupResponse)
async def run_retention_cleanup(
    session: SessionDependency,
    _administrator: SystemAdministrator,
) -> RetentionCleanupResponse:
    summary = await RetentionCleanupService(session).cleanup()
    return RetentionCleanupResponse.model_validate(summary)
