"""MCP request and response contracts for native control block proposals."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.workflows import WorkflowControlBlockInsert

CONTROL_PROPOSAL_SCHEMA = "flow-control-block-v1"


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
