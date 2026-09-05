"""Read-only project contracts for inspecting V6 test-context evidence."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.context_diff import ContextDiff
from app.domain.test_contexts import (
    ContextCompletenessSnapshot,
    ContextRevisionSnapshot,
    EvidenceProviderType,
    EvidenceSemanticRole,
    ExternalEvidenceFinding,
    ExternalEvidenceWarning,
    TestContextStatus,
)


class ContextInspectorProviderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: EvidenceProviderType
    provider_name: str
    provider_version: str
    finding_count: int = Field(ge=0)
    deterministic_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)


class ContextInspectorProposalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    status: str
    review_status: Literal["pending", "accepted", "rejected"]
    applied: bool
    target_workflow_id: UUID | None
    target_revision: int | None
    source_ref: str | None
    created_at: datetime
    updated_at: datetime


class ContextInspectorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    name: str
    objective: str
    status: TestContextStatus
    current_revision: int = Field(ge=1)
    revision_id: UUID
    revision_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    completeness: ContextCompletenessSnapshot
    conflict_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    provider_count: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class ContextInspectorEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_type: EvidenceProviderType
    provider_name: str
    provider_version: str
    source_ref: str
    source_revision: str
    subject_ref: str
    finding: ExternalEvidenceFinding
    semantic_role: EvidenceSemanticRole
    deterministic: bool
    confidence: float = Field(ge=0, le=1)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    warnings: list[ExternalEvidenceWarning]
    redaction_count: int = Field(ge=0)
    created_at: datetime
    expires_at: datetime


class ContextInspectorDetail(ContextInspectorSummary):
    organization_id: UUID
    target_environment_id: UUID | None
    created_by_type: Literal["user", "service_account"]
    created_by_id: UUID
    closed_at: datetime | None
    revision: ContextRevisionSnapshot
    providers: list[ContextInspectorProviderSummary]
    evidence_items: list[ContextInspectorEvidenceItem]
    proposals: list[ContextInspectorProposalSummary]


class ContextRevisionDiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    context_id: UUID
    before_revision: int
    after_revision: int
    before_revision_id: UUID
    after_revision_id: UUID
    difference: ContextDiff
