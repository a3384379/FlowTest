import logging
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from app.api.dependencies import CurrentUser, SessionDependency, WorkflowCoordinator
from app.composition import build_workflow_service
from app.core.errors import AppError
from app.schemas.flow_spec import (
    FlowSpecApplyResponse,
    FlowSpecChangeSetCursorResponse,
    FlowSpecChangeSetDetailResponse,
    FlowSpecChangeSetListResponse,
    FlowSpecChangeSetResponse,
    FlowSpecDiffRequest,
    FlowSpecDiffResponse,
    FlowSpecExportResponse,
    FlowSpecImportRequest,
    FlowSpecMcpProposalListResponse,
    FlowSpecReviewRequest,
    FlowSpecValidateRequest,
    FlowSpecValidationResponse,
    FlowSpecVisualProposalResponse,
)
from app.schemas.sandbox_preview import (
    SandboxPreviewApprovalCreate,
    SandboxPreviewApprovalResponse,
    SandboxPreviewExecuteRequest,
    SandboxPreviewExecutionResponse,
)
from app.schemas.workflows import WorkflowExecutionResponse
from app.services.durable_execution import DurableExecutionService
from app.services.flow_spec import FlowSpecChangeSetCursor, FlowSpecChangeSetView, FlowSpecService
from app.services.idempotency import IdempotencyService
from app.services.sandbox_preview import SandboxPreviewService

router = APIRouter(prefix="/projects/{project_id}/flow-specs")
logger = logging.getLogger(__name__)


@router.get("/workflows/{workflow_id}/export", response_model=FlowSpecExportResponse)
async def export_flow_spec(
    project_id: UUID,
    workflow_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> FlowSpecExportResponse:
    result = await FlowSpecService(session).export(
        actor=current_user,
        project_id=project_id,
        workflow_id=workflow_id,
        version=version,
    )
    return FlowSpecExportResponse(
        workflow_id=result.workflow.id,
        version=result.version,
        draft_revision=result.workflow.draft_revision if result.version is None else None,
        fingerprint=result.pipeline.fingerprint,
        spec=result.pipeline.spec,
        validation=result.pipeline.validation,
        compatibility=result.pipeline.compatibility,
    )


@router.post("/validate", response_model=FlowSpecValidationResponse)
async def validate_flow_spec(
    project_id: UUID,
    payload: FlowSpecValidateRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlowSpecValidationResponse:
    pipeline = await FlowSpecService(session).validate(
        actor=current_user,
        project_id=project_id,
        spec=payload.spec,
    )
    return FlowSpecValidationResponse(
        fingerprint=pipeline.fingerprint,
        spec=pipeline.spec,
        validation=pipeline.validation,
        compatibility=pipeline.compatibility,
    )


@router.post("/diff", response_model=FlowSpecDiffResponse)
async def diff_flow_specs(
    project_id: UUID,
    payload: FlowSpecDiffRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlowSpecDiffResponse:
    result = await FlowSpecService(session).diff(
        actor=current_user,
        project_id=project_id,
        before=payload.before,
        after=payload.after,
    )
    return FlowSpecDiffResponse(
        before_fingerprint=result.before_fingerprint,
        after_fingerprint=result.after_fingerprint,
        changes=list(result.changes),
    )


@router.post(
    "/imports",
    response_model=FlowSpecChangeSetDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_flow_spec(
    project_id: UUID,
    payload: FlowSpecImportRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlowSpecChangeSetDetailResponse:
    view = await FlowSpecService(session).create_import(
        actor=current_user,
        project_id=project_id,
        payload=payload,
    )
    return _detail(view)


@router.get("/change-sets", response_model=FlowSpecChangeSetListResponse)
async def list_flow_spec_change_sets(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> FlowSpecChangeSetListResponse:
    views, total = await FlowSpecService(session).list_change_sets(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return FlowSpecChangeSetListResponse(
        items=[_summary(view) for view in views],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/change-sets/mcp-proposals", response_model=FlowSpecMcpProposalListResponse)
async def list_mcp_flow_proposals(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page_size: int = Query(default=100, ge=1, le=100),
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> FlowSpecMcpProposalListResponse:
    if (cursor_created_at is None) != (cursor_id is None):
        raise AppError(
            code="FLOWSPEC_CURSOR_INVALID",
            message="FlowSpec 分页游标不完整",
            status_code=422,
        )
    cursor = (
        FlowSpecChangeSetCursor(created_at=cursor_created_at, id=cursor_id)
        if cursor_created_at is not None and cursor_id is not None
        else None
    )
    result = await FlowSpecService(session).list_mcp_proposals(
        actor=current_user,
        project_id=project_id,
        page_size=page_size,
        cursor=cursor,
    )
    return FlowSpecMcpProposalListResponse(
        items=[_summary(view) for view in result.views],
        next_cursor=(
            FlowSpecChangeSetCursorResponse(
                created_at=result.next_cursor.created_at,
                id=result.next_cursor.id,
            )
            if result.next_cursor is not None
            else None
        ),
        page_size=page_size,
    )


@router.get(
    "/change-sets/{change_set_id}",
    response_model=FlowSpecChangeSetDetailResponse,
)
async def get_flow_spec_change_set(
    project_id: UUID,
    change_set_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlowSpecChangeSetDetailResponse:
    view = await FlowSpecService(session).get_change_set(
        actor=current_user,
        project_id=project_id,
        change_set_id=change_set_id,
    )
    return _detail(view)


@router.get(
    "/change-sets/{change_set_id}/visual-proposal",
    response_model=FlowSpecVisualProposalResponse,
)
async def get_visual_flow_proposal(
    project_id: UUID,
    change_set_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlowSpecVisualProposalResponse:
    proposal = await FlowSpecService(session).get_visual_proposal(
        actor=current_user,
        project_id=project_id,
        change_set_id=change_set_id,
    )
    return FlowSpecVisualProposalResponse(
        proposal=_detail(proposal.view),
        existing_definition=proposal.existing_definition,
        proposed_definition=proposal.proposed_definition,
        integration_plan=proposal.integration_plan,
        compilation=proposal.compilation,
        service_mappings=dict(proposal.service_mappings),
        operation_mappings=dict(proposal.operation_mappings),
        operation_version_mappings=dict(proposal.operation_version_mappings),
    )


@router.post(
    "/change-sets/{change_set_id}/review",
    response_model=FlowSpecChangeSetDetailResponse,
)
async def review_flow_spec_change_set(
    project_id: UUID,
    change_set_id: UUID,
    payload: FlowSpecReviewRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlowSpecChangeSetDetailResponse:
    view = await FlowSpecService(session).review(
        actor=current_user,
        project_id=project_id,
        change_set_id=change_set_id,
        accept=payload.accept,
        note=payload.note,
    )
    return _detail(view)


@router.post(
    "/change-sets/{change_set_id}/preview-approvals",
    response_model=SandboxPreviewApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sandbox_preview_approval(
    project_id: UUID,
    change_set_id: UUID,
    payload: SandboxPreviewApprovalCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SandboxPreviewApprovalResponse:
    approval = await SandboxPreviewService(session).create_approval(
        actor=current_user,
        project_id=project_id,
        change_set_id=change_set_id,
        payload=payload,
    )
    return SandboxPreviewApprovalResponse.model_validate(approval)


@router.post(
    "/change-sets/{change_set_id}/preview-executions",
    response_model=SandboxPreviewExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_sandbox_preview(
    project_id: UUID,
    change_set_id: UUID,
    payload: SandboxPreviewExecuteRequest,
    session: SessionDependency,
    current_user: CurrentUser,
    coordinator: WorkflowCoordinator,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SandboxPreviewExecutionResponse:
    async def start() -> SandboxPreviewExecutionResponse:
        execution, plan = await SandboxPreviewService(
            session,
            workflows=build_workflow_service(session),
        ).prepare_execution(
            actor=current_user,
            project_id=project_id,
            change_set_id=change_set_id,
            payload=payload,
            commit=False,
        )
        try:
            command = await DurableExecutionService(session).create_start_command(
                actor=current_user,
                project_id=project_id,
                execution_id=execution.id,
                actor_key=f"user:{current_user.id}",
                idempotency_key=idempotency_key,
                payload={
                    "change_set_id": str(change_set_id),
                    "execution_id": str(execution.id),
                    "run_purpose": "preview",
                },
            )
        except Exception:
            await session.rollback()
            raise
        response = SandboxPreviewExecutionResponse(
            execution=WorkflowExecutionResponse.model_validate(execution)
        )
        execution_id = execution.id
        command_id = command.id
        try:
            await coordinator.start(plan)
        except Exception:
            await session.rollback()
            await DurableExecutionService(session).mark_failed(
                command.id,
                error_code="PREVIEW_COMMAND_DISPATCH_FAILED",
                error_message="Sandbox Preview 启动命令未能提交到执行运行时",
            )
            raise
        try:
            await DurableExecutionService(session).mark_dispatched(command_id)
        except Exception:
            await session.rollback()
            logger.exception(
                "Sandbox Preview dispatch accepted but status persistence failed",
                extra={"execution_id": str(execution_id), "command_id": str(command_id)},
            )
        return response

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"user:{current_user.id}",
        operation=f"sandbox_preview.execute:{change_set_id}",
        request_payload=payload.model_dump(mode="json"),
        action=start,
    )
    return SandboxPreviewExecutionResponse.model_validate(response)


@router.post(
    "/change-sets/{change_set_id}/apply",
    response_model=FlowSpecApplyResponse,
)
async def apply_flow_spec_change_set(
    project_id: UUID,
    change_set_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlowSpecApplyResponse:
    view, workflow = await FlowSpecService(session).apply(
        actor=current_user,
        project_id=project_id,
        change_set_id=change_set_id,
    )
    if view.change_set.applied_at is None:
        raise RuntimeError("FlowSpec apply timestamp is missing")
    return FlowSpecApplyResponse(
        change_set_id=view.change_set.id,
        workflow_id=workflow.id,
        draft_revision=workflow.draft_revision,
        fingerprint=view.pipeline.fingerprint,
        applied_at=view.change_set.applied_at,
    )


def _summary(view: FlowSpecChangeSetView) -> FlowSpecChangeSetResponse:
    snapshot = cast(dict[str, object], view.change_set.source_snapshot)
    return FlowSpecChangeSetResponse(
        id=view.change_set.id,
        project_id=view.change_set.project_id,
        title=view.change_set.title,
        status=view.change_set.status,
        source_type="flow_spec",
        source_ref=view.change_set.source_ref,
        source_fingerprint=view.change_set.source_fingerprint,
        target_workflow_id=_uuid(snapshot.get("target_workflow_id")),
        target_revision=_int(snapshot.get("target_revision")),
        target_snapshot_sha256=view.item.target_snapshot_sha256,
        review_status=view.item.review_status,
        reviewed_by_id=view.item.reviewed_by_id,
        reviewed_at=view.item.reviewed_at,
        applied_at=view.change_set.applied_at,
        created_by_id=view.change_set.created_by_id,
        created_at=view.change_set.created_at,
        updated_at=view.change_set.updated_at,
    )


def _detail(view: FlowSpecChangeSetView) -> FlowSpecChangeSetDetailResponse:
    return FlowSpecChangeSetDetailResponse(
        **_summary(view).model_dump(),
        spec=view.pipeline.spec,
        validation=view.pipeline.validation,
        compatibility=view.pipeline.compatibility,
        diff=list(view.diff),
    )


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None
