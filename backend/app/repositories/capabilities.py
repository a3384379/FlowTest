from uuid import UUID

from sqlalchemy import select
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

    async def list_runner_pools(self) -> list[RunnerPool]:
        rows = await self._session.scalars(select(RunnerPool).order_by(RunnerPool.name))
        return list(rows.all())

    async def list_runners(self, pool_id: UUID) -> list[Runner]:
        return list(
            (
                await self._session.scalars(
                    select(Runner).where(Runner.pool_id == pool_id).order_by(Runner.name)
                )
            ).all()
        )
