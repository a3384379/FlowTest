from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query

from app.api.dependencies import CurrentUser, SessionDependency
from app.domain.assertions import AssertionSpec
from app.models.executions import APICallExecution, AssertionResult
from app.schemas.common import Page
from app.schemas.executions import (
    AssertionResultResponse,
    ExecuteAPIRequest,
    ExecutionDetailResponse,
    ExecutionResponse,
)
from app.services.executions import ExecutionService
from app.services.idempotency import IdempotencyService

router = APIRouter(prefix="/projects/{project_id}")


@router.post("/apis/{definition_id}/execute", response_model=ExecutionDetailResponse)
async def execute_api(
    project_id: UUID,
    definition_id: UUID,
    payload: ExecuteAPIRequest,
    session: SessionDependency,
    current_user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionDetailResponse:
    async def run() -> ExecutionDetailResponse:
        execution, assertions = await ExecutionService(session).execute(
            actor=current_user,
            project_id=project_id,
            definition_id=definition_id,
            environment_id=payload.environment_id,
            runtime_variables=payload.runtime_variables,
            runtime_headers=payload.runtime_headers,
            body_override=payload.body_override,
            use_body_override=payload.use_body_override,
            timeout_seconds=payload.timeout_seconds,
            assertions=tuple(
                AssertionSpec(
                    kind=assertion.kind,
                    operator=assertion.operator,
                    target=assertion.target,
                    expected=assertion.expected,
                )
                for assertion in payload.assertions
            ),
        )
        return _execution_detail(execution, assertions)

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"user:{current_user.id}",
        operation=f"api.execute:{definition_id}",
        request_payload=payload.model_dump(mode="json"),
        action=run,
    )
    return ExecutionDetailResponse.model_validate(response)


@router.get("/executions", response_model=Page[ExecutionResponse])
async def list_executions(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ExecutionResponse]:
    executions, total = await ExecutionService(session).list_executions(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[ExecutionResponse.model_validate(execution) for execution in executions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    project_id: UUID,
    execution_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ExecutionDetailResponse:
    execution, assertions = await ExecutionService(session).get_execution(
        actor=current_user,
        project_id=project_id,
        execution_id=execution_id,
    )
    return _execution_detail(execution, assertions)


def _execution_detail(
    execution: APICallExecution, assertions: list[AssertionResult]
) -> ExecutionDetailResponse:
    return ExecutionDetailResponse(
        execution=ExecutionResponse.model_validate(execution),
        assertions=[AssertionResultResponse.model_validate(assertion) for assertion in assertions],
    )
