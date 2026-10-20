import socket
from dataclasses import dataclass, field
from typing import Never
from uuid import uuid4

import pytest
import respx
from httpx import AsyncClient
from test_api_assets_api import _create_environment, _create_project, _login_headers
from test_api_assets_api import asset_client as asset_client

from app.core.encryption import SecretBox


@dataclass(frozen=True)
class PreviewAssets:
    client: AsyncClient = field(repr=False)
    headers: dict[str, str] = field(repr=False)
    root: str
    environment_id: str
    service_id: str
    default_service_id: str
    endpoint_id: str
    api_id: str
    unbound_api_id: str


@pytest.fixture
async def preview_assets(asset_client: AsyncClient) -> PreviewAssets:
    headers = await _login_headers(asset_client)
    project = await _create_project(asset_client, headers)
    root = f"/api/v1/projects/{project['id']}"
    environment = await _create_environment(
        asset_client,
        headers,
        project["id"],
        name="预览环境",
        base_url="https://legacy.example.test/gateway",
        variables={"id": "42"},
        environment_headers={},
    )
    secret = await asset_client.put(
        f"{root}/secrets",
        headers=headers,
        json={
            "name": "token",
            "value": "synthetic-preview-credential",
            "environment_id": environment["id"],
        },
    )
    assert secret.status_code == 200, secret.text
    service = await asset_client.post(
        f"{root}/services",
        headers=headers,
        json={"service_key": "orders", "name": "订单服务"},
    )
    assert service.status_code == 201, service.text
    endpoint = await asset_client.post(
        f"{root}/environments/{environment['id']}/service-endpoints",
        headers=headers,
        json={
            "service_id": service.json()["id"],
            "base_url": "https://orders.example.test/v1",
            "variables": {"module": "orders"},
            "secret_refs": ["token"],
            "headers": {"Authorization": "{{secret.token}}"},
        },
    )
    assert endpoint.status_code == 201, endpoint.text
    api = await asset_client.post(
        f"{root}/apis",
        headers=headers,
        json={
            "name": "订单查询",
            "service_id": service.json()["id"],
            "request": {
                "method": "GET",
                "path": "/{{module}}/{{id}}",
                "query_parameters": [{"name": "q", "value": "{{id}}", "enabled": True}],
            },
        },
    )
    assert api.status_code == 201, api.text
    unbound = await asset_client.post(
        f"{root}/apis",
        headers=headers,
        json={"name": "继承环境", "request": {"method": "GET", "path": "/health"}},
    )
    assert unbound.status_code == 201, unbound.text
    return PreviewAssets(
        asset_client,
        headers,
        root,
        environment["id"],
        service.json()["id"],
        environment["default_service_id"],
        endpoint.json()["id"],
        api.json()["definition"]["id"],
        unbound.json()["definition"]["id"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["off", pytest.param("on", marks=pytest.mark.redaction_on)])
@respx.mock
async def test_endpoint_candidate_matches_actual_resolution_without_side_effects(
    preview_assets: PreviewAssets, monkeypatch: pytest.MonkeyPatch, policy: str
) -> None:
    fixture = preview_assets

    def forbidden_decrypt(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Configuration preview must not decrypt secrets")

    def forbidden_network(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Configuration preview must not perform DNS")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)
    original_decrypt = SecretBox.decrypt
    monkeypatch.setattr(SecretBox, "decrypt", forbidden_decrypt)
    response = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={
            "environment_id": fixture.environment_id,
            "api_id": fixture.api_id,
            "change": {
                "kind": "endpoint",
                "endpoint_id": fixture.endpoint_id,
                "base_url": "https://new.example.test/gateway",
                "variables": {"module": "billing"},
            },
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["before"]["url"] == "https://orders.example.test/v1/orders/42?q=42"
    assert result["after"]["url"] == "https://new.example.test/gateway/billing/42?q=42"
    assert result["persisted"] is result["network_checked"] is False
    assert "Authorization" not in response.text and "secret.token" not in response.text
    assert "synthetic-preview-credential" not in response.text
    stored = await fixture.client.get(
        f"{fixture.root}/environments/{fixture.environment_id}/service-endpoints",
        headers=fixture.headers,
    )
    endpoint = next(item for item in stored.json() if item["id"] == fixture.endpoint_id)
    assert endpoint["base_url"] == "https://orders.example.test/v1" and endpoint["revision"] == 1
    assert endpoint["variables"] == {"module": "orders"}
    monkeypatch.setattr(SecretBox, "decrypt", original_decrypt)
    # Explicitly save only after proving the read-only postcondition.
    saved = await fixture.client.patch(
        f"{fixture.root}/service-endpoints/{fixture.endpoint_id}",
        headers=fixture.headers,
        json={"base_url": "https://new.example.test/gateway", "variables": {"module": "billing"}},
    )
    assert saved.status_code == 200, saved.text
    actual = await fixture.client.post(
        f"{fixture.root}/apis/{fixture.api_id}/preview",
        headers=fixture.headers,
        json={"environment_id": fixture.environment_id},
    )
    assert actual.status_code == 200, actual.text
    assert actual.json()["url"] == result["after"]["url"]


@pytest.mark.asyncio
async def test_candidate_binding_preserves_pinned_versions(preview_assets: PreviewAssets) -> None:
    fixture = preview_assets
    change = {
        "kind": "api_binding",
        "api_id": fixture.api_id,
        "service_id": fixture.default_service_id,
    }
    context = {"environment_id": fixture.environment_id, "api_id": fixture.api_id, "change": change}
    # This API needs an endpoint variable absent on the fallback service.
    preview = await fixture.client.post(
        f"{fixture.root}/request-targets/preview", headers=fixture.headers, json=context
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["after"]["status"] == "unavailable"
    assert preview.json()["after"]["error"]["trace_id"]
    pinned = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={**context, "api_version": 1},
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["after"] == pinned.json()["before"]
    detail = await fixture.client.get(
        f"{fixture.root}/apis/{fixture.api_id}", headers=fixture.headers
    )
    assert detail.json()["definition"]["current_version"] == 1
    assert detail.json()["version"]["service_id"] == fixture.service_id


@pytest.mark.asyncio
async def test_environment_candidate_and_node_override_follow_resolver_precedence(
    preview_assets: PreviewAssets,
) -> None:
    fixture = preview_assets
    context = {
        "environment_id": fixture.environment_id,
        "api_id": fixture.unbound_api_id,
        "change": {
            "kind": "environment_default",
            "environment_id": fixture.environment_id,
            "service_id": fixture.service_id,
        },
    }
    preview = await fixture.client.post(
        f"{fixture.root}/request-targets/preview", headers=fixture.headers, json=context
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["before"]["url"] == "https://legacy.example.test/gateway/health"
    assert preview.json()["after"]["url"] == "https://orders.example.test/v1/health"
    overridden = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={**context, "service_override": "default"},
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["before"] == overridden.json()["after"]
    cleared = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={**context, "change": {**context["change"], "service_id": None}},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["after"]["service_key"] == "legacy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code",
    [
        ({"enabled": False}, "SERVICE_ENDPOINT_DISABLED"),
        ({"variant": "renamed"}, "SERVICE_ENDPOINT_NOT_FOUND"),
        ({"base_url": "https://user:password@example.test"}, "PREVIEW_TARGET_INVALID"),
    ],
)
async def test_invalid_candidate_does_not_fall_back_or_save(
    preview_assets: PreviewAssets, change: dict[str, object], code: str
) -> None:
    fixture = preview_assets
    response = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={
            "environment_id": fixture.environment_id,
            "api_id": fixture.api_id,
            "change": {"kind": "endpoint", "endpoint_id": fixture.endpoint_id, **change},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["before"]["status"] == "resolved"
    assert response.json()["after"]["url"] is None
    assert response.json()["after"]["error"]["code"] == code
    assert response.json()["after"]["error"]["trace_id"]


@pytest.mark.asyncio
async def test_preview_requires_project_owned_context_and_reports_missing_context(
    preview_assets: PreviewAssets,
) -> None:
    fixture = preview_assets
    change = {"kind": "service", "service_id": fixture.service_id, "enabled": False}
    missing = await fixture.client.post(
        f"{fixture.root}/request-targets/preview", headers=fixture.headers, json={"change": change}
    )
    assert missing.status_code == 200, missing.text
    assert missing.json()["after"]["error"]["code"] == "PREVIEW_CONTEXT_MISSING"
    for context in [{"api_id": str(uuid4())}, {"environment_id": str(uuid4())}]:
        response = await fixture.client.post(
            f"{fixture.root}/request-targets/preview",
            headers=fixture.headers,
            json={"change": change, **context},
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_preview_rejects_foreign_candidates_and_duplicate_variants(
    preview_assets: PreviewAssets,
) -> None:
    fixture = preview_assets
    foreign = await _create_project(fixture.client, fixture.headers, name="隔离项目")
    foreign_root = f"/api/v1/projects/{foreign['id']}"
    service = await fixture.client.post(
        f"{foreign_root}/services",
        headers=fixture.headers,
        json={"service_key": "foreign", "name": "其他项目服务"},
    )
    assert service.status_code == 201, service.text
    response = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={"change": {"kind": "service", "service_id": service.json()["id"], "enabled": False}},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["trace_id"]
    duplicate = await fixture.client.post(
        f"{fixture.root}/environments/{fixture.environment_id}/service-endpoints",
        headers=fixture.headers,
        json={
            "service_id": fixture.service_id,
            "variant": "canary",
            "base_url": "https://canary.example.test",
        },
    )
    assert duplicate.status_code == 201, duplicate.text
    response = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={
            "change": {"kind": "endpoint", "endpoint_id": fixture.endpoint_id, "variant": "canary"}
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "SERVICE_ENDPOINT_EXISTS"


@pytest.mark.asyncio
async def test_preview_authorizes_viewer_without_granting_writes(
    preview_assets: PreviewAssets,
) -> None:
    fixture = preview_assets
    viewer = await fixture.client.post(
        "/api/v1/users",
        headers=fixture.headers,
        json={
            "email": "target-viewer@example.com",
            "display_name": "只读预览",
            "password": "viewer-password-123!",
            "is_system_admin": False,
        },
    )
    assert viewer.status_code == 201, viewer.text
    membership = await fixture.client.put(
        f"{fixture.root}/members/{viewer.json()['id']}",
        headers=fixture.headers,
        json={"user_id": viewer.json()["id"], "role": "viewer"},
    )
    assert membership.status_code == 200, membership.text
    login = await fixture.client.post(
        "/api/v1/auth/login",
        json={"email": "target-viewer@example.com", "password": "viewer-password-123!"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    changed = await fixture.client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": "viewer-password-123!",
            "new_password": "changed-viewer-password-123!",
        },
    )
    assert changed.status_code == 204, changed.text
    preview = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=headers,
        json={
            "environment_id": fixture.environment_id,
            "api_id": fixture.unbound_api_id,
            "change": {"kind": "service", "service_id": fixture.service_id, "enabled": False},
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["persisted"] is False
    impact = await fixture.client.post(
        f"{fixture.root}/request-targets/impact-preview",
        headers=headers,
        json={"change": {"kind": "service", "service_id": fixture.service_id, "enabled": False}},
    )
    assert impact.status_code == 200, impact.text
    assert impact.json()["complete"] is True and impact.json()["trace_id"]
    denied = await fixture.client.patch(
        f"{fixture.root}/services/{fixture.service_id}",
        headers=headers,
        json={"enabled": False},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["trace_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["changed", "unchanged"])
async def test_binding_preview_matches_new_version_and_preserves_historical_resolution(
    preview_assets: PreviewAssets,
    binding: str,
) -> None:
    fixture = preview_assets
    service_id = fixture.service_id if binding == "changed" else None
    preview = await fixture.client.post(
        f"{fixture.root}/request-targets/preview",
        headers=fixture.headers,
        json={
            "environment_id": fixture.environment_id,
            "api_id": fixture.unbound_api_id,
            "change": {
                "kind": "api_binding",
                "api_id": fixture.unbound_api_id,
                "service_id": service_id,
            },
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["before"]["api_version"] == 1
    assert preview.json()["after"]["api_version"] == 2
    saved = await fixture.client.patch(
        f"{fixture.root}/apis/{fixture.unbound_api_id}",
        headers=fixture.headers,
        json={"service_id": service_id},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["current_version"] == 2
    for version, key in [(1, "before"), (2, "after")]:
        actual = await fixture.client.post(
            f"{fixture.root}/apis/{fixture.unbound_api_id}/preview",
            headers=fixture.headers,
            json={"environment_id": fixture.environment_id, "version": version},
        )
        assert actual.status_code == 200, actual.text
        assert actual.json()["url"] == preview.json()[key]["url"]
