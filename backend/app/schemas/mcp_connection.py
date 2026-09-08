"""Versioned, secret-free machine-connection diagnostics."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.runtime_profiles import RuntimeProfile

MCP_CONNECTION_VERSION: Literal["s61-mcp-connection-v1"] = "s61-mcp-connection-v1"
ConnectionAction = Literal[
    "inspect_connection",
    "read_authorized_assets",
    "propose_test_design",
    "write_context_evidence",
    "propose_flow",
    "request_approved_sandbox_preview",
    "bootstrap_project_assets",
]


class MCPConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_contract_version: str | None = Field(default=None, min_length=1, max_length=80)


class MCPConnectionFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    integration_flow: bool
    advanced_workflows: bool
    change_impact: bool
    ai: bool
    quality_intelligence: bool


class MCPConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["s61-mcp-connection-v1"] = MCP_CONNECTION_VERSION
    server_version: str
    client_contract_version: str
    application_version: str
    principal_type: Literal["service_account"] = "service_account"
    credential_status: Literal["valid"] = "valid"
    organization_id: UUID
    organization_name: str
    service_account_id: UUID
    expires_at: datetime | None
    effective_scopes: list[str]
    available_actions: list[ConnectionAction]
    features: MCPConnectionFeatures
    runtime_profile: RuntimeProfile
    next_action: Literal["inspect_projects", "request_scope"]
    human_review_required: Literal[True] = True
    trace_id: str
