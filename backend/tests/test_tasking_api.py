import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_test_plan_dispatcher, get_workflow_coordinator
from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.domain.tasking import webhook_signature
from app.main import app
from app.models import Base
from app.models.access import User
from app.services.execution_events import ExecutionEvent
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator

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

    def start_test_plan(self, run_id: UUID) -> None:
        self.test_plan_run_ids.append(run_id)


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
