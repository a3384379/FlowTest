"""Application boundary for durable commands and redacted execution checkpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import redact
from app.domain.durable_execution import (
    ExecutionCommandType,
    checkpoint_output_digest,
    json_object,
    request_hash,
)
from app.engine.contracts import NodeStatus, NodeType, WorkflowPhase
from app.engine.results import NodeResult
from app.engine.scheduler import NodeRunRecord
from app.models.access import User
from app.models.durable_execution import ExecutionCheckpoint, ExecutionCommand
from app.models.workflows import WorkflowExecution
from app.repositories.durable_execution import DurableExecutionRepository
from app.schemas.runner_fabric import RunnerCheckpointRequest, RunnerCheckpointResume
from app.services.audit import AuditService
from app.services.projects import ProjectService


class DurableExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = DurableExecutionRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_start_command(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        actor_key: str,
        idempotency_key: str | None,
        payload: dict[str, JsonValue],
    ) -> ExecutionCommand:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        command = self._new_command(
            actor=actor,
            project_id=project_id,
            execution_id=execution_id,
            command_type=ExecutionCommandType.START,
            actor_key=actor_key,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        self._repository.add(command)
        self._audit_command(command, actor.id, "execution.command.accepted")
        await self._session.commit()
        await self._session.refresh(command)
        return command

    async def prepare_recovery_command(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        command_type: ExecutionCommandType,
        actor_key: str,
        idempotency_key: str | None,
        payload: dict[str, JsonValue],
    ) -> tuple[ExecutionCommand, WorkflowExecution]:
        if command_type not in {ExecutionCommandType.RESUME, ExecutionCommandType.RETRY}:
            raise AppError(
                code="EXECUTION_COMMAND_INVALID",
                message="当前接口只支持 Resume 或 Retry Command",
                status_code=422,
            )
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        execution = await self._session.scalar(
            select(WorkflowExecution)
            .where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.project_id == project_id,
            )
            .with_for_update()
        )
        if execution is None:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND", message="执行不存在", status_code=404
            )
        if execution.status in {"queued", "running"}:
            raise AppError(
                code="EXECUTION_ALREADY_ACTIVE",
                message="执行仍在运行中, 不能重复 Resume 或 Retry",
                status_code=409,
            )
        if execution.status not in {"failed", "cancelled"}:
            raise AppError(
                code="EXECUTION_NOT_RECOVERABLE",
                message="只有失败或取消的执行可以 Resume 或 Retry",
                status_code=409,
            )
        command = self._new_command(
            actor=actor,
            project_id=project_id,
            execution_id=execution_id,
            command_type=command_type,
            actor_key=actor_key,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        execution.status = "running"
        execution.error_code = None
        execution.error_message = None
        execution.cancel_requested_at = None
        execution.completed_at = None
        self._repository.add(command)
        self._audit_command(command, actor.id, "execution.command.accepted")
        await self._session.commit()
        await self._session.refresh(command)
        await self._session.refresh(execution)
        return command, execution

    async def mark_dispatched(self, command_id: UUID, *, fencing_token: int | None = None) -> None:
        command = await self._repository.get_command(command_id, lock=True)
        if command is None:
            raise AppError(
                code="EXECUTION_COMMAND_NOT_FOUND",
                message="Execution Command 不存在",
                status_code=404,
            )
        command.status = "dispatched"
        command.dispatched_at = datetime.now(UTC)
        command.fencing_token = fencing_token
        await self._session.commit()

    async def mark_failed(self, command_id: UUID, *, error_code: str, error_message: str) -> None:
        command = await self._repository.get_command(command_id, lock=True)
        if command is None:
            return
        command.status = "failed"
        command.error_code = error_code
        command.error_message = error_message
        command.completed_at = datetime.now(UTC)
        execution = await self._session.scalar(
            select(WorkflowExecution)
            .where(WorkflowExecution.id == command.execution_id)
            .with_for_update()
        )
        if execution is not None and execution.status in {"queued", "running"}:
            execution.status = "failed"
            execution.error_code = error_code
            execution.error_message = error_message
            execution.completed_at = command.completed_at
            children = list(
                (
                    await self._session.scalars(
                        select(WorkflowExecution)
                        .where(
                            WorkflowExecution.parent_execution_id == execution.id,
                            WorkflowExecution.status.in_(("queued", "running")),
                        )
                        .with_for_update()
                    )
                ).all()
            )
            for child in children:
                child.status = "failed"
                child.error_code = error_code
                child.error_message = error_message
                child.completed_at = command.completed_at
        self._audit.record(
            actor_user_id=command.created_by_id,
            project_id=command.project_id,
            action="execution.command.dispatch_failed",
            resource_type="execution_command",
            resource_id=command.id,
            details={"execution_id": str(command.execution_id), "error_code": error_code},
        )
        await self._session.commit()

    async def reset_retry_budget(self, execution_id: UUID) -> bool:
        command = await self._repository.latest_recovery_command(execution_id)
        return command is not None and command.command_type == ExecutionCommandType.RETRY.value

    async def mark_execution_command_completed(
        self, execution_id: UUID, *, execution_status: str
    ) -> None:
        command = await self._session.scalar(
            select(ExecutionCommand)
            .where(
                ExecutionCommand.execution_id == execution_id,
                ExecutionCommand.status == "dispatched",
            )
            .order_by(ExecutionCommand.created_at.desc())
            .with_for_update()
        )
        if command is None:
            return
        command.status = "completed"
        command.completed_at = datetime.now(UTC)
        command.response_body = {"execution_id": str(execution_id), "status": execution_status}
        await self._session.commit()

    async def record_checkpoint(
        self,
        *,
        project_id: UUID,
        lease_id: UUID | None,
        runner_id: UUID | None,
        actor_user_id: UUID | None,
        payload: RunnerCheckpointRequest,
    ) -> ExecutionCheckpoint:
        if payload.status in {NodeStatus.PENDING, NodeStatus.RUNNING}:
            raise AppError(
                code="EXECUTION_CHECKPOINT_NOT_TERMINAL",
                message="Checkpoint 必须记录节点终态",
                status_code=422,
            )
        execution = await self._session.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.id == payload.execution_id,
                WorkflowExecution.project_id == project_id,
            )
        )
        if execution is None:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND", message="执行不存在", status_code=404
            )
        redacted_output = cast(JsonValue, redact(payload.output))
        redacted_result = json_object(redact(payload.result.model_dump(mode="json")))
        redacted_variables = json_object(redact(payload.extracted_variables))
        existing = await self._repository.get_checkpoint(
            execution_id=payload.execution_id,
            node_id=payload.node_id,
            attempt=payload.attempts,
            lock=True,
        )
        output_digest = checkpoint_output_digest(redacted_output)
        if existing is not None:
            if existing.input_hash != payload.input_hash or existing.output_digest != output_digest:
                raise AppError(
                    code="EXECUTION_CHECKPOINT_CONFLICT",
                    message="同一节点 Attempt 的 Checkpoint 内容不一致",
                    status_code=409,
                )
            await self._session.commit()
            return existing
        checkpoint = ExecutionCheckpoint(
            project_id=project_id,
            execution_id=payload.execution_id,
            node_id=payload.node_id,
            node_type=payload.node_type.value,
            node_name=payload.name,
            phase=payload.phase.value,
            best_effort=payload.best_effort,
            attempt=payload.attempts,
            input_hash=payload.input_hash,
            status=payload.status.value,
            output_digest=output_digest,
            output=redacted_output,
            result=redacted_result,
            extracted_variables=redacted_variables,
            started_at=payload.started_at,
            finished_at=payload.finished_at,
            snapshot_revision=payload.snapshot_revision,
            fencing_token=payload.fencing_token,
            lease_id=lease_id,
            runner_id=runner_id,
        )
        self._repository.add(checkpoint)
        self._audit.record(
            actor_user_id=actor_user_id,
            project_id=project_id,
            action="execution.checkpoint.recorded",
            resource_type="execution_checkpoint",
            resource_id=checkpoint.id,
            details={
                "execution_id": str(payload.execution_id),
                "node_id": payload.node_id,
                "status": payload.status.value,
                "phase": payload.phase.value,
                "attempt": payload.attempts,
                "output_digest": output_digest,
                "fencing_token": payload.fencing_token,
            },
        )
        await self._session.commit()
        await self._session.refresh(checkpoint)
        return checkpoint

    async def list_checkpoints(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> list[ExecutionCheckpoint]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        execution = await self._session.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.project_id == project_id,
            )
        )
        if execution is None:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND", message="执行不存在", status_code=404
            )
        return await self._repository.list_checkpoints(execution_id)

    async def list_commands(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> list[ExecutionCommand]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        execution = await self._session.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.project_id == project_id,
            )
        )
        if execution is None:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND", message="执行不存在", status_code=404
            )
        return await self._repository.list_commands(execution_id)

    async def checkpoint_history(
        self, execution_ids: list[UUID]
    ) -> dict[UUID, list[ExecutionCheckpoint]]:
        return await self._repository.list_checkpoints_for_executions(execution_ids)

    def _new_command(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        command_type: ExecutionCommandType,
        actor_key: str,
        idempotency_key: str | None,
        payload: dict[str, JsonValue],
    ) -> ExecutionCommand:
        now = datetime.now(UTC)
        return ExecutionCommand(
            project_id=project_id,
            execution_id=execution_id,
            command_type=command_type.value,
            status="accepted",
            actor_key=actor_key,
            idempotency_key=idempotency_key,
            request_hash=request_hash(payload),
            payload=payload,
            response_body=None,
            error_code=None,
            error_message=None,
            fencing_token=None,
            created_by_id=actor.id,
            accepted_at=now,
            dispatched_at=None,
            completed_at=None,
        )

    def _audit_command(self, command: ExecutionCommand, actor_id: UUID, action: str) -> None:
        self._audit.record(
            actor_user_id=actor_id,
            project_id=command.project_id,
            action=action,
            resource_type="execution_command",
            resource_id=command.id,
            details={
                "execution_id": str(command.execution_id),
                "command_type": command.command_type,
                "request_hash": command.request_hash,
                "idempotency_key_present": command.idempotency_key is not None,
            },
        )


def checkpoint_to_node_record(checkpoint: ExecutionCheckpoint) -> NodeRunRecord:
    return NodeRunRecord(
        node_id=checkpoint.node_id,
        node_type=NodeType(checkpoint.node_type),
        name=checkpoint.node_name,
        status=NodeStatus(checkpoint.status),
        attempts=checkpoint.attempt,
        output=cast(JsonValue, checkpoint.output),
        result=NodeResult.model_validate(checkpoint.result),
        error_code=_optional_string(checkpoint.result.get("error"), "code"),
        error_message=_optional_string(checkpoint.result.get("error"), "message"),
        started_at=_as_utc(checkpoint.started_at),
        completed_at=_required_utc(checkpoint.finished_at),
        input_hash=checkpoint.input_hash,
        phase=WorkflowPhase(checkpoint.phase),
        best_effort=checkpoint.best_effort,
    )


def checkpoint_to_runner_resume(checkpoint: ExecutionCheckpoint) -> RunnerCheckpointResume:
    record = checkpoint_to_node_record(checkpoint)
    return RunnerCheckpointResume(
        node_id=record.node_id,
        node_type=record.node_type,
        name=record.name,
        status=record.status,
        attempts=record.attempts,
        output=record.output,
        result=record.result,
        error_code=record.error_code,
        error_message=record.error_message,
        started_at=record.started_at,
        completed_at=record.completed_at,
        input_hash=record.input_hash or checkpoint.input_hash,
        extracted_variables=cast(dict[str, JsonValue], checkpoint.extracted_variables),
        phase=record.phase,
        best_effort=record.best_effort,
    )


def _optional_string(value: object, key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    candidate = value.get(key)
    return candidate if isinstance(candidate, str) else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _required_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
