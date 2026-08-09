from dataclasses import dataclass
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
