"""Independent public cancellation/claim interleaving at the scheduler boundary."""

import asyncio
from uuid import UUID

import pytest
from test_selftest_scheduler_boundaries import _queue
from test_tasking_api import TaskingTestContext
from test_tasking_api import tasking_context as tasking_context

from app.models.tasking import TestPlanRun as PlanRun
from app.models.tasking import TestPlanRunItem as RunItem
from app.models.workflows import WorkflowExecution
from app.repositories.tasking import TaskingRepository
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanCoordinator


@pytest.mark.parametrize("terminal_status", ["cancelled", "passed", "failed"])
async def test_cancel_waiting_for_guard_still_records_terminal_child(
    tasking_context: TaskingTestContext, monkeypatch: pytest.MonkeyPatch, terminal_status: str
) -> None:
    queued = await _queue(tasking_context)
    coordinator = PlanCoordinator(tasking_context.session_maker, tasking_context.events)
    cancel_read = asyncio.Event()
    release_cancel = asyncio.Event()
    original = TaskingRepository.lock_project_run

    async def queued_cancel_guard(repository, project_id: UUID, run_id: UUID):
        if not cancel_read.is_set():
            cancel_read.set()
            await asyncio.wait_for(release_cancel.wait(), timeout=5)
        return await original(repository, project_id, run_id)

    monkeypatch.setattr(TaskingRepository, "lock_project_run", queued_cancel_guard)
    cancel = asyncio.create_task(
        tasking_context.client.post(
            f"/api/v1/projects/{queued.project_id}/test-plan-runs/{queued.run_id}/cancel",
            headers=queued.headers,
        ),
        name="public-cancel-before-claim",
    )
    await asyncio.wait_for(cancel_read.wait(), timeout=5)
    assert await coordinator._claim(queued.run_id) is not None
    prepared = await coordinator._prepare_attempt(queued.run_id, queued.item_id)
    assert prepared is not None
    release_cancel.set()
    response = await asyncio.wait_for(cancel, timeout=5)
    assert response.status_code == 200, response.text
    async with tasking_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, prepared[0])
        assert execution is not None and execution.cancel_requested_at is not None
        execution.status = terminal_status
        await session.commit()
    assert not await coordinator._record_attempt(queued.run_id, queued.item_id, prepared[0])
    await coordinator._complete(queued.run_id)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        item = await session.get(RunItem, queued.item_id)
        assert run is not None and item is not None
        assert run.status == "cancelled"
        assert item.status == "cancelled"


async def test_quality_failure_rolls_back_parent_and_outcomes_before_retry(
    tasking_context: TaskingTestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from app.models.quality import FlakyRecord
    from app.services.quality import QualityService

    queued = await _queue(tasking_context)
    coordinator = PlanCoordinator(tasking_context.session_maker, tasking_context.events)
    assert await coordinator._claim(queued.run_id) is not None
    async with tasking_context.session_maker() as session:
        item = await session.get(RunItem, queued.item_id)
        assert item is not None
        item.status = "passed"
        await session.commit()
    original = QualityService.finalize_run

    async def interrupted_quality(service, *, run, items):
        await original(service, run=run, items=items)
        await service._session.flush()
        raise RuntimeError("synthetic failure after outcome write")

    with monkeypatch.context() as patch:
        patch.setattr(QualityService, "finalize_run", interrupted_quality)
        with pytest.raises(RuntimeError, match="after outcome write"):
            await coordinator._complete(queued.run_id)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        assert run is not None and run.status == "running"
        assert run.completed_at is None and run.quality_summary == {}
        assert (
            await session.scalar(
                select(FlakyRecord).where(FlakyRecord.last_run_id == queued.run_id)
            )
            is None
        )
    await coordinator._complete(queued.run_id)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        outcome = await session.scalar(
            select(FlakyRecord).where(FlakyRecord.last_run_id == queued.run_id)
        )
        assert run is not None and run.status == "passed"
        assert outcome is not None and outcome.total_runs == 1
