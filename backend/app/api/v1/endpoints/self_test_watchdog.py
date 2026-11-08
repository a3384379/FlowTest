"""Deployment H may request cleanup only after this exact batch's deadline."""

from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import SessionDependency
from app.api.v1.endpoints.self_tests import Agent, Config
from app.schemas.self_test_watchdog import WatchdogRequest
from app.schemas.self_tests import BatchResponse
from app.services.self_test_cancellation import SelfTestCancellation

router = APIRouter(prefix="/agent/projects/{project_id}/self-tests")


@router.post("/runs/{batch_id}/watchdog", response_model=BatchResponse)
async def request_expired_cleanup(
    project_id: UUID,
    batch_id: UUID,
    payload: WatchdogRequest,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> BatchResponse:
    return await SelfTestCancellation(session, config).watchdog(
        principal, project_id, batch_id, payload
    )
