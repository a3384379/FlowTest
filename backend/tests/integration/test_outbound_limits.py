"""Exercise the shared limiter against Redis with independent clients."""

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.core.config import settings
from app.services.outbound_limits import OutboundLimitPolicy, RedisOutboundLimiter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FLOWTEST_RUN_INTEGRATION") != "1",
        reason="Set FLOWTEST_RUN_INTEGRATION=1 to run infrastructure tests",
    ),
]


@pytest.mark.asyncio
async def test_project_outbound_limits_are_atomic_across_clients() -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    first_client = Redis.from_url(settings.redis_url, decode_responses=True)
    second_client = Redis.from_url(settings.redis_url, decode_responses=True)
    first = RedisOutboundLimiter(first_client, project_id)
    second = RedisOutboundLimiter(second_client, project_id)
    other = RedisOutboundLimiter(second_client, other_project_id)
    policy = OutboundLimitPolicy(concurrency_limit=1, requests_per_minute=2)
    try:
        decisions = await asyncio.gather(
            first.acquire(policy=policy, timeout_seconds=5),
            second.acquire(policy=policy, timeout_seconds=5),
        )
        granted = [decision for decision in decisions if decision.granted]
        rejected = [decision for decision in decisions if not decision.granted]
        assert len(granted) == len(rejected) == 1
        assert rejected[0].retry_after_seconds > 0
        assert (await other.acquire(policy=policy, timeout_seconds=5)).granted

        await first.release(granted[0].permit_id)
        second_grant = await second.acquire(policy=policy, timeout_seconds=5)
        assert second_grant.granted
        await second.release(second_grant.permit_id)

        rate_rejection = await first.acquire(policy=policy, timeout_seconds=5)
        assert not rate_rejection.granted
        assert rate_rejection.retry_after_seconds > 0
    finally:
        prefix = f"flowtest:outbound:{{{project_id}}}"
        other_prefix = f"flowtest:outbound:{{{other_project_id}}}"
        await first_client.delete(
            f"{prefix}:active", f"{prefix}:rate", f"{other_prefix}:active", f"{other_prefix}:rate"
        )
        await first_client.aclose()
        await second_client.aclose()
