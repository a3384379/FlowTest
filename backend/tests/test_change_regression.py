import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_test_plan_dispatcher, get_workflow_coordinator
from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.main import app
from app.models import Base
from app.models import TestCase as ORMTestCase
from app.models import TestDesign as ORMTestDesign
from app.models.access import User
from app.services.change_regression import (
    _add_semantic_value,
    _merge_workflow_semantics,
    _test_case_workflow_id,
)
from app.services.execution_events import ExecutionEvent
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator

ADMIN_EMAIL = "regression-admin@example.com"
ADMIN_PASSWORD = "regression-password-123!"


@dataclass(slots=True)
class RegressionContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    queue: "RecordingQueue"
    events: "RecordingEventBus"


@pytest.fixture
async def regression_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[RegressionContext]:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    monkeypatch.setattr("app.services.artifacts.object_storage", MemoryObjectStorage())
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'change-regression.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Regression administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    events = RecordingEventBus()
    coordinator = WorkflowRunCoordinator(sessions, events)
    queue = RecordingQueue()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workflow_coordinator] = lambda: coordinator
    app.dependency_overrides[get_test_plan_dispatcher] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield RegressionContext(client, sessions, queue, events)
    await coordinator.shutdown()
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
@respx.mock
async def test_change_to_release_gate_trace_and_missing_test_review(
    regression_context: RegressionContext,
) -> None:
    context = regression_context
    headers = await _login_headers(context.client)
    project_id, environment_id, workflow_id = await _create_workflow(context.client, headers)
    plan = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "S45 回归计划",
            "items": [{"workflow_id": workflow_id, "environment_id": environment_id}],
        },
    )
    assert plan.status_code == 201, plan.text
    policy = await context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json={
            "name": "S45 最小门禁",
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": True,
            "min_impact_coverage_percent": 100,
            "require_release_risk": False,
        },
    )
    assert policy.status_code == 201, policy.text
    mapping = await context.client.post(
        f"/api/v1/projects/{project_id}/impact/mappings",
        headers=headers,
        json={
            "source_kind": "git",
            "source_selector": "backend/*",
            "target_type": "workflow",
            "target_id": workflow_id,
        },
    )
    assert mapping.status_code == 201, mapping.text

    source_change = _git_diff("backend/orders.py")
    token_created = await context.client.post(
        f"/api/v1/projects/{project_id}/service-tokens",
        headers=headers,
        json={"name": "S45 GitHub Actions", "scopes": ["analyze:change-regression"]},
    )
    assert token_created.status_code == 201, token_created.text
    ci_headers = {
        "Authorization": f"Bearer {token_created.json()['token']}",
        "Idempotency-Key": "s45-ci-change-abc123",
    }
    ci_payload = {
        "title": "CI 订单变更回归",
        "source_ref": "github://acme/flowtest/pull/42",
        "candidate_ref": "commit:abc123",
        "git_diff": source_change,
        "test_plan_id": plan.json()["id"],
        "release_policy_id": policy.json()["id"],
    }
    missing_auth = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        json=ci_payload,
    )
    assert missing_auth.status_code == 401
    malformed_auth = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        headers={"Authorization": "Token malformed"},
        json=ci_payload,
    )
    assert malformed_auth.status_code == 401
    ci_created = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        headers=ci_headers,
        json=ci_payload,
    )
    assert ci_created.status_code == 201, ci_created.text
    ci_replayed = await context.client.post(
        f"/api/v1/ci/projects/{project_id}/change-regressions",
        headers=ci_headers,
        json=ci_payload,
    )
    assert ci_replayed.status_code == 201, ci_replayed.text
    assert ci_replayed.json()["id"] == ci_created.json()["id"]
    listed = await context.client.get(
        f"/api/v1/projects/{project_id}/change-regressions", headers=headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    detail = await context.client.get(
        f"/api/v1/projects/{project_id}/change-regressions/{ci_created.json()['id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == ci_created.json()["id"]

    created = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions",
        headers=headers,
        json={
            "title": "订单变更回归",
            "source_ref": "github://acme/flowtest/commit/abc123",
            "candidate_ref": "commit:abc123",
            "git_diff": source_change,
            "test_plan_id": plan.json()["id"],
            "release_policy_id": policy.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "review_required"
    assert run["change_set_id"] is None
    assert [stage["stage"] for stage in run["stages"]] == [
        "change",
        "impact",
        "regression_selection",
        "missing_test",
        "review",
    ]
    approved = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{run['id']}/approve",
        headers=headers,
        json={"note": "已确认选择范围"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    queued = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{run['id']}/execute",
        headers=headers,
    )
    assert queued.status_code == 202, queued.text
    test_plan_run_id = UUID(queued.json()["test_plan_run_id"])
    assert context.queue.test_plan_run_ids == [test_plan_run_id]
    respx.get("http://workflow.example.com/users/v1").mock(
        return_value=Response(200, json={"id": 7})
    )
    await PlanRunCoordinator(context.sessions, context.events).run(test_plan_run_id)
    decision = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{run['id']}/release-gate",
        headers=headers,
    )
    assert decision.status_code == 200, decision.text
    final = decision.json()
    assert final["status"] == "passed"
    assert final["release_decision_id"]
    assert final["evidence"]["impact"]["run_id"] == final["impact_run_id"]
    assert {stage["stage"] for stage in final["stages"]} >= {
        "execution",
        "evidence",
        "release_gate",
    }

    missing = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions",
        headers=headers,
        json={
            "title": "未映射变更回归",
            "source_ref": "github://acme/flowtest/commit/def456",
            "candidate_ref": "commit:def456",
            "git_diff": _git_diff("docs/unmapped.md"),
            "test_plan_id": plan.json()["id"],
            "release_policy_id": policy.json()["id"],
        },
    )
    assert missing.status_code == 201, missing.text
    missing_body = missing.json()
    assert missing_body["change_set_id"]
    assert len(missing_body["missing_tests"]) == 1
    item_id = missing_body["missing_tests"][0]["item_id"]
    reviewed = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{missing_body['id']}"
        f"/change-set-items/{item_id}/accept",
        headers=headers,
        json={"note": "低置信度草案已人工确认"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["missing_tests"][0]["review_status"] == "accepted"
    assert reviewed.json()["missing_tests"][0]["materialized_resource_type"] == "test_design"
    approved_missing = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{missing_body['id']}/approve",
        headers=headers,
        json={"note": "批准补齐测试设计"},
    )
    assert approved_missing.status_code == 200, approved_missing.text
    assert approved_missing.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_semantic_gap_is_independent_from_asset_mapping_and_uses_current_contract(
    regression_context: RegressionContext,
) -> None:
    context = regression_context
    headers = await _login_headers(context.client)
    project_id, environment_id, plan_workflow_id = await _create_workflow(context.client, headers)
    plan = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "S47.1 语义覆盖计划",
            "items": [{"workflow_id": plan_workflow_id, "environment_id": environment_id}],
        },
    )
    policy = await context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json={
            "name": "S47.1 语义覆盖门禁",
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": False,
            "require_release_risk": False,
        },
    )
    assert plan.status_code == 201, plan.text
    assert policy.status_code == 201, policy.text

    baseline_document = _orders_openapi(maximum=100)
    baseline_import = await _upload_openapi(context.client, headers, project_id, baseline_document)
    assert baseline_import.status_code == 201, baseline_import.text
    api_definition_id = baseline_import.json()["results"][0]["definition_id"]
    generated = await context.client.post(
        f"/api/v1/projects/{project_id}/test-engineering/generate",
        headers=headers,
        json={"api_definition_id": api_definition_id},
    )
    assert generated.status_code == 200, generated.text
    covered_scenarios = [
        scenario["id"]
        for scenario in generated.json()["design"]["scenarios"]
        if any(
            mutation["path"] == "body.quantity" and mutation.get("value") in {99, 100, 101}
            for mutation in scenario["mutations"]
        )
    ]
    assert len(covered_scenarios) == 3
    proposal = await context.client.post(
        f"/api/v1/projects/{project_id}/test-engineering/proposals",
        headers=headers,
        json={
            "title": "S47.1 旧边界生成测试",
            "api_definition_id": api_definition_id,
            "environment_id": environment_id,
            "scenario_ids": covered_scenarios,
        },
    )
    assert proposal.status_code == 201, proposal.text
    change_set_id = proposal.json()["change_set_id"]
    reviewed = await context.client.post(
        f"/api/v1/projects/{project_id}/test-engineering/proposals/{change_set_id}/review",
        headers=headers,
        json={"accept": True, "note": "确认旧边界覆盖"},
    )
    assert reviewed.status_code == 200, reviewed.text
    applied = await context.client.post(
        f"/api/v1/projects/{project_id}/test-engineering/proposals/{change_set_id}/apply",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    generated_workflow_ids = applied.json()["workflow_ids"]
    generated_workflow_id = generated_workflow_ids[0]
    for generated_id in generated_workflow_ids:
        generated_published = await context.client.post(
            f"/api/v1/projects/{project_id}/workflows/{generated_id}/versions",
            headers=headers,
        )
        assert generated_published.status_code == 200, generated_published.text

    inventory_api = await context.client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "Inventory quantity API",
            "request": {
                "method": "POST",
                "path": "/inventory",
                "body_kind": "json",
                "body": {"quantity": 1},
            },
        },
    )
    assert inventory_api.status_code == 201, inventory_api.text
    inventory_workflow = await context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "Inventory 999 and 1000 coverage",
            "definition": _quantity_workflow_definition(
                inventory_api.json()["definition"]["id"],
                values=(999, 1000),
            ),
        },
    )
    assert inventory_workflow.status_code == 201, inventory_workflow.text
    inventory_published = await context.client.post(
        f"/api/v1/projects/{project_id}/workflows/{inventory_workflow.json()['id']}/versions",
        headers=headers,
    )
    assert inventory_published.status_code == 200, inventory_published.text

    baseline_run_id = await _create_contract_run(
        context.client, headers, project_id, baseline_document, "orders-baseline.json"
    )
    current_document = _orders_openapi(maximum=999)
    current_import = await _upload_openapi(context.client, headers, project_id, current_document)
    assert current_import.status_code == 201, current_import.text
    current_run_id = await _create_contract_run(
        context.client, headers, project_id, current_document, "orders-current.json"
    )
    mapping = await context.client.post(
        f"/api/v1/projects/{project_id}/impact/mappings",
        headers=headers,
        json={
            "source_kind": "openapi",
            "source_selector": "POST /orders",
            "target_type": "workflow",
            "target_id": generated_workflow_id,
        },
    )
    assert mapping.status_code == 201, mapping.text

    run = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions",
        headers=headers,
        json={
            "title": "S47.1 maximum 语义变化",
            "source_ref": "openapi://orders/maximum",
            "candidate_ref": "contract:orders-v2",
            "openapi_diffs": [
                {
                    "baseline_run_id": baseline_run_id,
                    "current_run_id": current_run_id,
                }
            ],
            "test_plan_id": plan.json()["id"],
            "release_policy_id": policy.json()["id"],
        },
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["selection_summary"]["asset_coverage_gap_count"] == 0
    assert body["selection_summary"]["semantic_gap_count"] == 1
    assert len(body["missing_tests"]) == 1
    draft = body["missing_tests"][0]["proposed_content"]
    values = {
        mutation.get("value")
        for scenario in draft["scenarios"]
        for mutation in scenario["mutations"]
        if mutation["path"] == "body.quantity"
    }
    # 101 carried an invalid-request oracle under the previous maximum. It now
    # expects success, so value-only matching must not hide the changed semantic.
    assert values == {101, 999, 1000}
    semantic_scope = body["selection_summary"]["semantic_coverage_scopes"][0]
    assert "999|invalid_request" not in semantic_scope["project_known_values"]
    status_oracles = {
        oracle["expected"] for oracle in draft["oracles"] if oracle["kind"] == "status"
    }
    assert status_oracles == {201, 422}

    item_id = body["missing_tests"][0]["item_id"]
    accepted = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions/{body['id']}"
        f"/change-set-items/{item_id}/accept",
        headers=headers,
        json={
            "note": "确认新边界语义并物化",
            "materialization": {
                "api_definition_id": api_definition_id,
                "environment_id": environment_id,
                "scenario_ids": [scenario["id"] for scenario in draft["scenarios"]],
            },
        },
    )
    assert accepted.status_code == 200, accepted.text
    accepted_item = accepted.json()["missing_tests"][0]
    assert accepted_item["materialized_resource_type"] == "test_design_bundle"
    assert accepted_item["materialized_resource_id"]
    async with context.sessions() as session:
        materialized_design = await session.get(
            ORMTestDesign, UUID(accepted_item["materialized_resource_id"])
        )
        assert materialized_design is not None
        case_ids = [
            UUID(value.removeprefix("testcase://")) for value in materialized_design.test_case_refs
        ]
        materialized_cases = list(
            (await session.scalars(select(ORMTestCase).where(ORMTestCase.id.in_(case_ids)))).all()
        )
    for materialized_case in materialized_cases:
        materialized_workflow_id = materialized_case.draft_definition["workflow_id"]
        materialized_published = await context.client.post(
            f"/api/v1/projects/{project_id}/workflows/{materialized_workflow_id}/versions",
            headers=headers,
        )
        assert materialized_published.status_code == 200, materialized_published.text

    scoped = await context.client.post(
        f"/api/v1/projects/{project_id}/change-regressions",
        headers=headers,
        json={
            "title": "S47.2 current plan semantic scope",
            "source_ref": "openapi://orders/maximum",
            "candidate_ref": "contract:orders-v2-scoped",
            "openapi_diffs": [
                {
                    "baseline_run_id": baseline_run_id,
                    "current_run_id": current_run_id,
                }
            ],
            "test_plan_id": plan.json()["id"],
            "release_policy_id": policy.json()["id"],
        },
    )
    assert scoped.status_code == 201, scoped.text
    scoped_body = scoped.json()
    semantic_scope = scoped_body["selection_summary"]["semantic_coverage_scopes"][0]
    assert semantic_scope["operation"]["api_definition_id"] == api_definition_id
    assert semantic_scope["project_known_coverage"] == "covered"
    assert semantic_scope["current_test_plan_coverage"] == "missing"
    assert scoped_body["selection_summary"]["semantic_gap_count"] == 0
    assert scoped_body["missing_tests"] == []
    assert (
        scoped_body["selection_summary"]["current_plan_recommendations"][0]["action"]
        == "add_project_known_test_to_current_plan"
    )


def test_existing_workflow_semantics_extracts_locations_and_treats_opaque_data_as_unknown() -> None:
    coverage: dict[str, set[str]] = {}
    _merge_workflow_semantics(coverage, {"nodes": "opaque"})
    _merge_workflow_semantics(
        coverage,
        {
            "variables": {"tenant_id": "tenant-1"},
            "nodes": [
                "opaque",
                {"type": "delay", "config": {}},
                {"type": "api", "config": "opaque"},
                {"type": "api", "config": {}},
                {
                    "type": "api",
                    "config": {
                        "request_overrides": {
                            "query_parameters": [
                                {"name": "page", "value": 2},
                                {"value": "ignored"},
                            ],
                            "headers": {"X-Mode": "safe"},
                            "body": {
                                "kind": "json",
                                "value": {"order": {"quantity": 99}, "tags": ["A", "B"]},
                            },
                        }
                    },
                },
            ],
        },
    )
    _add_semantic_value(coverage, "body.opaque", object())

    assert coverage == {
        "path.tenant_id": {'"tenant-1"'},
        "query.page": {"2"},
        "header.X-Mode": {'"safe"'},
        "body.order.quantity": {"99"},
        "body.tags": {'"A"', '"B"'},
    }
    assert _test_case_workflow_id({}) is None
    assert _test_case_workflow_id({"workflow_id": "invalid"}) is None


class RecordingQueue:
    def __init__(self) -> None:
        self.test_plan_run_ids: list[UUID] = []

    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        del queue_name, priority
        self.test_plan_run_ids.append(run_id)


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    async def publish(self, event: ExecutionEvent) -> ExecutionEvent:
        stored = event.model_copy(update={"sequence": len(self.events) + 1})
        self.events.append(stored)
        return stored


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}

    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = StoredObject(content=content, content_type=content_type)

    async def get(self, *, key: str) -> StoredObject:
        return self.objects[key]

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_workflow(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    project = await client.post(
        "/api/v1/projects", headers=headers, json={"name": "S45 项目", "description": ""}
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    environment = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "S45 环境", "base_url": "http://workflow.example.com"},
    )
    api = await client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "S45 API",
            "request": {"method": "GET", "path": "/users/v1", "body_kind": "none"},
        },
    )
    api_id = api.json()["definition"]["id"]
    workflow = await client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "S45 流程", "definition": _workflow_definition(api_id)},
    )
    workflow_id = workflow.json()["id"]
    published = await client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    return project_id, environment.json()["id"], workflow_id


def _workflow_definition(api_id: str) -> dict[str, object]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "api",
                "type": "api",
                "name": "查询用户",
                "position": {"x": 100, "y": 0},
                "config": {"api_definition_id": api_id},
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "start-api", "source": "start", "target": "api"},
            {"id": "api-end", "source": "api", "target": "end"},
        ],
    }


def _quantity_workflow_definition(api_id: str, *, values: tuple[int, ...]) -> dict[str, object]:
    request_nodes = [
        {
            "id": f"quantity-{value}",
            "type": "api",
            "name": f"Quantity {value}",
            "position": {"x": 100 * index, "y": 0},
            "config": {
                "api_definition_id": api_id,
                "expected_statuses": [422],
                "request_overrides": {"body": {"kind": "json", "value": {"quantity": value}}},
            },
        }
        for index, value in enumerate(values, start=1)
    ]
    node_ids = ["start", *(node["id"] for node in request_nodes), "end"]
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "Start", "position": {"x": 0, "y": 0}},
            *request_nodes,
            {"id": "end", "type": "end", "name": "End", "position": {"x": 400, "y": 0}},
        ],
        "edges": [
            {
                "id": f"{source}-{target}",
                "source": source,
                "target": target,
            }
            for source, target in pairwise(node_ids)
        ],
    }


async def _upload_openapi(
    client: AsyncClient, headers: dict[str, str], project_id: str, content: bytes
):
    return await client.post(
        f"/api/v1/projects/{project_id}/imports",
        headers=headers,
        files={"document": ("orders.json", content, "application/json")},
        data={"source_type": "openapi3"},
    )


async def _create_contract_run(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    content: bytes,
    filename: str,
) -> str:
    response = await client.post(
        f"/api/v1/projects/{project_id}/contract-runs",
        headers=headers,
        files={"document": (filename, content, "application/json")},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _orders_openapi(*, maximum: int) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S47.1 Orders", "version": str(maximum)},
            "paths": {
                "/orders": {
                    "post": {
                        "operationId": "createOrder",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["quantity"],
                                        "properties": {
                                            "quantity": {
                                                "type": "integer",
                                                "minimum": 1,
                                                "maximum": maximum,
                                            }
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "201": {
                                "description": "created",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["id"],
                                            "properties": {"id": {"type": "string"}},
                                        }
                                    }
                                },
                            },
                            "422": {"description": "invalid request"},
                        },
                    }
                }
            },
        }
    ).encode()


def _git_diff(path: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
