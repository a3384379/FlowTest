from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import pytest
from sqlalchemy import select
from test_quality_intelligence import (
    ADMIN_EMAIL,
    QualityContext,
    _login,
    _project,
    _workflow_definition,
)
from test_quality_intelligence import quality_context as quality_context

from app.core.redaction import project_redaction_policy
from app.models.access import Project, User
from app.models.ai import AIChangeItem, AIChangeSet, AIJob, AISuggestion
from app.models.test_assets import TestCase as CaseModel
from app.models.workflows import Workflow
from app.services.ai_change_sets import _target_hash

AssetType = Literal["test_case", "workflow"]


@dataclass(frozen=True)
class ReviewTarget:
    project_id: str
    resource_id: str
    definition: dict[str, Any]


async def _review_target(
    context: QualityContext, headers: dict[str, str], asset_type: AssetType, mode: str
) -> ReviewTarget:
    project_id = await _project(context.client, headers, f"审核策略 {asset_type} {mode}")
    policy = await context.client.put(
        f"/api/v1/projects/{project_id}/redaction-policy",
        headers=headers,
        json={"mode": mode},
    )
    assert policy.status_code == 200, policy.text
    workflow_definition = _workflow_definition()
    workflow_definition["variables"] = {"existing": "original-variable"}
    workflow_definition["nodes"][0]["config"] = {
        "existing": "original-config",
        "items": ["first", "second"],
    }
    workflow = await context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "人工维护流程", "definition": workflow_definition},
    )
    assert workflow.status_code == 201, workflow.text
    if asset_type == "workflow":
        workflow_id = workflow.json()["id"]
        return ReviewTarget(
            project_id, workflow_id, await _stored_definition(context, asset_type, workflow_id)
        )
    environment = await context.client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "测试环境", "base_url": "https://example.test"},
    )
    assert environment.status_code == 201, environment.text
    definition = {
        "workflow_id": workflow.json()["id"],
        "environment_id": environment.json()["id"],
        "runtime_variables": {"existing": "original-variable"},
        "runtime_headers": {"X-Existing": "original-header"},
    }
    case = await context.client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        headers=headers,
        json={"name": "人工维护用例", "definition": definition},
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    return ReviewTarget(project_id, case_id, await _stored_definition(context, asset_type, case_id))


async def _review_item(
    context: QualityContext,
    target: ReviewTarget,
    asset_type: AssetType,
    action: str,
    definition: dict[str, Any],
) -> tuple[UUID, UUID]:
    async with context.sessions() as session:
        actor_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        assert actor_id is not None
        resource = await session.get(
            Workflow if asset_type == "workflow" else CaseModel, UUID(target.resource_id)
        )
        assert resource is not None
        project = await session.get(Project, UUID(target.project_id))
        assert project is not None
        policy = project_redaction_policy(project)
        job = AIJob(
            project_id=project.id,
            redaction_mode=policy.mode.value,
            redaction_policy_version=policy.policy_version,
            job_type="change_set",
            status="completed",
            sanitized_input={},
            input_sha256="a" * 64,
            prompt_template_version="test-review-policy-v1",
            model_name="synthetic-review-provider",
            created_by_id=actor_id,
        )
        session.add(job)
        await session.flush()
        proposal = {"name": f"审核后 {action} 草稿", "definition": definition}
        suggestion = AISuggestion(
            job_id=job.id,
            position=0,
            suggestion_type=asset_type,
            title="审核后草稿",
            content={
                "action": action,
                "target_id": str(resource.id) if action == "update" else None,
                **proposal,
            },
        )
        change_set = AIChangeSet(
            project_id=UUID(target.project_id),
            ai_job_id=job.id,
            title="人工审核草稿",
            status="draft",
            source_snapshot={},
            source_fingerprint="a" * 64,
            created_by_id=actor_id,
        )
        session.add_all([change_set, suggestion])
        await session.flush()
        item = AIChangeItem(
            change_set_id=change_set.id,
            suggestion_id=suggestion.id,
            position=0,
            item_type=asset_type,
            action=action,
            title="审核后草稿",
            target_resource_id=resource.id if action == "update" else None,
            target_snapshot_sha256=_target_hash(resource) if action == "update" else None,
            proposed_content=proposal,
        )
        session.add(item)
        await session.commit()
        return change_set.id, item.id


def _literal_definition(target: ReviewTarget, asset_type: AssetType, field: str) -> dict[str, Any]:
    definition = deepcopy(target.definition)
    if asset_type == "test_case":
        definition["runtime_variables"] = {field: "[REDACTED]"}
        definition["runtime_headers"] = {
            "X-Existing" if field == "existing" else "X-New": "[REDACTED]"
        }
        return definition
    definition["variables"] = {field: "[REDACTED]"}
    definition["nodes"][0]["config"] = {
        field: "[REDACTED]",
        "items": ["[REDACTED]", "literal [REDACTED] suffix", {"new": "[REDACTED]"}],
    }
    return definition


async def _stored_definition(
    context: QualityContext, asset_type: AssetType, resource_id: str
) -> dict[str, Any]:
    async with context.sessions() as session:
        resource = await session.get(
            Workflow if asset_type == "workflow" else CaseModel, UUID(resource_id)
        )
        assert resource is not None
        assert resource.current_version is None
        return resource.draft_definition


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", ["workflow", "test_case"])
@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("field", ["existing", "new"])
async def test_off_review_preserves_literal_redacted_values(
    quality_context: QualityContext, asset_type: AssetType, action: str, field: str
) -> None:
    headers = await _login(quality_context.client)
    target = await _review_target(quality_context, headers, asset_type, "off")
    definition = _literal_definition(target, asset_type, field)
    change_id, item_id = await _review_item(quality_context, target, asset_type, action, definition)
    response = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_id}/items/{item_id}/accept",
        headers=headers,
        json={"content": {"name": "审核后草稿", "definition": definition}},
    )
    assert response.status_code == 200, response.text
    stored = await _stored_definition(
        quality_context, asset_type, response.json()["materialized_resource_id"]
    )
    for field_name in definition:
        assert stored[field_name] == definition[field_name]


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", ["workflow", "test_case"])
@pytest.mark.parametrize("mode", ["off", "on"])
async def test_review_update_preserves_omitted_runtime_fields(
    quality_context: QualityContext, asset_type: AssetType, mode: str
) -> None:
    headers = await _login(quality_context.client)
    target = await _review_target(quality_context, headers, asset_type, mode)
    definition = deepcopy(target.definition)
    if asset_type == "workflow":
        definition.pop("variables")
        definition["nodes"][0].pop("config")
    else:
        definition.pop("runtime_variables")
        definition.pop("runtime_headers")
    change_id, item_id = await _review_item(
        quality_context, target, asset_type, "update", definition
    )
    response = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_id}/items/{item_id}/accept",
        headers=headers,
        json={},
    )
    assert response.status_code == 200, response.text
    stored = await _stored_definition(quality_context, asset_type, target.resource_id)
    for field_name in target.definition:
        assert stored[field_name] == target.definition[field_name]


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", ["workflow", "test_case"])
async def test_review_redacted_guard_is_scoped_to_each_project_request(
    quality_context: QualityContext, asset_type: AssetType
) -> None:
    headers = await _login(quality_context.client)
    off_target = await _review_target(quality_context, headers, asset_type, "off")
    on_target = await _review_target(quality_context, headers, asset_type, "on")
    original_on = await _stored_definition(quality_context, asset_type, on_target.resource_id)
    for target, action, accepted in [
        (on_target, "create", False),
        (off_target, "create", True),
        (on_target, "update", False),
        (off_target, "update", True),
    ]:
        definition = _literal_definition(target, asset_type, "new")
        change_id, item_id = await _review_item(
            quality_context, target, asset_type, action, definition
        )
        response = await quality_context.client.post(
            f"/api/v1/ai/change-sets/{change_id}/items/{item_id}/accept",
            headers=headers,
            json={},
        )
        if accepted:
            assert response.status_code == 200, response.text
            stored = await _stored_definition(
                quality_context, asset_type, response.json()["materialized_resource_id"]
            )
            for field_name in definition:
                assert stored[field_name] == definition[field_name]
        else:
            assert response.status_code == 422, response.text
            expected_code = (
                f"AI_{asset_type.upper()}_DRAFT_SECRET_BINDING_REQUIRED"
                if action == "create"
                else "AI_REDACTED_VALUE_INVALID"
            )
            assert response.json()["error"]["code"] == expected_code
            assert response.json()["error"]["trace_id"]
            async with quality_context.sessions() as session:
                item = await session.get(AIChangeItem, item_id)
                assert item is not None
                assert item.review_status == "pending"
            assert (
                await _stored_definition(quality_context, asset_type, target.resource_id)
                == original_on
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", ["workflow", "test_case"])
async def test_on_review_restores_known_redacted_values(
    quality_context: QualityContext, asset_type: AssetType
) -> None:
    headers = await _login(quality_context.client)
    target = await _review_target(quality_context, headers, asset_type, "on")
    definition = deepcopy(target.definition)
    if asset_type == "workflow":
        definition["variables"] = {"existing": "[REDACTED]"}
        definition["nodes"][0]["config"] = {
            "existing": "[REDACTED]",
            "items": ["[REDACTED]", "[REDACTED]"],
        }
    else:
        definition["runtime_variables"] = {"existing": "[REDACTED]"}
        definition["runtime_headers"] = {"X-Existing": "[REDACTED]"}
    change_id, item_id = await _review_item(
        quality_context, target, asset_type, "update", definition
    )
    response = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_id}/items/{item_id}/accept",
        headers=headers,
        json={},
    )
    assert response.status_code == 200, response.text
    assert (
        await _stored_definition(quality_context, asset_type, target.resource_id)
        == target.definition
    )


@pytest.mark.asyncio
async def test_on_review_rejects_partial_edits_to_redacted_lists(
    quality_context: QualityContext,
) -> None:
    headers = await _login(quality_context.client)
    target = await _review_target(quality_context, headers, "workflow", "on")
    definition = deepcopy(target.definition)
    definition["nodes"][0]["config"]["items"] = ["replacement", "[REDACTED]"]
    change_id, item_id = await _review_item(
        quality_context, target, "workflow", "update", definition
    )
    response = await quality_context.client.post(
        f"/api/v1/ai/change-sets/{change_id}/items/{item_id}/accept",
        headers=headers,
        json={},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "AI_REDACTED_LIST_STRUCTURE_INVALID"
    assert response.json()["error"]["trace_id"]
    assert (
        await _stored_definition(quality_context, "workflow", target.resource_id)
        == target.definition
    )
