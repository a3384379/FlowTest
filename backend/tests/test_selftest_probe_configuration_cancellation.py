"""A cancelled owner retains its lock until the bounded recreate thread is finished."""

import asyncio
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_selftest_mcp_probe_setup import binding

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.selftest import mcp_probe_setup
from scripts.selftest.bootstrap_journal import bootstrap_lock
from scripts.selftest.io import HarnessError


@pytest.mark.asyncio
async def test_cancelled_recreate_keeps_owner_lock_until_thread_finished(tmp_path, monkeypatch):
    entered, released = threading.Event(), threading.Event()

    def recreate(*args):
        entered.set()
        assert released.wait(2)
        return binding()

    monkeypatch.setattr(mcp_probe_setup, "configure", recreate)
    frozen = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=600))

    async def owner():
        with bootstrap_lock(tmp_path, "2" * 32):
            return await mcp_probe_setup.configure_owned(
                binding(), tmp_path, tmp_path, frozen, None, "2" * 32
            )

    task = asyncio.create_task(owner())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        with (
            pytest.raises(HarnessError, match="BOOTSTRAP_IN_PROGRESS"),
            bootstrap_lock(tmp_path, "2" * 32),
        ):
            pass
    finally:
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    with bootstrap_lock(tmp_path, "2" * 32):
        assert not entered.is_set() or released.is_set()
