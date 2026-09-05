"""Typed V6 extension of the existing change-regression snapshot."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.affected_flows import AffectedFlowsResponse
from app.schemas.context_inspector import ContextRevisionDiffResponse


class RegressionContextBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_id: UUID
    before_revision: int = Field(ge=1)
    after_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def forward_revisions(self) -> "RegressionContextBinding":
        if self.before_revision >= self.after_revision:
            raise ValueError("必须选择向前推进的两个上下文版本")
        return self


class RegressionProposalLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: UUID


class RegressionMaintenanceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=10, max_length=1000)
    acknowledge_incomplete_analysis: bool = False


class RegressionProposalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_set_id: UUID
    workflow_id: UUID
    review_status: Literal["pending", "accepted", "rejected"]
    applied: bool


class RegressionMaintenanceReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: UUID
    reviewed_at: datetime
    note: str
    acknowledged_incomplete_analysis: bool


class RegressionWorkflowEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    draft_revision: int
    workflow_version: int
    workflow_version_id: UUID
    fingerprint: str


class RegressionMaintenanceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["s47.4-change-regression-v4"] = "s47.4-change-regression-v4"
    impact_run_id: UUID
    context_diff_ref: str
    knowledge_diff_ref: str
    comparison: ContextRevisionDiffResponse
    affected: AffectedFlowsResponse
    proposals: list[RegressionProposalEvidence] = Field(default_factory=list, max_length=100)
    review: RegressionMaintenanceReviewEvidence | None = None
    required_workflows: list[RegressionWorkflowEvidence] = Field(default_factory=list)
    preview_counts_as_execution: Literal[False] = False
    automatic_apply_allowed: Literal[False] = False


def maintenance_snapshot(summary: dict[str, object]) -> RegressionMaintenanceSnapshot | None:
    raw = summary.get("context_maintenance")
    return RegressionMaintenanceSnapshot.model_validate(raw) if raw is not None else None
