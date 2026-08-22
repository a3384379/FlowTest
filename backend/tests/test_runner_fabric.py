import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from app.domain.network import OutboundNetworkPolicy
from app.domain.runner_fabric import RunnerProfile, normalize_labels
from app.engine.contracts import WorkflowDefinition
from app.engine.scheduler import CancellationToken
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.runner_fabric import RunnerLeaseRecord, RunnerTask
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution
from app.repositories.runner_fabric import _advisory_lock_key
from app.runner.agent import RunnerAgent, configuration_from_environment
from app.runner.client import RunnerControlPlaneClient
from app.runner.results import RunnerExecutionResult
from app.runner.workflow import RemoteWorkflowExecutor
from app.schemas.runner_fabric import (
    RunnerAgentConfiguration,
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
from app.services.runner_fabric import RunnerFabricService
from app.services.workflow_plan_codec import encode_execution_plan
from app.services.workflow_snapshots import PreparedExecution
from app.services.workflows import WorkflowRunPlan, WorkflowService


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
        first_lease = await session.get(RunnerLeaseRecord, first.lease_id)
        assert first_lease is not None
        first_lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        second = await service.claim(runner_token=second_token)
        assert second is not None
        assert second.task.fencing_token == first.task.fencing_token + 1
        assert second.task.attempt == 2

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
    assert control.closed == 1
    bad_lease = lease.model_copy(
        update={"task": lease.task.model_copy(update={"plan_sha256": "0" * 64})}
    )
    await agent._execute(bad_lease)
    assert control.failed == [bad_lease.lease_id]


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


def _lease_fixture(plan: WorkflowRunPlan) -> RunnerLeaseResponse:
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
    connected: int = 0
    closed: int = 0
    completed: list[UUID] = field(default_factory=list)
    failed: list[UUID] = field(default_factory=list)

    async def connect(self) -> None:
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
