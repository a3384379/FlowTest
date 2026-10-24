"""Settle expired worker claims without retrying an operation of unknown outcome."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tasking import TestPlanRun, TestPlanRunItem
from app.models.workflows import WorkflowExecution
from app.repositories.tasking import TaskingRepository
from app.repositories.workflows import WorkflowRepository

WORKER_LOST_CODE = "TEST_PLAN_WORKER_LOST"
WORKER_LOST_MESSAGE = "执行 worker 的租约已过期; 保留已知结果, 不重放结果未知的请求"


class TestPlanRecoveryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def recover_expired(self, now: datetime) -> int:
        identities = list(
            await self._session.scalars(
                select(TestPlanRun.id)
                .where(
                    TestPlanRun.status == "running",
                    TestPlanRun.worker_lease_owner.is_not(None),
                    TestPlanRun.worker_lease_expires_at <= now,
                )
                .order_by(TestPlanRun.worker_lease_expires_at)
                .limit(100)
            )
        )
        recovered = 0
        for identity in identities:
            recovered += int(await self._recover(identity, now))
        return recovered

    async def _recover(self, identity: UUID, now: datetime) -> bool:
        locked = await self._session.scalar(
            update(TestPlanRun)
            .where(
                TestPlanRun.id == identity,
                TestPlanRun.status == "running",
                TestPlanRun.worker_lease_owner.is_not(None),
                TestPlanRun.worker_lease_expires_at <= now,
            )
            .values(worker_lease_owner=None, worker_lease_expires_at=None)
            .execution_options(synchronize_session=False)
            .returning(TestPlanRun.id)
        )
        if locked is None:
            return False
        run = await self._session.get(TestPlanRun, identity, populate_existing=True)
        if run is None:
            raise RuntimeError("claimed test plan run disappeared within its transaction")
        items = await TaskingRepository(self._session).list_run_items(identity)
        for item in items:
            await self._settle_item(item, now)
        run.status = _run_status(items, cancelled=run.cancel_requested_at is not None)
        run.completed_at = now
        run.error_message = WORKER_LOST_MESSAGE if run.status == "failed" else None
        from app.services.quality import QualityService

        await QualityService(self._session).finalize_run(run=run, items=items)
        await self._session.commit()
        return True

    async def _settle_item(self, item: TestPlanRunItem, now: datetime) -> None:
        if item.status not in {"queued", "running"}:
            return
        if item.workflow_execution_id is not None:
            await WorkflowRepository(self._session).lock_execution_state(item.workflow_execution_id)
        execution = (
            await self._session.get(
                WorkflowExecution, item.workflow_execution_id, populate_existing=True
            )
            if item.workflow_execution_id is not None
            else None
        )
        if execution is not None and execution.status in {"passed", "failed", "cancelled"}:
            item.status = execution.status
            item.error_message = execution.error_message
            return
        item.status = "failed"
        item.error_message = WORKER_LOST_MESSAGE
        if execution is not None:
            await self._settle_execution(execution, now)

    async def _settle_execution(self, execution: WorkflowExecution, now: datetime) -> None:
        execution.status = "failed"
        execution.error_code = WORKER_LOST_CODE
        execution.error_message = WORKER_LOST_MESSAGE
        execution.cancel_requested_at = now
        execution.force_cancel_requested_at = now
        execution.completed_at = now
        children = await self._session.scalars(
            select(WorkflowExecution).where(
                WorkflowExecution.parent_execution_id == execution.id,
                WorkflowExecution.status.in_(("queued", "running")),
            )
        )
        for child in children:
            await self._settle_execution(child, now)


def _run_status(items: list[TestPlanRunItem], *, cancelled: bool) -> str:
    if cancelled or any(item.status == "cancelled" for item in items):
        return "cancelled"
    if not items or any(item.status == "failed" for item in items):
        return "failed"
    return "passed"
