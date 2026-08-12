import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.domain import impact as impact_domain
from app.domain.impact import (
    AssetMapping,
    ChangeSeverity,
    ImpactInputError,
    SourceKind,
    TargetType,
    build_impact_evidence,
    diff_graphql,
    diff_grpc,
    diff_openapi,
    parse_git_diff,
    validate_selector,
)
from app.domain.protocols import ProtoSourceFile, compile_proto_sources, validate_graphql_sdl
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.protocols import SchemaArtifact
from app.models.test_assets import TestCase as CaseModel
from app.models.workflows import Workflow

ADMIN_EMAIL = "impact-admin@example.com"
ADMIN_PASSWORD = "impact-password-123!"


@dataclass(slots=True)
class ImpactContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]


@pytest.fixture
async def impact_context(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[ImpactContext]:
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Impact administrator",
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

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield ImpactContext(client, sessions)
    app.dependency_overrides.clear()
    await engine.dispose()


def test_bounded_multi_source_diff_and_explainable_selection() -> None:
    git_changes = parse_git_diff(
        "diff --git a/backend/orders.py b/backend/orders.py\n"
        "--- a/backend/orders.py\n"
        "+++ b/backend/orders.py\n"
        "@@ -1 +1 @@\n"
        "-OLD = True\n"
        "+NEW = True\n"
    )
    assert git_changes[0].source_key == "backend/orders.py"
    assert git_changes[0].detail == "新增 1 行 / 删除 1 行"

    graphql_changes = diff_graphql(
        b"type Query { order(id: ID!): String health: String }",
        b"type Query { order(id: Int!): String }",
    )
    assert {item.source_key for item in graphql_changes} == {"Query.health", "Query.order"}
    assert all(item.severity == ChangeSeverity.BREAKING for item in graphql_changes)

    grpc_changes = diff_grpc(
        _compiled_proto("string"),
        _compiled_proto("int64"),
    )
    assert any(item.source_key == "sample.Request.value" for item in grpc_changes)

    mappings = (
        AssetMapping(
            "mapping-1",
            SourceKind.GIT,
            "backend/*",
            TargetType.WORKFLOW,
            "workflow-1",
            "订单流程",
            2,
        ),
    )
    evidence = build_impact_evidence(git_changes, mappings)
    assert evidence.summary["coverage_percent"] == 100.0
    assert evidence.selected_assets[0]["reasons"] == ["backend/* 命中 backend/orders.py"]
    assert evidence.matrix[0]["workflow_count"] == 1
    assert evidence.gaps == ()


def test_git_diff_and_mapping_guards() -> None:
    invalid_values = (
        "not a diff",
        "diff --git a/../secret b/../secret\n",
        "diff --git a/file name b/file name\n",
        "diff --git a//root b//root\n",
    )
    for content in invalid_values:
        with pytest.raises(ImpactInputError):
            parse_git_diff(content)
    with pytest.raises(ImpactInputError, match="2 MB"):
        parse_git_diff("x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ImpactInputError):
        validate_selector("backend/**/orders.py")
    assert validate_selector("backend/*") == "backend/*"


def test_change_variants_and_bounded_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    changes = parse_git_diff(
        "diff --git a/new.bin b/new.bin\n"
        "--- /dev/null\n"
        "+++ b/new.bin\n"
        "Binary files /dev/null and b/new.bin differ\n"
        "diff --git a/old.py b/old.py\n"
        "--- a/old.py\n"
        "+++ /dev/null\n"
        "-old\n"
    )
    assert [item.change_type.value for item in changes] == ["added", "deleted"]
    assert changes[0].detail == "二进制文件变化"

    with pytest.raises(ImpactInputError, match="没有文件变更"):
        parse_git_diff("")
    monkeypatch.setattr(impact_domain, "MAX_GIT_DIFF_LINES", 1)
    with pytest.raises(ImpactInputError, match="行数"):
        parse_git_diff("first\nsecond")
    monkeypatch.setattr(impact_domain, "MAX_GIT_DIFF_LINES", 100_000)
    monkeypatch.setattr(impact_domain, "MAX_GIT_DIFF_FILES", 1)
    with pytest.raises(ImpactInputError, match="文件数"):
        parse_git_diff("diff --git a/one.py b/one.py\ndiff --git a/two.py b/two.py\n")

    for selector in ("", "bad\nselector", "x" * 513):
        with pytest.raises(ImpactInputError, match="选择器无效"):
            validate_selector(selector)


def test_schema_diff_add_delete_and_invalid_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    added_openapi = diff_openapi(
        _openapi_dict(paths=_simple_openapi_path()),
        _openapi_dict(paths={**_simple_openapi_path(), **_second_openapi_path()}),
    )
    assert added_openapi[0].change_type.value == "added"
    removed_openapi = diff_openapi(
        _openapi_dict(paths={**_simple_openapi_path(), **_second_openapi_path()}),
        _openapi_dict(paths=_simple_openapi_path()),
    )
    assert removed_openapi[0].change_type.value == "deleted"

    added_graphql = diff_graphql(
        b"type Query { health: String }", b"type Query { health: String new: Int }"
    )
    assert any(item.change_type.value == "added" for item in added_graphql)
    assert diff_graphql(b"type Query { health: String }", b"type Query { health: String }") == ()
    with pytest.raises(ImpactInputError, match="GraphQL"):
        diff_graphql(b"\xff", b"type Query { health: String }")

    baseline = _compiled_proto("string")
    current = _compiled_proto_with_extra_field()
    grpc_changes = diff_grpc(baseline, current)
    assert any(item.change_type.value == "added" for item in grpc_changes)
    assert any(item.change_type.value == "deleted" for item in diff_grpc(current, baseline))
    with pytest.raises(ImpactInputError, match="不能为空"):
        diff_grpc(b"", baseline)

    git_change = parse_git_diff("diff --git a/a.py b/a.py\n+a\n")
    monkeypatch.setattr(impact_domain, "MAX_CHANGE_ITEMS", 0)
    with pytest.raises(ImpactInputError, match="变更项"):
        build_impact_evidence(git_change, ())
    with pytest.raises(ImpactInputError, match="Schema Diff"):
        diff_graphql(b"type Query { health: String }", b"type Query { health: String new: Int }")
    monkeypatch.setattr(impact_domain, "MAX_CHANGE_ITEMS", 5_000)
    monkeypatch.setattr(impact_domain, "MAX_MAPPINGS", 0)
    mapping = AssetMapping(
        "mapping",
        SourceKind.GIT,
        "a.py",
        TargetType.TEST_CASE,
        "case",
        "A case",
        1,
    )
    with pytest.raises(ImpactInputError, match="资产映射"):
        build_impact_evidence(git_change, (mapping,))


@pytest.mark.asyncio
async def test_impact_api_persists_multi_source_selection_and_coverage(
    impact_context: ImpactContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = impact_context.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers, "Impact project")
    other_project_id = await _create_project(client, headers, "Other impact project")
    workflow_id, case_id, schema_ids = await _seed_assets(impact_context.sessions, project_id)
    other_workflow_id, _, _ = await _seed_assets(
        impact_context.sessions, other_project_id, suffix="other"
    )
    baseline_id = await _create_contract_run(
        client, headers, project_id, _openapi_document(required=False), "orders-v1.json"
    )
    current_id = await _create_contract_run(
        client, headers, project_id, _openapi_document(required=True), "orders-v2.json"
    )
    root = f"/api/v1/projects/{project_id}/impact"

    catalog = await client.get(f"{root}/catalog", headers=headers)
    assert catalog.status_code == 200, catalog.text
    assert {item["target_type"] for item in catalog.json()["targets"]} >= {
        "test_case",
        "workflow",
        "openapi_contract",
    }
    assert [item["protocol"] for item in catalog.json()["schemas"]] == [
        "graphql",
        "graphql",
    ]

    mapping_inputs = [
        ("git", "backend/orders.py", "workflow", workflow_id),
        ("openapi", "POST /orders", "test_case", case_id),
        ("openapi", "POST /orders", "openapi_contract", current_id),
        ("graphql", "Query.order", "workflow", workflow_id),
    ]
    for source_kind, selector, target_type, target_id in mapping_inputs:
        response = await client.post(
            f"{root}/mappings",
            headers=headers,
            json={
                "source_kind": source_kind,
                "source_selector": selector,
                "target_type": target_type,
                "target_id": target_id,
            },
        )
        assert response.status_code == 201, response.text

    duplicate = await client.post(
        f"{root}/mappings",
        headers=headers,
        json={
            "source_kind": "git",
            "source_selector": "backend/orders.py",
            "target_type": "workflow",
            "target_id": workflow_id,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "IMPACT_MAPPING_EXISTS"
    cross_project = await client.post(
        f"{root}/mappings",
        headers=headers,
        json={
            "source_kind": "git",
            "source_selector": "backend/other.py",
            "target_type": "workflow",
            "target_id": other_workflow_id,
        },
    )
    assert cross_project.status_code == 422
    assert cross_project.json()["error"]["code"] == "IMPACT_TARGET_NOT_FOUND"

    run = await client.post(
        f"{root}/runs",
        headers=headers,
        json={
            "title": "订单接口与 GraphQL 影响分析",
            "source_ref": "feature/orders-required",
            "git_diff": (
                "diff --git a/backend/orders.py b/backend/orders.py\n"
                "--- a/backend/orders.py\n+++ b/backend/orders.py\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            ),
            "openapi_diffs": [{"baseline_run_id": baseline_id, "current_run_id": current_id}],
            "schema_diffs": [
                {
                    "baseline_artifact_id": schema_ids[0],
                    "current_artifact_id": schema_ids[1],
                }
            ],
        },
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["change_count"] == 3
    assert body["summary"] == {
        "change_count": 3,
        "breaking_change_count": 2,
        "selected_asset_count": 3,
        "covered_change_count": 3,
        "gap_count": 0,
        "coverage_percent": 100.0,
    }
    assert {item["asset_type"] for item in body["selection"]["selected_assets"]} == {
        "case",
        "workflow",
        "contract",
    }
    assert body["coverage"]["coverage_percent"] == 100.0
    assert body["coverage"]["gaps"] == []
    assert len(body["graph"]["edges"]) == 4

    listed = await client.get(f"{root}/runs", headers=headers)
    detail = await client.get(f"{root}/runs/{body['id']}", headers=headers)
    mappings = await client.get(f"{root}/mappings?page_size=2", headers=headers)
    assert listed.json()["total"] == 1
    assert detail.json() == body
    assert mappings.json()["total"] == 4
    assert len(mappings.json()["items"]) == 2

    deleted = await client.delete(
        f"{root}/mappings/{mappings.json()['items'][0]['id']}", headers=headers
    )
    assert deleted.status_code == 204
    invalid_diff = await client.post(
        f"{root}/runs",
        headers=headers,
        json={"title": "无效 Diff", "git_diff": "not a diff"},
    )
    assert invalid_diff.status_code == 422
    assert invalid_diff.json()["error"]["code"] == "IMPACT_INPUT_INVALID"

    monkeypatch.setattr(settings, "feature_impact_engine_enabled", False)
    disabled = await client.get(f"{root}/runs", headers=headers)
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "IMPACT_ENGINE_DISABLED"


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "description": "S28"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _seed_assets(
    sessions: async_sessionmaker[AsyncSession], project_id: str, *, suffix: str = "primary"
) -> tuple[str, str, tuple[str, str]]:
    baseline = validate_graphql_sdl("type Query { order(id: ID!): String }")
    current = validate_graphql_sdl("type Query { order(id: Int!): String }")
    async with sessions() as session:
        user_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
        assert user_id is not None
        workflow = Workflow(
            project_id=UUID(project_id),
            name=f"订单流程 {suffix}",
            description="",
            folder_id=None,
            draft_definition={"nodes": [], "edges": []},
            draft_revision=1,
            current_version=None,
            created_by_id=user_id,
        )
        session.add(workflow)
        await session.flush()
        case = CaseModel(
            project_id=UUID(project_id),
            folder_id=None,
            name=f"订单用例 {suffix}",
            description="",
            tags=[],
            is_template=False,
            draft_definition={
                "workflow_id": str(workflow.id),
                "workflow_version": None,
                "environment_id": "00000000-0000-0000-0000-000000000001",
                "runtime_variables": {},
                "runtime_headers": {},
            },
            current_version=None,
            created_by_id=user_id,
        )
        schemas = []
        for version, validated in enumerate((baseline, current), start=1):
            schema = SchemaArtifact(
                project_id=UUID(project_id),
                protocol="graphql",
                name=f"orders-{suffix}",
                description="",
                version=version,
                source_format=validated.source_format.value,
                content_sha256=validated.sha256,
                canonical_content=validated.canonical_content,
                source_content=validated.source_content,
                summary=validated.summary,
                created_by_id=user_id,
            )
            session.add(schema)
            schemas.append(schema)
        session.add(case)
        await session.commit()
        return str(workflow.id), str(case.id), (str(schemas[0].id), str(schemas[1].id))


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


def _openapi_document(*, required: bool) -> bytes:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"orderId": {"type": "string"}},
    }
    if required:
        schema["required"] = ["orderId"]
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Orders", "version": "1.0.0"},
            "paths": {
                "/orders": {
                    "post": {
                        "operationId": "createOrder",
                        "requestBody": {
                            "required": required,
                            "content": {"application/json": {"schema": schema}},
                        },
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"ok": {"type": "boolean"}},
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }
    ).encode()


def _openapi_dict(*, paths: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Impact fixture", "version": "1.0.0"},
        "paths": paths,
    }


def _simple_openapi_path() -> dict[str, JsonValue]:
    return {
        "/health": {
            "get": {
                "operationId": "health",
                "responses": {"200": {"description": "ok"}},
            }
        }
    }


def _second_openapi_path() -> dict[str, JsonValue]:
    return {
        "/ready": {
            "get": {
                "operationId": "ready",
                "responses": {"200": {"description": "ready"}},
            }
        }
    }


def _compiled_proto(field_type: str) -> bytes:
    return compile_proto_sources(
        (
            ProtoSourceFile(
                name="sample.proto",
                content=(
                    'syntax = "proto3"; package sample; '
                    f"message Request {{ {field_type} value = 1; }} "
                    "message Reply { bool ok = 1; } "
                    "service Orders { rpc Create(Request) returns (Reply); }"
                ),
            ),
        ),
        entrypoint="sample.proto",
    ).canonical_content


def _compiled_proto_with_extra_field() -> bytes:
    return compile_proto_sources(
        (
            ProtoSourceFile(
                name="sample.proto",
                content=(
                    'syntax = "proto3"; package sample; '
                    "message Request { string value = 1; int64 count = 2; } "
                    "message Reply { bool ok = 1; } "
                    "service Orders { rpc Create(Request) returns (Reply); }"
                ),
            ),
        ),
        entrypoint="sample.proto",
    ).canonical_content
