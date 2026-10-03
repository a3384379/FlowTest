import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_test_plan_dispatcher, get_workflow_coordinator
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.core.storage import StoredObject
from app.domain.tasking import webhook_signature
from app.domain.test_assets import definition_fingerprint
from app.main import app
from app.models import Base
from app.models import tasking as tasking_models
from app.models import test_assets as test_asset_models
from app.models.access import User
from app.models.workflows import WorkflowExecution, WorkflowVersion
from app.services.execution_events import ExecutionEvent
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator
from app.services.workflows import WorkflowService

ADMIN_EMAIL = "task-admin@example.com"
ADMIN_PASSWORD = "task-password-123!"


@dataclass(slots=True)
class TaskingTestContext:
    client: AsyncClient
    session_maker: async_sessionmaker[AsyncSession]
    events: "RecordingEventBus"
    queue: "RecordingQueue"


@pytest.fixture
async def tasking_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[TaskingTestContext]:
    monkeypatch.setattr("app.services.artifacts.object_storage", MemoryObjectStorage())
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'tasking.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Task administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    events = RecordingEventBus()
    workflow_coordinator = WorkflowRunCoordinator(session_maker, events)
    queue = RecordingQueue()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workflow_coordinator] = lambda: workflow_coordinator
    app.dependency_overrides[get_test_plan_dispatcher] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield TaskingTestContext(client, session_maker, events, queue)
    await workflow_coordinator.shutdown()
    app.dependency_overrides.clear()
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_direct_case_run_pins_versions_and_reports_real_case_source(
    tasking_context: TaskingTestContext,
) -> None:
    client = tasking_context.client
    headers = await _login_headers(client)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    target = respx.get("http://workflow.example.com/users/v1").mock(
        return_value=Response(200, json={"id": 1})
    )
    case_path = f"/api/v1/projects/{project_id}/test-cases"
    definition = {
        "workflow_id": workflow_id,
        "workflow_version": 1,
        "environment_id": environment_id,
        "runtime_variables": {"account": "001"},
        "runtime_headers": {"X-Case": "old"},
    }
    created = await client.post(
        case_path, headers=headers, json={"name": "第一用例", "definition": definition}
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    run_path = f"{case_path}/{case_id}/runs"
    assert (await client.get(f"{case_path}/{case_id}", headers=headers)).status_code == 200
    missing_key = await client.post(run_path, headers=headers, json={"source": "published"})
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    unpublished = await client.post(
        run_path,
        headers={**headers, "Idempotency-Key": "unpublished"},
        json={"source": "published"},
    )
    assert unpublished.status_code == 409, unpublished.text
    fingerprint = created.json()["draft_fingerprint"]
    run_headers = {**headers, "Idempotency-Key": "first-case-run"}
    started = await client.post(
        run_path,
        headers=run_headers,
        json={"source": "draft", "publish_draft": True, "expected_draft_fingerprint": fingerprint},
    )
    assert started.status_code == 202, started.text
    assert started.json()["case_version"] == 1
    assert started.json()["created_new_version"] is True
    replay = await client.post(
        run_path,
        headers=run_headers,
        json={"source": "draft", "publish_draft": True, "expected_draft_fingerprint": fingerprint},
    )
    assert replay.status_code == 202
    assert replay.json()["execution_id"] == started.json()["execution_id"]
    reused_key = await client.post(
        run_path, headers=run_headers, json={"source": "published", "version": 1}
    )
    assert reused_key.status_code == 409
    for _ in range(80):
        latest = await client.get(
            f"{case_path}/runs/latest", headers=headers, params={"case_ids": case_id}
        )
        assert latest.status_code == 200, latest.text
        if latest.json() and latest.json()[0]["status"] not in {"queued", "running"}:
            break
        await asyncio.sleep(0.05)
    assert latest.json()[0]["status"] == "passed"
    assert latest.json()[0]["source"] == "direct"
    assert latest.json()[0]["case_version"] == 1
    assert len(target.calls) == 1
    assert target.calls[0].request.headers["X-Case"] == "old"

    definition["runtime_headers"] = {"X-Case": "new"}
    changed = await client.patch(
        f"{case_path}/{case_id}", headers=headers, json={"definition": definition}
    )
    assert changed.status_code == 200
    old_run = await client.post(
        run_path,
        headers={**headers, "Idempotency-Key": "old-version-run"},
        json={
            "source": "published",
            "version": 1,
            "runtime_headers": {"x-case": "temporary"},
        },
    )
    assert old_run.status_code == 202, old_run.text
    assert old_run.json()["case_version"] == 1
    for _ in range(80):
        if len(target.calls) >= 2:
            break
        await asyncio.sleep(0.05)
    assert len(target.calls) >= 2
    assert target.calls[1].request.headers["X-Case"] == "temporary"
    conflict = await client.post(
        run_path,
        headers={**headers, "Idempotency-Key": "stale-draft-run"},
        json={"source": "draft", "publish_draft": True, "expected_draft_fingerprint": fingerprint},
    )
    assert conflict.status_code == 409
    updated = await client.post(
        run_path,
        headers={**headers, "Idempotency-Key": "new-version-run"},
        json={
            "source": "draft",
            "publish_draft": True,
            "expected_draft_fingerprint": changed.json()["draft_fingerprint"],
        },
    )
    assert updated.status_code == 202, updated.text
    assert updated.json()["case_version"] == 2
    assert updated.json()["workflow_version"] == 1
    repeat_publish = await client.post(
        run_path,
        headers={**headers, "Idempotency-Key": "repeat-draft-run"},
        json={
            "source": "draft",
            "publish_draft": True,
            "expected_draft_fingerprint": changed.json()["draft_fingerprint"],
        },
    )
    assert repeat_publish.status_code == 202, repeat_publish.text
    assert repeat_publish.json()["created_new_version"] is False
    assert repeat_publish.json()["case_version"] == 2

    plan = await client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "固定版本计划",
            "items": [
                {
                    "target_type": "workflow",
                    "target_id": workflow_id,
                    "environment_id": environment_id,
                },
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]
    added = await client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan_id}/items",
        headers=headers,
        json={"target_type": "case", "target_id": case_id, "target_version": 1},
    )
    assert added.status_code == 201, added.text
    assert added.json()["items"][1]["target_version"] == 1
    duplicate = await client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan_id}/items",
        headers=headers,
        json={"target_type": "case", "target_id": case_id, "target_version": 2},
    )
    assert duplicate.status_code == 409
    queued = await client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan_id}/runs", headers=headers
    )
    assert queued.status_code == 202, queued.text
    await PlanRunCoordinator(tasking_context.session_maker, tasking_context.events).run(
        UUID(queued.json()["id"])
    )
    latest_plan = await client.get(
        f"{case_path}/runs/latest", headers=headers, params={"case_ids": case_id}
    )
    assert latest_plan.status_code == 200, latest_plan.text
    assert latest_plan.json()[0]["source"] == "plan"
    assert latest_plan.json()[0]["case_version"] == 1
    historical_execution_id = UUID(latest_plan.json()[0]["execution_id"])
    async with tasking_context.session_maker() as session:
        historical_execution = await session.get(WorkflowExecution, historical_execution_id)
        assert historical_execution is not None
        historical_execution.source_case_id = None
        historical_execution.source_case_version = None
        historical_execution.source_trigger = None
        historical_execution.source_plan_run_item_id = None
        await session.commit()
    historical_latest = await client.get(
        f"{case_path}/runs/latest", headers=headers, params={"case_ids": case_id}
    )
    assert historical_latest.status_code == 200, historical_latest.text
    assert historical_latest.json()[0]["execution_id"] == str(historical_execution_id)
    assert historical_latest.json()[0]["source"] == "plan"

    second = await client.post(
        case_path,
        headers=headers,
        json={"name": "第二用例", "definition": definition},
    )
    assert second.status_code == 201, second.text
    second_run = await client.post(
        f"{case_path}/{second.json()['id']}/runs",
        headers={**headers, "Idempotency-Key": "second-case-run"},
        json={
            "source": "draft",
            "publish_draft": True,
            "expected_draft_fingerprint": second.json()["draft_fingerprint"],
        },
    )
    assert second_run.status_code == 202, second_run.text
    latest_both = await client.get(
        f"{case_path}/runs/latest",
        headers=headers,
        params=[("case_ids", case_id), ("case_ids", second.json()["id"])],
    )
    assert {row["case_id"] for row in latest_both.json()} == {case_id, second.json()["id"]}


@respx.mock
@pytest.mark.asyncio
async def test_test_plan_ci_retry_webhook_cancel_and_schedule(
    tasking_context: TaskingTestContext,
) -> None:
    context = tasking_context
    headers = await _login_headers(context.client)
    project_id, environment_id, workflow_id = await _create_published_workflow(
        context.client, headers
    )
    created = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "回归测试计划",
            "description": "S8",
            "schedule_interval_seconds": 60,
            "items": [
                {
                    "workflow_id": workflow_id,
                    "environment_id": environment_id,
                    "max_retries": 1,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    webhook_secret = plan.pop("webhook_secret")
    plan_id = plan["id"]
    listed = await context.client.get(f"/api/v1/projects/{project_id}/test-plans", headers=headers)
    assert listed.status_code == 200
    assert "webhook_secret" not in json.dumps(listed.json())
    assert listed.json()["items"][0]["items"][0]["workflow_version"] == 1

    token_created = await context.client.post(
        f"/api/v1/projects/{project_id}/service-tokens",
        headers=headers,
        json={
            "name": "GitHub Actions",
            "scopes": ["execute:test-plan", "execute:workflow"],
        },
    )
    assert token_created.status_code == 201, token_created.text
    service_token = token_created.json()["token"]
    token_id = token_created.json()["id"]
    tokens = await context.client.get(
        f"/api/v1/projects/{project_id}/service-tokens", headers=headers
    )
    assert service_token not in tokens.text

    target = respx.get("http://workflow.example.com/users/v1").mock(
        side_effect=[Response(500, json={"error": "temporary"}), Response(200, json={"id": 7})]
    )
    queued = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/test-plans/{plan_id}/runs",
        headers={"Authorization": f"Bearer {service_token}"},
    )
    assert queued.status_code == 202, queued.text
    run_id = UUID(queued.json()["id"])
    assert context.queue.test_plan_run_ids == [run_id]
    await PlanRunCoordinator(context.session_maker, context.events).run(run_id)
    detail = await context.client.get(
        f"/api/v1/projects/{project_id}/test-plan-runs/{run_id}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "passed"
    assert detail.json()["run"]["trigger_type"] == "ci"
    assert detail.json()["items"][0]["attempts"] == 2
    assert detail.json()["items"][0]["workflow_execution_id"]
    assert len(target.calls) == 2

    body = b'{"source":"deployment"}'
    timestamp = str(int(datetime.now(UTC).timestamp()))
    invalid = await context.client.post(
        f"/api/v1/webhooks/test-plans/{plan_id}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-FlowTest-Timestamp": timestamp,
            "X-FlowTest-Signature": "sha256=invalid",
        },
    )
    assert invalid.status_code == 401
    webhook = await context.client.post(
        f"/api/v1/webhooks/test-plans/{plan_id}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-FlowTest-Timestamp": timestamp,
            "X-FlowTest-Signature": webhook_signature(webhook_secret, timestamp, body),
        },
    )
    assert webhook.status_code == 202, webhook.text
    webhook_run_id = webhook.json()["id"]
    cancelled = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plan-runs/{webhook_run_id}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    await PlanRunCoordinator(context.session_maker, context.events).run(UUID(webhook_run_id))

    revoked = await context.client.delete(
        f"/api/v1/projects/{project_id}/service-tokens/{token_id}", headers=headers
    )
    assert revoked.status_code == 200
    denied = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/test-plans/{plan_id}/runs",
        headers={"Authorization": f"Bearer {service_token}"},
    )
    assert denied.status_code == 401

    from app.services.tasking import TestPlanService

    async with context.session_maker() as session:
        scheduled = await TestPlanService(session).queue_due_runs(
            datetime.now(UTC) + timedelta(seconds=61)
        )
    assert len(scheduled) == 1
    assert scheduled[0].trigger_type == "schedule"


class RecordingQueue:
    def __init__(self) -> None:
        self.test_plan_run_ids: list[UUID] = []
        self.dispatches: list[tuple[UUID, str, int]] = []

    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        self.test_plan_run_ids.append(run_id)
        self.dispatches.append((run_id, queue_name, priority))


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    async def publish(self, event: ExecutionEvent) -> ExecutionEvent:
        stored = event.model_copy(update={"sequence": len(self.events) + 1})
        self.events.append(stored)
        return stored


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}

    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = StoredObject(content=content, content_type=content_type)

    async def get(self, *, key: str) -> StoredObject:
        return self.objects[key]

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)


@respx.mock
@pytest.mark.asyncio
async def test_quality_gate_flaky_quarantine_cron_junit_and_capacity(
    tasking_context: TaskingTestContext,
) -> None:
    context = tasking_context
    headers = await _login_headers(context.client)
    project_id, environment_id, workflow_id = await _create_published_workflow(
        context.client, headers
    )
    capacity = await context.client.put(
        f"/api/v1/projects/{project_id}/capacity-policy",
        headers=headers,
        json={"execution_concurrency_limit": 8, "queued_run_limit": 1200},
    )
    assert capacity.status_code == 200, capacity.text
    assert capacity.json()["queued_run_limit"] == 1200

    invalid_cron = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "无效 Cron",
            "schedule_cron": "* * * *",
            "items": [{"workflow_id": workflow_id, "environment_id": environment_id}],
        },
    )
    assert invalid_cron.status_code == 422
    assert invalid_cron.json()["error"]["code"] == "INVALID_TEST_PLAN_SCHEDULE"

    gate = await context.client.post(
        f"/api/v1/projects/{project_id}/quality-gates",
        headers=headers,
        json={
            "name": "主分支门禁",
            "min_pass_rate": 50,
            "max_failed": 1,
            "max_flaky": 0,
            "max_duration_regression_percent": 1000,
            "require_no_breaking_changes": False,
        },
    )
    assert gate.status_code == 201, gate.text
    gate_id = gate.json()["id"]
    plan = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "Cron 质量计划",
            "schedule_cron": "0 9 * * 1-5",
            "schedule_timezone": "Asia/Shanghai",
            "queue_priority": 8,
            "items": [{"workflow_id": workflow_id, "environment_id": environment_id}],
        },
    )
    assert plan.status_code == 201, plan.text
    assert plan.json()["queue_priority"] == 8
    plan_id = plan.json()["id"]

    target = respx.get("http://workflow.example.com/users/v1").mock(
        side_effect=[Response(500, json={"error": "failure"}), Response(200, json={"id": 1})]
    )
    run_ids: list[UUID] = []
    for expected in ("failed", "passed"):
        queued = await context.client.post(
            f"/api/v1/projects/{project_id}/test-plans/{plan_id}/runs", headers=headers
        )
        assert queued.status_code == 202, queued.text
        assert queued.json()["queue_priority"] == 8
        run_id = UUID(queued.json()["id"])
        run_ids.append(run_id)
        await PlanRunCoordinator(context.session_maker, context.events).run(run_id)
        detail = await context.client.get(
            f"/api/v1/projects/{project_id}/test-plan-runs/{run_id}", headers=headers
        )
        assert detail.json()["run"]["status"] == expected
    assert len(target.calls) == 2
    assert context.queue.dispatches[-1] == (run_ids[-1], "general", 8)

    quality = await context.client.get(
        f"/api/v1/projects/{project_id}/test-plan-runs/{run_ids[-1]}/quality",
        headers=headers,
    )
    assert quality.status_code == 200, quality.text
    assert quality.json()["baseline_run_id"] == str(run_ids[0])
    assert quality.json()["summary"]["flaky"] == 1
    assert quality.json()["evaluations"][0]["status"] == "failed"

    flaky = await context.client.get(f"/api/v1/projects/{project_id}/flaky-tests", headers=headers)
    assert flaky.status_code == 200
    record = flaky.json()["items"][0]
    assert record["flaky_score"] == 100
    quarantined = await context.client.put(
        f"/api/v1/projects/{project_id}/flaky-tests/{record['id']}/quarantine",
        headers=headers,
        json={"quarantined": True},
    )
    assert quarantined.json()["quarantined"] is True

    limited = await context.client.put(
        f"/api/v1/projects/{project_id}/capacity-policy",
        headers=headers,
        json={"execution_concurrency_limit": 1, "queued_run_limit": 1},
    )
    assert limited.status_code == 200

    third = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan_id}/runs", headers=headers
    )
    third_id = UUID(third.json()["id"])
    queue_denied = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan_id}/runs", headers=headers
    )
    assert queue_denied.status_code == 429
    assert queue_denied.json()["error"]["code"] == "PROJECT_QUEUE_LIMIT_EXCEEDED"
    await PlanRunCoordinator(context.session_maker, context.events).run(third_id)
    detail = await context.client.get(
        f"/api/v1/projects/{project_id}/test-plan-runs/{third_id}", headers=headers
    )
    assert detail.json()["items"][0]["status"] == "quarantined"
    junit = await context.client.get(
        f"/api/v1/projects/{project_id}/test-plan-runs/{third_id}/junit.xml",
        headers=headers,
    )
    assert junit.status_code == 200
    assert b"<skipped" in junit.content

    token = await context.client.post(
        f"/api/v1/projects/{project_id}/service-tokens",
        headers=headers,
        json={"name": "Quality Gate", "scopes": ["execute:test-plan"]},
    )
    raw_token = token.json()["token"]
    ci_gate = await context.client.get(
        f"/api/v1/ci/projects/{project_id}/test-plan-runs/{run_ids[-1]}/quality-gate",
        params={"quality_gate_id": gate_id},
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert ci_gate.status_code == 200
    assert ci_gate.json()["status"] == "failed"
    ci_junit = await context.client.get(
        f"/api/v1/ci/projects/{project_id}/test-plan-runs/{run_ids[-1]}/junit.xml",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert ci_junit.status_code == 200
    assert b"testsuite" in ci_junit.content

    async with context.session_maker() as session:
        actor = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert actor is not None
        service = WorkflowService(session)
        await service.prepare_execution(
            actor=actor,
            project_id=UUID(project_id),
            workflow_id=UUID(workflow_id),
            environment_id=UUID(environment_id),
            version=1,
            runtime_variables={},
            runtime_headers={},
        )
        with pytest.raises(AppError, match="并发") as quota_error:
            await service.prepare_execution(
                actor=actor,
                project_id=UUID(project_id),
                workflow_id=UUID(workflow_id),
                environment_id=UUID(environment_id),
                version=1,
                runtime_variables={},
                runtime_headers={},
            )
        assert quota_error.value.code == "PROJECT_CONCURRENCY_EXCEEDED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header_name", "header_value"),
    [("X Legacy", "valid"), ("X-Legacy", "line\nbreak")],
)
async def test_legacy_case_headers_remain_readable_until_repaired(
    tasking_context: TaskingTestContext, header_name: str, header_value: str
) -> None:
    client = tasking_context.client
    headers = await _login_headers(client)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    case_path = f"/api/v1/projects/{project_id}/test-cases"
    definition = {
        "workflow_id": workflow_id,
        "workflow_version": 1,
        "environment_id": environment_id,
        "runtime_headers": {"X-Valid": "value"},
    }
    created = await client.post(
        case_path, headers=headers, json={"name": "历史用例", "definition": definition}
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    published = await client.post(f"{case_path}/{case_id}/versions", headers=headers, json={})
    assert published.status_code == 200, published.text

    legacy_definition = {**definition, "runtime_headers": {header_name: header_value}}
    async with tasking_context.session_maker() as session:
        case = await session.get(test_asset_models.TestCase, UUID(case_id))
        version = await session.scalar(
            select(test_asset_models.TestCaseVersion).where(
                test_asset_models.TestCaseVersion.test_case_id == UUID(case_id)
            )
        )
        assert case is not None and version is not None
        case.draft_definition = legacy_definition
        version.definition = legacy_definition
        version.fingerprint = definition_fingerprint(legacy_definition)
        await session.commit()

    listed = await client.get(case_path, headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["draft_definition"]["runtime_headers"] == {
        header_name: header_value
    }
    fetched = await client.get(f"{case_path}/{case_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    versions = await client.get(f"{case_path}/{case_id}/versions", headers=headers)
    assert versions.status_code == 200, versions.text
    assert versions.json()[0]["definition"]["runtime_headers"] == {header_name: header_value}
    metadata_update = await client.patch(
        f"{case_path}/{case_id}", headers=headers, json={"description": "待修复"}
    )
    assert metadata_update.status_code == 200, metadata_update.text

    invalid_create = await client.post(
        case_path,
        headers=headers,
        json={"name": "新用例", "definition": legacy_definition},
    )
    assert invalid_create.status_code == 422, invalid_create.text
    invalid_publish = await client.post(f"{case_path}/{case_id}/versions", headers=headers, json={})
    assert invalid_publish.status_code == 422, invalid_publish.text
    assert invalid_publish.json()["error"]["code"] == "INVALID_TEST_CASE_DEFINITION"
    invalid_run = await client.post(
        f"{case_path}/{case_id}/runs",
        headers={**headers, "Idempotency-Key": "legacy-header-run"},
        json={"source": "published", "version": 1},
    )
    assert invalid_run.status_code == 422, invalid_run.text
    assert invalid_run.json()["error"]["code"] == "INVALID_TEST_CASE_DEFINITION"
    invalid_draft_run = await client.post(
        f"{case_path}/{case_id}/runs",
        headers={**headers, "Idempotency-Key": "legacy-draft-run"},
        json={
            "source": "draft",
            "publish_draft": True,
            "expected_draft_fingerprint": fetched.json()["draft_fingerprint"],
        },
    )
    assert invalid_draft_run.status_code == 422, invalid_draft_run.text
    assert invalid_draft_run.json()["error"]["code"] == "INVALID_TEST_CASE_DEFINITION"
    invalid_clone = await client.post(
        f"{case_path}/{case_id}/clone", headers=headers, json={"name": "历史用例副本"}
    )
    assert invalid_clone.status_code == 422, invalid_clone.text
    assert invalid_clone.json()["error"]["code"] == "INVALID_TEST_CASE_DEFINITION"

    repaired = await client.patch(
        f"{case_path}/{case_id}", headers=headers, json={"definition": definition}
    )
    assert repaired.status_code == 200, repaired.text
    new_version = await client.post(f"{case_path}/{case_id}/versions", headers=headers, json={})
    assert new_version.status_code == 200, new_version.text
    assert new_version.json()["version"] == 2


@pytest.mark.asyncio
async def test_case_suite_versioning_and_fixed_plan_expansion(
    tasking_context: TaskingTestContext,
) -> None:
    client = tasking_context.client
    headers = await _login_headers(client)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    folder = await client.post(
        f"/api/v1/projects/{project_id}/folders",
        headers=headers,
        json={"name": "回归资产"},
    )
    assert folder.status_code == 201, folder.text
    folder_id = folder.json()["id"]

    case_definition = {
        "workflow_id": workflow_id,
        "workflow_version": 1,
        "environment_id": environment_id,
        "runtime_variables": {"dataset": "v1"},
        "runtime_headers": {"X-Case": "one"},
    }
    blank_name = await client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        headers=headers,
        json={"name": "   ", "definition": case_definition},
    )
    assert blank_name.status_code == 422
    created_case = await client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        headers=headers,
        json={
            "name": "用户查询用例",
            "description": "固定工作流版本",
            "tags": ["smoke", "api", "smoke"],
            "is_template": True,
            "definition": case_definition,
        },
    )
    assert created_case.status_code == 201, created_case.text
    test_case = created_case.json()
    case_id = test_case["id"]
    assert test_case["tags"] == ["api", "smoke"]
    assert test_case["current_version"] is None
    duplicate_case = await client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        headers=headers,
        json={
            "name": "用户查询用例",
            "definition": case_definition,
        },
    )
    assert duplicate_case.status_code == 409
    assert duplicate_case.json()["error"]["code"] == "TEST_CASE_NAME_EXISTS"

    case_v1 = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/versions",
        headers=headers,
        json={"change_note": "首个基线"},
    )
    assert case_v1.status_code == 200, case_v1.text
    assert case_v1.json()["version"] == 1
    case_definition["runtime_variables"] = {"dataset": "v2", "region": "cn"}
    updated_case = await client.patch(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}",
        headers=headers,
        json={
            "name": "用户查询用例",
            "description": "第二版草稿",
            "folder_id": folder_id,
            "tags": ["regression"],
            "is_template": False,
            "definition": case_definition,
        },
    )
    assert updated_case.status_code == 200, updated_case.text
    fetched_case = await client.get(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}", headers=headers
    )
    assert fetched_case.json()["description"] == "第二版草稿"
    case_v2 = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/versions",
        headers=headers,
        json={"change_note": "增加地域变量"},
    )
    assert case_v2.status_code == 200
    assert case_v2.json()["version"] == 2
    versions = await client.get(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/versions", headers=headers
    )
    assert [item["version"] for item in versions.json()] == [2, 1]
    case_diff = await client.get(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/versions/1/diff/2",
        headers=headers,
    )
    assert case_diff.status_code == 200
    assert {item["path"] for item in case_diff.json()["changes"]} == {
        "$.runtime_variables.dataset",
        "$.runtime_variables.region",
    }

    searched = await client.get(
        f"/api/v1/projects/{project_id}/test-cases",
        headers=headers,
        params={"search": "用户", "tag": "regression", "page": 1, "page_size": 20},
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    unfiltered_cases = await client.get(
        f"/api/v1/projects/{project_id}/test-cases",
        headers=headers,
        params={"is_template": False},
    )
    assert unfiltered_cases.json()["total"] == 1
    cloned_case = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/clone",
        headers=headers,
        json={"name": "用户查询副本"},
    )
    assert cloned_case.status_code == 201
    clone_id = cloned_case.json()["id"]
    moved_cases = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/bulk-move",
        headers=headers,
        json={"asset_ids": [case_id, clone_id], "folder_id": folder_id},
    )
    assert moved_cases.json() == {"updated": 2}

    duplicate_suite = await client.post(
        f"/api/v1/projects/{project_id}/test-suites",
        headers=headers,
        json={
            "name": "重复套件",
            "definition": {
                "items": [
                    {"test_case_id": case_id, "test_case_version": 1},
                    {"test_case_id": case_id, "test_case_version": 2},
                ]
            },
        },
    )
    assert duplicate_suite.status_code == 422
    suite_created = await client.post(
        f"/api/v1/projects/{project_id}/test-suites",
        headers=headers,
        json={
            "name": "冒烟套件",
            "description": "固定用例版本",
            "tags": ["smoke"],
            "definition": {"items": [{"test_case_id": case_id, "test_case_version": 1}]},
        },
    )
    assert suite_created.status_code == 201, suite_created.text
    suite_id = suite_created.json()["id"]
    suite_v1 = await client.post(
        f"/api/v1/projects/{project_id}/test-suites/{suite_id}/versions",
        headers=headers,
        json={"change_note": "套件基线"},
    )
    assert suite_v1.status_code == 200, suite_v1.text
    suite_updated = await client.patch(
        f"/api/v1/projects/{project_id}/test-suites/{suite_id}",
        headers=headers,
        json={
            "name": "冒烟套件",
            "description": "第二版套件草稿",
            "folder_id": folder_id,
            "tags": ["regression"],
            "definition": {"items": [{"test_case_id": case_id, "test_case_version": 2}]},
        },
    )
    assert suite_updated.status_code == 200
    fetched_suite = await client.get(
        f"/api/v1/projects/{project_id}/test-suites/{suite_id}", headers=headers
    )
    assert fetched_suite.json()["description"] == "第二版套件草稿"
    suite_v2 = await client.post(
        f"/api/v1/projects/{project_id}/test-suites/{suite_id}/versions",
        headers=headers,
        json={"change_note": "切换用例版本"},
    )
    assert suite_v2.json()["version"] == 2
    suite_versions = await client.get(
        f"/api/v1/projects/{project_id}/test-suites/{suite_id}/versions", headers=headers
    )
    assert [item["version"] for item in suite_versions.json()] == [2, 1]
    suite_diff = await client.get(
        f"/api/v1/projects/{project_id}/test-suites/{suite_id}/versions/1/diff/2",
        headers=headers,
    )
    assert suite_diff.json()["changes"][0]["path"] == "$.items"
    suites = await client.get(
        f"/api/v1/projects/{project_id}/test-suites",
        headers=headers,
        params={"search": "冒烟", "tag": "regression"},
    )
    assert suites.json()["total"] == 1
    unfiltered_suites = await client.get(
        f"/api/v1/projects/{project_id}/test-suites", headers=headers
    )
    assert unfiltered_suites.json()["total"] == 1
    cloned_suite = await client.post(
        f"/api/v1/projects/{project_id}/test-suites/{suite_id}/clone",
        headers=headers,
        json={"name": "冒烟套件副本"},
    )
    assert cloned_suite.status_code == 201
    moved_suites = await client.post(
        f"/api/v1/projects/{project_id}/test-suites/bulk-move",
        headers=headers,
        json={"asset_ids": [suite_id, cloned_suite.json()["id"]], "folder_id": folder_id},
    )
    assert moved_suites.json()["updated"] == 2

    plan_created = await client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "混合资产计划",
            "items": [
                {"workflow_id": workflow_id, "environment_id": environment_id},
                {
                    "target_type": "case",
                    "target_id": case_id,
                    "target_version": 1,
                    "runtime_variables": {"runtime": "override"},
                },
                {"target_type": "suite", "target_id": suite_id, "target_version": 1},
            ],
        },
    )
    assert plan_created.status_code == 201, plan_created.text
    plan = plan_created.json()
    assert [item["target_type"] for item in plan["items"]] == ["workflow", "case", "suite"]
    queued = await client.post(
        f"/api/v1/projects/{project_id}/test-plans/{plan['id']}/runs", headers=headers
    )
    assert queued.status_code == 202, queued.text
    run_detail = await client.get(
        f"/api/v1/projects/{project_id}/test-plan-runs/{queued.json()['id']}", headers=headers
    )
    assert run_detail.status_code == 200
    expanded = run_detail.json()["items"]
    assert len(expanded) == 3
    case_runs = [item for item in expanded if item["target_type"] == "case"]
    assert [item["target_version"] for item in case_runs] == [1, 1]
    assert case_runs[0]["target_snapshot"]["definition"]["runtime_variables"] == {"dataset": "v1"}
    assert case_runs[1]["target_snapshot"]["source_suite"] == {
        "id": suite_id,
        "version": 1,
    }


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_published_workflow(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, str, str]:
    project = await client.post("/api/v1/projects", headers=headers, json={"name": "Task project"})
    project_id = project.json()["id"]
    environment = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "Task target", "base_url": "http://workflow.example.com"},
    )
    api = await client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "User API",
            "request": {"method": "GET", "path": "/users/v1", "body_kind": "none"},
        },
    )
    api_id = api.json()["definition"]["id"]
    workflow = await client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "用户流程", "definition": _workflow_definition(api_id)},
    )
    workflow_id = workflow.json()["id"]
    published = await client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    return project_id, environment.json()["id"], workflow_id


def _workflow_definition(api_id: str) -> dict[str, object]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "api",
                "type": "api",
                "name": "查询用户",
                "position": {"x": 100, "y": 0},
                "config": {"api_definition_id": api_id},
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "start-api", "source": "start", "target": "api"},
            {"id": "api-end", "source": "api", "target": "end"},
        ],
    }


async def _native_asset_package(context: TaskingTestContext) -> tuple[str, dict[str, str], dict]:
    client = context.client
    headers = await _login_headers(client)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    root = f"/api/v1/projects/{project_id}"
    folder = await client.post(root + "/folders", headers=headers, json={"name": "包目录"})
    definition = {
        "workflow_id": workflow_id,
        "workflow_version": 1,
        "environment_id": environment_id,
        "runtime_variables": {"fixture": "v1"},
    }
    created = await client.post(
        root + "/test-cases",
        headers=headers,
        json={
            "name": "原生包用例",
            "description": "保留说明",
            "folder_id": folder.json()["id"],
            "tags": ["中文标签"],
            "is_template": True,
            "definition": definition,
        },
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    for version in (1, 2):
        definition["runtime_variables"] = {"fixture": f"v{version}"}
        updated = await client.patch(
            root + f"/test-cases/{case_id}", headers=headers, json={"definition": definition}
        )
        assert updated.status_code == 200, updated.text
        published = await client.post(
            root + f"/test-cases/{case_id}/versions", headers=headers, json={}
        )
        assert published.status_code == 200, published.text
    suite = await client.post(
        root + "/test-suites",
        headers=headers,
        json={
            "name": "原生包套件",
            "folder_id": folder.json()["id"],
            "tags": ["中文标签"],
            "definition": {"items": [{"test_case_id": case_id, "test_case_version": 1}]},
        },
    )
    assert suite.status_code == 201, suite.text
    published = await client.post(
        root + f"/test-suites/{suite.json()['id']}/versions", headers=headers, json={}
    )
    assert published.status_code == 200, published.text
    exported = await client.post(
        root + "/test-assets/export",
        headers=headers,
        json={"case_ids": [], "suite_ids": [suite.json()["id"]]},
    )
    assert exported.status_code == 200, exported.text
    assert "attachment" in exported.headers["content-disposition"]
    return root, headers, exported.json()


@pytest.mark.asyncio
async def test_native_asset_package_keeps_case_versions_and_suite_fixed_references(
    tasking_context: TaskingTestContext,
) -> None:
    context = tasking_context
    root, headers, package = await _native_asset_package(context)
    assert package["format"] == "flowtest-test-assets"
    assert package["format_version"] == 1
    assert len(package["cases"]) == 1
    case = package["cases"][0]
    assert case["is_template"] and case["tags"] == ["中文标签"]
    assert [row["version"] for row in case["versions"]] == [1, 2]
    assert package["suites"][0]["versions"][0]["definition"]["items"][0]["test_case_version"] == 1
    assert package["folders"][0]["name"] == "包目录"
    payload = {"package": package, "choices": [], "bindings": {}}
    conflict = await context.client.post(
        root + "/test-assets/import/preview", headers=headers, json=payload
    )
    assert conflict.status_code == 200, conflict.text
    assert not conflict.json()["can_apply"]
    payload["choices"] = [
        {"kind": "case", "source_id": case["id"], "action": "clone", "name": "导入用例"},
        {
            "kind": "suite",
            "source_id": package["suites"][0]["id"],
            "action": "clone",
            "name": "导入套件",
        },
    ]
    preview = await context.client.post(
        root + "/test-assets/import/preview", headers=headers, json=payload
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_apply"], preview.text
    assert not context.queue.test_plan_run_ids

    imported = await context.client.post(
        root + "/test-assets/import/apply",
        headers=headers,
        json={**payload, "expected_preview_fingerprint": preview.json()["fingerprint"]},
    )
    assert imported.status_code == 200, imported.text
    mappings = imported.json()["assets"]
    imported_case = next(row for row in mappings if row["kind"] == "case")
    imported_suite = next(row for row in mappings if row["kind"] == "suite")
    case_versions = await context.client.get(
        root + f"/test-cases/{imported_case['target_id']}/versions", headers=headers
    )
    assert len(case_versions.json()) == 2
    suite_versions = await context.client.get(
        root + f"/test-suites/{imported_suite['target_id']}/versions", headers=headers
    )
    member = suite_versions.json()[0]["definition"]["items"][0]
    assert member == {"test_case_id": imported_case["target_id"], "test_case_version": 1}
    assert not context.queue.test_plan_run_ids


def _package_clone_choices(package: dict) -> list[dict[str, str]]:
    return [
        {
            "kind": "case",
            "source_id": package["cases"][0]["id"],
            "action": "clone",
            "name": "导入用例",
        },
        {
            "kind": "suite",
            "source_id": package["suites"][0]["id"],
            "action": "clone",
            "name": "导入套件",
        },
    ]


@pytest.mark.asyncio
async def test_native_asset_package_rejects_stale_review_before_any_write(
    tasking_context: TaskingTestContext,
) -> None:
    client = tasking_context.client
    root, headers, package = await _native_asset_package(tasking_context)
    payload = {
        "package": package,
        "choices": [
            {"kind": "case", "source_id": package["cases"][0]["id"], "action": "update"},
            {"kind": "suite", "source_id": package["suites"][0]["id"], "action": "skip"},
        ],
    }
    preview = await client.post(root + "/test-assets/import/preview", headers=headers, json=payload)
    assert preview.json()["can_apply"], preview.text
    case_path = root + f"/test-cases/{package['cases'][0]['id']}"
    await client.patch(case_path, headers=headers, json={"description": "已在其他窗口编辑"})
    response = await client.post(
        root + "/test-assets/import/apply",
        headers=headers,
        json={
            **payload,
            "expected_preview_fingerprint": preview.json()["fingerprint"],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TEST_ASSET_PACKAGE_PREVIEW_STALE"
    assert response.json()["error"]["trace_id"]
    current = await client.get(case_path, headers=headers)
    assert current.json()["description"] == "已在其他窗口编辑"
    assert current.json()["current_version"] == 2


@pytest.mark.asyncio
async def test_native_asset_package_rolls_back_case_versions_when_suite_write_fails(
    tasking_context: TaskingTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.test_assets import TestSuiteService as SuiteService

    client = tasking_context.client
    root, headers, package = await _native_asset_package(tasking_context)
    payload = {"package": package, "choices": _package_clone_choices(package)}
    preview = await client.post(root + "/test-assets/import/preview", headers=headers, json=payload)
    assert preview.json()["can_apply"], preview.text

    async def fail_publish(
        self: SuiteService,
        *,
        actor: User,
        project_id: UUID,
        suite_id: UUID,
        change_note: str,
        commit: bool = True,
    ) -> test_asset_models.TestSuiteVersion:
        raise AppError(
            code="TEST_IMPORT_WRITE_FAILURE", message="模拟套件写入失败", status_code=409
        )

    monkeypatch.setattr(SuiteService, "publish", fail_publish)
    response = await client.post(
        root + "/test-assets/import/apply",
        headers=headers,
        json={
            **payload,
            "expected_preview_fingerprint": preview.json()["fingerprint"],
        },
    )
    assert response.status_code == 409, response.text
    cases = await client.get(root + "/test-cases", headers=headers)
    suites = await client.get(root + "/test-suites", headers=headers)
    assert cases.json()["total"] == suites.json()["total"] == 1
    async with tasking_context.session_maker() as session:
        assert len((await session.scalars(select(test_asset_models.TestCaseVersion))).all()) == 2
        assert len((await session.scalars(select(test_asset_models.TestSuiteVersion))).all()) == 1
    assert not tasking_context.queue.test_plan_run_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect", ["marker", "fingerprint", "fixed-reference", "duplicate", "header"]
)
async def test_native_asset_package_strict_validation_keeps_invalid_input_out_of_writes(
    tasking_context: TaskingTestContext,
    defect: str,
) -> None:
    client = tasking_context.client
    root, headers, package = await _native_asset_package(tasking_context)
    if defect == "marker":
        package["format_version"] = True
    elif defect == "fingerprint":
        package["cases"][0]["versions"][0]["fingerprint"] = "0" * 64
    elif defect == "fixed-reference":
        package["suites"][0]["versions"][0]["definition"]["items"][0]["test_case_version"] = 9
    elif defect == "duplicate":
        package["cases"].append(package["cases"][0])
    else:
        package["cases"][0]["draft_definition"]["runtime_headers"] = {
            "X-Test": "secret\r\ninjected"
        }
    response = await client.post(
        root + "/test-assets/import/preview", headers=headers, json={"package": package}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "TEST_ASSET_PACKAGE_INVALID"
    assert response.json()["error"]["trace_id"]
    assert "secret" not in response.text
    cases = await client.get(root + "/test-cases", headers=headers)
    assert cases.json()["total"] == 1


@pytest.mark.asyncio
async def test_native_asset_package_requires_explicit_project_local_resource_bindings(
    tasking_context: TaskingTestContext,
) -> None:
    client = tasking_context.client
    root, headers, package = await _native_asset_package(tasking_context)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    target_root = f"/api/v1/projects/{project_id}"
    selection = await client.post(
        target_root + "/test-assets/export",
        headers=headers,
        json={"case_ids": [package["cases"][0]["id"]]},
    )
    assert selection.status_code == 404 and selection.json()["error"]["trace_id"]
    payload = {"package": package}
    missing = await client.post(
        target_root + "/test-assets/import/preview", headers=headers, json=payload
    )
    assert missing.status_code == 200 and not missing.json()["can_apply"]
    source_workflow = package["workflows"][0]["id"]
    source_environment = package["environments"][0]["id"]
    payload["bindings"] = {
        "workflows": {source_workflow: {"target_id": workflow_id, "versions": {"1": 1}}},
        "environments": {source_environment: environment_id},
        "folders": {package["folders"][0]["id"]: None},
    }
    reviewed = await client.post(
        target_root + "/test-assets/import/preview", headers=headers, json=payload
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["can_apply"], reviewed.text
    workflow_binding = next(
        row for row in reviewed.json()["dependencies"] if row["kind"] == "workflow"
    )
    assert workflow_binding["fingerprint_changed"]
    imported = await client.post(
        target_root + "/test-assets/import/apply",
        headers=headers,
        json={
            **payload,
            "expected_preview_fingerprint": reviewed.json()["fingerprint"],
        },
    )
    assert imported.status_code == 200, imported.text
    new_case = next(row for row in imported.json()["assets"] if row["kind"] == "case")
    versions = await client.get(
        target_root + f"/test-cases/{new_case['target_id']}/versions", headers=headers
    )
    assert all(version["definition"]["workflow_id"] == workflow_id for version in versions.json())
    assert all(version["definition"]["workflow_version"] == 1 for version in versions.json())
    assert all(
        version["definition"]["environment_id"] == environment_id for version in versions.json()
    )
    original = await client.get(root + f"/test-cases/{package['cases'][0]['id']}", headers=headers)
    assert original.json()["current_version"] == 2


@pytest.mark.asyncio
async def test_native_asset_package_readonly_members_can_export_but_cannot_preview_or_apply(
    tasking_context: TaskingTestContext,
) -> None:
    from app.models.access import ProjectMember, ProjectRole

    client = tasking_context.client
    root, _headers, package = await _native_asset_package(tasking_context)
    async with tasking_context.session_maker() as session:
        viewer = User(
            email="package-viewer@example.com",
            display_name="包只读成员",
            password_hash=password_service.hash(ADMIN_PASSWORD),
            is_active=True,
            is_system_admin=False,
            requires_password_change=False,
        )
        session.add(viewer)
        await session.flush()
        session.add(
            ProjectMember(
                project_id=UUID(package["source_project_id"]),
                user_id=viewer.id,
                role=ProjectRole.VIEWER,
            )
        )
        await session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "package-viewer@example.com", "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    exported = await client.post(
        root + "/test-assets/export",
        headers=viewer_headers,
        json={"case_ids": [package["cases"][0]["id"]]},
    )
    assert exported.status_code == 200, exported.text
    for path in ("preview", "apply"):
        payload = {"package": package}
        if path == "apply":
            payload["expected_preview_fingerprint"] = "f" * 64
        response = await client.post(
            root + f"/test-assets/import/{path}", headers=viewer_headers, json=payload
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "PROJECT_FORBIDDEN"
        assert response.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_native_asset_package_enforces_streamed_request_limit(
    tasking_context: TaskingTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = tasking_context.client
    root, headers, package = await _native_asset_package(tasking_context)
    monkeypatch.setattr("app.http.test_asset_packages.PACKAGE_MAX_BYTES", 128)
    response = await client.post(
        root + "/test-assets/import/preview", headers=headers, json={"package": package}
    )
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "TEST_ASSET_PACKAGE_TOO_LARGE"
    assert response.json()["error"]["trace_id"]


@dataclass(slots=True)
class AssetHistoryFixture:
    context: TaskingTestContext
    headers: dict[str, str]
    project_id: str
    case_id: str
    suite_id: str
    oldest_execution_id: UUID
    retry_execution_id: UUID
    direct_execution_id: UUID
    oldest_run_id: UUID


@pytest.fixture
async def asset_history_fixture(tasking_context: TaskingTestContext) -> AssetHistoryFixture:
    client = tasking_context.client
    headers = await _login_headers(client)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    base_path = f"/api/v1/projects/{project_id}"
    created = await client.post(
        f"{base_path}/test-cases",
        headers=headers,
        json={
            "name": "历史分页用例",
            "definition": {
                "workflow_id": workflow_id,
                "workflow_version": 1,
                "environment_id": environment_id,
            },
        },
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    for version in (1, 2):
        response = await client.post(
            f"{base_path}/test-cases/{case_id}/versions", headers=headers, json={}
        )
        assert response.json()["version"] == version
    suite = await client.post(
        f"{base_path}/test-suites",
        headers=headers,
        json={
            "name": "历史分页套件",
            "definition": {"items": [{"test_case_id": case_id, "test_case_version": 1}]},
        },
    )
    assert suite.status_code == 201, suite.text
    suite_id = suite.json()["id"]
    for version in (1, 2):
        published = await client.post(
            f"{base_path}/test-suites/{suite_id}/versions", headers=headers, json={}
        )
        assert published.json()["version"] == version
    plan = await client.post(
        f"{base_path}/test-plans",
        headers=headers,
        json={
            "name": "资产历史计划",
            "items": [{"target_type": "suite", "target_id": suite_id, "target_version": 1}],
        },
    )
    assert plan.status_code == 201, plan.text
    oldest_execution_id, retry_id, direct_id, oldest_run_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with tasking_context.session_maker() as session:
        actor = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        version = await session.scalar(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == UUID(workflow_id))
        )
        assert actor is not None and version is not None
        start = datetime(2026, 9, 1, tzinfo=UTC)
        for index in range(41):
            run = tasking_models.TestPlanRun(
                id=oldest_run_id if index == 0 else uuid4(),
                project_id=UUID(project_id),
                test_plan_id=UUID(plan.json()["id"]),
                requested_by_id=actor.id,
                status="queued" if index == 40 else "passed",
                trigger_type="manual",
                created_at=start + timedelta(minutes=index),
            )
            item = tasking_models.TestPlanRunItem(
                id=uuid4(),
                test_plan_run_id=run.id,
                target_type="case",
                target_id=UUID(case_id),
                target_version=1 if index < 30 or index == 40 else 2,
                target_snapshot={
                    "source_suite": {
                        "id": suite_id,
                        "version": 1 if index < 30 or index == 40 else 2,
                    }
                },
                workflow_id=UUID(workflow_id),
                environment_id=UUID(environment_id),
                workflow_version=1,
                position=0,
                max_retries=1,
                attempts=0 if index == 40 else 1,
                status="queued" if index == 40 else "passed",
            )
            session.add_all([run, item])
            if index == 40:
                continue
            execution = WorkflowExecution(
                id=oldest_execution_id if index == 0 else uuid4(),
                project_id=UUID(project_id),
                workflow_id=UUID(workflow_id),
                workflow_version_id=version.id,
                environment_id=UUID(environment_id),
                triggered_by_id=actor.id,
                source_case_id=None if index == 0 else UUID(case_id),
                source_case_version=None if index == 0 else item.target_version,
                source_trigger=None if index == 0 else "plan",
                source_plan_run_item_id=None if index == 0 else item.id,
                status="passed",
                snapshot={"workflow_version": 1},
                started_at=start + timedelta(minutes=index),
            )
            item.workflow_execution_id = execution.id
            session.add(execution)
            if index == 2:
                session.add(
                    WorkflowExecution(
                        id=retry_id,
                        project_id=UUID(project_id),
                        workflow_id=UUID(workflow_id),
                        workflow_version_id=version.id,
                        environment_id=UUID(environment_id),
                        triggered_by_id=actor.id,
                        source_case_id=UUID(case_id),
                        source_case_version=1,
                        source_trigger="plan",
                        source_plan_run_item_id=item.id,
                        status="failed",
                        snapshot={"workflow_version": 1},
                        started_at=start + timedelta(minutes=index, seconds=-1),
                    )
                )
        direct = WorkflowExecution(
            id=direct_id,
            project_id=UUID(project_id),
            workflow_id=UUID(workflow_id),
            workflow_version_id=version.id,
            environment_id=UUID(environment_id),
            triggered_by_id=actor.id,
            source_case_id=UUID(case_id),
            source_case_version=2,
            source_trigger="direct",
            status="passed",
            snapshot={"workflow_version": 1},
            started_at=start + timedelta(minutes=100),
        )
        session.add(direct)
        session.add(
            WorkflowExecution(
                project_id=UUID(project_id),
                workflow_id=UUID(workflow_id),
                workflow_version_id=version.id,
                environment_id=UUID(environment_id),
                triggered_by_id=actor.id,
                source_case_id=UUID(case_id),
                source_case_version=2,
                source_trigger="direct",
                parent_execution_id=direct_id,
                dataset_row_index=0,
                status="passed",
                snapshot={"workflow_version": 1},
                started_at=start + timedelta(minutes=101),
            )
        )
        await session.commit()
    return AssetHistoryFixture(
        tasking_context,
        headers,
        project_id,
        case_id,
        suite_id,
        oldest_execution_id,
        retry_id,
        direct_id,
        oldest_run_id,
    )


@pytest.mark.asyncio
async def test_case_history_pages_direct_legacy_retry_and_queued_records(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    path = f"/api/v1/projects/{fixture.project_id}/test-cases/{fixture.case_id}/runs"
    records: list[dict[str, object]] = []
    for page in range(1, 4):
        response = await fixture.context.client.get(
            path, headers=fixture.headers, params={"page": page, "page_size": 20}
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 43
        records.extend(response.json()["items"])
    assert len(records) == 43
    assert len({row["id"] for row in records}) == 43
    assert records[0]["execution_id"] == str(fixture.direct_execution_id)
    assert records[0]["source"] == "direct"
    assert any(row["execution_id"] == str(fixture.oldest_execution_id) for row in records)
    retry = next(row for row in records if row["execution_id"] == str(fixture.retry_execution_id))
    assert retry["plan_run_id"] is not None
    assert retry["status"] == "failed"
    queued = next(row for row in records if row["execution_id"] is None)
    assert queued["status"] == "queued" and queued["source"] == "plan"
    filtered = await fixture.context.client.get(
        path, headers=fixture.headers, params={"version": 1, "page_size": 100}
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 32
    assert {row["case_version"] for row in filtered.json()["items"]} == {1}


@pytest.mark.asyncio
async def test_suite_history_queries_frozen_members_beyond_recent_twenty_runs(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    path = f"/api/v1/projects/{fixture.project_id}/test-suites/{fixture.suite_id}/runs"
    response = await fixture.context.client.get(
        path, headers=fixture.headers, params={"page": 3, "page_size": 20}
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 41
    assert len(response.json()["items"]) == 1
    oldest = response.json()["items"][0]
    assert oldest["run"]["id"] == str(fixture.oldest_run_id)
    assert oldest["items"][0]["workflow_execution_id"] == str(fixture.oldest_execution_id)
    filtered = await fixture.context.client.get(
        path, headers=fixture.headers, params={"version": 1, "page_size": 100}
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 31
    assert all(
        item["target_snapshot"]["source_suite"] == {"id": fixture.suite_id, "version": 1}
        for entry in filtered.json()["items"]
        for item in entry["items"]
    )
    latest = await fixture.context.client.get(
        f"/api/v1/projects/{fixture.project_id}/test-suites/runs/latest",
        headers=fixture.headers,
        params={"suite_ids": fixture.suite_id},
    )
    assert latest.status_code == 200, latest.text
    assert latest.json()[0]["suite_id"] == fixture.suite_id
    assert latest.json()[0]["detail"]["items"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_asset_history_rejects_other_project_assets_and_invalid_version(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    client = fixture.context.client
    other = await client.post(
        "/api/v1/projects", headers=fixture.headers, json={"name": "其他历史项目"}
    )
    for resource, asset_id in (("test-cases", fixture.case_id), ("test-suites", fixture.suite_id)):
        denied = await client.get(
            f"/api/v1/projects/{other.json()['id']}/{resource}/{asset_id}/runs",
            headers=fixture.headers,
        )
        assert denied.status_code == 404, denied.text
        assert denied.json()["error"]["trace_id"]
        invalid = await client.get(
            f"/api/v1/projects/{fixture.project_id}/{resource}/{asset_id}/runs",
            headers=fixture.headers,
            params={"version": 0},
        )
        assert invalid.status_code == 422, invalid.text


@pytest.mark.asyncio
async def test_asset_deletion_preview_protects_references_and_bulk_is_atomic(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    client = fixture.context.client
    path = f"/api/v1/projects/{fixture.project_id}/test-cases"
    clone = await client.post(
        f"{path}/{fixture.case_id}/clone", headers=fixture.headers, json={"name": "可移除副本"}
    )
    clone_id = clone.json()["id"]
    preview = await client.post(
        f"{path}/deletion-preview",
        headers=fixture.headers,
        json={"asset_ids": [clone_id, fixture.case_id]},
    )
    assert preview.status_code == 200, preview.text
    targets = preview.json()["targets"]
    assert {item["asset"]["id"] for item in targets} == {clone_id, fixture.case_id}
    original = next(item for item in targets if item["asset"]["id"] == fixture.case_id)
    assert {item["kind"] for item in original["references"]} >= {"test_suite", "test_plan"}
    assert next(item for item in targets if item["asset"]["id"] == clone_id)["references"] == []
    deleted = await client.post(
        f"{path}/bulk-delete",
        headers=fixture.headers,
        json={"assets": [item["asset"] for item in targets]},
    )
    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["error"]["code"] == "TEST_ASSET_IN_USE"
    assert (await client.get(f"{path}/{clone_id}", headers=fixture.headers)).json()[
        "archived_at"
    ] is None
    assert (await client.get(f"{path}/{fixture.case_id}", headers=fixture.headers)).json()[
        "archived_at"
    ] is None
    duplicate = await client.post(
        f"{path}/deletion-preview",
        headers=fixture.headers,
        json={"asset_ids": [clone_id, clone_id]},
    )
    assert duplicate.status_code == 422, duplicate.text


@pytest.mark.asyncio
async def test_asset_deletion_rechecks_drafts_and_retains_published_versions(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    client = fixture.context.client
    path = f"/api/v1/projects/{fixture.project_id}/test-cases"
    cloned = await client.post(
        f"{path}/{fixture.case_id}/clone", headers=fixture.headers, json={"name": "历史保留副本"}
    )
    case_id = cloned.json()["id"]
    published = await client.post(f"{path}/{case_id}/versions", headers=fixture.headers, json={})
    assert published.status_code == 200, published.text
    preview = await client.post(
        f"{path}/deletion-preview", headers=fixture.headers, json={"asset_ids": [case_id]}
    )
    assert preview.status_code == 200, preview.text
    old_target = preview.json()["targets"][0]["asset"]
    changed = await client.patch(
        f"{path}/{case_id}", headers=fixture.headers, json={"name": "更名后的副本"}
    )
    assert changed.status_code == 200, changed.text
    stale = await client.request(
        "DELETE", f"{path}/{case_id}", headers=fixture.headers, json=old_target
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "TEST_ASSET_DELETE_STALE"
    fresh = await client.post(
        f"{path}/deletion-preview", headers=fixture.headers, json={"asset_ids": [case_id]}
    )
    deleted = await client.request(
        "DELETE",
        f"{path}/{case_id}",
        headers=fixture.headers,
        json=fresh.json()["targets"][0]["asset"],
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["archived_ids"] == [case_id]
    assert deleted.json()["historical_data_retained"] is True
    listing = await client.get(path, headers=fixture.headers)
    assert case_id not in {item["id"] for item in listing.json()["items"]}
    retained = await client.get(f"{path}/{case_id}/versions", headers=fixture.headers)
    assert retained.status_code == 200 and retained.json()[0]["id"] == published.json()["id"]
    metadata = await client.get(f"{path}/{case_id}", headers=fixture.headers)
    assert metadata.json()["archived_at"] is not None
    editing = await client.patch(
        f"{path}/{case_id}", headers=fixture.headers, json={"name": "不能编辑"}
    )
    assert editing.status_code == 409 and editing.json()["error"]["code"] == "TEST_ASSET_ARCHIVED"
    running = await client.post(
        f"{path}/{case_id}/runs",
        headers={**fixture.headers, "Idempotency-Key": "archived-case"},
        json={"source": "published", "version": 1},
    )
    assert running.status_code == 409 and running.json()["error"]["code"] == "TEST_ASSET_ARCHIVED"


@pytest.mark.asyncio
async def test_suite_deletion_preserves_history_after_live_references_are_removed(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    client = fixture.context.client
    path = f"/api/v1/projects/{fixture.project_id}/test-suites"
    blocked = await client.post(
        f"{path}/deletion-preview", headers=fixture.headers, json={"asset_ids": [fixture.suite_id]}
    )
    assert blocked.status_code == 200, blocked.text
    assert {item["kind"] for item in blocked.json()["targets"][0]["references"]} >= {
        "test_plan",
        "execution",
    }
    async with fixture.context.session_maker() as session:
        items = (await session.scalars(select(tasking_models.TestPlanItem))).all()
        for item in items:
            await session.delete(item)
        runs = (
            await session.scalars(
                select(tasking_models.TestPlanRun).where(
                    tasking_models.TestPlanRun.status == "queued"
                )
            )
        ).all()
        for run in runs:
            run.status = "cancelled"
        await session.commit()
    fresh = await client.post(
        f"{path}/deletion-preview", headers=fixture.headers, json={"asset_ids": [fixture.suite_id]}
    )
    assert fresh.json()["targets"][0]["references"] == []
    deleted = await client.post(
        f"{path}/bulk-delete",
        headers=fixture.headers,
        json={"assets": [fresh.json()["targets"][0]["asset"]]},
    )
    assert deleted.status_code == 200, deleted.text
    history = await client.get(f"{path}/{fixture.suite_id}/runs", headers=fixture.headers)
    assert history.status_code == 200 and history.json()["total"] == 41
    versions = await client.get(f"{path}/{fixture.suite_id}/versions", headers=fixture.headers)
    assert [item["version"] for item in versions.json()] == [2, 1]


@pytest.mark.asyncio
async def test_asset_deletion_checks_project_permissions_and_exact_selection(
    asset_history_fixture: AssetHistoryFixture,
) -> None:
    fixture = asset_history_fixture
    client = fixture.context.client
    created = await client.post(
        "/api/v1/users",
        headers=fixture.headers,
        json={
            "email": "asset-viewer@example.com",
            "display_name": "资产只读成员",
            "password": ADMIN_PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    member = await client.put(
        f"/api/v1/projects/{fixture.project_id}/members/{created.json()['id']}",
        headers=fixture.headers,
        json={"user_id": created.json()["id"], "role": "viewer"},
    )
    assert member.status_code == 200, member.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": "asset-viewer@example.com", "password": ADMIN_PASSWORD}
    )
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=viewer_headers,
        json={
            "current_password": ADMIN_PASSWORD,
            "new_password": "asset-viewer-updated-123!",
        },
    )
    assert changed.status_code == 204, changed.text
    path = f"/api/v1/projects/{fixture.project_id}/test-cases"
    preview = await client.post(
        f"{path}/deletion-preview", headers=viewer_headers, json={"asset_ids": [fixture.case_id]}
    )
    assert preview.status_code == 403, preview.text
    assert preview.json()["error"]["code"] == "PROJECT_FORBIDDEN"
    foreign = await client.post(
        "/api/v1/projects", headers=fixture.headers, json={"name": "隔离删除项目"}
    )
    denied = await client.post(
        f"/api/v1/projects/{foreign.json()['id']}/test-cases/deletion-preview",
        headers=fixture.headers,
        json={"asset_ids": [fixture.case_id]},
    )
    assert denied.status_code == 404 and denied.json()["error"]["trace_id"]
    mixed = await client.post(
        f"{path}/deletion-preview",
        headers=fixture.headers,
        json={"asset_ids": [fixture.case_id, str(uuid4())]},
    )
    assert mixed.status_code == 404, mixed.text


@pytest.mark.asyncio
async def test_asset_directory_filters_pages_and_counts_the_complete_filtered_catalog(
    tasking_context: TaskingTestContext,
) -> None:
    client = tasking_context.client
    headers = await _login_headers(client)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    root = f"/api/v1/projects/{project_id}"
    folders = []
    for name in ("规模目录甲", "规模目录乙"):
        response = await client.post(f"{root}/folders", headers=headers, json={"name": name})
        assert response.status_code == 201, response.text
        folders.append(UUID(response.json()["id"]))
    folders.append(None)
    definition = {
        "workflow_id": workflow_id,
        "workflow_version": 1,
        "environment_id": environment_id,
        "runtime_variables": {},
        "runtime_headers": {},
    }
    async with tasking_context.session_maker() as session:
        actor = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert actor is not None
        cases = [
            test_asset_models.TestCase(
                id=uuid4(),
                project_id=UUID(project_id),
                folder_id=folders[index % 3],
                name=f"规模用例 {index}",
                tags=["回归", "规模"] if index % 2 == 0 else ["规模扩展"],
                draft_definition=definition,
                current_version=1 if index in {0, 2} else None,
                archived_at=datetime.now(UTC) if index >= 126 else None,
                created_by_id=actor.id,
            )
            for index in range(128)
        ]
        session.add_all(cases)
        session.add_all(
            [
                test_asset_models.TestCaseVersion(
                    test_case_id=cases[index].id,
                    version=1,
                    definition=definition,
                    fingerprint=definition_fingerprint(definition),
                    created_by_id=actor.id,
                )
                for index in (0, 2)
            ]
        )
        session.add_all(
            [
                test_asset_models.TestSuite(
                    project_id=UUID(project_id),
                    folder_id=folders[index % 3],
                    name=f"规模套件 {index}",
                    tags=["规模"] if index % 2 == 0 else ["规模扩展"],
                    draft_definition={
                        "items": [{"test_case_id": str(cases[0].id), "test_case_version": 1}]
                    },
                    archived_at=datetime.now(UTC) if index == 63 else None,
                    created_by_id=actor.id,
                )
                for index in range(64)
            ]
        )
        await session.commit()
    filtered = await client.get(
        f"{root}/test-cases",
        headers=headers,
        params={"folder_id": str(folders[0]), "page": 3, "page_size": 20},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 42 and len(filtered.json()["items"]) == 2
    assert {row["folder_id"] for row in filtered.json()["items"]} == {str(folders[0])}
    unfiled = await client.get(
        f"{root}/test-cases", headers=headers, params={"unfiled": True, "page_size": 100}
    )
    assert unfiled.json()["total"] == 42 and all(
        row["folder_id"] is None for row in unfiled.json()["items"]
    )
    suites = await client.get(
        f"{root}/test-suites",
        headers=headers,
        params={"folder_id": str(folders[1]), "page": 2, "page_size": 20},
    )
    assert suites.json()["total"] == 21 and len(suites.json()["items"]) == 1
    counts = await client.get(
        f"{root}/test-assets/directory-counts", headers=headers, params={"search": "规模"}
    )
    assert counts.status_code == 200, counts.text
    assert counts.json()["case_total"] == 126 and counts.json()["suite_total"] == 63
    assert counts.json()["published_case_total"] == 2
    exact_tags = await client.get(
        f"{root}/test-assets/directory-counts",
        headers=headers,
        params={"search": "规模", "tag": "规模"},
    )
    assert exact_tags.status_code == 200, exact_tags.text
    assert exact_tags.json()["case_total"] == 63 and exact_tags.json()["suite_total"] == 32
    assert exact_tags.json()["unfiled_cases"] == 21 and exact_tags.json()["unfiled_suites"] == 11
    directory = {row["folder_id"]: row for row in exact_tags.json()["folders"]}
    assert directory[str(folders[0])]["cases"] == 21 and directory[str(folders[0])]["suites"] == 11
    tagged = await client.get(
        f"{root}/test-cases", headers=headers, params={"tag": "规模", "page_size": 100}
    )
    assert tagged.json()["total"] == 63 and all(
        "规模" in row["tags"] for row in tagged.json()["items"]
    )
    injection = await client.get(
        f"{root}/test-suites", headers=headers, params={"tag": "规模' OR 1=1 --"}
    )
    assert injection.json()["total"] == 0
    for resource in ("test-cases", "test-suites"):
        invalid = await client.get(
            f"{root}/{resource}",
            headers=headers,
            params={"folder_id": str(folders[0]), "unfiled": True},
        )
        assert invalid.status_code == 422 and invalid.json()["error"]["trace_id"]
        foreign = await client.get(
            f"{root}/{resource}", headers=headers, params={"folder_id": str(uuid4())}
        )
        assert foreign.status_code == 404, foreign.text
