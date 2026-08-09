import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.access import User
from app.models.tasking import TestPlanRunItem
from app.repositories.tasking import TaskingRepository
from app.services.execution_events import ExecutionEventBus
from app.services.workflow_coordinator import WorkflowRunCoordinator
from app.services.workflows import WorkflowExecutionPlan, WorkflowService

logger = logging.getLogger(__name__)


class TestPlanRunCoordinator:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        events: ExecutionEventBus,
    ) -> None:
        self._session_maker = session_maker
        self._events = events

    async def run(self, run_id: UUID) -> None:
        items = await self._claim(run_id)
        if items is None:
            return
        semaphore = asyncio.Semaphore(settings.test_plan_concurrency)

        async def execute(item_id: UUID) -> None:
            async with semaphore:
                await self._execute_item(run_id, item_id)

        try:
            await asyncio.gather(*(execute(item.id) for item in items))
            await self._complete(run_id)
        except Exception as error:
            logger.exception("Test plan worker failed", extra={"test_plan_run_id": str(run_id)})
            await self._fail_run(run_id, str(error))

    async def _claim(self, run_id: UUID) -> list[TestPlanRunItem] | None:
        async with self._session_maker() as session:
            tasks = TaskingRepository(session)
            run = await tasks.get_run(run_id)
            if run is None or run.status != "queued" or run.cancel_requested_at is not None:
                return None
            run.status = "running"
            run.started_at = datetime.now(UTC)
            await session.commit()
            return await tasks.list_run_items(run.id)

    async def _execute_item(self, run_id: UUID, item_id: UUID) -> None:
        for _attempt in range(4):
            prepared = await self._prepare_attempt(run_id, item_id)
            if prepared is None:
                return
            execution_id, plan = prepared
            await WorkflowRunCoordinator(self._session_maker, self._events).run_now(plan)
            should_retry = await self._record_attempt(run_id, item_id, execution_id)
            if not should_retry:
                return

    async def _prepare_attempt(
        self, run_id: UUID, item_id: UUID
    ) -> tuple[UUID, WorkflowExecutionPlan] | None:
        async with self._session_maker() as session:
            tasks = TaskingRepository(session)
            run = await tasks.get_run(run_id)
            item = await session.get(TestPlanRunItem, item_id)
            if run is None or item is None or run.cancel_requested_at is not None:
                if item is not None and item.status in {"queued", "running"}:
                    item.status = "cancelled"
                    await session.commit()
                return None
            if item.attempts > item.max_retries:
                return None
            actor = await session.get(User, run.requested_by_id)
            if actor is None or not actor.is_active:
                item.status = "failed"
                item.error_message = "触发用户不存在或已停用"
                await session.commit()
                return None
            item.attempts += 1
            item.status = "running"
            await session.commit()
            try:
                execution, plan = await WorkflowService(session).prepare_execution(
                    actor=actor,
                    project_id=run.project_id,
                    workflow_id=item.workflow_id,
                    environment_id=item.environment_id,
                    version=item.workflow_version,
                    runtime_variables=item.runtime_variables,
                    runtime_headers=item.runtime_headers,
                )
            except Exception as error:
                logger.exception(
                    "Unable to prepare test plan item",
                    extra={"test_plan_run_id": str(run_id), "test_plan_run_item_id": str(item_id)},
                )
                item.status = "failed"
                item.error_message = str(error)
                await session.commit()
                return None
            item.workflow_execution_id = execution.id
            await session.commit()
            return execution.id, plan

    async def _record_attempt(self, run_id: UUID, item_id: UUID, execution_id: UUID) -> bool:
        async with self._session_maker() as session:
            tasks = TaskingRepository(session)
            run = await tasks.get_run(run_id)
            item = await session.get(TestPlanRunItem, item_id)
            execution = await WorkflowService(session).load_execution_for_run(execution_id)
            if run is None or item is None:
                return False
            if run.cancel_requested_at is not None or execution.status == "cancelled":
                item.status = "cancelled"
                item.error_message = execution.error_message
                await session.commit()
                return False
            if execution.status == "passed":
                item.status = "passed"
                item.error_message = None
                await session.commit()
                return False
            should_retry = item.attempts <= item.max_retries
            item.status = "queued" if should_retry else "failed"
            item.error_message = execution.error_message
            await session.commit()
            return should_retry

    async def _complete(self, run_id: UUID) -> None:
        async with self._session_maker() as session:
            tasks = TaskingRepository(session)
            run = await tasks.get_run(run_id)
            if run is None:
                return
            items = await tasks.list_run_items(run.id)
            if run.cancel_requested_at is not None or any(
                item.status == "cancelled" for item in items
            ):
                run.status = "cancelled"
            elif any(item.status == "failed" for item in items):
                run.status = "failed"
                run.error_message = f"{sum(item.status == 'failed' for item in items)} 个执行项失败"
            else:
                run.status = "passed"
            run.completed_at = datetime.now(UTC)
            await session.commit()

    async def _fail_run(self, run_id: UUID, message: str) -> None:
        async with self._session_maker() as session:
            tasks = TaskingRepository(session)
            run = await tasks.get_run(run_id)
            if run is None or run.status in {"passed", "failed", "cancelled"}:
                return
            items = await tasks.list_run_items(run.id)
            for item in items:
                if item.status in {"queued", "running"}:
                    item.status = "failed"
                    item.error_message = "后台任务运行失败"
            run.status = "failed"
            run.error_message = message[:2000]
            run.completed_at = datetime.now(UTC)
            await session.commit()
