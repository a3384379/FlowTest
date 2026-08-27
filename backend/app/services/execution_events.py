import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable
from time import monotonic
from typing import cast
from uuid import UUID

from redis.asyncio import Redis

from app.engine.events import ExecutionEvent, ExecutionEventType
from app.engine.events import ExecutionEventBus as ExecutionEventBus

__all__ = [
    "ExecutionEvent",
    "ExecutionEventBus",
    "ExecutionEventType",
    "InProcessExecutionEventBus",
    "RedisExecutionEventBus",
]

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


class InProcessExecutionEventBus:
    """Bounded event history and live fan-out for the single-process runtime."""

    def __init__(self, *, retention_seconds: int, history_limit: int = EVENT_HISTORY_LIMIT) -> None:
        self._retention_seconds = retention_seconds
        self._history_limit = history_limit
        self._history: dict[UUID, deque[ExecutionEvent]] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        self._history_times: dict[UUID, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        self._sequences: dict[UUID, int] = defaultdict(int)
        self._subscribers: dict[UUID, set[asyncio.Queue[ExecutionEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, event: ExecutionEvent) -> ExecutionEvent:
        async with self._lock:
            sequence = self._sequences[event.execution_id] + 1
            self._sequences[event.execution_id] = sequence
            stored = event.model_copy(update={"sequence": sequence})
            history = self._history[event.execution_id]
            timestamps = self._history_times[event.execution_id]
            now = monotonic()
            while timestamps and now - timestamps[0] > self._retention_seconds:
                timestamps.popleft()
                history.popleft()
            history.append(stored)
            timestamps.append(now)
            subscribers = tuple(self._subscribers[event.execution_id])
        for subscriber in subscribers:
            _offer_event(subscriber, stored)
        return stored

    async def subscribe(
        self, execution_id: UUID, *, after_sequence: int = 0
    ) -> AsyncIterator[ExecutionEvent]:
        queue: asyncio.Queue[ExecutionEvent] = asyncio.Queue(maxsize=self._history_limit)
        async with self._lock:
            self._prune(execution_id)
            self._subscribers[execution_id].add(queue)
            history = tuple(self._history.get(execution_id, ()))
        latest_sequence = after_sequence
        try:
            for event in history:
                if event.sequence > latest_sequence:
                    latest_sequence = event.sequence
                    yield event
                    if event.type is ExecutionEventType.EXECUTION_COMPLETED:
                        return
            while True:
                event = await queue.get()
                if event.sequence <= latest_sequence:
                    continue
                latest_sequence = event.sequence
                yield event
                if event.type is ExecutionEventType.EXECUTION_COMPLETED:
                    return
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(execution_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(execution_id, None)

    def _prune(self, execution_id: UUID) -> None:
        history = self._history.get(execution_id)
        timestamps = self._history_times.get(execution_id)
        if history is None or timestamps is None:
            return
        now = monotonic()
        while timestamps and now - timestamps[0] > self._retention_seconds:
            timestamps.popleft()
            history.popleft()


def _offer_event(queue: asyncio.Queue[ExecutionEvent], event: ExecutionEvent) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        queue.put_nowait(event)
