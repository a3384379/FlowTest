from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_sources import Credential, MockRequestLog, MockRoute, MockService


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

    async def list_mock_routes(self, service_id: UUID, *, enabled_only: bool) -> list[MockRoute]:
        query = select(MockRoute).where(MockRoute.mock_service_id == service_id)
        if enabled_only:
            query = query.where(MockRoute.is_enabled.is_(True))
        return list(
            (
                await self._session.scalars(
                    query.order_by(MockRoute.priority.desc(), MockRoute.created_at)
                )
            ).all()
        )

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
