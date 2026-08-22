import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.capabilities import RunnerType
from app.domain.runner_fabric import (
    RunnerEventKind,
    RunnerProfile,
    RunnerRuntime,
    RunnerStatus,
    identity_fingerprint,
    select_runner_type,
)
from app.engine.capabilities import builtin_capability_registry, legacy_node_adapter
from app.models.access import User
from app.models.capabilities import Runner, RunnerPool
from app.models.runner_fabric import (
    RunnerEvent,
    RunnerLeaseRecord,
    RunnerRegistrationToken,
    RunnerTask,
)
from app.repositories.runner_fabric import RunnerFabricRepository
from app.runner.results import RunnerExecutionResult
from app.schemas.runner_fabric import (
    RunnerFailRequest,
    RunnerHeartbeatRequest,
    RunnerLeaseAckResponse,
    RunnerLeaseResponse,
    RunnerLeaseTaskResponse,
    RunnerPoolCreate,
    RunnerPoolUpdate,
    RunnerProgressRequest,
    RunnerRegisterRequest,
    RunnerRegisterResponse,
)
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.workflow_plan_codec import encode_execution_plan
from app.services.workflows import WorkflowBatchPlan, WorkflowExecutionPlan, WorkflowService

REGISTRATION_TOKEN_PREFIX = "ftrreg_"  # noqa: S105
RUNNER_TOKEN_PREFIX = "ftrun_"  # noqa: S105
WORKFLOW_CAPABILITY = "flow.workflow"


class RunnerFabricService:
    def __init__(self, session: AsyncSession, *, enabled: bool) -> None:
        self._session = session
        self._enabled = enabled
        self._repository = RunnerFabricRepository(session)
        self._audit = AuditService(session)

    async def create_pool(self, *, actor: User, payload: RunnerPoolCreate) -> RunnerPool:
        self._require_admin(actor)
        normalized_name = payload.name.strip()
        if (
            await self._repository.find_pool_by_name(
                normalized_name,
                organization_id=_organization_id(),
            )
            is not None
        ):
            raise AppError(
                code="RUNNER_POOL_EXISTS", message="Runner Pool 名称已存在", status_code=409
            )
        profile = self._pool_profile(payload)
        pool = RunnerPool(
            organization_id=_organization_id(),
            name=normalized_name,
            runner_type=profile.runner_type.value,
            runtime=profile.runtime.value,
            network_zone=profile.network_zone,
            labels=list(profile.labels),
            capabilities=list(profile.capabilities),
            max_concurrency=profile.max_concurrency,
            lease_timeout_seconds=profile.lease_seconds,
            heartbeat_timeout_seconds=profile.heartbeat_timeout_seconds,
            enabled=True,
            created_by_id=actor.id,
        )
        self._repository.add(pool)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action="runner.pool_created",
            resource_type="runner_pool",
            resource_id=pool.id,
            details={"runner_type": pool.runner_type, "runtime": pool.runtime},
        )
        await self._session.commit()
        await self._session.refresh(pool)
        return pool

    async def update_pool(
        self, *, actor: User, pool_id: UUID, payload: RunnerPoolUpdate
    ) -> RunnerPool:
        self._require_admin(actor)
        pool = await self._require_pool(pool_id, lock=True)
        lease_seconds = payload.lease_timeout_seconds or pool.lease_timeout_seconds
        heartbeat_seconds = payload.heartbeat_timeout_seconds or pool.heartbeat_timeout_seconds
        if heartbeat_seconds <= lease_seconds:
            raise AppError(
                code="RUNNER_POOL_TIMEOUT_INVALID",
                message="心跳超时必须大于 Lease 时长",
                status_code=422,
            )
        if payload.max_concurrency is not None:
            current_load = await self._repository.pool_current_load(pool.id)
            if payload.max_concurrency < current_load:
                raise AppError(
                    code="RUNNER_POOL_BUSY",
                    message="Pool 并发上限不能低于当前负载",
                    status_code=409,
                    details={"current_load": current_load},
                )
            pool.max_concurrency = payload.max_concurrency
        pool.lease_timeout_seconds = lease_seconds
        pool.heartbeat_timeout_seconds = heartbeat_seconds
        if payload.enabled is not None:
            pool.enabled = payload.enabled
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action="runner.pool_updated",
            resource_type="runner_pool",
            resource_id=pool.id,
        )
        await self._session.commit()
        await self._session.refresh(pool)
        return pool

    async def list_pools(self, *, actor: User) -> list[tuple[RunnerPool, list[Runner]]]:
        self._require_admin(actor)
        pools = await self._repository.list_pools(organization_id=_organization_id())
        return [(pool, await self._repository.list_runners(pool.id)) for pool in pools]

    async def overview(self, *, actor: User) -> dict[str, int]:
        self._require_admin(actor)
        return await self._repository.counts(organization_id=_organization_id())

    async def list_tasks(self, *, actor: User, limit: int) -> list[RunnerTask]:
        self._require_admin(actor)
        return await self._repository.list_tasks(limit=limit, organization_id=_organization_id())

    async def list_leases(self, *, actor: User, limit: int) -> list[RunnerLeaseRecord]:
        self._require_admin(actor)
        return await self._repository.list_leases(limit=limit, organization_id=_organization_id())

    async def list_events(self, *, actor: User, limit: int) -> list[RunnerEvent]:
        self._require_admin(actor)
        return await self._repository.list_events(limit=limit, organization_id=_organization_id())

    async def create_registration_token(
        self, *, actor: User, pool_id: UUID, expires_in_seconds: int
    ) -> tuple[RunnerRegistrationToken, str]:
        self._require_admin(actor)
        pool = await self._require_pool(pool_id)
        if not pool.enabled:
            raise AppError(
                code="RUNNER_POOL_DISABLED", message="Runner Pool 已停用", status_code=409
            )
        raw_token = _new_token(REGISTRATION_TOKEN_PREFIX)
        model = RunnerRegistrationToken(
            pool_id=pool.id,
            token_hash=_token_hash(raw_token),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
            consumed_at=None,
            created_by_id=actor.id,
        )
        self._repository.add(model)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action="runner.registration_token_created",
            resource_type="runner_pool",
            resource_id=pool.id,
            details={"expires_at": model.expires_at.isoformat()},
        )
        await self._session.commit()
        await self._session.refresh(model)
        return model, raw_token

    async def register(
        self, *, registration_token: str, payload: RunnerRegisterRequest
    ) -> RunnerRegisterResponse:
        self._require_enabled()
        _require_token_prefix(registration_token, REGISTRATION_TOKEN_PREFIX)
        now = datetime.now(UTC)
        token = await self._repository.get_registration_token(
            _token_hash(registration_token), lock=True
        )
        if token is None or token.consumed_at is not None or _as_utc(token.expires_at) <= now:
            raise AppError(
                code="RUNNER_REGISTRATION_TOKEN_INVALID",
                message="Runner 注册令牌无效或已过期",
                status_code=401,
            )
        pool = await self._require_pool(token.pool_id, lock=True)
        profile = self._validate_registration(pool, payload)
        fingerprint = identity_fingerprint(payload.instance_id)
        if await self._repository.find_runner_by_identity(fingerprint) is not None:
            raise AppError(
                code="RUNNER_IDENTITY_EXISTS",
                message="Runner 实例身份已注册",
                status_code=409,
            )
        raw_token = _new_token(RUNNER_TOKEN_PREFIX)
        runner = Runner(
            pool_id=pool.id,
            name=payload.name.strip(),
            identity_fingerprint=fingerprint,
            token_hash=_token_hash(raw_token),
            runtime=profile.runtime.value,
            agent_version=payload.agent_version.strip(),
            architecture=payload.architecture.strip().lower(),
            status=RunnerStatus.ONLINE.value,
            labels=list(profile.labels),
            capabilities=list(profile.capabilities),
            max_concurrency=profile.max_concurrency,
            current_load=0,
            last_seen_at=now,
            draining_requested_at=None,
            disabled_at=None,
        )
        token.consumed_at = now
        self._repository.add(runner)
        await self._session.flush()
        self._event(
            pool_id=pool.id,
            runner_id=runner.id,
            kind=RunnerEventKind.REGISTERED,
            message="Runner 已完成一次性令牌注册",
            details={"runtime": runner.runtime, "architecture": runner.architecture},
        )
        await self._session.commit()
        return RunnerRegisterResponse(
            runner_id=runner.id,
            pool_id=pool.id,
            token=raw_token,
            lease_timeout_seconds=pool.lease_timeout_seconds,
            heartbeat_timeout_seconds=pool.heartbeat_timeout_seconds,
        )

    async def heartbeat(self, *, runner_token: str, payload: RunnerHeartbeatRequest) -> Runner:
        runner = await self._authenticate_locked_runner(runner_token)
        if payload.current_load > runner.max_concurrency:
            raise AppError(
                code="RUNNER_LOAD_INVALID",
                message="Runner 上报负载超过自身并发上限",
                status_code=422,
            )
        runner.current_load = payload.current_load
        runner.last_seen_at = datetime.now(UTC)
        if runner.status == RunnerStatus.OFFLINE.value:
            runner.status = RunnerStatus.ONLINE.value
            self._event(
                pool_id=runner.pool_id,
                runner_id=runner.id,
                kind=RunnerEventKind.ONLINE,
                message="Runner 心跳恢复",
            )
        await self._session.commit()
        await self._session.refresh(runner)
        return runner

    async def enqueue(self, plan: WorkflowExecutionPlan) -> RunnerTask:
        self._require_enabled()
        await self._repository.lock_project_capacity(plan.project_id)
        project = await self._repository.get_project(plan.project_id)
        if project is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        queued = await self._repository.queued_count(plan.project_id)
        if queued >= project.queued_run_limit:
            raise AppError(
                code="PROJECT_QUEUE_EXCEEDED",
                message="项目排队执行配额已用尽",
                status_code=429,
                details={"limit": project.queued_run_limit},
            )
        if await self._repository.get_task_by_execution(plan.execution_id) is not None:
            raise AppError(
                code="RUNNER_TASK_EXISTS", message="执行任务已进入 Runner 队列", status_code=409
            )
        now = datetime.now(UTC)
        task = RunnerTask(
            execution_id=plan.execution_id,
            project_id=plan.project_id,
            required_runner_type=_plan_runner_type(plan).value,
            required_labels=[],
            required_capabilities=[WORKFLOW_CAPABILITY],
            status="queued",
            priority=5,
            attempts=0,
            max_attempts=settings.runner_max_attempts,
            fencing_token=0,
            available_at=now,
            selected_runner_id=None,
            last_lease_id=None,
            error_code=None,
            error_message=None,
            completed_at=None,
        )
        self._repository.add(task)
        await self._repository.set_execution_family_status(plan.execution_id, "queued")
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def fail_enqueue(self, execution_id: UUID) -> None:
        await WorkflowService(self._session).stage_runtime_failed(
            execution_id,
            error_code="RUNNER_QUEUE_REJECTED",
            error_message="执行未能进入 Runner 队列",
        )
        await self._session.commit()

    async def claim(self, *, runner_token: str) -> RunnerLeaseResponse | None:
        self._require_enabled()
        now = datetime.now(UTC)
        await self._reconcile_expired(now)
        authenticated = await self._authenticate_runner(runner_token)
        await self._repository.lock_pool_claims(authenticated.pool_id)
        pool = await self._require_pool(authenticated.pool_id)
        runner = await self._lock_runner(authenticated.id)
        if not self._runner_can_claim(runner, pool):
            await self._session.commit()
            return None
        candidates = await self._repository.claim_candidates(
            runner_type=pool.runner_type,
            available_at=now,
            organization_id=pool.organization_id,
        )
        task = await self._select_candidate(candidates, runner, pool)
        if task is None:
            runner.last_seen_at = now
            await self._session.commit()
            return None
        plan = await WorkflowService(self._session).load_execution_plan(task.execution_id)
        policy = await ProjectService(self._session).load_runtime_security_policy(task.project_id)
        lease = self._acquire(task=task, runner=runner, pool=pool, now=now)
        await self._repository.set_execution_family_status(task.execution_id, "running")
        await self._session.flush()
        task.last_lease_id = lease.id
        self._event(
            pool_id=pool.id,
            runner_id=runner.id,
            task_id=task.id,
            lease_id=lease.id,
            kind=RunnerEventKind.LEASE_ACQUIRED,
            message="Runner 已认领执行 Lease",
            details={"fencing_token": lease.fencing_token, "attempt": task.attempts},
        )
        encoded = encode_execution_plan(plan)
        await self._session.commit()
        return RunnerLeaseResponse(
            lease_id=lease.id,
            runner_id=runner.id,
            acquired_at=lease.acquired_at,
            expires_at=lease.expires_at,
            task=RunnerLeaseTaskResponse(
                task_id=task.id,
                execution_id=task.execution_id,
                attempt=task.attempts,
                fencing_token=lease.fencing_token,
                plan=encoded,
                plan_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                outbound_policy_enabled=policy.enabled,
                allowed_hosts=list(policy.allowed_hosts),
                allowed_private_cidrs=list(policy.allowed_private_cidrs),
            ),
        )

    async def renew(
        self, *, runner_token: str, lease_id: UUID, fencing_token: int
    ) -> RunnerLeaseAckResponse:
        now = datetime.now(UTC)
        _runner, _lease, _task, acknowledgment = await self._renew_active_lease(
            runner_token=runner_token,
            lease_id=lease_id,
            fencing_token=fencing_token,
            now=now,
        )
        await self._session.commit()
        return acknowledgment

    async def progress(
        self, *, runner_token: str, lease_id: UUID, payload: RunnerProgressRequest
    ) -> RunnerLeaseAckResponse:
        runner, _lease, _task, acknowledgment = await self._renew_active_lease(
            runner_token=runner_token,
            lease_id=lease_id,
            fencing_token=payload.fencing_token,
            now=datetime.now(UTC),
        )
        if payload.message:
            self._event(
                pool_id=runner.pool_id,
                runner_id=runner.id,
                lease_id=lease_id,
                kind=RunnerEventKind.LEASE_RENEWED,
                message=payload.message,
                details={"progress_percent": payload.progress_percent},
            )
        await self._session.commit()
        return acknowledgment

    async def complete(
        self,
        *,
        runner_token: str,
        lease_id: UUID,
        fencing_token: int,
        result: RunnerExecutionResult,
    ) -> RunnerLeaseAckResponse:
        now = datetime.now(UTC)
        runner = await self._authenticate_locked_runner(runner_token)
        lease = await self._repository.get_lease(lease_id, lock=True)
        if lease is None or lease.runner_id != runner.id:
            raise _fenced_error()
        task = await self._require_task(lease.task_id, lock=True)
        if lease.status == "completed" and task.status == "completed":
            await self._session.commit()
            return RunnerLeaseAckResponse(task_status=task.status)
        self._validate_active_lease(lease, task, runner.id, fencing_token, now)
        plan = await WorkflowService(self._session).load_execution_plan(task.execution_id)
        await WorkflowService(self._session).stage_remote_result(plan=plan, submitted=result)
        lease.status = "completed"
        lease.completed_at = now
        task.status = "completed"
        task.completed_at = now
        task.error_code = None
        task.error_message = None
        runner.current_load = max(0, runner.current_load - 1)
        runner.last_seen_at = now
        self._event(
            pool_id=runner.pool_id,
            runner_id=runner.id,
            task_id=task.id,
            lease_id=lease.id,
            kind=RunnerEventKind.LEASE_COMPLETED,
            message="Runner Lease 已写入唯一终态",
            details={"fencing_token": fencing_token},
        )
        await self._session.commit()
        return RunnerLeaseAckResponse(task_status=task.status)

    async def fail(
        self, *, runner_token: str, lease_id: UUID, payload: RunnerFailRequest
    ) -> RunnerLeaseAckResponse:
        now = datetime.now(UTC)
        runner, lease, task = await self._active_lease(
            runner_token=runner_token,
            lease_id=lease_id,
            fencing_token=payload.fencing_token,
            now=now,
        )
        lease.status = "released"
        lease.completed_at = now
        runner.current_load = max(0, runner.current_load - 1)
        if payload.retryable and task.attempts < task.max_attempts:
            await self._requeue_task(task, now)
        else:
            await self._fail_task(
                task,
                now=now,
                error_code=payload.error_code,
                error_message=payload.error_message,
            )
        self._event(
            pool_id=runner.pool_id,
            runner_id=runner.id,
            task_id=task.id,
            lease_id=lease.id,
            kind=RunnerEventKind.TASK_FAILED,
            message="Runner 上报执行失败",
            details={"retryable": payload.retryable, "attempt": task.attempts},
        )
        await self._session.commit()
        return RunnerLeaseAckResponse(task_status=task.status)

    async def runner_action(self, *, actor: User, runner_id: UUID, action: str) -> Runner:
        self._require_admin(actor)
        runner = await self._lock_runner(runner_id)
        now = datetime.now(UTC)
        if action == "drain":
            runner.status = RunnerStatus.DRAINING.value
            runner.draining_requested_at = now
            kind = RunnerEventKind.DRAINING
            message = "Runner 已进入 Drain, 停止认领新任务"
        elif action == "resume":
            if runner.disabled_at is not None:
                raise AppError(
                    code="RUNNER_DISABLED", message="已停用 Runner 不能恢复", status_code=409
                )
            runner.status = RunnerStatus.ONLINE.value
            runner.draining_requested_at = None
            kind = RunnerEventKind.RESUMED
            message = "Runner 已恢复认领任务"
        else:
            runner.status = RunnerStatus.DISABLED.value
            runner.disabled_at = now
            kind = RunnerEventKind.DISABLED
            message = "Runner 已停用"
        self._event(
            pool_id=runner.pool_id,
            runner_id=runner.id,
            kind=kind,
            message=message,
        )
        await self._session.commit()
        await self._session.refresh(runner)
        return runner

    async def reconcile(self) -> int:
        self._require_enabled()
        now = datetime.now(UTC)
        expired = await self._reconcile_expired(now)
        offline = await self._reconcile_offline(now)
        return expired + offline

    async def _reconcile_offline(self, now: datetime) -> int:
        count = 0
        for pool in await self._repository.list_pools():
            deadline = now - timedelta(seconds=pool.heartbeat_timeout_seconds)
            for runner in await self._repository.list_runners(pool.id):
                if (
                    runner.status != RunnerStatus.ONLINE.value
                    or runner.last_seen_at is None
                    or _as_utc(runner.last_seen_at) > deadline
                ):
                    continue
                runner = await self._lock_runner(runner.id)
                if (
                    runner.status != RunnerStatus.ONLINE.value
                    or runner.last_seen_at is None
                    or _as_utc(runner.last_seen_at) > deadline
                ):
                    continue
                runner.status = RunnerStatus.OFFLINE.value
                self._event(
                    pool_id=pool.id,
                    runner_id=runner.id,
                    kind=RunnerEventKind.OFFLINE,
                    message="Runner 心跳超时, 已标记离线",
                )
                count += 1
        if count:
            await self._session.commit()
        return count

    async def _reconcile_expired(self, now: datetime) -> int:
        expired = await self._repository.expired_leases(now)
        count = 0
        for candidate in expired:
            runner = await self._lock_runner(candidate.runner_id)
            lease = await self._repository.get_lease(candidate.id, lock=True)
            if lease is None or lease.status != "active":
                continue
            task = await self._repository.get_task(lease.task_id, lock=True)
            if task is None or _as_utc(lease.expires_at) > now:
                continue
            await self._expire_lease(lease=lease, task=task, runner=runner, now=now)
            count += 1
        if count:
            await self._session.commit()
        return count

    async def _expire_lease(
        self,
        *,
        lease: RunnerLeaseRecord,
        task: RunnerTask,
        runner: Runner,
        now: datetime,
    ) -> None:
        lease.status = "expired"
        lease.completed_at = now
        runner.current_load = max(0, runner.current_load - 1)
        if task.last_lease_id == lease.id and task.fencing_token == lease.fencing_token:
            if task.attempts < task.max_attempts:
                await self._requeue_task(task, now)
            else:
                await self._fail_task(
                    task,
                    now=now,
                    error_code="RUNNER_LEASE_EXHAUSTED",
                    error_message="Runner Lease 多次过期, 执行已停止",
                )
        self._event(
            pool_id=runner.pool_id,
            runner_id=runner.id,
            task_id=task.id,
            lease_id=lease.id,
            kind=RunnerEventKind.LEASE_EXPIRED,
            message="Runner Lease 已过期并触发 Fence",
            details={"fencing_token": lease.fencing_token, "attempt": task.attempts},
        )

    async def _requeue_task(self, task: RunnerTask, now: datetime) -> None:
        task.status = "queued"
        task.available_at = now
        task.selected_runner_id = None
        task.error_code = None
        task.error_message = None
        await self._repository.set_execution_family_status(task.execution_id, "queued")

    async def _fail_task(
        self,
        task: RunnerTask,
        *,
        now: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        task.status = "failed"
        task.error_code = error_code
        task.error_message = error_message
        task.completed_at = now
        await WorkflowService(self._session).stage_runtime_failed(
            task.execution_id,
            error_code=error_code,
            error_message=error_message,
        )

    async def _active_lease(
        self,
        *,
        runner_token: str,
        lease_id: UUID,
        fencing_token: int,
        now: datetime,
    ) -> tuple[Runner, RunnerLeaseRecord, RunnerTask]:
        runner = await self._authenticate_locked_runner(runner_token)
        lease = await self._repository.get_lease(lease_id, lock=True)
        if lease is None or lease.runner_id != runner.id:
            raise _fenced_error()
        task = await self._require_task(lease.task_id, lock=True)
        self._validate_active_lease(lease, task, runner.id, fencing_token, now)
        return runner, lease, task

    async def _renew_active_lease(
        self,
        *,
        runner_token: str,
        lease_id: UUID,
        fencing_token: int,
        now: datetime,
    ) -> tuple[Runner, RunnerLeaseRecord, RunnerTask, RunnerLeaseAckResponse]:
        runner, lease, task = await self._active_lease(
            runner_token=runner_token,
            lease_id=lease_id,
            fencing_token=fencing_token,
            now=now,
        )
        pool = await self._require_pool(runner.pool_id)
        lease.expires_at = now + timedelta(seconds=pool.lease_timeout_seconds)
        lease.last_renewed_at = now
        runner.last_seen_at = now
        acknowledgment = RunnerLeaseAckResponse(
            task_status=task.status,
            expires_at=lease.expires_at,
            cancel_requested=await self._cancel_requested(task.execution_id),
        )
        return runner, lease, task, acknowledgment

    @staticmethod
    def _validate_active_lease(
        lease: RunnerLeaseRecord,
        task: RunnerTask,
        runner_id: UUID,
        fencing_token: int,
        now: datetime,
    ) -> None:
        valid = (
            lease.runner_id == runner_id
            and lease.status == "active"
            and _as_utc(lease.expires_at) > now
            and lease.fencing_token == fencing_token
            and task.status == "leased"
            and task.last_lease_id == lease.id
            and task.fencing_token == fencing_token
        )
        if not valid:
            raise _fenced_error()

    async def _select_candidate(
        self, candidates: list[RunnerTask], runner: Runner, pool: RunnerPool
    ) -> RunnerTask | None:
        if await self._repository.pool_current_load(pool.id) >= pool.max_concurrency:
            return None
        for task in candidates:
            if not _task_matches(task, runner):
                continue
            await self._repository.lock_project_capacity(task.project_id)
            project = await self._repository.get_project(task.project_id)
            if project is None:
                continue
            active = await self._repository.active_execution_count(task.project_id)
            if active < project.execution_concurrency_limit:
                return task
        return None

    def _acquire(
        self, *, task: RunnerTask, runner: Runner, pool: RunnerPool, now: datetime
    ) -> RunnerLeaseRecord:
        task.attempts += 1
        task.fencing_token += 1
        task.status = "leased"
        task.selected_runner_id = runner.id
        lease = RunnerLeaseRecord(
            task_id=task.id,
            runner_id=runner.id,
            fencing_token=task.fencing_token,
            status="active",
            acquired_at=now,
            expires_at=now + timedelta(seconds=pool.lease_timeout_seconds),
            last_renewed_at=now,
            completed_at=None,
        )
        self._repository.add(lease)
        runner.current_load += 1
        runner.last_seen_at = now
        return lease

    async def _cancel_requested(self, execution_id: UUID) -> bool:
        execution = await self._repository.get_execution(execution_id)
        return execution is not None and execution.cancel_requested_at is not None

    async def _authenticate_runner(self, raw_token: str) -> Runner:
        self._require_enabled()
        _require_token_prefix(raw_token, RUNNER_TOKEN_PREFIX)
        runner = await self._repository.find_runner_by_token(_token_hash(raw_token))
        if runner is None or runner.status == RunnerStatus.DISABLED.value:
            raise AppError(
                code="RUNNER_AUTHENTICATION_FAILED",
                message="Runner 身份令牌无效",
                status_code=401,
            )
        return runner

    async def _authenticate_locked_runner(self, raw_token: str) -> Runner:
        authenticated = await self._authenticate_runner(raw_token)
        runner = await self._lock_runner(authenticated.id)
        if runner.status == RunnerStatus.DISABLED.value:
            raise AppError(
                code="RUNNER_AUTHENTICATION_FAILED",
                message="Runner 身份令牌无效",
                status_code=401,
            )
        return runner

    async def _lock_runner(self, runner_id: UUID) -> Runner:
        await self._repository.lock_runner_control(runner_id)
        runner = await self._require_runner(runner_id)
        await self._session.refresh(runner)
        return runner

    async def _require_pool(self, pool_id: UUID, *, lock: bool = False) -> RunnerPool:
        pool = await self._repository.get_pool(pool_id, lock=lock)
        if pool is None:
            raise AppError(
                code="RUNNER_POOL_NOT_FOUND", message="Runner Pool 不存在", status_code=404
            )
        context = get_tenant_context()
        if (
            context is not None
            and pool.organization_id is not None
            and pool.organization_id != context.organization_id
        ):
            raise AppError(
                code="RUNNER_POOL_NOT_FOUND", message="Runner Pool 不存在", status_code=404
            )
        return pool

    async def _require_runner(self, runner_id: UUID, *, lock: bool = False) -> Runner:
        runner = await self._repository.get_runner(runner_id, lock=lock)
        if runner is None:
            raise AppError(code="RUNNER_NOT_FOUND", message="Runner 不存在", status_code=404)
        await self._require_pool(runner.pool_id)
        return runner

    async def _require_task(self, task_id: UUID, *, lock: bool = False) -> RunnerTask:
        task = await self._repository.get_task(task_id, lock=lock)
        if task is None:
            raise AppError(
                code="RUNNER_TASK_NOT_FOUND", message="Runner 任务不存在", status_code=404
            )
        return task

    def _require_admin(self, actor: User) -> None:
        self._require_enabled()
        if not actor.is_system_admin:
            raise AppError(
                code="SYSTEM_ADMIN_REQUIRED", message="需要系统管理员权限", status_code=403
            )

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise AppError(
                code="RUNNER_FABRIC_DISABLED", message="分布式执行面尚未启用", status_code=404
            )

    @staticmethod
    def _runner_can_claim(runner: Runner, pool: RunnerPool) -> bool:
        return (
            pool.enabled
            and runner.status == RunnerStatus.ONLINE.value
            and runner.current_load < runner.max_concurrency
        )

    @staticmethod
    def _pool_profile(payload: RunnerPoolCreate) -> RunnerProfile:
        try:
            return RunnerProfile(
                runner_type=RunnerType(payload.runner_type),
                runtime=RunnerRuntime(payload.runtime),
                network_zone=payload.network_zone.strip(),
                labels=tuple(payload.labels),
                capabilities=tuple(payload.capabilities),
                max_concurrency=payload.max_concurrency,
                lease_seconds=payload.lease_timeout_seconds,
                heartbeat_timeout_seconds=payload.heartbeat_timeout_seconds,
            )
        except (ValueError, ValidationError) as error:
            raise AppError(
                code="RUNNER_POOL_INVALID", message=str(error), status_code=422
            ) from error

    @staticmethod
    def _validate_registration(pool: RunnerPool, payload: RunnerRegisterRequest) -> RunnerProfile:
        try:
            profile = RunnerProfile(
                runner_type=RunnerType(pool.runner_type),
                runtime=RunnerRuntime(payload.runtime),
                network_zone=pool.network_zone,
                labels=tuple(payload.labels),
                capabilities=tuple(payload.capabilities),
                max_concurrency=payload.max_concurrency,
                lease_seconds=pool.lease_timeout_seconds,
                heartbeat_timeout_seconds=pool.heartbeat_timeout_seconds,
            )
        except (ValueError, ValidationError) as error:
            raise AppError(
                code="RUNNER_PROFILE_INVALID", message=str(error), status_code=422
            ) from error
        capabilities = set(profile.capabilities)
        valid = (
            pool.enabled
            and profile.runtime.value == pool.runtime
            and set(pool.labels).issubset(set(profile.labels))
            and capabilities.issubset(set(pool.capabilities))
            and WORKFLOW_CAPABILITY in capabilities
            and profile.max_concurrency <= pool.max_concurrency
        )
        if not valid:
            raise AppError(
                code="RUNNER_PROFILE_NOT_ALLOWED",
                message="Runner Profile 不符合 Pool 的运行时、标签或能力白名单",
                status_code=422,
            )
        return profile

    def _event(
        self,
        *,
        pool_id: UUID,
        kind: RunnerEventKind,
        message: str,
        runner_id: UUID | None = None,
        task_id: UUID | None = None,
        lease_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self._repository.add(
            RunnerEvent(
                pool_id=pool_id,
                runner_id=runner_id,
                task_id=task_id,
                lease_id=lease_id,
                kind=kind.value,
                message=message,
                details=details or {},
            )
        )


def _task_matches(task: RunnerTask, runner: Runner) -> bool:
    return set(task.required_labels).issubset(set(runner.labels)) and set(
        task.required_capabilities
    ).issubset(set(runner.capabilities))


def _plan_runner_type(plan: WorkflowExecutionPlan) -> RunnerType:
    definitions = (
        tuple(child.definition for child in plan.children)
        if isinstance(plan, WorkflowBatchPlan)
        else (plan.definition,)
    )
    types: list[RunnerType] = []
    for definition in definitions:
        for node in definition.nodes:
            invocation = legacy_node_adapter.compile(node)
            manifest = builtin_capability_registry.get(
                invocation.capability_id, invocation.capability_version
            )
            types.append(manifest.runner_type if manifest is not None else RunnerType.PLUGIN)
    return select_runner_type(types)


def _organization_id() -> UUID | None:
    context = get_tenant_context()
    return context.organization_id if context is not None else None


def _new_token(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(48)}"


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _require_token_prefix(raw_token: str, prefix: str) -> None:
    if not raw_token.startswith(prefix) or len(raw_token) < len(prefix) + 32:
        raise AppError(
            code="RUNNER_AUTHENTICATION_FAILED",
            message="Runner 身份令牌无效",
            status_code=401,
        )


def _fenced_error() -> AppError:
    return AppError(
        code="RUNNER_LEASE_FENCED",
        message="Lease 已过期或 Fencing Token 已失效",
        status_code=409,
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
