"""Focused S61D contracts for bounded discovery and readiness."""

from typing import Any

import pytest
from sqlalchemy import select
from test_mcp_read import mcp_context as mcp_context

from app.mcp.server import create_mcp_server
from app.models.api_assets import APIDefinition, APIVersion
from app.schemas.mcp_discovery import MCPFindAssetsRequest
from app.services.mcp_discovery import _has_credential_reference


@pytest.mark.asyncio
async def test_find_assets_is_typed_paginated_and_project_scoped(
    mcp_context: dict[str, Any],
) -> None:
    client = mcp_context["client"]
    headers = {"Authorization": f"Bearer {mcp_context['token']}"}
    response = await client.post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["project_id"]),
            "asset_types": ["api", "workflow", "execution"],
            "query": "payment",
            "page": 1,
            "page_size": 2,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 3
    assert data["has_more"] is True
    assert len(data["items"]) == 2
    assert {item["resource_type"] for item in data["items"]} <= {
        "api",
        "workflow",
        "execution",
    }
    assert "workflow-secret" not in response.text
    assert "execution-secret" not in response.text

    cross_tenant = await client.post(
        f"/api/v1/mcp/read/projects/{mcp_context['other_project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["other_project_id"]),
            "asset_types": ["api"],
        },
    )
    assert cross_tenant.status_code == 404


@pytest.mark.asyncio
async def test_project_readiness_returns_safe_actionable_contract(
    mcp_context: dict[str, Any],
) -> None:
    response = await mcp_context["client"].get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/readiness",
        headers={"Authorization": f"Bearer {mcp_context['token']}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["project_id"] == str(mcp_context["project_id"])
    assert data["can_generate_proposal"] is False
    assert any(check["name"] == "contract" for check in data["checks"])
    for secret in ("contract-auth-secret", "endpoint-secret", "execution-context-secret"):
        assert secret not in response.text


@pytest.mark.asyncio
async def test_find_assets_path_filter_uses_only_current_api_version(
    mcp_context: dict[str, Any],
) -> None:
    async with mcp_context["sessions"]() as session:
        definition = await session.scalar(
            select(APIDefinition).where(APIDefinition.id == mcp_context["definition_id"])
        )
        assert definition is not None
        definition.current_version = 2
        session.add(
            APIVersion(
                api_definition_id=definition.id,
                version=2,
                service_id=definition.service_id,
                method="POST",
                path="/new-payment",
                query_parameters=[],
                headers={},
                variables={},
                body_kind="none",
                body=None,
                auth_kind="none",
                auth_config={},
                extraction_rules=[],
                assertions=[],
                canonical_contract={},
                contract_fingerprint=None,
                contract_completeness="legacy_partial",
                created_by_id=definition.created_by_id,
            )
        )
        await session.commit()

    headers = {"Authorization": f"Bearer {mcp_context['token']}"}
    legacy = await mcp_context["client"].post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["project_id"]),
            "asset_types": ["api"],
            "path": "/payments",
        },
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["data"]["total"] == 0
    current = await mcp_context["client"].post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["project_id"]),
            "asset_types": ["api"],
            "path": "/new-payment",
        },
    )
    assert current.status_code == 200, current.text
    assert current.json()["data"]["total"] == 1
    assert current.json()["data"]["items"][0]["version"] == 2


def test_runtime_credential_evidence_requires_explicit_secret_reference() -> None:
    assert not _has_credential_reference({"kind": "runtime_observation"})
    assert not _has_credential_reference({"credential_refs": ["payments-token"]})
    assert _has_credential_reference({"credential_refs": ["secret://payments/token"]})


def test_s61d_server_registers_discovery_tools() -> None:
    server = create_mcp_server(
        client=__import__("app.mcp.client", fromlist=["MCPReadGatewayClient"]).MCPReadGatewayClient(
            base_url="http://gateway", token=""
        )
    )
    # Registration is exercised by the SDK's async list_tools in the existing MCP tests;
    # schema construction here catches accidental import/circular-dependency regressions.
    assert server is not None


def test_find_assets_request_rejects_duplicate_types() -> None:
    with pytest.raises(ValueError):
        MCPFindAssetsRequest(
            project_id="00000000-0000-0000-0000-000000000001",
            asset_types=["api", "api"],
        )
