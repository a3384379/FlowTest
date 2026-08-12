from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.access import Project
from app.models.capabilities import Runner, RunnerPool
from app.models.runner_fabric import (
    RunnerEvent,
    RunnerLeaseRecord,
    RunnerRegistrationToken,
    RunnerTask,
)
from app.models.workflows import WorkflowExecution


class RunnerFabricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, model: object) -> None:
        self._session.add(model)

    async def get_pool(self, pool_id: UUID, *, lock: bool = False) -> RunnerPool | None:
        statement = select(RunnerPool).where(RunnerPool.id == pool_id)
        return await self._one(statement, lock=lock)

    async def lock_pool_claims(self, pool_id: UUID) -> None:
        await self._lock_scope(pool_id, namespace=1)

    async def lock_runner_control(self, runner_id: UUID) -> None:
        await self._lock_scope(runner_id, namespace=2)

    async def lock_project_capacity(self, project_id: UUID) -> None:
        await self._lock_scope(project_id, namespace=3)

    async def find_pool_by_name(self, name: str) -> RunnerPool | None:
        return cast(
            RunnerPool | None,
            await self._session.scalar(select(RunnerPool).where(RunnerPool.name == name)),
        )

    async def list_pools(self) -> list[RunnerPool]:
        return list(
            (
                await self._session.scalars(
                    select(RunnerPool).order_by(RunnerPool.created_at.desc())
                )
            ).all()
        )

    async def list_runners(self, pool_id: UUID | None = None) -> list[Runner]:
        statement = select(Runner)
        if pool_id is not None:
            statement = statement.where(Runner.pool_id == pool_id)
        return list(
            (await self._session.scalars(statement.order_by(Runner.created_at.desc()))).all()
        )

    async def get_runner(self, runner_id: UUID, *, lock: bool = False) -> Runner | None:
        statement = select(Runner).where(Runner.id == runner_id)
        return await self._one(statement, lock=lock)

    async def find_runner_by_token(self, token_hash: str, *, lock: bool = False) -> Runner | None:
        statement = select(Runner).where(Runner.token_hash == token_hash)
        return await self._one(statement, lock=lock)

    async def find_runner_by_identity(self, fingerprint: str) -> Runner | None:
        return cast(
            Runner | None,
            await self._session.scalar(
                select(Runner).where(Runner.identity_fingerprint == fingerprint)
            ),
        )

    async def get_registration_token(
        self, token_hash: str, *, lock: bool = False
    ) -> RunnerRegistrationToken | None:
        statement = select(RunnerRegistrationToken).where(
            RunnerRegistrationToken.token_hash == token_hash
        )
        return await self._one(statement, lock=lock)

    async def queued_count(self, project_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(RunnerTask)
            .where(
                RunnerTask.project_id == project_id,
                RunnerTask.status.in_(("queued", "leased")),
            )
        )
        return int(value or 0)

    async def active_execution_count(self, project_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count())
            .select_from(WorkflowExecution)
            .where(
                WorkflowExecution.project_id == project_id,
                WorkflowExecution.parent_execution_id.is_(None),
                WorkflowExecution.status == "running",
            )
        )
        return int(value or 0)

    async def pool_current_load(self, pool_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.coalesce(func.sum(Runner.current_load), 0)).where(Runner.pool_id == pool_id)
        )
        return int(value or 0)

    async def get_project(self, project_id: UUID, *, lock: bool = False) -> Project | None:
        statement = select(Project).where(Project.id == project_id)
        return await self._one(statement, lock=lock)

    async def claim_candidates(
        self,
        *,
        runner_type: str,
        available_at: datetime,
        limit: int = 100,
    ) -> list[RunnerTask]:
        statement = (
            select(RunnerTask)
            .where(
                RunnerTask.status == "queued",
                RunnerTask.required_runner_type == runner_type,
                RunnerTask.available_at <= available_at,
            )
            .order_by(
                RunnerTask.priority.desc(),
                RunnerTask.available_at,
                RunnerTask.created_at,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.scalars(statement)).all())

    async def get_task(self, task_id: UUID, *, lock: bool = False) -> RunnerTask | None:
        statement = select(RunnerTask).where(RunnerTask.id == task_id)
        return await self._one(statement, lock=lock)

    async def get_task_by_execution(
        self, execution_id: UUID, *, lock: bool = False
    ) -> RunnerTask | None:
        statement = select(RunnerTask).where(RunnerTask.execution_id == execution_id)
        return await self._one(statement, lock=lock)

    async def get_execution(
        self, execution_id: UUID, *, lock: bool = False
    ) -> WorkflowExecution | None:
        statement = select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
        return await self._one(statement, lock=lock)

    async def set_execution_family_status(self, execution_id: UUID, status: str) -> None:
        await self._session.execute(
            update(WorkflowExecution)
            .where(
                (WorkflowExecution.id == execution_id)
                | (WorkflowExecution.parent_execution_id == execution_id)
            )
            .values(status=status)
        )

    async def get_lease(self, lease_id: UUID, *, lock: bool = False) -> RunnerLeaseRecord | None:
        statement = select(RunnerLeaseRecord).where(RunnerLeaseRecord.id == lease_id)
        return await self._one(statement, lock=lock)

    async def expired_leases(self, now: datetime, *, limit: int = 500) -> list[RunnerLeaseRecord]:
        return list(
            (
                await self._session.scalars(
                    select(RunnerLeaseRecord)
                    .where(
                        RunnerLeaseRecord.status == "active",
                        RunnerLeaseRecord.expires_at <= now,
                    )
                    .order_by(
                        RunnerLeaseRecord.runner_id,
                        RunnerLeaseRecord.expires_at,
                        RunnerLeaseRecord.id,
                    )
                    .limit(limit)
                )
            ).all()
        )

    async def list_tasks(self, *, limit: int = 100) -> list[RunnerTask]:
        return list(
            (
                await self._session.scalars(
                    select(RunnerTask).order_by(RunnerTask.created_at.desc()).limit(limit)
                )
            ).all()
        )

    async def list_leases(self, *, limit: int = 100) -> list[RunnerLeaseRecord]:
        return list(
            (
                await self._session.scalars(
                    select(RunnerLeaseRecord)
                    .order_by(RunnerLeaseRecord.acquired_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def list_events(self, *, limit: int = 100) -> list[RunnerEvent]:
        return list(
            (
                await self._session.scalars(
                    select(RunnerEvent).order_by(RunnerEvent.created_at.desc()).limit(limit)
                )
            ).all()
        )

    async def counts(self) -> dict[str, int]:
        pools = await self._count(RunnerPool)
        online = await self._count(Runner, Runner.status == "online")
        offline = await self._count(Runner, Runner.status == "offline")
        draining = await self._count(Runner, Runner.status == "draining")
        queued = await self._count(RunnerTask, RunnerTask.status == "queued")
        active = await self._count(RunnerLeaseRecord, RunnerLeaseRecord.status == "active")
        completed = await self._count(RunnerTask, RunnerTask.status == "completed")
        failed = await self._count(RunnerTask, RunnerTask.status == "failed")
        return {
            "pools": pools,
            "runners_online": online,
            "runners_offline": offline,
            "runners_draining": draining,
            "queued_tasks": queued,
            "active_leases": active,
            "completed_tasks": completed,
            "failed_tasks": failed,
        }

    async def _count(self, model: type[Any], condition: ColumnElement[bool] | None = None) -> int:
        statement = select(func.count()).select_from(model)
        if condition is not None:
            statement = statement.where(condition)
        return int(await self._session.scalar(statement) or 0)

    async def _lock_scope(self, identifier: UUID, *, namespace: int) -> None:
        if self._session.get_bind().dialect.name != "postgresql":
            return
        await self._session.execute(
            select(func.pg_advisory_xact_lock(_advisory_lock_key(identifier, namespace)))
        )

    async def _one[ModelT](self, statement: Select[tuple[ModelT]], *, lock: bool) -> ModelT | None:
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return (await self._session.execute(statement)).scalar_one_or_none()


def _advisory_lock_key(identifier: UUID, namespace: int) -> int:
    unsigned = ((identifier.int >> 64) ^ identifier.int ^ namespace) & ((1 << 64) - 1)
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned
