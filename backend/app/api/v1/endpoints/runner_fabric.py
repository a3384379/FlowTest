from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.config import settings
from app.core.errors import AppError
from app.runner.results import RUNNER_EXECUTION_RESULT_ADAPTER
from app.schemas.common import Page
from app.schemas.runner_fabric import (
    RunnerActionRequest,
    RunnerCompleteRequest,
    RunnerEventResponse,
    RunnerFabricOverviewResponse,
    RunnerFailRequest,
    RunnerHeartbeatRequest,
    RunnerLeaseAckResponse,
    RunnerLeaseAdminResponse,
    RunnerLeaseResponse,
    RunnerPoolCreate,
    RunnerPoolResponse,
    RunnerPoolUpdate,
    RunnerProgressRequest,
    RunnerRegisterRequest,
    RunnerRegisterResponse,
    RunnerRegistrationTokenCreate,
    RunnerRegistrationTokenResponse,
    RunnerRenewRequest,
    RunnerResponse,
    RunnerTaskResponse,
)
from app.services.runner_fabric import RunnerFabricService

admin_router = APIRouter(prefix="/execution-fabric")
runner_router = APIRouter(prefix="/runner-control")


@admin_router.get("/overview", response_model=RunnerFabricOverviewResponse)
async def get_runner_fabric_overview(
    session: SessionDependency, current_user: CurrentUser
) -> RunnerFabricOverviewResponse:
    counts = await _service(session).overview(actor=current_user)
    return RunnerFabricOverviewResponse(**counts)


@admin_router.get("/pools", response_model=Page[RunnerPoolResponse])
async def list_runner_fabric_pools(
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[RunnerPoolResponse]:
    views = await _service(session).list_pools(actor=current_user)
    start = (page - 1) * page_size
    return Page(
        items=[_pool_response(pool, runners) for pool, runners in views[start : start + page_size]],
        total=len(views),
        page=page,
        page_size=page_size,
    )


@admin_router.post("/pools", response_model=RunnerPoolResponse, status_code=status.HTTP_201_CREATED)
async def create_runner_fabric_pool(
    payload: RunnerPoolCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> RunnerPoolResponse:
    pool = await _service(session).create_pool(actor=current_user, payload=payload)
    return _pool_response(pool, [])


@admin_router.patch("/pools/{pool_id}", response_model=RunnerPoolResponse)
async def update_runner_fabric_pool(
    pool_id: UUID,
    payload: RunnerPoolUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> RunnerPoolResponse:
    service = _service(session)
    pool = await service.update_pool(actor=current_user, pool_id=pool_id, payload=payload)
    views = await service.list_pools(actor=current_user)
    runners = next(items for item, items in views if item.id == pool.id)
    return _pool_response(pool, runners)


@admin_router.post(
    "/pools/{pool_id}/registration-tokens",
    response_model=RunnerRegistrationTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_runner_registration_token(
    pool_id: UUID,
    payload: RunnerRegistrationTokenCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> RunnerRegistrationTokenResponse:
    model, raw_token = await _service(session).create_registration_token(
        actor=current_user,
        pool_id=pool_id,
        expires_in_seconds=payload.expires_in_seconds,
    )
    return RunnerRegistrationTokenResponse(
        id=model.id,
        pool_id=model.pool_id,
        token=raw_token,
        expires_at=model.expires_at,
    )


@admin_router.post("/runners/{runner_id}/actions", response_model=RunnerResponse)
async def change_runner_state(
    runner_id: UUID,
    payload: RunnerActionRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> RunnerResponse:
    runner = await _service(session).runner_action(
        actor=current_user, runner_id=runner_id, action=payload.action
    )
    return RunnerResponse.model_validate(runner)


@admin_router.get("/tasks", response_model=Page[RunnerTaskResponse])
async def list_runner_tasks(
    session: SessionDependency,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=100),
) -> Page[RunnerTaskResponse]:
    items = await _service(session).list_tasks(actor=current_user, limit=limit)
    return Page(
        items=[RunnerTaskResponse.model_validate(item) for item in items],
        total=len(items),
        page=1,
        page_size=limit,
    )


@admin_router.get("/leases", response_model=Page[RunnerLeaseAdminResponse])
async def list_runner_leases(
    session: SessionDependency,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=100),
) -> Page[RunnerLeaseAdminResponse]:
    items = await _service(session).list_leases(actor=current_user, limit=limit)
    return Page(
        items=[RunnerLeaseAdminResponse.model_validate(item) for item in items],
        total=len(items),
        page=1,
        page_size=limit,
    )


@admin_router.get("/events", response_model=Page[RunnerEventResponse])
async def list_runner_events(
    session: SessionDependency,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=100),
) -> Page[RunnerEventResponse]:
    items = await _service(session).list_events(actor=current_user, limit=limit)
    return Page(
        items=[RunnerEventResponse.model_validate(item) for item in items],
        total=len(items),
        page=1,
        page_size=limit,
    )


@runner_router.post(
    "/register", response_model=RunnerRegisterResponse, status_code=status.HTTP_201_CREATED
)
async def register_runner(
    payload: RunnerRegisterRequest,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerRegisterResponse:
    return await _service(session).register(
        registration_token=_bearer_token(authorization), payload=payload
    )


@runner_router.post("/heartbeat", response_model=RunnerResponse)
async def runner_heartbeat(
    payload: RunnerHeartbeatRequest,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerResponse:
    runner = await _service(session).heartbeat(
        runner_token=_bearer_token(authorization), payload=payload
    )
    return RunnerResponse.model_validate(runner)


@runner_router.post("/leases/claim", response_model=RunnerLeaseResponse | None)
async def claim_runner_lease(
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerLeaseResponse | None:
    return await _service(session).claim(runner_token=_bearer_token(authorization))


@runner_router.post("/leases/{lease_id}/renew", response_model=RunnerLeaseAckResponse)
async def renew_runner_lease(
    lease_id: UUID,
    payload: RunnerRenewRequest,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerLeaseAckResponse:
    return await _service(session).renew(
        runner_token=_bearer_token(authorization),
        lease_id=lease_id,
        fencing_token=payload.fencing_token,
    )


@runner_router.post("/leases/{lease_id}/progress", response_model=RunnerLeaseAckResponse)
async def report_runner_progress(
    lease_id: UUID,
    payload: RunnerProgressRequest,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerLeaseAckResponse:
    return await _service(session).progress(
        runner_token=_bearer_token(authorization), lease_id=lease_id, payload=payload
    )


@runner_router.post("/leases/{lease_id}/complete", response_model=RunnerLeaseAckResponse)
async def complete_runner_lease(
    lease_id: UUID,
    payload: RunnerCompleteRequest,
    request: Request,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerLeaseAckResponse:
    _validate_result_size(request, payload)
    return await _service(session).complete(
        runner_token=_bearer_token(authorization),
        lease_id=lease_id,
        fencing_token=payload.fencing_token,
        result=payload.result,
    )


@runner_router.post("/leases/{lease_id}/fail", response_model=RunnerLeaseAckResponse)
async def fail_runner_lease(
    lease_id: UUID,
    payload: RunnerFailRequest,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerLeaseAckResponse:
    return await _service(session).fail(
        runner_token=_bearer_token(authorization), lease_id=lease_id, payload=payload
    )


def _pool_response(pool: object, runners: Sequence[object]) -> RunnerPoolResponse:
    response = RunnerPoolResponse.model_validate(pool)
    return response.model_copy(
        update={"runners": [RunnerResponse.model_validate(runner) for runner in runners]}
    )


def _service(session: AsyncSession) -> RunnerFabricService:
    return RunnerFabricService(session, enabled=settings.feature_runner_fabric_enabled)


def _bearer_token(value: str | None) -> str:
    if value is None:
        raise AppError(
            code="RUNNER_AUTHENTICATION_FAILED",
            message="Runner 身份令牌无效",
            status_code=401,
        )
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(
            code="RUNNER_AUTHENTICATION_FAILED",
            message="Runner 身份令牌无效",
            status_code=401,
        )
    return token


def _validate_result_size(request: Request, payload: RunnerCompleteRequest) -> None:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise AppError(
                code="RUNNER_CONTENT_LENGTH_INVALID",
                message="Runner 请求长度无效",
                status_code=400,
            ) from error
        if declared_size > settings.runner_result_limit_bytes:
            raise _result_too_large()
    encoded = RUNNER_EXECUTION_RESULT_ADAPTER.dump_json(payload.result)
    if len(encoded) > settings.runner_result_limit_bytes:
        raise _result_too_large()


def _result_too_large() -> AppError:
    return AppError(
        code="RUNNER_RESULT_TOO_LARGE",
        message="Runner 结果超过允许大小",
        status_code=413,
        details={"limit_bytes": settings.runner_result_limit_bytes},
    )
