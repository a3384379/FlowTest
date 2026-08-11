from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from app.api.dependencies import CurrentUser, SessionDependency, WorkflowCoordinator
from app.composition import build_workflow_service
from app.engine.scheduler import WorkflowRunResult
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution
from app.schemas.common import Page
from app.schemas.workflows import (
    WorkflowCreate,
    WorkflowDebugNodeResponse,
    WorkflowDebugRequest,
    WorkflowDebugResponse,
    WorkflowDraftUpdate,
    WorkflowExecuteRequest,
    WorkflowExecutionDetailResponse,
    WorkflowExecutionResponse,
    WorkflowNodeExecutionResponse,
    WorkflowResponse,
    WorkflowVersionChangeResponse,
    WorkflowVersionDiffResponse,
    WorkflowVersionResponse,
)
from app.services.idempotency import IdempotencyService
from app.services.workflows import WorkflowService

router = APIRouter(prefix="/projects/{project_id}")


@router.get("/workflows", response_model=Page[WorkflowResponse])
async def list_workflows(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[WorkflowResponse]:
    items, total = await WorkflowService(session).list_workflows(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[WorkflowResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    project_id: UUID,
    payload: WorkflowCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowResponse:
    workflow = await WorkflowService(session).create(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        definition=payload.definition,
    )
    return WorkflowResponse.model_validate(workflow)


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    project_id: UUID,
    workflow_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowResponse:
    workflow = await WorkflowService(session).get(
        actor=current_user,
        project_id=project_id,
        workflow_id=workflow_id,
    )
    return WorkflowResponse.model_validate(workflow)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow_draft(
    project_id: UUID,
    workflow_id: UUID,
    payload: WorkflowDraftUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowResponse:
    workflow = await WorkflowService(session).update_draft(
        actor=current_user,
        project_id=project_id,
        workflow_id=workflow_id,
        expected_revision=payload.expected_revision,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        change_folder="folder_id" in payload.model_fields_set,
        definition=payload.definition,
    )
    return WorkflowResponse.model_validate(workflow)


@router.post("/workflows/{workflow_id}/versions", response_model=WorkflowVersionResponse)
async def publish_workflow(
    project_id: UUID,
    workflow_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowVersionResponse:
    version = await WorkflowService(session).publish(
        actor=current_user,
        project_id=project_id,
        workflow_id=workflow_id,
    )
    return WorkflowVersionResponse.model_validate(version)


@router.get("/workflows/{workflow_id}/versions", response_model=list[WorkflowVersionResponse])
async def list_workflow_versions(
    project_id: UUID,
    workflow_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[WorkflowVersionResponse]:
    versions = await WorkflowService(session).list_versions(
        actor=current_user,
        project_id=project_id,
        workflow_id=workflow_id,
    )
    return [WorkflowVersionResponse.model_validate(version) for version in versions]


@router.get(
    "/workflows/{workflow_id}/versions/{from_version}/diff/{to_version}",
    response_model=WorkflowVersionDiffResponse,
)
async def diff_workflow_versions(
    project_id: UUID,
    workflow_id: UUID,
    from_version: int,
    to_version: int,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowVersionDiffResponse:
    diff = await WorkflowService(session).diff_versions(
        actor=current_user,
        project_id=project_id,
        workflow_id=workflow_id,
        from_version=from_version,
        to_version=to_version,
    )
    return WorkflowVersionDiffResponse(
        from_version=diff.from_version,
        to_version=diff.to_version,
        changes=[
            WorkflowVersionChangeResponse(
                path=change.path,
                before=change.before,
                after=change.after,
            )
            for change in diff.changes
        ],
    )


@router.post("/workflows/{workflow_id}/debug", response_model=WorkflowDebugResponse)
async def debug_workflow(
    project_id: UUID,
    workflow_id: UUID,
    payload: WorkflowDebugRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowDebugResponse:
    result = await WorkflowService(session).debug_to_breakpoint(
        actor=current_user,
        project_id=project_id,
        workflow_id=workflow_id,
        environment_id=payload.environment_id,
        version=payload.version,
        runtime_variables=payload.runtime_variables,
        runtime_headers=payload.runtime_headers,
        breakpoint_node_id=payload.breakpoint_node_id,
    )
    return _debug_response(result, mode="breakpoint", target_node_id=payload.breakpoint_node_id)


@router.post(
    "/workflows/{workflow_id}/executions",
    response_model=WorkflowExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_workflow(
    project_id: UUID,
    workflow_id: UUID,
    payload: WorkflowExecuteRequest,
    session: SessionDependency,
    current_user: CurrentUser,
    coordinator: WorkflowCoordinator,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> WorkflowExecutionResponse:
    async def start() -> WorkflowExecutionResponse:
        execution, plan = await build_workflow_service(session).prepare_execution(
            actor=current_user,
            project_id=project_id,
            workflow_id=workflow_id,
            environment_id=payload.environment_id,
            version=payload.version,
            runtime_variables=payload.runtime_variables,
            runtime_headers=payload.runtime_headers,
        )
        coordinator.start(plan)
        return WorkflowExecutionResponse.model_validate(execution)

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"user:{current_user.id}",
        operation=f"workflow.execute:{workflow_id}",
        request_payload=payload.model_dump(mode="json"),
        action=start,
    )
    return WorkflowExecutionResponse.model_validate(response)


@router.get("/workflow-executions", response_model=Page[WorkflowExecutionResponse])
async def list_workflow_executions(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[WorkflowExecutionResponse]:
    items, total = await WorkflowService(session).list_executions(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[WorkflowExecutionResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/workflow-executions/{execution_id}", response_model=WorkflowExecutionDetailResponse)
async def get_workflow_execution(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowExecutionDetailResponse:
    execution, nodes, children = await WorkflowService(session).get_execution(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
    )
    return _execution_detail(execution, nodes, children)


@router.post(
    "/workflow-executions/{execution_id}/cancel",
    response_model=WorkflowExecutionResponse,
)
async def cancel_workflow_execution(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowExecutionResponse:
    execution = await WorkflowService(session).request_cancel(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
    )
    return WorkflowExecutionResponse.model_validate(execution)


@router.post(
    "/workflow-executions/{execution_id}/nodes/{node_id}/replay",
    response_model=WorkflowDebugResponse,
)
async def replay_workflow_node(
    project_id: UUID,
    execution_id: UUID,
    node_id: str,
    session: SessionDependency,
    current_user: CurrentUser,
) -> WorkflowDebugResponse:
    result = await WorkflowService(session).replay_node(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
        node_id=node_id,
    )
    return _debug_response(result, mode="replay", target_node_id=node_id)


def _execution_detail(
    execution: WorkflowExecution,
    nodes: list[WorkflowNodeExecution],
    children: list[WorkflowExecution],
) -> WorkflowExecutionDetailResponse:
    return WorkflowExecutionDetailResponse(
        execution=WorkflowExecutionResponse.model_validate(execution),
        nodes=[WorkflowNodeExecutionResponse.model_validate(node) for node in nodes],
        children=[WorkflowExecutionResponse.model_validate(child) for child in children],
    )


def _debug_response(
    result: WorkflowRunResult,
    *,
    mode: str,
    target_node_id: str,
) -> WorkflowDebugResponse:
    return WorkflowDebugResponse(
        status=result.status,
        mode=mode,
        target_node_id=target_node_id,
        context=result.context,
        nodes=[
            WorkflowDebugNodeResponse(
                node_id=record.node_id,
                node_type=record.node_type.value,
                name=record.name,
                status=record.status,
                attempts=record.attempts,
                output=record.output,
                error_code=record.error_code,
                error_message=record.error_message,
                started_at=record.started_at,
                completed_at=record.completed_at,
            )
            for record in result.records
        ],
    )
