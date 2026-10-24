import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.composition import build_workflow_service
from app.core.config import settings
from app.core.errors import AppError
from app.models.access import User
from app.models.tasking import TestPlanRun, TestPlanRunItem
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
        *,
        lease_seconds: int | None = None,
    ) -> None:
        self._session_maker = session_maker
        self._events = events
        if lease_seconds is not None and not 15 <= lease_seconds <= 300:
            raise ValueError("worker lease must be between 15 and 300 seconds")
        self._lease_seconds = lease_seconds
        self._lease_owner = str(uuid4())

    async def run(self, run_id: UUID) -> None:
        items = await self._claim(run_id)
        if items is None:
            return
        semaphore = asyncio.Semaphore(settings.test_plan_concurrency)
        completing = asyncio.Event()
        heartbeat = self._heartbeat(run_id, completing)

        async def execute(item_id: UUID) -> None:
            async with semaphore:
                await self._execute_item(run_id, item_id)

        try:
            await asyncio.gather(*(execute(item.id) for item in items))
            completing.set()
            await self._complete(run_id)
        except Exception as error:
            logger.exception("Test plan worker failed", extra={"test_plan_run_id": str(run_id)})
            await self._fail_run(run_id, str(error))
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)

    def _heartbeat(self, run_id: UUID, completing: asyncio.Event) -> asyncio.Task[None] | None:
        from app.services.test_plan_lease import maintain_worker_lease

        parent = asyncio.current_task()
        if self._lease_seconds is None or parent is None:
            return None
        return asyncio.create_task(
            maintain_worker_lease(
                self._session_maker,
                run_id,
                self._lease_owner,
                self._lease_seconds,
                parent,
                completing,
            ),
            name=f"plan-lease-{run_id}",
        )

    async def _claim(self, run_id: UUID) -> list[TestPlanRunItem] | None:
        async with self._session_maker() as session:
            tasks = TaskingRepository(session)
            started = datetime.now(UTC)
            claimed = (
                await tasks.claim_run(run_id, started)
                if self._lease_seconds is None
                else await tasks.claim_run(
                    run_id,
                    started,
                    lease_owner=self._lease_owner,
                    lease_expires_at=started + timedelta(seconds=self._lease_seconds),
                )
            )
            if not claimed:
                return None
            await session.commit()
            return await tasks.list_run_items(run_id)

    async def _execute_item(self, run_id: UUID, item_id: UUID) -> None:
        capacity_deadline = asyncio.get_running_loop().time() + 300
        for _attempt in range(4):
            while True:
                try:
                    prepared = await self._prepare_attempt(run_id, item_id)
                    break
                except _CapacityUnavailable:
                    if asyncio.get_running_loop().time() >= capacity_deadline:
                        await self._fail_item_capacity(item_id)
                        return
                    await asyncio.sleep(0.25)
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
            if not await self._can_prepare(tasks, run, item):
                return None
            if item.attempts > item.max_retries:
                return None
            actor = await session.get(User, run.requested_by_id)
            if actor is None or not actor.is_active:
                item.status = "failed"
                item.error_message = "触发用户不存在或已停用"
                await session.commit()
                return None
            try:
                execution, plan = await build_workflow_service(session).prepare_execution(
                    actor=actor,
                    project_id=run.project_id,
                    workflow_id=item.workflow_id,
                    environment_id=item.environment_id,
                    version=item.workflow_version,
                    runtime_variables=item.runtime_variables,
                    runtime_headers=item.runtime_headers,
                    commit=False,
                )
                if item.target_type == "case":
                    execution.source_case_id = item.target_id
                    execution.source_case_version = item.target_version
                    execution.source_trigger = "plan"
                execution.source_plan_run_item_id = item.id
            except AppError as error:
                if error.code == "PROJECT_CONCURRENCY_EXCEEDED":
                    await session.rollback()
                    raise _CapacityUnavailable from error
                item.status = "failed"
                item.error_message = error.message
                await session.commit()
                return None
            except Exception as error:
                logger.exception(
                    "Unable to prepare test plan item",
                    extra={"test_plan_run_id": str(run_id), "test_plan_run_item_id": str(item_id)},
                )
                item.status = "failed"
                item.error_message = str(error)
                await session.commit()
                return None
            item.attempts += 1
            item.status = "running"
            item.workflow_execution_id = execution.id
            await session.commit()
            return execution.id, plan

    async def _can_prepare(
        self, tasks: TaskingRepository, run: TestPlanRun, item: TestPlanRunItem
    ) -> bool:
        if run.status != "running" or item.status != "queued":
            return False
        return await tasks.lock_preparing_run(
            run.id,
            self._lease_owner if self._lease_seconds is not None else None,
            datetime.now(UTC),
        )

    async def _record_attempt(self, run_id: UUID, item_id: UUID, execution_id: UUID) -> bool:
        async with self._session_maker() as session:
            tasks = TaskingRepository(session)
            if self._lease_seconds is not None and not await tasks.lock_owned_running_run(
                run_id, self._lease_owner, datetime.now(UTC)
            ):
                return False
            run = await tasks.get_run(run_id)
            item = await session.get(TestPlanRunItem, item_id)
            execution = await WorkflowService(session).load_execution_for_run(execution_id)
            if (
                run is None
                or item is None
                or run.status not in {"running", "cancelled"}
                or item.status != "running"
                or item.workflow_execution_id != execution_id
                or execution.status not in {"passed", "failed", "cancelled"}
            ):
                return False
            if (
                run.status == "cancelled"
                or run.cancel_requested_at is not None
                or execution.status == "cancelled"
            ):
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
            locked = (
                await tasks.lock_running_run(run_id)
                if self._lease_seconds is None
                else await tasks.lock_owned_running_run(
                    run_id, self._lease_owner, datetime.now(UTC)
                )
            )
            if not locked:
                return
            run = await tasks.get_run(run_id)
            if run is None:
                return
            items = await tasks.list_run_items(run.id)
            if not items or any(item.status in {"queued", "running"} for item in items):
                return
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
            run.worker_lease_owner = None
            run.worker_lease_expires_at = None
            from app.services.quality import QualityService

            await QualityService(session).finalize_run(run=run, items=items)
            await session.commit()

    async def _fail_item_capacity(self, item_id: UUID) -> None:
        async with self._session_maker() as session:
            item = await session.get(TestPlanRunItem, item_id)
            if item is not None and item.status == "queued":
                item.status = "failed"
                item.error_message = "等待项目并发配额超时"
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
            run.worker_lease_owner = None
            run.worker_lease_expires_at = None
            await session.commit()


class _CapacityUnavailable(RuntimeError):
    pass
