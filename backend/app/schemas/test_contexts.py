"""Strict API contracts for V6 test contexts and FlowSpec proposals."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.flow_spec import FlowSpec
from app.domain.test_contexts import (
    ContextKnowledgeSnapshot,
    ContextRevisionSnapshot,
    EvidenceProviderType,
    EvidenceSemanticRole,
    ExternalEvidenceEnvelope,
    RevisionReference,
    TestContextStatus,
)


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


class FlowSpecProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    context_id: UUID
    context_revision_id: UUID
    spec: FlowSpec
    workflow_id: UUID | None = None
    source_ref: str | None = Field(
        default=None,
        pattern=r"^mcp://[A-Za-z0-9._/-]{1,480}$",
        max_length=512,
    )
    service_mappings: dict[str, UUID] = Field(default_factory=dict, max_length=500)
    operation_mappings: dict[str, UUID] = Field(default_factory=dict, max_length=1000)
    operation_version_mappings: dict[str, int] = Field(default_factory=dict, max_length=1000)
    dry_run: bool = True


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
