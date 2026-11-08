"""Real public API fixture: inactive creator differs from revoked machine token."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest import mcp_fault_setup, mcp_probe_setup
from scripts.selftest.io import read_json
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from test_selftest_mcp_probe_setup import binding
from test_tasking_api import ADMIN_EMAIL, ADMIN_PASSWORD
from test_tasking_api import tasking_context as tasking_context

from app.main import app


@pytest.mark.asyncio
async def test_public_inactive_creator_keeps_machine_enabled_and_unrevoked(
    tasking_context, monkeypatch, tmp_path
):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    original_api = mcp_probe_setup.ProbeAPI

    class API(original_api):
        def __init__(self, url, budget, token="", organization=None):
            super().__init__(url, budget, token, organization, transport=transport)

    monkeypatch.setattr(mcp_probe_setup, "ProbeAPI", API)
    monkeypatch.setattr(mcp_fault_setup, "ProbeAPI", API)
    original_login = mcp_probe_setup._login

    async def login(url, budget, email, password, *, new_actor=False):
        if email == "selftest-a@example.com":
            email, password = ADMIN_EMAIL, ADMIN_PASSWORD
        return await original_login(url, budget, email, password, new_actor=new_actor)

    monkeypatch.setattr(mcp_probe_setup, "_login", login)
    monkeypatch.setattr(
        mcp_probe_setup,
        "private_environment",
        lambda _: {"FLOWTEST_SELFTEST_RUNNER_PASSWORD": ADMIN_PASSWORD},
    )
    now = datetime.now(UTC)
    nonce = uuid4().hex
    budget = ProtocolHttpBudget(
        tmp_path / "budget.sqlite3", nonce, (now + timedelta(seconds=600)).timestamp()
    )
    issued = await mcp_probe_setup.provision(binding(), tmp_path, tmp_path, nonce, budget)
    updated, creator, machine, token, proof = await mcp_fault_setup.inactive_creator(
        binding(), issued, nonce, budget, tmp_path
    )
    assert creator != issued.fixture.governance.owner_user_id
    assert machine in updated.fixture.machine_ids and machine not in issued.fixture.machine_ids
    assert proof.machine_enabled and not proof.machine_revoked and not proof.creator_is_active
    async with httpx.AsyncClient(transport=transport, base_url="http://owned.test") as client:
        response = await client.post(
            "/api/v1/mcp/connection", headers={"Authorization": "Bearer " + token}, json={}
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MCP_AUTHENTICATION_REQUIRED"
    assert response.json()["error"]["trace_id"]
    saved = read_json(tmp_path / "inactive-fixture-receipt.json")
    assert saved["creator_id"] == str(creator) and saved["machine_id"] == str(machine)
    assert token not in str(saved) and "password" not in str(saved)


async def test_existing_fault_output_is_never_reused_or_rewritten(tmp_path):
    from scripts.selftest.io import HarnessError
    from scripts.selftest.mcp_fault_run import run

    state = tmp_path / "old-attempt"
    state.mkdir()
    previous = state / "immutable.json"
    previous.write_bytes(b'{"old":true}\n')
    with pytest.raises(HarnessError, match="OUTPUT_ALREADY_EXISTS"):
        await run(tmp_path / "no-stack", state)
    assert previous.read_bytes() == b'{"old":true}\n'
    assert sorted(p.name for p in state.iterdir()) == ["immutable.json"]
