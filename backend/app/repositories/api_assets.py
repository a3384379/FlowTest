from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_assets import APIDefinition, APIVersion, Environment, Secret


class APIAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: Environment | Secret | APIDefinition | APIVersion) -> None:
        self._session.add(entity)

    async def delete(self, entity: Environment | Secret | APIDefinition) -> None:
        await self._session.delete(entity)

    async def get_environment(self, environment_id: UUID) -> Environment | None:
        return await self._session.get(Environment, environment_id)

    async def find_environment_by_name(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> Environment | None:
        query = select(Environment).where(
            Environment.project_id == project_id,
            Environment.name == name,
        )
        if excluding_id is not None:
            query = query.where(Environment.id != excluding_id)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def list_environments(self, project_id: UUID) -> list[Environment]:
        return list(
            (
                await self._session.scalars(
                    select(Environment)
                    .where(Environment.project_id == project_id)
                    .order_by(Environment.created_at)
                )
            ).all()
        )

    async def find_secret(
        self, *, project_id: UUID, environment_id: UUID | None, name: str
    ) -> Secret | None:
        query = select(Secret).where(
            Secret.project_id == project_id,
            Secret.environment_id == environment_id,
            Secret.name == name,
        )
        return (await self._session.execute(query)).scalar_one_or_none()

    async def list_secrets(self, project_id: UUID) -> list[Secret]:
        return list(
            (
                await self._session.scalars(
                    select(Secret)
                    .where(Secret.project_id == project_id)
                    .order_by(Secret.created_at)
                )
            ).all()
        )

    async def secrets_for_environment(
        self, *, project_id: UUID, environment_id: UUID
    ) -> list[Secret]:
        return list(
            (
                await self._session.scalars(
                    select(Secret)
                    .where(
                        Secret.project_id == project_id,
                        (Secret.environment_id.is_(None))
                        | (Secret.environment_id == environment_id),
                    )
                    .order_by(Secret.environment_id.nulls_first(), Secret.created_at)
                )
            ).all()
        )

    async def get_definition(self, definition_id: UUID) -> APIDefinition | None:
        return await self._session.get(APIDefinition, definition_id)

    async def find_imported_definition(
        self, *, project_id: UUID, import_key: str
    ) -> APIDefinition | None:
        query = select(APIDefinition).where(
            APIDefinition.project_id == project_id,
            APIDefinition.import_key == import_key,
        )
        return (await self._session.execute(query)).scalar_one_or_none()

    async def list_imported_definitions(
        self, *, project_id: UUID, import_source: str
    ) -> list[APIDefinition]:
        return list(
            (
                await self._session.scalars(
                    select(APIDefinition).where(
                        APIDefinition.project_id == project_id,
                        APIDefinition.import_source == import_source,
                    )
                )
            ).all()
        )

    async def list_definitions(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[APIDefinition], int]:
        definitions = list(
            (
                await self._session.scalars(
                    select(APIDefinition)
                    .where(APIDefinition.project_id == project_id)
                    .order_by(APIDefinition.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(APIDefinition)
            .where(APIDefinition.project_id == project_id)
        )
        return definitions, int(total or 0)

    async def get_version(self, *, definition_id: UUID, version: int) -> APIVersion | None:
        query = select(APIVersion).where(
            APIVersion.api_definition_id == definition_id,
            APIVersion.version == version,
        )
        return (await self._session.execute(query)).scalar_one_or_none()

    async def list_versions(self, definition_id: UUID) -> list[APIVersion]:
        return list(
            (
                await self._session.scalars(
                    select(APIVersion)
                    .where(APIVersion.api_definition_id == definition_id)
                    .order_by(APIVersion.version.desc())
                )
            ).all()
        )
