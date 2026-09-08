"""S62 MCP adapters for analysis preparation, plan suggestions and Preview cancel."""

from typing import Annotated

from fastapi import APIRouter, Header

from app.api.dependencies import (
    MCPPreviewCurrent,
    MCPRegressionPrepareCurrent,
    MCPTestPlanProposeCurrent,
    SessionDependency,
)
from app.schemas.mcp_planning import (
    MCPCancelPreviewRequest,
    MCPCancelPreviewResponse,
    MCPPrepareChangeRegressionRequest,
    MCPPrepareChangeRegressionResponse,
    MCPTestPlanUpdateRequest,
    MCPTestPlanUpdateResponse,
)
from app.services.mcp_planning import MCPPlanningService

continuous_router = APIRouter(prefix="/mcp/continuous")
preview_router = APIRouter(prefix="/mcp/preview")
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@continuous_router.post(
    "/change-regression/prepare",
    response_model=MCPPrepareChangeRegressionResponse,
    status_code=202,
)
async def prepare_change_regression(
    payload: MCPPrepareChangeRegressionRequest,
    session: SessionDependency,
    principal: MCPRegressionPrepareCurrent,
    idempotency_key: IdempotencyHeader = None,
) -> MCPPrepareChangeRegressionResponse:
    return await MCPPlanningService(session).prepare_change_regression(
        actor=principal.actor,
        account_id=principal.account.id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@continuous_router.post(
    "/test-plan/proposals",
    response_model=MCPTestPlanUpdateResponse,
    status_code=202,
)
async def propose_test_plan_update(
    payload: MCPTestPlanUpdateRequest,
    session: SessionDependency,
    principal: MCPTestPlanProposeCurrent,
    idempotency_key: IdempotencyHeader = None,
) -> MCPTestPlanUpdateResponse:
    return await MCPPlanningService(session).propose_test_plan_update(
        actor=principal.actor,
        account_id=principal.account.id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@preview_router.post(
    "/cancel",
    response_model=MCPCancelPreviewResponse,
)
async def cancel_preview(
    payload: MCPCancelPreviewRequest,
    session: SessionDependency,
    principal: MCPPreviewCurrent,
) -> MCPCancelPreviewResponse:
    return await MCPPlanningService(session).cancel_preview(
        actor=principal.actor,
        payload=payload,
    )
