from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.access import ProjectRole
from app.main import app
from app.models import Base
from app.models.access import Project, ProjectMember, User
from app.models.api_assets import APIDefinition
from app.models.data_sources import Credential
from app.models.workflows import Workflow

SEARCH_EMAIL = "search-viewer@example.com"
SEARCH_PASSWORD = "search-viewer-password-123!"


@dataclass(frozen=True, slots=True)
class SearchContext:
    client: AsyncClient
    visible_project_id: UUID
    hidden_project_id: UUID


@pytest.fixture
async def search_context() -> AsyncIterator[SearchContext]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        context = await _seed_search_data(session)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield SearchContext(
            client=client,
            visible_project_id=context[0],
            hidden_project_id=context[1],
        )
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_global_search_ranks_assets_and_respects_project_access(
    search_context: SearchContext,
) -> None:
    headers = await _login(search_context.client)
    response = await search_context.client.get(
        "/api/v1/search", params={"q": "billing"}, headers=headers
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["title"] for item in payload["items"]] == [
        "Billing API",
        "Checkout regression",
    ]
    assert {item["project_id"] for item in payload["items"]} == {
        str(search_context.visible_project_id)
    }
    assert all("secret" not in item["title"].lower() for item in payload["items"])
    assert payload["items"][0]["path"].startswith(
        f"/projects/{search_context.visible_project_id}/apis?focus=api:"
    )


@pytest.mark.asyncio
async def test_global_search_escapes_wildcards_and_rejects_inaccessible_scope(
    search_context: SearchContext,
) -> None:
    headers = await _login(search_context.client)
    literal_match = await search_context.client.get(
        "/api/v1/search", params={"q": "100%"}, headers=headers
    )
    forbidden_scope = await search_context.client.get(
        "/api/v1/search",
        params={"q": "billing", "project_id": str(search_context.hidden_project_id)},
        headers=headers,
    )
    blank_query = await search_context.client.get(
        "/api/v1/search", params={"q": "  "}, headers=headers
    )

    assert literal_match.status_code == 200
    assert [item["title"] for item in literal_match.json()["items"]] == ["100% Coverage API"]
    assert forbidden_scope.status_code == 404
    assert forbidden_scope.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert forbidden_scope.json()["error"]["trace_id"]
    assert blank_query.status_code == 422
    assert blank_query.json()["error"]["code"] == "SEARCH_QUERY_INVALID"
    assert blank_query.json()["error"]["trace_id"]


async def _seed_search_data(session: AsyncSession) -> tuple[UUID, UUID]:
    viewer = User(
        email=SEARCH_EMAIL,
        display_name="Search viewer",
        password_hash=password_service.hash(SEARCH_PASSWORD),
        is_active=True,
        is_system_admin=False,
        requires_password_change=False,
    )
    session.add(viewer)
    await session.flush()
    visible = Project(name="Visible Workspace", description="", created_by_id=viewer.id)
    hidden = Project(name="Hidden Workspace", description="", created_by_id=viewer.id)
    session.add_all([visible, hidden])
    await session.flush()
    session.add(ProjectMember(project_id=visible.id, user_id=viewer.id, role=ProjectRole.VIEWER))
    session.add_all(
        [
            APIDefinition(
                project_id=visible.id,
                folder_id=None,
                name="Billing API",
                description="Invoice endpoint",
                import_key=None,
                import_fingerprint=None,
                import_source=None,
                created_by_id=viewer.id,
            ),
            APIDefinition(
                project_id=visible.id,
                folder_id=None,
                name="100% Coverage API",
                description="Literal wildcard fixture",
                import_key=None,
                import_fingerprint=None,
                import_source=None,
                created_by_id=viewer.id,
            ),
            APIDefinition(
                project_id=hidden.id,
                folder_id=None,
                name="Billing Hidden API",
                description="Must not leak",
                import_key=None,
                import_fingerprint=None,
                import_source=None,
                created_by_id=viewer.id,
            ),
            Workflow(
                project_id=visible.id,
                folder_id=None,
                name="Checkout regression",
                description="Billing regression flow",
                draft_definition={"schema_version": "1.0", "nodes": [], "edges": []},
                created_by_id=viewer.id,
            ),
            Credential(
                project_id=visible.id,
                name="Billing secret",
                kind="postgresql",
                host="db.internal",
                port=5432,
                database_name="flowtest",
                username="service",
                secret_provider="local",
                provider_reference=None,
                ciphertext=b"encrypted",
                nonce=b"123456789012",
                tls_enabled=True,
                created_by_id=viewer.id,
            ),
        ]
    )
    await session.commit()
    return visible.id, hidden.id


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": SEARCH_EMAIL, "password": SEARCH_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
