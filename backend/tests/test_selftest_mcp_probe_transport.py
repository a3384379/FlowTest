"""Pre-dispatch budget behavior; no candidate process or profile is started."""

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.shared.message import SessionMessage
from mcp_types import JSONRPCRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_probe_setup import ProbeRPCBudget
from scripts.selftest.mcp_probe_transport import ProbeWireJournal


def rpc(identifier):
    return SessionMessage(
        JSONRPCRequest(jsonrpc="2.0", id=identifier, method="tools/call", params={"name": "probe"})
    )


def test_rpc_reserves_shared_budget_before_any_wire_dispatch(tmp_path):
    budget = ProtocolHttpBudget(tmp_path / "budget.sqlite3", "nonce", time.time() + 60)
    prepared = SimpleNamespace(budget=budget, rpc_budget=ProbeRPCBudget())
    journal = ProbeWireJournal(prepared)
    journal.sent(rpc(1))
    assert budget.counts() == (1, 0) and budget.tool_counts() == (1, 0)
    assert prepared.rpc_budget.admitted == 1 and len(journal.requests) == 1
    for _ in range(499):
        assert budget.reserve()
    with pytest.raises(HarnessError, match="CANDIDATE_RPC_BUDGET"):
        journal.sent(rpc(2))
    assert budget.counts() == (500, 1)
    assert prepared.rpc_budget.rejected == 1 and len(journal.requests) == 1


def test_failed_tool_admission_still_consumes_conservative_rpc_reservation(tmp_path):
    budget = ProtocolHttpBudget(tmp_path / "budget.sqlite3", "nonce", time.time() + 60)
    for _ in range(100):
        assert budget.reserve_tool()
    prepared = SimpleNamespace(budget=budget, rpc_budget=ProbeRPCBudget())
    journal = ProbeWireJournal(prepared)
    with pytest.raises(HarnessError, match="TOOL_BUDGET"):
        journal.sent(rpc(1))
    assert prepared.rpc_budget.admitted == 1 and not journal.requests
    assert budget.tool_counts() == (100, 1)
