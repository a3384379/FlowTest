from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
)

from app.domain.reporting import (
    FailureCategory,
    NotificationEvent,
    ReportFilterKind,
    ReportScope,
    ReportSource,
    ReportStatus,
)
from app.engine.results import NodeObservation, NodeResult

WebhookName = Annotated[str, Field(min_length=1, max_length=160)]


class ReportQuery(BaseModel):
    status: ReportStatus | None = None
    started_from: AwareDatetime | None = None
    started_until: AwareDatetime | None = None
    workflow_id: UUID | None = None
    environment_id: UUID | None = None
    source_case_id: UUID | None = None
    source_plan_id: UUID | None = None
    source: ReportSource | None = None

    def to_scope(self) -> ReportScope:
        return ReportScope(
            status=self.status,
            started_from=self.started_from,
            started_until=self.started_until,
            workflow_id=self.workflow_id,
            environment_id=self.environment_id,
            source_case_id=self.source_case_id,
            source_plan_id=self.source_plan_id,
            source=self.source,
        )


class ReportListQuery(ReportQuery):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ReportTrendQuery(ReportQuery):
    days: int = 7


class ReportFilterQuery(BaseModel):
    kind: ReportFilterKind
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    search: str = Field(default="", max_length=200)
    selected_id: UUID | None = None


class ReportFilterOptionResponse(BaseModel):
    id: UUID
    name: str


class ReportExecutionResponse(BaseModel):
    id: UUID
    workflow_id: UUID | None
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
    observations: list[NodeObservation] = Field(default_factory=list)
    request: JsonValue = None
    response: JsonValue = None
    extraction: JsonValue = None
    assertion: JsonValue = None
    input_mappings: JsonValue = None
    output: JsonValue = None
    result: NodeResult | None = None
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


class ReportScopeSummaryResponse(BaseModel):
    started_from: datetime
    started_until: datetime
    total: int
    passed: int
    failed: int
    cancelled: int
    pending: int
    completed: int
    pass_rate: float | None


class ReportTrendResponse(BaseModel):
    points: list[TrendPointResponse]
    failures: list[FailureDistributionResponse]
    summary: ReportScopeSummaryResponse


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
