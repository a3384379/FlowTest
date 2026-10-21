from dataclasses import dataclass
from typing import cast as typing_cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Text, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models.data_sources import Credential, MockRequestLog, MockRoute, MockService


@dataclass(frozen=True, slots=True)
class MockStoredPreviewBody:
    route: MockRoute
    character_count: int
    body: JsonValue


@dataclass(frozen=True, slots=True)
class MockPreviewCatalogSize:
    count: int
    metadata_characters: int


class DataSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: Credential | MockService | MockRoute | MockRequestLog) -> None:
        self._session.add(entity)

    async def delete(self, entity: Credential | MockService | MockRoute) -> None:
        await self._session.delete(entity)

    async def get_credential(self, credential_id: UUID) -> Credential | None:
        return await self._session.get(Credential, credential_id)

    async def find_credential_by_name(
        self,
        *,
        project_id: UUID,
        name: str,
        excluding_id: UUID | None = None,
    ) -> Credential | None:
        query = select(Credential).where(
            Credential.project_id == project_id,
            Credential.name == name,
        )
        if excluding_id is not None:
            query = query.where(Credential.id != excluding_id)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def list_credentials(self, project_id: UUID) -> list[Credential]:
        return list(
            (
                await self._session.scalars(
                    select(Credential)
                    .where(Credential.project_id == project_id)
                    .order_by(Credential.created_at.desc())
                )
            ).all()
        )

    async def get_mock_service(self, service_id: UUID) -> MockService | None:
        return await self._session.get(MockService, service_id)

    async def find_mock_service_by_slug(self, slug: str) -> MockService | None:
        query = select(MockService).where(MockService.slug == slug)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def find_mock_service_by_name(
        self,
        *,
        project_id: UUID,
        name: str,
        excluding_id: UUID | None = None,
    ) -> MockService | None:
        query = select(MockService).where(
            MockService.project_id == project_id,
            MockService.name == name,
        )
        if excluding_id is not None:
            query = query.where(MockService.id != excluding_id)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def list_mock_services(self, project_id: UUID) -> list[MockService]:
        return list(
            (
                await self._session.scalars(
                    select(MockService)
                    .where(MockService.project_id == project_id)
                    .order_by(MockService.created_at.desc())
                )
            ).all()
        )

    async def get_mock_route(self, route_id: UUID) -> MockRoute | None:
        return await self._session.get(MockRoute, route_id)

    async def find_mock_route_by_name(
        self,
        *,
        service_id: UUID,
        name: str,
        excluding_id: UUID | None = None,
    ) -> MockRoute | None:
        query = select(MockRoute).where(
            MockRoute.mock_service_id == service_id,
            MockRoute.name == name,
        )
        if excluding_id is not None:
            query = query.where(MockRoute.id != excluding_id)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def list_mock_routes(
        self,
        service_id: UUID,
        *,
        enabled_only: bool,
        limit: int | None = None,
        include_response_body: bool = True,
    ) -> list[MockRoute]:
        query = select(MockRoute).where(MockRoute.mock_service_id == service_id)
        if enabled_only:
            query = query.where(MockRoute.is_enabled.is_(True))
        if not include_response_body:
            query = query.options(defer(MockRoute.response_body))
        if limit is not None:
            query = query.limit(limit)
        return list(
            (
                await self._session.scalars(
                    query.order_by(MockRoute.priority.desc(), MockRoute.created_at)
                )
            ).all()
        )

    async def mock_preview_catalog_size(self, service_id: UUID) -> MockPreviewCatalogSize:
        size = (
            func.length(MockRoute.name)
            + func.length(MockRoute.path_pattern)
            + func.coalesce(func.length(MockRoute.scenario), 0)
            + func.length(cast(MockRoute.query_conditions, Text))
            + func.length(cast(MockRoute.header_conditions, Text))
            + func.length(cast(MockRoute.response_headers, Text))
        )
        row = (
            await self._session.execute(
                select(func.count(), func.coalesce(func.sum(size), 0))
                .select_from(MockRoute)
                .where(MockRoute.mock_service_id == service_id)
            )
        ).one()
        return MockPreviewCatalogSize(int(row[0]), int(row[1]))

    async def get_mock_preview_body(
        self, route_id: UUID, *, maximum_characters: int
    ) -> MockStoredPreviewBody | None:
        size = func.coalesce(func.length(cast(MockRoute.response_body, Text)), 0)
        body = case((size <= maximum_characters, MockRoute.response_body), else_=None)
        row = (
            await self._session.execute(
                select(MockRoute, size, body)
                .where(MockRoute.id == route_id)
                .options(defer(MockRoute.response_body))
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            return None
        route, count, value = row
        return MockStoredPreviewBody(route, int(count), typing_cast(JsonValue, value))

    async def list_mock_logs(
        self,
        *,
        service_id: UUID,
        offset: int,
        limit: int,
    ) -> tuple[list[MockRequestLog], int]:
        logs = list(
            (
                await self._session.scalars(
                    select(MockRequestLog)
                    .where(MockRequestLog.mock_service_id == service_id)
                    .order_by(MockRequestLog.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(MockRequestLog)
            .where(MockRequestLog.mock_service_id == service_id)
        )
        return logs, int(total or 0)
