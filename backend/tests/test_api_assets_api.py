from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.main import app
from app.models import Base
from app.models.access import User

ADMIN_EMAIL = "assets-admin@example.com"
ADMIN_PASSWORD = "assets-password-123!"


@pytest.fixture
async def asset_client() -> AsyncIterator[AsyncClient]:
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
                display_name="Asset administrator",
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
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_environment_secret_api_version_and_preview_flow(
    asset_client: AsyncClient,
) -> None:
    headers = await _login_headers(asset_client)
    project = await _create_project(asset_client, headers)
    project_id = project["id"]

    configuration = await asset_client.put(
        f"/api/v1/projects/{project_id}/configuration",
        headers=headers,
        json={
            "variables": {"tenant": "project", "user_id": "project-user"},
            "headers": {"X-Source": "project", "X-Project": "{{tenant}}"},
        },
    )
    assert configuration.status_code == 200
    loaded_configuration = await asset_client.get(
        f"/api/v1/projects/{project_id}/configuration", headers=headers
    )
    assert loaded_configuration.json()["variables"]["tenant"] == "project"

    environment_a = await _create_environment(
        asset_client,
        headers,
        project_id,
        name="开发环境",
        base_url="http://env-a.example.com",
        variables={"tenant": "environment", "user_id": "env-user"},
        environment_headers={"x-source": "environment"},
    )
    environment_b = await _create_environment(
        asset_client,
        headers,
        project_id,
        name="测试环境",
        base_url="http://env-b.example.com",
        variables={"tenant": "test", "user_id": "test-user"},
        environment_headers={},
    )
    duplicate = await _create_environment_response(
        asset_client,
        headers,
        project_id,
        name="开发环境",
        base_url="http://duplicate.example.com",
        variables={},
        environment_headers={},
    )
    assert duplicate.status_code == 409
    updated_environment = await asset_client.patch(
        f"/api/v1/projects/{project_id}/environments/{environment_a['id']}",
        headers=headers,
        json={"name": "本地开发环境"},
    )
    assert updated_environment.status_code == 200
    environments = await asset_client.get(
        f"/api/v1/projects/{project_id}/environments", headers=headers
    )
    assert len(environments.json()) == 2

    secret_response = await asset_client.put(
        f"/api/v1/projects/{project_id}/secrets",
        headers=headers,
        json={
            "name": "API_TOKEN",
            "value": "super-secret-token",
            "environment_id": environment_a["id"],
        },
    )
    assert secret_response.status_code == 200
    assert "value" not in secret_response.json()
    listed_secrets = await asset_client.get(
        f"/api/v1/projects/{project_id}/secrets", headers=headers
    )
    assert listed_secrets.status_code == 200
    assert "super-secret-token" not in listed_secrets.text
    assert "ciphertext" not in listed_secrets.text

    created_api = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "查询用户",
            "description": "Variable and secret preview",
            "request": {
                "method": "POST",
                "path": "/{{tenant}}/users/{{user_id}}",
                "query_parameters": [
                    {"name": "locale", "value": "{{locale}}", "enabled": True},
                    {"name": "disabled", "value": "ignored", "enabled": False},
                ],
                "headers": {
                    "X-Source": "api",
                    "X-Token-Copy": "{{secret.API_TOKEN}}",
                },
                "body_kind": "json",
                "body": {
                    "tenant": "{{tenant}}",
                    "token": "{{secret.API_TOKEN}}",
                },
                "auth": {
                    "kind": "bearer",
                    "values": {"token": "{{secret.API_TOKEN}}"},
                },
            },
        },
    )
    assert created_api.status_code == 201, created_api.text
    definition_id = created_api.json()["definition"]["id"]
    renamed_api = await asset_client.patch(
        f"/api/v1/projects/{project_id}/apis/{definition_id}",
        headers=headers,
        json={"name": "查询用户详情"},
    )
    assert renamed_api.status_code == 200
    assert renamed_api.json()["name"] == "查询用户详情"
    blank_name = await asset_client.patch(
        f"/api/v1/projects/{project_id}/apis/{definition_id}",
        headers=headers,
        json={"name": "   "},
    )
    assert blank_name.status_code == 422

    preview_a = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/preview",
        headers=headers,
        json={
            "environment_id": environment_a["id"],
            "runtime_variables": {"tenant": "runtime", "locale": "zh-CN"},
            "runtime_headers": {"X-SOURCE": "runtime"},
        },
    )
    assert preview_a.status_code == 200, preview_a.text
    preview = preview_a.json()
    assert preview["url"] == "http://env-a.example.com/runtime/users/env-user?locale=zh-CN"
    header_map = {item["name"].lower(): item for item in preview["headers"]}
    assert header_map["x-source"] == {
        "name": "X-SOURCE",
        "value": "runtime",
        "source": "runtime",
    }
    assert header_map["authorization"]["value"] == "******"
    assert header_map["x-token-copy"]["value"] == "******"
    assert preview["body"] == {"tenant": "runtime", "token": "******"}
    secret_variable = next(
        item for item in preview["variables"] if item["name"] == "secret.API_TOKEN"
    )
    assert secret_variable["value"] == "******"
    assert secret_variable["secret"] is True
    assert "super-secret-token" not in preview_a.text

    preview_b = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/preview",
        headers=headers,
        json={
            "environment_id": environment_b["id"],
            "runtime_variables": {"locale": "en-US"},
        },
    )
    assert preview_b.status_code == 422
    assert preview_b.json()["error"]["code"] == "UNRESOLVED_VARIABLE"

    version_two = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/versions",
        headers=headers,
        json={
            "method": "GET",
            "path": "/health",
            "body_kind": "none",
            "auth": {"kind": "none", "values": {}},
            "extraction_rules": [
                {"name": "request_id", "kind": "header", "expression": "X-Request-ID"}
            ],
            "assertions": [
                {
                    "kind": "status_code",
                    "operator": "equals",
                    "target": None,
                    "expected": 200,
                }
            ],
        },
    )
    assert version_two.status_code == 201
    assert version_two.json()["version"] == 2
    assert version_two.json()["extraction_rules"][0]["name"] == "request_id"
    assert version_two.json()["assertions"][0]["expected"] == 200
    version_three = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/versions",
        headers=headers,
        json={
            "method": "GET",
            "path": "/health",
            "body_kind": "none",
            "auth": {
                "kind": "api_key",
                "values": {"name": "api_key", "value": "plain-credential", "in": "query"},
            },
        },
    )
    assert version_three.status_code == 201
    api_key_preview = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/preview",
        headers=headers,
        json={"environment_id": environment_b["id"]},
    )
    assert api_key_preview.status_code == 200
    assert (
        api_key_preview.json()["url"]
        == "http://env-b.example.com/health?api_key=%2A%2A%2A%2A%2A%2A"
    )
    assert "plain-credential" not in api_key_preview.text
    current = await asset_client.get(
        f"/api/v1/projects/{project_id}/apis/{definition_id}", headers=headers
    )
    original = await asset_client.get(
        f"/api/v1/projects/{project_id}/apis/{definition_id}?version=1", headers=headers
    )
    persisted_version_two = await asset_client.get(
        f"/api/v1/projects/{project_id}/apis/{definition_id}?version=2", headers=headers
    )
    assert current.json()["version"]["version"] == 3
    assert original.json()["version"]["version"] == 1
    assert persisted_version_two.json()["version"]["extraction_rules"] == [
        {"name": "request_id", "kind": "header", "expression": "X-Request-ID"}
    ]
    node_preview = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/preview",
        headers=headers,
        json={
            "environment_id": environment_a["id"],
            "version": 1,
            "runtime_variables": {"tenant": "node", "user_id": "42"},
            "query_parameters_override": [{"name": "source", "value": "workflow", "enabled": True}],
            "headers_override": {"X-Node": "custom"},
            "body_override": {"owner": "{{tenant}}"},
            "use_body_override": True,
        },
    )
    assert node_preview.status_code == 200, node_preview.text
    assert node_preview.json()["url"] == ("http://env-a.example.com/node/users/42?source=workflow")
    node_headers = {item["name"].lower(): item["value"] for item in node_preview.json()["headers"]}
    assert node_headers["x-node"] == "custom"
    assert "x-token-copy" not in node_headers
    assert node_headers["authorization"] == "******"
    assert node_preview.json()["body"] == {"owner": "node"}
    versions = await asset_client.get(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/versions", headers=headers
    )
    assert [item["version"] for item in versions.json()] == [3, 2, 1]
    definitions = await asset_client.get(f"/api/v1/projects/{project_id}/apis", headers=headers)
    assert definitions.json()["total"] == 1


@pytest.mark.asyncio
async def test_invalid_header_and_cross_project_environment_are_rejected(
    asset_client: AsyncClient,
) -> None:
    headers = await _login_headers(asset_client)
    first = await _create_project(asset_client, headers, name="First")
    second = await _create_project(asset_client, headers, name="Second")
    environment = await _create_environment(
        asset_client,
        headers,
        second["id"],
        name="Second environment",
        base_url="http://second.example.com",
        variables={},
        environment_headers={},
    )
    invalid_header = await asset_client.put(
        f"/api/v1/projects/{first['id']}/configuration",
        headers=headers,
        json={"variables": {}, "headers": {"Bad\nHeader": "value"}},
    )
    assert invalid_header.status_code == 422
    cross_project_secret = await asset_client.put(
        f"/api/v1/projects/{first['id']}/secrets",
        headers=headers,
        json={"name": "TOKEN", "value": "secret", "environment_id": environment["id"]},
    )
    assert cross_project_secret.status_code == 404


@pytest.mark.asyncio
async def test_api_list_supports_server_side_search_and_method_filter(
    asset_client: AsyncClient,
) -> None:
    headers = await _login_headers(asset_client)
    project = await _create_project(asset_client, headers, name="Search project")
    api_specs = (
        ("健康检查", "GET", "/health"),
        ("创建订单", "POST", "/orders"),
        ("订单详情", "GET", "/orders/{id}"),
    )
    for name, method, path in api_specs:
        response = await asset_client.post(
            f"/api/v1/projects/{project['id']}/apis",
            headers=headers,
            json={
                "name": name,
                "description": f"{name} description",
                "request": {
                    "method": method,
                    "path": path,
                    "body_kind": "none",
                    "auth": {"kind": "none", "values": {}},
                },
            },
        )
        assert response.status_code == 201, response.text

    searched = await asset_client.get(
        f"/api/v1/projects/{project['id']}/apis",
        headers=headers,
        params={"search": "orders", "page": 1, "page_size": 50},
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 2
    assert {item["name"] for item in searched.json()["items"]} == {"创建订单", "订单详情"}

    filtered = await asset_client.get(
        f"/api/v1/projects/{project['id']}/apis",
        headers=headers,
        params={"method": "POST", "page": 1, "page_size": 50},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["name"] == "创建订单"


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(
    client: AsyncClient, headers: dict[str, str], name: str = "API project"
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "description": "S2 tests"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_environment(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    name: str,
    base_url: str,
    variables: dict[str, str],
    environment_headers: dict[str, str],
) -> dict[str, Any]:
    response = await _create_environment_response(
        client,
        headers,
        project_id,
        name=name,
        base_url=base_url,
        variables=variables,
        environment_headers=environment_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_environment_response(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    name: str,
    base_url: str,
    variables: dict[str, str],
    environment_headers: dict[str, str],
):
    return await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={
            "name": name,
            "base_url": base_url,
            "variables": variables,
            "headers": environment_headers,
        },
    )
