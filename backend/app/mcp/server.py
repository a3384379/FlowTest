"""Official MCP SDK adapter for FlowTest read operations."""

# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

import json
from collections.abc import Awaitable, Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from app.domain.mcp_read import MCP_SERVER_NAME, MCP_SERVER_VERSION, MCPReadEnvelope
from app.mcp.client import MCPGatewayError, MCPReadGatewayClient

READ_ONLY_INSTRUCTIONS = (
    "FlowTest MCP 仅提供只读项目、服务、契约、工作流草稿和执行证据。"
    "它不会创建、修改、删除或执行任何 FlowTest 资源；任何后续写入都必须经由"
    "受控 ChangeSet 和人工确认。输出中的请求值、认证信息、Secret、PII 和响应体"
    "会被省略或脱敏。"
)


def create_mcp_server(
    *,
    client: MCPReadGatewayClient | None = None,
    api_base_url: str | None = None,
    service_account_token: str | None = None,
) -> MCPServer:
    """Create a server with stable, sorted read-only tools/resources/prompts."""

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
        version=MCP_SERVER_VERSION,
        instructions=READ_ONLY_INSTRUCTIONS,
    )

    _register_resources(server, client)
    _register_tools(server, client)
    _register_prompts(server)
    return server


def _register_tools(server: MCPServer, client: MCPReadGatewayClient) -> None:
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


async def _tool_payload(client_call: Awaitable[MCPReadEnvelope]) -> dict[str, Any]:
    try:
        envelope = await client_call
    except MCPGatewayError as error:
        return _error_payload(error)
    return envelope.model_dump(mode="json")


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
        "warnings": ["只读应用网关未返回业务数据。"],
    }


def _prompt_text(name: str, target: str, instruction: str) -> str:
    target_line = f"目标标识：{target}\n" if target else "目标标识：由调用方补充\n"
    return (
        f"FlowTest MCP Prompt: {name}\n"
        f"{target_line}"
        f"{instruction}\n"
        "本次 MCP 能力只读；所有写入、执行、重试或发布动作必须停止并请求人工确认。"
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
