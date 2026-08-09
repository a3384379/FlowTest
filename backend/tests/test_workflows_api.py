import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.main import app
from app.models import Base
from app.models.access import User

ADMIN_EMAIL = "workflow-admin@example.com"
ADMIN_PASSWORD = "workflow-password-123!"


@pytest.fixture
async def workflow_client() -> AsyncIterator[AsyncClient]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
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

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()
    await test_engine.dispose()


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
    assert executed.status_code == 200, executed.text
    detail = executed.json()
    assert detail["execution"]["status"] == "passed"
    assert detail["nodes"][1]["attempts"] == 2
    assert detail["nodes"][1]["output"]["body"] == {"id": 7}
    assert len(target.calls) == 2
    snapshot = detail["execution"]["snapshot"]
    assert snapshot["workflow"]["version"] == 1
    assert snapshot["apis"]["api"]["version"] == 2
    assert snapshot["apis"]["api"]["prepared_request"]["url"].endswith("/users/v2")
    assert snapshot["apis"]["api"]["spec"]["auth_config"]["value"] == "***"
    assert "snapshot-api-key" not in executed.text

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
    running = asyncio.create_task(
        workflow_client.post(
            f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
            headers=headers,
            json={"environment_id": environment_id},
        )
    )
    execution_id = await _wait_for_running_execution(workflow_client, headers, project_id)
    cancelled = await workflow_client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancel_requested_at"] is not None

    completed = await asyncio.wait_for(running, timeout=2)
    assert completed.status_code == 200, completed.text
    result = completed.json()
    assert result["execution"]["status"] == "cancelled"
    assert result["nodes"][1]["status"] == "cancelled"


async def _wait_for_running_execution(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
) -> str:
    for _attempt in range(40):
        response = await client.get(
            f"/api/v1/projects/{project_id}/workflow-executions",
            headers=headers,
        )
        if response.status_code == 200 and response.json()["items"]:
            return str(response.json()["items"][0]["id"])
        await asyncio.sleep(0.01)
    raise AssertionError("workflow execution did not enter running state")


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
