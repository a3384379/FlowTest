import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.main import app
from app.models import Base
from app.models.access import User

ADMIN_EMAIL = "import-admin@example.com"
ADMIN_PASSWORD = "import-password-123!"


@pytest.fixture
async def import_client() -> AsyncIterator[AsyncClient]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Import administrator",
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
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_reimport_produces_diff_without_duplicate_definitions(
    import_client: AsyncClient,
) -> None:
    headers = await _login_headers(import_client)
    project_id = await _create_project(import_client, headers)
    first_document = _openapi_document(
        {
            "/users": {"get": {"summary": "List users"}},
            "/orders": {"post": {"summary": "Create order"}},
        }
    )

    first = await _upload_document(import_client, headers, project_id, first_document)
    assert first.status_code == 201, first.text
    assert first.json()["added"] == 2
    assert first.json()["changed"] == 0

    repeated = await _upload_document(import_client, headers, project_id, first_document)
    assert repeated.json()["unchanged"] == 2
    assert repeated.json()["added"] == 0

    changed_document = _openapi_document({"/users": {"get": {"summary": "List active users"}}})
    changed = await _upload_document(import_client, headers, project_id, changed_document)
    payload = changed.json()
    assert payload["changed"] == 1
    assert payload["deleted"] == 1
    assert {item["change"] for item in payload["results"]} == {"changed", "deleted"}
    deleted = next(item for item in payload["results"] if item["change"] == "deleted")
    assert deleted["method"] == "POST"
    assert deleted["path"] == "/orders"

    definitions = await import_client.get(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        params={"page": 1, "page_size": 100},
    )
    assert definitions.json()["total"] == 2
    users = next(
        item for item in definitions.json()["items"] if item["name"] == "List active users"
    )
    assert users["current_version"] == 2

    history = await import_client.get(f"/api/v1/projects/{project_id}/imports", headers=headers)
    assert history.status_code == 200
    assert history.json()["total"] == 3


@pytest.mark.asyncio
async def test_import_rejects_invalid_and_duplicate_operations(
    import_client: AsyncClient,
) -> None:
    headers = await _login_headers(import_client)
    project_id = await _create_project(import_client, headers)
    invalid = await _upload_document(import_client, headers, project_id, b"[]")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "IMPORT_INVALID"

    duplicate = _openapi_document(
        {
            "/users": {"get": {"summary": "One"}},
            "//users": {"get": {"summary": "Duplicate"}},
        }
    )
    response = await _upload_document(import_client, headers, project_id, duplicate)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMPORT_DUPLICATE_OPERATION"


@pytest.mark.asyncio
async def test_import_preview_selective_merge_and_explicit_deactivation(
    import_client: AsyncClient,
) -> None:
    headers = await _login_headers(import_client)
    project_id = await _create_project(import_client, headers)
    original = _openapi_document(
        {
            "/users": {"get": {"summary": "List users"}},
            "/orders": {"post": {"summary": "Create order"}},
        }
    )
    assert (await _upload_document(import_client, headers, project_id, original)).status_code == 201

    changed = _openapi_document(
        {
            "/users": {"get": {"summary": "List active users"}},
            "/products": {"get": {"summary": "List products"}},
        }
    )
    preview = await _preview_document(import_client, headers, project_id, changed)
    assert preview.status_code == 201, preview.text
    diff = preview.json()
    assert diff["status"] == "preview"
    assert {item["change"] for item in diff["results"]} == {
        "added",
        "changed",
        "deleted",
    }
    assert (
        next(item for item in diff["results"] if item["change"] == "added")["definition_id"] is None
    )

    selected = {
        item["import_key"] for item in diff["results"] if item["change"] in {"added", "changed"}
    }
    merged = await import_client.post(
        f"/api/v1/projects/{project_id}/imports/{diff['id']}/merge",
        headers=headers,
        json={"selected_keys": sorted(selected)},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["status"] == "applied"
    assert set(merged.json()["applied_keys"]) == selected

    definitions = await import_client.get(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        params={"page": 1, "page_size": 100},
    )
    assert definitions.json()["total"] == 3
    assert {item["name"] for item in definitions.json()["items"]} == {
        "List active users",
        "Create order",
        "List products",
    }

    deletion_preview = await _preview_document(import_client, headers, project_id, changed)
    deletion = next(
        item for item in deletion_preview.json()["results"] if item["change"] == "deleted"
    )
    deactivated = await import_client.post(
        f"/api/v1/projects/{project_id}/imports/{deletion_preview.json()['id']}/merge",
        headers=headers,
        json={"selected_keys": [deletion["import_key"]]},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["applied_keys"] == [deletion["import_key"]]

    active = await import_client.get(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        params={"page": 1, "page_size": 100},
    )
    assert active.json()["total"] == 2

    repeated = await import_client.post(
        f"/api/v1/projects/{project_id}/imports/{deletion_preview.json()['id']}/merge",
        headers=headers,
        json={"selected_keys": [deletion["import_key"]]},
    )
    assert repeated.status_code == 200
    different = await import_client.post(
        f"/api/v1/projects/{project_id}/imports/{deletion_preview.json()['id']}/merge",
        headers=headers,
        json={"selected_keys": []},
    )
    assert different.status_code == 409
    assert different.json()["error"]["code"] == "IMPORT_ALREADY_APPLIED"


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Imported APIs", "description": "Import verification"},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def _upload_document(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    content: bytes,
):
    return await client.post(
        f"/api/v1/projects/{project_id}/imports",
        headers=headers,
        files={"document": ("sample.json", content, "application/json")},
        data={"source_type": "auto"},
    )


async def _preview_document(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    content: bytes,
):
    return await client.post(
        f"/api/v1/projects/{project_id}/imports/preview",
        headers=headers,
        files={"document": ("sample.json", content, "application/json")},
        data={"source_type": "auto"},
    )


def _openapi_document(paths: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Sample", "version": "1.0.0"},
            "paths": paths,
        }
    ).encode()
