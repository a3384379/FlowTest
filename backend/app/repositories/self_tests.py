"""Project-scoped persistence and atomic leases for self-test metadata."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.self_tests import SelfTestBatch, SelfTestInstallation, SelfTestScenarioResult


class SelfTestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def installation(self, project_id: UUID, identifier: UUID) -> SelfTestInstallation | None:
        return cast(
            SelfTestInstallation | None,
            await self.session.scalar(
                select(SelfTestInstallation).where(
                    SelfTestInstallation.id == identifier,
                    SelfTestInstallation.project_id == project_id,
                )
            ),
        )

    async def installed_pack(
        self, project_id: UUID, binding_id: UUID, digest: str
    ) -> SelfTestInstallation | None:
        return cast(
            SelfTestInstallation | None,
            await self.session.scalar(
                select(SelfTestInstallation).where(
                    SelfTestInstallation.project_id == project_id,
                    SelfTestInstallation.binding_id == binding_id,
                    SelfTestInstallation.pack_digest == digest,
                )
            ),
        )

    async def installation_by_key(self, project_id: UUID, key: str) -> SelfTestInstallation | None:
        return cast(
            SelfTestInstallation | None,
            await self.session.scalar(
                select(SelfTestInstallation).where(
                    SelfTestInstallation.project_id == project_id,
                    SelfTestInstallation.idempotency_key == key,
                )
            ),
        )

    async def installations(
        self, project_id: UUID, binding_id: UUID | None = None
    ) -> list[SelfTestInstallation]:
        query = select(SelfTestInstallation).where(SelfTestInstallation.project_id == project_id)
        if binding_id is not None:
            query = query.where(SelfTestInstallation.binding_id == binding_id)
        return list(
            (
                await self.session.scalars(
                    query.order_by(SelfTestInstallation.created_at.desc()).limit(100)
                )
            ).all()
        )

    async def batch(self, project_id: UUID, identifier: UUID) -> SelfTestBatch | None:
        return cast(
            SelfTestBatch | None,
            await self.session.scalar(
                select(SelfTestBatch).where(
                    SelfTestBatch.id == identifier, SelfTestBatch.project_id == project_id
                )
            ),
        )

    async def batch_by_key(self, project_id: UUID, key: str) -> SelfTestBatch | None:
        return cast(
            SelfTestBatch | None,
            await self.session.scalar(
                select(SelfTestBatch).where(
                    SelfTestBatch.project_id == project_id, SelfTestBatch.idempotency_key == key
                )
            ),
        )

    async def batches(
        self, project_id: UUID, installation_id: UUID, *, cursor: UUID | None, limit: int
    ) -> tuple[list[SelfTestBatch], int]:
        scope = (
            SelfTestBatch.project_id == project_id,
            SelfTestBatch.installation_id == installation_id,
        )
        total = int(
            await self.session.scalar(select(func.count()).select_from(SelfTestBatch).where(*scope))
            or 0
        )
        query = select(SelfTestBatch).where(*scope)
        if cursor is not None:
            query = query.where(SelfTestBatch.id < cursor)
        rows = list(
            (
                await self.session.scalars(query.order_by(SelfTestBatch.id.desc()).limit(limit + 1))
            ).all()
        )
        return rows, total

    async def scenarios(self, batch_id: UUID) -> list[SelfTestScenarioResult]:
        return list(
            (
                await self.session.scalars(
                    select(SelfTestScenarioResult)
                    .where(SelfTestScenarioResult.batch_id == batch_id)
                    .order_by(SelfTestScenarioResult.position)
                )
            ).all()
        )

    async def claim_installation(
        self,
        model: SelfTestInstallation,
        *,
        expected_revision: int,
        owner: str,
        lease_hash: str,
        nonce_hash: str,
        expiry: datetime,
    ) -> SelfTestInstallation | None:
        query = (
            update(SelfTestInstallation)
            .where(
                SelfTestInstallation.id == model.id,
                SelfTestInstallation.revision == expected_revision,
                SelfTestInstallation.status.in_(("needs_input", "queued")),
                SelfTestInstallation.lease_hash.is_(None),
            )
            .values(
                status="installing",
                revision=SelfTestInstallation.revision + 1,
                lease_owner=owner,
                lease_hash=lease_hash,
                nonce_hash=nonce_hash,
                lease_expires_at=expiry,
            )
            .returning(SelfTestInstallation)
            .execution_options(populate_existing=True, synchronize_session="fetch")
        )
        return cast(SelfTestInstallation | None, await self.session.scalar(query))

    async def claim_batch(
        self,
        model: SelfTestBatch,
        *,
        expected_revision: int,
        owner: str,
        lease_hash: str,
        nonce_hash: str,
        expiry: datetime,
        now: datetime,
        phase: str,
    ) -> SelfTestBatch | None:
        query = (
            update(SelfTestBatch)
            .where(
                SelfTestBatch.id == model.id,
                SelfTestBatch.revision == expected_revision,
                SelfTestBatch.sealed_at.is_(None),
                SelfTestBatch.phase.not_in(("cancelled", "expired", "completed")),
                SelfTestBatch.deadline > now,
                SelfTestBatch.lease_hash.is_(None),
                or_(SelfTestBatch.nonce_hash.is_(None), SelfTestBatch.nonce_hash == nonce_hash),
            )
            .values(
                revision=SelfTestBatch.revision + 1,
                lease_owner=owner,
                lease_hash=lease_hash,
                nonce_hash=nonce_hash,
                lease_expires_at=expiry,
                phase=phase,
            )
            .returning(SelfTestBatch)
            .execution_options(populate_existing=True, synchronize_session="fetch")
        )
        return cast(SelfTestBatch | None, await self.session.scalar(query))

    async def lock_batch(self, model: SelfTestBatch) -> SelfTestBatch | None:
        query = (
            update(SelfTestBatch)
            .where(SelfTestBatch.id == model.id, SelfTestBatch.revision == model.revision)
            .values(revision=SelfTestBatch.revision + 1)
            .returning(SelfTestBatch)
            .execution_options(populate_existing=True, synchronize_session="fetch")
        )
        return cast(SelfTestBatch | None, await self.session.scalar(query))

    async def lock_installation(self, model: SelfTestInstallation) -> SelfTestInstallation | None:
        query = (
            update(SelfTestInstallation)
            .where(
                SelfTestInstallation.id == model.id, SelfTestInstallation.revision == model.revision
            )
            .values(revision=SelfTestInstallation.revision + 1)
            .returning(SelfTestInstallation)
            .execution_options(populate_existing=True, synchronize_session="fetch")
        )
        return cast(SelfTestInstallation | None, await self.session.scalar(query))
