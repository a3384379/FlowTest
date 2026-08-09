from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifacts import Artifact


class ArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, artifact: Artifact) -> None:
        self._session.add(artifact)

    async def get(self, artifact_id: UUID) -> Artifact | None:
        return await self._session.get(Artifact, artifact_id)

    async def list_for_project(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[Artifact], int]:
        artifacts = list(
            (
                await self._session.scalars(
                    select(Artifact)
                    .where(Artifact.project_id == project_id)
                    .order_by(Artifact.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.project_id == project_id)
        )
        return artifacts, int(total or 0)
