"""Official MCP SDK adapter for FlowTest read operations."""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

import json
from collections.abc import Awaitable, Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from app.domain.mcp_read import MCP_SERVER_NAME
from app.domain.test_contexts import (
    MCP_CONTEXT_EVIDENCE_SERVER_VERSION,
    ContextKnowledgeSnapshot,
    EvidenceProviderType,
    ExternalEvidenceEnvelope,
    RevisionReference,
)
from app.mcp.client import MCPGatewayError, MCPReadGatewayClient

READ_ONLY_INSTRUCTIONS = (
    "FlowTest MCP 提供只读项目、服务、契约、工作流草稿和执行证据，并允许提交"
    "版本化外部证据与只进入待审核状态的 Test Design ChangeSet。"
    "它不会自动发布、执行、删除、修改"
    "权限或创建 Credential；高风险写入必须由人工批准。输出中的请求值、认证信息、"
    "Secret、PII 和响应体会被省略或脱敏。"
)


def create_mcp_server(
    *,
    client: MCPReadGatewayClient | None = None,
    api_base_url: str | None = None,
    service_account_token: str | None = None,
) -> MCPServer:
    """Create a server with stable, sorted tools/resources/prompts."""

    if client is None:
        from app.core.config import settings

        client = MCPReadGatewayClient(
            base_url=api_base_url or settings.mcp_api_base_url,
            token=service_account_token or settings.mcp_service_account_token or None,
            timeout=settings.mcp_request_timeout_seconds,
            client_version=settings.mcp_client_version,
        )
    server = MCPServer(
        name=MCP_SERVER_NAME,
        version=MCP_CONTEXT_EVIDENCE_SERVER_VERSION,
        instructions=READ_ONLY_INSTRUCTIONS,
    )

    _register_resources(server, client)
    _register_tools(server, client)
    _register_prompts(server)
    return server


def _register_tools(server: MCPServer, client: MCPReadGatewayClient) -> None:
    _register_coverage_tool(server, client)
    _register_begin_context_tool(server, client)
    _register_close_context_tool(server, client)
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

    _register_flow_spec_export_tool(server, client)
    _register_generate_tool(server, client)
    _register_ingest_evidence_tool(server, client)
    _register_change_impact_tool(server, client)
    _register_context_requirements_tool(server, client)

    @server.tool(
        name="flowtest.inspect_contract",
        description="Read current API contract structure without request values or secrets.",
        structured_output=True,
    )
    async def inspect_contract(
        project_id: str,
        api_definition_id: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        return await _tool_payload(
            client.inspect_contract(
                project_id,
                api_definition_id=api_definition_id,
                token=_request_token(ctx, client),
            )
        )

    _register_data_profile_tool(server, client)

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
    if ctx is not None:
        try:
            request = ctx.request_context.request
            headers = getattr(request, "headers", None)
            if isinstance(headers, Mapping):
                authorization = headers.get("authorization", "")
                if isinstance(authorization, str):
                    scheme, _, token = authorization.partition(" ")
                    if scheme.lower() == "bearer" and token.strip():
                        return token.strip()
        except (AttributeError, RuntimeError, ValueError):
            pass
    return getattr(client, "_token", None)


def _error_payload(error: MCPGatewayError) -> dict[str, Any]:
    return {
        "data": {"error": {"code": error.code}},
        "evidence_refs": [],
        "confidence": 0.0,
        "redactions": ["gateway_error_details"],
        "trace_id": "mcp-gateway",
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
