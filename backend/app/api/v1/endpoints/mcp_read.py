"""Read-only REST gateway used by the FlowTest MCP delivery adapter."""

import re
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.dependencies import MCPCurrent, SessionDependency
from app.domain.evidence import DataProfile, SourceSnapshot
from app.domain.mcp_read import MCPCallType, MCPReadCall, input_schema_hash
from app.schemas.flow_spec import FlowSpecDiffRequest, FlowSpecValidateRequest
from app.schemas.mcp_read import MCPReadResponse
from app.schemas.test_engineering import TestEngineeringGenerateRequest
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


@router.post("/projects/{project_id}/test-design/generate", response_model=MCPReadResponse)
async def generate_test_design(
    project_id: UUID,
    payload: TestEngineeringGenerateRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).generate_test_design(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "generate_test_design"),
        payload=payload,
    )
    return _response(result)


@router.post("/projects/{project_id}/coverage/analyze", response_model=MCPReadResponse)
async def analyze_test_coverage(
    project_id: UUID,
    payload: TestEngineeringGenerateRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).generate_test_design(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "analyze_test_coverage"),
        payload=payload,
        coverage_only=True,
    )
    return _response(result)


@router.post("/projects/{project_id}/evidence/source", response_model=MCPReadResponse)
async def inspect_source_evidence(
    project_id: UUID,
    payload: SourceSnapshot,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).inspect_source_evidence(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "inspect_source_evidence"),
        snapshot=payload,
    )
    return _response(result)


@router.post("/projects/{project_id}/evidence/data-profile", response_model=MCPReadResponse)
async def inspect_data_profile(
    project_id: UUID,
    payload: DataProfile,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).inspect_data_profile(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "inspect_data_profile"),
        profile=payload,
    )
    return _response(result)


@router.post("/projects/{project_id}/flow-spec/validate", response_model=MCPReadResponse)
async def validate_flow_spec(
    project_id: UUID,
    payload: FlowSpecValidateRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).validate_flow_spec(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "validate_flowspec"),
        spec=payload.spec,
    )
    return _response(result)


@router.post("/projects/{project_id}/flow-spec/diff", response_model=MCPReadResponse)
async def diff_flow_spec(
    project_id: UUID,
    payload: FlowSpecDiffRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).diff_flow_specs(
        actor=principal.actor,
        project_id=project_id,
        call=_call(request, "diff_flowspec"),
        before=payload.before,
        after=payload.after,
    )
    return _response(result)


@router.get(
    "/projects/{project_id}/flow-spec/workflows/{workflow_id}/export",
    response_model=MCPReadResponse,
)
async def export_flow_spec(
    project_id: UUID,
    workflow_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
    version: int | None = Query(default=None, ge=1),
) -> MCPReadResponse:
    result = await MCPReadService(session).export_flow_spec(
        actor=principal.actor,
        project_id=project_id,
        workflow_id=workflow_id,
        version=version,
        call=_call(request, "export_flowspec"),
    )
    return _response(result)


@router.get(
    "/projects/{project_id}/change-impact/{impact_run_id}",
    response_model=MCPReadResponse,
)
async def inspect_change_impact(
    project_id: UUID,
    impact_run_id: UUID,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadResponse:
    result = await MCPReadService(session).inspect_change_impact(
        actor=principal.actor,
        project_id=project_id,
        impact_run_id=impact_run_id,
        call=_call(request, "inspect_change_impact"),
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
