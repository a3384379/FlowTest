from typing import Any
from uuid import UUID

import pytest
import respx
from httpx import Response
from sqlalchemy import func, select
from test_s51_mcp_flow_proposals import (
    _plan_chain,
    _proposal_payload,
    s51_context,  # noqa: F401 - imported pytest fixture
)

from app.models.sandbox_preview import SandboxPreviewApproval
from app.models.workflows import WorkflowExecution
from app.services.workflows import WorkflowService


@pytest.mark.asyncio
async def test_accepted_proposal_requires_sandbox_and_consumes_approval_once(
    s51_context: dict[str, Any],  # noqa: F811 - pytest injects the imported fixture
) -> None:
    test_context, plan, compilation = await _plan_chain(s51_context, with_cleanup=True)
    client = s51_context["client"]
    proposed = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={**s51_context["mcp_headers"], "Idempotency-Key": "s55-proposal"},
        json={
            **_proposal_payload(s51_context, test_context, plan, compilation),
            "dry_run": False,
        },
    )
    assert proposed.status_code == 202, proposed.text
    change_set_id = proposed.json()["change_set_id"]
    reviewed = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/review",
        headers=s51_context["user_headers"],
        json={"accept": True, "note": "S55 sandbox preview review"},
    )
    assert reviewed.status_code == 200, reviewed.text

    production = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/preview-approvals",
        headers=s51_context["user_headers"],
        json={
            "environment_id": str(s51_context["production_environment_id"]),
            "executor_service_account_id": str(s51_context["service_account_id"]),
        },
    )
    assert production.status_code == 403
    assert production.json()["error"]["code"] == "PRODUCTION_PREVIEW_FORBIDDEN"

    approved = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/preview-approvals",
        headers=s51_context["user_headers"],
        json={
            "environment_id": str(s51_context["sandbox_environment_id"]),
            "executor_service_account_id": str(s51_context["service_account_id"]),
            "budget": {
                "max_nodes": 100,
                "max_requests": 10,
                "max_dataset_rows": 20,
                "max_parallelism": 2,
                "max_runtime_seconds": 120,
            },
        },
    )
    assert approved.status_code == 201, approved.text
    approval_id = approved.json()["id"]
    execute_payload = {
        "project_id": str(s51_context["project_id"]),
        "environment_id": str(s51_context["sandbox_environment_id"]),
        "approval_id": approval_id,
        "runtime_variables": {},
        "runtime_headers": {},
    }
    execution_headers = {
        **s51_context["mcp_headers"],
        "Idempotency-Key": "s55-preview-execution",
    }
    executed = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers=execution_headers,
        json=execute_payload,
    )
    assert executed.status_code == 202, executed.text
    execution = executed.json()["execution"]
    assert execution["run_purpose"] == "preview"
    assert execution["workflow_id"] is None
    assert execution["workflow_version_id"] is None
    assert execution["source_change_set_id"] == change_set_id
    assert execution["preview_approval_id"] == approval_id
    assert execution["preview_budget"]["max_requests"] == 10
    assert execution["preview_evidence"]["proposal_fingerprint"]
    assert execution["preview_evidence"]["context_fingerprint"]

    repeated = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers=execution_headers,
        json=execute_payload,
    )
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["execution"]["id"] == execution["id"]

    replayed = await client.post(
        f"/api/v1/mcp/flow/proposals/{change_set_id}/preview-executions",
        headers={**s51_context["mcp_headers"], "Idempotency-Key": "s55-preview-replay"},
        json=execute_payload,
    )
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] == "PREVIEW_APPROVAL_REPLAYED"

    async with s51_context["sessions"]() as session:
        approval = await session.get(SandboxPreviewApproval, UUID(approval_id))
        assert approval is not None and approval.consumed_at is not None
        assert str(approval.execution_id) == execution["id"]
        assert await session.scalar(select(func.count()).select_from(WorkflowExecution)) == 1
    assert len(s51_context["coordinator"].plans) == 1
    dispatched = s51_context["coordinator"].plans[0]
    assert dispatched.request_budget == 10
    assert dispatched.definition.settings.concurrency == 2
    assert dispatched.definition.run_policy.max_runtime_seconds == 120
    assert any(node.phase.value == "cleanup" for node in dispatched.definition.nodes)

    with respx.mock:
        request = respx.get("https://sandbox.example.test/health").mock(
            side_effect=[Response(200, json={"phase": "main"}), Response(200, json={})]
        )
        async with s51_context["sessions"]() as session:
            model = await session.get(WorkflowExecution, UUID(execution["id"]))
            assert model is not None
            completed, nodes = await WorkflowService(session).run_prepared(
                execution=model,
                plan=dispatched,
            )
    assert request.call_count == 2
    assert completed.status == "passed"
    assert completed.cleanup_status == "passed"
    assert len(nodes) >= 2
    assert completed.preview_evidence["execution_snapshot"]
    assert completed.preview_evidence["cleanup_result"]["activated_node_ids"] == ["cleanup-health"]
    assert completed.preview_evidence["cleanup_result"]["required_failures"] == []
    assert completed.preview_evidence["budget_usage"]["requests"] == {
        "limit": 10,
        "used": 2,
        "remaining": 8,
    }
    assert completed.preview_evidence["redactions"] == []

    report = await client.get(
        f"/api/v1/projects/{s51_context['project_id']}/reports/executions/{execution['id']}",
        headers=s51_context["user_headers"],
    )
    assert report.status_code == 200, report.text
    assert report.json()["summary"]["workflow_id"] is None
    assert report.json()["summary"]["workflow_name"] == "Sandbox Preview"
