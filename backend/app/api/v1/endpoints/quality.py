from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import AppError
from app.domain.tasking import ServiceTokenScope
from app.schemas.common import Page
from app.schemas.quality import (
    FlakyQuarantineUpdate,
    FlakyRecordResponse,
    QualityGateEvaluationResponse,
    QualityGateResponse,
    QualityGateWrite,
    RunQualityResponse,
)
from app.services.quality import QualityService
from app.services.tasking import ServiceTokenService

router = APIRouter()


@router.get("/projects/{project_id}/quality-gates", response_model=list[QualityGateResponse])
async def list_quality_gates(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[QualityGateResponse]:
    gates = await QualityService(session).list_gates(actor=current_user, project_id=project_id)
    return [QualityGateResponse.model_validate(gate) for gate in gates]


@router.post(
    "/projects/{project_id}/quality-gates",
    response_model=QualityGateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_quality_gate(
    project_id: UUID,
    payload: QualityGateWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> QualityGateResponse:
    gate = await QualityService(session).create_gate(
        actor=current_user, project_id=project_id, payload=payload
    )
    return QualityGateResponse.model_validate(gate)


@router.put("/projects/{project_id}/quality-gates/{gate_id}", response_model=QualityGateResponse)
async def update_quality_gate(
    project_id: UUID,
    gate_id: UUID,
    payload: QualityGateWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> QualityGateResponse:
    gate = await QualityService(session).update_gate(
        actor=current_user,
        project_id=project_id,
        gate_id=gate_id,
        payload=payload,
    )
    return QualityGateResponse.model_validate(gate)


@router.delete(
    "/projects/{project_id}/quality-gates/{gate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_quality_gate(
    project_id: UUID,
    gate_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> Response:
    await QualityService(session).delete_gate(
        actor=current_user, project_id=project_id, gate_id=gate_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/flaky-tests", response_model=Page[FlakyRecordResponse])
async def list_flaky_tests(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[FlakyRecordResponse]:
    items, total = await QualityService(session).list_flaky_records(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[FlakyRecordResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.put(
    "/projects/{project_id}/flaky-tests/{record_id}/quarantine",
    response_model=FlakyRecordResponse,
)
async def update_flaky_quarantine(
    project_id: UUID,
    record_id: UUID,
    payload: FlakyQuarantineUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> FlakyRecordResponse:
    record = await QualityService(session).set_quarantine(
        actor=current_user,
        project_id=project_id,
        record_id=record_id,
        quarantined=payload.quarantined,
    )
    return FlakyRecordResponse.model_validate(record)


@router.get(
    "/projects/{project_id}/test-plan-runs/{run_id}/quality",
    response_model=RunQualityResponse,
)
async def get_run_quality(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> RunQualityResponse:
    return await QualityService(session).get_run_quality(
        actor=current_user, project_id=project_id, run_id=run_id
    )


@router.get("/projects/{project_id}/test-plan-runs/{run_id}/junit.xml")
async def download_run_junit(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> Response:
    content = await QualityService(session).render_junit(
        actor=current_user, project_id=project_id, run_id=run_id
    )
    return _junit_response(content, run_id)


@router.get(
    "/ci/projects/{project_id}/test-plan-runs/{run_id}/quality-gate",
    response_model=QualityGateEvaluationResponse,
)
async def evaluate_ci_quality_gate(
    project_id: UUID,
    run_id: UUID,
    quality_gate_id: UUID,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> QualityGateEvaluationResponse:
    await ServiceTokenService(session).authenticate(
        raw_token=_bearer_token(authorization),
        project_id=project_id,
        required_scope=ServiceTokenScope.EXECUTE_TEST_PLAN,
    )
    evaluation = await QualityService(session).evaluate_ci_gate(
        project_id=project_id, run_id=run_id, gate_id=quality_gate_id
    )
    return QualityGateEvaluationResponse.model_validate(evaluation)


@router.get("/ci/projects/{project_id}/test-plan-runs/{run_id}/junit.xml")
async def download_ci_junit(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    await ServiceTokenService(session).authenticate(
        raw_token=_bearer_token(authorization),
        project_id=project_id,
        required_scope=ServiceTokenScope.EXECUTE_TEST_PLAN,
    )
    content = await QualityService(session).render_ci_junit(project_id=project_id, run_id=run_id)
    return _junit_response(content, run_id)


def _junit_response(content: bytes, run_id: UUID) -> Response:
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="flowtest-{run_id}.xml"'},
    )


def _bearer_token(value: str | None) -> str:
    if value is None:
        raise _invalid_token()
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _invalid_token()
    return token


def _invalid_token() -> AppError:
    return AppError(
        code="INVALID_SERVICE_TOKEN", message="CI Token 无效或权限不足", status_code=401
    )
