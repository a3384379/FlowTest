from typing import Any

import pytest
from httpx import ASGITransport
from sqlalchemy import select
from test_mcp_read import mcp_context as mcp_context
from test_s49_context_evidence import _evidence_envelope
from test_s60_continuous_mcp import _account, _counts

from app.main import app
from app.mcp.client import MCPReadGatewayClient
from app.mcp.server import create_mcp_server
from app.models.ai import AIChangeSet


@pytest.mark.asyncio
async def test_onboarding_skill_real_tools_preserve_missing_evidence_and_revision(
    mcp_context: dict[str, Any],
) -> None:
    fixture = mcp_context
    _, token = await _account(fixture, ["mcp:read", "mcp:evidence:write"])
    project_id = str(fixture["project_id"])
    async with MCPReadGatewayClient(
        base_url="http://test", token=token, transport=ASGITransport(app=app)
    ) as gateway:
        server = create_mcp_server(client=gateway)
        begun = (
            await server.call_tool(
                "flowtest.begin_test_context",
                {
                    "project_id": project_id,
                    "name": "接入测试项目",
                    "objective": "盘点契约证据缺口",
                    "required_evidence": ["contract"],
                },
            )
        ).structured_content
        assert begun["revision"]["snapshot"]["completeness"]["complete"] is False, begun
        context_id = begun["id"]
        missing = (
            await server.call_tool(
                "flowtest.inspect_context_requirements", {"context_id": context_id}
            )
        ).structured_content
        assert missing["missing"] == ["contract"], missing
        evidence = _evidence_envelope(project_id=project_id, statement="成功响应包含支付记录标识")
        ingested = (
            await server.call_tool(
                "flowtest.ingest_external_evidence",
                {"context_id": context_id, "envelope": evidence},
            )
        ).structured_content
        assert "error" not in ingested.get("data", {}), ingested
        inspected = (
            await server.call_tool("flowtest.inspect_test_context", {"context_id": context_id})
        ).structured_content
        assert inspected["revision"]["revision"] > begun["revision"]["revision"]
        assert inspected["revision"]["snapshot"]["completeness"]["complete"] is True
        assert inspected["revision"]["fingerprint"] != begun["revision"]["fingerprint"]
    async with fixture["sessions"]() as session:
        assert await session.scalar(select(AIChangeSet.id)) is None


@pytest.mark.asyncio
async def test_coverage_skill_real_generation_to_pending_design(
    mcp_context: dict[str, Any],
) -> None:
    fixture = mcp_context
    _, token = await _account(fixture, ["mcp:read", "mcp:write"])
    selection = {
        "project_id": str(fixture["project_id"]),
        "api_definition_id": str(fixture["definition_id"]),
    }
    async with MCPReadGatewayClient(
        base_url="http://test",
        token=token,
        transport=ASGITransport(app=app, raise_app_exceptions=False),
    ) as gateway:
        server = create_mcp_server(client=gateway)
        coverage = (
            await server.call_tool("flowtest.analyze_test_coverage", selection)
        ).structured_content
        assert coverage["data"]["entries"]
        generated = (
            await server.call_tool("flowtest.generate_test_design", selection)
        ).structured_content
        assert generated["data"]["persisted"] is False
        request = {
            "project_id": selection["project_id"],
            "title": "契约覆盖补全",
            "confidence": 0.8,
            "risk_level": "medium",
            "design": generated["data"]["design"],
            "idempotency_key": "s60-coverage-design",
        }
        before = await _counts(fixture)
        dry = (await server.call_tool("flowtest.propose_test_design", request)).structured_content
        assert dry["data"]["persisted"] is False, dry
        assert await _counts(fixture) == before
        created = (
            await server.call_tool("flowtest.propose_test_design", {**request, "dry_run": False})
        ).structured_content
        assert created["data"]["status"] == "draft", created
        assert all(item["review_status"] == "pending" for item in created["data"]["items"])
        repeated = (
            await server.call_tool("flowtest.propose_test_design", {**request, "dry_run": False})
        ).structured_content
        assert repeated["data"]["id"] == created["data"]["id"]


@pytest.mark.parametrize(
    "operation", ["failure-diagnosis", "change-regression", "context-diff", "affected-flows"]
)
@pytest.mark.asyncio
async def test_continuous_reads_reject_cross_tenant_projects(
    mcp_context: dict[str, Any], operation: str
) -> None:
    fixture = mcp_context
    request = {"project_id": str(fixture["other_project_id"])}
    if operation == "failure-diagnosis":
        request["execution_id"] = str(fixture["execution_id"])
    elif operation == "change-regression":
        request["run_id"] = str(fixture["execution_id"])
    else:
        request.update(context_id=str(fixture["execution_id"]), before_revision=1, after_revision=2)
    result = await fixture["client"].post(
        f"/api/v1/mcp/continuous/{operation}",
        headers={"Authorization": f"Bearer {fixture['token']}"},
        json=request,
    )
    assert result.status_code == 404, result.text
    assert result.json()["error"]["trace_id"]
