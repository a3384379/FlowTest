from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api

from app.core.context import reset_tenant_context, set_tenant_context
from app.core.errors import AppError
from app.domain.tenant import TenantContext
from app.domain.test_contexts import ContextRevisionSnapshot, context_revision_fingerprint
from app.models.access import Project, User
from app.models.ai import AIChangeSet
from app.models.api_assets import APIDefinition
from app.models.governance import IdempotencyRecord
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_contexts import TestContextRevision as RevisionModel
from app.models.workflows import Workflow
from app.schemas.maintenance_proposals import MaintenanceProposalCreate
from app.services.flow_spec import FlowSpecService
from app.services.idempotency import IdempotencyService
from app.services.maintenance_proposals import MaintenanceProposalService


async def _request(
    fixture: dict[str, Any], *, heuristic: bool = False, edge_only: bool = False
) -> dict[str, Any]:
    async with fixture["sessions"]() as session:
        original = await session.get(RevisionModel, fixture["context_revision_id"])
        context = await session.get(ContextModel, original.context_id)
        api = await session.scalar(select(APIDefinition))
        base = {
            "repository_revisions": [],
            "contract_revisions": [],
            "data_profile_revisions": [],
            "existing_test_revision": None,
            "completeness": original.completeness,
            "conflict_snapshot": original.conflict_snapshot,
            "evidence_fingerprints": [],
        }
        for number, state in ((2, "before"), (3, "after")):
            graph = {
                "nodes": [
                    {
                        "id": "op",
                        "kind": "operation",
                        "label": "Private method",
                        "facts": [
                            {"name": "api_definition_id", "value": str(api.id)},
                            {"name": "api_version", "value": "1"},
                        ],
                    },
                    {
                        "id": "event",
                        "kind": "event",
                        "label": "Private event",
                        "facts": [{"name": "revision", "value": "same" if edge_only else state}],
                    },
                ],
                "edges": [
                    {
                        "source": "op",
                        "target": "event",
                        "relation": "may_consume" if heuristic else "consumes",
                    }
                ],
            }
            if edge_only and number == 2:
                graph["edges"] = []
            snapshot = ContextRevisionSnapshot.model_validate({**base, "knowledge_snapshot": graph})
            session.add(
                RevisionModel(
                    context_id=context.id,
                    revision=number,
                    **base,
                    knowledge_snapshot=graph,
                    fingerprint=context_revision_fingerprint(snapshot),
                    created_by_type="user",
                    created_by_id=original.created_by_id,
                )
            )
        context.current_revision = 3
        await session.commit()
        context_id = context.id
    response = await fixture["client"].get(
        f"/api/v1/projects/{fixture['project_id']}/flow-specs/workflows/{fixture['workflow_id']}/export",
        headers=fixture["headers"],
    )
    assert response.status_code == 200, response.text
    spec = response.json()["spec"]
    spec["variables"] = {"customer_id": "fixture-customer"}
    return {
        "context_id": str(context_id),
        "before_revision": 2,
        "after_revision": 3,
        "expected_target_revision": 1,
        "kind": "data",
        "proposed_spec": spec,
        "rationale": "根据明确变更证据更新测试数据",
    }


def _url(fixture: dict[str, Any]) -> str:
    return (
        f"/api/v1/projects/{fixture['project_id']}/workflows/"
        f"{fixture['workflow_id']}/maintenance-proposals"
    )


async def _counts(fixture: dict[str, Any]) -> tuple[int, int]:
    async with fixture["sessions"]() as session:
        return (
            await session.scalar(select(func.count()).select_from(AIChangeSet)),
            await session.scalar(select(func.count()).select_from(IdempotencyRecord)),
        )


class _CommittedEffect(BaseModel):
    created: bool = True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["action", "completion"])
async def test_legacy_committed_effect_retains_claim_after_error(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = failure_repair_api
    calls = 0
    original_commit = AsyncSession.commit
    async with fixture["sessions"]() as session:
        actor_id = (await session.scalar(select(User))).id

        async def action() -> _CommittedEffect:
            nonlocal calls
            calls += 1
            session.add(
                Project(
                    organization_id=fixture["organization_id"],
                    name="committed-effect",
                    created_by_id=actor_id,
                )
            )
            await session.commit()
            if failure == "action":
                raise RuntimeError("injected legacy action")
            return _CommittedEffect()

        async def commit(active: AsyncSession) -> None:
            completed = await active.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.status == "completed")
            )
            if completed is not None:
                raise RuntimeError("injected completion")
            await original_commit(active)

        service = IdempotencyService(session)
        with monkeypatch.context() as patch:
            if failure == "completion":
                patch.setattr(AsyncSession, "commit", commit)
            with pytest.raises(RuntimeError, match="injected"):
                await service.run(
                    key="legacy-effect",
                    project_id=fixture["project_id"],
                    actor_key=str(actor_id),
                    operation="legacy",
                    request_payload={},
                    action=action,
                )
        record = await session.scalar(select(IdempotencyRecord))
        assert record is not None and record.status == "pending"
        with pytest.raises(AppError, match="相同操作正在处理中"):
            await service.run(
                key="legacy-effect",
                project_id=fixture["project_id"],
                actor_key=str(actor_id),
                operation="legacy",
                request_payload={},
                action=action,
            )
        assert calls == 1
        assert (
            await session.scalar(
                select(func.count()).select_from(Project).where(Project.name == "committed-effect")
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["maintenance", "repair"])
async def test_proposal_and_completed_claim_commit_atomically(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    fixture = failure_repair_api
    payload = await _request(fixture)
    url = _url(fixture)
    if origin == "repair":
        async with fixture["sessions"]() as session:
            revision = await session.scalar(
                select(RevisionModel).where(RevisionModel.revision == 3)
            )
        payload = {
            "kind": "data",
            "proposed_spec": payload["proposed_spec"],
            "expected_target_revision": 1,
            "context_revision_id": str(revision.id),
            "rationale": "补齐可重复测试数据",
        }
        url = (
            f"/api/v1/projects/{fixture['project_id']}/workflow-executions/"
            f"{fixture['execution_id']}/repair-proposals"
        )
    original = AsyncSession.commit
    unsafe_commits: list[tuple[int, int]] = []

    async def commit(session: AsyncSession) -> None:
        proposals = await session.scalar(select(func.count()).select_from(AIChangeSet))
        pending = await session.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.status == "pending")
        )
        if proposals and pending:
            unsafe_commits.append((proposals, pending))
        await original(session)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    response = await fixture["client"].post(
        url,
        headers={**fixture["headers"], "Idempotency-Key": "s59c-atomic"},
        json=payload,
    )
    assert response.status_code == 201, response.text
    assert unsafe_commits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["after_action", "completion_commit"])
async def test_failed_maintenance_action_rolls_back_and_can_retry(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = failure_repair_api
    payload = await _request(fixture)
    original_create, original_commit = FlowSpecService.create_import, AsyncSession.commit

    async def create(service: FlowSpecService, **kwargs: Any) -> None:
        await original_create(service, **kwargs)
        raise RuntimeError("injected after action")

    async def commit(session: AsyncSession) -> None:
        completed = await session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.status == "completed")
        )
        if completed is not None:
            raise RuntimeError("injected completion commit")
        await original_commit(session)

    headers = {**fixture["headers"], "Idempotency-Key": "s59c-rollback-retry"}
    with monkeypatch.context() as patch:
        if failure == "after_action":
            patch.setattr(FlowSpecService, "create_import", create)
        else:
            patch.setattr(AsyncSession, "commit", commit)
        failed = await fixture["client"].post(_url(fixture), headers=headers, json=payload)
        assert failed.status_code == 500
    assert await _counts(fixture) == (0, 0)
    retried = await fixture["client"].post(_url(fixture), headers=headers, json=payload)
    assert retried.status_code == 201, retried.text
    assert await _counts(fixture) == (1, 1)


@pytest.mark.asyncio
async def test_foreign_context_hides_revision_existence(failure_repair_api: dict[str, Any]) -> None:
    fixture = failure_repair_api
    payload = await _request(fixture)
    async with fixture["sessions"]() as session:
        context = await session.get(ContextModel, UUID(payload["context_id"]))
        project = Project(
            organization_id=context.organization_id,
            name="Other context scope",
            created_by_id=context.created_by_id,
        )
        session.add(project)
        await session.flush()
        context.project_id = project.id
        await session.commit()
    for revision in (3, 999):
        response = await fixture["client"].post(
            _url(fixture),
            headers={**fixture["headers"], "Idempotency-Key": "s59c-context-scope"},
            json={**payload, "after_revision": revision},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "TEST_CONTEXT_NOT_FOUND"
    assert await _counts(fixture) == (0, 0)


@pytest.mark.asyncio
async def test_heuristic_edge_only_change_cannot_authorize_maintenance(
    failure_repair_api: dict[str, Any],
) -> None:
    fixture = failure_repair_api
    payload = await _request(fixture, heuristic=True, edge_only=True)
    response = await fixture["client"].post(
        _url(fixture),
        headers={**fixture["headers"], "Idempotency-Key": "s59c-heuristic-edge"},
        json=payload,
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "MAINTENANCE_EXPLICIT_EVIDENCE_REQUIRED"
    assert await _counts(fixture) == (0, 0)


@pytest.mark.asyncio
async def test_maintenance_proposal_reuses_review_preview_apply_and_discovery(
    failure_repair_api: dict[str, Any],
) -> None:
    fixture = failure_repair_api
    request = await _request(fixture)
    client, headers = fixture["client"], fixture["headers"]
    created = await client.post(
        _url(fixture), headers={**headers, "Idempotency-Key": "s59c-maintenance"}, json=request
    )
    assert created.status_code == 201, created.text
    body = created.json()
    proposal = body["proposal"]
    assert proposal["review_status"] == "pending"
    assert proposal["source_ref"].startswith("maintenance://")
    assert body["provenance"]["evidence_refs"]
    assert not body["provenance"]["automatic_apply_allowed"]
    assert "Private" not in created.text
    base = f"/api/v1/projects/{fixture['project_id']}/flow-specs/change-sets"
    repeated = await client.post(
        _url(fixture), headers={**headers, "Idempotency-Key": "s59c-maintenance"}, json=request
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["proposal"]["id"] == proposal["id"]
    assert await _counts(fixture) == (1, 1)
    listing = await client.get(f"{base}/proposals", headers=headers)
    assert listing.json()["items"][0]["proposal_origin"] == "maintenance"
    visual = await client.get(f"{base}/{proposal['id']}/visual-proposal", headers=headers)
    assert visual.status_code == 200, visual.text
    assert visual.json()["maintenance_provenance"] == body["provenance"]
    early_apply = await client.post(f"{base}/{proposal['id']}/apply", headers=headers)
    assert early_apply.status_code == 409
    approval_payload = {"environment_id": str(fixture["environment_id"])}
    early_preview = await client.post(
        f"{base}/{proposal['id']}/preview-approvals", headers=headers, json=approval_payload
    )
    assert early_preview.status_code == 409
    reviewed = await client.post(
        f"{base}/{proposal['id']}/review",
        headers=headers,
        json={"accept": True, "note": "人工确认维护范围"},
    )
    assert reviewed.status_code == 200, reviewed.text
    approval = await client.post(
        f"{base}/{proposal['id']}/preview-approvals", headers=headers, json=approval_payload
    )
    assert approval.status_code == 201, approval.text
    applied = await client.post(f"{base}/{proposal['id']}/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft_revision"] == 2
    after_apply = await client.post(
        f"{base}/{proposal['id']}/preview-approvals", headers=headers, json=approval_payload
    )
    assert after_apply.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "heuristic",
        "stale_target",
        "wrong_context",
        "reverse",
        "sensitive",
        "scope",
        "missing_before",
        "inactive",
    ],
)
async def test_invalid_maintenance_request_does_not_claim_idempotency(
    failure_repair_api: dict[str, Any], mutation: str
) -> None:
    fixture = failure_repair_api
    request = await _request(fixture, heuristic=mutation == "heuristic")
    if mutation == "stale_target":
        request["expected_target_revision"] = 2
    elif mutation == "wrong_context":
        request["context_id"] = str(uuid4())
    elif mutation == "reverse":
        request["before_revision"] = 3
    elif mutation == "sensitive":
        request["proposed_spec"]["variables"] = {"password": "hunter2"}
    elif mutation == "scope":
        request["proposed_spec"]["name"] = "Forbidden rename"
    elif mutation == "missing_before":
        request["before_revision"] = 1
        request["after_revision"] = 99
    elif mutation == "inactive":
        async with fixture["sessions"]() as session:
            context = await session.get(ContextModel, UUID(request["context_id"]))
            context.expires_at = datetime.now(UTC) - timedelta(hours=1)
            await session.commit()
    response = await fixture["client"].post(
        _url(fixture),
        headers={**fixture["headers"], "Idempotency-Key": "s59c-rejected"},
        json=request,
    )
    assert response.status_code in {404, 409, 422}, response.text
    assert response.json()["error"]["trace_id"]
    assert "hunter2" not in response.text
    assert await _counts(fixture) == (0, 0)


@pytest.mark.asyncio
async def test_maintenance_rechecks_target_after_prepare(
    failure_repair_api: dict[str, Any],
) -> None:
    fixture = failure_repair_api
    request = MaintenanceProposalCreate.model_validate(await _request(fixture))
    async with fixture["sessions"]() as session:
        actor = await session.scalar(select(User))
        token = set_tenant_context(
            TenantContext(
                organization_id=fixture["organization_id"],
                actor_id=actor.id,
                role=None,
                is_system_admin=True,
            )
        )
        try:
            service = MaintenanceProposalService(session)
            prepared = await service.prepare(
                actor=actor,
                project_id=fixture["project_id"],
                workflow_id=fixture["workflow_id"],
                payload=request,
            )
            workflow = await session.get(Workflow, fixture["workflow_id"])
            workflow.draft_revision = 2
            await session.commit()
            with pytest.raises(AppError) as error:
                await service.persist(prepared)
            assert error.value.code == "MAINTENANCE_TARGET_STALE"
        finally:
            reset_tenant_context(token)
    assert await _counts(fixture) == (0, 0)


@pytest.mark.asyncio
async def test_maintenance_apply_rejects_closed_source_context(
    failure_repair_api: dict[str, Any],
) -> None:
    fixture = failure_repair_api
    request = await _request(fixture)
    client, headers = fixture["client"], fixture["headers"]
    created = await client.post(
        _url(fixture), headers={**headers, "Idempotency-Key": "s59c-stale-context"}, json=request
    )
    assert created.status_code == 201, created.text
    proposal_id = created.json()["proposal"]["id"]
    base = f"/api/v1/projects/{fixture['project_id']}/flow-specs/change-sets/{proposal_id}"
    reviewed = await client.post(f"{base}/review", headers=headers, json={"accept": True})
    assert reviewed.status_code == 200, reviewed.text
    async with fixture["sessions"]() as session:
        context = await session.get(ContextModel, UUID(request["context_id"]))
        context.status = "closed"
        context.closed_at = datetime.now(UTC)
        await session.commit()
    applied = await client.post(f"{base}/apply", headers=headers)
    assert applied.status_code == 409, applied.text
    assert applied.json()["error"]["code"] == "TEST_CONTEXT_CLOSED"


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["workflow", "context", "spec", "impact", "anonymous", "spoof"])
async def test_maintenance_project_and_input_boundaries(
    failure_repair_api: dict[str, Any],
    target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    fixture = failure_repair_api
    request = await _request(fixture)
    headers = {**fixture["headers"], "Idempotency-Key": "s59c-isolation"}
    url = _url(fixture)
    async with fixture["sessions"]() as session:
        actor = await session.scalar(select(User))
        other = Project(
            organization_id=fixture["organization_id"], name="Other project", created_by_id=actor.id
        )
        session.add(other)
        await session.flush()
        if target == "context":
            context = await session.get(ContextModel, UUID(request["context_id"]))
            context.project_id = other.id
        await session.commit()
        other_id = other.id
    if target == "workflow":
        url = url.replace(str(fixture["project_id"]), str(other_id))
    elif target == "spec":
        request["proposed_spec"]["project_id"] = str(other_id)
    elif target == "impact":
        monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
        request["impact_run_id"] = str(uuid4())
    elif target == "anonymous":
        headers = {"Idempotency-Key": "s59c-unauthenticated"}
    elif target == "spoof":
        request["source_ref"] = "maintenance://forged"
    response = await fixture["client"].post(url, headers=headers, json=request)
    assert response.status_code in {401, 404, 422}, response.text
    assert response.json()["error"]["trace_id"]
    assert await _counts(fixture) == (0, 0)
