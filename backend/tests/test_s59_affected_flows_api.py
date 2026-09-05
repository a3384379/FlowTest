from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_s57_context_inspector_api import context_inspector as context_inspector

from app.core.config import settings
from app.core.security import token_service
from app.models.access import User
from app.models.ai import AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion
from app.models.governance import IdempotencyRecord
from app.models.impact import CoverageSnapshot, ImpactRun
from app.models.impact import TestSelection as SelectionModel
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_contexts import TestContextRevision as RevisionModel
from app.models.workflows import Workflow
from app.services.change_regression import ChangeRegressionService


def _graph(state: str) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "orders",
                "kind": "operation",
                "label": "PRIVATE_LABEL",
                "facts": [
                    {"name": "method", "value": "GET"},
                    {"name": "path", "value": "/orders/{id}"},
                ],
            },
            {
                "id": "entity",
                "kind": "entity",
                "label": "PRIVATE_LABEL",
                "facts": [{"name": "state", "value": state}],
            },
        ],
        "edges": [{"source": "orders", "target": "entity", "relation": "maps_entity"}],
    }


def _draft(api_id: UUID, version: int | None, capability: bool = False) -> dict[str, Any]:
    config: dict[str, Any] = {"api_definition_id": str(api_id)}
    if version is not None:
        config["api_version"] = version
    node: dict[str, Any] = {
        "id": "request",
        "type": "api",
        "name": "PRIVATE_NODE_NAME",
        "position": {"x": 1, "y": 0},
        "config": config,
    }
    if capability:
        node.update(
            type="capability",
            capability_id="http.request",
            capability_version="2.0.0",
            configuration=config,
            bindings=[],
            config={},
        )
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            node,
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 2, "y": 0}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "request"},
            {"id": "b", "source": "request", "target": "end"},
        ],
    }


async def _seed(fixture: dict[str, Any]) -> dict[str, UUID]:
    async with fixture["sessions"]() as session:
        original = await session.scalar(select(RevisionModel))
        session.add(
            RevisionModel(
                context_id=original.context_id,
                revision=2,
                repository_revisions=original.repository_revisions,
                contract_revisions=[],
                data_profile_revisions=[],
                existing_test_revision=None,
                knowledge_snapshot=_graph("before"),
                completeness=original.completeness,
                conflict_snapshot=original.conflict_snapshot,
                evidence_fingerprints=original.evidence_fingerprints,
                fingerprint="e" * 64,
                created_by_type=original.created_by_type,
                created_by_id=original.created_by_id,
            )
        )
        session.add(
            RevisionModel(
                context_id=original.context_id,
                revision=3,
                repository_revisions=original.repository_revisions,
                contract_revisions=[],
                data_profile_revisions=[],
                existing_test_revision=None,
                knowledge_snapshot=_graph("PRIVATE_FACT_AFTER"),
                completeness=original.completeness,
                conflict_snapshot=original.conflict_snapshot,
                evidence_fingerprints=original.evidence_fingerprints,
                fingerprint="f" * 64,
                created_by_type=original.created_by_type,
                created_by_id=original.created_by_id,
            )
        )
        api = APIDefinition(
            project_id=fixture["project_id"],
            name="订单",
            current_version=2,
            created_by_id=original.created_by_id,
        )
        session.add(api)
        await session.flush()
        session.add(
            APIVersion(
                api_definition_id=api.id,
                version=2,
                method="GET",
                path="/orders/{id}",
                body=None,
                created_by_id=original.created_by_id,
            )
        )
        identifiers = {"api": api.id, "actor": original.created_by_id}
        for name, version, capability, project_id in [
            ("current", None, False, fixture["project_id"]),
            ("pinned_missing", 1, False, fixture["project_id"]),
            ("capability", None, True, fixture["project_id"]),
            ("foreign", None, False, fixture["other_project_id"]),
        ]:
            workflow = Workflow(
                project_id=project_id,
                name=name,
                draft_revision=3,
                draft_definition=_draft(api.id, version, capability),
                created_by_id=original.created_by_id,
            )
            session.add(workflow)
            await session.flush()
            identifiers[name] = workflow.id
        await session.commit()
        return identifiers


def _url(fixture: dict[str, Any], project_id: UUID | None = None) -> str:
    project = project_id or fixture["project_id"]
    return f"/api/v1/projects/{project}/contexts/{fixture['context_id']}/affected-flows"


async def _counts(fixture: dict[str, Any]) -> list[int]:
    async with fixture["sessions"]() as session:
        return [
            await session.scalar(select(func.count()).select_from(model))
            for model in (Workflow, RevisionModel, AIChangeSet, IdempotencyRecord)
        ]


@pytest.mark.asyncio
async def test_affected_flows_resolve_current_and_capability_without_pinned_fallback_or_writes(
    context_inspector: dict[str, Any],
) -> None:
    ids = await _seed(context_inspector)
    before = await _counts(context_inspector)
    response = await context_inspector["client"].get(
        _url(context_inspector),
        headers=context_inspector["headers"],
        params={"before_revision": 2, "after_revision": 3},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total_workflows"] == 3
    affected = {item["workflow_id"]: item for item in result["affected_workflows"]}
    assert set(affected) == {str(ids["current"]), str(ids["capability"])}
    for item in affected.values():
        assert item["draft_revision"] == 3
        assert all(reason["api_version"] == 2 for reason in item["reasons"])
        assert all(reason["match_strength"] == "candidate" for reason in item["reasons"])
        assert all(reason["api_definition_id"] == str(ids["api"]) for reason in item["reasons"])
    assert any(
        item["code"] == "API_UNRESOLVED" and item["workflow_id"] == str(ids["pinned_missing"])
        for item in result["diagnostics"]
    )
    assert result["requires_review"] and not result["automatic_patch_allowed"]
    assert not result["analysis_complete"]
    assert "PRIVATE_" not in response.text
    assert str(ids["foreign"]) not in response.text
    assert await _counts(context_inspector) == before
    async with context_inspector["sessions"]() as session:
        context = await session.get(ContextModel, context_inspector["context_id"])
        assert context.current_revision == 1


@pytest.mark.asyncio
async def test_affected_flows_pagination_is_explicit_and_bounded(
    context_inspector: dict[str, Any],
) -> None:
    ids = await _seed(context_inspector)
    scanned: list[str] = []
    for page in (1, 2, 3, 4):
        response = await context_inspector["client"].get(
            _url(context_inspector),
            headers=context_inspector["headers"],
            params={"before_revision": 1, "after_revision": 1, "page_size": 1, "page": page},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert not result["analysis_complete"]
        assert len(result["scanned_workflow_ids"]) <= 1
        assert result["total_workflows"] == 3
        scanned.extend(result["scanned_workflow_ids"])
    assert set(scanned) == {str(ids[name]) for name in ("current", "pinned_missing", "capability")}
    assert len(scanned) == 3


@pytest.mark.asyncio
async def test_affected_flows_authorization_and_revision_validation(
    context_inspector: dict[str, Any],
) -> None:
    client, headers = context_inspector["client"], context_inspector["headers"]
    params = {"before_revision": 1, "after_revision": 1}
    response = await client.get(_url(context_inspector), params=params)
    assert response.status_code == 401
    response = await client.get(
        _url(context_inspector, context_inspector["other_project_id"]),
        headers=headers,
        params=params,
    )
    assert response.status_code == 404
    for overrides, status in [
        ({"after_revision": 99}, 404),
        ({"before_revision": 0}, 422),
        ({"page_size": 51}, 422),
        ({"page": 0}, 422),
    ]:
        response = await client.get(
            _url(context_inspector), headers=headers, params=params | overrides
        )
        assert response.status_code == status, response.text
        assert response.json()["error"]["trace_id"]


async def _seed_impact(fixture: dict[str, Any], ids: dict[str, UUID], project_id: UUID) -> UUID:
    async with fixture["sessions"]() as session:
        run = ImpactRun(
            project_id=project_id,
            title="PRIVATE_IMPACT",
            source_fingerprint="f" * 64,
            source_summary={},
            change_count=1,
            changes=[{"kind": "git"}],
            graph={},
            summary={},
            created_by_id=ids["actor"],
        )
        session.add(run)
        await session.flush()
        session.add(
            SelectionModel(
                project_id=project_id,
                impact_run_id=run.id,
                selected_assets=[
                    {
                        "target_type": "workflow",
                        "target_id": str(ids["pinned_missing"]),
                        "version": 1,
                        "name": "PRIVATE_ASSET",
                    },
                    {"target_type": "workflow", "target_id": str(ids["foreign"]), "version": 1},
                ],
                explanations=[],
                created_by_id=ids["actor"],
            )
        )
        session.add(
            CoverageSnapshot(
                project_id=project_id,
                impact_run_id=run.id,
                total_changes=1,
                covered_changes=1,
                coverage_percent=100,
                matrix=[],
                gaps=[],
                created_by_id=ids["actor"],
            )
        )
        await session.commit()
        return run.id


@pytest.mark.asyncio
async def test_existing_impact_selection_reused_with_project_isolation(
    context_inspector: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    ids = await _seed(context_inspector)
    run_id = await _seed_impact(context_inspector, ids, context_inspector["project_id"])
    response = await context_inspector["client"].get(
        _url(context_inspector),
        headers=context_inspector["headers"],
        params={"before_revision": 1, "after_revision": 1, "impact_run_id": str(run_id)},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["affected_workflows"]) == 1
    item = result["affected_workflows"][0]
    assert item["workflow_id"] == str(ids["pinned_missing"])
    assert item["reasons"][0]["match_strength"] == "explicit_asset"
    assert item["reasons"][0]["asset_version"] == 1
    assert any(item["code"] == "IMPACT_CHANGE_UNMAPPED" for item in result["diagnostics"])
    assert "PRIVATE_" not in response.text
    assert str(ids["foreign"]) not in response.text
    foreign_id = await _seed_impact(context_inspector, ids, context_inspector["other_project_id"])
    for impact_id in (foreign_id, uuid4()):
        response = await context_inspector["client"].get(
            _url(context_inspector),
            headers=context_inspector["headers"],
            params={"before_revision": 1, "after_revision": 1, "impact_run_id": str(impact_id)},
        )
        assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("invalid_graph", "WORKFLOW_INVALID"),
        ("invalid_config", "WORKFLOW_INVALID"),
        ("subflow", "NODE_NOT_ANALYZED"),
        ("unknown_capability", "NODE_NOT_ANALYZED"),
        ("budget", "WORKFLOW_NODE_BUDGET_EXCEEDED"),
    ],
)
async def test_incomplete_workflow_is_reported_without_raw_configuration(
    context_inspector: dict[str, Any],
    kind: str,
    code: str,
) -> None:
    ids = await _seed(context_inspector)
    draft = _draft(ids["api"], None)
    if kind == "invalid_graph":
        draft = {"nodes": [], "edges": []}
    elif kind == "invalid_config":
        draft["nodes"][1]["config"] = {"api_definition_id": "PRIVATE_INVALID"}
    elif kind == "subflow":
        draft["nodes"][1].update(type="subflow", config={"workflow_id": str(ids["foreign"])})
    elif kind == "unknown_capability":
        draft = _draft(ids["api"], None, True)
        draft["nodes"][1]["capability_id"] = "custom.request"
    else:
        draft = {"nodes": [{}] * 201, "edges": []}
    async with context_inspector["sessions"]() as session:
        workflow = await session.get(Workflow, ids["current"])
        workflow.draft_definition = draft
        await session.commit()
    response = await context_inspector["client"].get(
        _url(context_inspector),
        headers=context_inspector["headers"],
        params={"before_revision": 2, "after_revision": 3},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert any(
        item["code"] == code and item["workflow_id"] == str(ids["current"])
        for item in result["diagnostics"]
    )
    assert not result["analysis_complete"]
    assert "PRIVATE_" not in response.text


@pytest.mark.asyncio
async def test_current_identity_is_resolved_once_per_request(
    context_inspector: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed(context_inspector)
    original = ChangeRegressionService.resolve_operation_identity
    calls: list[int | None] = []

    async def tracked(
        self: ChangeRegressionService,
        *,
        project_id: UUID,
        definition_id: UUID,
        version_number: int | None,
    ) -> Any:
        calls.append(version_number)
        return await original(
            self, project_id=project_id, definition_id=definition_id, version_number=version_number
        )

    monkeypatch.setattr(ChangeRegressionService, "resolve_operation_identity", tracked)
    response = await context_inspector["client"].get(
        _url(context_inspector),
        headers=context_inspector["headers"],
        params={"before_revision": 2, "after_revision": 3},
    )
    assert response.status_code == 200, response.text
    assert calls.count(None) == 1
    assert calls.count(1) == 1


@pytest.mark.asyncio
async def test_nonmember_cannot_analyze_project(context_inspector: dict[str, Any]) -> None:
    async with context_inspector["sessions"]() as session:
        user = User(
            email="outsider@example.test",
            display_name="Outsider",
            password_hash="unused",
            is_active=True,
            is_system_admin=False,
            requires_password_change=False,
        )
        session.add(user)
        await session.commit()
        token = token_service.create_access_token(user.id)
    response = await context_inspector["client"].get(
        _url(context_inspector),
        headers={"Authorization": f"Bearer {token}"},
        params={"before_revision": 1, "after_revision": 1},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert response.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_empty_catalog_same_revision_can_be_complete(
    context_inspector: dict[str, Any],
) -> None:
    response = await context_inspector["client"].get(
        _url(context_inspector),
        headers=context_inspector["headers"],
        params={"before_revision": 1, "after_revision": 1},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis_complete"]
    assert result["total_workflows"] == 0
    assert result["affected_workflows"] == []
    assert not result["automatic_patch_allowed"]


@pytest.mark.asyncio
async def test_impact_operation_changes_use_typed_identity_and_preserve_asset_versions(
    context_inspector: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    ids = await _seed(context_inspector)
    run_id = await _seed_impact(context_inspector, ids, context_inspector["project_id"])
    async with context_inspector["sessions"]() as session:
        run = await session.get(ImpactRun, run_id)
        run.changes = [
            {"api_definition_id": str(ids["api"]), "api_version": 2},
            {"api_definition_id": str(uuid4()), "method": "GET", "normalized_path": "/orders/{}"},
            {
                "api_definition_id": str(ids["api"]),
                "current_contract_fingerprint": "PRIVATE_INVALID",
            },
        ]
        run.change_count = 3
        selection = await session.scalar(
            select(SelectionModel).where(SelectionModel.impact_run_id == run_id)
        )
        selection.selected_assets = [
            *selection.selected_assets,
            {"target_type": "workflow", "target_id": str(ids["pinned_missing"]), "version": 2},
            {"target_type": "workflow", "target_id": "malformed", "version": True},
            {"target_type": "test_case", "target_id": str(ids["current"]), "version": 1},
        ]
        await session.commit()
    response = await context_inspector["client"].get(
        _url(context_inspector),
        headers=context_inspector["headers"],
        params={"before_revision": 1, "after_revision": 1, "impact_run_id": str(run_id)},
    )
    assert response.status_code == 200, response.text
    items = {item["workflow_id"]: item for item in response.json()["affected_workflows"]}
    assert {reason["asset_version"] for reason in items[str(ids["pinned_missing"])]["reasons"]} == {
        1,
        2,
    }
    for name in ("current", "capability"):
        reasons = items[str(ids[name])]["reasons"]
        assert len(reasons) == 1
        assert reasons[0]["match_strength"] == "instance"
        assert reasons[0]["source_ref"].endswith("/changes/0")
    assert "PRIVATE_" not in response.text
