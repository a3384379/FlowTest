"""MCP request and response contracts for native control block proposals."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engine.contracts import WorkflowDefinition
from app.schemas.workflows import WorkflowControlBlockInsert

CONTROL_PROPOSAL_SCHEMA = "flow-control-block-v1"
CONTROL_WORKFLOW_PROPOSAL_SCHEMA = "flow-control-workflow-v1"


class MCPControlBlockProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    workflow_id: UUID
    edit: WorkflowControlBlockInsert


class MCPControlBlockProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    workflow_id: UUID
    base_revision: int
    proposal_id: UUID
    item_id: UUID
    status: Literal["draft"] = "draft"
    proposed_fingerprint: str
    review_url: str
    idempotency_replayed: bool = False


class MCPControlBlockPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    base_revision: int
    existing_definition: WorkflowDefinition
    proposed_definition: WorkflowDefinition


class MCPControlWorkflowDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    definition: WorkflowDefinition

    @model_validator(mode="after")
    def require_native_control_flow(self) -> "MCPControlWorkflowDraft":
        if not self.name.strip():
            raise ValueError("工作流名称不能为空")
        if self.definition.schema_version != "4.0" or not self.definition.regions:
            raise ValueError("控制流工作流提案必须使用 schema 4.0 和内联区域")
        if not any(
            node.capability_id and node.capability_id.startswith("flow.control.")
            for node in self.definition.nodes
        ):
            raise ValueError("控制流工作流提案必须包含主流程控制节点")
        return self


class MCPControlWorkflowProposalRequest(MCPControlWorkflowDraft):
    project_id: UUID


class MCPControlWorkflowProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    proposal_id: UUID
    item_id: UUID
    status: Literal["draft"] = "draft"
    proposed_fingerprint: str
    review_url: str
    idempotency_replayed: bool = False
