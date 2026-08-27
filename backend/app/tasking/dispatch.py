from typing import Protocol
from uuid import UUID

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.observability.tracing import current_trace_headers
from app.services.runner_fabric import RunnerFabricService
from app.services.workflows import WorkflowExecutionPlan


class WorkflowDispatcher(Protocol):
    async def start(self, plan: WorkflowExecutionPlan) -> None: ...

    async def resume(self, plan: WorkflowExecutionPlan, *, retry: bool) -> None: ...


class TestPlanDispatcher(Protocol):
    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None: ...


class AIJobDispatcher(Protocol):
    def start_ai_job(self, job_id: UUID) -> None: ...


class PerformanceRunDispatcher(Protocol):
    def start_performance_run(self, run_id: UUID) -> None: ...


class EnvironmentTaskDispatcher(Protocol):
    def start_environment_provision(self, instance_id: UUID) -> None: ...

    def start_environment_cleanup(self, instance_id: UUID) -> None: ...


class CeleryTaskDispatcher:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    async def start(self, plan: WorkflowExecutionPlan) -> None:
        queue_name = _workflow_queue(plan)
        self._celery.send_task(
            "flowtest.run_workflow",
            args=[str(plan.execution_id)],
            queue=queue_name,
            priority=5,
            headers=current_trace_headers(),
        )

    async def resume(self, plan: WorkflowExecutionPlan, *, retry: bool) -> None:
        del retry
        await self.start(plan)

    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        self._celery.send_task(
            "flowtest.run_test_plan",
            args=[str(run_id)],
            queue=queue_name,
            priority=priority,
            headers=current_trace_headers(),
        )

    def start_ai_job(self, job_id: UUID) -> None:
        self._celery.send_task(
            "flowtest.run_ai_job",
            args=[str(job_id)],
            queue="ai",
            priority=5,
            headers=current_trace_headers(),
        )

    def start_performance_run(self, run_id: UUID) -> None:
        self._celery.send_task(
            "flowtest.run_performance",
            args=[str(run_id)],
            queue="performance",
            priority=5,
            headers=current_trace_headers(),
        )

    def start_environment_provision(self, instance_id: UUID) -> None:
        self._celery.send_task(
            "flowtest.provision_environment",
            args=[str(instance_id)],
            queue="environment",
            priority=5,
            headers=current_trace_headers(),
        )

    def start_environment_cleanup(self, instance_id: UUID) -> None:
        self._celery.send_task(
            "flowtest.cleanup_environment",
            args=[str(instance_id)],
            queue="environment",
            priority=9,
            headers=current_trace_headers(),
        )


class RunnerFabricDispatcher:
    def __init__(self, session: AsyncSession) -> None:
        self._service = RunnerFabricService(session, enabled=True)

    async def start(self, plan: WorkflowExecutionPlan) -> None:
        try:
            await self._service.enqueue(plan)
        except AppError:
            await self._service.fail_enqueue(plan.execution_id)
            raise

    async def resume(self, plan: WorkflowExecutionPlan, *, retry: bool) -> None:
        await self._service.resume(plan, retry=retry)


def _workflow_queue(plan: WorkflowExecutionPlan) -> str:
    definitions = (
        [child.definition for child in plan.children]
        if hasattr(plan, "children")
        else [plan.definition]
    )
    if any(
        node.type.value in {"sql", "redis"}
        for definition in definitions
        for node in definition.nodes
    ):
        return "data"
    return "general"
