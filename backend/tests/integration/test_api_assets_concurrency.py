import asyncio
import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import password_service
from app.domain.api_assets import APIVersionSpec, AuthKind, BodyKind, HttpMethod
from app.models.access import AuditLog, Folder, Project, User
from app.models.api_assets import APIDefinition, APIVersion
from app.repositories.access import ProjectRepository
from app.repositories.api_assets import APIAssetRepository
from app.services.api_assets import APIAssetService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FLOWTEST_RUN_INTEGRATION") != "1",
        reason="Set FLOWTEST_RUN_INTEGRATION=1 to run PostgreSQL tests",
    ),
]


@dataclass(frozen=True)
class MoveFixture:
    actor_id: UUID
    project_id: UUID
    folder_id: UUID
    definition_id: UUID
    version_id: UUID
    definition_ids: tuple[UUID, ...]
    marker: str


async def _create_assets(sessions: async_sessionmaker[AsyncSession]) -> MoveFixture:
    marker = f"Integration API grouping {uuid4().hex}"
    async with sessions() as session:
        actor = User(
            email=f"api-move-{uuid4().hex}@example.com",
            display_name=marker,
            password_hash=password_service.hash("integration-password-123!"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        session.add(actor)
        await session.flush()
        project = Project(name=marker, created_by_id=actor.id)
        session.add(project)
        await session.flush()
        folder = Folder(project_id=project.id, name="目标分组", created_by_id=actor.id)
        session.add(folder)
        await session.commit()
        definition, version = await APIAssetService(session).create_definition(
            actor=actor,
            project_id=project.id,
            folder_id=None,
            service_id=None,
            name="并发移动接口",
            description="",
            request=APIVersionSpec(
                method=HttpMethod.GET,
                path="/orders",
                query_parameters=(),
                headers={},
                body_kind=BodyKind.NONE,
                body=None,
                auth_kind=AuthKind.NONE,
                auth_config={},
            ),
        )
        definitions = [definition]
        for index in range(2):
            extra, _ = await APIAssetService(session).create_definition(
                actor=actor,
                project_id=project.id,
                folder_id=None,
                service_id=None,
                name=f"分页移动接口{index}",
                description="",
                request=APIVersionSpec(
                    method=HttpMethod.GET,
                    path="/orders",
                    query_parameters=(),
                    headers={},
                    body_kind=BodyKind.NONE,
                    body=None,
                    auth_kind=AuthKind.NONE,
                    auth_config={},
                ),
            )
            extra.created_at = definition.created_at
            definitions.append(extra)
        await session.commit()
        return MoveFixture(
            actor.id,
            project.id,
            folder.id,
            definition.id,
            version.id,
            tuple(item.id for item in definitions),
            marker,
        )


@pytest.mark.asyncio
async def test_single_and_bulk_move_share_destination_without_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fixture = await _create_assets(sessions)
    destination_locked = asyncio.Event()
    original_get = ProjectRepository.get_folder

    async def observe_destination(
        self: ProjectRepository,
        folder_id: UUID,
        *,
        for_update: bool = False,
    ) -> Folder | None:
        folder = await original_get(self, folder_id, for_update=for_update)
        if for_update:
            destination_locked.set()
        return folder

    monkeypatch.setattr(ProjectRepository, "get_folder", observe_destination)
    bulk: asyncio.Task[list[APIDefinition]] | None = None
    try:
        async with sessions() as single_session, sessions() as bulk_session:
            single_actor = await single_session.get(User, fixture.actor_id)
            bulk_actor = await bulk_session.get(User, fixture.actor_id)
            assert single_actor is not None and bulk_actor is not None
            locked = await APIAssetRepository(single_session).get_definition(
                fixture.definition_id,
                for_update=True,
            )
            assert locked is not None
            bulk = asyncio.create_task(
                APIAssetService(bulk_session).move_definitions(
                    actor=bulk_actor,
                    project_id=fixture.project_id,
                    definition_ids=[fixture.definition_id],
                    folder_id=fixture.folder_id,
                )
            )
            await asyncio.wait_for(destination_locked.wait(), timeout=5)
            moved = await asyncio.wait_for(
                APIAssetService(single_session).update_definition(
                    actor=single_actor,
                    project_id=fixture.project_id,
                    definition_id=fixture.definition_id,
                    name=None,
                    description=None,
                    folder_id=fixture.folder_id,
                    change_folder=True,
                    service_id=None,
                    change_service=False,
                ),
                timeout=5,
            )
            batch = await asyncio.wait_for(bulk, timeout=5)
            assert moved.folder_id == batch[0].folder_id == fixture.folder_id
            assert moved.current_version == batch[0].current_version == 1
            version = await single_session.get(APIVersion, fixture.version_id)
            assert version is not None and version.path == "/orders"
    finally:
        if bulk is not None and not bulk.done():
            bulk.cancel()
            await asyncio.gather(bulk, return_exceptions=True)
        async with sessions() as cleanup:
            project = await cleanup.get(Project, fixture.project_id)
            assert project is not None and project.name == fixture.marker
            await cleanup.execute(delete(AuditLog).where(AuditLog.project_id == fixture.project_id))
            await cleanup.execute(delete(Project).where(Project.id == fixture.project_id))
            await cleanup.execute(delete(User).where(User.id == fixture.actor_id))
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_paged_directory_remains_stable_while_moving_imported_timestamp_ties() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fixture = await _create_assets(sessions)
    try:
        async with sessions() as session:
            actor = await session.get(User, fixture.actor_id)
            assert actor is not None
            seen = []
            for page in range(1, 4):
                entries, total = await APIAssetService(session).list_directory(
                    actor=actor,
                    project_id=fixture.project_id,
                    page=page,
                    page_size=1,
                )
                assert total == 3
                seen.append(entries[0].id)
                await APIAssetService(session).move_definitions(
                    actor=actor,
                    project_id=fixture.project_id,
                    definition_ids=[entries[0].id],
                    folder_id=fixture.folder_id,
                )
            assert len(set(seen)) == 3
            assert set(seen) == set(fixture.definition_ids)
    finally:
        async with sessions() as cleanup:
            project = await cleanup.get(Project, fixture.project_id)
            assert project is not None and project.name == fixture.marker
            await cleanup.execute(delete(AuditLog).where(AuditLog.project_id == fixture.project_id))
            await cleanup.execute(delete(Project).where(Project.id == fixture.project_id))
            await cleanup.execute(delete(User).where(User.id == fixture.actor_id))
            await cleanup.commit()
        await engine.dispose()
