import asyncio
import os
import socket
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import check_database
from app.core.errors import AppError
from app.core.redis import check_redis
from app.core.security import password_service
from app.core.storage import check_storage, ensure_storage_bucket
from app.domain.data_nodes import CredentialKind
from app.domain.governance import QuotaDimension
from app.domain.network import OutboundNetworkPolicy
from app.domain.tenant import OrganizationRole
from app.models.access import AuditLog, User
from app.models.governance import OrganizationGovernance
from app.models.organizations import Organization, OrganizationMember
from app.services.credentials import CredentialMaterial
from app.services.data_nodes import InfrastructureDataNodeRunner
from app.services.execution_events import (
    ExecutionEvent,
    ExecutionEventType,
    RedisExecutionEventBus,
)
from app.services.organization_governance import OrganizationQuotaService
from app.services.organizations import OrganizationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FLOWTEST_RUN_INTEGRATION") != "1",
        reason="Set FLOWTEST_RUN_INTEGRATION=1 to run infrastructure tests",
    ),
]


async def test_postgres_redis_and_storage_are_available() -> None:
    await check_database()
    await check_redis()
    await ensure_storage_bucket()
    await check_storage()


async def test_redis_execution_events_are_ordered_and_replayable() -> None:
    execution_id = uuid4()
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        bus = RedisExecutionEventBus(client, retention_seconds=60)
        first = await bus.publish(
            ExecutionEvent(
                type=ExecutionEventType.EXECUTION_STARTED,
                execution_id=execution_id,
                emitted_at=datetime.now(UTC),
                execution_status="running",
            )
        )
        await bus.publish(
            ExecutionEvent(
                type=ExecutionEventType.EXECUTION_COMPLETED,
                execution_id=execution_id,
                emitted_at=datetime.now(UTC),
                execution_status="passed",
            )
        )

        replayed = [
            event async for event in bus.subscribe(execution_id, after_sequence=first.sequence)
        ]

        assert [event.type for event in replayed] == [ExecutionEventType.EXECUTION_COMPLETED]
        assert replayed[0].sequence == first.sequence + 1
    finally:
        await client.aclose()


async def test_data_nodes_execute_real_postgres_and_redis_reads() -> None:
    runner = InfrastructureDataNodeRunner(
        OutboundNetworkPolicy(),
        outbound_guard=IntegrationOutboundGuard(),  # type: ignore[arg-type]
    )
    database = make_url(settings.database_url)
    postgres = CredentialMaterial(
        id=uuid4(),
        project_id=uuid4(),
        name="Integration PostgreSQL",
        kind=CredentialKind.POSTGRESQL,
        host=database.host or "localhost",
        port=database.port or 5432,
        database_name=database.database or "flowtest",
        username=database.username or "",
        secret=database.password or "",
        tls_enabled=False,
    )
    sql_result = await runner.execute_sql(
        postgres,
        "SELECT CAST(:value AS INTEGER) AS value",
        {"value": 42},
        5,
    )
    assert sql_result == {"row_count": 1, "rows": [{"value": 42}]}

    redis_url = urlsplit(settings.redis_url)
    key = f"flowtest:integration:data-node:{uuid4()}"
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.set(key, "cached")
    try:
        redis = CredentialMaterial(
            id=uuid4(),
            project_id=uuid4(),
            name="Integration Redis",
            kind=CredentialKind.REDIS,
            host=redis_url.hostname or "localhost",
            port=redis_url.port or 6379,
            database_name=redis_url.path.removeprefix("/") or "0",
            username=redis_url.username or "",
            secret=redis_url.password or "",
            tls_enabled=redis_url.scheme == "rediss",
        )
        redis_result = await runner.execute_redis(redis, "GET", [key], 5)
        assert redis_result == {"command": "GET", "result": "cached"}
    finally:
        await client.delete(key)
        await client.aclose()


async def test_postgres_serializes_concurrent_organization_member_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quota_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    quota_sessions = async_sessionmaker(quota_engine, expire_on_commit=False)
    suffix = uuid4().hex
    actor_id: UUID
    organization_id: UUID
    target_ids: list[UUID]
    async with quota_sessions() as session:
        actor = User(
            email=f"quota-admin-{suffix}@example.com",
            display_name="Integration quota administrator",
            password_hash=password_service.hash("integration-password-123!"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        targets = [
            User(
                email=f"quota-target-{index}-{suffix}@example.com",
                display_name=f"Integration quota target {index}",
                password_hash=password_service.hash("integration-password-123!"),
                is_active=True,
                is_system_admin=False,
                requires_password_change=False,
            )
            for index in range(2)
        ]
        session.add_all([actor, *targets])
        await session.flush()
        organization = Organization(
            name="Integration member quota",
            slug=f"integration-member-quota-{suffix}",
            description="",
            enabled=True,
            created_by_id=actor.id,
        )
        session.add(organization)
        await session.flush()
        session.add(
            OrganizationGovernance(
                organization_id=organization.id,
                quota_policies={
                    QuotaDimension.USER_COUNT.value: {
                        "mode": "hard_limit",
                        "limit": 1,
                        "warn_at": None,
                    }
                },
                runner_policy={},
                active_key_version=1,
            )
        )
        await session.commit()
        actor_id = actor.id
        organization_id = organization.id
        target_ids = [target.id for target in targets]

    original_usage = OrganizationQuotaService._usage
    second_count_observed = asyncio.Event()
    count_calls = 0
    count_lock = asyncio.Lock()

    async def synchronized_usage(
        quota_service: OrganizationQuotaService,
        current_organization_id: UUID,
        dimension: QuotaDimension,
    ) -> int:
        nonlocal count_calls
        usage = await original_usage(quota_service, current_organization_id, dimension)
        async with count_lock:
            count_calls += 1
            if count_calls >= 2:
                second_count_observed.set()
        try:
            await asyncio.wait_for(second_count_observed.wait(), timeout=0.5)
        except TimeoutError:
            second_count_observed.set()
        return usage

    monkeypatch.setattr(OrganizationQuotaService, "_usage", synchronized_usage)

    async def add_member(user_id: UUID) -> OrganizationMember:
        async with quota_sessions() as session:
            actor = await session.get(User, actor_id)
            assert actor is not None
            return await OrganizationService(session).upsert_member(
                actor=actor,
                organization_id=organization_id,
                user_id=user_id,
                role=OrganizationRole.MEMBER,
            )

    try:
        outcomes = await asyncio.gather(
            *(add_member(user_id) for user_id in target_ids),
            return_exceptions=True,
        )
        successes = [outcome for outcome in outcomes if isinstance(outcome, OrganizationMember)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, AppError)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0].code == "ORGANIZATION_QUOTA_EXCEEDED"
        async with quota_sessions() as session:
            member_count = await session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.organization_id == organization_id)
            )
        assert member_count == 1
    finally:
        async with quota_sessions() as session:
            await session.execute(
                delete(AuditLog).where(AuditLog.organization_id == organization_id)
            )
            await session.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.organization_id == organization_id
                )
            )
            await session.execute(
                delete(OrganizationGovernance).where(
                    OrganizationGovernance.organization_id == organization_id
                )
            )
            await session.execute(delete(Organization).where(Organization.id == organization_id))
            await session.execute(delete(User).where(User.id.in_([actor_id, *target_ids])))
            await session.commit()
        await quota_engine.dispose()


class IntegrationOutboundGuard:
    async def enforce_target(
        self,
        host: str,
        port: int,
        _policy: OutboundNetworkPolicy,
    ) -> tuple[str, ...]:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return tuple(sorted({str(record[4][0]) for record in records}))
