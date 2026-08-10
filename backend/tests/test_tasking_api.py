import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

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
from app.main import app
from app.models import Base
from app.models.access import User
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
