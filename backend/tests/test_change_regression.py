from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_test_plan_dispatcher, get_workflow_coordinator
from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.main import app
from app.models import Base
from app.models.access import User
from app.services.execution_events import ExecutionEvent
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator

ADMIN_EMAIL = "regression-admin@example.com"
ADMIN_PASSWORD = "regression-password-123!"


@dataclass(slots=True)
class RegressionContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    queue: "RecordingQueue"
    events: "RecordingEventBus"


@pytest.fixture
async def regression_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[RegressionContext]:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    monkeypatch.setattr("app.services.artifacts.object_storage", MemoryObjectStorage())
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'change-regression.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Regression administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    events = RecordingEventBus()
    coordinator = WorkflowRunCoordinator(sessions, events)
    queue = RecordingQueue()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workflow_coordinator] = lambda: coordinator
    app.dependency_overrides[get_test_plan_dispatcher] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield RegressionContext(client, sessions, queue, events)
    await coordinator.shutdown()
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
@respx.mock
async def test_change_to_release_gate_trace_and_missing_test_review(
    regression_context: RegressionContext,
) -> None:
    context = regression_context
    headers = await _login_headers(context.client)
    project_id, environment_id, workflow_id = await _create_workflow(context.client, headers)
    plan = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "S45 回归计划",
            "items": [{"workflow_id": workflow_id, "environment_id": environment_id}],
        },
    )
    assert plan.status_code == 201, plan.text
    policy = await context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json={
            "name": "S45 最小门禁",
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": True,
            "min_impact_coverage_percent": 100,
            "require_release_risk": False,
        },
    )
    assert policy.status_code == 201, policy.text
    mapping = await context.client.post(
        f"/api/v1/projects/{project_id}/impact/mappings",
        headers=headers,
        json={
            "source_kind": "git",
            "source_selector": "backend/*",
            "target_type": "workflow",
            "target_id": workflow_id,
        },
    )
    assert mapping.status_code == 201, mapping.text

    source_change = _git_diff("backend/orders.py")
    token_created = await context.client.post(
        f"/api/v1/projects/{project_id}/service-tokens",
        headers=headers,
        json={"name": "S45 GitHub Actions", "scopes": ["analyze:change-regression"]},
    )
    assert token_created.status_code == 201, token_created.text
    ci_headers = {
        "Authorization": f"Bearer {token_created.json()['token']}",
        "Idempotency-Key": "s45-ci-change-abc123",
    }
    ci_payload = {
        "title": "CI 订单变更回归",
        "source_ref": "github://acme/flowtest/pull/42",
        "candidate_ref": "commit:abc123",
        "git_diff": source_change,
        "test_plan_id": plan.json()["id"],
        "release_policy_id": policy.json()["id"],
    }
    missing_auth = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        json=ci_payload,
    )
    assert missing_auth.status_code == 401
    malformed_auth = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        headers={"Authorization": "Token malformed"},
        json=ci_payload,
    )
    assert malformed_auth.status_code == 401
    ci_created = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        headers=ci_headers,
        json=ci_payload,
    )
    assert ci_created.status_code == 201, ci_created.text
    ci_replayed = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        headers=ci_headers,
        json=ci_payload,
    )
    assert ci_replayed.status_code == 201, ci_replayed.text
    assert ci_replayed.json()["id"] == ci_created.json()["id"]
    listed = await context.client.get(
        f"/api/v1/projects/{project_id}/change-regressions", headers=headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    detail = await context.client.get(
        f"/api/v1/projects/{project_id}/change-regressions/{ci_created.json()['id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == ci_created.json()["id"]

    created = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions",
        headers=headers,
        json={
            "title": "订单变更回归",
            "source_ref": "github://acme/flowtest/commit/abc123",
            "candidate_ref": "commit:abc123",
            "git_diff": source_change,
            "test_plan_id": plan.json()["id"],
            "release_policy_id": policy.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "review_required"
    assert run["change_set_id"] is None
    assert [stage["stage"] for stage in run["stages"]] == [
        "change",
        "impact",
        "regression_selection",
        "missing_test",
        "review",
    ]
    approved = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{run['id']}/approve",
        headers=headers,
        json={"note": "已确认选择范围"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    queued = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{run['id']}/execute",
        headers=headers,
    )
    assert queued.status_code == 202, queued.text
    test_plan_run_id = UUID(queued.json()["test_plan_run_id"])
    assert context.queue.test_plan_run_ids == [test_plan_run_id]
    respx.get("http://workflow.example.com/users/v1").mock(
        return_value=Response(200, json={"id": 7})
    )
    await PlanRunCoordinator(context.sessions, context.events).run(test_plan_run_id)
    decision = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{run['id']}/release-gate",
        headers=headers,
    )
    assert decision.status_code == 200, decision.text
    final = decision.json()
    assert final["status"] == "passed"
    assert final["release_decision_id"]
    assert final["evidence"]["impact"]["run_id"] == final["impact_run_id"]
    assert {stage["stage"] for stage in final["stages"]} >= {
        "execution",
        "evidence",
        "release_gate",
    }

    missing = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions",
        headers=headers,
        json={
            "title": "未映射变更回归",
            "source_ref": "github://acme/flowtest/commit/def456",
            "candidate_ref": "commit:def456",
            "git_diff": _git_diff("docs/unmapped.md"),
            "test_plan_id": plan.json()["id"],
            "release_policy_id": policy.json()["id"],
        },
    )
    assert missing.status_code == 201, missing.text
    missing_body = missing.json()
    assert missing_body["change_set_id"]
    assert len(missing_body["missing_tests"]) == 1
    item_id = missing_body["missing_tests"][0]["item_id"]
    reviewed = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{missing_body['id']}"
        f"/change-set-items/{item_id}/accept",
        headers=headers,
        json={"note": "低置信度草案已人工确认"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["missing_tests"][0]["review_status"] == "accepted"
    assert reviewed.json()["missing_tests"][0]["materialized_resource_type"] == "test_design"
    approved_missing = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{missing_body['id']}/approve",
        headers=headers,
        json={"note": "批准补齐测试设计"},
    )
    assert approved_missing.status_code == 200, approved_missing.text
    assert approved_missing.json()["status"] == "approved"


class RecordingQueue:
    def __init__(self) -> None:
        self.test_plan_run_ids: list[UUID] = []

    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        del queue_name, priority
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


async def _create_workflow(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    project = await client.post(
        "/api/v1/projects", headers=headers, json={"name": "S45 项目", "description": ""}
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    environment = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "S45 环境", "base_url": "http://workflow.example.com"},
    )
    api = await client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "S45 API",
            "request": {"method": "GET", "path": "/users/v1", "body_kind": "none"},
        },
    )
    api_id = api.json()["definition"]["id"]
    workflow = await client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "S45 流程", "definition": _workflow_definition(api_id)},
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


def _git_diff(path: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
