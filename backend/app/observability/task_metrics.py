from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Protocol, cast

from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

QUEUE_NAMES = ("general", "data", "ai")
PRIORITY_STEPS = (0, 3, 6, 9)
PRIORITY_SEPARATOR = "\x06\x16"
WORKER_KEY_PREFIX = "flowtest:celery:worker:"
TASK_COUNTER_KEY = "flowtest:celery:tasks"
WORKER_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class TaskMetricsSnapshot:
    queue_depths: Mapping[str, int]
    active_workers: int
    task_counts: Mapping[str, int]


class TaskMetricsReader(Protocol):
    async def read(self) -> TaskMetricsSnapshot: ...


class RedisTaskMetricsReader:
    async def read(self) -> TaskMetricsSnapshot:
        broker = Redis.from_url(settings.celery_broker_url, decode_responses=True)
        state = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            queue_depths = {queue: await self._queue_depth(broker, queue) for queue in QUEUE_NAMES}
            worker_keys = [key async for key in state.scan_iter(f"{WORKER_KEY_PREFIX}*")]
            raw_counts = await state.hgetall(TASK_COUNTER_KEY)
            return TaskMetricsSnapshot(
                queue_depths=queue_depths,
                active_workers=len(worker_keys),
                task_counts={status: int(count) for status, count in raw_counts.items()},
            )
        except RedisError as error:
            raise OSError("Celery metrics store is unavailable") from error
        finally:
            await broker.aclose()
            await state.aclose()

    async def _queue_depth(self, client: Redis, queue: str) -> int:
        keys = [queue]
        keys.extend(
            f"{queue}{PRIORITY_SEPARATOR}{priority}" for priority in PRIORITY_STEPS if priority != 0
        )
        lengths = await cast(Awaitable[int], client.llen(keys[0]))
        for key in keys[1:]:
            lengths += await cast(Awaitable[int], client.llen(key))
        return int(lengths)


class InProcessTaskMetricsReader:
    """Task metrics for the Standalone dispatcher."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._queue_depths: dict[str, int] = {queue: 0 for queue in QUEUE_NAMES}
        self._active_workers = 0
        self._task_counts: dict[str, int] = {}

    async def read(self) -> TaskMetricsSnapshot:
        with self._lock:
            return TaskMetricsSnapshot(
                queue_depths=dict(self._queue_depths),
                active_workers=self._active_workers,
                task_counts=dict(self._task_counts),
            )

    def set_active_workers(self, count: int) -> None:
        with self._lock:
            self._active_workers = max(0, count)

    def set_queue_depth(self, queue: str, depth: int) -> None:
        with self._lock:
            self._queue_depths[queue] = max(0, depth)

    def record_task(self, status: str) -> None:
        with self._lock:
            self._task_counts[status] = self._task_counts.get(status, 0) + 1


def record_worker_heartbeat(hostname: str) -> None:
    _write_worker_state(hostname, "active")


def remove_worker(hostname: str) -> None:
    client = _state_client()
    try:
        client.delete(_worker_key(hostname))
    except RedisError:
        return
    finally:
        client.close()


def record_task_result(status: str) -> None:
    client = _state_client()
    try:
        client.hincrby(TASK_COUNTER_KEY, status, 1)
    except RedisError:
        return
    finally:
        client.close()


def _write_worker_state(hostname: str, state: str) -> None:
    client = _state_client()
    try:
        client.set(_worker_key(hostname), state, ex=WORKER_TTL_SECONDS)
    except RedisError:
        return
    finally:
        client.close()


def _worker_key(hostname: str) -> str:
    return f"{WORKER_KEY_PREFIX}{hostname[:200]}"


def _state_client() -> SyncRedis:
    return SyncRedis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
