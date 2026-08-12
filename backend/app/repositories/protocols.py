from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.protocols import SchemaArtifact


class ProtocolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, artifact: SchemaArtifact) -> None:
        self._session.add(artifact)

    async def get(self, artifact_id: UUID) -> SchemaArtifact | None:
        return await self._session.get(SchemaArtifact, artifact_id)

    async def find_by_hash(
        self,
        *,
        project_id: UUID,
        protocol: str,
        content_sha256: str,
    ) -> SchemaArtifact | None:
        statement = select(SchemaArtifact).where(
            SchemaArtifact.project_id == project_id,
            SchemaArtifact.protocol == protocol,
            SchemaArtifact.content_sha256 == content_sha256,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def next_version(self, *, project_id: UUID, protocol: str, name: str) -> int:
        value = await self._session.scalar(
            select(func.max(SchemaArtifact.version)).where(
                SchemaArtifact.project_id == project_id,
                SchemaArtifact.protocol == protocol,
                SchemaArtifact.name == name,
            )
        )
        return int(value or 0) + 1

    async def list(
        self,
        *,
        project_id: UUID,
        protocol: str,
        offset: int,
        limit: int,
    ) -> tuple[list[SchemaArtifact], int]:
        filters = (
            SchemaArtifact.project_id == project_id,
            SchemaArtifact.protocol == protocol,
        )
        items = list(
            (
                await self._session.scalars(
                    select(SchemaArtifact)
                    .where(*filters)
                    .order_by(SchemaArtifact.name, SchemaArtifact.version.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(SchemaArtifact).where(*filters)
        )
        return items, int(total or 0)
