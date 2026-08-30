from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.domain.sandbox_preview import PreviewBudget, is_preview_routing_header
from app.schemas.workflows import RuntimeVariableName, WorkflowExecutionResponse


def _reject_preview_routing_headers(headers: dict[str, str]) -> dict[str, str]:
    blocked = sorted(name for name in headers if is_preview_routing_header(name))
    if blocked:
        raise ValueError("Sandbox Preview runtime headers cannot override request routing")
    return headers


PreviewRuntimeHeaders = Annotated[
    dict[str, str],
    AfterValidator(_reject_preview_routing_headers),
]


class SandboxPreviewApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: UUID
    budget: PreviewBudget = Field(default_factory=PreviewBudget)
    executor_service_account_id: UUID | None = None
    runtime_variables: dict[RuntimeVariableName, str] = Field(default_factory=dict)
    runtime_headers: PreviewRuntimeHeaders = Field(default_factory=dict)
    ttl_seconds: int = Field(default=300, ge=30, le=900)


class SandboxPreviewApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    change_set_id: UUID
    environment_id: UUID
    environment_fingerprint: str
    executor_kind: str
    executor_id: UUID
    proposal_fingerprint: str
    context_revision_id: UUID
    context_fingerprint: str
    budget: PreviewBudget
    expires_at: datetime
    consumed_at: datetime | None
    execution_id: UUID | None
    created_by_id: UUID
    created_at: datetime


class SandboxPreviewExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: UUID
    approval_id: UUID
    runtime_variables: dict[RuntimeVariableName, str] = Field(default_factory=dict)
    runtime_headers: PreviewRuntimeHeaders = Field(default_factory=dict)


class MCPSandboxPreviewExecuteRequest(SandboxPreviewExecuteRequest):
    project_id: UUID


class SandboxPreviewExecutionResponse(BaseModel):
    execution: WorkflowExecutionResponse
