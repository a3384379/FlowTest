import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Protocol, cast


class RedisRateClient(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RedisRateLimiter:
    def __init__(self, client: RedisRateClient) -> None:
        self._client = client

    async def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        result = cast(
            list[int],
            await self._client.eval(
                RATE_LIMIT_SCRIPT,
                1,
                f"flowtest:rate:{key}",
                window_seconds,
            ),
        )
        current, ttl = int(result[0]), max(1, int(result[1]))
        return RateLimitDecision(
            allowed=current <= limit,
            limit=limit,
            remaining=max(0, limit - current),
            retry_after=ttl,
        )


class InProcessRateLimiter:
    """Single-process fixed-window limiter with no Redis dependency."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = monotonic()
        async with self._lock:
            count, expires_at = self._buckets.get(key, (0, now + window_seconds))
            if expires_at <= now:
                count = 0
                expires_at = now + window_seconds
            count += 1
            self._buckets[key] = (count, expires_at)
            if len(self._buckets) > 10_000:
                self._buckets = {
                    bucket: value for bucket, value in self._buckets.items() if value[1] > now
                }
        retry_after = max(1, int(expires_at - now))
        return RateLimitDecision(
            allowed=count <= limit,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after=retry_after,
        )
