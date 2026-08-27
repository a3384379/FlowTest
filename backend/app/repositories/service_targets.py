from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_targets import Service, ServiceEndpoint


class ServiceTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: Service | ServiceEndpoint) -> None:
        self._session.add(entity)

    async def get_service(self, service_id: UUID) -> Service | None:
        return await self._session.get(Service, service_id)

    async def find_service_by_key(self, *, project_id: UUID, service_key: str) -> Service | None:
        return (
            await self._session.scalars(
                select(Service).where(
                    Service.project_id == project_id,
                    Service.service_key == service_key,
                )
            )
        ).one_or_none()

    async def list_services(self, project_id: UUID) -> list[Service]:
        return list(
            (
                await self._session.scalars(
                    select(Service)
                    .where(Service.project_id == project_id)
                    .order_by(Service.service_key)
                )
            ).all()
        )

    async def get_endpoint(self, endpoint_id: UUID) -> ServiceEndpoint | None:
        return await self._session.get(ServiceEndpoint, endpoint_id)

    async def find_endpoint(
        self,
        *,
        environment_id: UUID,
        service_id: UUID,
        variant: str,
    ) -> ServiceEndpoint | None:
        return (
            await self._session.scalars(
                select(ServiceEndpoint).where(
                    ServiceEndpoint.environment_id == environment_id,
                    ServiceEndpoint.service_id == service_id,
                    ServiceEndpoint.variant == variant,
                )
            )
        ).one_or_none()

    async def list_endpoints(
        self, *, project_id: UUID, environment_id: UUID | None = None
    ) -> list[ServiceEndpoint]:
        query = select(ServiceEndpoint).where(ServiceEndpoint.project_id == project_id)
        if environment_id is not None:
            query = query.where(ServiceEndpoint.environment_id == environment_id)
        return list((await self._session.scalars(query.order_by(ServiceEndpoint.created_at))).all())
