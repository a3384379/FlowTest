"""Official MCP SDK adapter for FlowTest read operations."""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

import json
from collections.abc import Awaitable, Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from app.domain.evidence_adapters import (
    DatabaseEvidenceSubmission,
    JavaEvidenceSubmission,
    JavaSourceInput,
)
from app.domain.integration_plans import (
    IntegrationPlan,
    IntegrationPlanCompilation,
    PlanActor,
    PlanCleanupRequirement,
    PlanPrecondition,
    PlanTargetEnvironment,
)
from app.domain.mcp_read import MCP_SERVER_NAME
from app.domain.test_contexts import (
    ContextKnowledgeSnapshot,
    EvidenceProviderType,
    ExternalEvidenceEnvelope,
    RevisionReference,
)
from app.mcp.client import MCPGatewayError, MCPReadGatewayClient
from app.mcp.connection_diagnostics import connection_diagnostic
from app.schemas.mcp_bootstrap import (
    MCPEnsureEnvironmentRequest,
    MCPEnsureProjectRequest,
    MCPEnsureServiceTargetRequest,
)
from app.schemas.mcp_connection import MCP_CONNECTION_VERSION, MCPConnectionRequest
from app.schemas.mcp_continuous import (
    MCPAffectedFlowsRequest,
    MCPContextComparisonRequest,
    MCPFailureRequest,
    MCPMaintenanceRequest,
    MCPRegressionRequest,
    MCPRepairRequest,
)
from app.schemas.mcp_contract_import import (
    MCPCommitContractImportRequest,
    MCPPreviewContractImportRequest,
)
from app.schemas.mcp_discovery import MCPFindAssetsRequest
from app.schemas.mcp_planning import (
    MCPCancelPreviewRequest,
    MCPPrepareChangeRegressionRequest,
    MCPTestPlanUpdateRequest,
)
from app.schemas.test_contexts import (
    ExistingAuthWorkflowSelectionRequest,
    IntegrationPlanOperationSelectionRequest,
)

MCP_INSTRUCTIONS = (
    "FlowTest MCP 提供只读项目、服务、契约、工作流草稿和执行证据，并允许提交"
    "版本化外部证据、强类型 Java/DB Evidence、内置 Java/Spring 静态源码分析、"
    "确定性 Integration Plan 与"
    "只进入待审核状态的 Flow Draft、Repair、关联现有 Change Regression 的 Maintenance，"
    "以及固定 Context 的 Change Regression 准备和 Test Plan 更新建议。"
    "Contract Import 只能从批准的 URL、有界文档或强类型 Operation 进入 Preview；"
    "Commit 使用冻结预览摘要，绝不重新抓取 URL。"
    "Context Diff、Affected Flow、资源发现、项目就绪和失败诊断只读；"
    "Service Target 检查只允许已登记目标；Sandbox Preview 需要人工一次性批准。"
    "Preview 可由有权主体请求 Graceful Cancel，但 FlowTest 不会主动连接任意外部 MCP Server。"
    "它不会自动发布、正式环境执行、删除、修改"
    "权限、审核、Apply 或创建 Credential；Flow Proposal 默认 Dry Run，必须由人工"
    "检查并显式接受后才能应用。输出中的请求值、认证信息、"
    "Secret、PII 和响应体会被省略或脱敏。"
)


def create_mcp_server(
    *,
    client: MCPReadGatewayClient | None = None,
    api_base_url: str | None = None,
    service_account_token: str | None = None,
    allow_process_token: bool = True,
) -> MCPServer:
    """Create a server with stable, sorted tools/resources/prompts."""

    if client is None:
        from app.core.config import settings

        client = MCPReadGatewayClient(
            base_url=api_base_url or settings.mcp_api_base_url,
            token=(
                service_account_token
                if service_account_token is not None
                else settings.mcp_service_account_token or None
            )
            if allow_process_token
            else None,
            timeout=settings.mcp_request_timeout_seconds,
            client_version=settings.mcp_client_version,
        )
    server = MCPServer(
        name=MCP_SERVER_NAME,
        version=MCP_CONNECTION_VERSION,
        instructions=MCP_INSTRUCTIONS,
    )

    _register_resources(server, client)
    _register_tools(server, client)
    _register_prompts(server)
    return server


def _register_context_diff_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_context_diff",
        description="读取固定版本的 Context/Knowledge 差异, 不授予 Patch 权限。",
        structured_output=True,
    )
    async def inspect_context_diff(
        request: MCPContextComparisonRequest,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_context_diff(request, token=_request_token(ctx, client))
        )


def _register_preview_contract_import_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.preview_contract_import",
        description=(
            "Preview an API contract from an approved URL, bounded document, or strongly typed "
            "operations. persist=false is a pure dry-run; persist=true creates an ImportRun."
        ),
        structured_output=True,
    )
    async def preview_contract_import(
        request: MCPPreviewContractImportRequest,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.preview_contract_import(
                request,
                token=_request_token(ctx, client),
            )
        )


def _register_commit_contract_import_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.commit_contract_import",
        description=(
            "Commit only a frozen contract preview by preview_id and source digest. The server "
            "never refetches a URL; updates, deletes, and endpoint changes require confirmation."
        ),
        structured_output=True,
    )
    async def commit_contract_import(
        request: MCPCommitContractImportRequest,
        idempotency_key: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.commit_contract_import(
                request,
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )


def _register_affected_flows_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_affected_flows",
        description="读取有界的受影响流程、原因和分析不完整诊断。",
        structured_output=True,
    )
    async def inspect_affected_flows(
        request: MCPAffectedFlowsRequest,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_affected_flows(request, token=_request_token(ctx, client))
        )


def _register_diagnose_failure_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.diagnose_failure",
        description="诊断实际失败并保留产品缺陷保护, 不自动重试。",
        structured_output=True,
    )
    async def diagnose_failure(request: MCPFailureRequest, ctx: Context = None) -> dict[str, Any]:  # type: ignore[assignment]
        return await _tool_payload(
            client.diagnose_failure(request, token=_request_token(ctx, client))
        )


def _register_change_regression_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_change_regression",
        description="读取现有 Change Regression 证据, Preview 不算正式执行。",
        structured_output=True,
    )
    async def inspect_change_regression(
        request: MCPRegressionRequest,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_change_regression(request, token=_request_token(ctx, client))
        )


def _register_connection_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_connection",
        description="检查当前机器身份、组织、权限和版本; 不需要项目 ID, 不签发或读取令牌。",
        structured_output=True,
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    async def inspect_connection(
        request: MCPConnectionRequest,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_connection(request, token=_request_token(ctx, client))
        )


def _register_bootstrap_tools(server: MCPServer, client: MCPReadGatewayClient) -> None:
    """Register the opt-in, idempotent organization bootstrap tools."""

    annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="flowtest.ensure_project",
        description=(
            "在当前授权组织中幂等创建或复用项目; 默认 Dry Run, 不修改已有配置、权限或名称。"
        ),
        structured_output=True,
        annotations=annotations,
    )
    async def ensure_project(
        name: str,
        project_id: str | None = None,
        external_key: str | None = None,
        description: str = "",
        dry_run: bool = True,
        idempotency_key: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        try:
            request = MCPEnsureProjectRequest(
                project_id=project_id,
                external_key=external_key,
                name=name,
                description=description,
                dry_run=dry_run,
            )
        except ValidationError:
            return _error_payload(
                MCPGatewayError(
                    code="MCP_BOOTSTRAP_PROJECT_INVALID",
                    status_code=422,
                    message="项目初始化参数无效",
                )
            )
        return await _tool_payload(
            client.ensure_project(
                request,
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )

    @server.tool(
        name="flowtest.ensure_service_target",
        description=(
            "在测试或 Sandbox 环境中幂等创建或复用 Service Endpoint; 保留 TLS 和出站网络策略。"
        ),
        structured_output=True,
        annotations=annotations,
    )
    async def ensure_service_target(
        project_id: str,
        environment_id: str,
        service_key: str,
        name: str,
        base_url: str,
        service_type: str = "http",
        variant: str = "default",
        dry_run: bool = True,
        idempotency_key: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        try:
            request = MCPEnsureServiceTargetRequest(
                project_id=project_id,
                environment_id=environment_id,
                service_key=service_key,
                name=name,
                base_url=base_url,
                service_type=service_type,
                variant=variant,
                dry_run=dry_run,
            )
        except ValidationError:
            return _error_payload(
                MCPGatewayError(
                    code="MCP_BOOTSTRAP_SERVICE_TARGET_INVALID",
                    status_code=422,
                    message="Service Target 初始化参数无效",
                )
            )
        return await _tool_payload(
            client.ensure_service_target(
                request,
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )

    @server.tool(
        name="flowtest.ensure_test_environment",
        description=(
            "在指定项目中幂等创建或复用 Test/Sandbox 环境; 禁止生产、未分类和敏感明文配置。"
        ),
        structured_output=True,
        annotations=annotations,
    )
    async def ensure_test_environment(
        project_id: str,
        name: str,
        base_url: str,
        classification: str,
        dry_run: bool = True,
        idempotency_key: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        try:
            request = MCPEnsureEnvironmentRequest(
                project_id=project_id,
                name=name,
                base_url=base_url,
                classification=classification,
                dry_run=dry_run,
            )
        except ValidationError:
            return _error_payload(
                MCPGatewayError(
                    code="MCP_BOOTSTRAP_ENVIRONMENT_INVALID",
                    status_code=422,
                    message="测试环境初始化参数无效",
                )
            )
        return await _tool_payload(
            client.ensure_test_environment(
                request,
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )


def _register_propose_repair_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.propose_repair",
        description="默认预检修复; 持久化需要幂等键, 提案仍须人工审核。",
        structured_output=True,
    )
    async def propose_repair(
        request: MCPRepairRequest,
        idempotency_key: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.propose_repair(
                request, idempotency_key=idempotency_key, token=_request_token(ctx, client)
            )
        )


def _register_propose_maintenance_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.propose_maintenance",
        description="默认预检维护, 或原子创建待审核提案并关联现有 Run。",
        structured_output=True,
    )
    async def propose_maintenance(
        request: MCPMaintenanceRequest,
        idempotency_key: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.propose_maintenance(
                request, idempotency_key=idempotency_key, token=_request_token(ctx, client)
            )
        )


def _register_discovery_tools(server: MCPServer, client: MCPReadGatewayClient) -> None:
    """Register bounded discovery and readiness checks without exposing raw storage."""

    annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="flowtest.find_assets",
        description=(
            "Find bounded, tenant-scoped project assets by typed resource kind and query; "
            "returns safe summaries, stable pagination and review links only."
        ),
        structured_output=True,
        annotations=annotations,
    )
    async def find_assets(
        request: MCPFindAssetsRequest,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(client.find_assets(request, token=_request_token(ctx, client)))

    @server.tool(
        name="flowtest.inspect_project_readiness",
        description=(
            "Inspect project Contract, Endpoint, Context, credential-reference metadata, "
            "scopes and Preview prerequisites without returning secret values."
        ),
        structured_output=True,
        annotations=annotations,
    )
    async def inspect_project_readiness(
        project_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_project_readiness(
                project_id,
                token=_request_token(ctx, client),
            )
        )

    @server.tool(
        name="flowtest.check_service_target",
        description=(
            "Check connectivity for one authorized, registered Service Endpoint with a bounded "
            "health request; never scans arbitrary URLs or ports."
        ),
        structured_output=True,
        annotations=annotations,
    )
    async def check_service_target(
        project_id: str,
        endpoint_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.check_service_target(
                project_id,
                endpoint_id,
                token=_request_token(ctx, client),
            )
        )


def _register_planning_tools(server: MCPServer, client: MCPReadGatewayClient) -> None:
    """Register review-only S62 planning and explicit graceful Preview cancellation."""

    proposal_annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="flowtest.prepare_change_regression",
        description=(
            "Prepare or preview one Change Regression analysis bound to fixed Context revisions; "
            "never approves, schedules, executes, or waives a release gate."
        ),
        structured_output=True,
        annotations=proposal_annotations,
    )
    async def prepare_change_regression(
        request: MCPPrepareChangeRegressionRequest,
        idempotency_key: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.prepare_change_regression(
                request,
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )

    @server.tool(
        name="flowtest.propose_test_plan_update",
        description=(
            "Create a typed, pending Test Plan membership suggestion using existing versioned "
            "assets; "
            "never edits a published plan or starts execution."
        ),
        structured_output=True,
        annotations=proposal_annotations,
    )
    async def propose_test_plan_update(
        request: MCPTestPlanUpdateRequest,
        idempotency_key: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.propose_test_plan_update(
                request,
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )

    @server.tool(
        name="flowtest.cancel_preview",
        description=(
            "Cancel one authorized Preview Execution gracefully and preserve Cleanup; "
            "does not force-cancel production or arbitrary runs."
        ),
        structured_output=True,
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def cancel_preview(
        request: MCPCancelPreviewRequest,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.cancel_preview(request, token=_request_token(ctx, client))
        )


def _register_tools(server: MCPServer, client: MCPReadGatewayClient) -> None:
    _register_coverage_tool(server, client)
    _register_begin_context_tool(server, client)
    _register_close_context_tool(server, client)
    _register_commit_contract_import_tool(server, client)
    _register_compile_integration_tool(server, client)
    _register_diagnose_failure_tool(server, client)
    _register_flow_spec_diff_tool(server, client)

    @server.tool(
        name="flowtest.discover_services",
        description="Read service and endpoint variants visible in one project.",
        structured_output=True,
    )
    async def discover_services(
        project_id: str,
        environment_id: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.discover_services(
                project_id,
                environment_id=environment_id,
                token=_request_token(ctx, client),
            )
        )

    _register_bootstrap_tools(server, client)
    _register_explain_compiler_tool(server, client)
    _register_flow_spec_export_tool(server, client)
    _register_generate_tool(server, client)
    _register_ingest_database_evidence_tool(server, client)
    _register_ingest_evidence_tool(server, client)
    _register_ingest_java_evidence_tool(server, client)
    _register_ingest_java_source_snapshot_tool(server, client)
    _register_affected_flows_tool(server, client)
    _register_change_impact_tool(server, client)
    _register_change_regression_tool(server, client)
    _register_connection_tool(server, client)
    _register_context_diff_tool(server, client)
    _register_context_requirements_tool(server, client)
    _register_discovery_tools(server, client)
    _register_planning_tools(server, client)

    @server.tool(
        name="flowtest.inspect_contract",
        description="Read current API contract structure without request values or secrets.",
        structured_output=True,
    )
    async def inspect_contract(
        project_id: str,
        api_definition_id: str | None = None,
        page: int = 1,
        page_size: int = 100,
        method: str | None = None,
        path: str | None = None,
        service_id: str | None = None,
        version: int | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_contract(
                project_id,
                api_definition_id=api_definition_id,
                page=page,
                page_size=page_size,
                method=method,
                path=path,
                service_id=service_id,
                version=version,
                token=_request_token(ctx, client),
            )
        )

    _register_data_profile_tool(server, client)
    _register_inspect_entity_mapping_tool(server, client)

    @server.tool(
        name="flowtest.inspect_flow",
        description="Read a workflow draft topology and safe operation references.",
        structured_output=True,
    )
    async def inspect_flow(
        workflow_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_workflow(workflow_id, token=_request_token(ctx, client))
        )

    _register_inspect_flow_proposal_tool(server, client)

    @server.tool(
        name="flowtest.inspect_project",
        description="Read safe project metadata within the authenticated organization.",
        structured_output=True,
    )
    async def inspect_project(
        project_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.get_project(project_id, token=_request_token(ctx, client))
        )

    @server.tool(
        name="flowtest.inspect_run_evidence",
        description="Read status evidence for a workflow run without outputs or request data.",
        structured_output=True,
    )
    async def inspect_run_evidence(
        execution_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_run_evidence(execution_id, token=_request_token(ctx, client))
        )

    _register_source_evidence_tool(server, client)
    _register_inspect_context_tool(server, client)
    _register_test_evidence_tool(server, client)

    @server.tool(
        name="flowtest.list_projects",
        description="List projects visible in the authenticated organization.",
        structured_output=True,
    )
    async def list_projects(
        page: int = 1,
        page_size: int = 20,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.list_projects(
                page=page,
                page_size=page_size,
                token=_request_token(ctx, client),
            )
        )

    _register_plan_integration_tool(server, client)
    _register_preview_contract_import_tool(server, client)
    _register_preview_flow_proposal_tool(server, client)
    _register_propose_flow_draft_tool(server, client)
    _register_propose_maintenance_tool(server, client)
    _register_propose_repair_tool(server, client)

    @server.tool(
        name="flowtest.propose_test_design",
        description="Create a draft Test Design ChangeSet for human review; never applies it.",
        structured_output=True,
    )
    async def propose_test_design(
        project_id: str,
        title: str,
        confidence: float,
        risk_level: str,
        design: dict[str, Any],
        idempotency_key: str,
        dry_run: bool = True,
        test_cases: list[dict[str, Any]] | None = None,
        source_ref: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": project_id,
            "title": title,
            "confidence": confidence,
            "risk_level": risk_level,
            "design": design,
            "idempotency_key": idempotency_key,
            "dry_run": dry_run,
            "test_cases": test_cases or [],
        }
        if source_ref is not None:
            payload["source_ref"] = source_ref
        return await _tool_payload(
            client.propose_test_design(payload, token=_request_token(ctx, client))
        )

    _register_flow_spec_validate_tool(server, client)
    _register_validate_integration_plan_tool(server, client)
    # The SDK preserves insertion order in list_tools.  Keep the public catalog stable even
    # when a capability group is implemented in one registration helper.
    server._tool_manager._tools = dict(sorted(server._tool_manager._tools.items()))


def _register_plan_integration_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.plan_integration_test",
        description=(
            "Resolve authorized assets into a deterministic, evidence-bearing Integration Plan."
        ),
        structured_output=True,
    )
    async def plan_integration_test(
        project_id: str,
        context_id: str,
        context_revision_id: str,
        actors: list[PlanActor],
        target_environment: PlanTargetEnvironment,
        operations: list[IntegrationPlanOperationSelectionRequest],
        preconditions: list[PlanPrecondition] | None = None,
        existing_auth: ExistingAuthWorkflowSelectionRequest | None = None,
        cleanup_requirements: list[PlanCleanupRequirement] | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": project_id,
            "context_id": context_id,
            "context_revision_id": context_revision_id,
            "actors": [item.model_dump(mode="json") for item in actors],
            "target_environment": target_environment.model_dump(mode="json"),
            "operations": [item.model_dump(mode="json") for item in operations],
            "preconditions": [item.model_dump(mode="json") for item in preconditions or []],
            "cleanup_requirements": [
                item.model_dump(mode="json") for item in cleanup_requirements or []
            ],
        }
        if existing_auth is not None:
            payload["existing_auth"] = existing_auth.model_dump(mode="json")
        return await _tool_payload(
            client.plan_integration_test(payload, token=_request_token(ctx, client))
        )


def _register_validate_integration_plan_tool(
    server: MCPServer, client: MCPReadGatewayClient
) -> None:
    @server.tool(
        name="flowtest.validate_integration_plan",
        description="Validate a strict Integration Plan without persistence or execution.",
        structured_output=True,
    )
    async def validate_plan(
        plan: IntegrationPlan,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.validate_integration_plan(plan, token=_request_token(ctx, client))
        )


def _register_compile_integration_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.compile_integration_flowspec",
        description="Compile an Integration Plan deterministically into an importable FlowSpec.",
        structured_output=True,
    )
    async def compile_plan(
        plan: IntegrationPlan,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.compile_integration_flowspec(plan, token=_request_token(ctx, client))
        )


def _register_explain_compiler_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.explain_compiler_diagnostics",
        description="Explain deterministic compiler blockers and required human reviews.",
        structured_output=True,
    )
    async def explain_diagnostics(
        plan: IntegrationPlan,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.explain_compiler_diagnostics(plan, token=_request_token(ctx, client))
        )


def _register_propose_flow_draft_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.propose_flow_draft",
        description=(
            "Dry-run or create one idempotent AIChangeSet Draft; never reviews, applies, "
            "publishes, or executes it."
        ),
        structured_output=True,
    )
    async def propose_flow_draft(
        project_id: str,
        context_id: str,
        context_revision_id: str,
        integration_plan: IntegrationPlan,
        compilation: IntegrationPlanCompilation,
        idempotency_key: str,
        dry_run: bool = True,
        workflow_id: str | None = None,
        expected_revision: int | None = None,
        source_ref: str | None = None,
        service_mappings: dict[str, str] | None = None,
        operation_mappings: dict[str, str] | None = None,
        operation_version_mappings: dict[str, int] | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        spec = compilation.flow_spec
        if spec is None:
            return _error_payload(
                MCPGatewayError(
                    code="INTEGRATION_PLAN_NOT_IMPORTABLE",
                    status_code=422,
                    message="Integration Plan compilation has no importable FlowSpec",
                )
            )
        payload: dict[str, Any] = {
            "project_id": project_id,
            "context_id": context_id,
            "context_revision_id": context_revision_id,
            "spec": spec.model_dump(mode="json", by_alias=True),
            "integration_plan": integration_plan.model_dump(mode="json"),
            "compilation": compilation.model_dump(mode="json"),
            "dry_run": dry_run,
            "service_mappings": service_mappings or {},
            "operation_mappings": operation_mappings or {},
            "operation_version_mappings": operation_version_mappings or {},
        }
        if workflow_id is not None:
            payload["workflow_id"] = workflow_id
        if expected_revision is not None:
            payload["expected_revision"] = expected_revision
        if source_ref is not None:
            payload["source_ref"] = source_ref
        return await _tool_payload(
            client.propose_flow_draft(
                payload,
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )


def _register_preview_flow_proposal_tool(
    server: MCPServer,
    client: MCPReadGatewayClient,
) -> None:
    @server.tool(
        name="flowtest.preview_flow_proposal",
        description=(
            "Execute an accepted Flow Proposal only in a Test/Sandbox environment with "
            "a matching, unexpired, one-time human approval and frozen preview budget."
        ),
        structured_output=True,
    )
    async def preview_flow_proposal(
        project_id: str,
        change_set_id: str,
        environment_id: str,
        approval_id: str,
        idempotency_key: str,
        runtime_variables: dict[str, str] | None = None,
        runtime_headers: dict[str, str] | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.preview_flow_proposal(
                change_set_id,
                {
                    "project_id": project_id,
                    "environment_id": environment_id,
                    "approval_id": approval_id,
                    "runtime_variables": runtime_variables or {},
                    "runtime_headers": runtime_headers or {},
                },
                idempotency_key=idempotency_key,
                token=_request_token(ctx, client),
            )
        )


def _register_inspect_flow_proposal_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_flow_proposal",
        description="Inspect a tenant-scoped Flow Proposal and its visual review evidence.",
        structured_output=True,
    )
    async def inspect_flow_proposal(
        project_id: str,
        change_set_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_flow_proposal(
                project_id,
                change_set_id,
                token=_request_token(ctx, client),
            )
        )


def _register_begin_context_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.begin_test_context",
        description="Begin a tenant-scoped, revisioned test context with bounded evidence needs.",
        structured_output=True,
    )
    async def begin_test_context(
        project_id: str,
        name: str,
        objective: str,
        target_environment_id: str | None = None,
        ttl_seconds: int = 3600,
        required_evidence: list[EvidenceProviderType] | None = None,
        repository_revisions: list[RevisionReference] | None = None,
        contract_revisions: list[RevisionReference] | None = None,
        data_profile_revisions: list[RevisionReference] | None = None,
        existing_test_revision: RevisionReference | None = None,
        knowledge_snapshot: ContextKnowledgeSnapshot | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": project_id,
            "name": name,
            "objective": objective,
            "ttl_seconds": ttl_seconds,
            "required_evidence": [
                value.value for value in required_evidence or [EvidenceProviderType.CONTRACT]
            ],
            "repository_revisions": [
                value.model_dump(mode="json") for value in repository_revisions or []
            ],
            "contract_revisions": [
                value.model_dump(mode="json") for value in contract_revisions or []
            ],
            "data_profile_revisions": [
                value.model_dump(mode="json") for value in data_profile_revisions or []
            ],
        }
        if target_environment_id is not None:
            payload["target_environment_id"] = target_environment_id
        if existing_test_revision is not None:
            payload["existing_test_revision"] = existing_test_revision.model_dump(mode="json")
        if knowledge_snapshot is not None:
            payload["knowledge_snapshot"] = knowledge_snapshot.model_dump(mode="json")
        return await _tool_payload(
            client.begin_test_context(payload, token=_request_token(ctx, client))
        )


def _register_close_context_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.close_test_context",
        description="Close a test context so it can no longer receive evidence or proposals.",
        structured_output=True,
    )
    async def close_test_context(
        context_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.close_test_context(context_id, token=_request_token(ctx, client))
        )


def _register_ingest_evidence_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.ingest_external_evidence",
        description=("Ingest a strict, revisioned External Evidence Envelope as untrusted data."),
        structured_output=True,
    )
    async def ingest_external_evidence(
        context_id: str,
        envelope: ExternalEvidenceEnvelope,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.ingest_external_evidence(
                context_id,
                envelope.model_dump(mode="json"),
                token=_request_token(ctx, client),
            )
        )


def _register_ingest_database_evidence_tool(
    server: MCPServer, client: MCPReadGatewayClient
) -> None:
    @server.tool(
        name="flowtest.ingest_database_evidence",
        description="写入严格、仅用于设计的数据库结构与脱敏分布证据。",
        structured_output=True,
    )
    async def ingest_database_evidence(
        context_id: str,
        evidence: DatabaseEvidenceSubmission,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.ingest_database_evidence(
                context_id,
                evidence.model_dump(mode="json"),
                token=_request_token(ctx, client),
            )
        )


def _register_ingest_java_evidence_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.ingest_java_evidence",
        description="写入严格的外部 Java/Spring 结构证据，不执行目标代码。",
        structured_output=True,
    )
    async def ingest_java_evidence(
        context_id: str,
        evidence: JavaEvidenceSubmission,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.ingest_java_evidence(
                context_id,
                evidence.model_dump(mode="json"),
                token=_request_token(ctx, client),
            )
        )


def _register_ingest_java_source_snapshot_tool(
    server: MCPServer, client: MCPReadGatewayClient
) -> None:
    @server.tool(
        name="flowtest.ingest_java_source_snapshot",
        description=(
            "使用 FlowTest 内置 Java/Spring Provider 静态分析有界源码快照并写入 Context；"
            "不编译或执行目标代码。"
        ),
        structured_output=True,
    )
    async def ingest_java_source_snapshot(
        context_id: str,
        source_ref: str,
        source_revision: str,
        subject_ref: str,
        files: object,
        execute_analyzed_code: bool = False,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        try:
            snapshot = JavaSourceInput.model_validate(
                {
                    "source": {"ref": source_ref, "revision": source_revision},
                    "subject_ref": subject_ref,
                    "files": files,
                    "execute_analyzed_code": execute_analyzed_code,
                }
            )
        except ValidationError:
            return _error_payload(
                MCPGatewayError(
                    code="MCP_JAVA_SOURCE_SNAPSHOT_INVALID",
                    status_code=422,
                    message="Java source snapshot validation failed",
                )
            )
        return await _tool_payload(
            client.ingest_java_source_snapshot(
                context_id,
                snapshot.model_dump(mode="json"),
                token=_request_token(ctx, client),
            )
        )


def _register_inspect_entity_mapping_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_entity_mapping",
        description="查看测试上下文中可追溯的实体候选与尚未解决的歧义。",
        structured_output=True,
    )
    async def inspect_entity_mapping(
        context_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_entity_mapping(context_id, token=_request_token(ctx, client))
        )


def _register_context_requirements_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_context_requirements",
        description="Inspect missing evidence and conflict requirements for a test context.",
        structured_output=True,
    )
    async def inspect_context_requirements(
        context_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_context_requirements(context_id, token=_request_token(ctx, client))
        )


def _register_inspect_context_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_test_context",
        description="Inspect the current immutable revision and redacted evidence summary.",
        structured_output=True,
    )
    async def inspect_test_context(
        context_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_test_context(context_id, token=_request_token(ctx, client))
        )


def _register_flow_spec_diff_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.diff_flowspec",
        description="Compare two portable FlowSpecs without persistence.",
        structured_output=True,
    )
    async def diff_flowspec(
        project_id: str,
        after: dict[str, Any],
        before: dict[str, Any] | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.diff_flow_specs(
                project_id,
                before=before,
                after=after,
                token=_request_token(ctx, client),
            )
        )


def _register_flow_spec_export_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.export_flowspec",
        description="Export a portable, validated FlowSpec from a workflow.",
        structured_output=True,
    )
    async def export_flowspec(
        project_id: str,
        workflow_id: str,
        version: int | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.export_flow_spec(
                project_id,
                workflow_id,
                version=version,
                token=_request_token(ctx, client),
            )
        )


def _register_flow_spec_validate_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.validate_flowspec",
        description="Validate and normalize a portable FlowSpec without persistence.",
        structured_output=True,
    )
    async def validate_flowspec(
        project_id: str,
        spec: dict[str, Any],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.validate_flow_spec(project_id, spec, token=_request_token(ctx, client))
        )


def _register_coverage_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.analyze_test_coverage",
        description="Generate dimension-level coverage and explicit gaps without persistence.",
        structured_output=True,
    )
    async def analyze_test_coverage(
        project_id: str,
        api_definition_id: str,
        generation_policy: dict[str, Any] | None = None,
        additional_evidence: list[dict[str, Any]] | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.analyze_test_coverage(
                project_id,
                {
                    "api_definition_id": api_definition_id,
                    "generation_policy": generation_policy or {},
                    "additional_evidence": additional_evidence or [],
                },
                token=_request_token(ctx, client),
            )
        )


def _register_change_impact_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_change_impact",
        description="Inspect structured contract changes, coverage gaps, and selected assets.",
        structured_output=True,
    )
    async def inspect_change_impact(
        project_id: str,
        impact_run_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_change_impact(
                project_id,
                impact_run_id,
                token=_request_token(ctx, client),
            )
        )


def _register_generate_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.generate_test_design",
        description=(
            "Generate scenarios, oracles, coverage, and evidence from an API contract; read-only."
        ),
        structured_output=True,
    )
    async def generate_test_design(
        project_id: str,
        api_definition_id: str,
        generation_policy: dict[str, Any] | None = None,
        additional_evidence: list[dict[str, Any]] | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.generate_test_design(
                project_id,
                {
                    "api_definition_id": api_definition_id,
                    "generation_policy": generation_policy or {},
                    "additional_evidence": additional_evidence or [],
                },
                token=_request_token(ctx, client),
            )
        )


def _register_data_profile_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_data_profile",
        description=(
            "Inspect a typed, masked data profile without accepting credentials or raw rows."
        ),
        structured_output=True,
    )
    async def inspect_data_profile(
        project_id: str,
        profile: dict[str, Any],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_data_profile(project_id, profile, token=_request_token(ctx, client))
        )


def _register_source_evidence_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_source_evidence",
        description="Analyze a bounded allow-listed Python repository snapshot through AST only.",
        structured_output=True,
    )
    async def inspect_source_evidence(
        project_id: str,
        snapshot: dict[str, Any],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_source_evidence(project_id, snapshot, token=_request_token(ctx, client))
        )


def _register_test_evidence_tool(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.tool(
        name="flowtest.inspect_test_evidence",
        description="Inspect evidence-backed generated test semantics without persistence.",
        structured_output=True,
    )
    async def inspect_test_evidence(
        project_id: str,
        api_definition_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.generate_test_design(
                project_id,
                {"api_definition_id": api_definition_id},
                token=_request_token(ctx, client),
            )
        )


def _register_resources(server: MCPServer, client: MCPReadGatewayClient) -> None:
    @server.resource(
        "flowtest://drafts/{workflow_id}",
        name="flowtest-workflow-draft",
        description="Safe workflow topology and draft fingerprint.",
        mime_type="application/json",
    )
    async def workflow_draft(workflow_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        return await _resource_payload(
            client.inspect_workflow(
                workflow_id,
                token=_request_token(ctx, client),
                resource_uri=f"flowtest://drafts/{workflow_id}",
            )
        )

    @server.resource(
        "flowtest://projects/{project_id}",
        name="flowtest-project",
        description="Safe project metadata.",
        mime_type="application/json",
    )
    async def project(project_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        return await _resource_payload(
            client.get_project(
                project_id,
                token=_request_token(ctx, client),
                resource_uri=f"flowtest://projects/{project_id}",
            )
        )

    @server.resource(
        "flowtest://projects/{project_id}/contract",
        name="flowtest-project-contract",
        description="Current API contract structure without secrets.",
        mime_type="application/json",
    )
    async def project_contract(project_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        return await _resource_payload(
            client.inspect_contract(
                project_id,
                token=_request_token(ctx, client),
                resource_uri=f"flowtest://projects/{project_id}/contract",
            )
        )

    @server.resource(
        "flowtest://projects/{project_id}/services",
        name="flowtest-project-services",
        description="Service and endpoint variant discovery without credentials.",
        mime_type="application/json",
    )
    async def project_services(project_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        return await _resource_payload(
            client.discover_services(
                project_id,
                token=_request_token(ctx, client),
                resource_uri=f"flowtest://projects/{project_id}/services",
            )
        )

    @server.resource(
        "flowtest://runs/{execution_id}/evidence",
        name="flowtest-run-evidence",
        description="Execution status evidence without outputs or request data.",
        mime_type="application/json",
    )
    async def run_evidence(execution_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        return await _resource_payload(
            client.inspect_run_evidence(
                execution_id,
                token=_request_token(ctx, client),
                resource_uri=f"flowtest://runs/{execution_id}/evidence",
            )
        )


def _register_prompts(server: MCPServer) -> None:
    @server.prompt(
        name="design_data_case",
        description="Prepare a read-only data case design for human review.",
    )
    def design_data_case(project_id: str = "") -> str:
        return _prompt_text(
            "design_data_case",
            project_id,
            "梳理数据场景、边界和脱敏要求；不要写入数据源，不要执行工作流。",
        )

    @server.prompt(
        name="discover_api_workflow",
        description="Guide read-only discovery of an API workflow.",
    )
    def discover_api_workflow(project_id: str = "") -> str:
        return _prompt_text(
            "discover_api_workflow",
            project_id,
            "先读取项目、Service 和 API Contract，再提出工作流候选；只读，不创建或执行。",
        )

    @server.prompt(
        name="migrate_collection",
        description="Plan a collection migration for human review without applying changes.",
    )
    def migrate_collection(project_id: str = "") -> str:
        return _prompt_text(
            "migrate_collection",
            project_id,
            "比较集合结构和兼容性风险；输出待审核 ChangeSet 建议，不直接修改或发布。",
        )

    @server.prompt(
        name="review_flow_draft",
        description="Review a workflow draft topology and identify risks.",
    )
    def review_flow_draft(workflow_id: str = "") -> str:
        return _prompt_text(
            "review_flow_draft",
            workflow_id,
            "检查节点拓扑、目标引用和覆盖风险；低置信度结论必须人工 Review。",
        )

    @server.prompt(
        name="triage_failure",
        description="Triage read-only execution evidence for human review.",
    )
    def triage_failure(execution_id: str = "") -> str:
        return _prompt_text(
            "triage_failure",
            execution_id,
            "只基于脱敏 evidence 分析失败分类；不重试、不改变运行状态，任何操作需人工确认。",
        )


async def _tool_payload(client_call: Awaitable[Any]) -> dict[str, Any]:
    try:
        envelope = await client_call
    except MCPGatewayError as error:
        return _error_payload(error)
    return dict(envelope.model_dump(mode="json"))


async def _resource_payload(client_call: Any) -> str:
    return json.dumps(await _tool_payload(client_call), ensure_ascii=False, sort_keys=True)


def _request_token(ctx: Context | None, client: MCPReadGatewayClient) -> str | None:
    if ctx is None:
        return getattr(client, "_token", None)
    try:
        request_context = ctx.request_context
    except ValueError:
        # The SDK raises this only for direct in-process calls outside a request.
        return getattr(client, "_token", None)
    request = request_context.request
    if request is None:
        return getattr(client, "_token", None)
    headers = getattr(request, "headers", None)
    authorization = headers.get("authorization", "") if isinstance(headers, Mapping) else ""
    if isinstance(authorization, str):
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    return ""


def _error_payload(error: MCPGatewayError) -> dict[str, Any]:
    return {
        "data": {
            "error": {"code": error.code},
            "connection_diagnostic": connection_diagnostic(error).model_dump(mode="json"),
        },
        "evidence_refs": [],
        "confidence": 0.0,
        "redactions": ["gateway_error_details"],
        "trace_id": error.trace_id,
        "warnings": ["MCP 应用网关未返回业务数据。"],
    }


def _prompt_text(name: str, target: str, instruction: str) -> str:
    target_line = f"目标标识：{target}\n" if target else "目标标识：由调用方补充\n"
    return (
        f"FlowTest MCP Prompt: {name}\n"
        f"{target_line}"
        f"{instruction}\n"
        "本 Prompt 只读；如需写入、执行、重试或发布，必须通过受控 ChangeSet 并请求人工确认。"
    )


def parse_resource_uri(uri: str) -> tuple[str, str]:
    """Validate a FlowTest resource URI for callers that need local routing."""

    parsed = urlsplit(uri)
    if parsed.scheme != "flowtest" or parsed.query or parsed.fragment:
        raise ValueError("unsupported MCP resource URI")
    segments = [unquote(part) for part in parsed.path.split("/") if part]
    if parsed.netloc == "projects" and len(segments) == 1:
        return "project", segments[0]
    if (
        parsed.netloc == "projects"
        and len(segments) == 2
        and segments[1]
        in {
            "contract",
            "services",
        }
    ):
        return segments[1], segments[0]
    if parsed.netloc == "drafts" and len(segments) == 1:
        return "draft", segments[0]
    if parsed.netloc == "runs" and len(segments) == 2 and segments[1] == "evidence":
        return "evidence", segments[0]
    raise ValueError("unsupported MCP resource URI")
