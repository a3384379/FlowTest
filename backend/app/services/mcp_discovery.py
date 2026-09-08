"""MCP resource discovery, project readiness and registered-target diagnostics."""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context, get_trace_id
from app.core.errors import AppError
from app.domain.mcp_read import EvidenceRef, MCPReadCall, MCPReadEnvelope
from app.domain.test_contexts import first_sensitive_value
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion, Environment, Secret
from app.models.service_targets import Service, ServiceEndpoint
from app.models.test_contexts import ContextEvidenceItem, TestContext, TestContextRevision
from app.repositories.mcp_assets import MCPAssetRepository, MCPAssetRow
from app.schemas.mcp_discovery import (
    MCPAssetSummary,
    MCPFindAssetsRequest,
    MCPFindAssetsResponse,
    MCPProjectReadinessResponse,
    MCPReadinessCheck,
    MCPRequiredAPIVersion,
    MCPRequiredServiceEndpoint,
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
_SECRET_TEMPLATE = re.compile(r"\{\{secret\.([A-Za-z0-9._:/-]{1,480})\}\}")


@dataclass(frozen=True, slots=True)
class _ReadinessTarget:
    environment_id: UUID | None
    proposal_id: UUID | None
    context_revision_id: UUID | None
    context_id: UUID | None
    api_definition_ids: frozenset[UUID] | None = None
    api_versions: frozenset[tuple[UUID, int]] | None = None
    proposal_secret_names: frozenset[str] = frozenset()
    endpoint_bindings: frozenset[tuple[UUID, str]] | None = None


@dataclass(frozen=True, slots=True)
class _ReadinessInventory:
    api_count: int
    endpoint_count: int
    context_count: int
    ready_context_count: int
    database_evidence_count: int
    preview_environment_count: int
    accepted_proposal_count: int
    authenticated_versions: tuple[APIVersion, ...]
    resolved_api_versions: frozenset[tuple[UUID, int]]
    resolved_endpoint_bindings: frozenset[tuple[UUID, str]]


@dataclass(frozen=True, slots=True)
class _ProposalReadinessMetadata:
    api_definition_ids: frozenset[UUID]
    api_versions: frozenset[tuple[UUID, int]]
    secret_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class _CredentialReadiness:
    required: bool
    verified: bool
    reference_count: int


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
        environment_id: UUID | None = None,
        proposal_id: UUID | None = None,
        context_revision_id: UUID | None = None,
    ) -> MCPReadEnvelope:
        self._require_scope()
        access = await self._projects.get(actor=actor, project_id=project_id)
        tenant = get_tenant_context()
        scopes = tenant.scopes if tenant is not None else frozenset()
        now = datetime.now(UTC)
        target = await self._resolve_readiness_target(
            project_id=project_id,
            environment_id=environment_id,
            proposal_id=proposal_id,
            context_revision_id=context_revision_id,
        )
        inventory = await self._readiness_inventory(
            project_id=project_id,
            now=now,
            target=target,
        )
        credentials = await self._credential_readiness(
            project_id=project_id,
            target=target,
            authenticated_versions=inventory.authenticated_versions,
        )
        api_count = inventory.api_count
        endpoint_count = inventory.endpoint_count
        context_count = inventory.context_count
        ready_context_count = inventory.ready_context_count
        database_evidence_count = inventory.database_evidence_count
        preview_environment_count = inventory.preview_environment_count
        accepted_proposal_count = inventory.accepted_proposal_count
        auth_reference_count = len(inventory.authenticated_versions)
        credentials_required = credentials.required
        credentials_verified = credentials.verified
        credential_reference_count = credentials.reference_count
        required_api_versions = target.api_versions or frozenset()
        resolved_api_versions = inventory.resolved_api_versions
        missing_api_versions = required_api_versions - resolved_api_versions
        required_endpoints = target.endpoint_bindings or frozenset()
        resolved_endpoints = inventory.resolved_endpoint_bindings
        missing_endpoints = required_endpoints - resolved_endpoints
        contracts_ready = bool(
            api_count
            and (
                target.api_versions is None or (required_api_versions and not missing_api_versions)
            )
        )
        endpoints_ready = bool(
            endpoint_count
            and (target.endpoint_bindings is None or (required_endpoints and not missing_endpoints))
        )
        credentials_state = (
            "ready"
            if credentials_verified
            else "missing"
            if not credential_reference_count
            else "not_verified"
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
                state="ready" if contracts_ready else "missing",
                detail=(
                    f"已解析全部 {len(required_api_versions)} 个固定 API 版本"
                    if target.api_versions is not None and contracts_ready
                    else f"缺少 {len(missing_api_versions)} 个固定 API 版本"
                    if target.api_versions is not None
                    else f"已发现 {api_count} 个启用的 API 定义"
                ),
                action=None if contracts_ready else "请导入或恢复 Proposal 固定的 API 版本",
            ),
            MCPReadinessCheck(
                name="service_endpoint",
                state="ready" if endpoints_ready else "missing",
                detail=(
                    f"已解析全部 {len(required_endpoints)} 个 Service Endpoint"
                    if target.endpoint_bindings is not None and endpoints_ready
                    else f"缺少 {len(missing_endpoints)} 个 Service/Variant 目标"
                    if target.endpoint_bindings is not None
                    else f"已登记 {endpoint_count} 个启用的 Service Endpoint"
                ),
                action=None
                if endpoints_ready
                else "请为每个必需 Service 登记启用的目标 Endpoint Variant",
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
                state=credentials_state,
                detail=(
                    "当前目标 Environment 的 Secret 引用已解析；凭据值不会通过 MCP 返回"
                    if credentials_verified and credentials_required
                    else "Contract/Endpoint 不需要业务测试凭据"
                    if not credentials_required
                    else "已声明凭据引用，但尚未完成目标 Environment 级解析"
                    if credential_reference_count
                    else "Contract 需要认证，但尚未声明 secret:// 凭据引用"
                ),
                action=(
                    None
                    if credentials_verified
                    else "请为目标 test/sandbox Environment 绑定可解析的 secret:// 凭据引用"
                ),
            ),
            MCPReadinessCheck(
                name="db_runtime_readonly",
                state="not_verified" if database_evidence_count else "not_configured",
                detail=(
                    "已有只读数据库证据，但尚未完成当前目标运行时连接验证"
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
            and contracts_ready
            and ready_context_count
            and "mcp:flow:propose" in scopes
        )
        target_bound = proposal_id is not None and environment_id is not None
        can_preview = bool(
            can_generate
            and "mcp:preview:execute" in scopes
            and preview_environment_count
            and endpoints_ready
            and accepted_proposal_count
            and credentials_verified
            and target_bound
        )
        actions = _readiness_actions(
            scopes=scopes,
            feature_enabled=_feature_enabled(),
            api_count=api_count if contracts_ready else 0,
            endpoint_count=endpoint_count if endpoints_ready else 0,
            ready_context_count=ready_context_count,
            auth_reference_count=auth_reference_count,
            credential_evidence_count=credential_reference_count,
            credentials_verified=credentials_verified,
            preview_environment_count=preview_environment_count,
            accepted_proposal_count=accepted_proposal_count,
            can_generate=can_generate,
            can_preview=can_preview,
        )
        if can_generate and not target_bound:
            actions.append(
                "请同时提供 proposal_id、test/sandbox environment_id 做目标级 Preview 预检"
            )
        response = MCPProjectReadinessResponse(
            project_id=project_id,
            can_generate_proposal=can_generate,
            can_request_preview=can_preview,
            required_service_endpoints=_service_endpoint_requirements(required_endpoints),
            resolved_service_endpoints=_service_endpoint_requirements(
                required_endpoints & resolved_endpoints
                if target.endpoint_bindings is not None
                else frozenset()
            ),
            missing_service_endpoints=_service_endpoint_requirements(missing_endpoints),
            required_api_versions=_api_version_requirements(required_api_versions),
            resolved_api_versions=_api_version_requirements(
                required_api_versions & resolved_api_versions
                if target.api_versions is not None
                else frozenset()
            ),
            missing_api_versions=_api_version_requirements(missing_api_versions),
            checks=checks,
            human_actions_required=actions,
            review_url=f"/projects/{project_id}/workflows",
            credential_setup_url=(
                f"/projects/{project_id}/data"
                if credentials_required and not credentials_verified
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

    async def _resolve_readiness_target(
        self,
        *,
        project_id: UUID,
        environment_id: UUID | None,
        proposal_id: UUID | None,
        context_revision_id: UUID | None,
    ) -> _ReadinessTarget:
        context_id: UUID | None = None
        api_definition_ids: frozenset[UUID] | None = None
        api_versions: frozenset[tuple[UUID, int]] | None = None
        proposal_secret_names: frozenset[str] = frozenset()
        endpoint_bindings: frozenset[tuple[UUID, str]] | None = None
        if environment_id is not None:
            environment = await self._session.get(Environment, environment_id)
            if environment is None or environment.project_id != project_id:
                raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        if context_revision_id is not None:
            revision = await self._session.get(TestContextRevision, context_revision_id)
            context = (
                await self._session.get(TestContext, revision.context_id) if revision else None
            )
            if revision is None or context is None or context.project_id != project_id:
                raise AppError(
                    code="CONTEXT_REVISION_NOT_FOUND",
                    message="Context Revision 不存在",
                    status_code=404,
                )
            context_id = context.id
        if proposal_id is not None:
            proposal = await self._session.get(AIChangeSet, proposal_id)
            if (
                proposal is None
                or proposal.project_id != project_id
                or proposal.source_type != "flow_spec"
            ):
                raise AppError(
                    code="FLOW_SPEC_PROPOSAL_NOT_FOUND",
                    message="Flow Proposal 不存在",
                    status_code=404,
                )
            item = await self._session.scalar(
                select(AIChangeItem).where(
                    AIChangeItem.change_set_id == proposal.id,
                    AIChangeItem.item_type == "workflow",
                )
            )
            metadata = _proposal_readiness_metadata(
                snapshot=proposal.source_snapshot,
                proposed_content=item.proposed_content if item is not None else None,
            )
            api_definition_ids = metadata.api_definition_ids
            api_versions = metadata.api_versions
            proposal_secret_names = metadata.secret_names
            endpoint_bindings = _proposal_endpoint_bindings(
                snapshot=proposal.source_snapshot,
                proposed_content=item.proposed_content if item is not None else None,
            )
        return _ReadinessTarget(
            environment_id=environment_id,
            proposal_id=proposal_id,
            context_revision_id=context_revision_id,
            context_id=context_id,
            api_definition_ids=api_definition_ids,
            api_versions=api_versions,
            proposal_secret_names=proposal_secret_names,
            endpoint_bindings=endpoint_bindings,
        )

    async def _readiness_inventory(
        self,
        *,
        project_id: UUID,
        now: datetime,
        target: _ReadinessTarget,
    ) -> _ReadinessInventory:
        api_conditions = [
            APIDefinition.project_id == project_id,
            APIDefinition.is_active.is_(True),
        ]
        resolved_api_versions: frozenset[tuple[UUID, int]] = frozenset()
        if target.api_versions is not None:
            exact_version_conditions = _api_version_conditions(target.api_versions)
            version_rows = (
                await self._session.execute(
                    select(APIVersion.api_definition_id, APIVersion.version)
                    .join(APIDefinition, APIDefinition.id == APIVersion.api_definition_id)
                    .where(*api_conditions, exact_version_conditions)
                )
            ).all()
            resolved_api_versions = frozenset(
                (definition_id, version) for definition_id, version in version_rows
            )
            api_count = len(resolved_api_versions)
        else:
            api_count = await self._count(
                select(func.count()).select_from(APIDefinition).where(*api_conditions)
            )
        endpoint_conditions = _endpoint_conditions(project_id=project_id, target=target)
        endpoints = list(
            (await self._session.scalars(select(ServiceEndpoint).where(*endpoint_conditions))).all()
        )
        endpoint_count = len(endpoints)
        resolved_endpoint_bindings = frozenset(
            (endpoint.service_id, endpoint.variant) for endpoint in endpoints
        )

        context_conditions = [TestContext.project_id == project_id]
        if target.context_id is not None:
            context_conditions.append(TestContext.id == target.context_id)
        context_count = await self._count(
            select(func.count()).select_from(TestContext).where(*context_conditions)
        )
        ready_conditions = [
            TestContext.project_id == project_id,
            TestContext.status == "ready",
            TestContext.expires_at > now,
        ]
        if target.context_id is not None:
            ready_conditions.append(TestContext.id == target.context_id)
        ready_query = select(func.count()).select_from(TestContext).where(*ready_conditions)
        if target.context_revision_id is not None:
            ready_query = ready_query.join(
                TestContextRevision,
                TestContextRevision.context_id == TestContext.id,
            ).where(
                TestContextRevision.id == target.context_revision_id,
                TestContextRevision.revision == TestContext.current_revision,
            )
        ready_context_count = await self._count(ready_query)

        authenticated_conditions = [
            APIDefinition.project_id == project_id,
            APIDefinition.is_active.is_(True),
            APIVersion.auth_kind != "none",
        ]
        if target.api_versions is not None:
            authenticated_conditions.append(_api_version_conditions(target.api_versions))
        else:
            authenticated_conditions.append(APIVersion.version == APIDefinition.current_version)
        authenticated_versions = tuple(
            (
                await self._session.scalars(
                    select(APIVersion)
                    .join(APIDefinition, APIDefinition.id == APIVersion.api_definition_id)
                    .where(*authenticated_conditions)
                )
            ).all()
        )
        evidence_conditions = [
            TestContext.project_id == project_id,
            TestContext.status == "ready",
            TestContext.expires_at > now,
            TestContextRevision.revision == TestContext.current_revision,
            ContextEvidenceItem.source_type == "database",
            ContextEvidenceItem.expires_at > now,
        ]
        if target.context_id is not None:
            evidence_conditions.append(TestContext.id == target.context_id)
        if target.context_revision_id is not None:
            evidence_conditions.append(
                ContextEvidenceItem.context_revision_id == target.context_revision_id
            )
        database_evidence_count = await self._count(
            select(func.count())
            .select_from(ContextEvidenceItem)
            .join(
                TestContextRevision,
                TestContextRevision.id == ContextEvidenceItem.context_revision_id,
            )
            .join(TestContext, TestContext.id == TestContextRevision.context_id)
            .where(*evidence_conditions)
        )
        environment_conditions = [
            Environment.project_id == project_id,
            Environment.classification.in_(["test", "sandbox"]),
        ]
        if target.environment_id is not None:
            environment_conditions.append(Environment.id == target.environment_id)
        preview_environment_count = await self._count(
            select(func.count()).select_from(Environment).where(*environment_conditions)
        )
        accepted_proposal_count = await self._count_previewable_proposals(
            project_id=project_id,
            now=now,
            proposal_id=target.proposal_id,
            context_revision_id=target.context_revision_id,
        )
        return _ReadinessInventory(
            api_count=api_count,
            endpoint_count=endpoint_count,
            context_count=context_count,
            ready_context_count=ready_context_count,
            database_evidence_count=database_evidence_count,
            preview_environment_count=preview_environment_count,
            accepted_proposal_count=accepted_proposal_count,
            authenticated_versions=authenticated_versions,
            resolved_api_versions=resolved_api_versions,
            resolved_endpoint_bindings=resolved_endpoint_bindings,
        )

    async def _credential_readiness(
        self,
        *,
        project_id: UUID,
        target: _ReadinessTarget,
        authenticated_versions: tuple[APIVersion, ...],
    ) -> _CredentialReadiness:
        endpoint_conditions = _endpoint_conditions(project_id=project_id, target=target)
        endpoints = list(
            (await self._session.scalars(select(ServiceEndpoint).where(*endpoint_conditions))).all()
        )
        declared_names = set(target.proposal_secret_names)
        declared_names.update(
            name
            for version in authenticated_versions
            for name in _secret_reference_names(version.auth_config)
        )
        declared_names.update(
            name
            for endpoint in endpoints
            for name in _secret_reference_names(endpoint.secret_refs, allow_raw=True)
        )
        available_names: set[str] = set()
        if target.environment_id is not None:
            secrets = list(
                (
                    await self._session.scalars(
                        select(Secret).where(
                            Secret.project_id == project_id,
                            (Secret.environment_id.is_(None))
                            | (Secret.environment_id == target.environment_id),
                        )
                    )
                ).all()
            )
            available_names = {secret.name for secret in secrets}
        resolved_names = {name for name in declared_names if name in available_names}
        required = bool(authenticated_versions or declared_names)
        verified = bool(
            not required
            or (
                target.environment_id is not None
                and declared_names
                and resolved_names == declared_names
            )
        )
        return _CredentialReadiness(
            required=required,
            verified=verified,
            reference_count=len(declared_names),
        )

    async def _count_previewable_proposals(
        self,
        *,
        project_id: UUID,
        now: datetime,
        proposal_id: UUID | None = None,
        context_revision_id: UUID | None = None,
    ) -> int:
        """Count only accepted FlowSpec proposals that Preview can resolve.

        Change Regression and Test Plan ChangeSets have different lifecycles and must
        never make readiness claim that a FlowSpec Preview is available.  The bounded
        context checks mirror the first immutable checks in
        ``SandboxPreviewService._previewable`` without loading or exposing proposal data.
        """

        conditions = [
            AIChangeSet.project_id == project_id,
            AIChangeSet.status == "accepted",
            AIChangeSet.applied_at.is_(None),
            AIChangeSet.source_type == "flow_spec",
            AIChangeItem.item_type == "workflow",
            AIChangeItem.review_status == "accepted",
        ]
        if proposal_id is not None:
            conditions.append(AIChangeSet.id == proposal_id)
        candidates = (
            await self._session.execute(
                select(AIChangeSet, AIChangeItem)
                .join(AIChangeItem, AIChangeItem.change_set_id == AIChangeSet.id)
                .where(*conditions)
                .order_by(AIChangeSet.updated_at.desc())
                .limit(2000)
            )
        ).all()
        count = 0
        for change_set, item in candidates:
            snapshot = change_set.source_snapshot
            if not isinstance(snapshot, dict) or not isinstance(item.proposed_content, dict):
                continue
            if not isinstance(item.proposed_content.get("flow_spec"), dict):
                continue
            revision_id = _uuid_value(snapshot.get("context_revision_id"))
            if context_revision_id is not None and revision_id != context_revision_id:
                continue
            context_fingerprint = snapshot.get("context_fingerprint")
            if revision_id is None or not isinstance(context_fingerprint, str):
                continue
            revision = await self._session.get(TestContextRevision, revision_id)
            if revision is None or revision.fingerprint != context_fingerprint:
                continue
            context = await self._session.get(TestContext, revision.context_id)
            if (
                context is None
                or context.project_id != project_id
                or context.status != "ready"
                or context.current_revision != revision.revision
                or _as_utc(context.expires_at) <= now
            ):
                continue
            count += 1
        return count

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
            source_type=cast(Any, row.source_type),
            item_type=cast(Any, row.item_type),
            proposal_kind=cast(Any, row.proposal_kind),
            updated_at=updated_at,
            deep_link=_deep_link(
                row.project_id,
                resource_type,
                row.resource_id,
                proposal_kind=row.proposal_kind,
            ),
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
    credentials_verified: bool,
    preview_environment_count: int,
    accepted_proposal_count: int,
    can_generate: bool,
    can_preview: bool,
) -> list[str]:
    actions: list[str] = []
    actions.extend(_feature_and_scope_actions(feature_enabled, scopes))
    actions.extend(_asset_readiness_actions(api_count, endpoint_count, ready_context_count))
    if (auth_reference_count or credential_evidence_count) and not credentials_verified:
        actions.append("请为目标 test/sandbox Environment 绑定并解析业务测试凭据引用")
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


def _proposal_readiness_metadata(
    *,
    snapshot: dict[str, Any],
    proposed_content: dict[str, Any] | None,
) -> _ProposalReadinessMetadata:
    mappings = snapshot.get("resource_mappings")
    operation_mappings = mappings.get("operations") if isinstance(mappings, dict) else None
    version_mappings = mappings.get("operation_versions") if isinstance(mappings, dict) else None
    api_definition_ids: set[UUID] = set()
    flow_spec = (
        proposed_content.get("flow_spec")
        if isinstance(proposed_content, dict)
        else snapshot.get("flow_spec")
    )
    operation_source_versions = _operation_source_versions(flow_spec)
    api_versions: set[tuple[UUID, int]] = set()
    if isinstance(operation_mappings, dict):
        for reference, value in operation_mappings.items():
            definition_id = _uuid_value(value)
            if definition_id is None:
                continue
            api_definition_ids.add(definition_id)
            raw_version = (
                version_mappings.get(reference, operation_source_versions.get(str(reference)))
                if isinstance(version_mappings, dict)
                else operation_source_versions.get(str(reference))
            )
            version = _positive_int(raw_version)
            if version is not None:
                api_versions.add((definition_id, version))
    secret_names = _secret_reference_names(flow_spec)
    return _ProposalReadinessMetadata(
        api_definition_ids=frozenset(api_definition_ids),
        api_versions=frozenset(api_versions),
        secret_names=frozenset(secret_names),
    )


def _proposal_endpoint_bindings(
    *,
    snapshot: dict[str, Any],
    proposed_content: dict[str, Any] | None,
) -> frozenset[tuple[UUID, str]]:
    mappings = snapshot.get("resource_mappings")
    service_mappings = mappings.get("services") if isinstance(mappings, dict) else None
    if not isinstance(service_mappings, dict):
        return frozenset()
    services = {
        str(reference): parsed
        for reference, value in service_mappings.items()
        if (parsed := _uuid_value(value)) is not None
    }
    flow_spec = (
        proposed_content.get("flow_spec")
        if isinstance(proposed_content, dict)
        else snapshot.get("flow_spec")
    )
    if not isinstance(flow_spec, dict):
        return frozenset()
    operations = _flow_operations(flow_spec)
    node_values = flow_spec.get("nodes")
    node_bindings = (
        {
            binding
            for node in node_values
            if isinstance(node, dict)
            and (binding := _node_endpoint_binding(node, operations, services)) is not None
        }
        if isinstance(node_values, list)
        else set()
    )
    return frozenset(node_bindings | _cleanup_endpoint_bindings(flow_spec, operations, services))


def _flow_operations(flow_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = flow_spec.get("operations")
    if not isinstance(values, list):
        return {}
    return {
        operation["ref"]: operation
        for operation in values
        if isinstance(operation, dict) and isinstance(operation.get("ref"), str)
    }


def _node_endpoint_binding(
    node: dict[str, Any],
    operations: dict[str, dict[str, Any]],
    services: dict[str, UUID],
) -> tuple[UUID, str] | None:
    target_value = node.get("target")
    target = target_value if isinstance(target_value, dict) else {}
    service_ref = target.get("service_ref")
    if not isinstance(service_ref, str):
        operation_ref = node.get("operation_ref")
        operation = operations.get(operation_ref) if isinstance(operation_ref, str) else None
        service_ref = operation.get("service_ref") if operation is not None else None
    service_id = services.get(service_ref) if isinstance(service_ref, str) else None
    if service_id is None:
        return None
    variant = target.get("endpoint_variant")
    return service_id, variant if isinstance(variant, str) else "default"


def _cleanup_endpoint_bindings(
    flow_spec: dict[str, Any],
    operations: dict[str, dict[str, Any]],
    services: dict[str, UUID],
) -> set[tuple[UUID, str]]:
    values = flow_spec.get("cleanup")
    if not isinstance(values, list):
        return set()
    bindings: set[tuple[UUID, str]] = set()
    for cleanup in values:
        operation_ref = cleanup.get("operation_ref") if isinstance(cleanup, dict) else None
        operation = operations.get(operation_ref) if isinstance(operation_ref, str) else None
        service_ref = operation.get("service_ref") if operation is not None else None
        service_id = services.get(service_ref) if isinstance(service_ref, str) else None
        if service_id is not None:
            bindings.add((service_id, "default"))
    return bindings


def _operation_source_versions(flow_spec: object) -> dict[str, int]:
    if not isinstance(flow_spec, dict):
        return {}
    operations = flow_spec.get("operations")
    if not isinstance(operations, list):
        return {}
    result: dict[str, int] = {}
    for operation in operations:
        if not isinstance(operation, dict) or not isinstance(operation.get("ref"), str):
            continue
        version = _positive_int(operation.get("source_version") or operation.get("api_version"))
        if version is not None:
            result[operation["ref"]] = version
    return result


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def _api_version_conditions(api_versions: frozenset[tuple[UUID, int]]) -> Any:
    if not api_versions:
        return false()
    return or_(
        *(
            and_(
                APIVersion.api_definition_id == definition_id,
                APIVersion.version == version,
            )
            for definition_id, version in sorted(
                api_versions, key=lambda item: (str(item[0]), item[1])
            )
        )
    )


def _service_endpoint_requirements(
    values: frozenset[tuple[UUID, str]],
) -> list[MCPRequiredServiceEndpoint]:
    return [
        MCPRequiredServiceEndpoint(service_id=service_id, variant=variant)
        for service_id, variant in sorted(values, key=lambda item: (str(item[0]), item[1]))
    ]


def _api_version_requirements(
    values: frozenset[tuple[UUID, int]],
) -> list[MCPRequiredAPIVersion]:
    return [
        MCPRequiredAPIVersion(api_definition_id=definition_id, version=version)
        for definition_id, version in sorted(values, key=lambda item: (str(item[0]), item[1]))
    ]


def _endpoint_conditions(*, project_id: UUID, target: _ReadinessTarget) -> list[Any]:
    conditions: list[Any] = [
        ServiceEndpoint.project_id == project_id,
        ServiceEndpoint.enabled.is_(True),
        ServiceEndpoint.service_id.in_(
            select(Service.id).where(
                Service.project_id == project_id,
                Service.enabled.is_(True),
            )
        ),
    ]
    if target.environment_id is not None:
        conditions.append(ServiceEndpoint.environment_id == target.environment_id)
    if target.endpoint_bindings is None:
        return conditions
    if not target.endpoint_bindings:
        conditions.append(false())
        return conditions
    binding_conditions = []
    for service_id, variant in sorted(
        target.endpoint_bindings, key=lambda item: (str(item[0]), item[1])
    ):
        binding_conditions.append(
            and_(
                ServiceEndpoint.service_id == service_id,
                ServiceEndpoint.variant == variant,
            )
        )
    conditions.append(or_(*binding_conditions))
    return conditions


def _secret_reference_names(value: object, *, allow_raw: bool = False, _depth: int = 0) -> set[str]:
    """Collect secret names without inspecting or returning secret values."""

    if _depth > 8:
        return set()
    if isinstance(value, str):
        normalized = value.strip()
        if _SECRET_REFERENCE.fullmatch(normalized):
            return {normalized.removeprefix("secret://")}
        templated = set(_SECRET_TEMPLATE.findall(normalized))
        if templated:
            return templated
        return {normalized} if allow_raw and normalized else set()
    if isinstance(value, dict):
        references: set[str] = set()
        for child in value.values():
            references.update(
                _secret_reference_names(child, allow_raw=allow_raw, _depth=_depth + 1)
            )
        return references
    if isinstance(value, (list, tuple)):
        references = set()
        for child in value:
            references.update(
                _secret_reference_names(child, allow_raw=allow_raw, _depth=_depth + 1)
            )
        return references
    return set()


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


def _uuid_value(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _deep_link(
    project_id: UUID,
    resource_type: str,
    resource_id: UUID,
    *,
    proposal_kind: str | None = None,
) -> str:
    project = f"/projects/{project_id}"
    resource = str(resource_id)
    if resource_type == "proposal":
        proposal_routes = {
            "flow_spec": f"{project}/workflows?proposal={resource}",
            "repair": f"{project}/workflows?proposal={resource}",
            "maintenance": f"{project}/workflows?proposal={resource}",
            "test_design": f"{project}/test-engineering?proposal={resource}",
            "test_plan_update": f"{project}/mcp-changes?focus={resource}",
            "mcp_controlled_write": f"{project}/mcp-changes?focus={resource}",
            "ai": f"{project}/ai-changes?focus={resource}",
        }
        return proposal_routes.get(proposal_kind or "", f"{project}/assets?focus={resource}")
    routes = {
        "api": f"{project}/apis?focus={resource}",
        "workflow": f"{project}/workflows?focus={resource}",
        "context": f"{project}/contexts?focus={resource}",
        "test_case": f"{project}/assets?type=case&focus={resource}",
        "test_suite": f"{project}/assets?type=suite&focus={resource}",
        "test_plan": f"{project}/tasks?focus={resource}",
        "import_run": f"{project}/apis?import_run={resource}",
        "execution": f"{project}/reports?execution={resource}",
        "change_regression_run": f"{project}/change-regression?run={resource}",
    }
    return routes.get(resource_type, f"{project}/assets?focus={resource}")
