"""Offline outbound limits share atomic state across workflow instances."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.outbound_limits import OutboundPermit, OutboundRateWindow
from app.services import outbound_limits
from app.services.outbound_limits import OutboundLimitPolicy, SqliteOutboundLimiter


@pytest.mark.asyncio
async def test_sqlite_outbound_limits_share_capacity_and_rate(tmp_path, monkeypatch) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbound.db'}")
    monkeypatch.setattr(outbound_limits, "engine", test_engine)
    async with test_engine.begin() as connection:
        await connection.run_sync(OutboundPermit.__table__.create)
        await connection.run_sync(OutboundRateWindow.__table__.create)
    project_id = uuid4()
    first = SqliteOutboundLimiter(project_id)
    second = SqliteOutboundLimiter(project_id)
    other = SqliteOutboundLimiter(uuid4())
    policy = OutboundLimitPolicy(concurrency_limit=1, requests_per_minute=2)
    try:
        decisions = await asyncio.gather(
            first.acquire(policy=policy, timeout_seconds=5),
            second.acquire(policy=policy, timeout_seconds=5),
        )
        granted = [decision for decision in decisions if decision.granted]
        rejected = [decision for decision in decisions if not decision.granted]
        assert len(granted) == len(rejected) == 1
        assert (await other.acquire(policy=policy, timeout_seconds=5)).granted

        await second.release(granted[0].permit_id, owner="wrong-owner")
        assert not (await second.acquire(policy=policy, timeout_seconds=5)).granted
        await first.release(granted[0].permit_id)
        second_grant = await second.acquire(policy=policy, timeout_seconds=5)
        assert second_grant.granted
        await second.release(second_grant.permit_id)
        assert not (await first.acquire(policy=policy, timeout_seconds=5)).granted
    finally:
        await test_engine.dispose()
