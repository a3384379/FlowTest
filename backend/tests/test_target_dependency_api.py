import socket
from typing import Never
from uuid import UUID

import pytest
import respx
from sqlalchemy import select
from test_api_assets_api import _create_environment, _create_project
from test_api_assets_api import asset_client as asset_client
from test_target_preview_api import PreviewAssets
from test_target_preview_api import preview_assets as preview_assets

from app.core.database import get_session
from app.core.encryption import SecretBox
from app.domain.api_assets import JsonValue
from app.main import app
from app.models.workflows import WorkflowVersion


def _definition(config: dict[str, JsonValue], *, native: bool = False) -> dict[str, JsonValue]:
    node: dict[str, JsonValue] = {
        "id": "request",
        "name": "请求",
        "position": {"x": 100, "y": 0},
        "type": "capability" if native else "api",
    }
    if native:
        node.update(
            capability_id="http.request",
            capability_version="2.0.0",
            configuration=config,
            bindings=[],
        )
    else:
        node["config"] = config
    return {
        "schema_version": "4.0",
        "run_policy": {"request_budget": 10, "max_runtime_seconds": 60},
        "nodes": [
            {"id": "start", "name": "开始", "type": "start", "position": {"x": 0, "y": 0}},
            node,
            {"id": "end", "name": "结束", "type": "end", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "one", "source": "start", "target": "request"},
            {"id": "two", "source": "request", "target": "end"},
        ],
    }


async def _workflow(fixture: PreviewAssets, name: str, definition: dict[str, JsonValue]) -> str:
    response = await fixture.client.post(
        f"{fixture.root}/workflows",
        headers=fixture.headers,
        json={"name": name, "definition": definition},
    )
    assert response.status_code == 201, response.text[:500]
    return response.json()["id"]


async def _publish(fixture: PreviewAssets, identifier: str) -> dict[str, JsonValue]:
    response = await fixture.client.post(
        f"{fixture.root}/workflows/{identifier}/versions",
        headers=fixture.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["definition"]


async def _impact(fixture: PreviewAssets, change: dict[str, JsonValue]) -> dict:
    response = await fixture.client.post(
        f"{fixture.root}/request-targets/impact-preview",
        headers=fixture.headers,
        json={"change": change},
    )
    assert response.status_code == 200, response.text
    assert response.json()["trace_id"]
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@respx.mock
async def test_binding_candidate_follows_current_versions_and_is_read_only(
    preview_assets: PreviewAssets,
    monkeypatch: pytest.MonkeyPatch,
    native: bool,
) -> None:
    fixture = preview_assets
    monkeypatch.setattr("app.services.workflows.settings.feature_capability_sdk_enabled", True)
    current = await _workflow(
        fixture, "跟随当前接口", _definition({"api_definition_id": fixture.api_id}, native=native)
    )
    await _publish(fixture, current)
    pinned = await _workflow(
        fixture,
        "固定历史接口",
        _definition({"api_definition_id": fixture.api_id, "api_version": 1}, native=native),
    )
    await _publish(fixture, pinned)

    # This explicit publication follows API v1; its current draft still follows the latest API.
    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Dependency preview must not decrypt credentials or perform DNS")

    monkeypatch.setattr(SecretBox, "decrypt", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    result = await _impact(
        fixture,
        {"kind": "api_binding", "api_id": fixture.api_id, "service_id": fixture.default_service_id},
    )
    assert result["complete"] is True and result["diagnostics"] == []
    assert [item["id"] for item in result["affected_apis"]] == [fixture.api_id]
    assert [item["id"] for item in result["affected_workflows"]] == [current]
    assert "草稿" in result["affected_workflows"][0]["reason"]
    assert "已发布" not in result["affected_workflows"][0]["reason"]
    stored = await fixture.client.get(
        f"{fixture.root}/apis/{fixture.api_id}", headers=fixture.headers
    )
    assert stored.json()["definition"]["current_version"] == 1
    assert stored.json()["version"]["service_id"] == fixture.service_id
    assert "synthetic-preview-credential" not in str(result)
    assert not respx.routes


@pytest.mark.asyncio
async def test_environment_candidate_uses_case_suite_versions_and_actual_plan_environment(
    preview_assets: PreviewAssets,
) -> None:
    fixture = preview_assets
    project_id = fixture.root.rsplit("/", 1)[1]
    other = await _create_environment(
        fixture.client,
        fixture.headers,
        project_id,
        name="其他环境",
        base_url="https://other.example.test",
        variables={},
        environment_headers={},
    )
    workflow = await _workflow(
        fixture, "继承环境流程", _definition({"api_definition_id": fixture.unbound_api_id})
    )
    await _publish(fixture, workflow)
    overridden = await _workflow(
        fixture,
        "节点覆盖流程",
        _definition({"api_definition_id": fixture.unbound_api_id, "service_override": "orders"}),
    )
    case = await fixture.client.post(
        f"{fixture.root}/test-cases",
        headers=fixture.headers,
        json={
            "name": "固定来源环境用例",
            "definition": {
                "workflow_id": workflow,
                "workflow_version": 1,
                "environment_id": fixture.environment_id,
            },
        },
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    case_version = await fixture.client.post(
        f"{fixture.root}/test-cases/{case_id}/versions", headers=fixture.headers, json={}
    )
    assert case_version.status_code == 200, case_version.text
    suite = await fixture.client.post(
        f"{fixture.root}/test-suites",
        headers=fixture.headers,
        json={
            "name": "固定成员套件",
            "definition": {"items": [{"test_case_id": case_id, "test_case_version": 1}]},
        },
    )
    assert suite.status_code == 201, suite.text
    suite_id = suite.json()["id"]
    suite_version = await fixture.client.post(
        f"{fixture.root}/test-suites/{suite_id}/versions", headers=fixture.headers, json={}
    )
    assert suite_version.status_code == 200, suite_version.text
    # Current case draft changes environment; the suite and plan must keep case version 1.
    updated = await fixture.client.patch(
        f"{fixture.root}/test-cases/{case_id}",
        headers=fixture.headers,
        json={
            "definition": {
                "workflow_id": workflow,
                "workflow_version": 1,
                "environment_id": other["id"],
            }
        },
    )
    assert updated.status_code == 200, updated.text
    plan_ids = []
    for name, items in [
        (
            "候选环境计划",
            [
                {
                    "workflow_id": workflow,
                    "workflow_version": 1,
                    "environment_id": fixture.environment_id,
                }
            ],
        ),
        (
            "其他环境计划",
            [{"workflow_id": workflow, "workflow_version": 1, "environment_id": other["id"]}],
        ),
        ("固定用例计划", [{"target_type": "case", "target_id": case_id, "target_version": 1}]),
        ("固定套件计划", [{"target_type": "suite", "target_id": suite_id, "target_version": 1}]),
    ]:
        plan = await fixture.client.post(
            f"{fixture.root}/test-plans",
            headers=fixture.headers,
            json={"name": name, "schedule_interval_seconds": 60, "enabled": False, "items": items},
        )
        assert plan.status_code == 201, plan.text
        plan_ids.append(plan.json()["id"])
    result = await _impact(
        fixture,
        {
            "kind": "environment_default",
            "environment_id": fixture.environment_id,
            "service_id": fixture.service_id,
        },
    )
    assert result["complete"] is True, result["diagnostics"]
    assert {item["id"] for item in result["affected_workflows"]} == {workflow}
    assert overridden not in {item["id"] for item in result["affected_workflows"]}
    expected = {plan_ids[0], plan_ids[2], plan_ids[3]}
    assert {item["id"] for item in result["affected_test_plans"]} == expected
    assert {item["id"] for item in result["affected_scheduled_runs"]} == expected
    assert all("已禁用" in item["reason"] for item in result["affected_scheduled_runs"])
    assert {item["id"] for item in result["affected_apis"]} == {fixture.unbound_api_id}


@pytest.mark.asyncio
async def test_endpoint_candidate_follows_variants_and_historical_subflow_references(
    preview_assets: PreviewAssets,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = preview_assets
    monkeypatch.setattr("app.services.workflows.settings.feature_capability_sdk_enabled", True)
    source_definition = _definition(
        {"api_definition_id": fixture.api_id, "endpoint_variant": "default"}
    )
    child = await _workflow(fixture, "历史子流程", source_definition)
    await _publish(fixture, child)
    other = await _workflow(
        fixture,
        "独立灰度节点",
        _definition({"api_definition_id": fixture.api_id, "endpoint_variant": "canary"}),
    )
    parent_definition = _definition({})
    nodes = parent_definition["nodes"]
    assert isinstance(nodes, list) and isinstance(nodes[1], dict)
    nodes[1].update(type="subflow", config={"workflow_id": child, "workflow_version": 1})
    parent = await _workflow(fixture, "父流程固定引用", parent_definition)
    await _publish(fixture, parent)
    result = await _impact(
        fixture, {"kind": "endpoint", "endpoint_id": fixture.endpoint_id, "variant": "renamed"}
    )
    assert result["complete"] is True, result["diagnostics"]
    assert {item["id"] for item in result["affected_workflows"]} == {child, parent}
    assert other not in {item["id"] for item in result["affected_workflows"]}
    # An older publication may contain unpinned HTTP references; analyze its actual snapshot.
    sessions = app.dependency_overrides[get_session]()
    async for session in sessions:
        version = await session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == UUID(child), WorkflowVersion.version == 1
            )
        )
        assert version is not None
        version.definition = source_definition
        await session.commit()
    binding = await _impact(
        fixture,
        {"kind": "api_binding", "api_id": fixture.api_id, "service_id": fixture.default_service_id},
    )
    assert {item["id"] for item in binding["affected_workflows"]} == {child, parent, other}
    child_item = next(item for item in binding["affected_workflows"] if item["id"] == child)
    assert "已发布 v1" in child_item["reason"]


@pytest.mark.asyncio
async def test_dependency_preview_rejects_cross_project_and_oversized_definitions_are_incomplete(
    preview_assets: PreviewAssets,
) -> None:
    fixture = preview_assets
    foreign = await _create_project(fixture.client, fixture.headers, "其他项目")
    response = await fixture.client.post(
        f"/api/v1/projects/{foreign['id']}/request-targets/impact-preview",
        headers=fixture.headers,
        json={
            "change": {
                "kind": "api_binding",
                "api_id": fixture.api_id,
                "service_id": fixture.service_id,
            }
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["trace_id"]
    oversized = _definition({"api_definition_id": fixture.api_id})
    oversized["variables"] = {"large": "x" * 110_000}
    await _workflow(fixture, "超大定义", oversized)
    result = await _impact(fixture, {"kind": "service", "service_id": fixture.service_id})
    assert result["complete"] is False
    assert any(item["code"] == "CATALOG_LIMIT" for item in result["diagnostics"])
    assert result["affected_workflows"] == []


@pytest.mark.asyncio
async def test_dependency_directory_retains_every_reference_beyond_first_hundred(
    preview_assets: PreviewAssets,
) -> None:
    fixture = preview_assets
    identifiers = set()
    for index in range(105):
        identifiers.add(
            await _workflow(
                fixture, f"完整引用范围{index}", _definition({"api_definition_id": fixture.api_id})
            )
        )
    result = await _impact(fixture, {"kind": "service", "service_id": fixture.service_id})
    assert result["complete"] is True, result["diagnostics"]
    assert {item["id"] for item in result["affected_workflows"]} == identifiers
    assert len(result["affected_workflows"]) == 105
