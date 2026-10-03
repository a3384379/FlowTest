import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_workflow_coordinator
from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.durable_execution import ExecutionCheckpoint
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution
from app.services.execution_events import ExecutionEvent
from app.services.workflow_coordinator import WorkflowRunCoordinator

pytestmark = pytest.mark.redaction_on


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
async def test_native_workflow_export_import_preserves_inline_control_and_runs(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    definition = {
        "schema_version": "4.0",
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "group",
                "type": "capability",
                "name": "步骤组",
                "position": {"x": 320, "y": 0},
                "capability_id": "flow.control.group",
                "capability_version": "1.0.0",
                "configuration": {"body": {"kind": "inline", "region_id": "body"}},
                "bindings": [],
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 640, "y": 0}},
        ],
        "edges": [
            {"id": "start-group", "source": "start", "target": "group"},
            {"id": "group-end", "source": "group", "target": "end"},
        ],
        "regions": [
            {
                "id": "body",
                "owner_node_id": "group",
                "role": "body",
                "nodes": [
                    {
                        "id": "choice",
                        "type": "capability",
                        "name": "分支",
                        "position": {"x": 0, "y": 0},
                        "capability_id": "flow.control.if",
                        "capability_version": "1.0.0",
                        "configuration": {
                            "condition": {
                                "kind": "compare",
                                "left": {"kind": "literal", "value": 4},
                                "operator": "equals",
                                "right": {"kind": "literal", "value": 4},
                            },
                            "true_body": {"kind": "inline", "region_id": "true"},
                            "false_body": {"kind": "inline", "region_id": "false"},
                            "policy": {"timeout_seconds": 45},
                        },
                        "bindings": [{"input": "marker", "expression": "literal"}],
                    }
                ],
                "entry_node_id": "choice",
                "exit_node_ids": ["choice"],
            },
            {
                "id": "true",
                "owner_node_id": "choice",
                "role": "true",
                "nodes": [
                    {
                        "id": "api",
                        "type": "api",
                        "name": "查询用户",
                        "position": {"x": 0, "y": 0},
                        "config": {"api_definition_id": api_id, "api_version": 1},
                    }
                ],
                "entry_node_id": "api",
                "exit_node_ids": ["api"],
                "outputs": {"selected": {"kind": "literal", "value": "true"}},
            },
            {
                "id": "false",
                "owner_node_id": "choice",
                "role": "false",
                "nodes": [
                    {
                        "id": "delay",
                        "type": "delay",
                        "name": "跳过接口",
                        "position": {"x": 0, "y": 0},
                        "config": {"seconds": 0},
                    }
                ],
                "entry_node_id": "delay",
                "exit_node_ids": ["delay"],
            },
        ],
        "run_policy": {"request_budget": 5, "max_runtime_seconds": 90},
    }
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "原生定义源", "definition": definition},
    )
    assert created.status_code == 201, created.text
    exported = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/native-export",
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    document = exported.json()
    assert document["format_version"] == "flowtest-workflow-native-v1"
    assert document["definition"] == created.json()["draft_definition"]
    assert [region["id"] for region in document["definition"]["regions"]] == [
        "body",
        "true",
        "false",
    ]
    assert document["definition"]["regions"][0]["nodes"][0]["bindings"] == [
        {"input": "marker", "expression": "literal"}
    ]

    imported = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/native-import",
        headers=headers,
        json={**document, "name": "原生定义副本"},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["draft_definition"] == document["definition"]
    assert imported.json()["current_version"] is None
    copied_id = imported.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{copied_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    target = respx.get("http://workflow.example.com/users/v1").mock(
        return_value=Response(200, json={"id": 7})
    )
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{copied_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    detail = await _wait_for_completed_execution(
        workflow_client, headers, project_id, started.json()["id"]
    )
    assert detail["execution"]["status"] == "passed"
    assert len(target.calls) == 1


@pytest.mark.asyncio
async def test_native_workflow_import_rejects_unknown_fields_and_missing_project_refs(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, _environment_id, api_id = await _create_assets(workflow_client, headers)
    document = {
        "format_version": "flowtest-workflow-native-v1",
        "name": "无效导入",
        "definition": _workflow_definition(api_id),
    }
    path = f"/api/v1/projects/{project_id}/workflows/native-import"
    unknown = await workflow_client.post(
        path, headers=headers, json={**document, "ignored_field": True}
    )
    assert unknown.status_code == 422
    missing = await workflow_client.post(
        path,
        headers=headers,
        json={
            **document,
            "definition": _workflow_definition("00000000-0000-0000-0000-000000000099"),
        },
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "WORKFLOW_API_NOT_FOUND"
    listed = await workflow_client.get(f"/api/v1/projects/{project_id}/workflows", headers=headers)
    assert listed.json()["total"] == 0


@pytest.mark.asyncio
async def test_atomic_control_block_insert_rejects_stale_and_invalid_edits(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, _environment_id, _api_id = await _create_assets(workflow_client, headers)
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "原子控制块",
            "definition": {
                "nodes": [
                    {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
                    {"id": "end", "type": "end", "name": "结束", "position": {"x": 400, "y": 0}},
                ],
                "edges": [{"id": "s-e", "source": "start", "target": "end"}],
            },
        },
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    path = f"/api/v1/projects/{project_id}/workflows/{workflow_id}/control-blocks"
    payload = {
        "expected_revision": 1,
        "edge_id": "s-e",
        "request_budget": 20,
        "node": {
            "id": "group",
            "type": "capability",
            "name": "步骤组",
            "position": {"x": 200, "y": 0},
            "capability_id": "flow.control.group",
            "capability_version": "1.0.0",
            "configuration": {"body": {"kind": "inline", "region_id": "body"}},
            "bindings": [],
        },
        "regions": [
            {
                "id": "body",
                "owner_node_id": "group",
                "role": "body",
                "nodes": [
                    {
                        "id": "wait",
                        "type": "delay",
                        "name": "等待",
                        "position": {"x": 0, "y": 0},
                        "config": {"seconds": 0},
                    }
                ],
                "entry_node_id": "wait",
                "exit_node_ids": ["wait"],
            }
        ],
    }
    missing_budget = await workflow_client.post(
        path, headers=headers, json={**payload, "request_budget": None}
    )
    assert missing_budget.status_code == 422
    assert missing_budget.json()["error"]["code"] == "CONTROL_BLOCK_INSERT_INVALID"
    assert (
        await workflow_client.get(path.removesuffix("/control-blocks"), headers=headers)
    ).json()["draft_revision"] == 1
    wrong_owner = {
        **payload,
        "regions": [{**payload["regions"][0], "owner_node_id": "other"}],
    }
    invalid = await workflow_client.post(path, headers=headers, json=wrong_owner)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "CONTROL_BLOCK_INSERT_INVALID"
    assert (
        await workflow_client.get(path.removesuffix("/control-blocks"), headers=headers)
    ).json()["draft_revision"] == 1

    inserted = await workflow_client.post(path, headers=headers, json=payload)
    assert inserted.status_code == 200, inserted.text
    draft = inserted.json()
    assert draft["draft_revision"] == 2
    assert draft["draft_definition"]["schema_version"] == "4.0"
    assert draft["draft_definition"]["run_policy"]["request_budget"] == 20
    assert [edge["source"] for edge in draft["draft_definition"]["edges"]] == [
        "start",
        "group",
    ]
    assert draft["draft_definition"]["regions"][0]["owner_node_id"] == "group"

    stale = await workflow_client.post(path, headers=headers, json=payload)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "WORKFLOW_DRAFT_CONFLICT"
    assert (
        await workflow_client.get(path.removesuffix("/control-blocks"), headers=headers)
    ).json()["draft_revision"] == 2
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text


def _iteration_debug_definition(*, fail: bool = False) -> dict[str, Any]:
    definition = {
        "schema_version": "4.0",
        "run_policy": {"request_budget": 10, "max_runtime_seconds": 30},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "loop",
                "type": "capability",
                "name": "重复三轮",
                "position": {"x": 200, "y": 0},
                "capability_id": "flow.control.repeat",
                "capability_version": "1.0.0",
                "configuration": {
                    "count": 3,
                    "body": {"kind": "inline", "region_id": "body"},
                },
                "bindings": [],
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 400, "y": 0}},
        ],
        "edges": [
            {"id": "s-l", "source": "start", "target": "loop"},
            {"id": "l-e", "source": "loop", "target": "end"},
        ],
        "regions": [
            {
                "id": "body",
                "owner_node_id": "loop",
                "role": "body",
                "nodes": [
                    {
                        "id": "wait",
                        "type": "delay",
                        "name": "等待",
                        "position": {"x": 0, "y": 0},
                        "config": {"seconds": 0},
                    }
                ],
                "edges": [],
                "entry_node_id": "wait",
                "exit_node_ids": ["wait"],
            }
        ],
    }
    if fail:
        definition["regions"][0]["nodes"] = [
            {
                "id": "fail",
                "type": "capability",
                "name": "受控失败",
                "position": {"x": 0, "y": 0},
                "capability_id": "flow.control.fail",
                "capability_version": "1.0.0",
                "configuration": {"code": "DEBUG_CASE_FAIL", "message": "受控失败"},
                "bindings": [],
            }
        ]
        definition["regions"][0]["entry_node_id"] = "fail"
        definition["regions"][0]["exit_node_ids"] = ["fail"]
    return definition


@pytest.mark.asyncio
async def test_iteration_debug_pauses_steps_and_resumes_a_published_loop(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, _api_id = await _create_assets(workflow_client, headers)
    definition = _iteration_debug_definition()
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "逐轮调试", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    start = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/debug-sessions",
        headers=headers,
        json={
            "environment_id": environment_id,
            "version": 1,
            "loop_node_id": "loop",
            "pause_before_index": 1,
            "max_session_seconds": 30,
        },
    )
    assert start.status_code == 202, start.text
    execution_id = start.json()["execution"]["id"]
    path = f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/debug-session"

    async def wait_for_pause(reason: str) -> dict[str, Any]:
        for _ in range(100):
            response = await workflow_client.get(path, headers=headers)
            assert response.status_code == 200, response.text
            state = response.json()
            if state["status"] == "paused" and state["pause_reason"] == reason:
                return state
            await asyncio.sleep(0.02)
        pytest.fail(f"debug session did not pause for {reason}")

    paused = await wait_for_pause("before_iteration")
    assert paused["paused_input_index"] == 1
    assert paused["last_completed_index"] == 0
    command_path = f"{path}/commands"
    stale = await workflow_client.post(
        command_path,
        headers=headers,
        json={"action": "step", "expected_revision": paused["revision"] - 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "DEBUG_SESSION_REVISION_CONFLICT"
    stepped = await workflow_client.post(
        command_path,
        headers=headers,
        json={"action": "step", "expected_revision": paused["revision"]},
    )
    assert stepped.status_code == 200, stepped.text
    paused_again = await wait_for_pause("step_completed")
    assert paused_again["paused_input_index"] == 1
    assert paused_again["last_completed_index"] == 1
    resumed = await workflow_client.post(
        command_path,
        headers=headers,
        json={"action": "continue", "expected_revision": paused_again["revision"]},
    )
    assert resumed.status_code == 200, resumed.text
    detail = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert detail["execution"]["status"] == "passed", detail
    final = await workflow_client.get(path, headers=headers)
    assert final.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_iteration_debug_pauses_failed_iteration_before_final_failure(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, _api_id = await _create_assets(workflow_client, headers)
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "失败轮次调试", "definition": _iteration_debug_definition(fail=True)},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/debug-sessions",
        headers=headers,
        json={
            "environment_id": environment_id,
            "loop_node_id": "loop",
            "pause_before_index": 0,
            "pause_on_error": True,
            "max_session_seconds": 30,
        },
    )
    assert started.status_code == 202, started.text
    execution_id = started.json()["execution"]["id"]
    path = f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/debug-session"
    initial = await _wait_for_debug_pause(workflow_client, headers, path, "before_iteration")
    resumed = await workflow_client.post(
        f"{path}/commands",
        headers=headers,
        json={"action": "continue", "expected_revision": initial["revision"]},
    )
    assert resumed.status_code == 200, resumed.text
    failed_pause = await _wait_for_debug_pause(workflow_client, headers, path, "error")
    assert failed_pause["paused_input_index"] == 0
    assert failed_pause["last_completed_index"] == 0
    detail = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}", headers=headers
    )
    assert detail.json()["execution"]["status"] == "running"
    continued = await workflow_client.post(
        f"{path}/commands",
        headers=headers,
        json={"action": "continue", "expected_revision": failed_pause["revision"]},
    )
    assert continued.status_code == 200, continued.text
    finished = await _wait_for_completed_execution(
        workflow_client, headers, project_id, execution_id
    )
    assert finished["execution"]["status"] == "failed"
    assert (await workflow_client.get(path, headers=headers)).json()["status"] == "completed"


@pytest.mark.asyncio
async def test_iteration_debug_expiry_stops_paused_execution(
    workflow_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, _api_id = await _create_assets(workflow_client, headers)
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "调试超时", "definition": _iteration_debug_definition()},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/debug-sessions",
        headers=headers,
        json={
            "environment_id": environment_id,
            "loop_node_id": "loop",
            "pause_before_index": 0,
            "max_session_seconds": 30,
        },
    )
    assert started.status_code == 202, started.text
    execution_id = started.json()["execution"]["id"]
    path = f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/debug-session"
    await _wait_for_debug_pause(workflow_client, headers, path, "before_iteration")

    class AfterDeadline(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime.now(UTC) + timedelta(seconds=31)

    monkeypatch.setattr("app.services.workflow_debug.datetime", AfterDeadline)
    finished = await _wait_for_completed_execution(
        workflow_client, headers, project_id, execution_id
    )
    assert finished["execution"]["status"] == "failed"
    expired = await workflow_client.get(path, headers=headers)
    assert expired.json()["status"] == "expired"


async def _wait_for_debug_pause(
    client: AsyncClient, headers: dict[str, str], path: str, reason: str
) -> dict[str, Any]:
    for _ in range(100):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        state = response.json()
        if state["status"] == "paused" and state["pause_reason"] == reason:
            return state
        await asyncio.sleep(0.02)
    pytest.fail(f"debug session did not pause for {reason}")


@pytest.mark.asyncio
async def test_inline_control_block_publishes_runs_and_exposes_scoped_instance(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, _api_id = await _create_assets(workflow_client, headers)
    definition = {
        "schema_version": "4.0",
        "run_policy": {"request_budget": 10, "max_runtime_seconds": 30},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "loop",
                "type": "capability",
                "name": "集合遍历",
                "position": {"x": 200, "y": 0},
                "capability_id": "flow.control.foreach",
                "capability_version": "1.0.0",
                "configuration": {
                    "collection": {"kind": "literal", "value": [1, 2, 3]},
                    "body": {"kind": "inline", "region_id": "body"},
                    "policy": {"max_iterations": 3, "timeout_seconds": 30},
                },
                "bindings": [],
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 400, "y": 0}},
        ],
        "edges": [
            {"id": "s-l", "source": "start", "target": "loop"},
            {"id": "l-e", "source": "loop", "target": "end"},
        ],
        "regions": [
            {
                "id": "body",
                "owner_node_id": "loop",
                "role": "body",
                "nodes": [
                    {
                        "id": "wait",
                        "type": "delay",
                        "name": "等待",
                        "position": {"x": 0, "y": 0},
                        "config": {"seconds": 0},
                    }
                ],
                "edges": [],
                "entry_node_id": "wait",
                "exit_node_ids": ["wait"],
            }
        ],
    }
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "内联集合遍历", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    execution_id = started.json()["id"]
    detail = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert detail["execution"]["status"] == "passed"
    loop = next(node for node in detail["nodes"] if node["node_id"] == "loop")
    assert loop["output"]["completed_count"] == 3
    instance_id = loop["output"]["items"][1]["nodes"][0]["instance_id"]
    scoped = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/instances/{instance_id}",
        headers=headers,
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["node_id"] == instance_id
    assert scoped.json()["status"] == "passed"
    paged = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/instances",
        headers=headers,
        params={"page": 2, "page_size": 1},
    )
    assert paged.status_code == 200, paged.text
    assert paged.json()["total"] == 3
    assert len(paged.json()["items"]) == 1
    assert paged.json()["items"][0]["node_id"] in {
        item["nodes"][0]["instance_id"] for item in loop["output"]["items"]
    }
    replayed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/nodes/loop/replay",
        headers=headers,
    )
    assert replayed.status_code == 409, replayed.text
    assert replayed.json()["error"]["code"] == "CONTROL_REPLAY_REQUIRES_DERIVED_RUN"


@respx.mock
@pytest.mark.asyncio
async def test_failed_item_rerun_uses_original_frozen_collection_and_keeps_source(
    workflow_client: AsyncClient,
    tmp_path: Path,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    created_api = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "创建资源",
            "request": {"method": "POST", "path": "/users/create", "body_kind": "none"},
        },
    )
    assert created_api.status_code == 201, created_api.text
    create_api_id = created_api.json()["definition"]["id"]
    definition = _workflow_definition(api_id)
    definition["schema_version"] = "4.0"
    definition["run_policy"] = {"request_budget": 6}
    definition["nodes"].insert(
        2,
        {
            "id": "loop",
            "type": "capability",
            "name": "集合遍历",
            "position": {"x": 200, "y": 0},
            "capability_id": "flow.control.foreach",
            "capability_version": "1.0.0",
            "configuration": {
                "collection": {"kind": "node_output", "node_id": "api", "path": ["body", "items"]},
                "body": {"kind": "inline", "region_id": "body"},
                "policy": {
                    "max_iterations": 3,
                    "timeout_seconds": 30,
                    "on_error": "continue_collect",
                },
            },
            "bindings": [],
        },
    )
    definition["edges"] = [
        {"id": "start-api", "source": "start", "target": "api"},
        {"id": "api-loop", "source": "api", "target": "loop"},
        {"id": "loop-end", "source": "loop", "target": "end"},
    ]
    definition["regions"] = [
        {
            "id": "body",
            "owner_node_id": "loop",
            "role": "body",
            "nodes": [
                {
                    "id": "step",
                    "type": "api",
                    "name": "创建",
                    "position": {"x": 0, "y": 0},
                    "config": {"api_definition_id": create_api_id},
                },
                {
                    "id": "check",
                    "type": "assert",
                    "name": "失败校验",
                    "position": {"x": 100, "y": 0},
                    "config": {
                        "source_node_id": "step",
                        "expression": "status_code",
                        "operator": "equals",
                        "expected": 200,
                    },
                },
            ],
            "edges": [{"id": "step-check", "source": "step", "target": "check"}],
            "entry_node_id": "step",
            "exit_node_ids": ["check"],
        }
    ]
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "失败轮次派生", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    target = respx.get("http://workflow.example.com/users/v1").mock(
        side_effect=[
            Response(200, json={"items": ["a", "b", "c"]}),
            Response(200, json={"items": ["changed"]}),
        ]
    )
    create_target = respx.post("http://workflow.example.com/users/create").mock(
        return_value=Response(201, json={"id": "resource-1"})
    )
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    source_id = started.json()["id"]
    source = await _wait_for_completed_execution(workflow_client, headers, project_id, source_id)
    source_loop = next(node for node in source["nodes"] if node["node_id"] == "loop")
    assert [item["input_index"] for item in source_loop["output"]["items"]] == [0, 1, 2]
    assert source_loop["output"]["failed_count"] == 3
    assert len(target.calls) == 1
    assert len(create_target.calls) == 3
    report_path = f"/api/v1/projects/{project_id}/workflow-executions/{source_id}"
    compact = await workflow_client.get(
        report_path, headers=headers, params={"compact_control": "true"}
    )
    assert compact.status_code == 200, compact.text
    compact_loop = next(node for node in compact.json()["nodes"] if node["node_id"] == "loop")
    assert compact_loop["output"]["record_count"] == 3
    assert compact_loop["output"]["failed_count"] == 3
    assert "items" not in compact_loop["output"]
    assert "items" not in compact_loop["result"]["output"]
    assert "items" not in compact.json()["execution"]["context"]["node_outputs"]["loop"]
    page = await workflow_client.get(
        f"{report_path}/control-records",
        headers=headers,
        params={"node_id": "loop", "kind": "iteration", "page": 2, "page_size": 1},
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 3
    assert page.json()["items"] == [{"ordinal": 1, "status": "failed", "test_verdict": "failed"}]
    failed_page = await workflow_client.get(
        f"{report_path}/control-records",
        headers=headers,
        params={"node_id": "loop", "kind": "iteration", "test_verdict": "failed"},
    )
    assert failed_page.status_code == 200, failed_page.text
    assert failed_page.json()["total"] == 3
    exact = await workflow_client.get(
        f"{report_path}/control-records/iteration/1",
        headers=headers,
        params={"node_id": "loop"},
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["payload"]["input_index"] == 1
    foreign_project = await workflow_client.get(
        f"/api/v1/projects/{UUID(int=0)}/workflow-executions/{source_id}/control-records/iteration/1",
        headers=headers,
        params={"node_id": "loop"},
    )
    assert foreign_project.status_code in {403, 404}
    missing = await workflow_client.get(
        f"{report_path}/control-records/iteration/99",
        headers=headers,
        params={"node_id": "loop"},
    )
    assert missing.status_code == 404
    instance_id = source_loop["output"]["items"][1]["nodes"][0]["instance_id"]
    instance = await workflow_client.get(f"{report_path}/instances/{instance_id}", headers=headers)
    assert instance.status_code == 200, instance.text
    assert instance.json()["node_id"] == instance_id

    invalid_index = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{source_id}/failed-items/rerun",
        headers=headers,
        json={"loop_node_id": "loop", "input_indices": [99]},
    )
    assert invalid_index.status_code == 409, invalid_index.text
    assert invalid_index.json()["error"]["code"] == "RERUN_INPUT_NOT_FAILED"

    unverified = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{source_id}/failed-items/rerun",
        headers=headers,
        json={"loop_node_id": "loop", "input_indices": [1]},
    )
    assert unverified.status_code == 409, unverified.text
    assert unverified.json()["error"]["code"] == "RERUN_RESOURCE_VERIFICATION_REQUIRED"
    rerun = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{source_id}/failed-items/rerun",
        headers=headers,
        json={
            "loop_node_id": "loop",
            "input_indices": [1],
            "upstream_resource_status": "confirmed_valid",
            "verification_note": "已人工查证 resource-1 仍有效",
        },
    )
    assert rerun.status_code == 202, rerun.text
    derived_id = rerun.json()["id"]
    assert derived_id != source_id
    assert rerun.json()["derived_from_execution_id"] == source_id
    assert rerun.json()["rerun_input_indices"] == [1]
    derived = await _wait_for_completed_execution(workflow_client, headers, project_id, derived_id)
    derived_loop = next(node for node in derived["nodes"] if node["node_id"] == "loop")
    assert [item["input_index"] for item in derived_loop["output"]["items"]] == [1]
    assert derived_loop["output"]["input_count"] == 3
    derived_page = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{derived_id}/control-records",
        headers=headers,
        params={"node_id": "loop", "kind": "iteration"},
    )
    assert derived_page.status_code == 200, derived_page.text
    assert [item["ordinal"] for item in derived_page.json()["items"]] == [1]
    assert len(target.calls) == 1
    assert len(create_target.calls) == 3
    unchanged = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{source_id}", headers=headers
    )
    original_loop = next(node for node in unchanged.json()["nodes"] if node["node_id"] == "loop")
    assert len(original_loop["output"]["items"]) == 3
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workflow.db'}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            legacy_execution = await session.get(WorkflowExecution, UUID(source_id))
            assert legacy_execution is not None
            legacy_execution.context_summary = None
            legacy_loop = await session.scalar(
                select(WorkflowNodeExecution).where(
                    WorkflowNodeExecution.workflow_execution_id == UUID(source_id),
                    WorkflowNodeExecution.node_id == "loop",
                )
            )
            assert legacy_loop is not None
            legacy_loop.output_summary = None
            legacy_loop.result_summary = None
            await session.commit()
    finally:
        await engine.dispose()
    legacy = await workflow_client.get(
        report_path, headers=headers, params={"compact_control": "true"}
    )
    assert legacy.status_code == 200, legacy.text
    legacy_loop_report = next(node for node in legacy.json()["nodes"] if node["node_id"] == "loop")
    assert [item["input_index"] for item in legacy_loop_report["output"]["items"]] == [0, 1, 2]


@respx.mock
@pytest.mark.asyncio
async def test_failed_item_rerun_requires_explicit_write_retry_strategy(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, _api_id = await _create_assets(workflow_client, headers)
    created_api = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "提交资源",
            "request": {"method": "POST", "path": "/resource", "body_kind": "none"},
        },
    )
    assert created_api.status_code == 201, created_api.text
    submit_api_id = created_api.json()["definition"]["id"]
    definition = {
        "schema_version": "4.0",
        "run_policy": {"request_budget": 2},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "loop",
                "type": "capability",
                "name": "提交集合",
                "position": {"x": 100, "y": 0},
                "capability_id": "flow.control.foreach",
                "capability_version": "1.0.0",
                "configuration": {
                    "collection": {"kind": "literal", "value": [1]},
                    "body": {"kind": "inline", "region_id": "body"},
                    "policy": {"max_iterations": 1, "timeout_seconds": 30},
                },
                "bindings": [],
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "start-loop", "source": "start", "target": "loop"},
            {"id": "loop-end", "source": "loop", "target": "end"},
        ],
        "regions": [
            {
                "id": "body",
                "owner_node_id": "loop",
                "role": "body",
                "nodes": [
                    {
                        "id": "submit",
                        "type": "api",
                        "name": "提交",
                        "position": {"x": 0, "y": 0},
                        "config": {"api_definition_id": submit_api_id},
                    }
                ],
                "edges": [],
                "entry_node_id": "submit",
                "exit_node_ids": ["submit"],
            }
        ],
    }
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "失败写入派生", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    target = respx.post("http://workflow.example.com/resource").mock(
        side_effect=[Response(503), Response(200)]
    )
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    source_id = started.json()["id"]
    source = await _wait_for_completed_execution(workflow_client, headers, project_id, source_id)
    source_loop = next(node for node in source["nodes"] if node["node_id"] == "loop")
    assert source_loop["output"]["items"][0]["test_verdict"] == "failed"
    assert len(target.calls) == 1

    path = f"/api/v1/projects/{project_id}/workflow-executions/{source_id}/failed-items/rerun"
    blocked = await workflow_client.post(
        path, headers=headers, json={"loop_node_id": "loop", "input_indices": [0]}
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "RERUN_WRITE_VERIFICATION_REQUIRED"
    assert len(target.calls) == 1
    retry_payload = {
        "loop_node_id": "loop",
        "input_indices": [0],
        "write_retry_strategy": "verified_safe_to_retry",
        "verification_note": "已查证第一次写入没有生效",
    }
    retry_headers = {**headers, "Idempotency-Key": "verified-write-rerun"}
    allowed = await workflow_client.post(
        path,
        headers=retry_headers,
        json=retry_payload,
    )
    assert allowed.status_code == 202, allowed.text
    derived = await _wait_for_completed_execution(
        workflow_client, headers, project_id, allowed.json()["id"]
    )
    derived_loop = next(node for node in derived["nodes"] if node["node_id"] == "loop")
    assert derived_loop["output"]["items"][0]["test_verdict"] == "passed"
    assert len(target.calls) == 2
    replayed = await workflow_client.post(path, headers=retry_headers, json=retry_payload)
    assert replayed.status_code == 202, replayed.text
    assert replayed.json()["id"] == allowed.json()["id"]
    assert len(target.calls) == 2


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
    assert version_one["definition"]["nodes"][1]["config"]["api_version"] == 1

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
    target = respx.get("http://workflow.example.com/users/v1").mock(
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
    observations = detail["nodes"][1]["result"]["observations"]
    assert [item["attempt"] for item in observations] == [1, 2]
    assert [item["response"]["status_code"] for item in observations] == [503, 200]
    assert observations[1]["request"]["url"].endswith("/users/v1")
    assert set(observations[1]["request"]["headers"]["X-Snapshot-Key"]) == {"*"}
    assert observations[1]["duration_ms"] >= 0
    assert len(target.calls) == 2
    commands = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{detail['execution']['id']}/commands",
        headers=headers,
    )
    assert commands.status_code == 200, commands.text
    assert len(commands.json()) == 1
    assert commands.json()[0]["command_type"] == "start"
    assert commands.json()[0]["status"] == "completed"
    checkpoints = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{detail['execution']['id']}/checkpoints",
        headers=headers,
    )
    assert checkpoints.status_code == 200, checkpoints.text
    assert {item["node_id"] for item in checkpoints.json()} == {"start", "api", "end"}
    assert all(len(item["input_hash"]) == 64 for item in checkpoints.json())
    checkpoint_log_url = (
        f"/api/v1/projects/{project_id}/workflow-executions/"
        f"{detail['execution']['id']}/checkpoint-log"
    )
    first_log_page = await workflow_client.get(
        checkpoint_log_url, headers=headers, params={"page": 1, "page_size": 2}
    )
    second_log_page = await workflow_client.get(
        checkpoint_log_url, headers=headers, params={"page": 2, "page_size": 2}
    )
    assert first_log_page.status_code == 200, first_log_page.text
    assert second_log_page.status_code == 200, second_log_page.text
    assert first_log_page.json()["total"] == 4
    log_items = first_log_page.json()["items"] + second_log_page.json()["items"]
    assert {item["node_id"] for item in log_items} == {"start", "api", "end"}
    assert sorted(item["attempt"] for item in log_items if item["node_id"] == "api") == [1, 2]
    assert all("output" not in item and "result" not in item for item in log_items)
    assert len({item["id"] for item in log_items}) == 4
    log_detail = await workflow_client.get(
        f"{checkpoint_log_url}/{log_items[0]['id']}", headers=headers
    )
    assert log_detail.status_code == 200, log_detail.text
    assert log_detail.json()["id"] == log_items[0]["id"]
    assert "output" in log_detail.json() and "result" in log_detail.json()
    missing_log_entry = await workflow_client.get(
        f"{checkpoint_log_url}/00000000-0000-4000-8000-000000000099",
        headers=headers,
    )
    assert missing_log_entry.status_code == 404
    assert missing_log_entry.json()["error"]["code"] == "WORKFLOW_CHECKPOINT_NOT_FOUND"
    snapshot = detail["execution"]["snapshot"]
    assert snapshot["workflow"]["version"] == 1
    assert snapshot["workflow"]["name"] == "订单流程"
    assert snapshot["apis"]["api"]["version"] == 1
    assert snapshot["apis"]["api"]["prepared_request"]["url"].endswith("/users/v1")
    assert snapshot["apis"]["api"]["spec"]["auth_config"]["value"] == "***"
    assert "snapshot-api-key" not in json.dumps(detail)

    execution_list = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions",
        headers=headers,
        params={"workflow_id": workflow["id"]},
    )
    assert execution_list.status_code == 200
    assert [item["id"] for item in execution_list.json()["items"]] == [detail["execution"]["id"]]
    unrelated_list = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions",
        headers=headers,
        params={"workflow_id": "00000000-0000-4000-8000-000000000999"},
    )
    assert unrelated_list.status_code == 200
    assert unrelated_list.json()["items"] == []

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
    assert historical_snapshot["apis"]["api"]["version"] == 1


@respx.mock
@pytest.mark.asyncio
async def test_failed_workflow_resume_reuses_checkpoints_and_command_idempotency(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    definition = _workflow_definition(api_id)
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "可恢复流程", "definition": definition},
    )
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    target = respx.get("http://workflow.example.com/users/v1").mock(
        side_effect=[Response(500, json={"error": "temporary"}), Response(200, json={"id": 8})]
    )

    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers={**headers, "Idempotency-Key": "s43-start"},
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    execution_id = started.json()["id"]
    failed = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert failed["execution"]["status"] == "failed"

    resumed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/resume",
        headers={**headers, "Idempotency-Key": "s43-resume"},
    )
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["command"]["command_type"] == "resume"
    completed = await _wait_for_completed_execution(
        workflow_client, headers, project_id, execution_id
    )
    assert completed["execution"]["status"] == "passed"
    assert len(target.calls) == 2

    duplicate = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/resume",
        headers={**headers, "Idempotency-Key": "s43-resume"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["command"]["id"] == resumed.json()["command"]["id"]
    commands = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/commands",
        headers=headers,
    )
    assert [item["command_type"] for item in commands.json()] == ["resume", "start"]
    checkpoints = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/checkpoints",
        headers=headers,
    )
    api_checkpoints = [item for item in checkpoints.json() if item["node_id"] == "api"]
    assert [item["attempt"] for item in api_checkpoints] == [1, 2]
    assert [item["status"] for item in api_checkpoints] == ["failed", "passed"]


@respx.mock
@pytest.mark.asyncio
async def test_schema4_resume_keeps_unknown_post_outcome_and_does_not_resend(
    workflow_client: AsyncClient, tmp_path: Path
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    post_version = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis/{api_id}/versions",
        headers=headers,
        json={"method": "POST", "path": "/users/v2", "body_kind": "none"},
    )
    assert post_version.status_code == 201, post_version.text
    definition = _workflow_definition(api_id)
    definition["schema_version"] = "4.0"
    definition["run_policy"] = {"request_budget": 4}
    definition["nodes"][1]["config"]["api_version"] = 2
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "未知写入恢复", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    target = respx.post("http://workflow.example.com/users/v2").mock(
        return_value=Response(500, json={"error": "unavailable"})
    )
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    execution_id = started.json()["id"]
    first = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert first["execution"]["status"] == "failed"
    assert len(target.calls) == 1

    # Recreate the durable state left by a worker lost after its request reservation.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workflow.db'}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            checkpoint = await session.scalar(
                select(ExecutionCheckpoint).where(
                    ExecutionCheckpoint.execution_id == UUID(execution_id),
                    ExecutionCheckpoint.node_id == "api",
                )
            )
            assert checkpoint is not None
            checkpoint.status = "running"
            checkpoint.result = {"status": "running", "request_attempts": 1}
            await session.commit()
    finally:
        await engine.dispose()

    resumed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/resume",
        headers=headers,
    )
    assert resumed.status_code == 202, resumed.text
    detail = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert detail["execution"]["status"] == "failed"
    assert detail["execution"]["error_code"] == "SIDE_EFFECT_OUTCOME_UNKNOWN"
    assert detail["nodes"][1]["error_code"] == "SIDE_EFFECT_OUTCOME_UNKNOWN"
    assert len(target.calls) == 1
    checkpoints = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/checkpoints",
        headers=headers,
    )
    api_checkpoint = next(item for item in checkpoints.json() if item["node_id"] == "api")
    assert api_checkpoint["attempt"] == 1
    assert api_checkpoint["status"] == "failed"


@respx.mock
@pytest.mark.asyncio
async def test_schema4_resume_uses_checkpointed_collection_instead_of_refetching(
    workflow_client: AsyncClient, tmp_path: Path
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    definition = _workflow_definition(api_id)
    definition["schema_version"] = "4.0"
    definition["run_policy"] = {"request_budget": 4}
    definition["nodes"].insert(
        2,
        {
            "id": "loop",
            "type": "capability",
            "name": "冻结集合",
            "position": {"x": 200, "y": 0},
            "capability_id": "flow.control.foreach",
            "capability_version": "1.0.0",
            "configuration": {
                "collection": {
                    "kind": "node_output",
                    "node_id": "api",
                    "path": ["body", "items"],
                },
                "body": {"kind": "inline", "region_id": "body"},
                "policy": {"max_iterations": 4, "timeout_seconds": 30},
            },
            "bindings": [],
        },
    )
    definition["edges"] = [
        {"id": "start-api", "source": "start", "target": "api"},
        {"id": "api-loop", "source": "api", "target": "loop"},
        {"id": "loop-end", "source": "loop", "target": "end"},
    ]
    definition["regions"] = [
        {
            "id": "body",
            "owner_node_id": "loop",
            "role": "body",
            "nodes": [
                {
                    "id": "step",
                    "type": "delay",
                    "name": "等待",
                    "position": {"x": 0, "y": 0},
                    "config": {"seconds": 0},
                }
            ],
            "edges": [],
            "entry_node_id": "step",
            "exit_node_ids": ["step"],
        }
    ]
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "冻结输入恢复", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    target = respx.get("http://workflow.example.com/users/v1").mock(
        side_effect=[
            Response(200, json={"items": ["first", "second"]}),
            Response(200, json={"items": ["changed", "again", "extra"]}),
        ]
    )
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    execution_id = started.json()["id"]
    first = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert first["execution"]["status"] == "passed"
    assert len(target.calls) == 1

    # Recreate a process loss after the collection source and both iterations committed.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workflow.db'}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            loop = await session.scalar(
                select(ExecutionCheckpoint).where(
                    ExecutionCheckpoint.execution_id == UUID(execution_id),
                    ExecutionCheckpoint.node_id == "loop",
                )
            )
            execution = await session.get(WorkflowExecution, UUID(execution_id))
            assert loop is not None and execution is not None
            loop.status = "running"
            loop.result = {"status": "running", "request_attempts": 0}
            execution.status = "failed"
            await session.execute(
                delete(ExecutionCheckpoint).where(
                    ExecutionCheckpoint.execution_id == UUID(execution_id),
                    ExecutionCheckpoint.node_id == "end",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()

    resumed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/resume",
        headers=headers,
    )
    assert resumed.status_code == 202, resumed.text
    detail = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert detail["execution"]["status"] == "passed"
    loop_node = next(node for node in detail["nodes"] if node["node_id"] == "loop")
    assert loop_node["output"]["input_count"] == 2
    assert [item["input_index"] for item in loop_node["output"]["items"]] == [0, 1]
    assert len(target.calls) == 1


@respx.mock
@pytest.mark.asyncio
async def test_api_node_pins_version_and_applies_request_overrides(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    version_two = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis/{api_id}/versions",
        headers=headers,
        json={"method": "GET", "path": "/users/v2", "body_kind": "none"},
    )
    assert version_two.status_code == 201
    definition = _workflow_definition(api_id)
    definition["nodes"][1]["config"].update(
        {
            "api_version": 1,
            "request_overrides": {
                "query_parameters": [{"name": "source", "value": "workflow", "enabled": True}],
                "headers": {"X-Node": "custom"},
            },
        }
    )
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "固定接口版本", "definition": definition},
    )
    assert created.status_code == 201, created.text
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    target = respx.get("http://workflow.example.com/users/v1?source=workflow").mock(
        return_value=Response(200, json={"version": 1})
    )
    executed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert executed.status_code == 202, executed.text
    detail = await _wait_for_completed_execution(
        workflow_client,
        headers,
        project_id,
        executed.json()["id"],
    )
    assert detail["execution"]["status"] == "passed"
    assert detail["execution"]["snapshot"]["apis"]["api"]["version"] == 1
    assert target.calls[0].request.headers["X-Node"] == "custom"
    assert target.calls[0].request.headers["X-Snapshot-Key"] == "snapshot-api-key"


@respx.mock
@pytest.mark.asyncio
async def test_location_overrides_and_auth_disabled_reach_real_target(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project = await workflow_client.post(
        "/api/v1/projects", headers=headers, json={"name": "Location E2E project"}
    )
    project_id = project.json()["id"]
    project_configuration = await workflow_client.put(
        f"/api/v1/projects/{project_id}/configuration",
        headers=headers,
        json={
            "headers": {
                "Authorization": "Bearer project-token",
                "X-Tenant-Id": "project",
                "Cookie": "session=project; keep=project",
            }
        },
    )
    assert project_configuration.status_code == 200, project_configuration.text
    environment = await workflow_client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={
            "name": "Location target",
            "base_url": "http://workflow.example.com",
            "headers": {
                "Authorization": "Bearer environment-token",
                "X-Tenant-Id": "environment",
                "Cookie": "session=environment; keep=environment",
            },
        },
    )
    endpoints = await workflow_client.get(
        f"/api/v1/projects/{project_id}/service-endpoints", headers=headers
    )
    assert endpoints.status_code == 200, endpoints.text
    default_endpoint = next(
        item
        for item in endpoints.json()
        if item["service_id"] == environment.json()["default_service_id"]
    )
    endpoint_update = await workflow_client.patch(
        f"/api/v1/projects/{project_id}/service-endpoints/{default_endpoint['id']}",
        headers=headers,
        json={
            "headers": {
                "Authorization": "Bearer endpoint-token",
                "X-Tenant-Id": "endpoint",
                "Cookie": "session=endpoint; keep=endpoint",
            }
        },
    )
    assert endpoint_update.status_code == 200, endpoint_update.text
    api = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "Create tenant order",
            "request": {
                "method": "POST",
                "path": "/tenants/{{tenantId}}/orders",
                "query_parameters": [
                    {"name": "dryRun", "value": "false", "enabled": True},
                    {"name": "api_key", "value": "api-key", "enabled": True},
                ],
                "headers": {
                    "Authorization": "Bearer api-token",
                    "X-Tenant-Id": "api",
                    "Cookie": "session=api; keep=api",
                },
                "body_kind": "json",
                "body": {"quantity": 1},
                "auth": {
                    "kind": "bearer",
                    "values": {"token": "api-bearer-token"},
                },
            },
        },
    )
    assert api.status_code == 201, api.text
    definition = _workflow_definition(api.json()["definition"]["id"])
    definition["variables"] = {"tenantId": "tenant-47"}
    definition["nodes"][1]["config"].update(
        {
            "expected_statuses": [401],
            "request_overrides": {
                "query_parameters": [{"name": "dryRun", "value": "true", "enabled": True}],
                "headers": {"X-Tenant-Id": "node-suppressed-value"},
                "replace_headers": True,
                "body": {"kind": "json", "value": {"quantity": 1000}},
                "auth_mode": "disabled",
                "suppressed_headers": ["x-tenant-id"],
                "suppressed_query_parameters": ["api_key"],
                "suppressed_cookies": ["session"],
            },
        }
    )
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "Location negative E2E", "definition": definition},
    )
    assert created.status_code == 201, created.text
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    target = respx.post("http://workflow.example.com/tenants/tenant-47/orders?dryRun=true").mock(
        return_value=Response(401, json={"error": "missing authentication"})
    )
    executed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/executions",
        headers=headers,
        json={
            "environment_id": environment.json()["id"],
            "runtime_headers": {
                "Authorization": "Bearer runtime-token",
                "X-Tenant-Id": "runtime",
                "Cookie": "session=runtime; keep=runtime",
            },
        },
    )
    assert executed.status_code == 202, executed.text
    detail = await _wait_for_completed_execution(
        workflow_client, headers, project_id, executed.json()["id"]
    )
    assert detail["execution"]["status"] == "passed"
    request = target.calls[0].request
    assert request.url.path == "/tenants/tenant-47/orders"
    assert request.url.params["dryRun"] == "true"
    assert "X-Tenant-Id" not in request.headers
    assert "Authorization" not in request.headers
    assert "api_key" not in request.url.params
    assert request.headers["Cookie"] == "keep=runtime"
    assert json.loads(request.content) == {"quantity": 1000}
    suppression = detail["execution"]["snapshot"]["apis"]["api"]["target"]["request_suppression"]
    assert suppression == {
        "auth_mode": "disabled",
        "suppressed_header_names": ["Authorization", "x-tenant-id"],
        "suppressed_query_parameter_names": ["api_key"],
        "suppressed_cookie_names": ["session"],
    }
    snapshot_text = json.dumps(detail["execution"]["snapshot"])
    for suppressed_value in (
        "node-suppressed-value",
        "api-key",
        "api-token",
        "runtime-token",
        "runtime-sentinel",
    ):
        assert suppressed_value not in snapshot_text


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("auth_location", ["query", "cookie"])
async def test_api_key_query_and_cookie_auth_are_suppressed_after_all_layers(
    workflow_client: AsyncClient,
    auth_location: str,
) -> None:
    headers = await _login_headers(workflow_client)
    project = await workflow_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": f"API key {auth_location} suppression"},
    )
    project_id = project.json()["id"]
    environment = await workflow_client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "Suppression target", "base_url": "http://workflow.example.com"},
    )
    carrier = "api_key" if auth_location == "query" else "auth_session"
    api_headers = {"Cookie": f"{carrier}=api; keep=api"} if auth_location == "cookie" else {}
    query_parameters = (
        [{"name": carrier, "value": "api", "enabled": True}] if auth_location == "query" else []
    )
    api = await workflow_client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": f"API key {auth_location}",
            "request": {
                "method": "GET",
                "path": f"/auth-{auth_location}",
                "query_parameters": query_parameters,
                "headers": api_headers,
                "body_kind": "none",
                "auth": {
                    "kind": "api_key",
                    "values": {
                        "in": auth_location,
                        "name": carrier,
                        "value": "auth-value",
                    },
                },
            },
        },
    )
    assert api.status_code == 201, api.text
    definition = _workflow_definition(api.json()["definition"]["id"])
    overrides: dict[str, Any] = {"auth_mode": "disabled"}
    if auth_location == "query":
        overrides["query_parameters"] = [{"name": carrier, "value": "node", "enabled": True}]
    definition["nodes"][1]["config"].update(
        {"expected_statuses": [200], "request_overrides": overrides}
    )
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": f"Suppress {auth_location} auth", "definition": definition},
    )
    assert created.status_code == 201, created.text
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    target = respx.get(f"http://workflow.example.com/auth-{auth_location}").mock(
        return_value=Response(200, json={"ok": True})
    )
    runtime_headers = {"Authorization": "Bearer stale-runtime-auth"}
    if auth_location == "cookie":
        runtime_headers["Cookie"] = f"{carrier}=runtime; keep=runtime"
    executed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{created.json()['id']}/executions",
        headers=headers,
        json={
            "environment_id": environment.json()["id"],
            "runtime_headers": runtime_headers,
        },
    )
    assert executed.status_code == 202, executed.text
    detail = await _wait_for_completed_execution(
        workflow_client, headers, project_id, executed.json()["id"]
    )
    assert detail["execution"]["status"] == "passed"
    request = target.calls[0].request
    assert "Authorization" not in request.headers
    if auth_location == "query":
        assert carrier not in request.url.params
    else:
        assert request.headers["Cookie"] == "keep=runtime"
    suppression = detail["execution"]["snapshot"]["apis"]["api"]["target"]["request_suppression"]
    assert suppression["auth_mode"] == "disabled"
    expected_key = (
        "suppressed_query_parameter_names"
        if auth_location == "query"
        else "suppressed_cookie_names"
    )
    assert suppression[expected_key] == [carrier]
    assert "auth-value" not in json.dumps(detail)
    assert "stale-runtime-auth" not in json.dumps(detail)


@respx.mock
@pytest.mark.asyncio
async def test_subflow_foreach_diff_breakpoint_replay_and_recursion_guards(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    child_created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "子流程", "definition": _empty_workflow_definition()},
    )
    assert child_created.status_code == 201, child_created.text
    child_id = child_created.json()["id"]
    child_v1 = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{child_id}/versions",
        headers=headers,
    )
    assert child_v1.status_code == 200, child_v1.text

    parent_definition = _for_each_workflow_definition(api_id, child_id, 1)
    parent_created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "批量子流程", "definition": parent_definition},
    )
    assert parent_created.status_code == 201, parent_created.text
    parent = parent_created.json()
    parent_id = parent["id"]
    parent_v1 = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{parent_id}/versions",
        headers=headers,
    )
    assert parent_v1.status_code == 200, parent_v1.text

    changed_definition = json.loads(json.dumps(parent_definition))
    changed_definition["nodes"][2]["name"] = "遍历用户 (新版草稿)"
    updated = await workflow_client.patch(
        f"/api/v1/projects/{project_id}/workflows/{parent_id}",
        headers=headers,
        json={"expected_revision": parent["draft_revision"], "definition": changed_definition},
    )
    assert updated.status_code == 200, updated.text
    parent_v2 = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{parent_id}/versions",
        headers=headers,
    )
    assert parent_v2.status_code == 200, parent_v2.text
    diff = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflows/{parent_id}/versions/1/diff/2",
        headers=headers,
    )
    assert diff.status_code == 200, diff.text
    assert {item["path"] for item in diff.json()["changes"]} == {"$.nodes"}

    target = respx.get("http://workflow.example.com/users/v1").mock(
        return_value=Response(200, json={"items": [{"id": 1}, {"id": 2}]})
    )
    debugged = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{parent_id}/debug",
        headers=headers,
        json={
            "environment_id": environment_id,
            "version": 1,
            "breakpoint_node_id": "loop",
        },
    )
    assert debugged.status_code == 200, debugged.text
    debug_nodes = {item["node_id"]: item for item in debugged.json()["nodes"]}
    assert debug_nodes["source"]["status"] == "passed"
    assert debug_nodes["loop"]["error_code"] == "DEBUG_SCOPE_EXCLUDED"

    executed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{parent_id}/executions",
        headers=headers,
        json={"environment_id": environment_id, "version": 1},
    )
    assert executed.status_code == 202, executed.text
    detail = await _wait_for_completed_execution(
        workflow_client,
        headers,
        project_id,
        executed.json()["id"],
    )
    assert detail["execution"]["status"] == "passed", detail
    loop = next(item for item in detail["nodes"] if item["node_id"] == "loop")
    assert loop["output"]["total"] == 2
    assert loop["output"]["items"][1]["result"]["workflow_version"] == 1
    assert detail["execution"]["snapshot"]["subflows"]["loop"]["workflow"]["version"] == 1

    replayed = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{executed.json()['id']}"
        "/nodes/source/replay",
        headers=headers,
    )
    assert replayed.status_code == 200, replayed.text
    replay_nodes = {item["node_id"]: item for item in replayed.json()["nodes"]}
    assert replay_nodes["source"]["status"] == "passed"
    assert replay_nodes["loop"]["status"] == "skipped"
    assert len(target.calls) == 3

    recursive_child = _subflow_workflow_definition(parent_id, 1)
    child_updated = await workflow_client.patch(
        f"/api/v1/projects/{project_id}/workflows/{child_id}",
        headers=headers,
        json={"expected_revision": 1, "definition": recursive_child},
    )
    assert child_updated.status_code == 200, child_updated.text
    recursion = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{child_id}/versions",
        headers=headers,
    )
    assert recursion.status_code == 422
    assert recursion.json()["error"]["code"] == "SUBFLOW_RECURSION"


@pytest.mark.asyncio
async def test_publish_rejects_invalid_or_cross_project_api_configuration(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, _environment_id, api_id = await _create_assets(workflow_client, headers)
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

    missing_version_definition = _workflow_definition(api_id)
    missing_version_definition["nodes"][1]["config"]["api_version"] = 99
    missing_version = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "版本不存在", "definition": missing_version_definition},
    )
    rejected_version = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{missing_version.json()['id']}/versions",
        headers=headers,
    )
    assert rejected_version.status_code == 422
    assert rejected_version.json()["error"]["code"] == "WORKFLOW_API_VERSION_NOT_FOUND"

    missing_file_definition = _workflow_definition(api_id)
    missing_file_definition["nodes"][1]["config"]["request_overrides"] = {
        "body": {
            "kind": "multipart",
            "value": {
                "files": [
                    {
                        "field": "document",
                        "artifact_id": "00000000-0000-4000-8000-000000000098",
                    }
                ]
            },
        }
    }
    missing_file = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "文件不存在", "definition": missing_file_definition},
    )
    rejected_file = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{missing_file.json()['id']}/versions",
        headers=headers,
    )
    assert rejected_file.status_code == 422
    assert rejected_file.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_cleanup_runtime_persists_separate_main_and_cleanup_report(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    definition = _workflow_definition(api_id)
    definition["nodes"].insert(
        -1,
        {
            "id": "cleanup",
            "type": "api",
            "name": "清理用户",
            "position": {"x": 200, "y": 100},
            "config": {"api_definition_id": api_id},
            "phase": "cleanup",
            "run_when": "always",
            "cleanup_for": ["api"],
            "best_effort": False,
            "cleanup_timeout_seconds": 5,
            "cleanup_retry_budget": 0,
        },
    )
    definition["run_policy"] = {"cleanup_request_budget": 1}
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "清理报告流程", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    target = respx.get("http://workflow.example.com/users/v1").mock(
        side_effect=[Response(200, json={"id": 7}), Response(500, json={"error": "cleanup"})]
    )

    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    detail = await _wait_for_completed_execution(
        workflow_client, headers, project_id, started.json()["id"]
    )

    execution = detail["execution"]
    assert execution["status"] == "failed"
    assert execution["main_status"] == "passed"
    assert execution["cleanup_status"] == "failed"
    assert execution["cleanup_report"]["required_failures"] == ["cleanup"]
    assert [item["phase"] for item in detail["nodes"]] == [
        "main",
        "main",
        "cleanup",
        "main",
    ]
    assert len(target.calls) == 2
    assert execution["snapshot"]["workflow"]["definition"]["nodes"][2]["phase"] == "cleanup"


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
    running_checkpoint: dict[str, Any] | None = None
    for _ in range(50):
        checkpoints = await workflow_client.get(
            f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/checkpoints",
            headers=headers,
        )
        running_checkpoint = next(
            (
                item
                for item in checkpoints.json()
                if item["node_id"] == "api" and item["status"] == "running"
            ),
            None,
        )
        if running_checkpoint is not None:
            break
        await asyncio.sleep(0.01)
    assert running_checkpoint is not None
    assert running_checkpoint["attempt"] == 1
    assert running_checkpoint["started_at"] is not None
    reserved_input_hash = running_checkpoint["input_hash"]
    cancelled = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancel_requested_at"] is not None

    result = await _wait_for_completed_execution(workflow_client, headers, project_id, execution_id)
    assert result["execution"]["status"] == "cancelled"
    assert result["nodes"][1]["status"] == "cancelled"
    checkpoints = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/checkpoints",
        headers=headers,
    )
    cancelled_api = next(item for item in checkpoints.json() if item["node_id"] == "api")
    assert cancelled_api["status"] == "cancelled"
    assert cancelled_api["attempt"] == 1
    assert cancelled_api["input_hash"] == reserved_input_hash

    forced = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    missing_reason = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{forced.json()['id']}/cancel",
        headers=headers,
        json={"force": True},
    )
    assert missing_reason.status_code == 422
    force_cancelled = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{forced.json()['id']}/cancel",
        headers=headers,
        json={"force": True, "reason": "测试 Runner 无响应时的强制终止"},
    )
    assert force_cancelled.status_code == 200, force_cancelled.text
    assert force_cancelled.json()["force_cancel_requested_at"] is not None
    assert force_cancelled.json()["force_cancel_reason"] == "测试 Runner 无响应时的强制终止"
    forced_result = await _wait_for_completed_execution(
        workflow_client, headers, project_id, forced.json()["id"]
    )
    assert forced_result["execution"]["status"] == "cancelled"

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
async def test_dataset_child_can_rerun_failed_control_iteration_without_rerunning_other_rows(
    workflow_client: AsyncClient,
) -> None:
    headers = await _login_headers(workflow_client)
    project_id, environment_id, api_id = await _create_assets(workflow_client, headers)
    dataset = await workflow_client.post(
        f"/api/v1/projects/{project_id}/files",
        headers=headers,
        files={
            "file": (
                "rows.json",
                b'[{"row":"first"},{"row":"second"}]',
                "application/json",
            )
        },
    )
    assert dataset.status_code == 201, dataset.text
    definition = {
        "schema_version": "4.0",
        "run_policy": {"request_budget": 4},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "dataset",
                "type": "dataset",
                "name": "数据行",
                "position": {"x": 100, "y": 0},
                "config": {"artifact_id": dataset.json()["id"], "format": "json"},
            },
            {
                "id": "api",
                "type": "api",
                "name": "读取集合",
                "position": {"x": 200, "y": 0},
                "config": {"api_definition_id": api_id},
            },
            {
                "id": "loop",
                "type": "capability",
                "name": "遍历",
                "position": {"x": 300, "y": 0},
                "capability_id": "flow.control.foreach",
                "capability_version": "1.0.0",
                "configuration": {
                    "collection": {
                        "kind": "node_output",
                        "node_id": "api",
                        "path": ["body", "items"],
                    },
                    "body": {"kind": "inline", "region_id": "body"},
                    "policy": {
                        "max_iterations": 2,
                        "timeout_seconds": 30,
                        "on_error": "continue_collect",
                    },
                },
                "bindings": [],
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 400, "y": 0}},
        ],
        "edges": [
            {"id": "start-dataset", "source": "start", "target": "dataset"},
            {"id": "dataset-api", "source": "dataset", "target": "api"},
            {"id": "api-loop", "source": "api", "target": "loop"},
            {"id": "loop-end", "source": "loop", "target": "end"},
        ],
        "regions": [
            {
                "id": "body",
                "owner_node_id": "loop",
                "role": "body",
                "nodes": [
                    {
                        "id": "check",
                        "type": "api",
                        "name": "检查资源",
                        "position": {"x": 0, "y": 0},
                        "config": {"api_definition_id": api_id},
                    },
                    {
                        "id": "assert",
                        "type": "assert",
                        "name": "校验状态",
                        "position": {"x": 100, "y": 0},
                        "config": {
                            "source_node_id": "check",
                            "expression": "status_code",
                            "operator": "equals",
                            "expected": 201,
                        },
                    },
                ],
                "edges": [{"id": "check-assert", "source": "check", "target": "assert"}],
                "entry_node_id": "check",
                "exit_node_ids": ["assert"],
            }
        ],
    }
    created = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "批量失败轮次", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    published = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    target = respx.get("http://workflow.example.com/users/v1").mock(
        return_value=Response(200, json={"items": ["one", "two"]})
    )
    started = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert started.status_code == 202, started.text
    parent_id = started.json()["id"]
    parent = await _wait_for_completed_execution(workflow_client, headers, project_id, parent_id)
    assert len(parent["children"]) == 2
    assert len(target.calls) == 6
    source_id = parent["children"][0]["id"]
    source = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{source_id}", headers=headers
    )
    assert source.status_code == 200
    original_loop = next(node for node in source.json()["nodes"] if node["node_id"] == "loop")
    assert [item["input_index"] for item in original_loop["output"]["items"]] == [0, 1]
    parent_rerun = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{parent_id}/failed-items/rerun",
        headers=headers,
        json={"loop_node_id": "loop", "input_indices": [1]},
    )
    assert parent_rerun.status_code == 409
    assert parent_rerun.json()["error"]["code"] == "RERUN_SOURCE_UNSUPPORTED"

    rerun = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{source_id}/failed-items/rerun",
        headers=headers,
        json={"loop_node_id": "loop", "input_indices": [1]},
    )
    assert rerun.status_code == 202, rerun.text
    assert rerun.json()["derived_from_execution_id"] == source_id
    assert rerun.json()["parent_execution_id"] is None
    derived = await _wait_for_completed_execution(
        workflow_client, headers, project_id, rerun.json()["id"]
    )
    derived_loop = next(node for node in derived["nodes"] if node["node_id"] == "loop")
    assert [item["input_index"] for item in derived_loop["output"]["items"]] == [1]
    assert len(target.calls) == 6
    unchanged_parent = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{parent_id}", headers=headers
    )
    assert [child["id"] for child in unchanged_parent.json()["children"]] == [
        child["id"] for child in parent["children"]
    ]
    unchanged_child = await workflow_client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{source_id}", headers=headers
    )
    unchanged_loop = next(
        node for node in unchanged_child.json()["nodes"] if node["node_id"] == "loop"
    )
    assert unchanged_loop["output"] == original_loop["output"]


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


def _empty_workflow_definition() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 220, "y": 0}},
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
    }


def _for_each_workflow_definition(
    api_id: str,
    child_workflow_id: str,
    child_version: int,
) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "source",
                "type": "api",
                "name": "读取用户",
                "position": {"x": 220, "y": 0},
                "config": {"api_definition_id": api_id},
            },
            {
                "id": "loop",
                "type": "for_each",
                "name": "遍历用户",
                "position": {"x": 440, "y": 0},
                "config": {
                    "workflow_id": child_workflow_id,
                    "workflow_version": child_version,
                    "source_node_id": "source",
                    "expression": "body.items",
                    "item_variable": "user",
                    "concurrency": 2,
                    "fail_fast": False,
                },
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 660, "y": 0}},
        ],
        "edges": [
            {"id": "start-source", "source": "start", "target": "source"},
            {"id": "source-loop", "source": "source", "target": "loop"},
            {"id": "loop-end", "source": "loop", "target": "end"},
        ],
    }


def _subflow_workflow_definition(workflow_id: str, version: int) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "subflow",
                "type": "subflow",
                "name": "调用父流程",
                "position": {"x": 220, "y": 0},
                "config": {"workflow_id": workflow_id, "workflow_version": version},
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 440, "y": 0}},
        ],
        "edges": [
            {"id": "start-subflow", "source": "start", "target": "subflow"},
            {"id": "subflow-end", "source": "subflow", "target": "end"},
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
