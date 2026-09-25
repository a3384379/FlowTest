"""Cross-worker outbound admission shared by local workers and runner control."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from math import ceil
from time import time
from typing import Protocol, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import engine
from app.domain.runtime_profiles import RuntimeProfile
from app.engine.scheduler import NodeExecutionError


class OutboundRedisClient(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


ACQUIRE_SCRIPT = """
local concurrency = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local token = ARGV[3]
local lease_ms = tonumber(ARGV[4])
local clock = redis.call('TIME')
local now_ms = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
if concurrency > 0 then
  redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
  if redis.call('ZCARD', KEYS[1]) >= concurrency then
    local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, math.max(1, tonumber(first[2]) - now_ms)}
  end
end
if rate > 0 then
  local used = tonumber(redis.call('GET', KEYS[2]) or '0')
  if used >= rate then
    return {0, math.max(1, redis.call('PTTL', KEYS[2]))}
  end
end
if concurrency > 0 then
  redis.call('ZADD', KEYS[1], now_ms + lease_ms, token)
  local active_ttl = redis.call('PTTL', KEYS[1])
  if active_ttl < lease_ms + 60000 then
    redis.call('PEXPIRE', KEYS[1], lease_ms + 60000)
  end
end
if rate > 0 then
  local count = redis.call('INCR', KEYS[2])
  if count == 1 then redis.call('PEXPIRE', KEYS[2], 60000) end
end
return {1, 0}
"""

RELEASE_SCRIPT = """
redis.call('ZREM', KEYS[1], ARGV[1])
if redis.call('ZCARD', KEYS[1]) == 0 then redis.call('DEL', KEYS[1]) end
return 1
"""


@dataclass(frozen=True, slots=True)
class OutboundLimitPolicy:
    concurrency_limit: int | None
    requests_per_minute: int | None

    @property
    def enabled(self) -> bool:
        return self.concurrency_limit is not None or self.requests_per_minute is not None


@dataclass(frozen=True, slots=True)
class OutboundPermitDecision:
    granted: bool
    permit_id: UUID | None
    retry_after_seconds: float


class OutboundPermitStore(Protocol):
    async def acquire(
        self, *, policy: OutboundLimitPolicy, timeout_seconds: float, owner: str = "local"
    ) -> OutboundPermitDecision: ...

    async def release(self, permit_id: UUID | None, *, owner: str = "local") -> None: ...


class RedisOutboundLimiter:
    def __init__(self, client: OutboundRedisClient, project_id: UUID) -> None:
        self._client = client
        key_prefix = f"flowtest:outbound:{{{project_id}}}"
        self._active_key = f"{key_prefix}:active"
        self._rate_key = f"{key_prefix}:rate"

    async def acquire(
        self, *, policy: OutboundLimitPolicy, timeout_seconds: float, owner: str = "local"
    ) -> OutboundPermitDecision:
        if not policy.enabled:
            return OutboundPermitDecision(True, None, 0)
        permit_id = uuid4()
        lease_ms = _lease_ms(timeout_seconds)
        try:
            raw = await self._client.eval(
                ACQUIRE_SCRIPT,
                2,
                self._active_key,
                self._rate_key,
                policy.concurrency_limit or 0,
                policy.requests_per_minute or 0,
                f"{owner}:{permit_id}",
                lease_ms,
            )
        except RedisError as error:
            raise NodeExecutionError(
                code="OUTBOUND_LIMITER_UNAVAILABLE",
                message="出站请求限额服务不可用。请求尚未发送",
            ) from error
        result = cast(list[int], raw)
        if int(result[0]) != 1:
            return OutboundPermitDecision(False, None, max(0.001, int(result[1]) / 1000))
        return OutboundPermitDecision(True, permit_id, 0)

    async def release(self, permit_id: UUID | None, *, owner: str = "local") -> None:
        if permit_id is None:
            return
        try:
            await self._client.eval(RELEASE_SCRIPT, 1, self._active_key, f"{owner}:{permit_id}")
        except RedisError as error:
            raise NodeExecutionError(
                code="OUTBOUND_LIMITER_RELEASE_FAILED",
                message="请求可能已完成。出站许可未能回收。不会自动重试",
            ) from error


class SqliteOutboundLimiter:
    """Atomic project admission for the offline, in-process runtime."""

    def __init__(self, project_id: UUID) -> None:
        self._project_id = str(project_id)

    async def acquire(
        self, *, policy: OutboundLimitPolicy, timeout_seconds: float, owner: str = "local"
    ) -> OutboundPermitDecision:
        if not policy.enabled:
            return OutboundPermitDecision(True, None, 0)
        now_ms = int(time() * 1000)
        permit_id = uuid4()
        try:
            async with engine.connect() as connection:
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
                await connection.execute(
                    text("DELETE FROM outbound_permits WHERE expires_at_ms <= :now_ms"),
                    {"now_ms": now_ms},
                )
                active = (
                    await connection.execute(
                        text(
                            "SELECT COUNT(*), MIN(expires_at_ms) FROM outbound_permits "
                            "WHERE project_id = :project_id"
                        ),
                        {"project_id": self._project_id},
                    )
                ).one()
                if (
                    policy.concurrency_limit is not None
                    and int(active[0]) >= policy.concurrency_limit
                ):
                    await connection.rollback()
                    retry = max(1, int(active[1]) - now_ms) / 1000
                    return OutboundPermitDecision(False, None, retry)
                window = (
                    await connection.execute(
                        text(
                            "SELECT started_at_ms, used FROM outbound_rate_windows "
                            "WHERE project_id = :project_id"
                        ),
                        {"project_id": self._project_id},
                    )
                ).one_or_none()
                if window is None:
                    started, used = now_ms, 0
                else:
                    previous_start = int(window[0])
                    fresh_window = now_ms < previous_start or now_ms - previous_start >= 60_000
                    started = now_ms if fresh_window else previous_start
                    used = 0 if fresh_window else int(window[1])
                if policy.requests_per_minute is not None and used >= policy.requests_per_minute:
                    await connection.rollback()
                    retry = max(1, 60_000 - (now_ms - started)) / 1000
                    return OutboundPermitDecision(False, None, retry)
                if policy.concurrency_limit is not None:
                    await connection.execute(
                        text(
                            "INSERT INTO outbound_permits "
                            "(permit_id, project_id, owner, expires_at_ms) "
                            "VALUES (:permit_id, :project_id, :owner, :expires_at_ms)"
                        ),
                        {
                            "permit_id": str(permit_id),
                            "project_id": self._project_id,
                            "owner": owner,
                            "expires_at_ms": now_ms + _lease_ms(timeout_seconds),
                        },
                    )
                if policy.requests_per_minute is not None:
                    await connection.execute(
                        text(
                            "INSERT INTO outbound_rate_windows (project_id, started_at_ms, used) "
                            "VALUES (:project_id, :started_at_ms, :used) "
                            "ON CONFLICT(project_id) DO UPDATE SET "
                            "started_at_ms = excluded.started_at_ms, used = excluded.used"
                        ),
                        {
                            "project_id": self._project_id,
                            "started_at_ms": started,
                            "used": used + 1,
                        },
                    )
                await connection.commit()
        except SQLAlchemyError as error:
            raise NodeExecutionError(
                code="OUTBOUND_LIMITER_UNAVAILABLE",
                message="出站请求限额服务不可用。请求尚未发送",
            ) from error
        return OutboundPermitDecision(True, permit_id if policy.concurrency_limit else None, 0)

    async def release(self, permit_id: UUID | None, *, owner: str = "local") -> None:
        if permit_id is None:
            return
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM outbound_permits "
                        "WHERE permit_id = :permit_id AND project_id = :project_id "
                        "AND owner = :owner"
                    ),
                    {"permit_id": str(permit_id), "project_id": self._project_id, "owner": owner},
                )
        except SQLAlchemyError as error:
            raise NodeExecutionError(
                code="OUTBOUND_LIMITER_RELEASE_FAILED",
                message="请求可能已完成。出站许可未能回收。不会自动重试",
            ) from error


class ProjectOutboundAdmission:
    def __init__(self, limiter: OutboundPermitStore, policy: OutboundLimitPolicy) -> None:
        self._limiter = limiter
        self._policy = policy

    @asynccontextmanager
    async def window(self, timeout_seconds: float) -> AsyncIterator[None]:
        while True:
            decision = await self._limiter.acquire(
                policy=self._policy, timeout_seconds=timeout_seconds
            )
            if decision.granted:
                break
            await asyncio.sleep(min(0.5, decision.retry_after_seconds))
        try:
            yield
        finally:
            await self._limiter.release(decision.permit_id)


@asynccontextmanager
async def project_outbound_limiter(project_id: UUID) -> AsyncIterator[RedisOutboundLimiter]:
    client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        yield RedisOutboundLimiter(client, project_id)
    finally:
        await client.aclose()


@asynccontextmanager
async def project_outbound_admission(
    project_id: UUID, policy: OutboundLimitPolicy
) -> AsyncIterator[ProjectOutboundAdmission | None]:
    if not policy.enabled:
        yield None
        return
    if settings.runtime_profile is RuntimeProfile.STANDALONE:
        yield ProjectOutboundAdmission(SqliteOutboundLimiter(project_id), policy)
        return
    async with project_outbound_limiter(project_id) as limiter:
        yield ProjectOutboundAdmission(limiter, policy)


def _lease_ms(timeout_seconds: float) -> int:
    return min(3_630_000, max(1_000, ceil(timeout_seconds * 1000) + 30_000))
