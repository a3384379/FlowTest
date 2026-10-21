from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import select
from test_ai_assistant import (
    ADMIN_EMAIL,
    AIEnvironment,
    _create_project,
    _create_user,
    _login_headers,
    _login_user_headers,
    _workflow_definition,
)
from test_ai_assistant import ai_environment as ai_environment

from app.core.config import settings
from app.models.access import User
from app.models.protocols import SchemaArtifact
from app.models.workflows import WorkflowExecution


@dataclass(frozen=True)
class PublicSources:
    project_id: str
    foreign_project_id: str
    headers: dict[str, str]
    api_id: str
    schema_id: str
    execution_id: str

    def source_id(self, kind: str) -> str:
        if kind == "api":
            return self.api_id
        if kind == "schema":
            return self.schema_id
        return self.execution_id


@pytest.fixture
async def public_sources(ai_environment: AIEnvironment) -> PublicSources:
    context = ai_environment
    headers = await _login_headers(context.client)
    project_id = await _create_project(context.client, headers)
    foreign_id = await _create_project(context.client, headers, name="Foreign source owner")
    api = await context.client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "Public material API",
            "request": {
                "method": "GET",
                "path": "/public-v1",
                "headers": {"X-Private-Fixture": "private-header-not-shared"},
                "body_kind": "json",
                "body": {"fixture": "private-body-not-shared"},
                "auth": {"kind": "none", "values": {}},
            },
        },
    )
    assert api.status_code == 201, api.text
    environment = await context.client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "Source fixture", "base_url": "https://example.test"},
    )
    assert environment.status_code == 201
    workflow = await context.client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={"name": "Source fixture", "definition": _workflow_definition()},
    )
    assert workflow.status_code == 201
    version = await context.client.post(
        f"/api/v1/projects/{project_id}/workflows/{workflow.json()['id']}/versions", headers=headers
    )
    assert version.status_code == 200
    async with context.sessions() as session:
        actor = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert actor is not None
        content = b"type Query { fixture: String }"
        schema = SchemaArtifact(
            project_id=UUID(project_id),
            protocol="graphql",
            name="Public schema",
            version=1,
            source_format="graphql_sdl",
            content_sha256=sha256(content).hexdigest(),
            canonical_content=content,
            source_content=content,
            summary={"type_count": 1},
            created_by_id=actor.id,
        )
        execution = WorkflowExecution(
            project_id=UUID(project_id),
            workflow_id=UUID(workflow.json()["id"]),
            workflow_version_id=UUID(version.json()["id"]),
            environment_id=UUID(environment.json()["id"]),
            triggered_by_id=actor.id,
            status="failed",
            error_code="FIXTURE_FAILURE",
            error_message="公开诊断原文",
            snapshot={"private": "private-snapshot-not-shared"},
            context={"private": "private-context-not-shared"},
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add_all([schema, execution])
        await session.commit()
    return PublicSources(
        project_id,
        foreign_id,
        headers,
        api.json()["definition"]["id"],
        str(schema.id),
        str(execution.id),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["api", "schema", "execution"])
async def test_public_sources_only_return_declared_material_without_ai_dispatch(
    ai_environment: AIEnvironment,
    public_sources: PublicSources,
    kind: str,
) -> None:
    source = public_sources
    response = await ai_environment.client.get(
        f"/api/v1/ai/projects/{source.project_id}/sources/{kind}/{source.source_id(kind)}",
        headers=source.headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project_id"] == source.project_id
    assert payload["metadata"]["source_id"] == source.source_id(kind)
    assert "private-header-not-shared" not in response.text
    assert "private-body-not-shared" not in response.text
    assert "private-snapshot-not-shared" not in response.text
    assert "private-context-not-shared" not in response.text
    assert ai_environment.queue.job_ids == []
    if kind == "api":
        assert payload["metadata"]["version"] == 1
        assert payload["metadata"]["path"] == "/public-v1"
        assert payload["schema_document"]["path"] == "/public-v1"
    elif kind == "schema":
        assert payload["schema_document"]["schema_text"] == "type Query { fixture: String }"
    else:
        assert payload["metadata"]["error_code"] == "FIXTURE_FAILURE"
        assert payload["metadata"]["error_message"] == "公开诊断原文"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["api", "schema", "execution"])
async def test_public_source_scope_does_not_follow_foreign_ids(
    ai_environment: AIEnvironment,
    public_sources: PublicSources,
    kind: str,
) -> None:
    source = public_sources
    response = await ai_environment.client.get(
        f"/api/v1/ai/projects/{source.foreign_project_id}/sources/{kind}/{source.source_id(kind)}",
        headers=source.headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_public_source_catalog_is_paginated_literal_and_available_without_generation(
    ai_environment: AIEnvironment,
    public_sources: PublicSources,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = public_sources
    monkeypatch.setattr(settings, "feature_ai_enabled", False)
    for kind in ("api", "schema", "execution"):
        route = f"/api/v1/ai/projects/{source.project_id}/sources"
        response = await ai_environment.client.get(
            route, headers=source.headers, params={"kind": kind, "page_size": 1}
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["id"] == source.source_id(kind)
        empty = await ai_environment.client.get(
            route, headers=source.headers, params={"kind": kind, "page": 2, "page_size": 1}
        )
        assert empty.json()["items"] == []
        literal = await ai_environment.client.get(
            route, headers=source.headers, params={"kind": kind, "search": "%_"}
        )
        assert literal.json()["total"] == 0


@pytest.mark.asyncio
async def test_public_source_rejects_oversized_material_and_unknown_api_version(
    ai_environment: AIEnvironment,
    public_sources: PublicSources,
) -> None:
    source = public_sources
    async with ai_environment.sessions() as session:
        schema = await session.get(SchemaArtifact, UUID(source.schema_id))
        assert schema is not None
        schema.source_content = b"x" * (1024 * 1024)
        await session.commit()
    root = f"/api/v1/ai/projects/{source.project_id}/sources"
    oversized = await ai_environment.client.get(
        f"{root}/schema/{source.schema_id}", headers=source.headers
    )
    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["error"]["trace_id"]
    missing = await ai_environment.client.get(
        f"{root}/api/{source.api_id}", headers=source.headers, params={"version": 999}
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_public_material_read_is_allowed_to_viewer_and_rejects_nonmember(
    ai_environment: AIEnvironment,
    public_sources: PublicSources,
) -> None:
    source = public_sources
    client = ai_environment.client
    actor = await _create_user(client, source.headers, "source-viewer@example.com")
    member = await client.put(
        f"/api/v1/projects/{source.project_id}/members/{actor['id']}",
        headers=source.headers,
        json={"user_id": actor["id"], "role": "viewer"},
    )
    assert member.status_code == 200
    headers = await _login_user_headers(
        client, "source-viewer@example.com", "initial-password-123!"
    )
    root = f"/api/v1/ai/projects/{source.project_id}/sources"
    assert (await client.get(root, headers=headers, params={"kind": "api"})).status_code == 200
    assert (await client.get(f"{root}/api/{source.api_id}", headers=headers)).status_code == 200
    denied = await client.get(
        f"/api/v1/ai/projects/{source.foreign_project_id}/sources",
        headers=headers,
        params={"kind": "api"},
    )
    assert denied.status_code in (403, 404)
    assert denied.json()["error"]["trace_id"]
    assert ai_environment.queue.job_ids == []


@pytest.mark.asyncio
async def test_fixed_public_api_material_does_not_follow_new_api_revision(
    ai_environment: AIEnvironment, public_sources: PublicSources
) -> None:
    source = public_sources
    client = ai_environment.client
    route = f"/api/v1/ai/projects/{source.project_id}/sources/api/{source.api_id}"
    before = await client.get(route, headers=source.headers, params={"version": 1})
    assert before.status_code == 200
    newer = await client.post(
        f"/api/v1/projects/{source.project_id}/apis/{source.api_id}/versions",
        headers=source.headers,
        json={"method": "GET", "path": "/public-v2", "body_kind": "none"},
    )
    assert newer.status_code == 201, newer.text
    fixed = await client.get(route, headers=source.headers, params={"version": 1})
    current = await client.get(route, headers=source.headers)
    assert fixed.json() == before.json()
    assert current.json()["metadata"]["version"] == 2
    assert current.json()["metadata"]["path"] == "/public-v2"
    assert ai_environment.queue.job_ids == []


@pytest.mark.asyncio
async def test_public_schema_version_must_match_the_exact_artifact(
    ai_environment: AIEnvironment, public_sources: PublicSources
) -> None:
    source = public_sources
    route = f"/api/v1/ai/projects/{source.project_id}/sources/schema/{source.schema_id}"
    found = await ai_environment.client.get(route, headers=source.headers, params={"version": 1})
    missing = await ai_environment.client.get(route, headers=source.headers, params={"version": 2})
    assert found.status_code == 200
    assert missing.status_code == 404
    assert missing.json()["error"]["trace_id"]
