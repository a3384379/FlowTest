import os
import socket
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import check_database
from app.core.redis import check_redis
from app.core.storage import check_storage, ensure_storage_bucket
from app.domain.data_nodes import CredentialKind
from app.domain.network import OutboundNetworkPolicy
from app.services.credentials import CredentialMaterial
from app.services.data_nodes import InfrastructureDataNodeRunner
from app.services.execution_events import (
    ExecutionEvent,
    ExecutionEventType,
    RedisExecutionEventBus,
)

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


class IntegrationOutboundGuard:
    async def enforce_target(
        self,
        host: str,
        port: int,
        _policy: OutboundNetworkPolicy,
    ) -> tuple[str, ...]:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return tuple(sorted({str(record[4][0]) for record in records}))
