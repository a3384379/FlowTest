"""Restricted CI evidence; no arbitrary snapshots, payloads, credentials or context."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.tasking import TestPlanTrigger

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
RunStatus = Literal["queued", "running", "passed", "failed", "cancelled"]
NodeStatus = Literal["pending", "running", "passed", "failed", "skipped", "cancelled"]


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssertionEvidenceResponse(EvidenceResponse):
    name: str = Field(min_length=1, max_length=200)
    passed: bool
    expected_digest: Digest
    actual_digest: Digest


class NodeEvidenceResponse(EvidenceResponse):
    node_id: str = Field(min_length=1, max_length=128)
    node_type: str = Field(min_length=1, max_length=80)
    phase: Literal["main", "cleanup"]
    status: NodeStatus
    attempts: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=100)
    assertions: tuple[AssertionEvidenceResponse, ...] = Field(default=(), max_length=100)
    assertions_complete: bool = True


class APIBindingEvidenceResponse(EvidenceResponse):
    node_id: str = Field(min_length=1, max_length=128)
    api_definition_id: UUID
    api_version_id: UUID
    api_version: int = Field(ge=1)
    contract_fingerprint: Digest | None


class SubflowBindingEvidenceResponse(EvidenceResponse):
    path: tuple[str, ...] = Field(min_length=1, max_length=5)
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_version: int = Field(ge=1)
    workflow_fingerprint: Digest
    api_bindings: tuple[APIBindingEvidenceResponse, ...] = Field(max_length=500)
    complete: bool


class DatasetBindingEvidenceResponse(EvidenceResponse):
    artifact_id: UUID
    sha256: Digest
    row_count: int = Field(ge=1, le=500)


class DatasetChildReferenceEvidenceResponse(EvidenceResponse):
    execution_id: UUID
    row_index: int = Field(ge=0, le=499)
    status: RunStatus


class ExecutionEvidenceResponse(EvidenceResponse):
    parent_execution_id: UUID | None = None
    dataset_row_index: int | None = Field(default=None, ge=0, le=499)
    dataset: DatasetBindingEvidenceResponse | None = None
    children: tuple[DatasetChildReferenceEvidenceResponse, ...] = Field(default=(), max_length=500)
    children_total: int = Field(default=0, ge=0)
    children_complete: bool = True
    subflows: tuple[SubflowBindingEvidenceResponse, ...] = Field(default=(), max_length=100)
    subflows_complete: bool = True
    execution_id: UUID
    project_id: UUID
    workflow_id: UUID | None
    workflow_version_id: UUID | None
    environment_id: UUID
    status: RunStatus
    main_status: RunStatus | None
    cleanup_status: RunStatus | None
    error_code: str | None = Field(default=None, max_length=100)
    run_purpose: Literal["standard", "preview"]
    source_case_id: UUID | None
    source_case_version: int | None
    source_plan_run_item_id: UUID | None
    started_at: datetime
    completed_at: datetime | None
    snapshot_digest: Digest
    workflow_fingerprint: Digest | None
    api_bindings: tuple[APIBindingEvidenceResponse, ...] = Field(default=(), max_length=1000)
    bindings_complete: bool
    nodes: tuple[NodeEvidenceResponse, ...] = Field(default=(), max_length=1000)
    node_total: int = Field(ge=0)
    truncated: bool
    nested_nodes: tuple[NodeEvidenceResponse, ...] = Field(default=(), max_length=1000)
    nested_node_total: int = Field(default=0, ge=0)
    nested_nodes_complete: bool = True


class PlanItemEvidenceResponse(EvidenceResponse):
    id: UUID
    target_type: Literal["workflow", "case", "suite"]
    target_id: UUID
    target_version: int = Field(ge=1)
    target_snapshot_digest: Digest
    workflow_id: UUID
    workflow_version: int = Field(ge=1)
    environment_id: UUID
    status: Literal["queued", "running", "passed", "failed", "cancelled", "quarantined"]
    attempts: int = Field(ge=0)
    execution_id: UUID | None
    execution_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    attempts_complete: bool


class PlanRunEvidenceResponse(EvidenceResponse):
    run_id: UUID
    project_id: UUID
    test_plan_id: UUID
    status: RunStatus
    trigger_type: TestPlanTrigger
    completed_at: datetime | None
    items: tuple[PlanItemEvidenceResponse, ...] = Field(default=(), max_length=100)
    total: int = Field(ge=0)
    page: int = Field(ge=1, le=1000)
    page_size: int = Field(ge=1, le=100)
    has_more: bool
    truncated: bool


class ControlRecordEvidenceResponse(EvidenceResponse):
    ordinal: int = Field(ge=0)
    status: str = Field(max_length=16)
    test_verdict: Literal["passed", "failed", "not_run"]


class ControlRecordsEvidenceResponse(EvidenceResponse):
    execution_id: UUID
    node_id: str = Field(min_length=1, max_length=128)
    kind: Literal["iteration", "branch"]
    items: tuple[ControlRecordEvidenceResponse, ...] = Field(default=(), max_length=100)
    total: int = Field(ge=0)
    page: int = Field(ge=1, le=1000)
    page_size: int = Field(ge=1, le=100)
    has_more: bool
    truncated: bool
