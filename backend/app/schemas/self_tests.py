"""Strict product and external-agent contracts for the self-test workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, Field(min_length=1, max_length=200)]
Reason = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")]
ScenarioId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")]
BatchKind = Literal["fixed_baseline", "mcp_generated"]
GenerationMode = Literal["deterministic_mcp", "host_llm_mcp"]
Readiness = Literal["ready", "needs_input", "needs_review", "unsupported", "blocked"]
GenerationStage = Literal[
    "discovering",
    "reading_contract",
    "designing",
    "compiling",
    "proposing",
    "awaiting_review",
    "publishing",
    "ready",
    "blocked",
    "cancelled",
]
BatchPhase = Literal[
    "pending",
    "generating",
    "awaiting_review",
    "ready",
    "running",
    "collecting",
    "completed",
    "cancelled",
    "expired",
]
Verdict = Literal["pending", "passed", "failed", "blocked"]
VerificationStatus = Literal[
    "pending", "matched", "mismatched", "incomplete", "error", "unsupported"
]
Provenance = Literal["local_untrusted", "trusted_ci"]
Integrity = Literal["complete", "missing", "expired"]
CleanupStatus = Literal["pending", "completed", "failed", "needs_review"]
RawStatus = Literal["queued", "running", "passed", "failed", "cancelled", "quarantined"]
Scope = Literal["full_pack", "selected_suites", "diagnostic_subset"]
ArtifactKind = Literal[
    "manifest",
    "generation",
    "evidence",
    "verification",
    "junit",
    "execution_junit",
    "verification_junit",
    "cleanup",
]
InstallationStatus = Literal["needs_input", "queued", "installing", "ready", "blocked", "archived"]
AgentCapability = Literal["install", "deterministic_mcp", "host_llm_mcp", "observe", "verify"]


class SelfTestDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SelfTestPage[T](SelfTestDTO):
    items: tuple[T, ...] = Field(max_length=100)
    next_cursor: UUID | None = None
    has_more: bool = False
    total: int = Field(ge=0)
    truncated: bool = False


class Actions(SelfTestDTO):
    can_initialize: bool = False
    can_generate: bool = False
    can_execute: bool = False
    can_cancel: bool = False
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)


class BuildIdentity(SelfTestDTO):
    runner: Identity
    target: Identity
    fixture: Identity
    verifier: Identity


class ScenarioKey(SelfTestDTO):
    scenario_id: ScenarioId
    variant_key: Identity = "default"


class ExpectedResult(SelfTestDTO):
    status: Literal["passed", "failed", "cancelled"]
    error_code: Reason | None = None
    phase: Literal["main", "cleanup"] | None = None


class TemplateScenario(ScenarioKey):
    title: Identity
    category: Literal["api", "engine", "mcp"]
    required: bool = True
    expected: ExpectedResult


class TemplateResponse(SelfTestDTO):
    id: Identity
    version: Identity = "1.0.0"
    title: Identity
    batch_kind: BatchKind
    pack_digest: Digest
    task_set_digest: Digest
    scenarios: tuple[TemplateScenario, ...] = Field(min_length=1, max_length=100)
    supported_modes: tuple[GenerationMode, ...] = Field(default=(), max_length=2)


class InstallationSummary(SelfTestDTO):
    id: UUID
    pack_digest: Digest
    status: InstallationStatus


class BindingResponse(SelfTestDTO):
    id: UUID
    name: Identity
    fingerprint: Digest
    environment_fingerprint: Digest
    runner_instance_id: Identity
    target_instance_id: Identity
    target_display: Identity
    fixture_display: Identity
    builds: BuildIdentity
    runtime_profile: Literal["full", "compact", "compose", "standalone"]
    host_status: Literal["available", "not_registered", "expired"]
    observer_status: Literal["available", "not_configured", "expired"]
    readiness: Readiness
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)
    installations: tuple[InstallationSummary, ...] = Field(default=(), max_length=20)
    actions: Actions


class InstallationPreviewRequest(SelfTestDTO):
    template_id: Identity
    template_version: Identity = "1.0.0"
    binding_id: UUID


class PreflightCheck(SelfTestDTO):
    code: Reason
    status: Literal["passed", "blocked", "warning"]
    message: Annotated[str, Field(min_length=1, max_length=500)]


class PlannedResource(SelfTestDTO):
    kind: Literal["environment", "service", "api", "workflow", "case", "suite", "plan"]
    action: Literal["create", "reuse", "conflict"]
    count: int = Field(ge=0, le=1000)


class InstallationPreviewResponse(SelfTestDTO):
    fingerprint: Digest
    expires_at: datetime
    binding_id: UUID
    template: TemplateResponse
    can_apply: bool
    checks: tuple[PreflightCheck, ...] = Field(min_length=1, max_length=30)
    resources: tuple[PlannedResource, ...] = Field(max_length=20)
    conflicts: tuple[Reason, ...] = Field(default=(), max_length=30)
    existing_installation_id: UUID | None = None


class InstallationCreate(InstallationPreviewRequest):
    preview_fingerprint: Digest
    preview_expires_at: datetime


class PublishedAsset(SelfTestDTO):
    id: UUID
    version: int = Field(ge=1)
    fingerprint: Digest


class ScenarioAssets(ScenarioKey):
    workflow: PublishedAsset
    case: PublishedAsset


class InstallationMapping(SelfTestDTO):
    environment_id: UUID
    target_environment_id: UUID
    fixture_service_id: UUID
    target_service_id: UUID
    target_project_id: UUID
    target_organization_id: UUID
    target_user_id: UUID
    target_instance_id: Identity
    target_build_digest: Identity
    assets: tuple[ScenarioAssets, ...] = Field(default=(), max_length=100)


class InstallationResponse(SelfTestDTO):
    id: UUID
    project_id: UUID
    binding_id: UUID
    template_id: Identity
    template_version: Identity = "1.0.0"
    pack_digest: Digest
    status: InstallationStatus
    revision: int = Field(ge=0)
    readiness: Readiness
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)
    environment_fingerprint: Digest
    mapping: InstallationMapping | None = None
    task_id: UUID
    created_at: datetime
    updated_at: datetime
    actions: Actions


class Budget(SelfTestDTO):
    timeout_seconds: int = Field(default=600, ge=30, le=600, strict=True)
    max_requests: int = Field(default=500, ge=1, le=500, strict=True)
    max_tool_calls: int = Field(default=100, ge=1, le=100, strict=True)


class BatchCreate(SelfTestDTO):
    scenario_ids: tuple[ScenarioId, ...] = Field(default=(), max_length=100)
    verification_scope: Scope = "full_pack"
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="after")
    def unique_scenarios(self) -> BatchCreate:
        if len(self.scenario_ids) != len(set(self.scenario_ids)):
            raise ValueError("场景不能重复")
        return self


class GenerationBatchCreate(BatchCreate):
    assisted_before_batch_id: UUID | None = None
    generation_mode: GenerationMode = "deterministic_mcp"
    host_id: Identity | None = None


class ArtifactReference(SelfTestDTO):
    id: UUID
    sha256: Digest
    kind: ArtifactKind


class ProposalReference(SelfTestDTO):
    change_set_id: UUID
    item_id: UUID | None = None
    route: Literal["flow_spec_visual", "controlled_write"]
    content_fingerprint: Digest
    review_status: Literal["pending", "accepted", "rejected"]
    materialized_resource_id: UUID | None = None


class APISourceReference(SelfTestDTO):
    project_id: UUID
    api_definition_id: UUID
    api_version: int = Field(ge=1)
    contract_fingerprint: Digest


class OracleReference(SelfTestDTO):
    oracle_id: Identity
    node_id: Identity
    phase: Literal["main", "cleanup"]
    expression: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_value_digest: Digest
    assertion_name: Identity = "workflow_assertion"


class RevisionDifference(SelfTestDTO):
    path: Annotated[
        str, Field(min_length=3, max_length=4096, pattern=r"^\$\.(workflow|case)(?:$|[.\[])")
    ]
    before_digest: Digest | None
    after_digest: Digest | None

    @model_validator(mode="after")
    def changed_value(self) -> RevisionDifference:
        if self.before_digest == self.after_digest:
            raise ValueError("修订差异必须包含实际变化")
        return self


class AssistedLineage(SelfTestDTO):
    authorization_digest: Digest
    before_batch_id: UUID
    origin_batch_id: UUID
    before_source_digest: Digest
    before_workflow: PublishedAsset
    before_case: PublishedAsset
    before_workflow_proposal: ProposalReference
    before_case_proposal: ProposalReference
    editor_id: UUID
    workflow_reviewer_id: UUID
    case_reviewer_id: UUID
    reason_digest: Digest
    diff_digest: Digest
    changes: tuple[RevisionDifference, ...] = Field(min_length=1, max_length=200)
    revision_number: int = Field(ge=1, le=20, strict=True)
    review_mode: Literal["human", "ci_fixture"]

    @model_validator(mode="after")
    def unique_paths(self) -> AssistedLineage:
        paths = [item.path for item in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("修订差异路径不能重复")
        return self


class SourceReference(ScenarioAssets):
    design_fingerprint: Digest
    compilation_fingerprint: Digest
    oracle_mapping_digest: Digest
    workflow_proposal: ProposalReference
    case_proposal: ProposalReference
    api_sources_digest: Digest
    api_sources: tuple[APISourceReference, ...] = Field(min_length=1, max_length=100)
    oracle_bindings: tuple[OracleReference, ...] = Field(min_length=1, max_length=500)
    protocol_receipts_digest: Digest
    generation_manifest: ArtifactReference
    host_evidence: HostEvidence | None = None
    fixture_batch_key: Identity | None = None
    assisted: AssistedLineage | None = None


class HostEvidence(SelfTestDTO):
    """One batch-wide call trail, repeated identically on every generated source."""

    host: Identity
    model: Identity
    skill_digest: Digest
    prompt_digest: Digest
    authorized_budget_digest: Digest
    actual_tool_calls: int = Field(ge=1, le=100, strict=True)


class AssistedBeforeSource(ScenarioKey):
    batch_id: UUID
    batch_key: Identity
    source: SourceReference
    source_digest: Digest
    artifacts: tuple[ArtifactReference, ...] = Field(min_length=1, max_length=100)
    sealed_at: datetime
    verdict: Literal["passed", "failed", "blocked"]
    evidence_integrity: Integrity
    cleanup_status: CleanupStatus
    resource_digest: Digest | None
    policy_digest: Digest
    builds: BuildIdentity


class ExecutionReference(SelfTestDTO):
    test_plan_run_id: UUID
    run_item_id: UUID
    execution_id: UUID | None
    target_version: int = Field(ge=1)
    target_snapshot_digest: Digest | None = None


class FrozenCaseReference(ScenarioAssets):
    environment_id: UUID
    target_snapshot_digest: Digest


class ResourceSnapshot(SelfTestDTO):
    suite: PublishedAsset
    plan_id: UUID
    cases: tuple[FrozenCaseReference, ...] = Field(min_length=1, max_length=100)


class GenerationSummary(SelfTestDTO):
    batch_id: UUID
    generation_mode: GenerationMode | None
    stage: GenerationStage
    readiness: Readiness
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)
    host_status: Literal["available", "not_registered", "expired"]
    tool_call_count: int = Field(default=0, ge=0, le=300)
    proposals: tuple[ProposalReference, ...] = Field(default=(), max_length=100)
    sources: tuple[SourceReference, ...] = Field(default=(), max_length=100)
    manifest: ArtifactReference | None = None
    actions: Actions


class BatchResponse(SelfTestDTO):
    id: UUID
    installation_id: UUID
    project_id: UUID
    binding_id: UUID
    batch_key: Identity
    batch_kind: BatchKind
    generation_mode: GenerationMode | None
    generation_stage: GenerationStage
    readiness: Readiness
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)
    phase: BatchPhase
    revision: int = Field(ge=0)
    verdict: Verdict
    sealed_verdict: Literal["passed", "failed", "blocked"] | None = None
    verification_scope: Scope
    provenance: Provenance
    evidence_integrity: Integrity
    cleanup_status: CleanupStatus
    expected_count: int = Field(ge=1, le=100)
    expected_scenario_set: tuple[ScenarioKey, ...] = Field(min_length=1, max_length=100)
    required_scenario_set: tuple[ScenarioKey, ...] = Field(min_length=1, max_length=100)
    manifest_digest: Digest
    resource_digest: Digest | None = None
    policy_digest: Digest
    binding_fingerprint: Digest
    environment_fingerprint: Digest
    builds: BuildIdentity
    deadline: datetime
    created_at: datetime
    updated_at: datetime
    sealed_at: datetime | None = None
    plan_run_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    plan_id: UUID | None = None
    suite: PublishedAsset | None = None
    resource_snapshot: ResourceSnapshot | None = None
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=100)
    actions: Actions


class ScenarioResultResponse(ScenarioKey):
    id: UUID
    batch_id: UUID
    title: Identity
    category: Literal["api", "engine", "mcp"]
    expected: ExpectedResult
    observed_status: RawStatus | None = None
    verification_status: VerificationStatus
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)
    generation_attempt: int = Field(ge=0, le=10)
    source: SourceReference | None = None
    published_assets: ScenarioAssets | None = None
    executions: tuple[ExecutionReference, ...] = Field(default=(), max_length=20)
    evidence_refs: tuple[ArtifactReference, ...] = Field(default=(), max_length=30)
    attempts_complete: bool


class ExecuteMaterializedRequest(SelfTestDTO):
    resource_digest: Digest
    environment_fingerprint: Digest
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("必须明确确认执行冻结资产")
        return value


class ScenarioExecutionRelation(SelfTestDTO):
    batch: BatchResponse
    scenario: ScenarioResultResponse
    execution_id: UUID


class AgentRegistrationRequest(SelfTestDTO):
    binding_id: UUID
    binding_fingerprint: Digest
    environment_fingerprint: Digest
    builds: BuildIdentity
    capabilities: tuple[AgentCapability, ...] = Field(min_length=1, max_length=5)
    host_id: Identity


class AgentRegistrationResponse(SelfTestDTO):
    agent_id: Identity
    binding_id: UUID
    expires_at: datetime
    installation_ids: tuple[UUID, ...] = Field(max_length=100)
    batch_ids: tuple[UUID, ...] = Field(max_length=100)


class LeaseClaim(SelfTestDTO):
    expected_revision: int = Field(ge=0, strict=True)
    nonce: Annotated[str, Field(min_length=32, max_length=200)]


class LeaseRequest(SelfTestDTO):
    lease_token: Annotated[str, Field(min_length=32, max_length=200)]
    nonce: Annotated[str, Field(min_length=32, max_length=200)]


class AgentTaskResponse(SelfTestDTO):
    task_kind: Literal["installation", "preparation", "generation", "observation"]
    task_id: UUID
    project_id: UUID
    binding_id: UUID
    agent_id: Identity
    revision: int = Field(ge=1)
    lease_token: Annotated[str, Field(min_length=32, max_length=200)]
    lease_expires_at: datetime
    nonce: Annotated[str, Field(min_length=32, max_length=200)]
    binding_fingerprint: Digest
    environment_fingerprint: Digest
    builds: BuildIdentity
    installation: InstallationResponse
    batch: BatchResponse | None = None
    budget: Budget
    frozen_manifest: FrozenBatchManifest | None = None
    sources: tuple[SourceReference, ...] = Field(default=(), max_length=100)
    before_sources: tuple[AssistedBeforeSource, ...] = Field(default=(), max_length=20)


class InstallationReceipt(LeaseRequest):
    environment_fingerprint: Digest
    mapping: InstallationMapping


class GenerationProgress(LeaseRequest):
    stage: GenerationStage
    readiness: Readiness
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)
    tool_call_count: int = Field(ge=0, le=100, strict=True)
    proposals: tuple[ProposalReference, ...] = Field(default=(), max_length=100)
    manifest: ArtifactReference | None = None


class MaterializedReceipt(LeaseRequest):
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=100)
    manifest: ArtifactReference


class VerificationScenario(ScenarioKey):
    observed_status: RawStatus | None
    verification_status: VerificationStatus
    reason_codes: tuple[Reason, ...] = Field(default=(), max_length=30)
    evidence_refs: tuple[ArtifactReference, ...] = Field(default=(), max_length=30)


class VerificationReceipt(LeaseRequest):
    manifest_digest: Digest
    resource_digest: Digest | None
    policy_digest: Digest
    builds: BuildIdentity
    ci_run_id: Identity | None = None
    ci_attempt: int | None = Field(default=None, ge=1)
    batch_verdict: Literal["passed", "failed", "blocked"]
    evidence_integrity: Integrity
    batch_reason_codes: tuple[Reason, ...] = Field(max_length=30)
    cleanup_status: CleanupStatus
    scenarios: tuple[VerificationScenario, ...] = Field(min_length=1, max_length=100)
    artifacts: tuple[ArtifactReference, ...] = Field(min_length=1, max_length=100)


class AgentTaskList(SelfTestDTO):
    installations: tuple[InstallationResponse, ...] = Field(max_length=100)
    batches: tuple[BatchResponse, ...] = Field(max_length=100)


class AgentArtifactUpload(LeaseRequest):
    kind: ArtifactKind
    filename: Annotated[str, Field(min_length=1, max_length=120)]
    content_type: Literal["application/json", "application/xml"] = "application/json"
    content_base64: Annotated[str, Field(min_length=1, max_length=2796204)]


class FrozenBatchManifest(SelfTestDTO):
    assisted_before_batch_id: UUID | None = None
    batch_id: UUID
    installation_id: UUID
    project_id: UUID
    binding_id: UUID
    template: TemplateResponse
    scenarios: tuple[TemplateScenario, ...] = Field(min_length=1, max_length=100)
    batch_kind: BatchKind
    generation_mode: GenerationMode | None
    verification_scope: Scope
    budget: Budget
    binding_fingerprint: Digest
    environment_fingerprint: Digest
    builds: BuildIdentity
    created_at: datetime
    deadline: datetime


class GenerationState(SelfTestDTO):
    tool_call_count: int = Field(default=0, ge=0, le=300)
    proposals: tuple[ProposalReference, ...] = Field(default=(), max_length=100)
    manifest: ArtifactReference | None = None
