from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from app.domain.reporting import FailureCategory, NotificationEvent

WebhookName = Annotated[str, Field(min_length=1, max_length=160)]


class ReportExecutionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    workflow_name: str
    workflow_version: int
    status: str
    failure_category: FailureCategory
    total_nodes: int
    passed_nodes: int
    failed_nodes: int
    skipped_nodes: int
    duration_ms: float | None
    started_at: datetime
    completed_at: datetime | None


class ReportNodeResponse(BaseModel):
    id: UUID
    node_id: str
    node_type: str
    name: str
    status: str
    attempts: int
    duration_ms: float | None
    request: JsonValue = None
    response: JsonValue = None
    extraction: JsonValue = None
    assertion: JsonValue = None
    input_mappings: JsonValue = None
    error_code: str | None
    error_message: str | None


class ReportExecutionDetailResponse(BaseModel):
    summary: ReportExecutionResponse
    nodes: list[ReportNodeResponse]
    context: dict[str, JsonValue]
    dataset_children: list[ReportExecutionResponse] = Field(default_factory=list)


class TrendPointResponse(BaseModel):
    date: date
    total: int
    passed: int
    failed: int
    cancelled: int
    pass_rate: float
    average_duration_ms: float


class FailureDistributionResponse(BaseModel):
    category: FailureCategory
    count: int


class ReportTrendResponse(BaseModel):
    points: list[TrendPointResponse]
    failures: list[FailureDistributionResponse]


class NotificationWebhookCreate(BaseModel):
    name: WebhookName
    url: HttpUrl
    events: set[NotificationEvent] = Field(
        default_factory=lambda: {
            NotificationEvent.WORKFLOW_COMPLETED,
            NotificationEvent.TEST_PLAN_COMPLETED,
        },
        min_length=1,
    )


class NotificationWebhookUpdate(BaseModel):
    name: WebhookName | None = None
    url: HttpUrl | None = None
    events: set[NotificationEvent] | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class NotificationWebhookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    url: str
    events: list[NotificationEvent]
    enabled: bool
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class NotificationWebhookCreatedResponse(NotificationWebhookResponse):
    secret: str


class NotificationDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    webhook_id: UUID
    event_type: NotificationEvent
    resource_id: UUID
    status: str
    attempt: int
    response_status: int | None
    error_message: str | None
    delivered_at: datetime | None
    created_at: datetime
