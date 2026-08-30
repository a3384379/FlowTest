from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.test_engineering import OperationContract, fingerprint_contract
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
    unreferenced_secret_response = await asset_client.put(
        f"/api/v1/projects/{project_id}/secrets",
        headers=headers,
        json={
            "name": "UNREFERENCED",
            "value": "unreferenced-secret-value",
            "environment_id": environment_a["id"],
        },
    )
    assert unreferenced_secret_response.status_code == 200
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
    assert not any(item["name"] == "secret.UNREFERENCED" for item in preview["variables"])
    assert "UNREFERENCED" not in preview["target"]["secret_refs"]
    assert "super-secret-token" not in preview_a.text
    assert "unreferenced-secret-value" not in preview_a.text

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


@pytest.mark.asyncio
async def test_service_endpoint_resolution_and_snapshot(
    asset_client: AsyncClient,
) -> None:
    headers = await _login_headers(asset_client)
    project = await _create_project(asset_client, headers, name="Request targets")
    project_id = project["id"]
    environment = await _create_environment(
        asset_client,
        headers,
        project_id,
        name="Target",
        base_url="http://legacy.example.com",
        variables={"layer": "environment"},
        environment_headers={"X-Layer": "environment"},
    )
    default_service_id = environment["default_service_id"]
    services = await asset_client.get(f"/api/v1/projects/{project_id}/services", headers=headers)
    assert services.status_code == 200
    assert {item["service_key"] for item in services.json()} == {"default"}

    auth_service = await asset_client.post(
        f"/api/v1/projects/{project_id}/services",
        headers=headers,
        json={"service_key": "auth", "name": "Auth Service"},
    )
    order_service = await asset_client.post(
        f"/api/v1/projects/{project_id}/services",
        headers=headers,
        json={"service_key": "orders", "name": "Order Service"},
    )
    assert auth_service.status_code == 201, auth_service.text
    assert order_service.status_code == 201, order_service.text
    auth_id = auth_service.json()["id"]
    order_id = order_service.json()["id"]

    auth_endpoint = await asset_client.post(
        f"/api/v1/projects/{project_id}/environments/{environment['id']}/service-endpoints",
        headers=headers,
        json={
            "service_id": auth_id,
            "base_url": "https://auth.example.com",
            "headers": {"X-Layer": "endpoint", "X-Endpoint": "auth"},
            "variables": {"layer": "endpoint"},
        },
    )
    order_endpoint = await asset_client.post(
        f"/api/v1/projects/{project_id}/environments/{environment['id']}/service-endpoints",
        headers=headers,
        json={
            "service_id": order_id,
            "base_url": "https://orders.example.com",
            "headers": {"X-Endpoint": "orders"},
        },
    )
    order_canary = await asset_client.post(
        f"/api/v1/projects/{project_id}/environments/{environment['id']}/service-endpoints",
        headers=headers,
        json={
            "service_id": order_id,
            "variant": "canary",
            "base_url": "https://orders-canary.example.com",
        },
    )
    assert auth_endpoint.status_code == 201, auth_endpoint.text
    assert order_endpoint.status_code == 201, order_endpoint.text
    assert order_canary.status_code == 201, order_canary.text

    created = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "Auth API",
            "service_id": auth_id,
            "request": {
                "method": "GET",
                "path": "/users/{{layer}}",
                "variables": {"layer": "api"},
                "headers": {"X-Layer": "api"},
                "body_kind": "none",
            },
        },
    )
    assert created.status_code == 201, created.text
    created_version = created.json()["version"]
    created_contract = OperationContract.model_validate(created_version["canonical_contract"])
    assert created_contract.service == "auth"
    assert created_version["contract_fingerprint"] == fingerprint_contract(created_contract)
    definition_id = created.json()["definition"]["id"]
    created_version_two = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/versions",
        headers=headers,
        json={
            "method": "GET",
            "path": "/users/{{layer}}",
            "variables": {"layer": "api"},
            "headers": {"X-Layer": "api"},
            "body_kind": "none",
        },
    )
    assert created_version_two.status_code == 201, created_version_two.text
    version_two_contract = OperationContract.model_validate(
        created_version_two.json()["canonical_contract"]
    )
    assert version_two_contract.service == "auth"
    assert created_version_two.json()["contract_fingerprint"] == fingerprint_contract(
        version_two_contract
    )

    rebound = await asset_client.patch(
        f"/api/v1/projects/{project_id}/apis/{definition_id}",
        headers=headers,
        json={"service_id": order_id},
    )
    assert rebound.status_code == 200, rebound.text
    rebound_detail = await asset_client.get(
        f"/api/v1/projects/{project_id}/apis/{definition_id}", headers=headers
    )
    rebound_contract = OperationContract.model_validate(
        rebound_detail.json()["version"]["canonical_contract"]
    )
    assert rebound_contract.service == "orders"
    assert rebound_detail.json()["version"]["contract_fingerprint"] == fingerprint_contract(
        rebound_contract
    )
    historical_detail = await asset_client.get(
        f"/api/v1/projects/{project_id}/apis/{definition_id}?version=2", headers=headers
    )
    historical_contract = OperationContract.model_validate(
        historical_detail.json()["version"]["canonical_contract"]
    )
    assert historical_contract.service == "auth"
    assert historical_detail.json()["version"]["contract_fingerprint"] == fingerprint_contract(
        historical_contract
    )
    historical_preview = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/preview",
        headers=headers,
        json={"environment_id": environment["id"], "version": 2},
    )
    assert historical_preview.status_code == 200, historical_preview.text
    assert historical_preview.json()["url"] == "https://auth.example.com/users/api"
    assert historical_preview.json()["target"]["service_key"] == "auth"
    pinned_definition = {
        "schema_version": "1.0",
        "variables": {},
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "config": {},
            },
            {
                "id": "request",
                "type": "api",
                "name": "Pinned request",
                "position": {"x": 180, "y": 0},
                "config": {
                    "api_definition_id": definition_id,
                    "api_version": 2,
                },
            },
            {
                "id": "end",
                "type": "end",
                "name": "End",
                "position": {"x": 360, "y": 0},
                "config": {},
            },
        ],
        "edges": [
            {"id": "start-request", "source": "start", "target": "request"},
            {"id": "request-end", "source": "request", "target": "end"},
        ],
        "settings": {
            "fail_fast": True,
            "concurrency": 1,
            "default_timeout_seconds": 30,
        },
    }
    pinned_workflow = await asset_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "Pinned auth API",
            "definition": pinned_definition,
        },
    )
    assert pinned_workflow.status_code == 201, pinned_workflow.text
    workflow_id = pinned_workflow.json()["id"]
    published = await asset_client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    pinned_plan = await asset_client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "Pinned auth plan",
            "schedule_interval_seconds": 60,
            "items": [
                {
                    "workflow_id": workflow_id,
                    "workflow_version": 1,
                    "environment_id": environment["id"],
                }
            ],
        },
    )
    assert pinned_plan.status_code == 201, pinned_plan.text
    pinned_definition["nodes"][1]["config"]["api_version"] = 3
    updated_draft = await asset_client.patch(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}",
        headers=headers,
        json={"expected_revision": 1, "definition": pinned_definition},
    )
    assert updated_draft.status_code == 200, updated_draft.text
    auth_impact = await asset_client.get(
        f"/api/v1/projects/{project_id}/services/{auth_id}/impact-preview",
        headers=headers,
    )
    orders_impact = await asset_client.get(
        f"/api/v1/projects/{project_id}/services/{order_id}/impact-preview",
        headers=headers,
    )
    assert auth_impact.status_code == 200, auth_impact.text
    assert orders_impact.status_code == 200, orders_impact.text
    assert {item["id"] for item in auth_impact.json()["affected_apis"]} == {definition_id}
    assert {item["id"] for item in auth_impact.json()["affected_workflows"]} == {workflow_id}
    assert {item["id"] for item in auth_impact.json()["affected_test_plans"]} == {
        pinned_plan.json()["id"]
    }
    assert {item["id"] for item in auth_impact.json()["affected_scheduled_runs"]} == {
        pinned_plan.json()["id"]
    }
    assert {item["id"] for item in orders_impact.json()["affected_workflows"]} == {workflow_id}
    assert orders_impact.json()["affected_test_plans"] == []
    restored = await asset_client.patch(
        f"/api/v1/projects/{project_id}/apis/{definition_id}",
        headers=headers,
        json={"service_id": auth_id},
    )
    assert restored.status_code == 200, restored.text
    preview = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/preview",
        headers=headers,
        json={
            "environment_id": environment["id"],
            "runtime_variables": {"layer": "node"},
            "runtime_headers": {"X-Layer": "node"},
        },
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["url"] == "https://auth.example.com/users/node"
    assert payload["target"]["service_key"] == "auth"
    assert payload["target"]["endpoint_variant"] == "default"
    assert payload["target"]["endpoint_revision"] == 1
    assert next(item for item in payload["variables"] if item["name"] == "layer") == {
        "name": "layer",
        "value": "node",
        "source": "runtime",
        "secret": False,
    }
    assert (
        next(item for item in payload["headers"] if item["name"].lower() == "x-layer")["source"]
        == "runtime"
    )

    overridden = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/preview",
        headers=headers,
        json={
            "environment_id": environment["id"],
            "service_override": "orders",
            "endpoint_variant": "canary",
        },
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["url"] == "https://orders-canary.example.com/users/api"
    assert overridden.json()["target"]["service_key"] == "orders"

    changed_environment = await asset_client.patch(
        f"/api/v1/projects/{project_id}/environments/{environment['id']}",
        headers=headers,
        json={"default_service_id": order_id},
    )
    assert changed_environment.status_code == 200, changed_environment.text
    legacy_api = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "Environment default API",
            "request": {"method": "GET", "path": "/health", "body_kind": "none"},
        },
    )
    assert legacy_api.status_code == 201, legacy_api.text
    legacy_definition_id = legacy_api.json()["definition"]["id"]
    legacy_preview = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{legacy_definition_id}/preview",
        headers=headers,
        json={"environment_id": environment["id"]},
    )
    assert legacy_preview.status_code == 200, legacy_preview.text
    assert legacy_preview.json()["target"]["service_key"] == "orders"
    assert legacy_preview.json()["url"] == "https://orders.example.com/health"
    bound_legacy = await asset_client.patch(
        f"/api/v1/projects/{project_id}/apis/{legacy_definition_id}",
        headers=headers,
        json={"service_id": auth_id},
    )
    assert bound_legacy.status_code == 200, bound_legacy.text
    pinned_unassigned_preview = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{legacy_definition_id}/preview",
        headers=headers,
        json={"environment_id": environment["id"], "version": 1},
    )
    assert pinned_unassigned_preview.status_code == 200, pinned_unassigned_preview.text
    assert pinned_unassigned_preview.json()["target"]["service_key"] == "orders"
    assert pinned_unassigned_preview.json()["url"] == "https://orders.example.com/health"
    bound_preview = await asset_client.post(
        f"/api/v1/projects/{project_id}/apis/{legacy_definition_id}/preview",
        headers=headers,
        json={"environment_id": environment["id"]},
    )
    assert bound_preview.status_code == 200, bound_preview.text
    assert bound_preview.json()["target"]["service_key"] == "auth"
    assert bound_preview.json()["url"] == "https://auth.example.com/health"
    pinned_definition["nodes"][1]["config"] = {
        "api_definition_id": legacy_definition_id,
        "api_version": 1,
    }
    unassigned_workflow = await asset_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "Pinned environment-default API",
            "definition": pinned_definition,
        },
    )
    assert unassigned_workflow.status_code == 201, unassigned_workflow.text
    unassigned_workflow_id = unassigned_workflow.json()["id"]
    unassigned_published = await asset_client.post(
        f"/api/v1/projects/{project_id}/workflows/{unassigned_workflow_id}/versions",
        headers=headers,
    )
    assert unassigned_published.status_code == 200, unassigned_published.text
    unassigned_plan = await asset_client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "Pinned environment-default plan",
            "schedule_interval_seconds": 60,
            "items": [
                {
                    "workflow_id": unassigned_workflow_id,
                    "workflow_version": 1,
                    "environment_id": environment["id"],
                }
            ],
        },
    )
    assert unassigned_plan.status_code == 201, unassigned_plan.text
    default_impact = await asset_client.get(
        f"/api/v1/projects/{project_id}/services/{order_id}/impact-preview",
        headers=headers,
    )
    assert default_impact.status_code == 200, default_impact.text
    default_impact_payload = default_impact.json()
    assert legacy_definition_id in {item["id"] for item in default_impact_payload["affected_apis"]}
    assert unassigned_workflow_id in {
        item["id"] for item in default_impact_payload["affected_workflows"]
    }
    assert unassigned_plan.json()["id"] in {
        item["id"] for item in default_impact_payload["affected_test_plans"]
    }
    assert unassigned_plan.json()["id"] in {
        item["id"] for item in default_impact_payload["affected_scheduled_runs"]
    }
    assert default_service_id != order_id


@pytest.mark.asyncio
async def test_service_target_management_update_and_connectivity(
    asset_client: AsyncClient,
) -> None:
    headers = await _login_headers(asset_client)
    project = await _create_project(asset_client, headers, name="Target management")
    environment = await _create_environment(
        asset_client,
        headers,
        project["id"],
        name="Connectivity",
        base_url="http://legacy.example.com",
        variables={},
        environment_headers={},
    )
    service_response = await asset_client.post(
        f"/api/v1/projects/{project['id']}/services",
        headers=headers,
        json={
            "service_key": "billing",
            "name": "Billing",
            "description": "Original",
            "owner_team": "payments",
            "service_type": "https",
        },
    )
    assert service_response.status_code == 201, service_response.text
    service_id = service_response.json()["id"]
    duplicate = await asset_client.post(
        f"/api/v1/projects/{project['id']}/services",
        headers=headers,
        json={"service_key": "billing", "name": "Duplicate"},
    )
    assert duplicate.status_code == 409

    updated_service = await asset_client.patch(
        f"/api/v1/projects/{project['id']}/services/{service_id}",
        headers=headers,
        json={
            "name": "Billing API",
            "description": "Updated",
            "owner_team": "platform",
            "enabled": False,
        },
    )
    assert updated_service.status_code == 200, updated_service.text
    assert updated_service.json()["owner_team"] == "platform"
    listed_services = await asset_client.get(
        f"/api/v1/projects/{project['id']}/services", headers=headers
    )
    assert listed_services.status_code == 200
    assert any(item["id"] == service_id for item in listed_services.json())
    impact_preview = await asset_client.get(
        f"/api/v1/projects/{project['id']}/services/{service_id}/impact-preview",
        headers=headers,
    )
    assert impact_preview.status_code == 200, impact_preview.text
    assert impact_preview.json() == {
        "strategy": "request_target_dependency_v1",
        "service_id": service_id,
        "service_key": "billing",
        "affected_apis": [],
        "affected_workflows": [],
        "affected_test_plans": [],
        "affected_scheduled_runs": [],
        "affected_release_gates": [],
    }

    endpoint_response = await asset_client.post(
        f"/api/v1/projects/{project['id']}/environments/{environment['id']}/service-endpoints",
        headers=headers,
        json={
            "service_id": service_id,
            "variant": "probe",
            "base_url": "https://billing.example.com/api",
            "health_check_path": "/health",
            "health_expected_status": 200,
        },
    )
    assert endpoint_response.status_code == 201, endpoint_response.text
    endpoint_id = endpoint_response.json()["id"]
    invalid_header = await asset_client.post(
        f"/api/v1/projects/{project['id']}/environments/{environment['id']}/service-endpoints",
        headers=headers,
        json={
            "service_id": service_id,
            "variant": "invalid-header",
            "base_url": "https://billing.example.com",
            "headers": {"Bad\nHeader": "value"},
        },
    )
    assert invalid_header.status_code == 422

    updated_endpoint = await asset_client.patch(
        f"/api/v1/projects/{project['id']}/service-endpoints/{endpoint_id}",
        headers=headers,
        json={
            "variant": "probe-v2",
            "base_url": "https://billing.example.com/api-v2",
            "enabled": False,
            "connect_timeout_ms": 1000,
            "read_timeout_ms": 2000,
            "tls_verify": False,
            "proxy_ref": "corp-proxy",
            "headers": {"X-Probe": "true"},
            "variables": {"region": "cn"},
            "secret_refs": ["billing-token"],
            "health_check_path": "/ready",
            "health_expected_status": 204,
        },
    )
    assert updated_endpoint.status_code == 200, updated_endpoint.text
    assert updated_endpoint.json()["revision"] == 2
    assert updated_endpoint.json()["variant"] == "probe-v2"

    all_endpoints = await asset_client.get(
        f"/api/v1/projects/{project['id']}/service-endpoints", headers=headers
    )
    assert all_endpoints.status_code == 200
    assert any(item["id"] == endpoint_id for item in all_endpoints.json())

    with respx.mock(assert_all_called=False) as mocked:
        mocked.head("https://billing.example.com/api-v2/ready").mock(
            return_value=httpx.Response(200)
        )
        connectivity = await asset_client.post(
            f"/api/v1/projects/{project['id']}/service-endpoints/{endpoint_id}/connectivity",
            headers=headers,
        )
    assert connectivity.status_code == 200, connectivity.text
    assert connectivity.json()["status"] == "unexpected_status"
    assert connectivity.json()["http_status"] == 200
