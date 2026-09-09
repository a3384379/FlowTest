from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_s51_mcp_flow_proposals import RecordingWorkflowCoordinator
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api
from test_s59d_change_regression import _bound

from app.api.dependencies import get_workflow_coordinator
from app.core.config import settings
from app.main import app
from app.mcp.client import MCPReadGatewayClient
from app.mcp.server import create_mcp_server
from app.models.access import User
from app.models.ai import AIChangeSet
from app.models.change_regression import ChangeRegressionRun
from app.models.governance import IdempotencyRecord
from app.models.sandbox_preview import SandboxPreviewApproval
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.services.change_regression import ChangeRegressionService
from app.services.service_accounts import ServiceAccountService

pytestmark = pytest.mark.redaction_on


async def _account(fixture: dict[str, Any], scopes: list[str]) -> tuple[UUID, str]:
    async with fixture["sessions"]() as session:
        actor = await session.scalar(select(User))
        key = f"s60-{uuid4().hex[:12]}"
        issued = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=fixture["organization_id"],
            name=key,
            account_key=key,
            scopes=scopes,
            expires_at=None,
            metadata={},
        )
        return issued.account.id, issued.token


async def _repair(fixture: dict[str, Any]) -> dict[str, Any]:
    exported = await fixture["client"].get(
        f"/api/v1/projects/{fixture['project_id']}/flow-specs/workflows/{fixture['workflow_id']}/export",
        headers=fixture["headers"],
    )
    assert exported.status_code == 200, exported.text
    spec = exported.json()["spec"]
    spec["variables"] = {"customer_id": "fixture-customer"}
    return {
        "project_id": str(fixture["project_id"]),
        "execution_id": str(fixture["execution_id"]),
        "repair": {
            "kind": "data",
            "proposed_spec": spec,
            "expected_target_revision": 1,
            "context_revision_id": str(fixture["context_revision_id"]),
            "rationale": "补全失败执行所需的确定性测试数据",
        },
    }


async def _counts(fixture: dict[str, Any]) -> tuple[int, int]:
    async with fixture["sessions"]() as session:
        return (
            await session.scalar(select(func.count()).select_from(AIChangeSet)),
            await session.scalar(select(func.count()).select_from(IdempotencyRecord)),
        )


@pytest.mark.asyncio
async def test_mcp_repair_dry_run_persist_retry_and_scope(
    failure_repair_api: dict[str, Any],
) -> None:
    fixture = failure_repair_api
    _, token = await _account(fixture, ["mcp:read", "mcp:flow:propose"])
    payload = await _repair(fixture)
    headers = {"Authorization": f"Bearer {token}"}
    before = await _counts(fixture)
    async with MCPReadGatewayClient(
        base_url="http://test",
        token=token,
        transport=ASGITransport(app=app, raise_app_exceptions=False),
    ) as client:
        server = create_mcp_server(client=client)
        tools = {item.name: item for item in await server.list_tools()}
        assert "ctx" not in tools["flowtest.propose_repair"].input_schema["properties"]
        diagnosis = await server.call_tool(
            "flowtest.diagnose_failure",
            {"request": {key: payload[key] for key in ("project_id", "execution_id")}},
        )
        assert diagnosis.structured_content["data"]["diagnosis"]["repair_policy"][
            "allowed_kinds"
        ] == ["data", "binding"]
        dry = await server.call_tool("flowtest.propose_repair", {"request": payload})
        assert dry.structured_content["dry_run"] is True, dry
        assert dry.structured_content["change_set_id"] is None
        assert await _counts(fixture) == before
        persisted = await server.call_tool(
            "flowtest.propose_repair",
            {"request": {**payload, "dry_run": False}, "idempotency_key": "s60-repair-persist"},
        )
        assert persisted.structured_content["dry_run"] is False, persisted
        proposal_id = persisted.structured_content["change_set_id"]
        again = await server.call_tool(
            "flowtest.propose_repair",
            {"request": {**payload, "dry_run": False}, "idempotency_key": "s60-repair-persist"},
        )
        assert again.structured_content["change_set_id"] == proposal_id
        assert again.structured_content["requires_human_review"] is True
        assert again.structured_content["applied"] is False
    assert await _counts(fixture) == (before[0] + 1, before[1] + 1)
    # Human JWTs cannot masquerade as scoped MCP service accounts.
    denied = await fixture["client"].post(
        "/api/v1/mcp/continuous/repair-proposals", headers=fixture["headers"], json=payload
    )
    assert denied.status_code == 401
    _, read_token = await _account(fixture, ["mcp:read"])
    denied = await fixture["client"].post(
        "/api/v1/mcp/continuous/repair-proposals",
        headers={"Authorization": f"Bearer {read_token}"},
        json=payload,
    )
    assert denied.status_code == 403
    # Service accounts with proposal scope do not get an Accept endpoint.
    review = await fixture["client"].post(
        f"/api/v1/projects/{fixture['project_id']}/flow-specs/change-sets/{proposal_id}/review",
        headers=headers,
        json={"accept": True, "note": "not permitted through MCP"},
    )
    assert review.status_code == 401


@pytest.mark.asyncio
async def test_mcp_maintenance_is_bound_and_atomic(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = failure_repair_api
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    _, payload, bound = await _bound(fixture)
    account_id, token = await _account(fixture, ["mcp:read", "mcp:flow:propose"])
    request = {
        "project_id": str(fixture["project_id"]),
        "run_id": bound["id"],
        "workflow_id": str(fixture["workflow_id"]),
        "maintenance": payload,
    }
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "s60-maintenance-persist"}
    root = "/api/v1/mcp/continuous"
    comparison = {
        "project_id": str(fixture["project_id"]),
        **{key: payload[key] for key in ("context_id", "before_revision", "after_revision")},
    }
    for path in ("context-diff", "affected-flows"):
        result = await fixture["client"].post(f"{root}/{path}", headers=headers, json=comparison)
        assert result.status_code == 200, result.text
        assert result.json()["trace_id"]

    async def forbidden_sync(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("MCP inspection advanced execution")

    monkeypatch.setattr(ChangeRegressionService, "_sync_execution", forbidden_sync)
    inspected = await fixture["client"].post(
        f"{root}/change-regression",
        headers=headers,
        json={"project_id": request["project_id"], "run_id": request["run_id"]},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["data"]["preview_counts_as_execution"] is False
    before = await _counts(fixture)
    dry = await fixture["client"].post(
        f"{root}/maintenance-proposals", headers=headers, json=request
    )
    assert dry.status_code == 200, dry.text
    assert await _counts(fixture) == before
    commit = AsyncSession.commit

    async def fail_completion(session: AsyncSession) -> None:
        if any(
            isinstance(item, IdempotencyRecord) and item.status == "completed"
            for item in session.identity_map.values()
        ):
            raise RuntimeError("injected commit failure")
        await commit(session)

    monkeypatch.setattr(AsyncSession, "commit", fail_completion)
    failed = await fixture["client"].post(
        f"{root}/maintenance-proposals", headers=headers, json={**request, "dry_run": False}
    )
    assert failed.status_code == 500
    assert await _counts(fixture) == before
    monkeypatch.setattr(AsyncSession, "commit", commit)
    created = await fixture["client"].post(
        f"{root}/maintenance-proposals", headers=headers, json={**request, "dry_run": False}
    )
    assert created.status_code == 200, created.text
    repeated = await fixture["client"].post(
        f"{root}/maintenance-proposals", headers=headers, json={**request, "dry_run": False}
    )
    assert repeated.json()["change_set_id"] == created.json()["change_set_id"]
    async with fixture["sessions"]() as session:
        run = await session.get(ChangeRegressionRun, UUID(bound["id"]))
        proposals = run.selection_summary["context_maintenance"]["proposals"]
        assert [item["change_set_id"] for item in proposals] == [created.json()["change_set_id"]]
        claim = await session.scalar(select(IdempotencyRecord))
        assert claim.actor_key == f"service-account:{account_id}"


@pytest.mark.parametrize(
    "mutation", ["foreign_project", "stale_target", "sensitive", "product_defect", "missing_key"]
)
@pytest.mark.asyncio
async def test_mcp_repair_rejections_do_not_claim(
    failure_repair_api: dict[str, Any], mutation: str
) -> None:
    fixture = failure_repair_api
    _, token = await _account(fixture, ["mcp:flow:propose"])
    payload = {**await _repair(fixture), "dry_run": False}
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "s60-invalid-repair"}
    if mutation == "foreign_project":
        payload["project_id"] = str(uuid4())
    elif mutation == "stale_target":
        payload["repair"]["expected_target_revision"] = 999
    elif mutation == "sensitive":
        payload["repair"]["proposed_spec"]["variables"] = {"password": "private-repair-value"}
    elif mutation == "missing_key":
        headers.pop("Idempotency-Key")
    else:
        async with fixture["sessions"]() as session:
            execution = await session.get(WorkflowExecution, fixture["execution_id"])
            execution.error_code = "WORKFLOW_ASSERTION_FAILED"
            node = await session.scalar(
                select(WorkflowNodeExecution).where(
                    WorkflowNodeExecution.workflow_execution_id == execution.id,
                    WorkflowNodeExecution.status == "failed",
                )
            )
            node.error_code = "WORKFLOW_ASSERTION_FAILED"
            await session.commit()
    before = await _counts(fixture)
    result = await fixture["client"].post(
        "/api/v1/mcp/continuous/repair-proposals", headers=headers, json=payload
    )
    assert result.status_code in {403, 404, 409, 422}, result.text
    assert "private-repair-value" not in result.text
    assert await _counts(fixture) == before


@pytest.mark.asyncio
async def test_distinct_service_accounts_do_not_share_claims(
    failure_repair_api: dict[str, Any],
) -> None:
    fixture = failure_repair_api
    payload = {**await _repair(fixture), "dry_run": False}
    results = []
    for _ in range(2):
        _, token = await _account(fixture, ["mcp:flow:propose"])
        result = await fixture["client"].post(
            "/api/v1/mcp/continuous/repair-proposals",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "s60-shared-client-key",
            },
            json=payload,
        )
        assert result.status_code == 200, result.text
        results.append(result.json()["change_set_id"])
    assert len(set(results)) == 2


@pytest.mark.asyncio
async def test_repair_revalidates_after_claim(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.idempotency import IdempotencyService

    fixture = failure_repair_api
    _, token = await _account(fixture, ["mcp:flow:propose"])
    payload = {**await _repair(fixture), "dry_run": False}
    original = IdempotencyService.run

    async def change_revision(service: IdempotencyService, **kwargs: Any) -> Any:
        async with fixture["sessions"]() as session:
            workflow = await session.get(Workflow, fixture["workflow_id"])
            workflow.draft_revision += 1
            await session.commit()
        return await original(service, **kwargs)

    monkeypatch.setattr(IdempotencyService, "run", change_revision)
    before = await _counts(fixture)
    result = await fixture["client"].post(
        "/api/v1/mcp/continuous/repair-proposals",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "s60-stale-after-claim"},
        json=payload,
    )
    assert result.status_code == 409, result.text
    assert await _counts(fixture) == before


@pytest.mark.parametrize("origin", ["repair", "maintenance"])
@pytest.mark.asyncio
async def test_continuous_proposals_reuse_human_review_and_one_time_preview(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    fixture = failure_repair_api
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    account_id, token = await _account(
        fixture, ["mcp:read", "mcp:flow:propose", "mcp:preview:execute"]
    )
    coordinator = RecordingWorkflowCoordinator()
    app.dependency_overrides[get_workflow_coordinator] = lambda: coordinator
    if origin == "repair":
        request = await _repair(fixture)
    else:
        _, maintenance, bound = await _bound(fixture)
        request = {
            "project_id": str(fixture["project_id"]),
            "run_id": bound["id"],
            "workflow_id": str(fixture["workflow_id"]),
            "maintenance": maintenance,
        }
    created = await fixture["client"].post(
        f"/api/v1/mcp/continuous/{origin}-proposals",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "s60-review-preview"},
        json={**request, "dry_run": False},
    )
    assert created.status_code == 200, created.text
    proposal_id = created.json()["change_set_id"]
    root = f"/api/v1/projects/{fixture['project_id']}/flow-specs/change-sets/{proposal_id}"
    approval_request = {
        "environment_id": str(fixture["environment_id"]),
        "executor_service_account_id": str(account_id),
    }
    pending = await fixture["client"].post(
        f"{root}/preview-approvals", headers=fixture["headers"], json=approval_request
    )
    assert pending.status_code == 409, pending.text
    accepted = await fixture["client"].post(
        f"{root}/review",
        headers=fixture["headers"],
        json={"accept": True, "note": "人工确认本次受限修订"},
    )
    assert accepted.status_code == 200, accepted.text
    approval = await fixture["client"].post(
        f"{root}/preview-approvals", headers=fixture["headers"], json=approval_request
    )
    assert approval.status_code == 201, approval.text
    payload = {
        "project_id": str(fixture["project_id"]),
        "environment_id": str(fixture["environment_id"]),
        "approval_id": approval.json()["id"],
    }
    url = f"/api/v1/mcp/flow/proposals/{proposal_id}/preview-executions"
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "s60-preview-once"}
    executed = await fixture["client"].post(url, headers=headers, json=payload)
    assert executed.status_code == 202, executed.text
    execution = executed.json()["execution"]
    assert execution["run_purpose"] == "preview"
    assert execution["workflow_id"] == str(fixture["workflow_id"])
    assert len(coordinator.plans) == 1
    retried = await fixture["client"].post(url, headers=headers, json=payload)
    assert retried.status_code == 202, retried.text
    assert retried.json()["execution"]["id"] == execution["id"]
    replay = await fixture["client"].post(
        url, headers={**headers, "Idempotency-Key": "s60-preview-replay"}, json=payload
    )
    assert replay.status_code == 409
    assert len(coordinator.plans) == 1
    async with fixture["sessions"]() as session:
        proposal = await session.get(AIChangeSet, UUID(proposal_id))
        assert proposal.applied_at is None
        approval_row = await session.get(SandboxPreviewApproval, UUID(approval.json()["id"]))
        assert approval_row.consumed_at is not None
        workflow = await session.get(Workflow, fixture["workflow_id"])
        assert workflow.draft_revision == 1
