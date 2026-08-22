"""In-process task runtime for the Standalone deployment profile."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.errors import AppError
from app.core.storage import ObjectStorage
from app.http.ai import OpenAICompatibleConfiguration, OpenAICompatibleProvider
from app.observability.task_metrics import InProcessTaskMetricsReader
from app.services.ai import AIJobRunner
from app.services.execution_events import ExecutionEventBus
from app.services.notifications import NotificationDeliveryService
from app.services.retention import RetentionCleanupService
from app.services.tasking import TestPlanService
from app.services.test_plan_runner import TestPlanRunCoordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator
from app.services.workflows import WorkflowExecutionPlan
from app.tasking.dispatch import (
    AIJobDispatcher,
    EnvironmentTaskDispatcher,
    PerformanceRunDispatcher,
    TestPlanDispatcher,
    WorkflowDispatcher,
)

logger = logging.getLogger(__name__)
Operation = Callable[[], Awaitable[None]]


class StandaloneTaskDispatcher(
    WorkflowDispatcher,
    TestPlanDispatcher,
    AIJobDispatcher,
    PerformanceRunDispatcher,
    EnvironmentTaskDispatcher,
):
    """Run supported background work inside the API event loop."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        events: ExecutionEventBus,
        storage: ObjectStorage,
    ) -> None:
        self._session_factory = session_factory
        self._events = events
        self._storage = storage
        self._workflow = WorkflowRunCoordinator(session_factory, events)
        self._tasks: set[asyncio.Task[None]] = set()
        self._slot = asyncio.Semaphore(settings.standalone_task_concurrency)
        self._closed = False
        self._scheduler_task: asyncio.Task[None] | None = None
        self.metrics_reader = InProcessTaskMetricsReader()

    def start_scheduler(self) -> None:
        if settings.standalone_scheduler_enabled and self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(
                self._scheduler_loop(), name="standalone-scheduler"
            )

    async def start(self, plan: WorkflowExecutionPlan) -> None:
        self._spawn(
            "workflow",
            lambda: self._run_workflow(plan),
        )

    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        del queue_name, priority
        self._spawn("test-plan", lambda: self._run_test_plan(run_id))

    def start_ai_job(self, job_id: UUID) -> None:
        self._spawn("ai", lambda: self._run_ai_job(job_id))

    def start_performance_run(self, run_id: UUID) -> None:
        del run_id
        raise AppError(
            code="PERFORMANCE_QUEUE_UNAVAILABLE",
            message="Standalone 运行档位不支持性能任务",
            status_code=503,
        )

    def start_environment_provision(self, instance_id: UUID) -> None:
        del instance_id
        raise AppError(
            code="ENVIRONMENT_QUEUE_UNAVAILABLE",
            message="Standalone 运行档位不支持环境任务",
            status_code=503,
        )

    def start_environment_cleanup(self, instance_id: UUID) -> None:
        del instance_id
        raise AppError(
            code="ENVIRONMENT_QUEUE_UNAVAILABLE",
            message="Standalone 运行档位不支持环境任务",
            status_code=503,
        )

    async def shutdown(self) -> None:
        self._closed = True
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            await asyncio.gather(self._scheduler_task, return_exceptions=True)
            self._scheduler_task = None
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self.metrics_reader.set_active_workers(0)

    def _spawn(self, name: str, operation: Operation) -> None:
        if self._closed:
            raise AppError(
                code="TASK_QUEUE_UNAVAILABLE",
                message="Standalone 后台任务运行时已关闭",
                status_code=503,
            )
        task = asyncio.create_task(self._run_with_slot(operation), name=f"standalone-{name}")
        self._tasks.add(task)
        self.metrics_reader.set_active_workers(len(self._tasks))
        task.add_done_callback(self._task_done)

    async def _run_with_slot(self, operation: Operation) -> None:
        async with self._slot:
            await operation()

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        self.metrics_reader.set_active_workers(len(self._tasks))
        if task.cancelled():
            return
        error = task.exception()
        self.metrics_reader.record_task("failed" if error is not None else "succeeded")
        if error is not None:
            logger.error("Standalone background task failed: %s", type(error).__name__)

    async def _run_workflow(self, plan: WorkflowExecutionPlan) -> None:
        await self._workflow.run_now(plan)
        await self._deliver_workflow_notification(plan.execution_id)

    async def _run_test_plan(self, run_id: UUID) -> None:
        await TestPlanRunCoordinator(self._session_factory, self._events).run(run_id)
        await self._deliver_test_plan_notification(run_id)

    async def _run_ai_job(self, job_id: UUID) -> None:
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfiguration(
                base_url=settings.ai_base_url,
                model=settings.ai_model,
                api_key=settings.ai_api_key,
                timeout_seconds=settings.ai_request_timeout_seconds,
            )
        )
        async with self._session_factory() as session:
            await AIJobRunner(session, provider).run(job_id)

    async def _scheduler_loop(self) -> None:
        last_retention = asyncio.get_running_loop().time()
        while True:
            await asyncio.sleep(settings.scheduler_poll_seconds)
            try:
                await self._enqueue_due_test_plans()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Standalone scheduler poll failed: %s", type(error).__name__)
            now = asyncio.get_running_loop().time()
            if now - last_retention >= settings.retention_cleanup_interval_seconds:
                try:
                    await self._cleanup_retention()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning("Standalone retention cleanup failed: %s", type(error).__name__)
                last_retention = now

    async def _enqueue_due_test_plans(self) -> None:
        async with self._session_factory() as session:
            runs = await TestPlanService(session).queue_due_runs(datetime.now(UTC))
        for run in runs:
            self.start_test_plan(run.id, queue_name=run.queue_name, priority=run.queue_priority)

    async def _cleanup_retention(self) -> None:
        async with self._session_factory() as session:
            summary = await RetentionCleanupService(session, self._storage).cleanup()
        logger.info("Standalone retention cleanup completed: %s", summary)

    async def _deliver_workflow_notification(self, execution_id: UUID) -> None:
        try:
            async with self._session_factory() as session:
                await NotificationDeliveryService(session).deliver_workflow(execution_id)
        except Exception as error:
            logger.warning(
                "Standalone workflow notification failed: %s",
                type(error).__name__,
                extra={"execution_id": str(execution_id)},
            )

    async def _deliver_test_plan_notification(self, run_id: UUID) -> None:
        try:
            async with self._session_factory() as session:
                await NotificationDeliveryService(session).deliver_test_plan(run_id)
        except Exception as error:
            logger.warning(
                "Standalone test plan notification failed: %s",
                type(error).__name__,
                extra={"test_plan_run_id": str(run_id)},
            )
