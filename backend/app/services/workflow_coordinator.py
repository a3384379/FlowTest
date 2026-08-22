import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import redact
from app.engine.results import NodeResult
from app.engine.scheduler import NodeStatusUpdate
from app.models.workflows import WorkflowExecution
from app.services.execution_events import (
    ExecutionEvent,
    ExecutionEventBus,
    ExecutionEventType,
)
from app.services.workflows import (
    WorkflowBatchPlan,
    WorkflowExecutionPlan,
    WorkflowRunPlan,
    WorkflowService,
)

logger = logging.getLogger(__name__)


class WorkflowRunCoordinator:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        events: ExecutionEventBus,
    ) -> None:
        self._session_maker = session_maker
        self._events = events
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    async def start(self, plan: WorkflowExecutionPlan) -> None:
        task = asyncio.create_task(self._run(plan), name=f"workflow-{plan.execution_id}")
        self._tasks[plan.execution_id] = task
        task.add_done_callback(lambda _completed: self._tasks.pop(plan.execution_id, None))

    async def run_now(self, plan: WorkflowExecutionPlan) -> None:
        """Run a persisted plan in the current worker event loop."""
        await self._run(plan)

    async def wait_for(self, execution_id: UUID) -> None:
        task = self._tasks.get(execution_id)
        if task is not None:
            await asyncio.shield(task)

    async def shutdown(self) -> None:
        if not self._tasks:
            return
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self, plan: WorkflowExecutionPlan) -> None:
        await self._publish(
            ExecutionEvent(
                type=ExecutionEventType.EXECUTION_STARTED,
                execution_id=plan.execution_id,
                emitted_at=datetime.now(UTC),
                execution_status="running",
            )
        )
        try:
            execution = (
                await self._execute_batch(plan)
                if isinstance(plan, WorkflowBatchPlan)
                else await self._execute(plan)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Background workflow execution failed",
                extra={"execution_id": str(plan.execution_id)},
            )
            execution = await self._mark_failed(plan)
        await self._publish(
            ExecutionEvent(
                type=ExecutionEventType.EXECUTION_COMPLETED,
                execution_id=plan.execution_id,
                emitted_at=datetime.now(UTC),
                execution_status=execution.status,
                error_code=execution.error_code,
                error_message=execution.error_message,
            )
        )

    async def _execute_batch(self, plan: WorkflowBatchPlan) -> WorkflowExecution:
        semaphore = asyncio.Semaphore(plan.concurrency)

        async def execute_child(child: WorkflowRunPlan) -> None:
            async with semaphore:
                await self._publish(
                    ExecutionEvent(
                        type=ExecutionEventType.EXECUTION_STARTED,
                        execution_id=child.execution_id,
                        emitted_at=datetime.now(UTC),
                        execution_status="running",
                    )
                )
                try:
                    execution = await self._execute(child)
                except Exception:
                    logger.exception(
                        "Dataset child execution failed",
                        extra={"execution_id": str(child.execution_id)},
                    )
                    execution = await self._mark_failed(child)
                await self._publish_completion(execution)

        tasks = [asyncio.create_task(execute_child(child)) for child in plan.children]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            await asyncio.gather(*tasks, return_exceptions=True)
            async with self._session_maker() as session:
                await WorkflowService(session).cancel_incomplete_batch(plan.execution_id)
        async with self._session_maker() as session:
            return await WorkflowService(session).complete_batch(plan.execution_id)

    async def _execute(self, plan: WorkflowRunPlan) -> WorkflowExecution:
        async with self._session_maker() as session:
            service = WorkflowService(session)
            execution = await service.load_execution_for_run(plan.execution_id)

            async def publish_status(update: NodeStatusUpdate) -> None:
                safe_result = (
                    NodeResult.model_validate(redact(update.result.model_dump(mode="json")))
                    if update.result is not None
                    else None
                )
                await self._publish(
                    ExecutionEvent(
                        type=(
                            ExecutionEventType.NODE_RESULT
                            if update.result is not None
                            else ExecutionEventType.NODE_STATUS
                        ),
                        execution_id=plan.execution_id,
                        emitted_at=update.occurred_at,
                        node_id=update.node_id,
                        node_name=update.name,
                        node_type=update.node_type.value,
                        node_status=update.status,
                        result=safe_result,
                        attempt=update.attempts,
                        attempts=update.attempts,
                        fencing_token=0,
                        error_code=update.error_code,
                        error_message=update.error_message,
                    )
                )

            completed, _nodes = await service.run_prepared(
                execution=execution,
                plan=plan,
                on_node_status=publish_status,
            )
            return completed

    async def _mark_failed(self, plan: WorkflowExecutionPlan) -> WorkflowExecution:
        async with self._session_maker() as session:
            return await WorkflowService(session).mark_runtime_failed(plan.execution_id)

    async def _publish_completion(self, execution: WorkflowExecution) -> None:
        await self._publish(
            ExecutionEvent(
                type=ExecutionEventType.EXECUTION_COMPLETED,
                execution_id=execution.id,
                emitted_at=datetime.now(UTC),
                execution_status=execution.status,
                error_code=execution.error_code,
                error_message=execution.error_message,
            )
        )

    async def _publish(self, event: ExecutionEvent) -> None:
        try:
            await self._events.publish(event)
        except RedisError:
            logger.warning(
                "Workflow event publication failed",
                extra={"execution_id": str(event.execution_id), "event_type": event.type.value},
                exc_info=True,
            )
