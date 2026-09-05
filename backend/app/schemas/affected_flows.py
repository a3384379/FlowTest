"""Read-only, bounded affected-flow analysis responses."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.affected_flows import MatchStrength


class AffectedFlowReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str | None
    source_ref: str
    match_strength: MatchStrength | Literal["explicit_asset"]
    api_definition_id: str | None = None
    api_version: int | None = None
    contract_fingerprint: str | None = None
    asset_version: int | None = None
    knowledge_relation: Literal["explicit", "heuristic"] | None = None
    changed_knowledge_node_ids: tuple[str, ...] = ()


class AffectedWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    draft_revision: int
    reasons: list[AffectedFlowReason] = Field(max_length=100)


class AffectedFlowDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "WORKFLOW_INVALID",
        "API_UNRESOLVED",
        "NODE_NOT_ANALYZED",
        "RESULT_TRUNCATED",
        "WORKFLOW_NODE_BUDGET_EXCEEDED",
        "IMPACT_CHANGE_UNMAPPED",
        "CONTEXT_CHANGE_UNMAPPED",
        "KNOWLEDGE_IDENTITY_AMBIGUOUS",
    ]
    workflow_id: UUID | None = None
    node_id: str | None = None
    source_ref: str | None = None


class AffectedFlowsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-affected-flows-v1"] = "flowtest-affected-flows-v1"
    project_id: UUID
    context_id: UUID
    before_revision_id: UUID
    after_revision_id: UUID
    before_fingerprint: str
    after_fingerprint: str
    page: int
    page_size: int
    total_workflows: int
    scanned_workflow_ids: list[UUID]
    affected_workflows: list[AffectedWorkflow]
    diagnostics: list[AffectedFlowDiagnostic]
    analysis_complete: bool
    requires_review: Literal[True] = True
    automatic_patch_allowed: Literal[False] = False
