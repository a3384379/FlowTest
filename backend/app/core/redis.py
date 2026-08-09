from redis.asyncio import Redis

from app.core.config import settings

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def check_redis() -> None:
    response = await redis_client.ping()
    if not response:
        raise ConnectionError("Redis ping returned a false response")


async def close_redis() -> None:
    await redis_client.aclose()
