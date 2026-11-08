"""Native MCP proposals have their own source contract; no fabricated Design receipt."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from scripts.selftest.cleanup import PlanStopReceipt
from scripts.selftest.contracts import (
    Builds,
    Contract,
    ExecutionEvidence,
    McpCallReceipt,
    RequiredDisposal,
    Sha256,
    TargetDisposalReceipt,
)
from scripts.selftest.io import JsonObject
from scripts.selftest.start_plan import PlanSelection

ControlVariant = Literal["native_control_chain", "regions4_draft", "regions4_published"]


class NativeBranchGolden(Contract):
    ordinal: int = Field(ge=0, le=1)
    branch_id: Literal["first", "second"]
    node_id: Literal["wait_first", "wait_second"]
    instance_id: str
    status: Literal["passed"]
    test_verdict: Literal["passed"]


class NativeControlPack(Contract):
    format: Literal["flowtest-native-control-mcp-v1"]
    pack_id: Literal["native-control-mcp-v1"]
    version: Literal["1.0.0"]
    variants: tuple[ControlVariant, ...]
    definition: JsonObject
    branch_node_id: Literal["parallel"]
    branches: tuple[NativeBranchGolden, ...] = Field(min_length=2, max_length=2)
    export_error_code: Literal["FLOWSPEC_CONTROL_UNSUPPORTED"]
    export_status: Literal[422]
    max_requests: Literal[500]
    max_tool_calls: Literal[100]
    max_seconds: Literal[600]


class NativeControlManifest(Contract):
    batch_key: str
    nonce: str
    pack_digest: Sha256
    binding_fingerprint: Sha256
    binding_nonce: str
    builds: Builds
    project_id: UUID
    environment_id: UUID
    reviewer_id: UUID
    mcp_account_id: UUID
    mcp_actor_id: UUID
    created_at: datetime
    expires_at: datetime
    required_disposal: RequiredDisposal

    @model_validator(mode="after")
    def bounded_time(self) -> "NativeControlManifest":
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("时间必须包含时区")
        if not 0 < (self.expires_at - self.created_at).total_seconds() <= 600:
            raise ValueError("时间预算必须不超过600秒")
        return self


class NativePublishedCase(Contract):
    case: JsonObject
    version: JsonObject


class NativeControlFreeze(Contract):
    request: JsonObject
    proposal: JsonObject
    replay: JsonObject
    pending: JsonObject
    accepted: JsonObject
    draft: JsonObject
    published: JsonObject
    case: NativePublishedCase
    suite: JsonObject
    plan: JsonObject
    selection: PlanSelection
    before_workflow_ids: tuple[UUID, ...]
    pending_workflow_ids: tuple[UUID, ...]
    pending_execution_ids: tuple[UUID, ...]
    before_execution_ids: tuple[UUID, ...]
    frozen_at: datetime


class NativeExportObservation(Contract):
    variant: Literal["regions4_draft", "regions4_published"]
    workflow_id: UUID
    version: int | None = None
    path: str
    status: int
    error_code: str
    trace_present: bool
    before_definition_digest: Sha256
    after_definition_digest: Sha256
    before_execution_ids: tuple[UUID, ...]
    after_execution_ids: tuple[UUID, ...]


class NativeControlEvidence(Contract):
    manifest_digest: Sha256
    frozen: NativeControlFreeze | None = None
    execution: ExecutionEvidence | None = None
    plan_run: JsonObject | None = None
    raw_execution: JsonObject | None = None
    control_page: JsonObject | None = None
    control_details: tuple[JsonObject, ...] = Field(default=(), max_length=2)
    exports: tuple[NativeExportObservation, ...] = Field(default=(), max_length=2)
    calls: tuple[McpCallReceipt, ...] = Field(default=(), max_length=100)
    cleanup: PlanStopReceipt | None = None
    disposal: TargetDisposalReceipt | None = None
    admitted_request_upper_bound: int = Field(default=0, ge=0, le=500)
    admitted_tool_calls: int = Field(default=0, ge=0, le=100)
    rejected_requests: int = Field(default=0, ge=0)
    rejected_tool_calls: int = Field(default=0, ge=0)
    collected_at: datetime
    failure_code: str | None = None


class NativeControlCheck(Contract):
    variant: ControlVariant
    status: Literal["matched", "mismatched", "incomplete"]
    findings: tuple[str, ...]


class NativeControlReport(Contract):
    pack_id: Literal["native-control-mcp-v1"] = "native-control-mcp-v1"
    verification_scope: Literal["native_control_proposal_only"] = "native_control_proposal_only"
    trust: Literal["local_untrusted"] = "local_untrusted"
    batch_key: str
    pack_digest: Sha256
    manifest_digest: Sha256
    verdict: Literal["passed", "failed", "blocked"]
    exit_code: Literal[0, 1, 2]
    findings: tuple[str, ...]
    scenarios: tuple[NativeControlCheck, ...] = Field(min_length=3, max_length=3)
