import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_workflow_coordinator
from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.main import app
from app.models import Base
from app.models.access import User
from app.services.execution_events import ExecutionEvent
from app.services.workflow_coordinator import WorkflowRunCoordinator

ADMIN_EMAIL = "workflow-admin@example.com"
ADMIN_PASSWORD = "workflow-password-123!"


@pytest.fixture
async def workflow_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[AsyncClient]:
    storage = MemoryObjectStorage()
    monkeypatch.setattr("app.services.artifacts.object_storage", storage)
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'workflow.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Workflow administrator",
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
    coordinator = WorkflowRunCoordinator(session_maker, events)
    app.state.workflow_run_coordinator = coordinator
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workflow_coordinator] = lambda: coordinator
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client
    await coordinator.shutdown()
    app.dependency_overrides.clear()
    await test_engine.dispose()


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
async def test_workflow_draft_publish_snapshot_and_retry(workflow_client: AsyncClient) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    definition = _workflow_definition(api_id, max_retries=1)
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "订单流程", "description": "snapshot", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow = created.json()
    assert workflow["draft_revision"] == 1
    assert workflow["current_version"] is None

    conflict = await workflow_client.patch(
        f"/api/v1/projects/{project_id}/workflows/{workflow['id']}",
        headers=headers,
        json={"expected_revision": 2, "description": "stale"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["details"]["current_revision"] == 1

    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow['id']}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    version_one = published.json()
    assert version_one["version"] == 1

    updated_draft = _workflow_definition(api_id, max_retries=0)
    updated_draft["nodes"][1]["name"] = "已修改的草稿"
    saved = await workflow_client.patch(
        f"/api/v1/projects/{project_id}/workflows/{workflow['id']}",
        headers=headers,
        json={"expected_revision": 1, "definition": updated_draft},
    )
    assert saved.status_code == 200
    assert saved.json()["draft_revision"] == 2
    versions = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflows/{workflow['id']}/versions",
        headers=headers,
    )
    assert versions.json()[0]["definition"]["nodes"][1]["name"] == "查询用户"

    api_v2 = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis/{api_id}/versions",
        headers=headers,
        json={
            "method": "GET",
            "path": "/users/v2",
            "body_kind": "none",
            "auth": {
                "kind": "api_key",
                "values": {
                    "in": "header",
                    "name": "X-Snapshot-Key",
                    "value": "snapshot-api-key",
                },
            },
        },
    )
    assert api_v2.status_code == 201
    target = respx.get("http://workflow.example.com/users/v2").mock(
        side_effect=[Response(503, json={"error": "temporary"}), Response(200, json={"id": 7})]
    )
    executed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow['id']}/executions",
        headers=headers,
        json={"environment_id": environment_id, "version": 1},
    )
    assert executed.status_code == 202, executed.text
    detail = await _wait_for_completed_execution(
        workflow_client, headers, project_id, executed.json()["id"]
    )
    assert detail["execution"]["status"] == "passed"
    assert detail["nodes"][1]["attempts"] == 2
    assert detail["nodes"][1]["output"]["body"] == {"id": 7}
    assert len(target.calls) == 2
    snapshot = detail["execution"]["snapshot"]
    assert snapshot["workflow"]["version"] == 1
    assert snapshot["apis"]["api"]["version"] == 2
    assert snapshot["apis"]["api"]["prepared_request"]["url"].endswith("/users/v2")
    assert snapshot["apis"]["api"]["spec"]["auth_config"]["value"] == "***"
    assert "snapshot-api-key" not in json.dumps(detail)

    environment_changed = await workflow_client.patch(
        f"/api/v1/projects/{project_id}/environments/{environment_id}",
        headers=headers,
        json={"base_url": "http://changed.example.com"},
    )
    assert environment_changed.status_code == 200
    api_v3 = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis/{api_id}/versions",
        headers=headers,
        json={"method": "GET", "path": "/users/v3", "body_kind": "none"},
    )
    assert api_v3.status_code == 201
    history = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{detail['execution']['id']}",
        headers=headers,
    )
    assert history.status_code == 200
    historical_snapshot = history.json()["execution"]["snapshot"]
    assert historical_snapshot["environment"]["base_url"] == "http://workflow.example.com"
    assert historical_snapshot["apis"]["api"]["version"] == 2


@pytest.mark.asyncio
async def test_publish_rejects_invalid_or_cross_project_api_configuration(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, _environment_id, _api_id = await _create_assets(workflow_client, headers)
    missing_api = "00000000-0000-0000-0000-000000000099"
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "无效流程", "definition": _workflow_definition(missing_api)},
    )
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/versions",
        headers=headers,
    )
    assert published.status_code == 422
    assert published.json()["error"]["code"] == "WORKFLOW_API_NOT_FOUND"

    invalid_definition = _workflow_definition(missing_api)
    invalid_definition["nodes"][1]["config"] = {}
    invalid = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "配置缺失", "definition": invalid_definition},
    )
    rejected = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{invalid.json()['id']}/versions",
        headers=headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "INVALID_NODE_CONFIG"


@respx.mock
@pytest.mark.asyncio
async def test_running_workflow_can_be_cancelled(workflow_client: AsyncClient) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "取消流程", "definition": _workflow_definition(api_id)},
    )
    workflow_id = created.json()["id"]
    await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )

    async def slow_response(_request: Any) -> Response:
        await asyncio.sleep(5)
        return Response(200, json={"late": True})

    respx.get("http://workflow.example.com/users/v1").mock(side_effect=slow_response)
    running = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert running.status_code == 202, running.text
    execution_id = running.json()["id"]
    cancelled = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancel_requested_at"] is not None

    result = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert result["execution"]["status"] == "cancelled"
    assert result["nodes"][1]["status"] == "cancelled"

    interrupted = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert interrupted.status_code == 202
    await asyncio.sleep(0.1)
    await app.state.workflow_run_coordinator.shutdown()
    interrupted_result = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{interrupted.json()['id']}",
        headers=headers,
    )
    assert interrupted_result.status_code == 200
    assert interrupted_result.json()["execution"]["status"] == "cancelled"
    assert interrupted_result.json()["nodes"][1]["status"] == "cancelled"


@respx.mock
@pytest.mark.asyncio
async def test_dataset_execution_maps_rows_and_explains_condition_branches(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, _api_id = await _create_assets(workflow_client, headers)
    dataset = await workflow_client.post(
        f"/api/v1/projects/{project_id}/files",
        headers=headers,
        files={
            "file": (
                "users.json",
                json.dumps(
                    [
                        {"email": "enabled@example.com", "enabled": "true"},
                        {"email": "disabled@example.com", "enabled": "false"},
                    ]
                ).encode(),
                "application/json",
            )
        },
    )
    assert dataset.status_code == 201, dataset.text
    source_api = await _create_api_definition(
        workflow_client,
        headers,
        project_id,
        name="Dataset source",
        path="/dataset-source",
        body={"email": "{{email}}", "enabled": "{{enabled}}"},
    )
    target_api = await _create_api_definition(
        workflow_client,
        headers,
        project_id,
        name="Mapped target",
        path="/mapped-target",
        body={"email": ""},
    )
    definition = _dataset_workflow_definition(
        dataset.json()["id"],
        source_api,
        target_api,
    )
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "数据驱动流程", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text

    received: list[dict[str, Any]] = []

    def echo_source(request: Any) -> Response:
        return Response(200, json=json.loads(request.content))

    def capture_target(request: Any) -> Response:
        body = json.loads(request.content)
        received.append(body)
        return Response(200, json=body)

    respx.post("http://workflow.example.com/dataset-source").mock(side_effect=echo_source)
    respx.post("http://workflow.example.com/mapped-target").mock(side_effect=capture_target)
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    assert started.json()["parent_execution_id"] is None
    detail = await _wait_for_completed_execution(
        workflow_client, headers, project_id, started.json()["id"]
    )

    assert detail["execution"]["status"] == "passed"
    assert detail["execution"]["context"]["dataset_summary"] == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "cancelled": 0,
    }
    assert [child["dataset_row_index"] for child in detail["children"]] == [0, 1]
    assert {item["email"] for item in received} == {
        "enabled@example.com",
        "disabled@example.com",
    }
    child_details = [
        (
            await workflow_client.get(
                f"/api/v1/projects/{project_id}/workflow-executions/{child['id']}",
                headers=headers,
            )
        ).json()
        for child in detail["children"]
    ]
    for child in child_details:
        statuses = {node["node_id"]: node["status"] for node in child["nodes"]}
        assert sorted(statuses[node_id] for node_id in ("true-delay", "false-delay")) == [
            "passed",
            "skipped",
        ]
        mapped = next(node for node in child["nodes"] if node["node_id"] == "target")
        assert mapped["output"]["input_mappings"][0]["target_key"] == "email"


@respx.mock
@pytest.mark.asyncio
async def test_dataset_parent_cancellation_reaches_active_and_queued_rows(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    dataset = await workflow_client.post(
        f"/api/v1/projects/{project_id}/files",
        headers=headers,
        files={
            "file": (
                "cancel.json",
                json.dumps([{"row": index} for index in range(6)]).encode(),
                "application/json",
            )
        },
    )
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "取消数据集流程",
            "definition": _dataset_cancel_definition(dataset.json()["id"], api_id),
        },
    )
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text

    async def slow_response(_request: Any) -> Response:
        await asyncio.sleep(5)
        return Response(200, json={"late": True})

    respx.get("http://workflow.example.com/users/v1").mock(side_effect=slow_response)
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    execution_id = started.json()["id"]
    requested = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/cancel",
        headers=headers,
    )
    assert requested.status_code == 200, requested.text
    detail = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert detail["execution"]["status"] == "cancelled", detail
    assert len(detail["children"]) == 6
    assert {child["status"] for child in detail["children"]} == {"cancelled"}


async def _wait_for_completed_execution(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    execution_id: str,
) -> dict[str, Any]:
    await app.state.workflow_run_coordinator.wait_for(UUID(execution_id))
    for _attempt in range(100):
        response = await client.get(
            f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}",
            headers=headers,
        )
        if response.status_code == 200 and response.json()["execution"]["status"] != "running":
            return dict(response.json())
        await asyncio.sleep(0.01)
    raise AssertionError("workflow execution did not complete")


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    async def publish(self, event: ExecutionEvent) -> ExecutionEvent:
        stored = event.model_copy(update={"sequence": len(self.events) + 1})
        self.events.append(stored)
        return stored


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_assets(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    project = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Workflow project"},
    )
    project_id = project.json()["id"]
    environment = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "Workflow target", "base_url": "http://workflow.example.com"},
    )
    definition = await client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "User API",
            "request": {
                "method": "GET",
                "path": "/users/v1",
                "body_kind": "none",
                "auth": {
                    "kind": "api_key",
                    "values": {
                        "in": "header",
                        "name": "X-Snapshot-Key",
                        "value": "snapshot-api-key",
                    },
                },
            },
        },
    )
    assert definition.status_code == 201, definition.text
    return project_id, environment.json()["id"], definition.json()["definition"]["id"]


def _workflow_definition(api_id: str, *, max_retries: int = 0) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "api",
                "type": "api",
                "name": "查询用户",
                "position": {"x": 100, "y": 0},
                "config": {"api_definition_id": api_id, "max_retries": max_retries},
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "start-api", "source": "start", "target": "api"},
            {"id": "api-end", "source": "api", "target": "end"},
        ],
    }


async def _create_api_definition(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    name: str,
    path: str,
    body: dict[str, Any],
) -> str:
    created = await client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": name,
            "request": {
                "method": "POST",
                "path": path,
                "body_kind": "json",
                "body": body,
            },
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["definition"]["id"])


def _dataset_workflow_definition(
    artifact_id: str,
    source_api_id: str,
    target_api_id: str,
) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "dataset",
                "type": "dataset",
                "name": "用户数据",
                "position": {"x": 100, "y": 0},
                "config": {"artifact_id": artifact_id, "format": "json"},
            },
            {
                "id": "source",
                "type": "api",
                "name": "读取数据行",
                "position": {"x": 200, "y": 0},
                "config": {"api_definition_id": source_api_id},
            },
            {
                "id": "extract",
                "type": "extract",
                "name": "提取邮箱",
                "position": {"x": 300, "y": 0},
                "config": {
                    "source_node_id": "source",
                    "expression": "body.email",
                    "variable": "selected_email",
                },
            },
            {
                "id": "target",
                "type": "api",
                "name": "映射邮箱",
                "position": {"x": 400, "y": 0},
                "config": {"api_definition_id": target_api_id},
            },
            {
                "id": "assert",
                "type": "assert",
                "name": "校验响应",
                "position": {"x": 500, "y": 0},
                "config": {
                    "source_node_id": "target",
                    "expression": "status_code",
                    "operator": "equals",
                    "expected": 200,
                },
            },
            {
                "id": "condition",
                "type": "condition",
                "name": "判断启用状态",
                "position": {"x": 600, "y": 0},
                "config": {
                    "source_node_id": "source",
                    "expression": "body.enabled",
                    "operator": "equals",
                    "expected": "true",
                },
            },
            {
                "id": "true-delay",
                "type": "delay",
                "name": "启用分支",
                "position": {"x": 700, "y": -80},
                "config": {"seconds": 0},
            },
            {
                "id": "false-delay",
                "type": "delay",
                "name": "停用分支",
                "position": {"x": 700, "y": 80},
                "config": {"seconds": 0},
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 800, "y": 0}},
        ],
        "edges": [
            {"id": "start-dataset", "source": "start", "target": "dataset"},
            {"id": "dataset-source", "source": "dataset", "target": "source"},
            {"id": "source-extract", "source": "source", "target": "extract"},
            {
                "id": "extract-target",
                "source": "extract",
                "target": "target",
                "mappings": [
                    {
                        "source": {"node_id": "extract", "path": "value"},
                        "target": {
                            "node_id": "target",
                            "location": "body",
                            "key": "email",
                        },
                    }
                ],
            },
            {"id": "target-assert", "source": "target", "target": "assert"},
            {"id": "assert-condition", "source": "assert", "target": "condition"},
            {
                "id": "condition-true",
                "source": "condition",
                "target": "true-delay",
                "condition": "true",
            },
            {
                "id": "condition-false",
                "source": "condition",
                "target": "false-delay",
                "condition": "false",
            },
            {"id": "true-end", "source": "true-delay", "target": "end"},
            {"id": "false-end", "source": "false-delay", "target": "end"},
        ],
    }


def _dataset_cancel_definition(artifact_id: str, api_id: str) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "dataset",
                "type": "dataset",
                "name": "取消数据",
                "position": {"x": 100, "y": 0},
                "config": {"artifact_id": artifact_id, "format": "json"},
            },
            {
                "id": "api",
                "type": "api",
                "name": "慢请求",
                "position": {"x": 200, "y": 0},
                "config": {"api_definition_id": api_id},
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 300, "y": 0}},
        ],
        "edges": [
            {"id": "start-dataset", "source": "start", "target": "dataset"},
            {"id": "dataset-api", "source": "dataset", "target": "api"},
            {"id": "api-end", "source": "api", "target": "end"},
        ],
    }
