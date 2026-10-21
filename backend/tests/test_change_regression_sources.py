from dataclasses import dataclass
from hashlib import sha256
from typing import TypedDict
from uuid import UUID

import pytest
from sqlalchemy import select
from test_change_regression import (
    RegressionContext,
    _create_contract_run,
    _create_workflow,
    _git_diff,
    _login_headers,
    _orders_openapi,
)
from test_change_regression import regression_context as regression_context
from test_impact_engine import _compiled_proto

from app.models.access import User
from app.models.protocols import SchemaArtifact


class OpenApiReference(TypedDict):
    baseline_run_id: str
    current_run_id: str


class SchemaReference(TypedDict):
    baseline_artifact_id: str
    current_artifact_id: str


class SourceRequest(TypedDict, total=False):
    title: str
    source_ref: str
    candidate_ref: str
    git_diff: str
    test_plan_id: str
    release_policy_id: str
    generate_missing_tests: bool
    openapi_diffs: list[OpenApiReference]
    schema_diffs: list[SchemaReference]


@dataclass(frozen=True)
class SourceFixture:
    project_id: str
    headers: dict[str, str]
    plan_id: str
    policy_id: str
    baseline_id: str
    current_id: str
    foreign_contract_id: str
    graphql_id: str
    grpc_id: str
    foreign_schema_id: str


@pytest.fixture
async def source_fixture(regression_context: RegressionContext) -> SourceFixture:
    context = regression_context
    headers = await _login_headers(context.client)
    project_id, environment_id, workflow_id = await _create_workflow(context.client, headers)
    foreign = await context.client.post(
        "/api/v1/projects", headers=headers, json={"name": "Foreign source fixture"}
    )
    assert foreign.status_code == 201, foreign.text
    foreign_id = foreign.json()["id"]
    plan = await context.client.post(
        f"/api/v1/projects/{project_id}/test-plans",
        headers=headers,
        json={
            "name": "Source validation plan",
            "items": [
                {
                    "target_type": "workflow",
                    "target_id": workflow_id,
                    "target_version": 1,
                    "environment_id": environment_id,
                }
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    policy = await context.client.post(
        f"/api/v1/projects/{project_id}/release-policies",
        headers=headers,
        json={
            "name": "Source validation policy",
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": True,
            "min_impact_coverage_percent": 0,
            "require_release_risk": False,
        },
    )
    assert policy.status_code == 201, policy.text
    baseline_id = await _create_contract_run(
        context.client, headers, project_id, _orders_openapi(maximum=100), "baseline.json"
    )
    current_id = await _create_contract_run(
        context.client, headers, project_id, _orders_openapi(maximum=999), "current.json"
    )
    foreign_contract_id = await _create_contract_run(
        context.client, headers, foreign_id, _orders_openapi(maximum=999), "foreign.json"
    )
    schemas: list[SchemaArtifact] = []
    graphql = b"type Query { value: String }"
    grpc = _compiled_proto("string")
    async with context.sessions() as session:
        user_id = await session.scalar(select(User.id).where(User.is_system_admin.is_(True)))
        assert user_id is not None
        for owner, protocol, content in [
            (project_id, "graphql", graphql),
            (project_id, "grpc", grpc),
            (foreign_id, "graphql", graphql),
        ]:
            schema = SchemaArtifact(
                project_id=UUID(owner),
                protocol=protocol,
                name=f"Source fixture {protocol}",
                version=1,
                source_format="graphql_sdl" if protocol == "graphql" else "proto_source",
                content_sha256=sha256(content).hexdigest(),
                canonical_content=content,
                source_content=content,
                summary={},
                created_by_id=user_id,
            )
            session.add(schema)
            schemas.append(schema)
        await session.commit()
    return SourceFixture(
        project_id,
        headers,
        plan.json()["id"],
        policy.json()["id"],
        baseline_id,
        current_id,
        foreign_contract_id,
        str(schemas[0].id),
        str(schemas[1].id),
        str(schemas[2].id),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["impact/runs", "change-regressions"])
@pytest.mark.parametrize("kind", ["openapi", "schema"])
async def test_sources_reject_identical_versions_even_when_git_has_changes(
    regression_context: RegressionContext,
    source_fixture: SourceFixture,
    endpoint: str,
    kind: str,
) -> None:
    fixture = source_fixture
    payload = _payload(fixture)
    if endpoint == "impact/runs":
        payload = {
            "title": payload["title"],
            "source_ref": payload["source_ref"],
            "git_diff": payload["git_diff"],
        }
    if kind == "openapi":
        payload["openapi_diffs"] = [
            {"baseline_run_id": fixture.baseline_id, "current_run_id": fixture.baseline_id}
        ]
    else:
        payload["schema_diffs"] = [
            {"baseline_artifact_id": fixture.graphql_id, "current_artifact_id": fixture.graphql_id}
        ]
    response = await regression_context.client.post(
        f"/api/v1/projects/{fixture.project_id}/{endpoint}",
        headers=fixture.headers,
        json=payload,
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["trace_id"]
    assert regression_context.queue.test_plan_run_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["foreign_openapi", "foreign_schema", "different_protocol", "none"]
)
async def test_regression_sources_enforce_project_protocol_and_presence(
    regression_context: RegressionContext,
    source_fixture: SourceFixture,
    kind: str,
) -> None:
    fixture = source_fixture
    payload = _payload(fixture)
    if kind == "foreign_openapi":
        payload["openapi_diffs"] = [
            {"baseline_run_id": fixture.foreign_contract_id, "current_run_id": fixture.current_id}
        ]
    elif kind in {"foreign_schema", "different_protocol"}:
        current = fixture.foreign_schema_id if kind == "foreign_schema" else fixture.grpc_id
        payload["schema_diffs"] = [
            {"baseline_artifact_id": fixture.graphql_id, "current_artifact_id": current}
        ]
    else:
        payload.pop("git_diff")
    response = await regression_context.client.post(
        f"/api/v1/projects/{fixture.project_id}/change-regressions",
        headers=fixture.headers,
        json=payload,
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["trace_id"]
    assert regression_context.queue.test_plan_run_ids == []


@pytest.mark.asyncio
async def test_openapi_only_chain_retains_its_original_source_after_new_versions(
    regression_context: RegressionContext,
    source_fixture: SourceFixture,
) -> None:
    fixture = source_fixture
    payload = _payload(fixture)
    payload.pop("git_diff")
    payload["openapi_diffs"] = [
        {"baseline_run_id": fixture.baseline_id, "current_run_id": fixture.current_id}
    ]
    root = f"/api/v1/projects/{fixture.project_id}"
    created = await regression_context.client.post(
        root + "/change-regressions",
        headers=fixture.headers,
        json=payload,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    original_impact = await regression_context.client.get(
        root + "/impact/runs/" + body["impact_run_id"],
        headers=fixture.headers,
    )
    assert original_impact.status_code == 200
    original = original_impact.json()
    assert original["source_summary"]["openapi"][0]["current_run_id"] == fixture.current_id
    await _create_contract_run(
        regression_context.client,
        fixture.headers,
        fixture.project_id,
        _orders_openapi(maximum=2000),
        "newer.json",
    )
    restored = await regression_context.client.get(
        root + "/change-regressions/" + body["id"],
        headers=fixture.headers,
    )
    frozen = await regression_context.client.get(
        root + "/impact/runs/" + body["impact_run_id"],
        headers=fixture.headers,
    )
    assert restored.status_code == frozen.status_code == 200
    assert restored.json()["source_fingerprint"] == body["source_fingerprint"]
    assert frozen.json()["source_fingerprint"] == original["source_fingerprint"]
    assert frozen.json()["source_summary"] == original["source_summary"]
    assert regression_context.queue.test_plan_run_ids == []


def _payload(fixture: SourceFixture) -> SourceRequest:
    return {
        "title": "Source-only regression fixture",
        "source_ref": "audit://source-validation",
        "candidate_ref": "source:current",
        "git_diff": _git_diff("backend/changed.py"),
        "test_plan_id": fixture.plan_id,
        "release_policy_id": fixture.policy_id,
        "generate_missing_tests": False,
    }
