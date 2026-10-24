"""A timed-out A request cannot cancel the independent target's lifetime in this transport."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from scripts.selftest.collect_evidence import journal
from scripts.selftest.contracts import Builds
from scripts.selftest.fixed_baseline import execute_fixed_baseline
from test_selftest_engine_dependencies import DependencyContext
from test_selftest_engine_dependencies import dependency_context as dependency_context
from test_tasking_api import tasking_context as tasking_context


async def test_old_core_timeout_waits_for_real_mock_end_without_changing_raw_failed(
    dependency_context: DependencyContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = dependency_context
    batch = "old-core-late-target-end"
    background: list[asyncio.Task[httpx.Response]] = []
    terminal_active: list[int] = []
    original = context.api.object

    async def record_terminal(method, path, payload=None, *, idempotency_key=None):
        result = await original(method, path, payload, idempotency_key=idempotency_key)
        if method == "POST" and path.endswith("/runs"):
            snapshot = await context.observer.object(
                "GET", f"/selftest/batches/{batch}/scenarios/ST-CORE-timeout/journal"
            )
            terminal_active.append(snapshot["metrics"]["active_count"])
        return result

    monkeypatch.setattr(context.api, "object", record_terminal)

    async def forward(request: httpx.Request) -> httpx.Response:
        task = asyncio.create_task(
            context.target.request(
                request.method,
                request.url.raw_path.decode(),
                content=request.content,
                headers=dict(request.headers),
            )
        )
        background.append(task)
        # Shield substitutes only the separate deployed M process lifetime.
        # The M begin/end events and delayed response are real.
        response = await asyncio.shield(task)
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    with respx.mock as routes:
        routes.route(host="fixed-fixture.example").mock(side_effect=forward)
        result = await execute_fixed_baseline(
            context.api,
            context.reader,
            context.observer,
            project_id=context.project,
            environment_id=context.environment,
            service_id=context.service,
            batch_key=batch,
            nonce="old-core-timeout-nonce-001",
            fixture_digest="a" * 64,
            builds=Builds(
                runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
            ),
            output_dir=tmp_path / "settled",
            deadline=datetime.now(UTC) + timedelta(seconds=30),
        )
    await asyncio.gather(*background)
    assert terminal_active == [1]
    assert result.report.exit_code == 0, result.report.model_dump_json(indent=2)
    timeout = next(
        item for item in result.evidence.scenarios if item.scenario_id == "ST-CORE-timeout"
    )
    assert timeout.execution.status == "failed" and timeout.execution.error_code == "NODE_TIMEOUT"
    assert timeout.journal.metrics.complete and timeout.journal.metrics.active_count == 0
    assert timeout.journal.metrics.completed_count == 1
    assert (
        timeout.journal.metrics.events[0].completed_at > timeout.execution.completed_at.timestamp()
    )
    assert (
        timeout.journal.metrics.events[0].completed_at <= result.evidence.collected_at.timestamp()
    )


async def test_journal_settlement_honors_deadline_and_retains_unfinished_fact(
    dependency_context: DependencyContext,
) -> None:
    context = dependency_context
    batch = "settlement-deadline"
    await context.observer.request(
        "PUT",
        f"/selftest/batches/{batch}/scenarios/scenario",
        {
            "nonce": "settlement-deadline-nonce-001",
            "fixture_digest": "a" * 64,
            "delay_ms": 150,
        },
    )
    request = asyncio.create_task(context.target.get(f"/selftest/{batch}/scenario/request"))
    await asyncio.sleep(0.01)
    actual = await journal(
        context.observer, batch, "scenario", deadline=datetime.now(UTC) + timedelta(milliseconds=20)
    )
    assert actual.metrics.active_count == 1 and not actual.metrics.complete
    assert actual.metrics.events[0].completed_at is None
    await request
    settled = await journal(context.observer, batch, "scenario")
    assert settled.metrics.complete and settled.metrics.active_count == 0
    assert actual.metrics.events[0].request_id == settled.metrics.events[0].request_id
