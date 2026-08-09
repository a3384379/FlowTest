from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.common import Page
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    DashboardTrendPointResponse,
    RecentExecutionResponse,
)
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard")


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    session: SessionDependency,
    current_user: CurrentUser,
    project_id: Annotated[UUID | None, Query()] = None,
) -> DashboardSummaryResponse:
    summary = await DashboardService(session).summary(actor=current_user, project_id=project_id)
    return DashboardSummaryResponse(
        project_count=summary.project_count,
        api_count=summary.api_count,
        workflow_count=summary.workflow_count,
        today_total=summary.today_total,
        today_passed=summary.today_passed,
        today_failed=summary.today_failed,
        pass_rate=summary.pass_rate,
        trend=[
            DashboardTrendPointResponse.model_validate(item, from_attributes=True)
            for item in summary.trend
        ],
    )


@router.get("/recent-executions", response_model=Page[RecentExecutionResponse])
async def recent_executions(
    session: SessionDependency,
    current_user: CurrentUser,
    project_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> Page[RecentExecutionResponse]:
    executions, total = await DashboardService(session).recent_executions(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[
            RecentExecutionResponse.model_validate(execution, from_attributes=True)
            for execution in executions
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
