from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.core.context import get_trace_id
from app.domain.target_preview import (
    PreviewAPIChange,
    PreviewChange,
    PreviewEndpointChange,
    PreviewEnvironmentChange,
    PreviewServiceChange,
    TargetPreviewCommand,
)
from app.schemas.service_targets import EndpointVariant, ServiceKey


class ServiceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["service"]
    service_id: UUID
    enabled: bool | None = None

    def to_change(self) -> PreviewServiceChange:
        return PreviewServiceChange(self.service_id, self.enabled)


class EndpointCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["endpoint"]
    endpoint_id: UUID
    variant: EndpointVariant | None = None
    base_url: HttpUrl | None = None
    enabled: bool | None = None
    variables: dict[str, str] | None = None

    def to_change(self) -> PreviewEndpointChange:
        return PreviewEndpointChange(
            endpoint_id=self.endpoint_id,
            variant=self.variant,
            base_url=str(self.base_url) if self.base_url is not None else None,
            enabled=self.enabled,
            variables=self.variables,
        )


class EnvironmentCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["environment_default"]
    environment_id: UUID
    service_id: UUID | None

    def to_change(self) -> PreviewEnvironmentChange:
        return PreviewEnvironmentChange(self.environment_id, self.service_id)


class APICandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["api_binding"]
    api_id: UUID
    service_id: UUID | None

    def to_change(self) -> PreviewAPIChange:
        return PreviewAPIChange(self.api_id, self.service_id)


type TargetCandidate = Annotated[
    ServiceCandidate | EndpointCandidate | EnvironmentCandidate | APICandidate,
    Field(discriminator="kind"),
]


class TargetImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change: TargetCandidate

    def to_command(self) -> TargetPreviewCommand:
        return TargetPreviewCommand(change=self.change.to_change())


class TargetPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change: TargetCandidate
    environment_id: UUID | None = None
    api_id: UUID | None = None
    api_version: int | None = Field(default=None, ge=1)
    service_override: ServiceKey | None = None
    endpoint_variant: EndpointVariant = "default"

    def to_command(self) -> TargetPreviewCommand:
        change: PreviewChange = self.change.to_change()
        return TargetPreviewCommand(
            change=change,
            environment_id=self.environment_id,
            api_id=self.api_id,
            api_version=self.api_version,
            service_override=self.service_override,
            endpoint_variant=self.endpoint_variant,
        )


class PreviewErrorResponse(BaseModel):
    code: str
    message: str
    details: None
    trace_id: str


class PreviewResolutionResponse(BaseModel):
    status: Literal["resolved", "unavailable"]
    url: str | None
    service_key: str | None
    endpoint_variant: str | None
    endpoint_revision: int | None
    api_version: int | None
    error: PreviewErrorResponse | None


class TargetPreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    before: PreviewResolutionResponse
    after: PreviewResolutionResponse
    persisted: Literal[False]
    network_checked: Literal[False]


class CandidateDependencyItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    reason: str
    available: bool


class CandidateDependencyDiagnosticResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    message: str
    resource_id: UUID | None
    node_id: str | None


class TargetImpactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    scope_kind: Literal["service", "endpoint", "environment_default", "api_binding"]
    scope_id: UUID
    complete: bool
    diagnostics: tuple[CandidateDependencyDiagnosticResponse, ...]
    affected_apis: tuple[CandidateDependencyItemResponse, ...]
    affected_workflows: tuple[CandidateDependencyItemResponse, ...]
    affected_test_plans: tuple[CandidateDependencyItemResponse, ...]
    affected_scheduled_runs: tuple[CandidateDependencyItemResponse, ...]
    affected_release_gates: tuple[CandidateDependencyItemResponse, ...]
    trace_id: str = Field(default_factory=get_trace_id)
