"""Bounded, review-only MCP contracts for continuous quality workflows."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.failure_repair import RepairProposalCreate
from app.schemas.maintenance_proposals import MaintenanceProposalCreate
from app.schemas.regression_maintenance import (
    RegressionProposalEvidence,
    RegressionWorkflowEvidence,
)

MCP_CONTINUOUS_QA_VERSION = "s60-continuous-qa-v1"


class MCPContextComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    context_id: UUID
    before_revision: int = Field(ge=1)
    after_revision: int = Field(ge=1)


class MCPAffectedFlowsRequest(MCPContextComparisonRequest):
    impact_run_id: UUID | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class MCPFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    execution_id: UUID


class MCPRegressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    run_id: UUID


class MCPRepairRequest(MCPFailureRequest):
    repair: RepairProposalCreate
    dry_run: bool = True


class MCPMaintenanceRequest(MCPRegressionRequest):
    workflow_id: UUID
    maintenance: MaintenanceProposalCreate
    dry_run: bool = True


class MCPContinuousProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-mcp-continuous-proposal-v1"] = (
        "flowtest-mcp-continuous-proposal-v1"
    )
    project_id: UUID
    proposal_origin: Literal["repair", "maintenance"]
    dry_run: bool
    change_set_id: UUID | None
    target_workflow_id: UUID
    target_revision: int = Field(ge=1)
    context_revision_id: UUID
    regression_run_id: UUID | None = None
    requires_human_review: Literal[True] = True
    applied: Literal[False] = False
    trace_id: str

    @model_validator(mode="after")
    def require_proposal_identity(self) -> "MCPContinuousProposalResponse":
        if self.dry_run != (self.change_set_id is None):
            raise ValueError("only a persisted proposal can have a change_set_id")
        return self


class MCPRegressionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    run_id: UUID
    status: str
    impact_run_id: UUID
    test_plan_id: UUID
    test_plan_run_id: UUID | None
    release_decision_id: UUID | None
    context_diff_ref: str | None
    knowledge_diff_ref: str | None
    analysis_complete: bool | None
    proposals: list[RegressionProposalEvidence]
    required_workflows: list[RegressionWorkflowEvidence]
    preview_counts_as_execution: Literal[False] = False
    automatic_apply_allowed: Literal[False] = False
