"""Persisted, time-bounded commands for one workflow iteration-debug session."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.engine.contracts import WorkflowRunStatus
from app.engine.scheduler import ExecutionContext, NodeExecutionError
from app.models.access import User
from app.models.workflow_debug import WorkflowDebugSession
from app.services.audit import AuditService
from app.services.projects import ProjectService

DebugCommand = Literal["step", "continue"]
DEBUG_POLL_SECONDS = 0.25


class WorkflowDebugService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        loop_node_id: str,
        pause_before_index: int,
        pause_on_error: bool,
        max_session_seconds: int,
    ) -> WorkflowDebugSession:
        row = WorkflowDebugSession(
            execution_id=execution_id,
            project_id=project_id,
            target_node_id=loop_node_id,
            pause_before_index=pause_before_index,
            pause_on_error=pause_on_error,
            status="armed",
            pause_reason=None,
            paused_input_index=None,
            last_completed_index=-1,
            step_target_index=None,
            initial_pause_consumed=False,
            expires_at=datetime.now(UTC) + timedelta(seconds=max_session_seconds),
            revision=1,
        )
        self._session.add(row)
        AuditService(self._session).record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.debug_session_created",
            resource_type="workflow_execution",
            resource_id=execution_id,
            details={"loop_node_id": loop_node_id, "pause_before_index": pause_before_index},
        )
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> WorkflowDebugSession:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        row = await self._find(project_id, execution_id)
        if row is None:
            raise _missing_session()
        return row

    async def command(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        action: DebugCommand,
        expected_revision: int,
    ) -> WorkflowDebugSession:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        row = await self._find(project_id, execution_id, lock=True)
        if row is None:
            raise _missing_session()
        if row.revision != expected_revision:
            raise AppError(
                code="DEBUG_SESSION_REVISION_CONFLICT",
                message="调试会话已变化, 请刷新后重试",
                status_code=409,
            )
        if row.status != "paused" or row.paused_input_index is None:
            raise AppError(
                code="DEBUG_SESSION_NOT_PAUSED", message="当前调试会话没有暂停", status_code=409
            )
        if _expired(row):
            row.status = "expired"
            row.revision += 1
            await self._session.commit()
            raise AppError(code="DEBUG_SESSION_EXPIRED", message="调试会话已超时", status_code=409)
        row.step_target_index = (
            row.paused_input_index + (row.pause_reason != "before_iteration")
            if action == "step"
            else None
        )
        row.status = "running"
        row.pause_reason = None
        row.paused_input_index = None
        row.revision += 1
        AuditService(self._session).record(
            actor_user_id=actor.id,
            project_id=project_id,
            action=f"workflow.debug_session_{action}",
            resource_type="workflow_execution",
            resource_id=execution_id,
            details={"revision": row.revision},
        )
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def finish(self, execution_id: UUID, *, execution_status: str) -> None:
        row = await self._session.get(
            WorkflowDebugSession,
            execution_id,
            with_for_update=True,
            populate_existing=True,
        )
        if row is None or row.status in {"expired", "cancelled", "completed"}:
            return
        row.status = "cancelled" if execution_status == "cancelled" else "completed"
        row.pause_reason = None
        row.paused_input_index = None
        row.step_target_index = None
        row.revision += 1
        await self._session.commit()

    async def _find(
        self, project_id: UUID, execution_id: UUID, *, lock: bool = False
    ) -> WorkflowDebugSession | None:
        statement = select(WorkflowDebugSession).where(
            WorkflowDebugSession.execution_id == execution_id,
            WorkflowDebugSession.project_id == project_id,
        )
        if lock:
            statement = statement.with_for_update()
        return cast(WorkflowDebugSession | None, await self._session.scalar(statement))


class DatabaseIterationDebugGate:
    def __init__(self, session_maker: async_sessionmaker[AsyncSession], execution_id: UUID) -> None:
        self._session_maker = session_maker
        self._execution_id = execution_id

    async def before_iteration(
        self,
        *,
        owner_node_id: str,
        input_index: int,
        scope: tuple[str, ...],
        context: ExecutionContext,
    ) -> None:
        del scope
        async with self._session_maker() as session:
            row = await session.get(WorkflowDebugSession, self._execution_id, with_for_update=True)
            if row is None or row.target_node_id != owner_node_id:
                return
            await _check_deadline(session, row)
            if input_index <= row.last_completed_index:
                return
            if row.status == "armed" and not row.initial_pause_consumed:
                if input_index == row.pause_before_index:
                    _pause(row, input_index, "before_iteration")
                    row.initial_pause_consumed = True
                    await session.commit()
                else:
                    return
            if row.status != "paused":
                return
        await self._wait(context)

    async def after_iteration(
        self,
        *,
        owner_node_id: str,
        input_index: int,
        scope: tuple[str, ...],
        context: ExecutionContext,
        status: WorkflowRunStatus,
    ) -> None:
        del scope
        async with self._session_maker() as session:
            row = await session.get(WorkflowDebugSession, self._execution_id, with_for_update=True)
            if row is None or row.target_node_id != owner_node_id:
                return
            await _check_deadline(session, row)
            if input_index <= row.last_completed_index:
                should_wait = row.status == "paused" and row.paused_input_index == input_index
            else:
                row.last_completed_index = input_index
                reason = _pause_after_reason(row, status, input_index)
                if reason is not None:
                    _pause(row, input_index, reason)
                await session.commit()
                should_wait = reason is not None
        if should_wait:
            await self._wait(context)

    async def _wait(self, context: ExecutionContext) -> None:
        while True:
            if context.cancellation is not None and context.cancellation.cancelled:
                return
            async with self._session_maker() as session:
                row = await session.get(
                    WorkflowDebugSession, self._execution_id, with_for_update=True
                )
                if row is None:
                    raise NodeExecutionError(code="DEBUG_SESSION_MISSING", message="调试会话不存在")
                await _check_deadline(session, row)
                if row.status == "running":
                    return
                if row.status != "paused":
                    raise NodeExecutionError(code="DEBUG_SESSION_STOPPED", message="调试会话已停止")
            await asyncio.sleep(DEBUG_POLL_SECONDS)


def _pause(row: WorkflowDebugSession, input_index: int, reason: str) -> None:
    row.status = "paused"
    row.pause_reason = reason
    row.paused_input_index = input_index
    row.step_target_index = None
    row.revision += 1


def _pause_after_reason(
    row: WorkflowDebugSession, status: WorkflowRunStatus, input_index: int
) -> str | None:
    if row.pause_on_error and status is WorkflowRunStatus.FAILED:
        return "error"
    if row.step_target_index == input_index:
        return "step_completed"
    return None


async def _check_deadline(session: AsyncSession, row: WorkflowDebugSession) -> None:
    if row.status in {"completed", "cancelled", "expired"}:
        raise NodeExecutionError(code="DEBUG_SESSION_STOPPED", message="调试会话已停止")
    if not _expired(row):
        return
    row.status = "expired"
    row.revision += 1
    await session.commit()
    raise NodeExecutionError(code="DEBUG_SESSION_EXPIRED", message="调试会话已超时")


def _expired(row: WorkflowDebugSession) -> bool:
    deadline = row.expires_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return datetime.now(UTC) >= deadline


def _missing_session() -> AppError:
    return AppError(code="DEBUG_SESSION_NOT_FOUND", message="调试会话不存在", status_code=404)
