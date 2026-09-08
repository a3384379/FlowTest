"""Focused S62 contracts for analysis preparation, Plan suggestions and Preview cancel."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api
from test_s60_continuous_mcp import _account

from app.core.config import settings
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.change_regression import ChangeRegressionRun
from app.models.tasking import TestPlanItem as PlanItemModel
from app.models.test_contexts import (
    TestContext as ContextModel,
)
from app.models.test_contexts import (
    TestContextRevision as ContextRevisionModel,
)
from app.schemas.mcp_planning import (
    MCPCancelPreviewRequest,
    MCPPrepareChangeRegressionRequest,
    MCPTestPlanUpdateRequest,
)
from app.services.mcp_planning import MCPPlanningService


async def _create_plan_and_policy(fixture: dict[str, Any]) -> tuple[str, str]:
    client = fixture["client"]
    root = f"/api/v1/projects/{fixture['project_id']}"
    plan = await client.post(
        f"{root}/test-plans",
        headers=fixture["headers"],
        json={
            "name": "S62 plan",
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
        headers=fixture["headers"],
        json={
            "name": "S62 gate",
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": False,
            "require_release_risk": False,
        },
    )
    assert policy.status_code == 201, policy.text
    return plan.json()["id"], policy.json()["id"]


async def _add_second_context_revision(fixture: dict[str, Any]) -> str:
    async with fixture["sessions"]() as session:
        first = await session.get(ContextRevisionModel, fixture["context_revision_id"])
        assert first is not None
        context = await session.get(ContextModel, first.context_id)
        assert context is not None
        second = ContextRevisionModel(
            context_id=context.id,
            revision=2,
            repository_revisions=first.repository_revisions,
            contract_revisions=first.contract_revisions,
            data_profile_revisions=first.data_profile_revisions,
            existing_test_revision=first.existing_test_revision,
            knowledge_snapshot=first.knowledge_snapshot,
            completeness=first.completeness,
            conflict_snapshot=first.conflict_snapshot,
            evidence_fingerprints=first.evidence_fingerprints,
            fingerprint="c" * 64,
            created_by_type=first.created_by_type,
            created_by_id=first.created_by_id,
        )
        session.add(second)
        context.current_revision = 2
        await session.commit()
        return str(context.id)


@pytest.mark.asyncio
async def test_prepare_change_regression_is_analysis_only_and_idempotent(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = failure_repair_api
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    plan_id, policy_id = await _create_plan_and_policy(fixture)
    context_id = await _add_second_context_revision(fixture)
    _, token = await _account(fixture, ["mcp:read", "mcp:regression:prepare"])
    payload = {
        "project_id": str(fixture["project_id"]),
        "title": "S62 prepared regression",
        "source_ref": "git://fixture/s62",
        "candidate_ref": "commit:s62",
        "git_diff": "diff --git a/a b/a\n-old\n+new\n",
        "test_plan_id": plan_id,
        "release_policy_id": policy_id,
        "context_id": context_id,
        "before_revision": 1,
        "after_revision": 2,
        "generate_missing_tests": False,
    }
    headers = {"Authorization": f"Bearer {token}"}
    client = fixture["client"]
    dry = await client.post(
        "/api/v1/mcp/continuous/change-regression/prepare",
        headers=headers,
        json=payload,
    )
    assert dry.status_code == 202, dry.text
    assert dry.json()["dry_run"] is True
    assert dry.json()["run_id"] is None
    assert dry.json()["automatic_execute"] is False
    persisted = await client.post(
        "/api/v1/mcp/continuous/change-regression/prepare",
        headers={**headers, "Idempotency-Key": "s62-prepare-v1"},
        json={**payload, "dry_run": False},
    )
    assert persisted.status_code == 202, persisted.text
    body = persisted.json()
    assert body["run_id"]
    assert body["automatic_release"] is False
    repeated = await client.post(
        "/api/v1/mcp/continuous/change-regression/prepare",
        headers={**headers, "Idempotency-Key": "s62-prepare-v1"},
        json={**payload, "dry_run": False},
    )
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["run_id"] == body["run_id"]
    assert repeated.json()["idempotency_replayed"] is True
    async with fixture["sessions"]() as session:
        run = await session.get(ChangeRegressionRun, UUID(body["run_id"]))
        assert run is not None
        assert run.status == "review_required"


@pytest.mark.asyncio
async def test_test_plan_update_creates_pending_changeset_without_mutating_plan(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = failure_repair_api
    plan_id, _ = await _create_plan_and_policy(fixture)
    _, token = await _account(fixture, ["mcp:read", "mcp:test-plan:propose"])
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "project_id": str(fixture["project_id"]),
        "test_plan_id": plan_id,
        "workflow_ids": [str(fixture["workflow_id"])],
        "title": "S62 plan membership",
        "rationale": "将已发布的目标流程交给人工审核后加入计划",
    }
    client = fixture["client"]
    async with fixture["sessions"]() as session:
        before = await session.scalar(
            select(func.count())
            .select_from(PlanItemModel)
            .where(PlanItemModel.test_plan_id == UUID(plan_id))
        )
    dry = await client.post(
        "/api/v1/mcp/continuous/test-plan/proposals",
        headers=headers,
        json=payload,
    )
    assert dry.status_code == 202, dry.text
    assert dry.json()["dry_run"] is True
    assert dry.json()["change_set_id"] is None
    async with fixture["sessions"]() as session:
        after_dry = await session.scalar(
            select(func.count())
            .select_from(PlanItemModel)
            .where(PlanItemModel.test_plan_id == UUID(plan_id))
        )
    assert after_dry == before
    created = await client.post(
        "/api/v1/mcp/continuous/test-plan/proposals",
        headers={**headers, "Idempotency-Key": "s62-plan-v1"},
        json={**payload, "dry_run": False},
    )
    assert created.status_code == 202, created.text
    change_set_id = UUID(created.json()["change_set_id"])
    assert created.json()["requires_human_review"] is True
    assert created.json()["automatic_publish"] is False
    async with fixture["sessions"]() as session:
        change_set = await session.get(AIChangeSet, change_set_id)
        item = await session.scalar(
            select(AIChangeItem).where(AIChangeItem.change_set_id == change_set_id)
        )
        after_create = await session.scalar(
            select(func.count())
            .select_from(PlanItemModel)
            .where(PlanItemModel.test_plan_id == UUID(plan_id))
        )
        assert change_set is not None
        assert change_set.status == "draft"
        assert item is not None and item.item_type == "test_plan_update"
    assert after_create == before

    # A completed receipt must be replayable without resolving mutable targets again.
    async def fail_target_resolution(*_: object, **__: object) -> object:
        raise AssertionError("completed idempotency receipts must bypass target resolution")

    monkeypatch.setattr(MCPPlanningService, "_resolve_plan_targets", fail_target_resolution)
    replayed = await client.post(
        "/api/v1/mcp/continuous/test-plan/proposals",
        headers={**headers, "Idempotency-Key": "s62-plan-v1"},
        json={**payload, "dry_run": False},
    )
    assert replayed.status_code == 202, replayed.text
    assert replayed.json()["change_set_id"] == str(change_set_id)
    assert replayed.json()["idempotency_replayed"] is True


def test_s62_request_contracts_are_strict_and_safe() -> None:
    with pytest.raises(ValueError):
        MCPTestPlanUpdateRequest(
            project_id="00000000-0000-0000-0000-000000000001",
            test_plan_id="00000000-0000-0000-0000-000000000002",
            workflow_ids=["00000000-0000-0000-0000-000000000003"],
            test_case_ids=["00000000-0000-0000-0000-000000000003"],
        )
    with pytest.raises(ValueError, match="不能超过 100"):
        MCPTestPlanUpdateRequest(
            project_id="00000000-0000-0000-0000-000000000001",
            test_plan_id="00000000-0000-0000-0000-000000000002",
            workflow_ids=[UUID(int=index + 1) for index in range(100)],
            test_case_ids=[UUID(int=101)],
        )
    with pytest.raises(ValueError):
        MCPPrepareChangeRegressionRequest(
            project_id="00000000-0000-0000-0000-000000000001",
            title="bad",
            candidate_ref="commit:x",
            test_plan_id="00000000-0000-0000-0000-000000000002",
            release_policy_id="00000000-0000-0000-0000-000000000003",
            context_id="00000000-0000-0000-0000-000000000004",
            before_revision=2,
            after_revision=1,
            git_diff="diff",
        )
    assert MCPCancelPreviewRequest.model_config["extra"] == "forbid"
