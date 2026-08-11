import json
from collections.abc import AsyncIterator, Awaitable
from typing import cast
from uuid import UUID

from redis.asyncio import Redis

from app.engine.events import ExecutionEvent, ExecutionEventType
from app.engine.events import ExecutionEventBus as ExecutionEventBus

__all__ = ["ExecutionEvent", "ExecutionEventBus", "ExecutionEventType", "RedisExecutionEventBus"]

EVENT_HISTORY_LIMIT = 500


class RedisExecutionEventBus:
    def __init__(self, client: Redis, *, retention_seconds: int) -> None:
        self._client = client
        self._retention_seconds = retention_seconds

    async def publish(self, event: ExecutionEvent) -> ExecutionEvent:
        sequence_key = _sequence_key(event.execution_id)
        history_key = _history_key(event.execution_id)
        sequence = int(await self._client.incr(sequence_key))
        stored = event.model_copy(update={"sequence": sequence})
        serialized = stored.model_dump_json()
        pipeline = self._client.pipeline(transaction=True)
        pipeline.rpush(history_key, serialized)
        pipeline.ltrim(history_key, -EVENT_HISTORY_LIMIT, -1)
        pipeline.expire(history_key, self._retention_seconds)
        pipeline.expire(sequence_key, self._retention_seconds)
        pipeline.publish(_channel(event.execution_id), serialized)
        await pipeline.execute()
        return stored

    async def _history(self, execution_id: UUID) -> list[ExecutionEvent]:
        values = await cast(
            Awaitable[list[str]],
            self._client.lrange(_history_key(execution_id), 0, -1),
        )
        return [ExecutionEvent.model_validate(json.loads(value)) for value in values]

    async def subscribe(
        self, execution_id: UUID, *, after_sequence: int = 0
    ) -> AsyncIterator[ExecutionEvent]:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(_channel(execution_id))
        latest_sequence = after_sequence
        try:
            for event in await self._history(execution_id):
                if event.sequence > latest_sequence:
                    latest_sequence = event.sequence
                    yield event
                    if event.type is ExecutionEventType.EXECUTION_COMPLETED:
                        return
            async for message in pubsub.listen():
                if message["type"] != "message" or not isinstance(message["data"], str):
                    continue
                event = ExecutionEvent.model_validate(json.loads(message["data"]))
                if event.sequence <= latest_sequence:
                    continue
                latest_sequence = event.sequence
                yield event
                if event.type is ExecutionEventType.EXECUTION_COMPLETED:
                    return
        finally:
            await pubsub.unsubscribe(_channel(execution_id))
            await pubsub.aclose()  # type: ignore[no-untyped-call]


def _channel(execution_id: UUID) -> str:
    return f"flowtest:workflow-execution:{execution_id}:events"


def _history_key(execution_id: UUID) -> str:
    return f"flowtest:workflow-execution:{execution_id}:event-history"


def _sequence_key(execution_id: UUID) -> str:
    return f"flowtest:workflow-execution:{execution_id}:event-sequence"
