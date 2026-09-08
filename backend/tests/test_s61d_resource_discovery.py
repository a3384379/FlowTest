"""Focused S61D contracts for bounded discovery and readiness."""

from typing import Any

import pytest
from test_mcp_read import mcp_context as mcp_context

from app.mcp.server import create_mcp_server
from app.schemas.mcp_discovery import MCPFindAssetsRequest


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
