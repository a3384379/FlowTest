from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.artifacts import ArtifactResponse
from app.schemas.common import Page
from app.schemas.reporting import (
    FailureDistributionResponse,
    NotificationDeliveryResponse,
    NotificationWebhookCreate,
    NotificationWebhookCreatedResponse,
    NotificationWebhookResponse,
    NotificationWebhookUpdate,
    ReportExecutionDetailResponse,
    ReportExecutionResponse,
    ReportFilterOptionResponse,
    ReportFilterQuery,
    ReportListQuery,
    ReportNodeResponse,
    ReportScopeSummaryResponse,
    ReportTrendQuery,
    ReportTrendResponse,
    TrendPointResponse,
)
from app.services.notifications import NotificationWebhookService
from app.services.reporting import ExecutionReportDetail, ReportService

router = APIRouter(prefix="/projects/{project_id}")


@router.get("/reports/filter-options", response_model=Page[ReportFilterOptionResponse])
async def list_report_filter_options(
    project_id: UUID,
    query: Annotated[ReportFilterQuery, Query()],
    session: SessionDependency,
    current_user: CurrentUser,
) -> Page[ReportFilterOptionResponse]:
    items, total = await ReportService(session).list_filter_options(
        actor=current_user,
        project_id=project_id,
        kind=query.kind,
        page=query.page,
        page_size=query.page_size,
        search=query.search,
        selected_id=query.selected_id,
    )
    return Page(
        items=[
            ReportFilterOptionResponse.model_validate(item, from_attributes=True) for item in items
        ],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/reports/executions", response_model=Page[ReportExecutionResponse])
async def list_report_executions(
    project_id: UUID,
    query: Annotated[ReportListQuery, Query()],
    session: SessionDependency,
    current_user: CurrentUser,
) -> Page[ReportExecutionResponse]:
    items, total = await ReportService(session).list_executions(
        actor=current_user,
        project_id=project_id,
        page=query.page,
        page_size=query.page_size,
        scope=query.to_scope(),
    )
    return Page(
        items=[
            ReportExecutionResponse.model_validate(item, from_attributes=True) for item in items
        ],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/reports/executions/{execution_id}", response_model=ReportExecutionDetailResponse)
async def get_report_execution(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReportExecutionDetailResponse:
    detail = await ReportService(session).get_execution(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
    )
    return _detail_response(detail)


@router.get("/reports/trends", response_model=ReportTrendResponse)
async def get_report_trends(
    project_id: UUID,
    query: Annotated[ReportTrendQuery, Query()],
    session: SessionDependency,
    current_user: CurrentUser,
) -> ReportTrendResponse:
    trend = await ReportService(session).trend(
        actor=current_user,
        project_id=project_id,
        days=query.days,
        scope=query.to_scope(),
    )
    return ReportTrendResponse(
        points=[
            TrendPointResponse.model_validate(item, from_attributes=True) for item in trend.points
        ],
        failures=[
            FailureDistributionResponse(category=category, count=count)
            for category, count in trend.failures
        ],
        summary=ReportScopeSummaryResponse.model_validate(trend.summary, from_attributes=True),
    )


@router.post(
    "/reports/executions/{execution_id}/exports/html",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def export_report_html(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ArtifactResponse:
    artifact = await ReportService(session).export_html(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
    )
    return ArtifactResponse.model_validate(artifact)


@router.post(
    "/notification-webhooks",
    response_model=NotificationWebhookCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification_webhook(
    project_id: UUID,
    payload: NotificationWebhookCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> NotificationWebhookCreatedResponse:
    created = await NotificationWebhookService(session).create(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        url=str(payload.url),
        events=payload.events,
    )
    stored = NotificationWebhookResponse.model_validate(created.model).model_dump()
    return NotificationWebhookCreatedResponse(**stored, secret=created.secret)


@router.get("/notification-webhooks", response_model=list[NotificationWebhookResponse])
async def list_notification_webhooks(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[NotificationWebhookResponse]:
    webhooks = await NotificationWebhookService(session).list_webhooks(
        actor=current_user,
        project_id=project_id,
    )
    return [NotificationWebhookResponse.model_validate(item) for item in webhooks]


@router.patch("/notification-webhooks/{webhook_id}", response_model=NotificationWebhookResponse)
async def update_notification_webhook(
    project_id: UUID,
    webhook_id: UUID,
    payload: NotificationWebhookUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> NotificationWebhookResponse:
    webhook = await NotificationWebhookService(session).update(
        actor=current_user,
        project_id=project_id,
        webhook_id=webhook_id,
        name=payload.name,
        url=str(payload.url) if payload.url is not None else None,
        events=payload.events,
        enabled=payload.enabled,
    )
    return NotificationWebhookResponse.model_validate(webhook)


@router.get("/notification-deliveries", response_model=Page[NotificationDeliveryResponse])
async def list_notification_deliveries(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[NotificationDeliveryResponse]:
    deliveries, total = await NotificationWebhookService(session).list_deliveries(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[NotificationDeliveryResponse.model_validate(item) for item in deliveries],
        total=total,
        page=page,
        page_size=page_size,
    )


def _detail_response(detail: ExecutionReportDetail) -> ReportExecutionDetailResponse:
    return ReportExecutionDetailResponse(
        summary=ReportExecutionResponse.model_validate(detail.summary, from_attributes=True),
        nodes=[
            ReportNodeResponse.model_validate(item, from_attributes=True) for item in detail.nodes
        ],
        context=detail.context,
        dataset_children=[
            ReportExecutionResponse.model_validate(item, from_attributes=True)
            for item in detail.dataset_children
        ],
    )
