from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.durable_execution import ExecutionCheckpoint, ExecutionCommand


class DurableExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, model: object) -> None:
        self._session.add(model)

    async def get_command(self, command_id: UUID, *, lock: bool = False) -> ExecutionCommand | None:
        statement = select(ExecutionCommand).where(ExecutionCommand.id == command_id)
        return cast(ExecutionCommand | None, await self._one(statement, lock=lock))

    async def list_commands(self, execution_id: UUID) -> list[ExecutionCommand]:
        return list(
            (
                await self._session.scalars(
                    select(ExecutionCommand)
                    .where(ExecutionCommand.execution_id == execution_id)
                    .order_by(ExecutionCommand.created_at.desc())
                )
            ).all()
        )

    async def get_checkpoint(
        self,
        *,
        execution_id: UUID,
        node_id: str,
        attempt: int,
        lock: bool = False,
    ) -> ExecutionCheckpoint | None:
        statement = select(ExecutionCheckpoint).where(
            ExecutionCheckpoint.execution_id == execution_id,
            ExecutionCheckpoint.node_id == node_id,
            ExecutionCheckpoint.attempt == attempt,
        )
        return cast(ExecutionCheckpoint | None, await self._one(statement, lock=lock))

    async def list_checkpoints(
        self, execution_id: UUID, *, resumable_only: bool = False
    ) -> list[ExecutionCheckpoint]:
        statement = select(ExecutionCheckpoint).where(
            ExecutionCheckpoint.execution_id == execution_id
        )
        if resumable_only:
            statement = statement.where(ExecutionCheckpoint.status.in_(("passed", "skipped")))
        rows = list(
            (
                await self._session.scalars(
                    statement.order_by(ExecutionCheckpoint.node_id, ExecutionCheckpoint.attempt)
                )
            ).all()
        )
        if not resumable_only:
            return rows
        latest: dict[str, ExecutionCheckpoint] = {}
        for row in rows:
            current = latest.get(row.node_id)
            if current is None or row.attempt > current.attempt:
                latest[row.node_id] = row
        return sorted(latest.values(), key=lambda item: item.node_id)

    async def list_checkpoints_for_executions(
        self, execution_ids: Sequence[UUID]
    ) -> dict[UUID, list[ExecutionCheckpoint]]:
        if not execution_ids:
            return {}
        rows = list(
            (
                await self._session.scalars(
                    select(ExecutionCheckpoint)
                    .where(
                        ExecutionCheckpoint.execution_id.in_(execution_ids),
                    )
                    .order_by(ExecutionCheckpoint.execution_id, ExecutionCheckpoint.node_id)
                )
            ).all()
        )
        latest: dict[tuple[UUID, str], ExecutionCheckpoint] = {}
        for row in rows:
            key = (row.execution_id, row.node_id)
            current = latest.get(key)
            if current is None or row.attempt > current.attempt:
                latest[key] = row
        result: dict[UUID, list[ExecutionCheckpoint]] = {}
        for (execution_id, _node_id), row in latest.items():
            result.setdefault(execution_id, []).append(row)
        for items in result.values():
            items.sort(key=lambda item: item.node_id)
        return result

    async def _one(self, statement: Select[Any], *, lock: bool) -> Any | None:
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)
