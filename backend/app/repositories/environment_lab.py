from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment_lab import (
    EnvironmentInstance,
    EnvironmentTemplate,
    EnvironmentTemplateVersion,
)


class EnvironmentLabRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_template(self, template: EnvironmentTemplate) -> None:
        self._session.add(template)

    def add_template_version(self, version: EnvironmentTemplateVersion) -> None:
        self._session.add(version)

    def add_instance(self, instance: EnvironmentInstance) -> None:
        self._session.add(instance)

    async def get_template(self, template_id: UUID) -> EnvironmentTemplate | None:
        return await self._session.get(EnvironmentTemplate, template_id)

    async def get_template_for_update(self, template_id: UUID) -> EnvironmentTemplate | None:
        result = await self._session.execute(
            select(EnvironmentTemplate)
            .where(EnvironmentTemplate.id == template_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_template_by_key(self, template_key: str) -> EnvironmentTemplate | None:
        result = await self._session.execute(
            select(EnvironmentTemplate).where(EnvironmentTemplate.template_key == template_key)
        )
        return result.scalar_one_or_none()

    async def latest_template_version(self, template_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.max(EnvironmentTemplateVersion.version)).where(
                EnvironmentTemplateVersion.template_id == template_id
            )
        )
        return int(value or 0)

    async def get_template_version(self, version_id: UUID) -> EnvironmentTemplateVersion | None:
        return await self._session.get(EnvironmentTemplateVersion, version_id)

    async def list_template_versions(
        self, *, include_disabled: bool
    ) -> list[tuple[EnvironmentTemplateVersion, EnvironmentTemplate]]:
        statement = (
            select(EnvironmentTemplateVersion, EnvironmentTemplate)
            .join(
                EnvironmentTemplate,
                EnvironmentTemplate.id == EnvironmentTemplateVersion.template_id,
            )
            .order_by(
                EnvironmentTemplateVersion.created_at.desc(),
                EnvironmentTemplate.template_key,
                EnvironmentTemplateVersion.version.desc(),
            )
        )
        if not include_disabled:
            statement = statement.where(EnvironmentTemplate.status == "active")
        return list((await self._session.execute(statement)).tuples().all())

    async def get_instance(self, instance_id: UUID) -> EnvironmentInstance | None:
        return await self._session.get(EnvironmentInstance, instance_id)

    async def get_instance_for_update(self, instance_id: UUID) -> EnvironmentInstance | None:
        result = await self._session.execute(
            select(EnvironmentInstance)
            .where(EnvironmentInstance.id == instance_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_instance_by_idempotency_key(
        self, *, project_id: UUID, idempotency_key: str
    ) -> EnvironmentInstance | None:
        result = await self._session.execute(
            select(EnvironmentInstance).where(
                EnvironmentInstance.project_id == project_id,
                EnvironmentInstance.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_instances(
        self, *, project_id: UUID, offset: int, limit: int
    ) -> tuple[list[EnvironmentInstance], int]:
        criteria = EnvironmentInstance.project_id == project_id
        total = await self._session.scalar(
            select(func.count()).select_from(EnvironmentInstance).where(criteria)
        )
        rows = await self._session.scalars(
            select(EnvironmentInstance)
            .where(criteria)
            .order_by(EnvironmentInstance.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows.all()), int(total or 0)

    async def list_reconciliation_candidates(
        self, *, now: datetime, stale_at: datetime, limit: int
    ) -> list[EnvironmentInstance]:
        rows = await self._session.scalars(
            select(EnvironmentInstance)
            .where(
                or_(
                    EnvironmentInstance.expires_at <= now,
                    EnvironmentInstance.cleanup_status.in_(("pending", "failed")),
                    (
                        EnvironmentInstance.status.in_(("queued", "provisioning"))
                        & (EnvironmentInstance.updated_at <= stale_at)
                    ),
                ),
                EnvironmentInstance.cleanup_status != "completed",
            )
            .order_by(EnvironmentInstance.expires_at, EnvironmentInstance.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows.all())
