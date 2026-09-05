from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api
from test_s59c_maintenance_api import _request

from app.api.dependencies import get_test_plan_dispatcher
from app.core.config import settings
from app.domain.access import ProjectRole
from app.domain.change_regression import ChangeConstraintTarget, OperationIdentity
from app.main import app
from app.models.access import ProjectMember, User
from app.models.ai import AIChangeSet
from app.models.change_regression import ChangeRegressionRun
from app.models.governance import IdempotencyRecord
from app.models.tasking import TestPlanRun as PlanRun
from app.models.tasking import TestPlanRunItem as PlanRunItem
from app.models.test_contexts import TestContext as ContextModel
from app.models.workflows import Workflow, WorkflowExecution
from app.repositories.change_regression import ChangeRegressionRepository
from app.services.change_regression import _update_operation_selection_snapshot


async def _run(fixture: dict[str, Any]) -> dict[str, Any]:
    client, headers = fixture["client"], fixture["headers"]
    root = f"/api/v1/projects/{fixture['project_id']}"
    plan = await client.post(
        f"{root}/test-plans",
        headers=headers,
        json={
            "name": "S59D plan",
            "items": [
                {
                    "workflow_id": str(fixture["workflow_id"]),
                    "environment_id": str(fixture["environment_id"]),
                }
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    policy = await client.post(
        f"{root}/release-policies",
        headers=headers,
        json={
            "name": "S59D gate",
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": False,
            "require_release_risk": False,
        },
    )
    assert policy.status_code == 201, policy.text
    response = await client.post(
        f"{root}/change-regressions",
        headers=headers,
        json={
            "title": "S59D regression",
            "candidate_ref": "commit:s59d",
            "git_diff": (
                "diff --git a/orders.py b/orders.py\n--- a/orders.py\n"
                "+++ b/orders.py\n@@ -1 +1 @@\n-old\n+new\n"
            ),
            "test_plan_id": plan.json()["id"],
            "release_policy_id": policy.json()["id"],
            "generate_missing_tests": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("version", ["s47.4-change-regression-v3", "s47.4-change-regression-v4"])
def test_operation_selection_keeps_versioned_maintenance_extension(version: str) -> None:
    change_set = AIChangeSet(
        source_snapshot={
            "schema_version": version,
            "context_maintenance": {"context_diff_ref": "fixed"},
        }
    )
    identity = OperationIdentity(
        portable_operation_ref="orders:get",
        service_key="orders",
        method="GET",
        normalized_path="/orders",
        contract_fingerprint="f" * 64,
    )
    _update_operation_selection_snapshot(
        change_set,
        binding={},
        change_key="change",
        identity=identity,
        target=ChangeConstraintTarget(
            location="query", field_path=("limit",), constraint="maximum"
        ),
        design_fingerprint="a" * 64,
        superseded=False,
    )
    assert change_set.source_snapshot["schema_version"] == version
    assert change_set.source_snapshot["context_maintenance"] == {"context_diff_ref": "fixed"}


@pytest.mark.asyncio
async def test_viewer_cannot_mutate_maintenance_or_claim_idempotency(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    root, payload, _ = await _bound(fixture)
    async with fixture["sessions"]() as session:
        actor = await session.scalar(select(User))
        actor.is_system_admin = False
        session.add(
            ProjectMember(
                project_id=fixture["project_id"], user_id=actor.id, role=ProjectRole.VIEWER
            )
        )
        await session.commit()
    response = await fixture["client"].post(
        f"{root}/context-maintenance/workflows/{fixture['workflow_id']}/proposals",
        headers={**fixture["headers"], "Idempotency-Key": "s59d-viewer-denied"},
        json=payload,
    )
    assert response.status_code == 403, response.text
    async with fixture["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0


@pytest.mark.asyncio
async def test_context_binding_preserves_legacy_gaps_and_freezes_terminal_run(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    payload = await _request(fixture)
    run = await _run(fixture)
    assert run["change_set_id"] is None
    assert run.get("context_maintenance") is None
    root = f"/api/v1/projects/{fixture['project_id']}/change-regressions/{run['id']}"
    comparison = {key: payload[key] for key in ("context_id", "before_revision", "after_revision")}
    response = await fixture["client"].put(
        f"{root}/context-maintenance", headers=fixture["headers"], json=comparison
    )
    assert response.status_code == 200, response.text
    bound = response.json()
    snapshot = bound["context_maintenance"]
    assert snapshot["schema_version"] == "s47.4-change-regression-v4"
    assert snapshot["affected"]["affected_workflows"][0]["workflow_id"] == str(
        fixture["workflow_id"]
    )
    assert snapshot["comparison"]["difference"]["knowledge"]["changed"] is True
    assert snapshot["review"] is None
    for key, value in run["selection_summary"].items():
        assert bound["selection_summary"][key] == value
    assert bound["change_set_id"] is None
    invalid = await fixture["client"].put(
        f"{root}/context-maintenance",
        headers=fixture["headers"],
        json={**comparison, "context_id": str(uuid4())},
    )
    assert invalid.status_code == 404
    async with fixture["sessions"]() as session:
        model = await session.get(ChangeRegressionRun, UUID(run["id"]))
        model.status = "approved"
        await session.commit()
    frozen = await fixture["client"].put(
        f"{root}/context-maintenance", headers=fixture["headers"], json=comparison
    )
    assert frozen.status_code == 409
    async with fixture["sessions"]() as session:
        model = await session.scalar(select(ChangeRegressionRun))
        assert model.selection_summary["context_maintenance"] == snapshot


async def _bound(fixture: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    payload = await _request(fixture)
    run = await _run(fixture)
    root = f"/api/v1/projects/{fixture['project_id']}/change-regressions/{run['id']}"
    response = await fixture["client"].put(
        f"{root}/context-maintenance",
        headers=fixture["headers"],
        json={key: payload[key] for key in ("context_id", "before_revision", "after_revision")},
    )
    assert response.status_code == 200, response.text
    payload["impact_run_id"] = run["impact_run_id"]
    return root, payload, response.json()


@pytest.mark.asyncio
async def test_run_lock_refreshes_cached_state(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    run = await _run(fixture)
    async with fixture["sessions"]() as session:
        cached = await session.get(ChangeRegressionRun, UUID(run["id"]))
        await session.execute(
            update(ChangeRegressionRun)
            .where(ChangeRegressionRun.id == cached.id)
            .values(status="approved")
            .execution_options(synchronize_session=False)
        )
        assert cached.status == "review_required"
        locked = await ChangeRegressionRepository(session).get_run_for_update(cached.id)
        assert locked.status == "approved"


class _Queue:
    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        pass


@pytest.mark.asyncio
async def test_release_requires_real_pinned_execution_and_preserves_frozen_history(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    root, payload, _ = await _bound(fixture)
    headers = fixture["headers"]
    rejected = await fixture["client"].post(
        f"{root}/approve", headers=headers, json={"note": "review"}
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "REGRESSION_MAINTENANCE_REVIEW_REQUIRED"
    reviewed = await fixture["client"].post(
        f"{root}/context-maintenance/review",
        headers=headers,
        json={"note": "已人工检查全部差异和流程证据", "acknowledge_incomplete_analysis": True},
    )
    assert reviewed.status_code == 200, reviewed.text
    frozen = reviewed.json()["context_maintenance"]
    approved = await fixture["client"].post(
        f"{root}/approve", headers=headers, json={"note": "review"}
    )
    assert approved.status_code == 200, approved.text
    app.dependency_overrides[get_test_plan_dispatcher] = lambda: _Queue()
    try:
        executed = await fixture["client"].post(f"{root}/execute", headers=headers)
    finally:
        app.dependency_overrides.pop(get_test_plan_dispatcher, None)
    assert executed.status_code == 202, executed.text
    plan_run_id = UUID(executed.json()["test_plan_run_id"])
    async with fixture["sessions"]() as session:
        await session.execute(
            update(PlanRun).where(PlanRun.id == plan_run_id).values(status="passed")
        )
        await session.execute(
            update(PlanRunItem)
            .where(PlanRunItem.test_plan_run_id == plan_run_id)
            .values(status="passed", workflow_execution_id=fixture["execution_id"])
        )
        await session.commit()
    missing = await fixture["client"].post(f"{root}/release-gate", headers=headers)
    assert missing.status_code == 409, missing.text
    assert missing.json()["error"]["code"] == "REGRESSION_MAINTENANCE_EXECUTION_GAP"
    async with fixture["sessions"]() as session:
        execution = await session.get(WorkflowExecution, fixture["execution_id"])
        execution.status = "passed"
        await session.commit()
    released = await fixture["client"].post(f"{root}/release-gate", headers=headers)
    assert released.status_code == 200, released.text
    assert released.json()["evidence"]["context_maintenance"] == frozen
    evidence = released.json()["evidence"]["maintenance_execution_evidence"]
    assert evidence["test_plan_run_id"] == str(plan_run_id)
    assert evidence["preview_counts_as_execution"] is False
    async with fixture["sessions"]() as session:
        context = await session.get(ContextModel, UUID(payload["context_id"]))
        context.status = "closed"
        await session.commit()
    repeated = await fixture["client"].post(f"{root}/release-gate", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["evidence"] == released.json()["evidence"]
    assert repeated.json()["release_decision_id"] == released.json()["release_decision_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["impact", "context", "origin", "fingerprint", "workflow"])
async def test_proposal_association_rejects_untrusted_or_unrelated_evidence(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    root, payload, _ = await _bound(fixture)
    created = await fixture["client"].post(
        f"/api/v1/projects/{fixture['project_id']}/workflows/{fixture['workflow_id']}/maintenance-proposals",
        headers={**fixture["headers"], "Idempotency-Key": "s59d-existing-proposal"},
        json=payload,
    )
    assert created.status_code == 201, created.text
    change_set_id = created.json()["proposal"]["id"]
    async with fixture["sessions"]() as session:
        model = await session.get(AIChangeSet, UUID(change_set_id))
        snapshot = dict(model.source_snapshot)
        provenance = dict(snapshot["maintenance"])
        if mismatch == "origin":
            snapshot["proposal_schema_version"] = "untrusted"
        else:
            field = {
                "impact": "impact_run_id",
                "context": "context_id",
                "fingerprint": "context_fingerprint",
                "workflow": "workflow_id",
            }[mismatch]
            provenance[field] = "c" * 64 if mismatch == "fingerprint" else str(uuid4())
            snapshot["maintenance"] = provenance
        model.source_snapshot = snapshot
        await session.commit()
    response = await fixture["client"].post(
        f"{root}/context-maintenance/proposals",
        headers=fixture["headers"],
        json={"change_set_id": change_set_id},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "REGRESSION_MAINTENANCE_PROPOSAL_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["draft", "context"])
async def test_maintenance_review_cannot_use_stale_source_or_unpublished_draft(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    stale: str,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    root, payload, _ = await _bound(fixture)
    async with fixture["sessions"]() as session:
        if stale == "draft":
            workflow = await session.get(Workflow, fixture["workflow_id"])
            workflow.draft_definition = {**workflow.draft_definition, "variables": {"new": "value"}}
            workflow.draft_revision += 1
        else:
            context = await session.get(ContextModel, UUID(payload["context_id"]))
            context.status = "closed"
        await session.commit()
    response = await fixture["client"].post(
        f"{root}/context-maintenance/review",
        headers=fixture["headers"],
        json={"note": "已人工检查全部差异和流程证据", "acknowledge_incomplete_analysis": True},
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_maintenance_creation_is_atomic_and_pending_cannot_approve(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    root, payload, run = await _bound(fixture)
    url = f"{root}/context-maintenance/workflows/{fixture['workflow_id']}/proposals"
    headers = {**fixture["headers"], "Idempotency-Key": "s59d-atomic-create"}
    commit = AsyncSession.commit

    async def fail_completion(session: AsyncSession) -> None:
        completed = await session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.status == "completed")
        )
        if completed is not None:
            raise RuntimeError("injected completion failure")
        await commit(session)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_completion)
        failed = await fixture["client"].post(url, headers=headers, json=payload)
    assert failed.status_code == 500
    async with fixture["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(AIChangeSet)) == 0
        assert await session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
        model = await session.get(ChangeRegressionRun, UUID(run["id"]))
        assert model.selection_summary["context_maintenance"]["proposals"] == []
    created = await fixture["client"].post(url, headers=headers, json=payload)
    assert created.status_code == 201, created.text
    proposals = created.json()["context_maintenance"]["proposals"]
    assert len(proposals) == 1 and proposals[0]["review_status"] == "pending"
    repeated = await fixture["client"].post(url, headers=headers, json=payload)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json() == created.json()
    review = await fixture["client"].post(
        f"{root}/context-maintenance/review",
        headers=headers,
        json={"note": "已检查全部受影响流程和未覆盖诊断", "acknowledge_incomplete_analysis": True},
    )
    assert review.status_code == 409
    assert review.json()["error"]["code"] == "REGRESSION_MAINTENANCE_PROPOSAL_REVIEW_PENDING"
    linked = await fixture["client"].post(
        f"{root}/context-maintenance/proposals",
        headers=headers,
        json={"change_set_id": proposals[0]["change_set_id"]},
    )
    assert linked.status_code == 200
    assert len(linked.json()["context_maintenance"]["proposals"]) == 1


@pytest.mark.asyncio
async def test_maintenance_review_requires_explicit_diagnostics_and_published_plan(
    failure_repair_api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    fixture = failure_repair_api
    root, _, run = await _bound(fixture)
    url = f"{root}/context-maintenance/review"
    note = {"note": "已人工检查全部差异和受影响流程证据"}
    missing = await fixture["client"].post(url, headers=fixture["headers"], json=note)
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "REGRESSION_MAINTENANCE_ANALYSIS_REVIEW_REQUIRED"
    reviewed = await fixture["client"].post(
        url, headers=fixture["headers"], json={**note, "acknowledge_incomplete_analysis": True}
    )
    assert reviewed.status_code == 200, reviewed.text
    snapshot = reviewed.json()["context_maintenance"]
    assert len(snapshot["required_workflows"]) == 1
    assert snapshot["review"]["note"] == note["note"]
    assert (
        run["selection_summary"]["current_plan_gaps"]
        == reviewed.json()["selection_summary"]["current_plan_gaps"]
    )
