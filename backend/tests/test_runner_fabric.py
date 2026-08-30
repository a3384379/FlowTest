import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request as StarletteRequest

from app.api.dependencies import get_current_user
from app.api.v1.endpoints.runner_fabric import _validate_result_size
from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.durable_execution import ExecutionCommandType
from app.domain.network import OutboundNetworkPolicy
from app.domain.runner_fabric import RunnerProfile, normalize_labels
from app.engine.contracts import NodeStatus, NodeType, WorkflowDefinition
from app.engine.results import NodeResult
from app.engine.scheduler import CancellationToken, NodeStatusUpdate
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.durable_execution import ExecutionCommand
from app.models.runner_fabric import RunnerLeaseRecord, RunnerTask
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution
from app.repositories.durable_execution import DurableExecutionRepository
from app.repositories.runner_fabric import _advisory_lock_key
from app.runner.agent import (
    RunnerAgent,
    _checkpoint_payload,
    _read_runner_token,
    _retryable_control_plane_error,
    configuration_from_environment,
)
from app.runner.client import RunnerControlPlaneClient
from app.runner.results import RunnerExecutionResult
from app.runner.workflow import PreviewRuntimeBudgetExceeded, RemoteWorkflowExecutor
from app.schemas.runner_fabric import (
    RunnerAgentConfiguration,
    RunnerCheckpointRequest,
    RunnerCompleteRequest,
    RunnerFailRequest,
    RunnerHeartbeatRequest,
    RunnerLeaseResponse,
    RunnerLeaseTaskResponse,
    RunnerPoolCreate,
    RunnerPoolUpdate,
    RunnerProgressRequest,
    RunnerRegisterRequest,
)
from app.services.durable_execution import (
    DurableExecutionService,
    _optional_string,
    checkpoint_to_node_record,
    checkpoint_to_runner_resume,
)
from app.services.execution_events import InProcessExecutionEventBus
from app.services.runner_fabric import RunnerFabricService
from app.services.workflow_coordinator import WorkflowRunCoordinator
from app.services.workflow_plan_codec import encode_execution_plan
from app.services.workflow_snapshots import PreparedExecution
from app.services.workflows import WorkflowBatchPlan, WorkflowRunPlan, WorkflowService


def test_pool_advisory_lock_key_is_stable_and_signed() -> None:
    identifier = UUID("ffffffff-ffff-ffff-0000-000000000000")

    assert _advisory_lock_key(identifier, 0) == -1
    assert _advisory_lock_key(identifier, 1) != _advisory_lock_key(identifier, 2)


@dataclass(slots=True)
class FabricApiContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    actor: User


@pytest.fixture
async def fabric_api_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FabricApiContext]:
    monkeypatch.setattr(settings, "feature_runner_fabric_enabled", True)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        actor, _project = await _seed_actor_and_project(session)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    async def override_user() -> User:
        return actor

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield FabricApiContext(client=client, sessions=sessions, actor=actor)
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def fabric_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "feature_runner_fabric_enabled", True)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_profile_drain_and_one_time_tokens(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, _project = await _seed_actor_and_project(session)
        actor_id = actor.id
        service = RunnerFabricService(session, enabled=True)
        pool = await service.create_pool(actor=actor, payload=_pool_payload(labels=["arm64"]))
        registration, raw_registration = await service.create_registration_token(
            actor=actor, pool_id=pool.id, expires_in_seconds=300
        )
        registered = await service.register(
            registration_token=raw_registration,
            payload=_runner_payload("runner-a", "instance-runner-a", labels=["arm64"]),
        )

        assert registration.consumed_at is not None
        assert registered.token.startswith("ftrun_")
        with pytest.raises(AppError, match="注册令牌无效"):
            await service.register(
                registration_token=raw_registration,
                payload=_runner_payload("runner-b", "instance-runner-b", labels=["arm64"]),
            )
        await session.rollback()
        actor = await session.get(User, actor_id)
        assert actor is not None

        heartbeat = await service.heartbeat(
            runner_token=registered.token,
            payload=RunnerHeartbeatRequest(current_load=0),
        )
        assert heartbeat.status == "online"
        drained = await service.runner_action(
            actor=actor, runner_id=registered.runner_id, action="drain"
        )
        assert drained.status == "draining"
        assert await service.claim(runner_token=registered.token) is None
        resumed = await service.runner_action(
            actor=actor, runner_id=registered.runner_id, action="resume"
        )
        assert resumed.status == "online"


@pytest.mark.asyncio
async def test_expired_lease_requeues_and_old_fence_cannot_duplicate_terminal_state(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, project = await _seed_actor_and_project(session)
        plan, execution = await _seed_execution_plan(session, actor, project)
        execution_id = execution.id
        service = RunnerFabricService(session, enabled=True)
        pool = await service.create_pool(actor=actor, payload=_pool_payload())
        first_token = await _register_runner(service, actor, pool.id, "runner-a")
        second_token = await _register_runner(service, actor, pool.id, "runner-b")
        await service.enqueue(plan)

        first = await service.claim(runner_token=first_token)
        assert first is not None
        result = await RemoteWorkflowExecutor().execute(
            plan,
            network_policy=OutboundNetworkPolicy(),
            cancellation=CancellationToken(),
        )
        result_record = result.result.records[0]
        checkpoint = RunnerCheckpointRequest(
            execution_id=execution.id,
            node_id=result_record.node_id,
            node_type=result_record.node_type,
            name=result_record.name,
            status=result_record.status,
            attempts=max(1, result_record.attempts),
            output=result_record.output,
            result=result_record.result,
            error_code=result_record.error_code,
            error_message=result_record.error_message,
            started_at=result_record.started_at,
            finished_at=result_record.completed_at,
            input_hash=result_record.input_hash or "0" * 64,
            fencing_token=first.task.fencing_token,
        )
        acknowledged = await service.checkpoint(
            runner_token=first_token,
            lease_id=first.lease_id,
            payload=checkpoint,
        )
        assert acknowledged.task_status == "leased"
        first_lease = await session.get(RunnerLeaseRecord, first.lease_id)
        assert first_lease is not None
        first_lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        second = await service.claim(runner_token=second_token)
        assert second is not None
        assert second.task.fencing_token == first.task.fencing_token + 1
        assert second.task.attempt == 2
        assert [item.node_id for item in second.task.resume_checkpoints[str(execution.id)]] == [
            "start"
        ]

        with pytest.raises(AppError) as stale_checkpoint:
            await service.checkpoint(
                runner_token=first_token,
                lease_id=first.lease_id,
                payload=checkpoint,
            )
        assert stale_checkpoint.value.code == "RUNNER_LEASE_FENCED"

        with pytest.raises(AppError) as fenced:
            await service.complete(
                runner_token=first_token,
                lease_id=first.lease_id,
                fencing_token=first.task.fencing_token,
                result=result,
            )
        assert fenced.value.code == "RUNNER_LEASE_FENCED"
        await session.rollback()

        completed = await service.complete(
            runner_token=second_token,
            lease_id=second.lease_id,
            fencing_token=second.task.fencing_token,
            result=result,
        )
        repeated = await service.complete(
            runner_token=second_token,
            lease_id=second.lease_id,
            fencing_token=second.task.fencing_token,
            result=result,
        )

        assert completed.task_status == "completed"
        assert repeated.task_status == "completed"
        await session.refresh(execution)
        assert execution.status == "passed"
        task = await session.scalar(
            select(RunnerTask).where(RunnerTask.execution_id == execution_id)
        )
        assert task is not None
        assert task.status == "completed"
        leases = list(
            (
                await session.scalars(
                    select(RunnerLeaseRecord).where(RunnerLeaseRecord.task_id == task.id)
                )
            ).all()
        )
        assert [lease.status for lease in leases] == ["expired", "completed"]
        nodes = list(
            (
                await session.scalars(
                    select(WorkflowNodeExecution).where(
                        WorkflowNodeExecution.workflow_execution_id == execution.id
                    )
                )
            ).all()
        )
        assert {node.node_id for node in nodes} == {"start", "end"}
        assert len(nodes) == 2


@pytest.mark.asyncio
async def test_durable_command_and_checkpoint_edge_cases(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, project = await _seed_actor_and_project(session)
        _plan, execution = await _seed_execution_plan(session, actor, project)
        execution_id = execution.id
        durable = DurableExecutionService(session)
        coordinator = WorkflowRunCoordinator(
            fabric_sessions, InProcessExecutionEventBus(retention_seconds=60)
        )
        failed_runtime = await coordinator._mark_failed(_plan)
        assert failed_runtime.status == "failed"

        with pytest.raises(AppError) as invalid_command:
            await durable.prepare_recovery_command(
                actor=actor,
                project_id=project.id,
                execution_id=execution.id,
                command_type=ExecutionCommandType.START,
                actor_key="user:test",
                idempotency_key=None,
                payload={},
            )
        assert invalid_command.value.code == "EXECUTION_COMMAND_INVALID"

        with pytest.raises(AppError) as missing_execution:
            await durable.prepare_recovery_command(
                actor=actor,
                project_id=project.id,
                execution_id=uuid4(),
                command_type=ExecutionCommandType.RESUME,
                actor_key="user:test",
                idempotency_key=None,
                payload={},
            )
        assert missing_execution.value.code == "WORKFLOW_EXECUTION_NOT_FOUND"

        execution.status = "queued"
        await session.commit()
        with pytest.raises(AppError) as active_execution:
            await durable.prepare_recovery_command(
                actor=actor,
                project_id=project.id,
                execution_id=execution.id,
                command_type=ExecutionCommandType.RESUME,
                actor_key="user:test",
                idempotency_key=None,
                payload={},
            )
        assert active_execution.value.code == "EXECUTION_ALREADY_ACTIVE"

        execution.status = "passed"
        await session.commit()
        with pytest.raises(AppError) as completed_execution:
            await durable.prepare_recovery_command(
                actor=actor,
                project_id=project.id,
                execution_id=execution.id,
                command_type=ExecutionCommandType.RESUME,
                actor_key="user:test",
                idempotency_key=None,
                payload={},
            )
        assert completed_execution.value.code == "EXECUTION_NOT_RECOVERABLE"

        execution.status = "failed"
        await session.commit()
        command = await durable.create_start_command(
            actor=actor,
            project_id=project.id,
            execution_id=execution.id,
            actor_key="user:test",
            idempotency_key=None,
            payload={},
        )
        execution.status = "running"
        await session.commit()
        await durable.mark_failed(
            command.id,
            error_code="WORKER_CRASHED",
            error_message="worker stopped",
        )
        failed_command = await session.get(ExecutionCommand, command.id)
        assert failed_command is not None
        assert failed_command.status == "failed"
        await session.refresh(execution)
        assert execution.status == "failed"
        assert execution.error_code == "WORKER_CRASHED"

        execution.status = "cancelled"
        execution.cancel_requested_at = datetime.now(UTC)
        execution.force_cancel_requested_at = datetime.now(UTC)
        execution.force_cancel_reason = "runner did not stop"
        await session.commit()
        recovery, recovered_execution = await durable.prepare_recovery_command(
            actor=actor,
            project_id=project.id,
            execution_id=execution.id,
            command_type=ExecutionCommandType.RESUME,
            actor_key="user:test",
            idempotency_key=None,
            payload={},
        )
        assert recovery.command_type == ExecutionCommandType.RESUME.value
        assert recovered_execution.cancel_requested_at is None
        assert recovered_execution.force_cancel_requested_at is None
        assert recovered_execution.force_cancel_reason is None

        with pytest.raises(AppError) as missing_dispatch:
            await durable.mark_dispatched(uuid4())
        assert missing_dispatch.value.code == "EXECUTION_COMMAND_NOT_FOUND"
        await durable.mark_failed(uuid4(), error_code="MISSING", error_message="missing")

        result = NodeResult.passed({"value": "checkpoint"})
        checkpoint_payload = RunnerCheckpointRequest(
            execution_id=execution.id,
            node_id="start",
            node_type=NodeType.START,
            name="开始",
            status=NodeStatus.PASSED,
            attempts=1,
            output=result.output,
            result=result,
            error_code=None,
            error_message=None,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            input_hash="0" * 64,
            extracted_variables={"safe": "value"},
            snapshot_revision=1,
            fencing_token=0,
        )
        with pytest.raises(AppError) as non_terminal:
            await durable.record_checkpoint(
                project_id=project.id,
                lease_id=None,
                runner_id=None,
                actor_user_id=actor.id,
                payload=checkpoint_payload.model_copy(update={"status": NodeStatus.PENDING}),
            )
        assert non_terminal.value.code == "EXECUTION_CHECKPOINT_NOT_TERMINAL"

        reservation_payload = RunnerCheckpointRequest.model_validate(
            {
                **checkpoint_payload.model_dump(mode="python"),
                "node_id": "reserved-api",
                "node_type": NodeType.API,
                "name": "Reserved API",
                "status": NodeStatus.RUNNING,
                "output": None,
                "result": None,
            }
        )
        reservation = await durable.record_checkpoint(
            project_id=project.id,
            lease_id=None,
            runner_id=None,
            actor_user_id=actor.id,
            payload=reservation_payload,
        )
        assert reservation.status == NodeStatus.RUNNING.value
        resume_reservation = checkpoint_to_runner_resume(reservation)
        assert resume_reservation.result is None
        assert resume_reservation.started_at == reservation_payload.started_at
        finalized_reservation = await durable.record_checkpoint(
            project_id=project.id,
            lease_id=None,
            runner_id=None,
            actor_user_id=actor.id,
            payload=RunnerCheckpointRequest.model_validate(
                {
                    **reservation_payload.model_dump(mode="python"),
                    "status": NodeStatus.PASSED,
                    "output": result.output,
                    "result": result,
                }
            ),
        )
        assert finalized_reservation.id == reservation.id
        assert finalized_reservation.status == NodeStatus.PASSED.value

        zero_attempt = await durable.record_checkpoint(
            project_id=project.id,
            lease_id=None,
            runner_id=None,
            actor_user_id=actor.id,
            payload=RunnerCheckpointRequest.model_validate(
                {
                    **checkpoint_payload.model_dump(mode="python"),
                    "node_id": "not-dispatched",
                    "status": NodeStatus.CANCELLED,
                    "attempts": 0,
                    "output": None,
                    "result": NodeResult(status=NodeStatus.CANCELLED),
                }
            ),
        )
        assert zero_attempt.attempt == 0

        with pytest.raises(AppError) as missing_checkpoint_execution:
            await durable.record_checkpoint(
                project_id=project.id,
                lease_id=None,
                runner_id=None,
                actor_user_id=actor.id,
                payload=checkpoint_payload.model_copy(update={"execution_id": uuid4()}),
            )
        assert missing_checkpoint_execution.value.code == "WORKFLOW_EXECUTION_NOT_FOUND"

        checkpoint = await durable.record_checkpoint(
            project_id=project.id,
            lease_id=None,
            runner_id=None,
            actor_user_id=actor.id,
            payload=checkpoint_payload,
        )
        duplicate = await durable.record_checkpoint(
            project_id=project.id,
            lease_id=None,
            runner_id=None,
            actor_user_id=actor.id,
            payload=checkpoint_payload,
        )
        assert duplicate.id == checkpoint.id
        checkpoint.finished_at = datetime.now(UTC)
        assert checkpoint_to_node_record(checkpoint).status is NodeStatus.PASSED
        assert checkpoint_to_runner_resume(checkpoint).input_hash == "0" * 64
        assert _optional_string({"code": "value"}, "code") == "value"
        assert _optional_string({"code": 1}, "code") is None

        with pytest.raises(AppError) as conflict:
            await durable.record_checkpoint(
                project_id=project.id,
                lease_id=None,
                runner_id=None,
                actor_user_id=actor.id,
                payload=checkpoint_payload.model_copy(update={"input_hash": "1" * 64}),
            )
        assert conflict.value.code == "EXECUTION_CHECKPOINT_CONFLICT"
        await session.rollback()
        await session.refresh(actor)
        await session.refresh(project)

        repository = DurableExecutionRepository(session)
        resumable = await repository.list_checkpoints(execution_id, resumable_only=True)
        assert [item.node_id for item in resumable] == ["reserved-api", "start"]
        assert await repository.list_checkpoints_for_executions([]) == {}
        with pytest.raises(AppError):
            await durable.list_checkpoints(actor=actor, project_id=project.id, execution_id=uuid4())
        with pytest.raises(AppError):
            await durable.list_commands(actor=actor, project_id=project.id, execution_id=uuid4())


@pytest.mark.asyncio
async def test_retry_exhaustion_fails_execution_and_pool_limits_are_guarded(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, project = await _seed_actor_and_project(session)
        plan, execution = await _seed_execution_plan(session, actor, project)
        execution_id = execution.id
        service = RunnerFabricService(session, enabled=True)
        pool = await service.create_pool(actor=actor, payload=_pool_payload(max_concurrency=1))
        token = await _register_runner(service, actor, pool.id, "runner-a")
        await service.enqueue(plan)
        claimed = await service.claim(runner_token=token)
        assert claimed is not None

        with pytest.raises(AppError, match="心跳超时"):
            await service.update_pool(
                actor=actor,
                pool_id=pool.id,
                payload=RunnerPoolUpdate(lease_timeout_seconds=30, heartbeat_timeout_seconds=20),
            )
        await session.rollback()
        task = await session.scalar(
            select(RunnerTask).where(RunnerTask.execution_id == execution_id)
        )
        assert task is not None
        task.max_attempts = task.attempts
        await session.commit()
        failed = await service.fail(
            runner_token=token,
            lease_id=claimed.lease_id,
            payload=RunnerFailRequest(
                fencing_token=claimed.task.fencing_token,
                error_code="WORKER_CRASHED",
                error_message="worker stopped",
                retryable=True,
            ),
        )
        assert failed.task_status == "failed"
        execution = await session.get(WorkflowExecution, execution_id)
        assert execution is not None
        assert execution.status == "failed"
        assert execution.error_code == "WORKER_CRASHED"


@pytest.mark.asyncio
async def test_lease_renew_progress_cancel_and_offline_recovery(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, project = await _seed_actor_and_project(session)
        plan, execution = await _seed_execution_plan(session, actor, project)
        service = RunnerFabricService(session, enabled=True)
        pool = await service.create_pool(actor=actor, payload=_pool_payload())
        token = await _register_runner(service, actor, pool.id, "runner-renew")
        await service.enqueue(plan)
        lease = await service.claim(runner_token=token)
        assert lease is not None

        execution.cancel_requested_at = datetime.now(UTC)
        await session.commit()
        renewed = await service.renew(
            runner_token=token,
            lease_id=lease.lease_id,
            fencing_token=lease.task.fencing_token,
        )
        progressed = await service.progress(
            runner_token=token,
            lease_id=lease.lease_id,
            payload=RunnerProgressRequest(
                fencing_token=lease.task.fencing_token,
                progress_percent=50,
                message="halfway",
            ),
        )
        assert renewed.cancel_requested
        assert progressed.cancel_requested
        assert renewed.expires_at is not None and renewed.expires_at > lease.expires_at

        listed = await service.list_pools(actor=actor)
        runner = listed[0][1][0]
        runner.last_seen_at = datetime.now(UTC) - timedelta(seconds=31)
        await session.commit()
        assert await service.reconcile() == 1
        await session.refresh(runner)
        assert runner.status == "offline"
        recovered = await service.heartbeat(
            runner_token=token,
            payload=RunnerHeartbeatRequest(current_load=1),
        )
        assert recovered.status == "online"


@pytest.mark.asyncio
async def test_expired_final_attempt_is_terminal(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, project = await _seed_actor_and_project(session)
        plan, execution = await _seed_execution_plan(session, actor, project)
        service = RunnerFabricService(session, enabled=True)
        pool = await service.create_pool(actor=actor, payload=_pool_payload())
        token = await _register_runner(service, actor, pool.id, "runner-exhausted")
        await service.enqueue(plan)
        claimed = await service.claim(runner_token=token)
        assert claimed is not None
        task = await session.get(RunnerTask, claimed.task.task_id)
        lease = await session.get(RunnerLeaseRecord, claimed.lease_id)
        assert task is not None and lease is not None
        task.max_attempts = task.attempts
        lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        assert await service.reconcile() == 1
        await session.refresh(task)
        await session.refresh(execution)
        assert task.status == "failed"
        assert task.error_code == "RUNNER_LEASE_EXHAUSTED"
        assert execution.status == "failed"


@pytest.mark.asyncio
async def test_runner_fabric_policy_guards(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, project = await _seed_actor_and_project(session)
        service = RunnerFabricService(session, enabled=True)
        actor.is_system_admin = False
        with pytest.raises(AppError) as forbidden:
            await service.create_pool(actor=actor, payload=_pool_payload())
        assert forbidden.value.code == "SYSTEM_ADMIN_REQUIRED"
        actor.is_system_admin = True

        payload = _pool_payload()
        pool = await service.create_pool(actor=actor, payload=payload)
        with pytest.raises(AppError) as duplicate_pool:
            await service.create_pool(actor=actor, payload=payload)
        assert duplicate_pool.value.code == "RUNNER_POOL_EXISTS"
        with pytest.raises(AppError) as invalid_profile:
            await service.create_pool(
                actor=actor,
                payload=_pool_payload(labels=["arm64", "ARM64"]),
            )
        assert invalid_profile.value.code == "RUNNER_POOL_INVALID"

        pool.enabled = False
        await session.commit()
        with pytest.raises(AppError) as disabled_pool:
            await service.create_registration_token(
                actor=actor, pool_id=pool.id, expires_in_seconds=300
            )
        assert disabled_pool.value.code == "RUNNER_POOL_DISABLED"
        pool.enabled = True
        await session.commit()
        _registration, raw = await service.create_registration_token(
            actor=actor, pool_id=pool.id, expires_in_seconds=300
        )
        with pytest.raises(AppError) as invalid_runner:
            await service.register(
                registration_token=raw,
                payload=_runner_payload(
                    "invalid-labels",
                    "invalid-labels-instance",
                    labels=["arm64", "ARM64"],
                ),
            )
        assert invalid_runner.value.code == "RUNNER_PROFILE_INVALID"
        registered = await service.register(
            registration_token=raw,
            payload=_runner_payload("guard-runner", "guard-runner-instance"),
        )
        _second, second_raw = await service.create_registration_token(
            actor=actor, pool_id=pool.id, expires_in_seconds=300
        )
        with pytest.raises(AppError) as duplicate_identity:
            await service.register(
                registration_token=second_raw,
                payload=_runner_payload("guard-runner-copy", "guard-runner-instance"),
            )
        assert duplicate_identity.value.code == "RUNNER_IDENTITY_EXISTS"
        with pytest.raises(AppError) as invalid_load:
            await service.heartbeat(
                runner_token=registered.token,
                payload=RunnerHeartbeatRequest(current_load=2),
            )
        assert invalid_load.value.code == "RUNNER_LOAD_INVALID"

        await service.runner_action(actor=actor, runner_id=registered.runner_id, action="disable")
        with pytest.raises(AppError) as disabled_runner:
            await service.runner_action(
                actor=actor, runner_id=registered.runner_id, action="resume"
            )
        assert disabled_runner.value.code == "RUNNER_DISABLED"

        plan, _execution = await _seed_execution_plan(session, actor, project)
        await service.enqueue(plan)
        with pytest.raises(AppError) as duplicate_task:
            await service.enqueue(plan)
        assert duplicate_task.value.code == "RUNNER_TASK_EXISTS"
        with pytest.raises(AppError) as missing_project:
            await service.enqueue(replace(plan, project_id=uuid4()))
        assert missing_project.value.code == "PROJECT_NOT_FOUND"
        project.queued_run_limit = 1
        await session.commit()
        second_plan, _second_execution = await _seed_execution_plan(session, actor, project)
        with pytest.raises(AppError) as queue_full:
            await service.enqueue(second_plan)
        assert queue_full.value.code == "PROJECT_QUEUE_EXCEEDED"

        with pytest.raises(AppError) as disabled:
            await RunnerFabricService(session, enabled=False).overview(actor=actor)
        assert disabled.value.code == "RUNNER_FABRIC_DISABLED"


@pytest.mark.asyncio
async def test_runner_lease_carries_project_outbound_policy_toggle(
    fabric_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with fabric_sessions() as session:
        actor, project = await _seed_actor_and_project(session)
        project.outbound_policy_enabled = False
        await session.commit()
        plan, _execution = await _seed_execution_plan(session, actor, project)
        service = RunnerFabricService(session, enabled=True)
        pool = await service.create_pool(actor=actor, payload=_pool_payload())
        token = await _register_runner(service, actor, pool.id, "runner-policy-toggle")
        await service.enqueue(plan)

        lease = await service.claim(runner_token=token)

        assert lease is not None
        assert lease.task.outbound_policy_enabled is False


def test_runner_profile_and_production_transport_are_strict() -> None:
    assert normalize_labels(["ARM64", "zone.cn"]) == ("arm64", "zone.cn")
    with pytest.raises(ValueError, match="unique"):
        normalize_labels(["arm64", "ARM64"])
    with pytest.raises(ValidationError, match="heartbeat timeout"):
        RunnerProfile(
            runner_type="general",
            runtime="docker",
            network_zone="default",
            capabilities=("flow.workflow",),
            max_concurrency=1,
            lease_seconds=30,
            heartbeat_timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_runner_fabric_admin_and_agent_api(
    fabric_api_context: FabricApiContext,
) -> None:
    client = fabric_api_context.client
    overview = await client.get("/api/v1/execution-fabric/overview")
    assert overview.status_code == 200
    assert overview.json()["pools"] == 0

    created = await client.post(
        "/api/v1/execution-fabric/pools",
        json=_pool_payload(labels=["arm64"]).model_dump(mode="json"),
    )
    assert created.status_code == 201, created.text
    pool = created.json()
    listed = await client.get("/api/v1/execution-fabric/pools")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["runtime"] == "docker"
    updated = await client.patch(
        f"/api/v1/execution-fabric/pools/{pool['id']}",
        json={"max_concurrency": 12},
    )
    assert updated.status_code == 200
    assert updated.json()["max_concurrency"] == 12

    token_response = await client.post(
        f"/api/v1/execution-fabric/pools/{pool['id']}/registration-tokens",
        json={"expires_in_seconds": 300},
    )
    assert token_response.status_code == 201
    registration_token = token_response.json()["token"]
    invalid_registration = await client.post(
        "/api/v1/runner-control/register",
        headers={"Authorization": "Bearer invalid"},
        json=_runner_payload(
            "api-runner-invalid", "api-runner-invalid-instance", labels=["arm64"]
        ).model_dump(mode="json"),
    )
    assert invalid_registration.status_code == 401
    registered = await client.post(
        "/api/v1/runner-control/register",
        headers={"Authorization": f"Bearer {registration_token}"},
        json=_runner_payload("api-runner", "api-runner-instance-0001", labels=["arm64"]).model_dump(
            mode="json"
        ),
    )
    assert registered.status_code == 201, registered.text
    runner_token = registered.json()["token"]
    runner_id = registered.json()["runner_id"]

    heartbeat = await client.post(
        "/api/v1/runner-control/heartbeat",
        headers={"Authorization": f"Bearer {runner_token}"},
        json={"current_load": 0},
    )
    assert heartbeat.status_code == 200
    claim = await client.post(
        "/api/v1/runner-control/leases/claim",
        headers={"Authorization": f"Bearer {runner_token}"},
    )
    assert claim.status_code == 200
    assert claim.json() is None
    for action, expected in (("drain", "draining"), ("resume", "online")):
        response = await client.post(
            f"/api/v1/execution-fabric/runners/{runner_id}/actions",
            json={"action": action},
        )
        assert response.status_code == 200
        assert response.json()["status"] == expected
    for resource in ("tasks", "leases", "events"):
        response = await client.get(f"/api/v1/execution-fabric/{resource}?limit=20")
        assert response.status_code == 200
        assert response.json()["page_size"] == 20
        oversized = await client.get(f"/api/v1/execution-fabric/{resource}?limit=101")
        assert oversized.status_code == 422
    disabled = await client.post(
        f"/api/v1/execution-fabric/runners/{runner_id}/actions",
        json={"action": "disable"},
    )
    assert disabled.json()["status"] == "disabled"
    rejected = await client.post(
        "/api/v1/runner-control/heartbeat",
        headers={"Authorization": f"Bearer {runner_token}"},
        json={"current_load": 0},
    )
    assert rejected.status_code == 401


@pytest.mark.asyncio
async def test_runner_control_plane_http_client_covers_full_protocol(tmp_path: Path) -> None:
    plan = _plan_fixture()
    result = await RemoteWorkflowExecutor().execute(
        plan,
        network_policy=OutboundNetworkPolicy(),
        cancellation=CancellationToken(),
    )
    lease = _lease_fixture(plan)
    calls: list[Request] = []
    claim_count = 0

    async def handler(request: Request) -> Response:
        nonlocal claim_count
        calls.append(request)
        if request.url.path.endswith("/register"):
            return Response(
                201,
                json={
                    "runner_id": str(lease.runner_id),
                    "pool_id": str(uuid4()),
                    "token": "ftrun_runner-client-token-that-is-long-enough",
                    "lease_timeout_seconds": 30,
                    "heartbeat_timeout_seconds": 90,
                },
            )
        if request.url.path.endswith("/heartbeat"):
            return Response(200, json={})
        if request.url.path.endswith("/claim"):
            claim_count += 1
            if claim_count == 1:
                return Response(200, json=lease.model_dump(mode="json"))
            return Response(200, content=b"null", headers={"content-type": "application/json"})
        return Response(
            200,
            json={"accepted": True, "task_status": "leased", "cancel_requested": False},
        )

    transport = httpx.MockTransport(handler)
    async with AsyncClient(transport=transport, base_url="http://control") as http_client:
        configuration = _agent_configuration(
            registration_token="ftrreg_client-registration-token-that-is-long-enough",
            runner_token_file=str(tmp_path / "runner" / "identity-token"),
        )
        client = RunnerControlPlaneClient(configuration, client=http_client)
        registration = await client.connect()
        assert registration is not None
        await client.heartbeat(1)
        assert await client.claim() == lease
        assert await client.claim() is None
        renewed = await client.renew(lease.lease_id, lease.task.fencing_token)
        assert renewed.accepted
        progressed = await client.progress(lease.lease_id, lease.task.fencing_token, 50, "running")
        assert progressed.task_status == "leased"
        record = result.result.records[0]
        checkpoint = RunnerCheckpointRequest(
            execution_id=lease.task.execution_id,
            node_id=record.node_id,
            node_type=record.node_type,
            name=record.name,
            status=record.status,
            attempts=max(1, record.attempts),
            output=record.output,
            result=record.result,
            error_code=record.error_code,
            error_message=record.error_message,
            started_at=record.started_at,
            finished_at=record.completed_at,
            input_hash=record.input_hash or "0" * 64,
            fencing_token=lease.task.fencing_token,
        )
        checkpoint_ack = await client.checkpoint(lease.lease_id, checkpoint)
        assert checkpoint_ack.task_status == "leased"
        await client.complete(lease.lease_id, lease.task.fencing_token, result)
        await client.fail(
            lease.lease_id,
            lease.task.fencing_token,
            error_code="RUNNER_TEST",
            error_message="failure",
            retryable=False,
        )
        await client.close()
    assert (tmp_path / "runner" / "identity-token").read_text() == (
        "ftrun_runner-client-token-that-is-long-enough"
    )
    assert all(request.headers["authorization"].startswith("Bearer ftr") for request in calls)


@pytest.mark.asyncio
async def test_runner_agent_executes_claim_and_reports_digest_failure() -> None:
    plan = _plan_fixture()
    lease = _lease_fixture(plan)
    control = FakeControlPlane(leases=[lease])
    agent = RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=control
    )
    control.stop = agent.stop

    await asyncio.wait_for(agent.run(), timeout=2)

    assert control.connected == 1
    assert control.completed == [lease.lease_id]
    assert [item.node_id for item in control.checkpoints] == ["start", "end"]
    assert all(len(item.input_hash) == 64 for item in control.checkpoints)
    assert control.closed == 1
    bad_lease = lease.model_copy(
        update={"task": lease.task.model_copy(update={"plan_sha256": "0" * 64})}
    )
    await agent._execute(bad_lease)
    assert control.failed == [bad_lease.lease_id]


@pytest.mark.asyncio
async def test_runner_agent_reports_batch_checkpoints_for_actual_child_executions() -> None:
    first = _plan_fixture()
    second = replace(first, execution_id=uuid4())
    batch = WorkflowBatchPlan(
        execution_id=uuid4(),
        actor_id=first.actor_id,
        project_id=first.project_id,
        workflow_version=first.workflow_version,
        children=(first, second),
        concurrency=2,
    )
    lease = _lease_fixture(batch)
    control = FakeControlPlane(leases=[])

    await RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=control
    )._execute(lease)

    assert {item.execution_id for item in control.checkpoints} == {
        first.execution_id,
        second.execution_id,
    }
    assert lease.task.execution_id not in {item.execution_id for item in control.checkpoints}


@pytest.mark.asyncio
async def test_remote_preview_batch_enforces_one_deadline_across_queued_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _plan_fixture()
    second = replace(first, execution_id=uuid4())
    plan = WorkflowBatchPlan(
        execution_id=uuid4(),
        actor_id=first.actor_id,
        project_id=first.project_id,
        workflow_version=0,
        children=(first, second),
        concurrency=1,
        max_runtime_seconds=cast(int, 0.01),
        cleanup_timeout_seconds=cast(int, 0.01),
    )
    executor = RemoteWorkflowExecutor()
    cancellation = CancellationToken()
    started: list[UUID] = []
    cleanup_started: list[UUID] = []

    async def slow_execution(
        child: WorkflowRunPlan,
        **kwargs: object,
    ) -> object:
        started.append(child.execution_id)
        token = cast(CancellationToken, kwargs["cancellation"])
        await token.wait()
        cleanup_started.append(child.execution_id)
        await asyncio.sleep(60)
        raise AssertionError("bounded cleanup grace must cancel a stuck remote child")

    monkeypatch.setattr(executor, "_execute_run", slow_execution)
    with pytest.raises(PreviewRuntimeBudgetExceeded):
        await executor.execute(
            plan,
            network_policy=OutboundNetworkPolicy(),
            cancellation=cancellation,
        )

    assert len(started) == 1
    assert cleanup_started == started
    assert cancellation.cancelled is True
    assert cancellation.force_cancelled is False


@pytest.mark.asyncio
async def test_runner_agent_retries_transient_control_plane_failure() -> None:
    plan = _plan_fixture()
    lease = _lease_fixture(plan)
    control = FakeControlPlane(leases=[lease], claim_failures=1)
    agent = RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=control
    )
    control.stop = agent.stop

    await asyncio.wait_for(agent.run(), timeout=2)

    assert control.claim_failures == 0
    assert control.completed == [lease.lease_id]
    assert control.closed == 1


@pytest.mark.asyncio
async def test_runner_agent_reconnects_renews_and_shuts_down_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = FakeControlPlane(leases=[], connect_failures=1)
    agent = RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=control
    )

    async def no_wait() -> None:
        return None

    monkeypatch.setattr(agent, "_wait_for_poll", no_wait)
    assert await agent._connect()
    assert control.connected == 1

    class PermanentConnect(FakeControlPlane):
        async def connect(self) -> None:
            request = Request("POST", "http://control/connect")
            raise httpx.HTTPStatusError(
                "permanent failure", request=request, response=Response(400, request=request)
            )

    permanent_agent = RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"),
        control_plane=PermanentConnect(leases=[]),
    )
    monkeypatch.setattr(permanent_agent, "_wait_for_poll", no_wait)
    with pytest.raises(httpx.HTTPStatusError):
        await permanent_agent._connect()
    stopped_agent = RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=control
    )
    stopped_agent.stop()
    assert not await stopped_agent._connect()

    class CancelOnRenew(FakeControlPlane):
        async def renew(self, _lease_id: UUID, _fencing_token: int) -> object:
            return type("Ack", (), {"cancel_requested": True})()

    renewing_control = CancelOnRenew(leases=[])
    renewing_agent = RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=renewing_control
    )
    lease = _lease_fixture(_plan_fixture())
    cancellation = CancellationToken()
    sleep_calls = 0

    async def stop_after_renew(_delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr("app.runner.agent.asyncio.sleep", stop_after_renew)
    with pytest.raises(asyncio.CancelledError):
        await renewing_agent._renew_until_done(lease, cancellation)
    assert cancellation.cancelled

    pending = asyncio.Event()
    renewing_agent._tasks.add(asyncio.create_task(pending.wait()))
    await renewing_agent._shutdown_tasks()
    assert not renewing_agent._tasks


@pytest.mark.asyncio
async def test_runner_agent_honors_checkpoint_cancel_and_fenced_complete() -> None:
    plan = _plan_fixture()
    lease = _lease_fixture(plan)

    class CancelCheckpoint(FakeControlPlane):
        async def checkpoint(self, _lease_id: UUID, payload: RunnerCheckpointRequest) -> object:
            self.checkpoints.append(payload)
            return type("Ack", (), {"cancel_requested": True})()

    cancelling = CancelCheckpoint(leases=[])
    await RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=cancelling
    )._execute(lease)
    assert cancelling.checkpoints

    class FencedComplete(FakeControlPlane):
        async def complete(
            self,
            _lease_id: UUID,
            _fencing_token: int,
            _result: RunnerExecutionResult,
        ) -> None:
            request = Request("POST", "http://control/complete")
            raise httpx.HTTPStatusError(
                "fenced", request=request, response=Response(409, request=request)
            )

    fenced = FencedComplete(leases=[])
    await RunnerAgent(
        _agent_configuration(runner_token="ftrun_agent-token"), control_plane=fenced
    )._execute(lease)
    assert fenced.failed == []


def test_runner_checkpoint_and_token_guards(tmp_path: Path) -> None:
    plan = _plan_fixture()
    lease = _lease_fixture(plan)
    update = NodeStatusUpdate(
        node_id="start",
        node_type=NodeType.START,
        name="开始",
        status=NodeStatus.PASSED,
        attempts=1,
        error_code=None,
        error_message=None,
        result=NodeResult.passed({"value": "safe"}),
        occurred_at=datetime.now(UTC),
        context_snapshot={"extracted_variables": "not-a-map"},
    )
    checkpoint = _checkpoint_payload(lease, update)
    assert checkpoint.extracted_variables == {}
    reservation_started_at = datetime.now(UTC)
    reservation = _checkpoint_payload(
        lease,
        replace(
            update,
            status=NodeStatus.RUNNING,
            result=None,
            occurred_at=reservation_started_at,
            started_at=reservation_started_at,
            request_reserved=True,
        ),
    )
    assert reservation.status is NodeStatus.RUNNING
    assert reservation.result is None
    assert reservation.started_at == reservation_started_at
    with pytest.raises(ValueError, match="NodeResult"):
        _checkpoint_payload(lease, replace(update, result=None))

    assert _read_runner_token("") == ""
    assert _read_runner_token(str(tmp_path / "missing-token")) == ""
    oversized = tmp_path / "oversized-token"
    oversized.write_text("x" * 513)
    with pytest.raises(ValueError, match="too large"):
        _read_runner_token(str(oversized))

    request = Request("GET", "http://control")
    retryable = httpx.HTTPStatusError("temporary", request=request, response=Response(500))
    permanent = httpx.HTTPStatusError("permanent", request=request, response=Response(400))
    assert _retryable_control_plane_error(retryable)
    assert not _retryable_control_plane_error(permanent)


def test_runner_agent_environment_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "identity-token"
    token_file.write_text("ftrun_persisted-environment-token")
    monkeypatch.setenv("FLOWTEST_RUNNER_CONTROL_PLANE_URL", "http://backend:8000")
    monkeypatch.delenv("FLOWTEST_RUNNER_TOKEN", raising=False)
    monkeypatch.setenv("FLOWTEST_RUNNER_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("FLOWTEST_RUNNER_NAME", "environment-runner")
    monkeypatch.setenv("FLOWTEST_RUNNER_INSTANCE_ID", "environment-runner-instance")
    monkeypatch.setenv("FLOWTEST_RUNNER_LABELS", "arm64, zone.cn")
    monkeypatch.setenv("FLOWTEST_RUNNER_MAX_CONCURRENCY", "3")
    configuration = configuration_from_environment()
    assert configuration.labels == ["arm64", "zone.cn"]
    assert configuration.max_concurrency == 3
    assert configuration.runner_token == "ftrun_persisted-environment-token"
    with pytest.raises(ValidationError, match="必须使用 HTTPS"):
        RunnerAgentConfiguration(
            control_plane_url="http://api:8000",
            registration_token="ftrreg_test-token-that-is-long-enough",
            name="runner",
            instance_id="instance-production-runner",
            runtime="docker",
            agent_version="3.0.0",
            architecture="arm64",
            production=True,
        )


@pytest.mark.asyncio
async def test_runner_result_rejects_malformed_content_length() -> None:
    plan = _plan_fixture()
    result = await RemoteWorkflowExecutor().execute(
        plan,
        network_policy=OutboundNetworkPolicy(),
        cancellation=CancellationToken(),
    )
    request = StarletteRequest(
        {"type": "http", "method": "POST", "path": "/", "headers": [(b"content-length", b"x")]}
    )
    with pytest.raises(AppError) as invalid:
        _validate_result_size(
            request,
            RunnerCompleteRequest(fencing_token=1, result=result),
        )
    assert invalid.value.code == "RUNNER_CONTENT_LENGTH_INVALID"


async def _seed_actor_and_project(session: AsyncSession) -> tuple[User, Project]:
    actor = User(
        email=f"runner-{uuid4()}@example.com",
        display_name="Runner administrator",
        password_hash=password_service.hash("runner-fabric-password!"),
        is_active=True,
        is_system_admin=True,
        requires_password_change=False,
    )
    session.add(actor)
    await session.flush()
    project = Project(
        name="Runner project",
        description="",
        execution_concurrency_limit=10,
        queued_run_limit=100,
        created_by_id=actor.id,
    )
    session.add(project)
    await session.commit()
    return actor, project


async def _seed_execution_plan(
    session: AsyncSession, actor: User, project: Project
) -> tuple[WorkflowRunPlan, WorkflowExecution]:
    execution = WorkflowExecution(
        project_id=project.id,
        workflow_id=uuid4(),
        workflow_version_id=uuid4(),
        environment_id=uuid4(),
        triggered_by_id=actor.id,
        parent_execution_id=None,
        dataset_row_index=None,
        status="running",
        snapshot={},
        context={},
        error_code=None,
        error_message=None,
        cancel_requested_at=None,
        started_at=datetime.now(UTC),
        completed_at=None,
        run_payload_ciphertext=None,
        run_payload_nonce=None,
    )
    session.add(execution)
    await session.commit()
    definition = _definition()
    plan = WorkflowRunPlan(
        execution_id=execution.id,
        actor_id=actor.id,
        project_id=project.id,
        workflow_version=1,
        definition=definition,
        prepared=PreparedExecution(snapshot={}, requests={}, dataset_variables={}),
        runtime_variables={},
    )
    await WorkflowService(session)._persist_execution_plan(execution, plan)
    return plan, execution


async def _register_runner(
    service: RunnerFabricService, actor: User, pool_id: UUID, name: str
) -> str:
    _model, registration = await service.create_registration_token(
        actor=actor, pool_id=pool_id, expires_in_seconds=300
    )
    response = await service.register(
        registration_token=registration,
        payload=_runner_payload(name, f"instance-{name}-identity"),
    )
    return response.token


def _pool_payload(
    *, labels: list[str] | None = None, max_concurrency: int = 10
) -> RunnerPoolCreate:
    return RunnerPoolCreate(
        name=f"general-{uuid4()}",
        runner_type="general",
        runtime="docker",
        network_zone="default",
        labels=labels or [],
        capabilities=["flow.workflow"],
        max_concurrency=max_concurrency,
        lease_timeout_seconds=10,
        heartbeat_timeout_seconds=30,
    )


def _runner_payload(
    name: str, instance_id: str, *, labels: list[str] | None = None
) -> RunnerRegisterRequest:
    return RunnerRegisterRequest(
        name=name,
        instance_id=instance_id,
        runtime="docker",
        agent_version="3.0.0-beta.3",
        architecture="arm64",
        labels=labels or [],
        capabilities=["flow.workflow"],
        max_concurrency=1,
    )


def _definition() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "2.0",
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "name": "开始",
                    "position": {"x": 0, "y": 0},
                    "config": {},
                },
                {
                    "id": "end",
                    "type": "end",
                    "name": "结束",
                    "position": {"x": 200, "y": 0},
                    "config": {},
                },
            ],
            "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        }
    )


def _plan_fixture() -> WorkflowRunPlan:
    return WorkflowRunPlan(
        execution_id=uuid4(),
        actor_id=uuid4(),
        project_id=uuid4(),
        workflow_version=1,
        definition=_definition(),
        prepared=PreparedExecution(snapshot={}, requests={}, dataset_variables={}),
        runtime_variables={},
    )


def _lease_fixture(plan: WorkflowRunPlan | WorkflowBatchPlan) -> RunnerLeaseResponse:
    acquired_at = datetime.now(UTC)
    encoded = encode_execution_plan(plan)
    return RunnerLeaseResponse(
        lease_id=uuid4(),
        runner_id=uuid4(),
        acquired_at=acquired_at,
        expires_at=acquired_at + timedelta(seconds=30),
        task=RunnerLeaseTaskResponse(
            task_id=uuid4(),
            execution_id=plan.execution_id,
            attempt=1,
            fencing_token=1,
            plan=encoded,
            plan_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
            allowed_hosts=[],
            allowed_private_cidrs=[],
        ),
    )


def _agent_configuration(
    *,
    registration_token: str = "",
    runner_token: str = "",
    runner_token_file: str = "",
) -> RunnerAgentConfiguration:
    return RunnerAgentConfiguration(
        control_plane_url="http://control",
        registration_token=registration_token,
        runner_token=runner_token,
        runner_token_file=runner_token_file,
        name="agent",
        instance_id="runner-agent-instance-fixture",
        runtime="docker",
        agent_version="3.0.0-beta.3",
        architecture="arm64",
        max_concurrency=1,
        poll_seconds=0.1,
    )


@dataclass(slots=True)
class FakeControlPlane:
    leases: list[RunnerLeaseResponse]
    stop: object | None = None
    claim_failures: int = 0
    connect_failures: int = 0
    connected: int = 0
    closed: int = 0
    completed: list[UUID] = field(default_factory=list)
    failed: list[UUID] = field(default_factory=list)
    checkpoints: list[RunnerCheckpointRequest] = field(default_factory=list)

    async def connect(self) -> None:
        if self.connect_failures:
            self.connect_failures -= 1
            raise httpx.ConnectError(
                "temporary failure", request=Request("POST", "http://control/connect")
            )
        self.connected += 1

    async def claim(self) -> RunnerLeaseResponse | None:
        if self.claim_failures:
            self.claim_failures -= 1
            raise httpx.ConnectError(
                "temporary failure", request=Request("POST", "http://control/leases/claim")
            )
        if self.leases:
            return self.leases.pop(0)
        if callable(self.stop):
            self.stop()
        return None

    async def heartbeat(self, _current_load: int) -> None:
        return None

    async def renew(self, _lease_id: UUID, _fencing_token: int) -> object:
        return type("Ack", (), {"cancel_requested": False})()

    async def progress(
        self,
        _lease_id: UUID,
        _fencing_token: int,
        _progress_percent: float,
        _message: str,
    ) -> object:
        return type("Ack", (), {"cancel_requested": False})()

    async def checkpoint(self, _lease_id: UUID, payload: RunnerCheckpointRequest) -> object:
        self.checkpoints.append(payload)
        return type("Ack", (), {"cancel_requested": False})()

    async def complete(
        self,
        lease_id: UUID,
        _fencing_token: int,
        _result: RunnerExecutionResult,
    ) -> None:
        self.completed.append(lease_id)

    async def fail(
        self,
        lease_id: UUID,
        _fencing_token: int,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> None:
        del error_code, error_message, retryable
        self.failed.append(lease_id)

    async def close(self) -> None:
        self.closed += 1
