"""Real gateway port ownership requires one server for two separately authorized SDK clients."""

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest import quality_sessions
from scripts.selftest.io import HarnessError
from test_selftest_ci_runner_lineage import binding


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_reader", [False, True])
async def test_two_http_identities_share_gateway_and_cleanup_in_reverse_order(
    tmp_path, monkeypatch, fail_reader
):
    order = []
    active = False

    @asynccontextmanager
    async def gateway(*args, **kwargs):
        nonlocal active
        if active:
            raise OSError("fixed port already bound")
        active = True
        order.append("gateway-start")
        try:
            yield SimpleNamespace(url="http://synthetic.invalid/mcp")
        finally:
            order.append("gateway-stop")
            active = False

    @asynccontextmanager
    async def protocol(*, url, token, batch_key, output_dir):
        assert active and url == "http://synthetic.invalid/mcp"
        order.append("open-" + token)
        if token == "reader" and fail_reader:
            raise HarnessError("READER_DISCOVERY_FAILED")
        try:
            yield token
        finally:
            order.append("close-" + token)

    monkeypatch.setattr(quality_sessions, "container_http_gateway", gateway)
    monkeypatch.setattr(quality_sessions, "http_protocol", protocol)

    async def run():
        async with quality_sessions.open_protocols(
            binding(),
            "streamable-http",
            "writer",
            "reader",
            "batch",
            tmp_path,
            tmp_path,
            datetime.now(UTC) + timedelta(seconds=30),
        ) as pair:
            assert pair == ("writer", "reader")

    if fail_reader:
        with pytest.raises(HarnessError, match="READER_DISCOVERY_FAILED"):
            await run()
    else:
        await run()
    assert not active
    assert order == [
        "gateway-start",
        "open-writer",
        "open-reader",
        *([] if fail_reader else ["close-reader"]),
        "close-writer",
        "gateway-stop",
    ]


@pytest.mark.asyncio
async def test_quality_cannot_collapse_two_identities(tmp_path):
    with pytest.raises(HarnessError, match="DISTINCT_IDENTITIES_REQUIRED"):
        async with quality_sessions.open_protocols(
            binding(),
            "streamable-http",
            "same",
            "same",
            "batch",
            tmp_path,
            tmp_path,
            datetime.now(UTC) + timedelta(seconds=30),
        ):
            pytest.fail("must reject before gateway startup")
