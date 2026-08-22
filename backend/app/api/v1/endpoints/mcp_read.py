"""Read-only REST gateway used by the FlowTest MCP delivery adapter."""

import re
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.dependencies import MCPCurrent, SessionDependency
from app.domain.mcp_read import MCPCallType, MCPReadCall, input_schema_hash
from app.schemas.mcp_read import MCPReadResponse
from app.services.mcp_read import MCPReadService

router = APIRouter(prefix="/mcp/read")
_CLIENT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")


@router.get("/projects", response_model=MCPReadResponse)
async def list_projects(
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> MCPReadResponse:
    result = await MCPReadService(session).list_projects(
        actor=principal.actor,
        call=_call(request, "list_projects"),
        page=page,
        page_size=page_size,
    )
    return _response(result)


@router.get("/projects/{project_id}", response_model=MCPReadResponse)
async def get_project(
    project_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).get_project(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "inspect_project", f"flowtest://projects/{project_id}"),
    )
    return _response(result)


@router.get("/projects/{project_id}/services", response_model=MCPReadResponse)
async def discover_services(
    project_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
    environment_id: UUID | None = None,
) -> MCPReadResponse:
    result = await MCPReadService(session).discover_services(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "discover_services", f"flowtest://projects/{project_id}/services"),
        environment_id=environment_id,
    )
    return _response(result)


@router.get("/projects/{project_id}/contracts", response_model=MCPReadResponse)
async def inspect_contract(
    project_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
    api_definition_id: UUID | None = None,
) -> MCPReadResponse:
    result = await MCPReadService(session).inspect_contract(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "inspect_contract", f"flowtest://projects/{project_id}/contract"),
        api_definition_id=api_definition_id,
    )
    return _response(result)


@router.get("/workflows/{workflow_id}/draft", response_model=MCPReadResponse)
async def inspect_workflow(
    workflow_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).inspect_workflow(
        actor=principal.actor,
        workflow_id=workflow_id,
        call=_call(request, "inspect_flow", f"flowtest://drafts/{workflow_id}"),
    )
    return _response(result)


@router.get("/runs/{execution_id}/evidence", response_model=MCPReadResponse)
async def inspect_run_evidence(
    execution_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).inspect_run_evidence(
        actor=principal.actor,
        execution_id=execution_id,
        call=_call(request, "inspect_run_evidence", f"flowtest://runs/{execution_id}/evidence"),
    )
    return _response(result)


def _call(request: Request, operation: str, resource_uri: str | None = None) -> MCPReadCall:
    client_version = request.headers.get("x-mcp-client-version", "unknown")
    if _CLIENT_VERSION_PATTERN.fullmatch(client_version) is None:
        client_version = "unknown"
    requested_uri = request.headers.get("x-mcp-resource-uri")
    safe_uri = requested_uri if requested_uri and requested_uri.startswith("flowtest://") else None
    effective_uri = safe_uri or resource_uri
    return MCPReadCall(
        operation=operation,
        call_type=MCPCallType.RESOURCE if safe_uri else MCPCallType.TOOL,
        input_schema_hash=input_schema_hash(operation),
        client_version=client_version,
        resource_uri=effective_uri,
    )


def _response(result: object) -> MCPReadResponse:
    if hasattr(result, "model_dump"):
        return MCPReadResponse.model_validate(result.model_dump(mode="json"))
    return MCPReadResponse.model_validate(result)
