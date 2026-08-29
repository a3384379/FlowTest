import asyncio
import logging
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import redact
from app.domain.durable_execution import checkpoint_input_hash
from app.engine.contracts import NodeStatus
from app.engine.results import NodeResult
from app.engine.scheduler import NodeStatusUpdate
from app.models.workflows import WorkflowExecution
from app.schemas.runner_fabric import RunnerCheckpointRequest
from app.services.durable_execution import DurableExecutionService
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

    async def resume(self, plan: WorkflowExecutionPlan, *, retry: bool) -> None:
        del retry
        await self.start(plan)

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
        async with self._session_maker() as session:
            await DurableExecutionService(session).mark_execution_command_completed(
                plan.execution_id,
                execution_status=execution.status,
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
                should_checkpoint = (
                    safe_result is not None and update.status.is_terminal and update.attempts > 0
                ) or (
                    update.status is NodeStatus.RUNNING
                    and update.attempts > 0
                    and update.request_reserved
                )
                if should_checkpoint:
                    snapshot = update.context_snapshot or {}
                    extracted = snapshot.get("extracted_variables", {})
                    if not isinstance(extracted, dict):
                        extracted = {}
                    # Node callbacks run concurrently with the cancellation poll and with
                    # other scheduler callbacks.  Persist each checkpoint through its own
                    # session so a checkpoint commit cannot race a refresh on the run
                    # session or interleave transactions for sibling nodes.
                    async with self._session_maker() as checkpoint_session:
                        await DurableExecutionService(checkpoint_session).record_checkpoint(
                            project_id=plan.project_id,
                            lease_id=None,
                            runner_id=None,
                            actor_user_id=plan.actor_id,
                            payload=RunnerCheckpointRequest(
                                execution_id=plan.execution_id,
                                node_id=update.node_id,
                                node_type=update.node_type,
                                name=update.name,
                                status=update.status,
                                attempts=update.attempts,
                                output=safe_result.output if safe_result is not None else None,
                                result=safe_result,
                                error_code=update.error_code,
                                error_message=update.error_message,
                                started_at=update.started_at,
                                finished_at=update.occurred_at,
                                input_hash=update.input_hash
                                or checkpoint_input_hash(update.node_id, snapshot),
                                extracted_variables=cast(dict[str, JsonValue], redact(extracted)),
                                snapshot_revision=1,
                                fencing_token=0,
                                phase=update.phase,
                                best_effort=update.best_effort,
                            ),
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
