from collections.abc import AsyncIterator
from copy import deepcopy
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.flow_spec import (
    assess_flow_spec_compatibility,
    diff_flow_specs,
    flow_spec_fingerprint,
    normalize_flow_spec,
    validate_flow_spec,
)
from app.main import app
from app.models import Base
from app.models.access import User

ADMIN_EMAIL = "flowspec-admin@example.com"
ADMIN_PASSWORD = "flowspec-password-123!"


@pytest.fixture
async def flow_spec_client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="FlowSpec administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


def test_flowspec_normalization_is_portable_and_secret_safe() -> None:
    raw = {
        "schema_version": "flowtest-flow-spec-v1",
        "project_id": str(uuid4()),
        "name": "  portable flow  ",
        "source_evidence": ["source://b", "source://a", "source://a"],
        "nodes": [
            {"id": "end", "kind": "end", "name": "End"},
            {"id": "start", "kind": "start", "name": "Start"},
        ],
        "edges": [{"id": "edge-1", "source": "start", "target": "end"}],
    }
    spec = normalize_flow_spec(raw)
    assert [node.id for node in spec.nodes] == ["end", "start"]
    assert spec.source_evidence == ["source://a", "source://b"]
    assert flow_spec_fingerprint(spec) == flow_spec_fingerprint(
        spec.model_copy(update={"project_id": uuid4(), "source_evidence": ["other://evidence"]})
    )

    unsafe = spec.model_copy(
        update={
            "nodes": [
                spec.nodes[0].model_copy(update={"config": {"authorization": "Bearer raw"}}),
                spec.nodes[1],
            ]
        }
    )
    validation = validate_flow_spec(unsafe)
    assert validation.valid is False
    assert any(item.code == "SECRET_LITERAL_FORBIDDEN" for item in validation.issues)


def test_flowspec_diff_and_compatibility_report_reviewable_changes() -> None:
    spec = normalize_flow_spec(
        {
            "schema_version": "flowtest-flow-spec-v1",
            "project_id": str(uuid4()),
            "confidence": {"overall": 0.5, "unresolved": ["response schema"]},
            "nodes": [
                {"id": "start", "kind": "start", "name": "Start"},
                {
                    "id": "request",
                    "kind": "http",
                    "name": "Request",
                    "config": {"api_definition_id": str(uuid4())},
                },
                {"id": "end", "kind": "end", "name": "End"},
            ],
            "edges": [
                {"id": "start-request", "source": "start", "target": "request"},
                {"id": "request-end", "source": "request", "target": "end"},
            ],
        }
    )
    changed = spec.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"name": "Request v2"}) if node.id == "request" else node
                for node in spec.nodes
            ]
        }
    )

    changes = diff_flow_specs(spec, changed)
    assert any(item.path == "$.nodes[id=request].name" for item in changes)

    compatibility = assess_flow_spec_compatibility(spec)
    warning_codes = {item.code for item in compatibility.warnings}
    assert compatibility.compatible is True
    assert compatibility.requires_review is True
    assert {
        "INSTANCE_RESOURCE_REFERENCE",
        "SOURCE_PROJECT_ID_IGNORED",
        "LOW_CONFIDENCE",
        "UNRESOLVED_EVIDENCE",
        "REVIEW_REQUIRED",
    } <= warning_codes


@pytest.mark.asyncio
async def test_flowspec_export_review_apply_and_roundtrip(flow_spec_client: AsyncClient) -> None:
    token_response = await flow_spec_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert token_response.status_code == 200, token_response.text
    headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}

    project_response = await flow_spec_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "FlowSpec project"},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    definition = {
        "schema_version": "1.0",
        "variables": {},
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "config": {},
            },
            {
                "id": "end",
                "type": "end",
                "name": "End",
                "position": {"x": 200, "y": 0},
                "config": {},
            },
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        "settings": {"fail_fast": True, "concurrency": 20, "default_timeout_seconds": 30},
    }
    created = await flow_spec_client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "原始流程", "description": "portable", "definition": definition},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]

    exported = await flow_spec_client.get(
        f"/api/v1/projects/{project_id}/flow-specs/workflows/{workflow_id}/export",
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    exported_body = exported.json()
    assert exported_body["spec"]["schema_version"] == "flowtest-flow-spec-v1"
    assert exported_body["validation"]["valid"] is True
    original_fingerprint = exported_body["fingerprint"]

    imported_spec = deepcopy(exported_body["spec"])
    imported_spec["project_id"] = str(uuid4())
    next(node for node in imported_spec["nodes"] if node["id"] == "end")["name"] = "End (imported)"
    diff = await flow_spec_client.post(
        f"/api/v1/projects/{project_id}/flow-specs/diff",
        headers=headers,
        json={"before": exported_body["spec"], "after": imported_spec},
    )
    assert diff.status_code == 200, diff.text
    assert diff.json()["before_fingerprint"] == original_fingerprint
    assert any(item["path"].endswith(".name") for item in diff.json()["changes"])
    draft = await flow_spec_client.post(
        f"/api/v1/projects/{project_id}/flow-specs/imports",
        headers=headers,
        json={
            "spec": imported_spec,
            "workflow_id": workflow_id,
            "source_ref": "instance://source/commit/flow.json",
        },
    )
    assert draft.status_code == 201, draft.text
    draft_body = draft.json()
    assert draft_body["status"] == "draft"
    assert draft_body["review_status"] == "pending"
    assert draft_body["source_type"] == "flow_spec"
    assert draft_body["source_fingerprint"] != original_fingerprint

    before_apply = await flow_spec_client.get(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}", headers=headers
    )
    assert before_apply.json()["draft_revision"] == 1
    blocked = await flow_spec_client.post(
        f"/api/v1/projects/{project_id}/flow-specs/change-sets/{draft_body['id']}/apply",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "FLOWSPEC_REVIEW_REQUIRED"

    reviewed = await flow_spec_client.post(
        f"/api/v1/projects/{project_id}/flow-specs/change-sets/{draft_body['id']}/review",
        headers=headers,
        json={"accept": True, "note": "人工确认跨实例导入"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "accepted"
    applied = await flow_spec_client.post(
        f"/api/v1/projects/{project_id}/flow-specs/change-sets/{draft_body['id']}/apply",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["workflow_id"] == workflow_id
    assert applied.json()["draft_revision"] == 2

    after_apply = await flow_spec_client.get(
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}", headers=headers
    )
    assert after_apply.json()["draft_definition"]["nodes"][0]["name"] == "End (imported)"

    roundtrip = await flow_spec_client.get(
        f"/api/v1/projects/{project_id}/flow-specs/workflows/{workflow_id}/export",
        headers=headers,
    )
    assert roundtrip.status_code == 200
    assert roundtrip.json()["fingerprint"] == draft_body["source_fingerprint"]
