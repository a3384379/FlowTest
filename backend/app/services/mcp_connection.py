"""Connection diagnostics use the authenticated account, never its creator's privileges."""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_trace_id
from app.core.errors import AppError
from app.core.redaction import redaction_enabled
from app.domain.test_contexts import first_sensitive_value
from app.models.organizations import Organization, ServiceAccount
from app.schemas.mcp_connection import (
    MCP_CONNECTION_VERSION,
    ConnectionAction,
    MCPConnectionFeatures,
    MCPConnectionRequest,
    MCPConnectionResponse,
)


class MCPConnectionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def inspect(
        self, *, account: ServiceAccount, payload: MCPConnectionRequest, client_version: str
    ) -> MCPConnectionResponse:
        organization = await self._session.get(Organization, account.organization_id)
        if organization is None or not organization.enabled:
            raise AppError(code="AUTH_REQUIRED", message="机器账号所属组织不可用", status_code=401)
        if payload.expected_contract_version not in {None, MCP_CONNECTION_VERSION}:
            raise AppError(
                code="CONTRACT_VERSION_UNSUPPORTED",
                message="连接契约版本不受支持, 请更新客户端 Adapter 后重新检查",
                status_code=409,
            )
        scopes = sorted(account.scopes)
        name = organization.name
        if redaction_enabled() and first_sensitive_value({"name": name}) is not None:
            name = "已授权组织"
        return MCPConnectionResponse(
            server_version=MCP_CONNECTION_VERSION,
            client_contract_version=(
                client_version
                if re.fullmatch(
                    r"(?:flowtest-mcp-s[0-9]+|s[0-9]+-mcp-[a-z-]+-v[0-9]+)", client_version
                )
                else "unknown"
            ),
            application_version=settings.app_version,
            organization_id=organization.id,
            organization_name=name,
            service_account_id=account.id,
            expires_at=account.expires_at,
            effective_scopes=scopes,
            available_actions=_available_actions(frozenset(scopes)),
            features=MCPConnectionFeatures(
                integration_flow=settings.feature_integration_flow_enabled,
                advanced_workflows=settings.feature_advanced_workflows_enabled,
                change_impact=settings.feature_impact_engine_enabled,
                ai=settings.feature_ai_enabled,
                quality_intelligence=settings.feature_quality_intelligence_enabled,
            ),
            runtime_profile=settings.runtime_profile,
            next_action="inspect_projects" if "mcp:read" in scopes else "request_scope",
            trace_id=get_trace_id(),
        )


def _available_actions(scopes: frozenset[str]) -> list[ConnectionAction]:
    # These are action groups, not claims that every future tool is already installed.
    actions: list[ConnectionAction] = ["inspect_connection"]
    actions.extend(_read_and_import_actions(scopes))
    actions.extend(_design_actions(scopes))
    actions.extend(_integration_actions(scopes))
    actions.extend(_planning_actions(scopes))
    return actions


def _read_and_import_actions(scopes: frozenset[str]) -> list[ConnectionAction]:
    actions: list[ConnectionAction] = []
    if "mcp:read" in scopes:
        actions.append("read_authorized_assets")
    if "mcp:project:bootstrap" in scopes:
        actions.append("bootstrap_project_assets")
    if "mcp:contract:import" in scopes:
        actions.append("import_contract")
    return actions


def _design_actions(scopes: frozenset[str]) -> list[ConnectionAction]:
    if (
        "mcp:write" in scopes
        and settings.feature_ai_enabled
        and settings.feature_quality_intelligence_enabled
    ):
        return ["propose_test_design"]
    return []


def _integration_actions(scopes: frozenset[str]) -> list[ConnectionAction]:
    if not settings.feature_integration_flow_enabled:
        return []
    actions: list[ConnectionAction] = []
    if "mcp:evidence:write" in scopes:
        actions.append("write_context_evidence")
    if "mcp:flow:propose" in scopes:
        actions.append("propose_flow")
    if "mcp:preview:execute" in scopes:
        actions.extend(["request_approved_sandbox_preview", "cancel_sandbox_preview"])
    return actions


def _planning_actions(scopes: frozenset[str]) -> list[ConnectionAction]:
    actions: list[ConnectionAction] = []
    if "mcp:regression:prepare" in scopes:
        actions.append("prepare_change_regression")
    if "mcp:test-plan:propose" in scopes:
        actions.append("propose_test_plan_update")
    return actions
