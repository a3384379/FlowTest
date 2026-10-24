"""Synthetic executable/ASGI tests only. No Codex exec or model/provider invocation."""

from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_attempts import AttemptStore  # noqa: E402
from scripts.selftest.host_events import EventLedger  # noqa: E402
from scripts.selftest.host_launch import CodexLaunchPlan, VerifiedGrant  # noqa: E402
from scripts.selftest.host_runner import run_process  # noqa: E402
from scripts.selftest.io import HarnessError  # noqa: E402
from test_selftest_host_adapter import authorization, gateway  # noqa: E402


def grant():
    value = authorization()
    return VerifiedGrant(value, canonical_digest(value.model_dump(mode="json")))


def test_one_signed_authorization_is_reserved_exactly_once_even_by_concurrent_owners(tmp_path):
    approved = grant()
    store = AttemptStore(tmp_path / "attempts")

    def reserve(_index):
        try:
            return store.reserve(approved, uuid4()).attempt_id
        except HarnessError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(8)))
    assert sum(not isinstance(item, str) for item in results) == 1
    assert results.count("HOST_AUTHORIZATION_ATTEMPT_ALREADY_RESERVED") == 7


def test_attempt_cas_terminal_and_unknown_phase_cannot_be_replayed(tmp_path):
    approved = grant()
    store = AttemptStore(tmp_path / "attempts")
    original = store.reserve(approved, uuid4())
    running = store.transition(approved, original, "workflow_running")
    with pytest.raises(HarnessError, match="REVISION_CHANGED"):
        store.transition(approved, original, "workflow_running")
    with pytest.raises(HarnessError, match="TRANSITION_FORBIDDEN"):
        store.transition(approved, running, "workflow_running")
    error = store.transition(approved, running, "error", reason_code="UNKNOWN_MUTATION")
    with pytest.raises(HarnessError, match="TRANSITION_FORBIDDEN"):
        store.transition(approved, error, "workflow_running")


@pytest.mark.parametrize(
    "kind", ["command_execution", "file_change", "web_search", "collab_tool_call", "future_tool"]
)
def test_non_mcp_model_tools_fail_closed_in_actual_event_stream(kind):
    ledger = EventLedger(frozenset({"flowtest.inspect_contract"}))
    ledger.accept(b'{"type":"thread.started","thread_id":"isolated"}')
    ledger.accept(b'{"type":"turn.started"}')
    with pytest.raises(HarnessError, match="NON_MCP_TOOL_FORBIDDEN"):
        ledger.accept(
            json.dumps({"type": "item.started", "item": {"id": "x", "type": kind}}).encode()
        )


def test_jsonl_claims_cannot_invent_actual_mcp_receipts():
    ledger = EventLedger(frozenset())
    for value in (
        {"type": "thread.started", "thread_id": "isolated"},
        {"type": "turn.started"},
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    ):
        ledger.accept(json.dumps(value).encode())
    assert ledger.calls == {}
    ledger.reconcile(())
    # Empty CLI text never becomes a proposal. Proposal readback is a separate required gate.


FAKE_CLI = r"""
import asyncio,json,sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client
def event(value): print(json.dumps(value),flush=True)
async def main():
    socket,proxy,project,output=sys.argv[1:5]
    event({"type":"thread.started","thread_id":"synthetic-cli"})
    event({"type":"turn.started"})
    args={"project_id":project}
    item={"id":"tool-1","type":"mcp_tool_call","server":"flowtest","tool":"flowtest.inspect_contract","arguments":args,"status":"in_progress"}
    event({"type":"item.started","item":item})
    params=StdioServerParameters(command=sys.executable,args=[proxy,"--socket",socket],env={"LANG":"en_US.UTF-8"})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.discover()
            await session.call_tool("flowtest.inspect_contract",arguments=args)
    item["status"]="completed"
    event({"type":"item.completed","item":item})
    event({"type":"turn.completed","usage":{"input_tokens":11,"output_tokens":7}})
    Path(output).write_text(json.dumps({"phase":"workflow","status":"blocked","proposal_ids":[],"reason_codes":["SYNTHETIC_ONLY"]}))
asyncio.run(main())
"""


@pytest.mark.asyncio
async def test_real_subprocess_jsonl_private_mcp_and_actual_upstream_receipts_without_model():
    with TemporaryDirectory(prefix="fh-", dir="/tmp") as location:
        directory = Path(location)
        approved = grant()
        proxy, upstream = gateway(directory / "gateway", auth=approved.authorization)
        fake = directory / "synthetic_cli.py"
        fake.write_text(FAKE_CLI)
        summary = directory / "summary.json"
        socket = directory / "mcp.sock"
        plan = CodexLaunchPlan(
            (
                sys.executable,
                str(fake),
                str(socket),
                str(ROOT / "scripts/selftest/host_proxy_stdio.py"),
                str(approved.authorization.project_id),
                str(summary),
                "--output-last-message",
                str(summary),
            ),
            directory,
            (("LANG", "en_US.UTF-8"),),
            canonical_digest("synthetic"),
            approved.digest,
            datetime.now(UTC) + timedelta(seconds=8),
        )
        result = await run_process(
            plan,
            prompt="synthetic",
            gateway=proxy,
            socket_path=socket,
            output_dir=directory / "output",
        )
        assert result.receipt.reason_code is None and result.receipt.exit_code == 0
        assert result.receipt.billed_cost == "unknown"
        assert result.receipt.input_tokens == 11 and result.receipt.output_tokens == 7
        assert len(upstream.calls) == 1 and len(proxy.receipts) == 1
        assert not socket.exists()
        stored = (directory / "output/process.json").read_text()
        assert "structured_content" not in stored and "synthetic-cli" not in stored


@pytest.mark.asyncio
async def test_actual_bounded_child_is_terminated_and_unknown_state_retained_without_retry():
    with TemporaryDirectory(prefix="fh-", dir="/tmp") as location:
        directory = Path(location)
        approved = grant()
        proxy, upstream = gateway(directory / "gateway", auth=approved.authorization)
        plan = CodexLaunchPlan(
            (sys.executable, "-c", "import time;time.sleep(30)"),
            directory,
            (("LANG", "en_US.UTF-8"),),
            canonical_digest("synthetic"),
            approved.digest,
            datetime.now(UTC) + timedelta(seconds=0.1),
        )
        result = await asyncio.wait_for(
            run_process(
                plan,
                prompt="synthetic",
                gateway=proxy,
                socket_path=directory / "mcp.sock",
                output_dir=directory / "output",
            ),
            timeout=5,
        )
        assert result.receipt.reason_code == "HOST_DEADLINE_EXCEEDED"
        assert result.receipt.exit_code is not None and result.receipt.exit_code != 0
        assert upstream.calls == [] and result.receipt.summary is None


@pytest.mark.asyncio
async def test_budget_denial_terminates_live_synthetic_host_and_keeps_bounded_denial_receipt():
    from scripts.selftest.host_contracts import HostBudget
    from test_selftest_host_adapter import authorization

    with TemporaryDirectory(prefix="fh-", dir="/tmp") as location:
        directory = Path(location)
        auth = authorization(
            budget=HostBudget(
                maximum_tool_calls=1,
                wall_seconds=10,
                maximum_prompt_bytes=1024,
                maximum_result_bytes=1024,
                maximum_total_result_bytes=2048,
            )
        )
        approved = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
        proxy, upstream = gateway(directory / "gateway", auth=auth)
        fake = directory / "synthetic_cli.py"
        fake.write_text(
            FAKE_CLI.replace(
                '            await session.call_tool("flowtest.inspect_contract",arguments=args)',
                '            await session.call_tool("flowtest.inspect_contract",arguments=args)\n'
                '            await session.call_tool("flowtest.inspect_contract",arguments=args)\n'
                "            await asyncio.sleep(30)",
            )
        )
        summary = directory / "summary.json"
        plan = CodexLaunchPlan(
            (
                sys.executable,
                str(fake),
                str(directory / "mcp.sock"),
                str(ROOT / "scripts/selftest/host_proxy_stdio.py"),
                str(auth.project_id),
                str(summary),
                "--output-last-message",
                str(summary),
            ),
            directory,
            (("LANG", "en_US.UTF-8"),),
            canonical_digest("synthetic"),
            approved.digest,
            datetime.now(UTC) + timedelta(seconds=8),
        )
        result = await asyncio.wait_for(
            run_process(
                plan,
                prompt="synthetic",
                gateway=proxy,
                socket_path=directory / "mcp.sock",
                output_dir=directory / "output",
            ),
            timeout=5,
        )
        assert result.receipt.reason_code == "HOST_TOOL_BUDGET_EXCEEDED"
        assert (
            result.receipt.exit_code != 0 and len(upstream.calls) == 1 and len(proxy.receipts) == 1
        )
        assert proxy.stop_receipt.admitted_calls == 1 and proxy.stop_receipt.rejected_calls == 1
        assert (directory / "gateway" / "host-stop.json").exists()
        assert not summary.exists()


def test_default_host_cli_is_not_run_and_never_starts_a_model(tmp_path):
    import os
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.selftest.run_host",
            "--output",
            str(tmp_path / "not-run.json"),
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        },
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert json.loads((tmp_path / "not-run.json").read_text()) == {
        "status": "NOT_RUN",
        "reason_codes": ["HOST_AUTHORIZATION_PENDING"],
        "actual_model_calls": 0,
    }


def test_product_dispatch_without_explicit_host_configuration_stays_not_run(tmp_path):
    from scripts.selftest.product_agent import _host_ready

    from app.schemas.self_tests import BatchResponse

    identifier = uuid4()
    batch = BatchResponse.model_construct(
        id=identifier,
        project_id=uuid4(),
        generation_mode="host_llm_mcp",
        phase="pending",
        batch_key="host-pending",
        policy_digest="a" * 64,
    )
    assert not _host_ready(batch, None, tmp_path)
    stored = json.loads((tmp_path / str(identifier) / "host-not-run.json").read_text())
    assert stored["status"] == "NOT_RUN" and stored["reason_codes"] == [
        "HOST_AUTHORIZATION_PENDING"
    ]
    assert _host_ready(
        batch.model_copy(update={"generation_mode": "deterministic_mcp"}), None, tmp_path
    )


@pytest.mark.asyncio
async def test_product_host_generation_never_falls_back_to_deterministic_without_grant(
    tmp_path, monkeypatch
):
    from scripts.selftest import product_agent, product_mcp
    from scripts.selftest.product_agent import _generate

    from app.schemas.self_tests import AgentTaskResponse, BatchResponse

    async def forbidden(*args, **kwargs):
        pytest.fail("host_llm_mcp must never fall back to deterministic generation")

    async def unrelated_cleanup_arm(*args, **kwargs):
        return None

    monkeypatch.setattr(product_agent, "arm_target_lifecycle", unrelated_cleanup_arm)
    monkeypatch.setattr(product_mcp, "generate_task", forbidden)
    batch = BatchResponse.model_construct(generation_mode="host_llm_mcp")
    task = AgentTaskResponse.model_construct(task_kind="generation", batch=batch)
    with pytest.raises(HarnessError, match="HOST_AUTHORIZATION_PENDING"):
        await _generate(
            None,
            None,
            None,
            task=task,
            stack=None,
            boot=None,
            directory=tmp_path,
            installation_directory=tmp_path,
            review_mode="human",
            host_config=None,
        )


async def test_standalone_host_entrypoint_checks_public_binding_before_role_credentials(
    tmp_path, monkeypatch
):
    from scripts.selftest import run_host
    from scripts.selftest.io import write_json
    from test_selftest_runtime_credentials import binding

    stack = binding()
    write_json(tmp_path / "stack.json", stack)
    monkeypatch.setattr(run_host, "load_config", lambda _: object())
    monkeypatch.setattr(run_host, "approved_grant", lambda _: object())
    inspected = []

    def reject(actual, directory):
        inspected.append((actual, directory))
        raise HarnessError("SELFTEST_CONTAINER_BUILD_MISMATCH")

    def private_forbidden(*args):
        pytest.fail("endpoint drift must stop before loading private agent credentials")

    monkeypatch.setattr(run_host, "verify_agent_endpoints", reject, raising=False)
    monkeypatch.setattr(run_host, "load_runtime", private_forbidden)
    with pytest.raises(HarnessError, match="CONTAINER_BUILD_MISMATCH"):
        await run_host.poll_host(
            stack_directory=tmp_path,
            state_directory=tmp_path / "state",
            agent_config=tmp_path / "missing-private-agent.json",
            host_config=tmp_path / "host.json",
            role="observer",
        )
    assert inspected == [(stack, tmp_path)]
    assert not (tmp_path / "state").exists()
