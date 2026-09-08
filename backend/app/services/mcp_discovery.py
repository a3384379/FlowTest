"""MCP resource discovery, project readiness and registered-target diagnostics."""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context, get_trace_id
from app.core.errors import AppError
from app.domain.mcp_read import EvidenceRef, MCPReadCall, MCPReadEnvelope
from app.domain.test_contexts import first_sensitive_value
from app.models.access import User
from app.models.ai import AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.service_targets import ServiceEndpoint
from app.models.test_contexts import ContextEvidenceItem, TestContext, TestContextRevision
from app.repositories.mcp_assets import MCPAssetRepository, MCPAssetRow
from app.schemas.mcp_discovery import (
    MCPAssetSummary,
    MCPFindAssetsRequest,
    MCPFindAssetsResponse,
    MCPProjectReadinessResponse,
    MCPReadinessCheck,
    MCPServiceTargetCheckResponse,
)
from app.schemas.service_targets import ServiceEndpointConnectivityResponse
from app.services.mcp_bootstrap import MCP_PROJECT_BOOTSTRAP_SCOPE
from app.services.mcp_read import MCPReadService, _safe_origin
from app.services.projects import ProjectService
from app.services.service_targets import ServiceTargetService

_CREDENTIAL_REFERENCE_KEYS = frozenset(
    {
        "auth_binding",
        "auth_bindings",
        "auth_ref",
        "auth_refs",
        "credential_binding",
        "credential_bindings",
        "credential_ref",
        "credential_refs",
        "secret_ref",
        "secret_refs",
        "token_ref",
        "token_refs",
    }
)
_SECRET_REFERENCE = re.compile(r"^secret://[A-Za-z0-9._:/-]{1,480}$")


class MCPDiscoveryService(MCPReadService):
    """Keep discovery on the existing read/audit boundary and repositories."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._asset_discovery = MCPAssetRepository(session)

    async def find_assets(
        self,
        *,
        actor: User,
        payload: MCPFindAssetsRequest,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_scope()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=False)
        rows, total = await self._asset_discovery.find_assets(
            project_id=payload.project_id,
            asset_types=payload.asset_types,
            query=payload.query,
            method=payload.method,
            path=payload.path,
            source=payload.source,
            offset=(payload.page - 1) * payload.page_size,
            limit=payload.page_size,
        )
        items = [self._asset_summary(row) for row in rows]
        response = MCPFindAssetsResponse(
            project_id=payload.project_id,
            items=items,
            total=total,
            page=payload.page,
            page_size=payload.page_size,
            has_more=payload.page * payload.page_size < total,
            next_page=payload.page + 1 if payload.page * payload.page_size < total else None,
        )
        return await self._envelope(
            actor=actor,
            project_id=payload.project_id,
            call=call,
            data=cast(JsonValue, response.model_dump(mode="json")),
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://projects/{payload.project_id}/assets",
                    kind="asset-discovery",
                    version="flowtest-mcp-asset-discovery-v1",
                )
            ],
            redactions=[
                "asset.description",
                "asset.variables",
                "asset.headers",
                "asset.request_body",
                "asset.response_body",
                "asset.credentials",
            ],
        )

    async def inspect_project_readiness(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_scope()
        access = await self._projects.get(actor=actor, project_id=project_id)
        tenant = get_tenant_context()
        scopes = tenant.scopes if tenant is not None else frozenset()
        now = datetime.now(UTC)

        api_count = await self._count(
            select(func.count())
            .select_from(APIDefinition)
            .where(
                APIDefinition.project_id == project_id,
                APIDefinition.is_active.is_(True),
            )
        )
        endpoint_count = await self._count(
            select(func.count())
            .select_from(ServiceEndpoint)
            .where(
                ServiceEndpoint.project_id == project_id,
                ServiceEndpoint.enabled.is_(True),
            )
        )
        context_count = await self._count(
            select(func.count())
            .select_from(TestContext)
            .where(TestContext.project_id == project_id)
        )
        ready_context_count = await self._count(
            select(func.count())
            .select_from(TestContext)
            .where(
                TestContext.project_id == project_id,
                TestContext.status == "ready",
                TestContext.expires_at > now,
            )
        )
        auth_reference_count = await self._count(
            select(func.count())
            .select_from(APIVersion)
            .join(APIDefinition, APIDefinition.id == APIVersion.api_definition_id)
            .where(
                APIDefinition.project_id == project_id,
                APIVersion.auth_kind != "none",
                APIVersion.version == APIDefinition.current_version,
            )
        )
        current_runtime_evidence = list(
            (
                await self._session.scalars(
                    select(ContextEvidenceItem)
                    .join(
                        TestContextRevision,
                        TestContextRevision.id == ContextEvidenceItem.context_revision_id,
                    )
                    .join(TestContext, TestContext.id == TestContextRevision.context_id)
                    .where(
                        TestContext.project_id == project_id,
                        TestContext.status == "ready",
                        TestContext.expires_at > now,
                        TestContextRevision.revision == TestContext.current_revision,
                        ContextEvidenceItem.source_type == "runtime",
                        ContextEvidenceItem.expires_at > now,
                    )
                    .limit(2000)
                )
            ).all()
        )
        credential_evidence_count = sum(
            1
            for item in current_runtime_evidence
            if _has_credential_reference(item.finding_payload)
        )
        database_evidence_count = await self._count(
            select(func.count())
            .select_from(ContextEvidenceItem)
            .join(
                TestContextRevision,
                TestContextRevision.id == ContextEvidenceItem.context_revision_id,
            )
            .join(TestContext, TestContext.id == TestContextRevision.context_id)
            .where(
                TestContext.project_id == project_id,
                ContextEvidenceItem.source_type == "database",
            )
        )
        preview_environment_count = await self._count(
            select(func.count())
            .select_from(Environment)
            .where(
                Environment.project_id == project_id,
                Environment.classification.in_(["test", "sandbox"]),
            )
        )
        accepted_proposal_count = await self._count(
            select(func.count())
            .select_from(AIChangeSet)
            .where(
                AIChangeSet.project_id == project_id,
                AIChangeSet.status == "accepted",
                AIChangeSet.applied_at.is_(None),
                AIChangeSet.source_type.in_(["flow_spec", "mcp", "change_regression"]),
            )
        )

        checks: list[MCPReadinessCheck] = [
            MCPReadinessCheck(
                name="project_access",
                state="ready",
                detail=f"已授权访问项目 {access.project.name[:120]}",
            ),
            MCPReadinessCheck(
                name="integration_flow_feature",
                state="ready" if _feature_enabled() else "not_configured",
                detail="Integration Flow 功能开关已启用"
                if _feature_enabled()
                else "Integration Flow 功能开关未启用",
                action=None if _feature_enabled() else "请由管理员启用 Integration Flow 功能",
            ),
            MCPReadinessCheck(
                name="contract",
                state="ready" if api_count else "missing",
                detail=f"已发现 {api_count} 个启用的 API 定义",
                action=None if api_count else "请导入或提交至少一个 API Contract",
            ),
            MCPReadinessCheck(
                name="service_endpoint",
                state="ready" if endpoint_count else "missing",
                detail=f"已登记 {endpoint_count} 个启用的 Service Endpoint",
                action=None if endpoint_count else "请登记测试或 Sandbox Service Endpoint",
            ),
            MCPReadinessCheck(
                name="test_context",
                state="ready"
                if ready_context_count
                else ("degraded" if context_count else "missing"),
                detail=(
                    f"有 {ready_context_count} 个未过期 Ready Context"
                    if ready_context_count
                    else "存在 Context，但没有可用的未过期 Ready Revision"
                    if context_count
                    else "尚未建立 Test Context"
                ),
                action=None if ready_context_count else "请建立或补齐 Context/Evidence 后重新检查",
            ),
            MCPReadinessCheck(
                name="flowtest_mcp_token",
                state="ready" if tenant is not None else "not_authorized",
                detail="当前请求使用已认证的 MCP 机器身份；不会返回令牌",
                action=None if tenant is not None else "请使用有效的 MCP Service Account Token",
            ),
            MCPReadinessCheck(
                name="business_test_credentials",
                state="ready"
                if (not auth_reference_count or credential_evidence_count)
                else "missing",
                detail=(
                    "已记录认证引用元数据；凭据值不会通过 MCP 返回"
                    if (not auth_reference_count or credential_evidence_count)
                    else "Contract 需要认证，但尚未发现运行期凭据引用"
                ),
                action=(
                    None
                    if (not auth_reference_count or credential_evidence_count)
                    else "请在授权凭据入口绑定若依等业务测试凭据"
                ),
            ),
            MCPReadinessCheck(
                name="db_runtime_readonly",
                state="ready" if database_evidence_count else "not_configured",
                detail=(
                    "已记录只读数据库证据引用；连接信息不会通过 MCP 返回"
                    if database_evidence_count
                    else "未配置数据库运行期只读引用（API-only 流程仍可继续）"
                ),
            ),
            MCPReadinessCheck(
                name="preview_budget_and_environment",
                state="ready" if preview_environment_count else "missing",
                detail=(
                    f"已找到 {preview_environment_count} 个 test/sandbox 环境"
                    if preview_environment_count
                    else "没有可用于 Preview 的 test/sandbox 环境"
                ),
                action=None if preview_environment_count else "请登记 test 或 sandbox 环境",
            ),
        ]
        can_generate = bool(
            _feature_enabled()
            and api_count
            and ready_context_count
            and "mcp:flow:propose" in scopes
        )
        credentials_ready = not auth_reference_count or bool(credential_evidence_count)
        can_preview = bool(
            can_generate
            and "mcp:preview:execute" in scopes
            and preview_environment_count
            and accepted_proposal_count
            and credentials_ready
        )
        actions = _readiness_actions(
            scopes=scopes,
            feature_enabled=_feature_enabled(),
            api_count=api_count,
            endpoint_count=endpoint_count,
            ready_context_count=ready_context_count,
            auth_reference_count=auth_reference_count,
            credential_evidence_count=credential_evidence_count,
            preview_environment_count=preview_environment_count,
            accepted_proposal_count=accepted_proposal_count,
            can_generate=can_generate,
            can_preview=can_preview,
        )
        response = MCPProjectReadinessResponse(
            project_id=project_id,
            can_generate_proposal=can_generate,
            can_request_preview=can_preview,
            checks=checks,
            human_actions_required=actions,
            review_url=f"/projects/{project_id}/flow-spec/proposals",
            credential_setup_url=(
                f"/projects/{project_id}/settings/credentials"
                if auth_reference_count and not credentials_ready
                else None
            ),
            next_action=(
                "可在人工审核后请求 Sandbox Preview"
                if can_preview
                else "可生成待审核 Flow Proposal"
                if can_generate
                else actions[0]
                if actions
                else "补齐项目就绪条件后重新检查"
            ),
        )
        return await self._envelope(
            actor=actor,
            project_id=project_id,
            call=call,
            data=cast(JsonValue, response.model_dump(mode="json")),
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://projects/{project_id}/readiness",
                    kind="project-readiness",
                    version="flowtest-mcp-project-readiness-v1",
                )
            ],
            redactions=["credential.value", "credential.secret", "runtime.dsn", "runtime.body"],
        )

    async def check_service_target(
        self,
        *,
        actor: User,
        project_id: UUID,
        endpoint_id: UUID,
        call: MCPReadCall,
    ) -> MCPReadEnvelope:
        self._require_bootstrap_scope()
        await ProjectService(self._session).authorize(
            actor=actor, project_id=project_id, editing=False
        )
        endpoint = await self._targets.get_endpoint(endpoint_id)
        if endpoint is None or endpoint.project_id != project_id:
            raise AppError(
                code="SERVICE_ENDPOINT_NOT_FOUND",
                message="Service Endpoint 不存在",
                status_code=404,
            )
        environment = await self._session.get(Environment, endpoint.environment_id)
        if environment is None or environment.project_id != project_id:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        if not endpoint.enabled:
            result: dict[str, object] = {
                "endpoint_id": endpoint.id,
                "status": "disabled",
                "dns": "",
                "http_status": None,
                "latency_ms": None,
                "redirect": False,
                "error_code": "ENDPOINT_DISABLED",
            }
        else:
            result = await ServiceTargetService(self._session).check_connectivity(
                actor=actor,
                project_id=project_id,
                endpoint_id=endpoint_id,
            )
        connectivity = ServiceEndpointConnectivityResponse.model_validate(result)
        actions = []
        if connectivity.status != "reachable":
            actions.append("请在 FlowTest 主机检查目标网络、健康检查路径和允许的出站策略")
        response = MCPServiceTargetCheckResponse(
            project_id=project_id,
            endpoint_id=endpoint.id,
            variant=endpoint.variant,
            base_origin=_safe_origin(endpoint.base_url),
            execution_origin="flowtest_api_host",
            worker_network_verified=False,
            status=connectivity.status,
            dns=connectivity.dns,
            http_status=connectivity.http_status,
            latency_ms=connectivity.latency_ms,
            redirect=connectivity.redirect,
            error_code=connectivity.error_code,
            human_actions_required=actions,
            next_action=(
                "可继续使用该登记目标"
                if connectivity.status == "reachable"
                else "修复目标或出站策略后重新检查"
            ),
        )
        return await self._scoped_envelope(
            actor=actor,
            project_id=project_id,
            call=call,
            data=cast(JsonValue, response.model_dump(mode="json")),
            evidence_refs=[
                EvidenceRef(
                    uri=f"flowtest://projects/{project_id}/service-targets/{endpoint_id}",
                    kind="service-target-connectivity",
                    version="v1",
                )
            ],
            redactions=[
                "service_endpoint.headers",
                "service_endpoint.variables",
                "service_endpoint.secret_refs",
            ],
        )

    async def _scoped_envelope(
        self,
        *,
        actor: User,
        project_id: UUID,
        call: MCPReadCall,
        data: JsonValue,
        evidence_refs: list[EvidenceRef],
        redactions: list[str],
    ) -> MCPReadEnvelope:
        """Audit an operation authorized by a non-read MCP capability.

        Bootstrap-only accounts intentionally do not need the broad mcp:read scope for a
        registered endpoint health check.  The normal read envelope remains unchanged.
        """

        context = get_tenant_context()
        if context is None or MCP_PROJECT_BOOTSTRAP_SCOPE not in context.scopes:
            raise AppError(
                code="MCP_SCOPE_REQUIRED",
                message="服务账号缺少项目初始化权限范围",
                status_code=403,
            )
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=context.organization_id,
            project_id=project_id,
            action="mcp.tool.read",
            resource_type="mcp_read",
            resource_id=project_id,
            details={
                "server_version": "s61d-discovery-v1",
                "operation": call.operation,
                "input_schema_hash": call.input_schema_hash,
                "client_version": call.client_version,
                "confidence": 1.0,
                "redactions": redactions,
                "evidence_refs": [ref.model_dump(mode="json") for ref in evidence_refs],
            },
        )
        await self._session.commit()
        return MCPReadEnvelope(
            data=data,
            evidence_refs=evidence_refs,
            confidence=1.0,
            redactions=redactions,
            trace_id=get_trace_id(),
        )

    async def _count(self, statement: Any) -> int:
        value = await self._session.scalar(statement)
        return int(value or 0)

    @staticmethod
    def _asset_summary(row: MCPAssetRow) -> MCPAssetSummary:
        resource_type = row.resource_type
        name = _safe_text(row.name, resource_type)
        summary = _safe_text(row.summary, "")
        source_ref = _safe_source_ref(row.source_ref)
        updated_at = row.updated_at if isinstance(row.updated_at, datetime) else datetime.now(UTC)
        return MCPAssetSummary(
            resource_type=cast(Any, resource_type),
            id=row.resource_id,
            project_id=row.project_id,
            name=name,
            summary=summary,
            version=row.version,
            status=_safe_text(row.status, "unknown")[:32],
            source_ref=source_ref,
            updated_at=updated_at,
            deep_link=_deep_link(row.project_id, resource_type, row.resource_id),
        )

    def _require_bootstrap_scope(self) -> None:
        tenant = get_tenant_context()
        if tenant is None or MCP_PROJECT_BOOTSTRAP_SCOPE not in tenant.scopes:
            raise AppError(
                code="MCP_SCOPE_REQUIRED",
                message="服务账号缺少项目初始化权限范围",
                status_code=403,
            )


def _feature_enabled() -> bool:
    from app.core.config import settings

    return settings.feature_integration_flow_enabled


def _readiness_actions(
    *,
    scopes: frozenset[str],
    feature_enabled: bool,
    api_count: int,
    endpoint_count: int,
    ready_context_count: int,
    auth_reference_count: int,
    credential_evidence_count: int,
    preview_environment_count: int,
    accepted_proposal_count: int,
    can_generate: bool,
    can_preview: bool,
) -> list[str]:
    actions: list[str] = []
    actions.extend(_feature_and_scope_actions(feature_enabled, scopes))
    actions.extend(_asset_readiness_actions(api_count, endpoint_count, ready_context_count))
    if auth_reference_count and not credential_evidence_count:
        actions.append("请在授权凭据入口绑定业务测试凭据引用")
    if not preview_environment_count:
        actions.append("请登记 test 或 sandbox Preview 环境")
    if not accepted_proposal_count and can_generate:
        actions.append("请先由人工接受一个未应用的 Flow Proposal")
    if can_preview and not actions:
        return []
    return actions[:30]


def _feature_and_scope_actions(feature_enabled: bool, scopes: frozenset[str]) -> list[str]:
    actions: list[str] = []
    if not feature_enabled:
        actions.append("请由管理员启用 Integration Flow 功能")
    if "mcp:flow:propose" not in scopes:
        actions.append("请为当前 MCP Service Account 授予 mcp:flow:propose")
    if "mcp:preview:execute" not in scopes:
        actions.append("如需 Preview，请为当前 MCP Service Account 授予 mcp:preview:execute")
    return actions


def _asset_readiness_actions(
    api_count: int, endpoint_count: int, ready_context_count: int
) -> list[str]:
    actions: list[str] = []
    if not api_count:
        actions.append("请导入或提交至少一个 API Contract")
    if not endpoint_count:
        actions.append("请登记测试或 Sandbox Service Endpoint")
    if not ready_context_count:
        actions.append("请建立或补齐未过期 Ready Test Context")
    return actions


def _has_credential_reference(value: object, *, _depth: int = 0) -> bool:
    """Return true only for explicit secret references in credential fields.

    Runtime evidence is intentionally not considered credential evidence merely because
    it has ``source_type=runtime``.  Values are never returned by the readiness API.
    """

    if _depth > 8:
        return False
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _CREDENTIAL_REFERENCE_KEYS and _credential_reference_value(
                child, depth=_depth + 1
            ):
                return True
            if _has_credential_reference(child, _depth=_depth + 1):
                return True
        return False
    if isinstance(value, list):
        return any(_has_credential_reference(item, _depth=_depth + 1) for item in value)
    return False


def _credential_reference_value(value: object, *, depth: int) -> bool:
    if depth > 8:
        return False
    if isinstance(value, str):
        return _SECRET_REFERENCE.fullmatch(value.strip()) is not None
    if isinstance(value, list):
        return any(_credential_reference_value(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        return any(_credential_reference_value(item, depth=depth + 1) for item in value.values())
    return False


def _safe_text(value: str, fallback: str) -> str:
    text = value.strip()[:400] if value else ""
    if not text or first_sensitive_value({"value": text}) is not None:
        return fallback[:200] or "未命名资源"
    return text


def _safe_source_ref(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme
        not in {"mcp", "repair", "maintenance", "change-regression", "import", "flow-spec"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:512]


def _deep_link(project_id: UUID, resource_type: str, resource_id: UUID) -> str:
    routes = {
        "api": f"/projects/{project_id}/apis/{resource_id}",
        "workflow": f"/projects/{project_id}/workflows/{resource_id}",
        "context": f"/projects/{project_id}/contexts/{resource_id}",
        "proposal": f"/projects/{project_id}/flow-spec/proposals/{resource_id}",
        "test_case": f"/projects/{project_id}/test-assets/cases/{resource_id}",
        "test_suite": f"/projects/{project_id}/test-assets/suites/{resource_id}",
        "test_plan": f"/projects/{project_id}/test-plans/{resource_id}",
        "import_run": f"/projects/{project_id}/imports/{resource_id}",
        "execution": f"/projects/{project_id}/workflows/executions/{resource_id}",
        "change_regression_run": f"/projects/{project_id}/change-regression/{resource_id}",
    }
    return routes.get(resource_type, f"/projects/{project_id}/assets/{resource_id}")
