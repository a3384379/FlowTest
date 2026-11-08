"""Deterministic scheduling interleavings; these are not distributed-worker acceptance."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import pytest
import respx
from httpx import Response
from sqlalchemy import select
from test_tasking_api import (
    TaskingTestContext,
    _create_published_workflow,
    _login_headers,
)
from test_tasking_api import tasking_context as tasking_context

from app.models.quality import FlakyRecord
from app.models.tasking import TestPlanRun as PlanRun
from app.models.tasking import TestPlanRunItem as RunItem
from app.models.workflows import WorkflowExecution
from app.repositories.tasking import TaskingRepository
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanCoordinator


@dataclass(frozen=True)
class QueuedRun:
    project_id: str
    run_id: UUID
    item_id: UUID
    headers: dict[str, str]


async def _queue(context: TaskingTestContext, *, retries: int = 0) -> QueuedRun:
    headers = await _login_headers(context.client)
    project, environment, workflow = await _create_published_workflow(context.client, headers)
    response = await context.client.post(
        f"/api/v1/projects/{project}/test-plans",
        headers=headers,
        json={
            "name": "调度边界表征",
            "items": [
                {"workflow_id": workflow, "environment_id": environment, "max_retries": retries}
            ],
        },
    )
    assert response.status_code == 201, response.text
    plan_id = response.json()["id"]
    queued = await context.client.post(
        f"/api/v1/projects/{project}/test-plans/{plan_id}/runs", headers=headers
    )
    assert queued.status_code == 202, queued.text
    run_id = UUID(queued.json()["id"])
    async with context.session_maker() as session:
        item = await session.scalar(select(RunItem).where(RunItem.test_plan_run_id == run_id))
        assert item is not None
        return QueuedRun(project, run_id, item.id, headers)


async def test_two_workers_have_at_most_one_successful_claim(
    tasking_context: TaskingTestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued = await _queue(tasking_context)
    original = TaskingRepository.claim_run
    both_read = asyncio.Event()
    reads = 0

    async def synchronized_claim(
        repository: TaskingRepository, run_id: UUID, started_at: datetime
    ) -> bool:
        nonlocal reads
        reads += 1
        if reads == 2:
            both_read.set()
        await asyncio.wait_for(both_read.wait(), timeout=5)
        return await original(repository, run_id, started_at)

    monkeypatch.setattr(TaskingRepository, "claim_run", synchronized_claim)
    coordinators = [
        PlanCoordinator(tasking_context.session_maker, tasking_context.events) for _ in range(2)
    ]
    claims = await asyncio.gather(
        *(coordinator._claim(queued.run_id) for coordinator in coordinators)
    )

    assert sum(claim is not None for claim in claims) == 1


@pytest.mark.parametrize("concurrent", [False, True])
async def test_duplicate_complete_does_not_double_count_quality_outcomes(
    tasking_context: TaskingTestContext, concurrent: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued = await _queue(tasking_context)
    coordinator = PlanCoordinator(tasking_context.session_maker, tasking_context.events)
    await coordinator._claim(queued.run_id)
    async with tasking_context.session_maker() as session:
        item = await session.get(RunItem, queued.item_id)
        assert item is not None
        item.status = "passed"
        await session.commit()
    if concurrent:
        original = TaskingRepository.lock_running_run
        both_ready = asyncio.Event()
        entrants = 0

        async def synchronized_finalize(repository: TaskingRepository, run_id: UUID) -> bool:
            nonlocal entrants
            entrants += 1
            if entrants == 2:
                both_ready.set()
            await asyncio.wait_for(both_ready.wait(), timeout=5)
            return await original(repository, run_id)

        monkeypatch.setattr(TaskingRepository, "lock_running_run", synchronized_finalize)
        await asyncio.gather(
            coordinator._complete(queued.run_id), coordinator._complete(queued.run_id)
        )
    else:
        await coordinator._complete(queued.run_id)
        await coordinator._complete(queued.run_id)

    async with tasking_context.session_maker() as session:
        record = await session.scalar(
            select(FlakyRecord).where(FlakyRecord.last_run_id == queued.run_id)
        )
        assert record is not None
        assert record.total_runs == 1


@pytest.mark.parametrize("child_status", ["queued", "running"])
async def test_parent_cannot_pass_while_a_child_is_nonterminal(
    tasking_context: TaskingTestContext, child_status: str
) -> None:
    queued = await _queue(tasking_context)
    coordinator = PlanCoordinator(tasking_context.session_maker, tasking_context.events)
    await coordinator._claim(queued.run_id)
    async with tasking_context.session_maker() as session:
        item = await session.get(RunItem, queued.item_id)
        assert item is not None
        item.status = child_status
        await session.commit()

    await coordinator._complete(queued.run_id)

    async with tasking_context.session_maker() as session:
        run = await session.get(PlanRun, queued.run_id)
        assert run is not None
        assert run.status == "running"
        assert run.completed_at is None


@respx.mock
async def test_cancel_between_failed_attempt_read_and_retry_prevents_extra_wire_request(
    tasking_context: TaskingTestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued = await _queue(tasking_context, retries=1)
    coordinator = PlanCoordinator(tasking_context.session_maker, tasking_context.events)
    await coordinator._claim(queued.run_id)
    target = respx.get("http://workflow.example.com/users/v1").mock(
        return_value=Response(500, json={"error": "synthetic failure"})
    )
    stale_read = asyncio.Event()
    cancelled = asyncio.Event()
    original = TaskingRepository.get_run

    async def pause_before_retry(repository: TaskingRepository, run_id: UUID) -> PlanRun | None:
        run = await original(repository, run_id)
        current = asyncio.current_task()
        if current is not None and current.get_name() == "cancel-race-worker" and target.called:
            stale_read.set()
            await asyncio.wait_for(cancelled.wait(), timeout=5)
        return run

    monkeypatch.setattr(TaskingRepository, "get_run", pause_before_retry)
    worker = asyncio.create_task(
        coordinator._execute_item(queued.run_id, queued.item_id), name="cancel-race-worker"
    )
    try:
        await asyncio.wait_for(stale_read.wait(), timeout=10)
        response = await tasking_context.client.post(
            f"/api/v1/projects/{queued.project_id}/test-plan-runs/{queued.run_id}/cancel",
            headers=queued.headers,
        )
        assert response.status_code == 200, response.text
    finally:
        cancelled.set()
    await asyncio.wait_for(worker, timeout=10)
    await coordinator._complete(queued.run_id)

    async with tasking_context.session_maker() as session:
        run, item = (
            await session.get(PlanRun, queued.run_id),
            await session.get(RunItem, queued.item_id),
        )
        assert run is not None and item is not None
        assert run.status == item.status == "cancelled"
        assert item.attempts == 1
    assert target.call_count == 1


async def test_old_attempt_callback_cannot_reopen_a_successful_retry(
    tasking_context: TaskingTestContext,
) -> None:
    queued = await _queue(tasking_context, retries=1)
    coordinator = PlanCoordinator(tasking_context.session_maker, tasking_context.events)
    await coordinator._claim(queued.run_id)
    first = await coordinator._prepare_attempt(queued.run_id, queued.item_id)
    assert first is not None
    async with tasking_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, first[0])
        assert execution is not None
        execution.status = "failed"
        await session.commit()
    assert await coordinator._record_attempt(queued.run_id, queued.item_id, first[0])
    second = await coordinator._prepare_attempt(queued.run_id, queued.item_id)
    assert second is not None and second[0] != first[0]
    async with tasking_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, second[0])
        assert execution is not None
        execution.status = "passed"
        await session.commit()
    assert not await coordinator._record_attempt(queued.run_id, queued.item_id, second[0])
    await coordinator._complete(queued.run_id)

    assert not await coordinator._record_attempt(queued.run_id, queued.item_id, first[0])

    async with tasking_context.session_maker() as session:
        run, item = (
            await session.get(PlanRun, queued.run_id),
            await session.get(RunItem, queued.item_id),
        )
        assert run is not None and item is not None
        assert run.status == item.status == "passed"
        assert item.workflow_execution_id == second[0]
        assert item.attempts == 2


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_incomplete_execution_cannot_be_recorded_as_a_failed_retry(
    tasking_context: TaskingTestContext, status: str
) -> None:
    queued = await _queue(tasking_context, retries=1)
    coordinator = PlanCoordinator(tasking_context.session_maker, tasking_context.events)
    await coordinator._claim(queued.run_id)
    prepared = await coordinator._prepare_attempt(queued.run_id, queued.item_id)
    assert prepared is not None
    async with tasking_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, prepared[0])
        assert execution is not None
        execution.status = status
        await session.commit()

    assert not await coordinator._record_attempt(queued.run_id, queued.item_id, prepared[0])

    async with tasking_context.session_maker() as session:
        item = await session.get(RunItem, queued.item_id)
        assert item is not None and item.status == "running"
        assert item.attempts == 1
