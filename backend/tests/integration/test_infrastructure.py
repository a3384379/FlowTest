import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.core.config import settings
from app.core.database import check_database
from app.core.redis import check_redis
from app.core.storage import check_storage, ensure_storage_bucket
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
