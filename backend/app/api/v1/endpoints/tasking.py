from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from app.api.dependencies import CurrentUser, SessionDependency, TestPlanQueue, WorkflowCoordinator
from app.core.errors import AppError
from app.domain.tasking import ServiceTokenScope, TestPlanTrigger
from app.models.tasking import TestPlanItem
from app.schemas.common import Page
from app.schemas.tasking import (
    ServiceTokenCreate,
    ServiceTokenCreatedResponse,
    ServiceTokenResponse,
    TestPlanCreate,
    TestPlanCreatedResponse,
    TestPlanItemResponse,
    TestPlanResponse,
    TestPlanRunDetailResponse,
    TestPlanRunItemResponse,
    TestPlanRunResponse,
    TestPlanUpdate,
)
from app.schemas.workflows import WorkflowExecuteRequest, WorkflowExecutionResponse
from app.services.idempotency import IdempotencyService
from app.services.tasking import ServiceTokenService, TestPlanDetail, TestPlanService
from app.services.workflows import WorkflowService

router = APIRouter()


@router.get("/projects/{project_id}/test-plans", response_model=Page[TestPlanResponse])
async def list_test_plans(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[TestPlanResponse]:
    items, total = await TestPlanService(session).list_plans(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[_plan_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/test-plans",
    response_model=TestPlanCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_plan(
    project_id: UUID,
    payload: TestPlanCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestPlanCreatedResponse:
    created = await TestPlanService(session).create(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        enabled=payload.enabled,
        schedule_interval_seconds=payload.schedule_interval_seconds,
        items=payload.items,
    )
    response = _plan_response(created.detail).model_dump()
    return TestPlanCreatedResponse(**response, webhook_secret=created.webhook_secret)


@router.get("/projects/{project_id}/test-plans/{plan_id}", response_model=TestPlanResponse)
async def get_test_plan(
    project_id: UUID,
    plan_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestPlanResponse:
    detail = await TestPlanService(session).get(
        actor=current_user, project_id=project_id, plan_id=plan_id
    )
    return _plan_response(detail)


@router.patch("/projects/{project_id}/test-plans/{plan_id}", response_model=TestPlanResponse)
async def update_test_plan(
    project_id: UUID,
    plan_id: UUID,
    payload: TestPlanUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestPlanResponse:
    detail = await TestPlanService(session).update(
        actor=current_user,
        project_id=project_id,
        plan_id=plan_id,
        name=payload.name,
        description=payload.description,
        enabled=payload.enabled,
        schedule_interval_seconds=payload.schedule_interval_seconds,
        change_schedule="schedule_interval_seconds" in payload.model_fields_set,
    )
    return _plan_response(detail)


@router.post(
    "/projects/{project_id}/test-plans/{plan_id}/runs",
    response_model=TestPlanRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_test_plan(
    project_id: UUID,
    plan_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    queue: TestPlanQueue,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TestPlanRunResponse:
    async def start() -> TestPlanRunResponse:
        run = await TestPlanService(session).queue_run(
            actor=current_user,
            project_id=project_id,
            plan_id=plan_id,
            trigger=TestPlanTrigger.MANUAL,
        )
        queue.start_test_plan(run.id)
        return TestPlanRunResponse.model_validate(run)

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"user:{current_user.id}",
        operation=f"test-plan.run:{plan_id}",
        request_payload={},
        action=start,
    )
    return TestPlanRunResponse.model_validate(response)


@router.get("/projects/{project_id}/test-plan-runs", response_model=Page[TestPlanRunResponse])
async def list_test_plan_runs(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[TestPlanRunResponse]:
    items, total = await TestPlanService(session).list_runs(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[TestPlanRunResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/projects/{project_id}/test-plan-runs/{run_id}",
    response_model=TestPlanRunDetailResponse,
)
async def get_test_plan_run(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestPlanRunDetailResponse:
    detail = await TestPlanService(session).get_run(
        actor=current_user, project_id=project_id, run_id=run_id
    )
    return TestPlanRunDetailResponse(
        run=TestPlanRunResponse.model_validate(detail.run),
        items=[TestPlanRunItemResponse.model_validate(item) for item in detail.items],
    )


@router.post(
    "/projects/{project_id}/test-plan-runs/{run_id}/cancel",
    response_model=TestPlanRunResponse,
)
async def cancel_test_plan_run(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestPlanRunResponse:
    run = await TestPlanService(session).cancel_run(
        actor=current_user, project_id=project_id, run_id=run_id
    )
    return TestPlanRunResponse.model_validate(run)


@router.post(
    "/projects/{project_id}/service-tokens",
    response_model=ServiceTokenCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_token(
    project_id: UUID,
    payload: ServiceTokenCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceTokenCreatedResponse:
    created = await ServiceTokenService(session).create(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    response = ServiceTokenResponse.model_validate(created.model).model_dump()
    return ServiceTokenCreatedResponse(**response, token=created.token)


@router.get("/projects/{project_id}/service-tokens", response_model=list[ServiceTokenResponse])
async def list_service_tokens(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[ServiceTokenResponse]:
    items = await ServiceTokenService(session).list_tokens(
        actor=current_user, project_id=project_id
    )
    return [ServiceTokenResponse.model_validate(item) for item in items]


@router.delete(
    "/projects/{project_id}/service-tokens/{token_id}",
    response_model=ServiceTokenResponse,
)
async def revoke_service_token(
    project_id: UUID,
    token_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ServiceTokenResponse:
    token = await ServiceTokenService(session).revoke(
        actor=current_user, project_id=project_id, token_id=token_id
    )
    return ServiceTokenResponse.model_validate(token)


@router.post(
    "/ci/projects/{project_id}/test-plans/{plan_id}/runs",
    response_model=TestPlanRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ci_run_test_plan(
    project_id: UUID,
    plan_id: UUID,
    session: SessionDependency,
    queue: TestPlanQueue,
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TestPlanRunResponse:
    identity = await ServiceTokenService(session).authenticate(
        raw_token=_bearer_token(authorization),
        project_id=project_id,
        required_scope=ServiceTokenScope.EXECUTE_TEST_PLAN,
    )

    async def start() -> TestPlanRunResponse:
        plan = await TestPlanService(session).get(
            actor=identity.actor, project_id=project_id, plan_id=plan_id
        )
        run = await TestPlanService(session).queue_external_run(
            plan=plan.plan,
            requested_by_id=identity.actor.id,
            trigger=TestPlanTrigger.CI,
        )
        queue.start_test_plan(run.id)
        return TestPlanRunResponse.model_validate(run)

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"service-token:{identity.model.id}",
        operation=f"ci.test-plan.run:{plan_id}",
        request_payload={},
        action=start,
    )
    return TestPlanRunResponse.model_validate(response)


@router.post(
    "/ci/projects/{project_id}/workflows/{workflow_id}/executions",
    response_model=WorkflowExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ci_run_workflow(
    project_id: UUID,
    workflow_id: UUID,
    payload: WorkflowExecuteRequest,
    session: SessionDependency,
    coordinator: WorkflowCoordinator,
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> WorkflowExecutionResponse:
    identity = await ServiceTokenService(session).authenticate(
        raw_token=_bearer_token(authorization),
        project_id=project_id,
        required_scope=ServiceTokenScope.EXECUTE_WORKFLOW,
    )

    async def start() -> WorkflowExecutionResponse:
        execution, plan = await WorkflowService(session).prepare_execution(
            actor=identity.actor,
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
        actor_key=f"service-token:{identity.model.id}",
        operation=f"ci.workflow.execute:{workflow_id}",
        request_payload=payload.model_dump(mode="json"),
        action=start,
    )
    return WorkflowExecutionResponse.model_validate(response)


@router.post(
    "/webhooks/test-plans/{plan_id}",
    response_model=TestPlanRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def webhook_run_test_plan(
    plan_id: UUID,
    request: Request,
    session: SessionDependency,
    queue: TestPlanQueue,
    x_flowtest_timestamp: Annotated[str | None, Header()] = None,
    x_flowtest_signature: Annotated[str | None, Header()] = None,
) -> TestPlanRunResponse:
    body = await request.body()
    service = TestPlanService(session)
    plan = await service.authenticate_webhook(
        plan_id=plan_id,
        timestamp=x_flowtest_timestamp or "",
        signature=x_flowtest_signature or "",
        body=body,
    )
    run = await service.queue_external_run(
        plan=plan,
        requested_by_id=plan.created_by_id,
        trigger=TestPlanTrigger.WEBHOOK,
    )
    queue.start_test_plan(run.id)
    return TestPlanRunResponse.model_validate(run)


def _plan_response(detail: TestPlanDetail) -> TestPlanResponse:
    plan = detail.plan
    return TestPlanResponse(
        id=plan.id,
        project_id=plan.project_id,
        name=plan.name,
        description=plan.description,
        enabled=plan.enabled,
        schedule_interval_seconds=plan.schedule_interval_seconds,
        next_run_at=plan.next_run_at,
        created_by_id=plan.created_by_id,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        items=[_plan_item(item) for item in detail.items],
    )


def _plan_item(item: TestPlanItem) -> TestPlanItemResponse:
    return TestPlanItemResponse.model_validate(item)


def _bearer_token(value: str | None) -> str:
    if value is None:
        raise AppError(
            code="INVALID_SERVICE_TOKEN", message="CI Token 无效或权限不足", status_code=401
        )
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(
            code="INVALID_SERVICE_TOKEN", message="CI Token 无效或权限不足", status_code=401
        )
    return token
