from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_environment_lab import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    USER_EMAIL,
    USER_PASSWORD,
    EnvironmentTestContext,
    _create_project,
    _create_template,
    _login_headers,
    _queue_instance_id,
    _template_payload,
)
from test_environment_lab import environment_context as environment_context

from app.domain.access import ProjectRole
from app.models.access import AuditLog, Project, ProjectMember, User
from app.models.environment_lab import EnvironmentTemplateVersion
from app.models.organizations import OrganizationMember


@pytest.mark.asyncio
async def test_instance_reader_recovers_disabled_original_without_runtime_side_effects(
    environment_context: EnvironmentTestContext,
) -> None:
    context = environment_context
    client = context.client
    admin = await _login_headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    viewer = await _login_headers(client, USER_EMAIL, USER_PASSWORD)
    project_id = await _create_project(client, admin)
    original = await _create_template(client, admin)
    instance_id = await _queue_instance_id(
        context, admin, project_id, original["id"], "old-template-read"
    )
    changed = deepcopy(original["manifest"])
    assert isinstance(changed, dict)
    changed["default_ttl_seconds"] = 900
    newer = await client.post(
        f"/api/v1/environment-templates/{original['template_id']}/versions",
        headers=admin,
        json={"manifest": changed},
    )
    assert newer.status_code == 201, newer.text
    disabled = await client.post(
        f"/api/v1/environment-templates/{original['template_id']}/disable",
        headers=admin,
    )
    assert disabled.status_code == 204
    async with context.sessions() as session:
        project = await session.get(Project, UUID(project_id))
        user = await session.scalar(select(User).where(User.email == USER_EMAIL))
        assert project is not None and user is not None
        session.add(
            OrganizationMember(
                organization_id=project.organization_id, user_id=user.id, role="member"
            )
        )
        session.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.VIEWER))
        await session.commit()
        audits_before = await session.scalar(select(func.count()).select_from(AuditLog))
    public_path = f"/api/v1/environment-templates/versions/{original['id']}"
    hidden = await client.get(public_path, headers=viewer)
    assert hidden.status_code == 404 and hidden.json()["error"]["trace_id"]
    catalog = await client.get("/api/v1/environment-templates", headers=viewer)
    assert catalog.status_code == 200 and catalog.json()["total"] == 0
    read = await client.get(
        f"/api/v1/projects/{project_id}/environment-instances/{instance_id}/template-version",
        headers=viewer,
    )
    assert read.status_code == 200, read.text
    assert read.json()["id"] == original["id"]
    assert read.json()["version"] == 1 and read.json()["status"] == "disabled"
    assert read.json()["manifest"] == original["manifest"]
    assert read.json()["manifest_sha256"] == original["manifest_sha256"]
    admin_read = await client.get(public_path, headers=admin)
    assert admin_read.status_code == 200 and admin_read.json()["manifest"] == original["manifest"]
    async with context.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == audits_before
    assert context.queue.provision_ids == [instance_id]


@pytest.mark.asyncio
async def test_template_catalog_pages_and_search_preserve_visibility_and_exact_versions(
    environment_context: EnvironmentTestContext,
) -> None:
    context = environment_context
    client = context.client
    admin = await _login_headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    viewer = await _login_headers(client, USER_EMAIL, USER_PASSWORD)
    original = await _create_template(client, admin)
    ids = {original["id"]}
    for ttl in range(121, 141):
        manifest = {**original["manifest"], "default_ttl_seconds": ttl}
        response = await client.post(
            f"/api/v1/environment-templates/{original['template_id']}/versions",
            headers=admin,
            json={"manifest": manifest},
        )
        assert response.status_code == 201, response.text
        ids.add(response.json()["id"])
    literal_payload = {**_template_payload(), "template_key": "fixture.literal"}
    literal_payload["display_name"] = "百分号%_原样匹配"
    literal = await client.post(
        "/api/v1/environment-templates", headers=admin, json=literal_payload
    )
    assert literal.status_code == 201, literal.text
    ids.add(literal.json()["id"])
    found: set[str] = set()
    for page, expected in ((1, 20), (2, 2), (99, 0)):
        response = await client.get(
            "/api/v1/environment-templates",
            headers=viewer,
            params={"page": page, "page_size": 20},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == 22 and len(result["items"]) == expected
        page_ids = {row["id"] for row in result["items"]}
        assert not found.intersection(page_ids)
        found.update(page_ids)
    assert found == ids
    search = await client.get(
        "/api/v1/environment-templates", headers=viewer, params={"search": "%_"}
    )
    assert search.status_code == 200 and search.json()["total"] == 1
    assert search.json()["items"][0]["id"] == literal.json()["id"]
    disabled = await client.post(
        f"/api/v1/environment-templates/{original['template_id']}/disable", headers=admin
    )
    assert disabled.status_code == 204
    for headers, active_only, expected in (
        (viewer, False, 1),
        (admin, True, 1),
        (admin, False, 22),
    ):
        response = await client.get(
            "/api/v1/environment-templates",
            headers=headers,
            params={"active_only": active_only},
        )
        assert response.status_code == 200 and response.json()["total"] == expected
    assert context.queue.provision_ids == [] and context.queue.cleanup_ids == []
    assert context.queue.cleanup_ids == []


@pytest.mark.asyncio
async def test_fixed_template_reads_reject_missing_foreign_and_tampered_references(
    environment_context: EnvironmentTestContext,
) -> None:
    context = environment_context
    client = context.client
    admin = await _login_headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    project_id = await _create_project(client, admin)
    template = await _create_template(client, admin)
    instance_id = await _queue_instance_id(
        context, admin, project_id, template["id"], "scoped-template-read"
    )
    foreign = await _create_project(client, admin)
    foreign_read = await client.get(
        f"/api/v1/projects/{foreign}/environment-instances/{instance_id}/template-version",
        headers=admin,
    )
    assert foreign_read.status_code == 404 and foreign_read.json()["error"]["trace_id"]
    missing = await client.get(f"/api/v1/environment-templates/versions/{uuid4()}", headers=admin)
    assert missing.status_code == 404 and missing.json()["error"]["trace_id"]
    async with context.sessions() as session:
        stored = await session.get(EnvironmentTemplateVersion, UUID(str(template["id"])))
        assert stored is not None
        stored.manifest = {**stored.manifest, "default_ttl_seconds": 901}
        await session.commit()
    for path in (
        f"/api/v1/environment-templates/versions/{template['id']}",
        f"/api/v1/projects/{project_id}/environment-instances/{instance_id}/template-version",
    ):
        rejected = await client.get(path, headers=admin)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["error"]["code"] == "ENVIRONMENT_TEMPLATE_SIGNATURE_INVALID"
        assert rejected.json()["error"]["trace_id"]
    assert context.queue.provision_ids == [instance_id]


@pytest.mark.asyncio
async def test_invalid_stored_manifest_uses_standard_error_without_runtime_commands(
    environment_context: EnvironmentTestContext,
) -> None:
    context = environment_context
    headers = await _login_headers(context.client, ADMIN_EMAIL, ADMIN_PASSWORD)
    template = await _create_template(context.client, headers)
    async with context.sessions() as session:
        stored = await session.get(EnvironmentTemplateVersion, UUID(str(template["id"])))
        assert stored is not None
        stored.manifest = {"services": []}
        await session.commit()
    for path in (
        "/api/v1/environment-templates",
        f"/api/v1/environment-templates/versions/{template['id']}",
    ):
        response = await context.client.get(path, headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ENVIRONMENT_TEMPLATE_SIGNATURE_INVALID"
        assert response.json()["error"]["trace_id"]
    assert context.queue.provision_ids == [] and context.queue.cleanup_ids == []
