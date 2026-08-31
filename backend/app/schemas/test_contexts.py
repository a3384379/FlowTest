"""Strict API contracts for V6 test contexts and FlowSpec proposals."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.evidence_adapters import (
    DatabaseEvidenceSubmission,
    EntityMappingResult,
    JavaEvidenceSubmission,
    JavaSourceInput,
)
from app.domain.flow_spec import FlowSpec
from app.domain.flow_spec_v2 import FlowSpecV2
from app.domain.integration_plans import (
    IntegrationPlan,
    IntegrationPlanCompilation,
    PlanActor,
    PlanCleanupRequirement,
    PlanDatabaseRead,
    PlanDataRecipe,
    PlanDiagnostic,
    PlanOracle,
    PlanPrecondition,
    PlanTargetEnvironment,
    PlanValidationResult,
)
from app.domain.test_contexts import (
    ContextKnowledgeSnapshot,
    ContextRevisionSnapshot,
    EvidenceProviderType,
    EvidenceSemanticRole,
    ExternalEvidenceEnvelope,
    RevisionReference,
    TestContextStatus,
)
from app.engine.contracts import WorkflowDefinition


class BeginTestContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4000)
    target_environment_id: UUID | None = None
    ttl_seconds: int = Field(default=3600, ge=60, le=30 * 24 * 3600)
    required_evidence: list[EvidenceProviderType] = Field(
        default_factory=lambda: [EvidenceProviderType.CONTRACT], min_length=1, max_length=20
    )
    repository_revisions: list[RevisionReference] = Field(default_factory=list, max_length=100)
    contract_revisions: list[RevisionReference] = Field(default_factory=list, max_length=100)
    data_profile_revisions: list[RevisionReference] = Field(default_factory=list, max_length=100)
    existing_test_revision: RevisionReference | None = None
    knowledge_snapshot: ContextKnowledgeSnapshot = Field(default_factory=ContextKnowledgeSnapshot)

    @field_validator("name", "objective")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("上下文名称和目标不能为空")
        return normalized


class IngestExternalEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: ExternalEvidenceEnvelope


class IngestJavaEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: JavaEvidenceSubmission


class JavaSourceFilePayload(BaseModel):
    """MCP transport shape; bounded source validation runs inside the redacted tool boundary."""

    model_config = ConfigDict(extra="forbid")

    path: str
    content: str


class IngestJavaSourceSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: JavaSourceInput


class IngestDatabaseEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: DatabaseEvidenceSubmission


class ContextEvidenceItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_type: EvidenceProviderType
    provider_name: str
    provider_version: str
    source_ref: str
    source_revision: str
    subject_ref: str
    semantic_role: EvidenceSemanticRole
    deterministic: bool
    confidence: float
    fingerprint: str
    data_classification: Literal["internal_redacted"] = "internal_redacted"
    created_at: datetime
    expires_at: datetime


class TestContextRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    context_id: UUID
    revision: int
    fingerprint: str
    snapshot: ContextRevisionSnapshot
    created_at: datetime


class TestContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    objective: str
    target_environment_id: UUID | None
    status: TestContextStatus
    current_revision: int
    created_by_type: Literal["user", "service_account"]
    created_by_id: UUID
    expires_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    revision: TestContextRevisionResponse
    evidence_items: list[ContextEvidenceItemResponse]


class EvidenceAdapterIngestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: TestContextResponse
    entity_mapping: EntityMappingResult


class JavaSourceSnapshotIngestionResponse(EvidenceAdapterIngestionResponse):
    analysis: JavaEvidenceSubmission


class ContextRequirementsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_id: UUID
    context_revision_id: UUID
    context_fingerprint: str
    status: TestContextStatus
    required: list[EvidenceProviderType]
    present: list[EvidenceProviderType]
    missing: list[EvidenceProviderType]
    complete: bool
    conflict_count: int
    expires_at: datetime


class IntegrationPlanOperationSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: UUID
    scenario_id: str | None = Field(default=None, min_length=1, max_length=160)


class ExistingAuthWorkflowSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    workflow_version: int = Field(ge=1)
    token_path: str = Field(min_length=1, max_length=500)
    step_id: str = Field(default="existing-auth", pattern=r"^[A-Za-z_][A-Za-z0-9_.:-]{0,119}$")


class IntegrationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    context_id: UUID
    context_revision_id: UUID
    actors: list[PlanActor] = Field(min_length=1, max_length=50)
    preconditions: list[PlanPrecondition] = Field(default_factory=list, max_length=100)
    target_environment: PlanTargetEnvironment
    operations: list[IntegrationPlanOperationSelectionRequest] = Field(
        min_length=1, max_length=1000
    )
    existing_auth: ExistingAuthWorkflowSelectionRequest | None = None
    data_recipes: list[PlanDataRecipe] = Field(default_factory=list, max_length=500)
    database_reads: list[PlanDatabaseRead] = Field(default_factory=list, max_length=200)
    additional_oracles: list[PlanOracle] = Field(default_factory=list, max_length=2000)
    cleanup_requirements: list[PlanCleanupRequirement] = Field(default_factory=list, max_length=200)


class IntegrationPlanValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: IntegrationPlan


class IntegrationPlanCompileRequest(IntegrationPlanValidateRequest):
    pass


class CompilerDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-compiler-diagnostics-v1"] = "flowtest-compiler-diagnostics-v1"
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    importable: bool
    diagnostics: list[PlanDiagnostic] = Field(default_factory=list, max_length=500)
    blocker_codes: list[str] = Field(default_factory=list, max_length=500)
    review_codes: list[str] = Field(default_factory=list, max_length=500)
    next_actions: list[str] = Field(default_factory=list, max_length=500)


class FlowSpecProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    context_id: UUID
    context_revision_id: UUID
    spec: FlowSpec | FlowSpecV2
    workflow_id: UUID | None = None
    source_ref: str | None = Field(
        default=None,
        pattern=r"^mcp://[A-Za-z0-9._/-]{1,480}$",
        max_length=512,
    )
    service_mappings: dict[str, UUID] = Field(default_factory=dict, max_length=500)
    operation_mappings: dict[str, UUID] = Field(default_factory=dict, max_length=1000)
    operation_version_mappings: dict[str, int] = Field(default_factory=dict, max_length=1000)
    expected_revision: int | None = Field(default=None, ge=1)
    integration_plan: IntegrationPlan | None = None
    compilation: IntegrationPlanCompilation | None = None
    dry_run: bool = True

    @model_validator(mode="after")
    def validate_proposal_contract(self) -> "FlowSpecProposalRequest":
        if self.workflow_id is not None and self.expected_revision is None:
            raise ValueError("更新现有 Workflow 必须提供 Expected Revision")
        if self.workflow_id is None and self.expected_revision is not None:
            raise ValueError("新建 Workflow Proposal 不接受 Expected Revision")
        if (self.integration_plan is None) != (self.compilation is None):
            raise ValueError("Integration Plan 与 Compilation 必须同时提供")
        return self


class IntegrationPlanValidationResponse(PlanValidationResult):
    pass


class FlowSpecProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-flow-proposal-adapter-v1"] = (
        "flowtest-flow-proposal-adapter-v1"
    )
    dry_run: bool
    status: Literal["preview", "draft"]
    context_id: UUID
    context_revision_id: UUID
    context_fingerprint: str
    flow_spec_fingerprint: str
    source_ref: str
    change_set_id: UUID | None
    target_workflow_id: UUID | None
    target_revision: int | None
    warnings: list[str] = Field(default_factory=list, max_length=100)


class FlowSpecProposalInspectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-flow-proposal-inspection-v1"] = (
        "flowtest-flow-proposal-inspection-v1"
    )
    change_set_id: UUID
    project_id: UUID
    status: str
    review_status: Literal["pending", "accepted", "rejected"]
    applied: bool
    target_workflow_id: UUID | None
    target_revision: int | None
    context_revision_id: UUID | None
    context_fingerprint: str | None
    integration_plan: IntegrationPlan | None
    compilation: IntegrationPlanCompilation | None
    existing_definition: WorkflowDefinition | None
    proposed_definition: WorkflowDefinition
