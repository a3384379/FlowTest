from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.capabilities import Capability, Plugin, Runner, RunnerPool


class CapabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_plugin_capabilities(self) -> list[Capability]:
        return list(
            (
                await self._session.scalars(
                    select(Capability)
                    .where(Capability.source == "plugin")
                    .order_by(Capability.capability_key, Capability.version)
                )
            ).all()
        )

    async def list_plugins(self) -> list[Plugin]:
        return list(
            (
                await self._session.scalars(
                    select(Plugin).order_by(Plugin.plugin_key, Plugin.version)
                )
            ).all()
        )

    async def list_runner_pools(self, *, organization_id: UUID | None = None) -> list[RunnerPool]:
        statement = select(RunnerPool)
        if organization_id is not None:
            statement = statement.where(
                or_(
                    RunnerPool.organization_id == organization_id,
                    RunnerPool.organization_id.is_(None),
                )
            )
        rows = await self._session.scalars(statement.order_by(RunnerPool.name))
        return list(rows.all())

    async def list_runners(self, pool_id: UUID) -> list[Runner]:
        return list(
            (
                await self._session.scalars(
                    select(Runner).where(Runner.pool_id == pool_id).order_by(Runner.name)
                )
            ).all()
        )
