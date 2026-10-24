"""A lost worker must settle persisted work without replaying an unknown mutation."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import respx
from httpx import Response
from test_selftest_scheduler_boundaries import _queue
from test_tasking_api import TaskingTestContext
from test_tasking_api import tasking_context as tasking_context

from app.models.tasking import TestPlanRun as PlanRun
from app.models.tasking import TestPlanRunItem as RunItem
from app.models.workflows import WorkflowExecution
from app.repositories.tasking import TaskingRepository
from app.services.test_plan_lease import maintain_worker_lease
from app.services.test_plan_recovery import TestPlanRecoveryService as Recovery
from app.services.test_plan_runner import TestPlanRunCoordinator as Coordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_status", ["running", "passed"])
async def test_expired_worker_settles_unknown_or_completed_attempt_without_replay(
    tasking_context: TaskingTestContext, execution_status: str
) -> None:
    queued = await _queue(tasking_context, retries=3)
    worker = Coordinator(tasking_context.session_maker, tasking_context.events, lease_seconds=60)
    assert await worker._claim(queued.run_id)
    prepared = await worker._prepare_attempt(queued.run_id, queued.item_id)
    assert prepared is not None
    execution_id, _ = prepared
    now = datetime.now(UTC)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        execution = await session.get(WorkflowExecution, execution_id)
        assert run is not None and execution is not None
        run.worker_lease_expires_at = now - timedelta(seconds=1)
        execution.status = execution_status
        await session.commit()
    async with tasking_context.session_maker() as session:
        assert await Recovery(session).recover_expired(now) == 1
        assert await Recovery(session).recover_expired(now) == 0
    assert await worker._prepare_attempt(queued.run_id, queued.item_id) is None
    assert await worker._claim(queued.run_id) is None
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        item = await session.get(RunItem, queued.item_id)
        execution = await session.get(WorkflowExecution, execution_id)
        assert run is not None and item is not None and execution is not None
        expected = "passed" if execution_status == "passed" else "failed"
        assert run.status == item.status == execution.status == expected
        assert item.attempts == 1
        assert run.worker_lease_owner is None
        assert run.completed_at is not None
        if execution_status == "running":
            assert execution.error_code == "TEST_PLAN_WORKER_LOST"


@pytest.mark.asyncio
async def test_live_worker_lease_and_unleased_runs_are_not_recovered(
    tasking_context: TaskingTestContext,
) -> None:
    queued = await _queue(tasking_context)
    worker = Coordinator(tasking_context.session_maker, tasking_context.events, lease_seconds=60)
    assert await worker._claim(queued.run_id)
    async with tasking_context.session_maker() as session:
        assert await Recovery(session).recover_expired(datetime.now(UTC)) == 0
        run = await session.get(PlanRun, queued.run_id)
        assert run is not None
        run.worker_lease_expires_at = None
        await session.commit()
        assert await Recovery(session).recover_expired(datetime.now(UTC) + timedelta(days=1)) == 0


@pytest.mark.asyncio
@respx.mock
async def test_late_worker_completion_cannot_revive_an_expired_claim(
    tasking_context: TaskingTestContext,
) -> None:
    queued = await _queue(tasking_context)
    worker = Coordinator(tasking_context.session_maker, tasking_context.events, lease_seconds=60)
    assert await worker._claim(queued.run_id)
    prepared = await worker._prepare_attempt(queued.run_id, queued.item_id)
    assert prepared is not None
    execution_id, plan = prepared
    received, release = asyncio.Event(), asyncio.Event()

    async def respond(_request):
        received.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return Response(200, json={"code": 0})

    route = respx.get("http://workflow.example.com/users/v1").mock(side_effect=respond)
    task = asyncio.create_task(
        WorkflowRunCoordinator(tasking_context.session_maker, tasking_context.events).run_now(plan)
    )
    try:
        await asyncio.wait_for(received.wait(), timeout=5)
        now = datetime.now(UTC)
        async with tasking_context.session_maker() as session:
            run = await session.get(PlanRun, queued.run_id)
            assert run is not None
            run.worker_lease_expires_at = now - timedelta(seconds=1)
            await session.commit()
        async with tasking_context.session_maker() as session:
            assert await Recovery(session).recover_expired(now) == 1
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=5)
    async with tasking_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, execution_id)
        run = await session.get(PlanRun, queued.run_id)
        assert execution is not None and run is not None
        assert execution.status == run.status == "failed"
        assert execution.error_code == "TEST_PLAN_WORKER_LOST"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_a_normal_terminal_run_does_not_cancel_its_successful_parent_task(
    tasking_context: TaskingTestContext,
) -> None:
    queued = await _queue(tasking_context)
    worker = Coordinator(tasking_context.session_maker, tasking_context.events, lease_seconds=60)
    assert await worker._claim(queued.run_id)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        assert run is not None
        owner = run.worker_lease_owner
        assert owner is not None
        run.status = "passed"
        run.worker_lease_owner = None
        await session.commit()

    async def waiting_parent() -> None:
        await asyncio.Event().wait()

    parent = asyncio.create_task(waiting_parent())
    completing = asyncio.Event()
    completing.set()
    try:
        await asyncio.wait_for(
            maintain_worker_lease(
                tasking_context.session_maker, queued.run_id, owner, 0, parent, completing
            ),
            timeout=2,
        )
        assert parent.cancelling() == 0
    finally:
        parent.cancel()
        await asyncio.gather(parent, return_exceptions=True)


@pytest.mark.asyncio
async def test_only_the_live_current_owner_can_extend_the_lease(
    tasking_context: TaskingTestContext,
) -> None:
    queued = await _queue(tasking_context)
    worker = Coordinator(tasking_context.session_maker, tasking_context.events, lease_seconds=60)
    assert await worker._claim(queued.run_id)
    now = datetime.now(UTC)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        assert run is not None and run.worker_lease_owner is not None
        owner = run.worker_lease_owner
        repository = TaskingRepository(session)
        assert not await repository.renew_worker_lease(
            queued.run_id, "different-owner", now, now + timedelta(seconds=60)
        )
        assert await repository.renew_worker_lease(
            queued.run_id, owner, now, now + timedelta(seconds=60)
        )
        await session.commit()
        run.worker_lease_expires_at = now - timedelta(seconds=1)
        await session.commit()
        assert not await repository.renew_worker_lease(
            queued.run_id, owner, now, now + timedelta(seconds=60)
        )


@pytest.mark.asyncio
async def test_expired_worker_cannot_finalize_before_reconciliation(
    tasking_context: TaskingTestContext,
) -> None:
    queued = await _queue(tasking_context)
    worker = Coordinator(tasking_context.session_maker, tasking_context.events, lease_seconds=60)
    assert await worker._claim(queued.run_id)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        item = await session.get(RunItem, queued.item_id)
        assert run is not None and item is not None
        run.worker_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        item.status = "passed"
        await session.commit()
    await worker._complete(queued.run_id)
    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        assert run is not None and run.status == "running"


@pytest.mark.asyncio
@pytest.mark.parametrize("leased", [False, True])
async def test_cancel_committed_between_prepare_read_and_claim_starts_no_new_attempt(
    tasking_context: TaskingTestContext, monkeypatch: pytest.MonkeyPatch, leased: bool
) -> None:
    queued = await _queue(tasking_context)
    worker = Coordinator(
        tasking_context.session_maker, tasking_context.events, lease_seconds=60 if leased else None
    )
    assert await worker._claim(queued.run_id)
    reached, release = asyncio.Event(), asyncio.Event()
    original = Coordinator._can_prepare

    async def gate(self, repository, run, item):
        reached.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return await original(self, repository, run, item)

    monkeypatch.setattr(Coordinator, "_can_prepare", gate)
    task = asyncio.create_task(worker._prepare_attempt(queued.run_id, queued.item_id))
    try:
        await asyncio.wait_for(reached.wait(), timeout=5)
        cancelled = await tasking_context.client.post(
            f"/api/v1/projects/{queued.project_id}/test-plan-runs/{queued.run_id}/cancel",
            headers=queued.headers,
        )
        assert cancelled.status_code == 200, cancelled.text
    finally:
        release.set()
    assert await asyncio.wait_for(task, timeout=5) is None
    async with tasking_context.session_maker() as session:
        item = await session.get(RunItem, queued.item_id)
        assert item is not None
        assert (
            item.status == "cancelled" and item.attempts == 0 and item.workflow_execution_id is None
        )
