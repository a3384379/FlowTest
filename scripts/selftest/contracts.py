"""Bounded Observer contracts, deliberately independent of candidate product code."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    model_validator,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, Field(min_length=1, max_length=200)]
ScenarioId = Annotated[str, Field(min_length=1, max_length=160)]
SyntheticText = Annotated[str, Field(max_length=200)]
RawStatus = Literal["queued", "running", "passed", "failed", "cancelled"]
NodeStatus = Literal["pending", "running", "passed", "failed", "skipped", "cancelled"]
Phase = Literal["main", "cleanup"]
EvidenceKind = Literal[
    "execution",
    "assertions",
    "fixture_journal",
    "provenance",
    "postcondition",
    "control_records",
    "response_fields",
]
VerificationStatus = Literal[
    "pending", "matched", "mismatched", "incomplete", "error", "unsupported"
]


def canonical_digest(value: JsonValue) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Builds(Contract):
    runner: Identity
    target: Identity
    fixture: Identity
    verifier: Identity


class AssertionEvidence(Contract):
    mode: Literal["value"] = "value"
    name: Identity
    passed: StrictBool
    expected: JsonValue
    actual: JsonValue


class DigestAssertionEvidence(Contract):
    mode: Literal["digest"]
    name: Identity
    passed: StrictBool
    expected_digest: Sha256
    actual_digest: Sha256


def _default_assertion_mode(value: object) -> object:
    if isinstance(value, dict) and "mode" not in value:
        return {**value, "mode": "value"}
    return value


ObservedAssertion = Annotated[
    AssertionEvidence | DigestAssertionEvidence,
    Field(discriminator="mode"),
    BeforeValidator(_default_assertion_mode),
]


class AssertionExpectation(AssertionEvidence):
    node_id: Identity
    phase: Phase = "main"


class SyntheticHeaderSnapshot(Contract):
    value: Literal["project", "environment", "api", "case", "runtime", "node"] | None = None
    count: int = Field(default=0, ge=0, le=100)


class FixtureResponseExpectation(Contract):
    response_status: int = Field(ge=100, le=599)
    actual: int
    code: int
    authorization_present: StrictBool = False
    cookie_present: StrictBool = False
    synthetic_precedence_header: SyntheticHeaderSnapshot | None = None


class ResourceAbsenceExpectation(Contract):
    project_id: UUID
    resource_kind: Literal["environments", "folders"] = "environments"
    absent_names: tuple[Identity, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_names(self) -> ResourceAbsenceExpectation:
        if len(self.absent_names) != len(set(self.absent_names)):
            raise ValueError("业务后置条件名称不能重复")
        return self


class ResourceAbsenceEvidence(Contract):
    project_id: UUID
    resource_kind: Literal["environments", "folders"] = "environments"
    returned_names: tuple[Identity, ...] = Field(max_length=10000)
    observed_at: datetime
    complete: StrictBool


class ResponseFieldExpectation(Contract):
    api_source: ApiSource
    node_id: Identity
    field: Literal["name"] = "name"
    expected: Identity


class ResponseFieldEvidence(Contract):
    batch_key: Identity
    scenario_id: ScenarioId
    project_id: UUID
    execution_id: UUID
    workflow_version_id: UUID
    api_source: ApiSource
    node_id: Identity
    field: Literal["name"] = "name"
    actual: Identity
    observed_at: datetime


class NestedNodeExpectation(Contract):
    node_id: Identity
    phase: Phase
    status: Literal["passed", "failed", "skipped", "cancelled"]
    error_code: Identity | None = None
    attempts: int = Field(default=1, ge=0, le=100)


class ErrorEnvelopeExpectation(Contract):
    node_id: Identity
    status_code: Literal[401, 403, 422]
    error_code: Identity
    trace_id: Identity


class ErrorEnvelopeEvidence(ErrorEnvelopeExpectation):
    project_id: UUID
    execution_id: UUID
    response_trace_id: Identity


class DisposableTargetIdentity(Contract):
    project_name: Identity
    target_container_id: Identity
    target_volume: Identity
    target_image: Identity


class TargetDisposalReceipt(DisposableTargetIdentity):
    binding_nonce: Identity
    removed_at: datetime
    containers_absent: StrictBool
    volumes_absent: StrictBool
    networks_absent: StrictBool


class ProjectStateExpectation(Contract):
    organization_id: UUID
    created_by_id: UUID
    name: Identity
    disposal_binding_nonce: Identity
    disposable_target: DisposableTargetIdentity | None = None


class ProjectStateEvidence(ProjectStateExpectation):
    project_id: UUID
    created_at: datetime
    observed_at: datetime
    disposal_status: Literal["pending", "completed"]
    disposal_receipt: TargetDisposalReceipt | None = None


class SubflowBinding(Contract):
    path: tuple[Identity, ...] = Field(min_length=1, max_length=5)
    project_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_version: int = Field(ge=1)
    workflow_fingerprint: Sha256
    api_sources: tuple[ApiSource, ...] = Field(max_length=500)
    complete: StrictBool = True


class DatasetBinding(Contract):
    artifact_id: UUID
    sha256: Sha256
    row_count: int = Field(ge=1, le=500)


class DatasetExpectation(DatasetBinding):
    row_indices: tuple[int, ...] = Field(min_length=1, max_length=500)
    nodes: tuple[NestedNodeExpectation, ...] = Field(default=(), max_length=500)
    assertions: tuple[AssertionExpectation, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def exact_rows(self) -> DatasetExpectation:
        if self.row_indices != tuple(range(self.row_count)):
            raise ValueError("数据行集合必须完整、从零开始且非空")
        return self


class FixtureMetricsExpectation(Contract):
    peak_concurrency: int = Field(ge=1, le=20)
    completed_count: int = Field(ge=1, le=500)
    active_count: Literal[0] = 0
    cancelled_count: Literal[0] = 0
    failed_count: Literal[0] = 0


class FixtureRequestEvent(Contract):
    request_id: UUID
    sequence: int = Field(ge=1, le=10000)
    started_at: float
    completed_at: float | None = None
    outcome: Literal["completed", "cancelled", "failed"] | None = None
    active_at_begin: int = Field(ge=1, le=500)


class FixtureMetrics(Contract):
    events: tuple[FixtureRequestEvent, ...] = Field(max_length=500)
    complete: StrictBool
    active_count: int = Field(ge=0, le=10000)
    peak_concurrency: int = Field(ge=0, le=10000)
    completed_count: int = Field(ge=0, le=10000)
    cancelled_count: int = Field(ge=0, le=10000)
    failed_count: int = Field(ge=0, le=10000)


class RequiredDisposal(DisposableTargetIdentity):
    binding_nonce: Identity


class FixtureBudgetScope(Contract):
    parent_batch_key: Identity
    nonce: Identity
    limit: int = Field(default=500, ge=1, le=500)
    expires_at: float = Field(gt=0, allow_inf_nan=False)


class FixtureBudgetReceipt(FixtureBudgetScope):
    admitted_count: int = Field(ge=0, le=500)
    rejected_count: int = Field(ge=0)
    fixture_digest: Identity
    registration_epoch: Identity
    expires_at: float


class BinaryFileExpectation(Contract):
    content_utf8: Annotated[str, Field(min_length=1, max_length=4096)]
    size_bytes: int = Field(ge=1, le=4096)
    sha256: Sha256
    content_type: Literal["application/octet-stream"]
    filename: Literal["flowtest.bin"]


class SyntheticArtifactExpectation(BinaryFileExpectation):
    project_id: UUID
    artifact_id: UUID


class SyntheticArtifactEvidence(Contract):
    project_id: UUID
    artifact_id: UUID
    content_base64: Annotated[str, Field(min_length=1, max_length=8192)]
    content_type: Literal["application/octet-stream"]


class CreatedFileExpectation(BinaryFileExpectation):
    project_id: UUID
    created_by_id: UUID
    previous_artifact_ids: tuple[UUID, ...] = Field(max_length=100)
    target_origin: Annotated[str, Field(min_length=1, max_length=300)]
    timestamp_precision: Literal["second", "microsecond"]


class CreatedFileEvidence(SyntheticArtifactEvidence):
    filename: Literal["flowtest.bin"]
    size_bytes: int = Field(ge=1, le=4096)
    sha256: Sha256
    observed_artifact_ids: tuple[UUID, ...] = Field(max_length=100)
    native_uploaded_id: UUID
    created_by_id: UUID
    created_at: datetime
    observed_at: datetime
    purpose: Literal["upload"]
    requested_download_origin: Annotated[str, Field(min_length=1, max_length=300)]
    requested_download_path: Annotated[str, Field(min_length=1, max_length=512)]


class SyntheticCookieSnapshot(Contract):
    stage: Literal["set", "barrier", "check"]
    value: Literal["left", "right"] | None


class ExpectedOutcome(Contract):
    created_file: CreatedFileExpectation | None = None
    synthetic_artifact: SyntheticArtifactExpectation | None = None
    uploaded_synthetic_file: bool = False
    isolated_cookies: bool = False
    binary_file: BinaryFileExpectation | None = None
    required_disposal: RequiredDisposal | None = None
    execution_status: Literal["passed", "failed", "cancelled"]
    top_nodes: tuple[NestedNodeExpectation, ...] = Field(default=(), max_length=5000)
    fixture_metrics: FixtureMetricsExpectation | None = None
    subflows: tuple[SubflowBinding, ...] = Field(default=(), max_length=100)
    dataset: DatasetExpectation | None = None
    main_status: Literal["passed", "failed", "cancelled"] | None = None
    cleanup_status: Literal["passed", "failed", "cancelled"] | None = None
    error_code: Identity | None = None
    node_id: Identity | None = None
    phase: Phase | None = None
    request_count: int | None = Field(default=None, ge=0, le=10000)
    expected_request_value_presence: tuple[StrictBool, ...] = Field(default=(), max_length=10000)
    assertions: tuple[AssertionExpectation, ...] = Field(default=(), max_length=500)
    fixture_responses: tuple[FixtureResponseExpectation, ...] = Field(default=(), max_length=10000)
    resource_absence: ResourceAbsenceExpectation | None = None
    response_fields: tuple[ResponseFieldExpectation, ...] = Field(default=(), max_length=100)
    nested_nodes: tuple[NestedNodeExpectation, ...] = Field(default=(), max_length=1000)
    error_envelopes: tuple[ErrorEnvelopeExpectation, ...] = Field(default=(), max_length=20)
    resource_absences: tuple[ResourceAbsenceExpectation, ...] = Field(default=(), max_length=20)
    project_state: ProjectStateExpectation | None = None

    @model_validator(mode="after")
    def exact_failure(self) -> ExpectedOutcome:
        if self.execution_status == "failed" and (
            self.error_code is None or self.node_id is None or self.phase is None
        ):
            raise ValueError("失败期望必须同时固定错误码、节点和阶段")
        if self.execution_status == "passed" and any(
            value is not None for value in (self.error_code, self.node_id, self.phase)
        ):
            raise ValueError("成功期望不能携带失败位置")
        return self


class ScenarioExpectation(Contract):
    scenario_id: ScenarioId
    variant_key: Identity = "default"
    fixture_batch_key: Identity | None = None
    expected: ExpectedOutcome
    required_evidence: tuple[EvidenceKind, ...] = Field(min_length=1, max_length=7)
    required_oracle_ids: tuple[Identity, ...] = Field(default=(), max_length=500)
    expected_attempts: int = Field(default=1, ge=1, le=4)
    cleanup_required: bool = True
    require_suite_provenance: bool = False
    expected_api_sources: tuple[ApiSource, ...] = Field(default=(), max_length=100)
    expected_design_sources: tuple[DesignSource, ...] = Field(default=(), max_length=100)
    expected_combined_design_fingerprint: Sha256 | None = None
    expected_oracle_bindings: tuple[OracleBinding, ...] = Field(default=(), max_length=500)
    expected_mcp_calls: tuple[McpCallReceipt, ...] = Field(default=(), max_length=100)
    expected_suite: PublishedSuite | None = None
    expected_target_snapshot_digest: Sha256 | None = None

    @model_validator(mode="after")
    def required_assertion_expectations(self) -> ScenarioExpectation:
        if "assertions" in self.required_evidence and not self.expected.assertions:
            raise ValueError("必需断言证据必须具有独立黄金断言")
        if "response_fields" in self.required_evidence and not self.expected.response_fields:
            raise ValueError("必需响应字段证据必须具有独立字段黄金值")
        field_keys = [(item.node_id, item.field) for item in self.expected.response_fields]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("响应字段黄金值的节点与字段不能重复")
        return self

    @model_validator(mode="after")
    def frozen_provenance_expectations(self) -> ScenarioExpectation:
        if len(self.required_evidence) != len(set(self.required_evidence)):
            raise ValueError("必需证据类型不能重复")
        if len(self.required_oracle_ids) != len(set(self.required_oracle_ids)):
            raise ValueError("必需 Oracle ID 不能重复")
        call_ids = [item.call_id for item in self.expected_mcp_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("冻结 MCP 回执不能重复")
        if self.expected_oracle_bindings and (
            len({item.oracle_id for item in self.expected_oracle_bindings})
            != len(self.expected_oracle_bindings)
            or {item.oracle_id for item in self.expected_oracle_bindings}
            != set(self.required_oracle_ids)
        ):
            raise ValueError("冻结 Oracle 映射必须与必需集合完全对应")
        if self.require_suite_provenance and (
            self.expected_suite is None or self.expected_target_snapshot_digest is None
        ):
            raise ValueError("套件来源必须在执行前固定版本与计划展开摘要")
        if len(self.expected_api_sources) != len(set(self.expected_api_sources)):
            raise ValueError("冻结 API 来源不能重复")
        if self.expected_design_sources and (
            len(self.expected_design_sources) != len(set(self.expected_design_sources))
            or {item.api_source for item in self.expected_design_sources}
            != set(self.expected_api_sources)
        ):
            raise ValueError("冻结设计必须逐项覆盖完整 API 来源")
        return self


class BatchManifest(Contract):
    fixture_budget: FixtureBudgetScope | None = None
    format: Literal["flowtest-selftest"] = "flowtest-selftest"
    format_version: Literal[1] = 1
    pack_id: Identity
    pack_version: Identity
    pack_digest: Sha256
    policy_digest: Sha256
    project_id: UUID
    batch_key: Identity
    nonce: Identity
    builds: Builds
    fixture_epoch: Identity | None = None
    batch_kind: Literal["fixed_baseline", "mcp_generated"]
    generation_mode: Literal["deterministic_mcp", "host_llm_mcp"] | None = None
    verification_scope: Literal["full_pack", "selected_suites", "diagnostic_subset"]
    expected_scenario_set: tuple[ScenarioId, ...] = Field(min_length=1, max_length=500)
    required_scenario_set: tuple[ScenarioId, ...] = Field(min_length=1, max_length=500)
    trusted_required_scenario_set: tuple[ScenarioId, ...] = Field(default=(), max_length=500)
    scenarios: tuple[ScenarioExpectation, ...] = Field(min_length=1, max_length=500)
    ci_run_id: Identity | None = None
    ci_attempt: int | None = Field(default=None, ge=1)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def frozen_selection(self) -> BatchManifest:
        expected = set(self.expected_scenario_set)
        required = set(self.required_scenario_set)
        unique = (self.expected_scenario_set, self.required_scenario_set)
        if any(len(values) != len(set(values)) for values in unique):
            raise ValueError("场景集合不能包含重复 ID")
        if not required <= expected or not set(self.trusted_required_scenario_set) <= required:
            raise ValueError("选择器不能减少受信必测集合")
        if [item.scenario_id for item in self.scenarios] != list(self.expected_scenario_set):
            raise ValueError("期望定义必须与冻结执行集合逐项对应")
        if (self.batch_kind == "mcp_generated") != (self.generation_mode is not None):
            raise ValueError("MCP 批次必须固定生成模式")
        _validate_times(self.created_at, self.expires_at)
        if self.fixture_budget is not None and (
            self.fixture_budget.nonce != self.nonce
            or self.fixture_budget.expires_at != self.expires_at.timestamp()
        ):
            raise ValueError("目标预算必须固定同批nonce与不可延长的截止时间")
        return self


def _validate_times(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("时间必须含时区, 截止时间必须晚于开始时间")


class NodeEvidence(Contract):
    node_id: Identity
    node_type: Identity
    phase: Phase
    status: NodeStatus
    attempts: int = Field(ge=0, le=10000)
    error_code: Identity | None = None
    assertions: tuple[ObservedAssertion, ...] = Field(default=(), max_length=500)


class DatasetChildReference(Contract):
    execution_id: UUID
    row_index: int = Field(ge=0, le=499)
    status: RawStatus


class ExecutionEvidence(Contract):
    parent_execution_id: UUID | None = None
    dataset_row_index: int | None = Field(default=None, ge=0, le=499)
    dataset: DatasetBinding | None = None
    children: tuple[DatasetChildReference, ...] = Field(default=(), max_length=500)
    children_complete: StrictBool = True
    subflows: tuple[SubflowBinding, ...] = Field(default=(), max_length=100)
    subflows_complete: StrictBool = True
    id: UUID
    project_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    environment_id: UUID
    status: RawStatus
    error_code: Identity | None = None
    run_purpose: Literal["standard", "preview"] = "standard"
    main_status: Literal["passed", "failed", "cancelled"] | None = None
    cleanup_status: Literal["passed", "failed", "cancelled"] | None = None
    snapshot_digest: Sha256
    workflow_fingerprint: Sha256
    api_sources: tuple[ApiSource, ...] = Field(default=(), max_length=500)
    started_at: datetime
    completed_at: datetime | None = None
    nodes: tuple[NodeEvidence, ...] = Field(default=(), max_length=5000)
    nested_nodes: tuple[NodeEvidence, ...] = Field(default=(), max_length=1000)
    nested_nodes_complete: StrictBool = True

    @model_validator(mode="after")
    def execution_times(self) -> ExecutionEvidence:
        if self.started_at.tzinfo is None:
            raise ValueError("执行时间必须含时区")
        if self.completed_at is not None and (
            self.completed_at.tzinfo is None or self.completed_at < self.started_at
        ):
            raise ValueError("执行完成时间不合法")
        return self


class FixturePayload(Contract):
    actual: int | None = None
    code: int | None = None
    marker: SyntheticText | None = None
    value: JsonValue = None
    branch: SyntheticText | None = None
    iteration_key: SyntheticText | None = None
    request_count: int | None = Field(default=None, ge=0)
    fixture_epoch: Identity | None = None


class FixtureBinaryResponse(Contract):
    size_bytes: int = Field(ge=1, le=4096)
    sha256: Sha256
    content_type: Literal["application/octet-stream"]
    filename: Literal["flowtest.bin"]


class FixtureRequest(Contract):
    received_at: float | None = Field(default=None, ge=0)
    binary_request: FixtureBinaryResponse | None = None
    synthetic_cookie: SyntheticCookieSnapshot | None = None
    binary_response: FixtureBinaryResponse | None = None
    request_value_present: StrictBool | None = None
    sequence: int = Field(ge=1)
    method: Identity
    path: Annotated[str, Field(min_length=1, max_length=2048)]
    response_status: int = Field(ge=100, le=599)
    marker: SyntheticText | None = None
    request_body: FixturePayload | None = None
    response_body: FixturePayload | None = None
    authorization_present: StrictBool = False
    cookie_present: StrictBool = False
    fixture_epoch: Identity | None = None
    synthetic_precedence_header: SyntheticHeaderSnapshot | None = None

    @model_validator(mode="before")
    @classmethod
    def preserve_request_value_presence(cls, value: object) -> object:
        if not isinstance(value, dict) or "request_value_present" in value:
            return value
        body = value.get("request_body")
        return {
            **value,
            "request_value_present": "value" in body if isinstance(body, dict) else None,
        }


class FixtureJournal(Contract):
    budget: FixtureBudgetReceipt | None = None
    metrics: FixtureMetrics | None = None
    batch_key: Identity
    scenario_id: ScenarioId
    nonce: Identity
    fixture_epoch: Identity
    fixture_digest: Identity
    request_count: int = Field(ge=0, le=10000)
    entries: tuple[FixtureRequest, ...] = Field(default=(), max_length=10000)
    truncated: bool = False
    expired: bool = False
    epoch_changed: bool = False
    next_sequence: int | None = Field(default=None, ge=1)


class EvidencePage(Contract):
    page: int = Field(ge=1, le=1000)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0, le=100000)
    ordinals: tuple[int, ...] = Field(default=(), max_length=100)
    truncated: bool = False


class McpCallReceipt(Contract):
    call_id: Identity
    batch_key: Identity
    scenario_id: ScenarioId
    phase: Identity
    tool_name: Annotated[str, Field(pattern=r"^flowtest\.[a-z_]+$", max_length=160)]
    transport: Literal["stdio", "streamable-http"]
    sdk_version: Identity
    protocol_version: Identity
    request_digest: Sha256
    result_digest: Sha256
    catalog_digest: Sha256
    completed_at: datetime
    success: bool


class OracleBinding(Contract):
    oracle_id: Identity
    node_id: Identity
    phase: Phase = "main"
    assertion_name: Identity
    expression: Annotated[str, Field(min_length=1, max_length=2048)]
    expected_value_digest: Sha256


class ApiSource(Contract):
    project_id: UUID
    api_definition_id: UUID
    api_version: int = Field(ge=1)
    contract_fingerprint: Sha256


class DesignSource(Contract):
    api_source: ApiSource
    operation_ref: Identity
    scenario_id: Identity
    design_fingerprint: Sha256


class ProposalEvidence(Contract):
    project_id: UUID
    proposal_id: UUID
    item_id: UUID | None = None
    route: Literal["flow_spec", "controlled_write"]
    review_status: Literal["accepted", "pending", "rejected"]
    materialized_resource_id: UUID | None = None
    content_fingerprint: Sha256
    review_mode: Literal["ci_fixture", "human"]
    reviewer_id: UUID


class PublishedWorkflow(Contract):
    project_id: UUID
    id: UUID
    version_id: UUID
    version: int = Field(ge=1)
    fingerprint: Sha256
    api_sources: tuple[ApiSource, ...] = Field(default=(), max_length=500)
    assertions: tuple[OracleBinding, ...] = Field(min_length=1, max_length=500)


class PublishedCase(Contract):
    project_id: UUID
    id: UUID
    version: int = Field(ge=1)
    fingerprint: Sha256
    workflow_id: UUID
    workflow_version: int = Field(ge=1)
    environment_id: UUID


class SuiteCaseVersion(Contract):
    case_id: UUID
    version: int = Field(ge=1)


class SuiteReference(Contract):
    id: UUID
    version: int = Field(ge=1)


class PublishedSuite(Contract):
    project_id: UUID
    id: UUID
    version: int = Field(ge=1)
    fingerprint: Sha256
    case_versions: tuple[SuiteCaseVersion, ...] = Field(min_length=1, max_length=500)


class PlanRunSnapshot(Contract):
    project_id: UUID
    run_id: UUID
    run_item_id: UUID
    target_type: Literal["case"] = "case"
    target_id: UUID
    target_version: int = Field(ge=1)
    workflow_id: UUID
    workflow_version: int = Field(ge=1)
    environment_id: UUID
    execution_id: UUID
    attempts: int = Field(ge=0, le=4)
    status: Literal["queued", "running", "passed", "failed", "cancelled", "quarantined"]
    target_snapshot_digest: Sha256
    expected_target_snapshot_digest: Sha256 | None = None
    source_suite: SuiteReference | None = None


class HostEvidence(Contract):
    host: Identity
    model: Identity
    skill_digest: Sha256
    prompt_digest: Sha256
    authorized_budget_digest: Sha256
    actual_tool_calls: int = Field(ge=1)


class GenerationProvenance(Contract):
    batch_key: Identity
    scenario_id: ScenarioId
    generation_mode: Literal["deterministic_mcp", "host_llm_mcp"]
    api_source: ApiSource
    design_sources: tuple[DesignSource, ...] = Field(default=(), max_length=100)
    design_fingerprint: Sha256
    combined_design_fingerprint: Sha256 | None = None
    compilation_fingerprint: Sha256
    catalog_digest: Sha256
    oracle_bindings: tuple[OracleBinding, ...] = Field(min_length=1, max_length=500)
    calls: tuple[McpCallReceipt, ...] = Field(min_length=1, max_length=200)
    workflow_proposal: ProposalEvidence
    case_proposal: ProposalEvidence
    workflow: PublishedWorkflow
    case: PublishedCase
    suite: PublishedSuite | None = None
    run: PlanRunSnapshot
    generated_at: datetime
    frozen_at: datetime
    assisted: bool = False
    host: HostEvidence | None = None


class ScenarioObservation(Contract):
    created_file: CreatedFileEvidence | None = None
    synthetic_artifact: SyntheticArtifactEvidence | None = None
    target_disposal: TargetDisposalReceipt | None = None
    children: tuple[ExecutionEvidence, ...] = Field(default=(), max_length=500)
    children_complete: StrictBool = True
    scenario_id: ScenarioId
    variant_key: Identity = "default"
    execution: ExecutionEvidence | None = None
    attempts: tuple[ExecutionEvidence, ...] = Field(default=(), max_length=4)
    journal: FixtureJournal | None = None
    control_pages: tuple[EvidencePage, ...] = Field(default=(), max_length=1000)
    provenance: GenerationProvenance | None = None
    postcondition_matched: bool | None = None
    resource_absence: ResourceAbsenceEvidence | None = None
    response_fields: tuple[ResponseFieldEvidence, ...] = Field(default=(), max_length=100)
    error_envelopes: tuple[ErrorEnvelopeEvidence, ...] = Field(default=(), max_length=20)
    resource_absences: tuple[ResourceAbsenceEvidence, ...] = Field(default=(), max_length=20)
    project_state: ProjectStateEvidence | None = None
    cleanup_status: Literal["completed", "failed", "pending", "not_required"]
    evidence_complete: bool = True
    truncated: bool = False
    read_error: Identity | None = None


class BatchEvidence(Contract):
    batch_key: Identity
    nonce: Identity
    pack_digest: Sha256
    policy_digest: Sha256
    builds: Builds
    ci_run_id: Identity | None = None
    ci_attempt: int | None = Field(default=None, ge=1)
    collected_at: datetime
    scenarios: tuple[ScenarioObservation, ...] = Field(default=(), max_length=500)
    cleanup_status: Literal["completed", "failed", "pending"]
    observer_error: Identity | None = None
    expired: bool = False

    @model_validator(mode="after")
    def collection_time(self) -> BatchEvidence:
        if self.collected_at.tzinfo is None:
            raise ValueError("证据采集时间必须含时区")
        return self


class Finding(Contract):
    code: Identity
    status: VerificationStatus
    message: Annotated[str, Field(min_length=1, max_length=1000)]


class ScenarioVerification(Contract):
    scenario_id: ScenarioId
    variant_key: Identity
    expected: ExpectedOutcome
    observed_status: RawStatus | None
    execution_id: UUID | None
    verification_status: VerificationStatus
    findings: tuple[Finding, ...] = ()


class VerificationReport(Contract):
    schema_version: Literal["flowtest-verification-v1"] = "flowtest-verification-v1"
    batch_key: Identity
    pack_digest: Sha256
    verification_scope: Literal["full_pack", "selected_suites", "diagnostic_subset"]
    provenance: Literal["local_untrusted"] = "local_untrusted"
    evidence_integrity: Literal["complete", "missing", "expired"]
    batch_verdict: Literal["passed", "failed", "blocked"]
    exit_code: Literal[0, 1, 2]
    findings: tuple[Finding, ...] = ()
    scenarios: tuple[ScenarioVerification, ...]
