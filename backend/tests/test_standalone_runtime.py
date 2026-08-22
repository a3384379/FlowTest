import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import standalone_schema
from app.core.config import Settings
from app.core.storage import LocalObjectStorage
from app.domain.runtime_profiles import RuntimeProfile, describe_runtime_profile
from app.services.execution_events import (
    ExecutionEvent,
    ExecutionEventType,
    InProcessExecutionEventBus,
)
from app.services.rate_limit import InProcessRateLimiter
from app.tasking import standalone as standalone_tasks
from app.tasking.standalone import StandaloneTaskDispatcher


class _SessionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_standalone_profile_uses_in_process_topology() -> None:
    description = describe_runtime_profile(RuntimeProfile.STANDALONE)
    assert description.worker_topology.value == "in_process"
    assert {feature.value for feature in description.unavailable_features} == {
        "performance_lab",
        "environment_lab",
    }


def test_standalone_rejects_runner_fabric() -> None:
    with pytest.raises(ValidationError, match="Runner Fabric"):
        Settings(
            _env_file=None,
            runtime_profile="standalone",
            feature_runner_fabric_enabled=True,
        )


@pytest.mark.asyncio
async def test_local_object_storage_is_atomic_and_rejects_traversal(tmp_path) -> None:
    storage = LocalObjectStorage(tmp_path / "artifacts")
    await storage.put(key="nested/result.json", content=b"{}", content_type="application/json")
    stored = await storage.get(key="nested/result.json")
    assert stored.content == b"{}"
    assert stored.content_type == "application/json"
    with pytest.raises(ValueError):
        await storage.put(key="../outside", content=b"bad", content_type="text/plain")


@pytest.mark.asyncio
async def test_in_process_event_bus_replays_and_sequences_events() -> None:
    bus = InProcessExecutionEventBus(retention_seconds=60)
    execution_id = uuid4()
    started = ExecutionEvent(
        type=ExecutionEventType.EXECUTION_STARTED,
        execution_id=execution_id,
        emitted_at=datetime.now(UTC),
        execution_status="running",
    )
    completed = ExecutionEvent(
        type=ExecutionEventType.EXECUTION_COMPLETED,
        execution_id=execution_id,
        emitted_at=datetime.now(UTC),
        execution_status="passed",
    )
    await bus.publish(started)
    await bus.publish(completed)
    events = [event async for event in bus.subscribe(execution_id)]
    assert [event.sequence for event in events] == [1, 2]
    assert events[-1].type is ExecutionEventType.EXECUTION_COMPLETED


@pytest.mark.asyncio
async def test_in_process_rate_limiter_enforces_window() -> None:
    limiter = InProcessRateLimiter()
    first = await limiter.check(key="test", limit=1, window_seconds=60)
    second = await limiter.check(key="test", limit=1, window_seconds=60)
    assert first.allowed is True
    assert second.allowed is False
    assert second.remaining == 0


@pytest.mark.asyncio
async def test_standalone_schema_bootstrap_records_revision(tmp_path, monkeypatch) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
    monkeypatch.setattr(standalone_schema, "engine", test_engine)
    await standalone_schema.initialize_standalone_database()
    async with test_engine.connect() as connection:
        value = await connection.scalar(
            standalone_schema.text(
                "SELECT value FROM flowtest_standalone_meta WHERE key = 'schema_baseline'"
            )
        )
    await test_engine.dispose()
    assert value == standalone_schema.BASELINE_REVISION


@pytest.mark.asyncio
async def test_standalone_schema_upgrades_existing_project_policy_column(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy-schema.db'}")
    async with test_engine.begin() as connection:
        await connection.execute(
            standalone_schema.text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)")
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO flowtest_standalone_meta (key, value) "
                "VALUES ('schema_baseline', '20260822_0032')"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text("INSERT INTO alembic_version VALUES ('20260822_0032')")
        )
        await standalone_schema._ensure_incremental_columns(connection)
        columns = await connection.execute(standalone_schema.text("PRAGMA table_info(projects)"))
        version = await connection.scalar(
            standalone_schema.text("SELECT version_num FROM alembic_version")
        )

    await test_engine.dispose()
    assert "outbound_policy_enabled" in {str(row[1]) for row in columns.fetchall()}
    assert version == standalone_schema.BASELINE_REVISION


@pytest.mark.asyncio
async def test_standalone_dispatcher_runs_and_stops_in_process_tasks(monkeypatch) -> None:
    dispatcher = StandaloneTaskDispatcher(
        lambda: _SessionContext(),
        InProcessExecutionEventBus(retention_seconds=60),
        LocalObjectStorage(),
    )
    called: list[str] = []

    async def operation() -> None:
        called.append("ok")

    dispatcher._spawn("unit", operation)
    await asyncio.gather(*tuple(dispatcher._tasks))
    await asyncio.sleep(0)
    assert called == ["ok"]
    assert (await dispatcher.metrics_reader.read()).task_counts == {"succeeded": 1}

    async def failure() -> None:
        raise RuntimeError("expected")

    dispatcher._spawn("failure", failure)
    with pytest.raises(RuntimeError):
        await asyncio.gather(*tuple(dispatcher._tasks))
    await asyncio.sleep(0)
    assert (await dispatcher.metrics_reader.read()).task_counts["failed"] == 1

    with pytest.raises(Exception, match="性能任务"):
        dispatcher.start_performance_run(uuid4())
    with pytest.raises(Exception, match="环境任务"):
        dispatcher.start_environment_provision(uuid4())
    with pytest.raises(Exception, match="环境任务"):
        dispatcher.start_environment_cleanup(uuid4())
    await dispatcher.shutdown()
    with pytest.raises(Exception, match="后台任务运行时已关闭"):
        dispatcher.start_test_plan(uuid4(), queue_name="general", priority=5)


@pytest.mark.asyncio
async def test_standalone_dispatcher_executes_workflow_plan_and_ai(monkeypatch) -> None:
    dispatcher = StandaloneTaskDispatcher(
        lambda: _SessionContext(),
        InProcessExecutionEventBus(retention_seconds=60),
        LocalObjectStorage(),
    )
    workflow_called: list[object] = []
    notification_called: list[object] = []

    async def run_now(plan) -> None:
        workflow_called.append(plan)

    async def workflow_notification(execution_id) -> None:
        notification_called.append(execution_id)

    monkeypatch.setattr(dispatcher._workflow, "run_now", run_now)
    monkeypatch.setattr(dispatcher, "_deliver_workflow_notification", workflow_notification)
    plan = SimpleNamespace(execution_id="execution")
    await dispatcher._run_workflow(plan)
    assert workflow_called == [plan]
    assert notification_called == ["execution"]

    test_plan_called: list[object] = []

    class FakeTestPlanCoordinator:
        def __init__(self, *_args) -> None:
            pass

        async def run(self, run_id) -> None:
            test_plan_called.append(run_id)

    monkeypatch.setattr(standalone_tasks, "TestPlanRunCoordinator", FakeTestPlanCoordinator)
    monkeypatch.setattr(dispatcher, "_deliver_test_plan_notification", workflow_notification)
    await dispatcher._run_test_plan("run")
    assert test_plan_called == ["run"]

    ai_called: list[object] = []

    class FakeAIJobRunner:
        def __init__(self, *_args) -> None:
            pass

        async def run(self, job_id) -> None:
            ai_called.append(job_id)

    monkeypatch.setattr(standalone_tasks, "AIJobRunner", FakeAIJobRunner)
    monkeypatch.setattr(standalone_tasks, "OpenAICompatibleProvider", lambda _config: object())
    await dispatcher._run_ai_job("job")
    assert ai_called == ["job"]
    await dispatcher.shutdown()


@pytest.mark.asyncio
async def test_standalone_scheduler_enqueues_and_cleans_up(monkeypatch) -> None:
    dispatcher = StandaloneTaskDispatcher(
        lambda: _SessionContext(),
        InProcessExecutionEventBus(retention_seconds=60),
        LocalObjectStorage(),
    )
    run = SimpleNamespace(id="run", queue_name="general", queue_priority=5)
    queued: list[tuple[object, str, int]] = []
    cleaned: list[object] = []

    class FakeTaskPlanService:
        def __init__(self, _session) -> None:
            pass

        async def queue_due_runs(self, _now):
            return [run]

    class FakeRetentionService:
        def __init__(self, _session, _storage) -> None:
            pass

        async def cleanup(self):
            cleaned.append("done")
            return "summary"

    def record_run(run_id, *, queue_name, priority) -> None:
        queued.append((run_id, queue_name, priority))

    monkeypatch.setattr(standalone_tasks, "TestPlanService", FakeTaskPlanService)
    monkeypatch.setattr(standalone_tasks, "RetentionCleanupService", FakeRetentionService)
    monkeypatch.setattr(dispatcher, "start_test_plan", record_run)
    await dispatcher._enqueue_due_test_plans()
    await dispatcher._cleanup_retention()
    assert queued == [("run", "general", 5)]
    assert cleaned == ["done"]
    dispatcher.start_scheduler()
    await dispatcher.shutdown()
