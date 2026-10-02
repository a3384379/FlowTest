"""Start test cases through the existing durable workflow execution path."""

from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.composition import build_workflow_service
from app.core.errors import AppError
from app.models.access import User
from app.models.tasking import TestPlanRun, TestPlanRunItem
from app.models.workflows import WorkflowExecution, WorkflowVersion
from app.schemas.test_assets import TestCaseRunRequest, TestCaseRunResponse
from app.services.durable_execution import DurableExecutionService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.test_assets import TestCaseService
from app.services.test_case_targets import resolve_test_case_target
from app.services.workflows import WorkflowExecutionPlan


class ExecutionStarter(Protocol):
    async def start(self, plan: WorkflowExecutionPlan) -> None: ...


class TestCaseRunService:
    def __init__(self, session: AsyncSession, starter: ExecutionStarter) -> None:
        self._session = session
        self._starter = starter
        self._cases = TestCaseService(session)

    async def start(
        self,
        *,
        actor: User,
        project_id: UUID,
        case_id: UUID,
        request: TestCaseRunRequest,
        idempotency_key: str | None,
    ) -> TestCaseRunResponse:
        key = require_idempotency_key(idempotency_key)
        await self._cases.get(actor=actor, project_id=project_id, case_id=case_id)
        if request.source == "draft":
            if (
                not request.publish_draft
                or request.expected_draft_fingerprint is None
                or request.version is not None
            ):
                raise AppError(
                    code="INVALID_TEST_CASE_RUN",
                    message="发布草稿运行需要明确确认和草稿校验值",
                    status_code=422,
                )
        elif request.publish_draft:
            raise AppError(
                code="INVALID_TEST_CASE_RUN", message="已发布版本运行不能发布草稿", status_code=422
            )

        async def create() -> TestCaseRunResponse:
            if request.source == "draft":
                version, created = await self._cases.publish_for_run(
                    actor=actor,
                    project_id=project_id,
                    case_id=case_id,
                    expected_fingerprint=request.expected_draft_fingerprint or "",
                )
                case_version = version.version
            else:
                case = await self._cases.get(actor=actor, project_id=project_id, case_id=case_id)
                selected_version = request.version or case.current_version
                created = False
                if selected_version is None:
                    raise AppError(
                        code="TEST_CASE_NOT_PUBLISHED", message="用例尚未发布", status_code=409
                    )
                case_version = selected_version
            target = await resolve_test_case_target(
                self._session,
                project_id=project_id,
                case_id=case_id,
                case_version=case_version,
                runtime_variables=request.runtime_variables,
                runtime_headers=request.runtime_headers,
            )
            execution, plan = await build_workflow_service(self._session).prepare_execution(
                actor=actor,
                project_id=project_id,
                workflow_id=target.workflow_id,
                environment_id=target.environment_id,
                version=target.workflow_version,
                runtime_variables=target.runtime_variables,
                runtime_headers=target.runtime_headers,
                commit=False,
            )
            execution.source_case_id = target.case_id
            execution.source_case_version = target.case_version
            execution.source_trigger = "direct"
            command = await DurableExecutionService(self._session).create_start_command(
                actor=actor,
                project_id=project_id,
                execution_id=execution.id,
                actor_key=f"user:{actor.id}",
                idempotency_key=key,
                payload={
                    "case_id": str(case_id),
                    "case_version": case_version,
                    "execution_id": str(execution.id),
                },
            )
            try:
                await self._starter.start(plan)
                await DurableExecutionService(self._session).mark_dispatched(command.id)
            except Exception:
                await self._session.rollback()
                await DurableExecutionService(self._session).mark_failed(
                    command.id,
                    error_code="EXECUTION_COMMAND_DISPATCH_FAILED",
                    error_message="执行启动命令未能提交到执行运行时",
                )
                raise
            return TestCaseRunResponse(
                execution_id=execution.id,
                case_id=case_id,
                case_version=case_version,
                workflow_id=target.workflow_id,
                workflow_version=target.workflow_version,
                environment_id=target.environment_id,
                status=execution.status,
                source="direct",
                started_at=execution.started_at,
                created_new_version=created,
            )

        result = await IdempotencyService(self._session).run(
            key=key,
            project_id=project_id,
            actor_key=f"user:{actor.id}",
            operation=f"test_case.run:{case_id}",
            request_payload=request.model_dump(mode="json"),
            action=create,
        )
        return TestCaseRunResponse.model_validate(result)

    async def latest(
        self,
        *,
        actor: User,
        project_id: UUID,
        case_ids: list[UUID],
    ) -> list[TestCaseRunResponse]:
        from app.services.projects import ProjectService

        await ProjectService(self._session).authorize(
            actor=actor, project_id=project_id, editing=False
        )
        if not case_ids:
            return []
        ranked = (
            select(
                WorkflowExecution.id.label("execution_id"),
                func.row_number()
                .over(
                    partition_by=WorkflowExecution.source_case_id,
                    order_by=(WorkflowExecution.started_at.desc(), WorkflowExecution.id.desc()),
                )
                .label("rank"),
            )
            .where(
                WorkflowExecution.project_id == project_id,
                WorkflowExecution.source_case_id.in_(case_ids),
                WorkflowExecution.parent_execution_id.is_(None),
            )
            .subquery()
        )
        rows = await self._session.execute(
            select(WorkflowExecution, WorkflowVersion.version)
            .join(ranked, ranked.c.execution_id == WorkflowExecution.id)
            .join(WorkflowVersion, WorkflowVersion.id == WorkflowExecution.workflow_version_id)
            .where(ranked.c.rank == 1)
        )
        current = [
            TestCaseRunResponse(
                execution_id=execution.id,
                case_id=execution.source_case_id,
                case_version=execution.source_case_version,
                workflow_id=execution.workflow_id,
                workflow_version=workflow_version,
                environment_id=execution.environment_id,
                status=execution.status,
                source=execution.source_trigger,
                started_at=execution.started_at,
            )
            for execution, workflow_version in rows
        ]
        historical_ranked = (
            select(
                TestPlanRunItem.workflow_execution_id.label("execution_id"),
                TestPlanRunItem.target_id.label("case_id"),
                TestPlanRunItem.target_version.label("case_version"),
                func.row_number()
                .over(
                    partition_by=TestPlanRunItem.target_id,
                    order_by=(WorkflowExecution.started_at.desc(), WorkflowExecution.id.desc()),
                )
                .label("rank"),
            )
            .join(TestPlanRun, TestPlanRun.id == TestPlanRunItem.test_plan_run_id)
            .join(
                WorkflowExecution,
                WorkflowExecution.id == TestPlanRunItem.workflow_execution_id,
            )
            .where(
                TestPlanRun.project_id == project_id,
                WorkflowExecution.project_id == project_id,
                TestPlanRunItem.target_type == "case",
                TestPlanRunItem.target_id.in_(case_ids),
                WorkflowExecution.source_case_id.is_(None),
            )
            .subquery()
        )
        historical_rows = await self._session.execute(
            select(
                WorkflowExecution,
                WorkflowVersion.version,
                historical_ranked.c.case_id,
                historical_ranked.c.case_version,
            )
            .join(historical_ranked, historical_ranked.c.execution_id == WorkflowExecution.id)
            .join(WorkflowVersion, WorkflowVersion.id == WorkflowExecution.workflow_version_id)
            .where(historical_ranked.c.rank == 1)
        )
        for execution, workflow_version, case_id, case_version in historical_rows:
            current.append(
                TestCaseRunResponse(
                    execution_id=execution.id,
                    case_id=case_id,
                    case_version=case_version,
                    workflow_id=execution.workflow_id,
                    workflow_version=workflow_version,
                    environment_id=execution.environment_id,
                    status=execution.status,
                    source="plan",
                    started_at=execution.started_at,
                )
            )
        latest_by_case: dict[UUID, TestCaseRunResponse] = {}
        for run in current:
            previous = latest_by_case.get(run.case_id)
            if previous is None or (run.started_at, run.execution_id) > (
                previous.started_at,
                previous.execution_id,
            ):
                latest_by_case[run.case_id] = run
        return list(latest_by_case.values())
