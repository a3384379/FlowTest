"""Safe recovery hints; never substitute browser credentials for machine identity."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.mcp.client import MCPGatewayError


class ConnectionDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal[
        "AUTH_REQUIRED",
        "AUTH_EXPIRED",
        "SCOPE_REQUIRED",
        "SERVER_UNREACHABLE",
        "CONTRACT_VERSION_UNSUPPORTED",
        "FEATURE_DISABLED",
        "REQUEST_REJECTED",
    ]
    next_action: Literal[
        "configure_machine_account",
        "renew_machine_account",
        "request_scope",
        "check_server",
        "update_adapter",
        "request_feature",
        "inspect_request",
    ]
    setup_required: bool = False


def connection_diagnostic(error: MCPGatewayError) -> ConnectionDiagnostic:
    if error.code == "SERVICE_ACCOUNT_EXPIRED":
        return ConnectionDiagnostic(
            code="AUTH_EXPIRED", next_action="renew_machine_account", setup_required=True
        )
    if error.status_code == 401:
        return ConnectionDiagnostic(
            code="AUTH_REQUIRED", next_action="configure_machine_account", setup_required=True
        )
    if error.code in {
        "FEATURE_DISABLED",
        "AI_DISABLED",
        "QUALITY_INTELLIGENCE_DISABLED",
        "IMPACT_ENGINE_DISABLED",
    }:
        return ConnectionDiagnostic(code="FEATURE_DISABLED", next_action="request_feature")
    if error.code == "MCP_SCOPE_REQUIRED":
        return ConnectionDiagnostic(code="SCOPE_REQUIRED", next_action="request_scope")
    if error.code == "MCP_GATEWAY_UNAVAILABLE":
        return ConnectionDiagnostic(code="SERVER_UNREACHABLE", next_action="check_server")
    if error.code in {"CONTRACT_VERSION_UNSUPPORTED", "MCP_GATEWAY_INVALID_RESPONSE"}:
        return ConnectionDiagnostic(
            code="CONTRACT_VERSION_UNSUPPORTED", next_action="update_adapter"
        )
    return ConnectionDiagnostic(code="REQUEST_REJECTED", next_action="inspect_request")
