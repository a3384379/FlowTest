"""Actual SDK, OS pipes and loopback sockets; no injected transport exceptions."""

import asyncio
import contextlib
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.selftest.mcp_fault_http import FaultHTTPProxy, fault_http_proxy
from scripts.selftest.mcp_fault_session import error_result

SERVER = Path(__file__).parent / "fixtures/mcp_fault_server.py"


@asynccontextmanager
async def real_server(tmp_path, *, catalog_padding=0):
    with socket.socket() as selected:
        selected.bind(("127.0.0.1", 0))
        port = selected.getsockname()[1]
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SERVER),
        env={
            **os.environ,
            "FLOWTEST_FAULT_FIXTURE_PORT": str(port),
            "FLOWTEST_FAULT_FIXTURE_CATALOG_PADDING": str(catalog_padding),
            "FLOWTEST_FAULT_FIXTURE_JOURNAL": str(tmp_path / "mutations.jsonl"),
        },
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=0.2) as client:
            for _ in range(60):
                try:
                    async with client.stream("GET", url):
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
            else:
                pytest.fail("owned real MCP fixture did not start")
        yield (url, child)
    finally:
        if child.returncode is None:
            child.terminate()
        await asyncio.wait_for(child.wait(), timeout=5)


@pytest.mark.parametrize("fault,expected", [("bad_json", -32700), ("bad_version", -32600)])
async def test_actual_server_rejects_mutated_jsonrpc_and_sdk_correlates_original_id(
    tmp_path, fault, expected
):
    async with real_server(tmp_path) as (url, _):
        proxy = FaultHTTPProxy(url, uuid4().hex, fault, lambda: True)
        async with (
            fault_http_proxy(proxy) as endpoint,
            httpx2.AsyncClient(trust_env=False, timeout=3) as http,
            streamable_http_client(endpoint, http_client=http) as streams,
            ClientSession(streams[0], streams[1], read_timeout_seconds=2) as client,
        ):
            await client.discover()
            with pytest.raises(MCPError) as caught:
                await client.call_tool(
                    "flowtest.inspect_connection", {"request": {}}, read_timeout_seconds=1
                )
            assert caught.value.code == expected
        assert proxy.dispatch.server_http_status == 400
        assert proxy.dispatch.server_rpc_error == expected
        assert proxy.dispatch.response_id is None
        assert proxy.dispatch.forwarded_count == 1 and proxy.dispatch.process_cleanup_complete


async def sdk_call(endpoint, name, args, *, timeout=0.3):
    try:
        async with (
            httpx2.AsyncClient(trust_env=False, timeout=3) as http,
            streamable_http_client(endpoint, http_client=http) as streams,
            ClientSession(streams[0], streams[1], read_timeout_seconds=2) as client,
        ):
            await client.discover()
            return await client.call_tool(name, args, read_timeout_seconds=timeout)
    except (MCPError, httpx2.RemoteProtocolError, ExceptionGroup) as error:
        return error_result(error)


@pytest.mark.parametrize("fault", ["timeout", "socket_break", "unknown_mutation"])
async def test_actual_http_fault_keeps_raw_sdk_failure_and_one_forwarded_dispatch(tmp_path, fault):
    async with real_server(tmp_path) as (url, _):
        proxy = FaultHTTPProxy(url, uuid4().hex, fault, lambda: True)
        async with fault_http_proxy(proxy) as endpoint:
            name = (
                "flowtest.propose_test_design"
                if fault == "unknown_mutation"
                else "flowtest.inspect_connection"
            )
            args = (
                {"project_id": str(uuid4()), "idempotency_key": "fixed-one-attempt", "design": {}}
                if fault == "unknown_mutation"
                else {"request": {}}
            )
            result = await sdk_call(endpoint, name, args)
        assert not result.complete
        assert (result.rpc_error_code, result.transport_error) == (
            (-32001, None) if fault == "timeout" else (None, "remote_protocol_error")
        )
        assert proxy.dispatch.response_digest is not None
        assert proxy.dispatch.forwarded_count == 1 and proxy.dispatch.process_cleanup_complete
        if fault == "unknown_mutation":
            assert str(proxy.dispatch.proposal_id) == "edc0cf14-a78b-43c1-b019-7285da6bcc65"
            assert len((tmp_path / "mutations.jsonl").read_text().splitlines()) == 1


async def test_oversized_is_real_server_field_boundary_not_a_message_size_claim(tmp_path):
    async with real_server(tmp_path) as (url, _):
        proxy = FaultHTTPProxy(url, uuid4().hex, "oversized_field", lambda: True)
        async with (
            fault_http_proxy(proxy) as endpoint,
            httpx2.AsyncClient(trust_env=False, timeout=3) as http,
            streamable_http_client(endpoint, http_client=http) as streams,
            ClientSession(streams[0], streams[1], read_timeout_seconds=2) as client,
        ):
            await client.discover()
            result = await client.call_tool(
                "flowtest.inspect_connection",
                {"request": {"expected_contract_version": "x" * 81}},
                read_timeout_seconds=1,
            )
            assert result.is_error
        assert proxy.dispatch.server_http_status == 200
        assert proxy.dispatch.server_rpc_error is None
        assert proxy.dispatch.forwarded_bytes < 1024


async def test_unknown_dispatch_cannot_be_replayed_through_same_fault_proxy(tmp_path):
    async with real_server(tmp_path) as (url, _):
        proxy = FaultHTTPProxy(url, uuid4().hex, "unknown_mutation", lambda: True)
        async with (
            fault_http_proxy(proxy) as endpoint,
            httpx.AsyncClient(trust_env=False) as client,
        ):
            frame = {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "flowtest.propose_test_design",
                    "arguments": {
                        "project_id": str(uuid4()),
                        "idempotency_key": "fixed-one-attempt",
                        "design": {},
                    },
                },
            }
            headers = {
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            }
            for _ in range(2):
                with contextlib.suppress(httpx.TransportError):
                    await client.post(endpoint, json=frame, headers=headers)
        assert len((tmp_path / "mutations.jsonl").read_text().splitlines()) == 1
        assert "SELFTEST_FAULT_MUTATION_REPLAY_FORBIDDEN" in proxy.errors


@pytest.mark.parametrize(
    "fault,code",
    [
        ("pipe_break", -32000),
        ("timeout", -32001),
        ("server_crash", -32000),
        ("unknown_mutation", -32000),
    ],
)
async def test_actual_os_pipe_faults_dispatch_once_and_kill_only_owned_server(
    tmp_path, fault, code
):
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from scripts.selftest.io import read_json
    from scripts.selftest.mcp_fault_contracts import DispatchReceipt

    nonce = uuid4().hex
    output = tmp_path / "dispatch.json"
    relay = SERVER.with_name("mcp_fault_pipe_relay.py")
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(relay), fault, nonce, str(output)],
        env={
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "FLOWTEST_FAULT_FIXTURE_JOURNAL": str(tmp_path / "mutations.jsonl"),
        },
    )
    result = None
    with Path(os.devnull).open("w") as errors:
        try:
            async with (
                stdio_client(params, errlog=errors) as streams,
                ClientSession(streams[0], streams[1], read_timeout_seconds=3) as client,
            ):
                await client.discover()
                name = (
                    "flowtest.propose_test_design"
                    if fault == "unknown_mutation"
                    else "flowtest.inspect_connection"
                )
                args = (
                    {
                        "project_id": str(uuid4()),
                        "idempotency_key": "fixed-one-attempt",
                        "design": {},
                    }
                    if fault == "unknown_mutation"
                    else {"request": {}}
                )
                await client.call_tool(name, args, read_timeout_seconds=0.3)
        except (MCPError, ExceptionGroup) as error:
            result = error_result(error)
    assert result is not None and (not result.complete) and (result.rpc_error_code == code)
    observed = DispatchReceipt.model_validate(read_json(output))
    assert observed.forwarded_count == 1 and observed.response_digest is not None
    assert observed.server_killed == (fault == "server_crash")
    if fault == "unknown_mutation":
        assert len((tmp_path / "mutations.jsonl").read_text().splitlines()) == 1
        assert observed.proposal_id is not None


async def test_http_crash_really_terminates_the_owned_mcp_server_process(tmp_path):
    from scripts.selftest.mcp_fault_contracts import ProcessIdentity

    async with real_server(tmp_path) as (url, child):
        nonce = uuid4().hex

        async def crash():
            assert child.returncode is None
            child.kill()
            assert await asyncio.wait_for(child.wait(), timeout=5) != 0
            return ProcessIdentity(nonce=nonce, pid=child.pid, start_ticks="1")

        proxy = FaultHTTPProxy(url, nonce, "server_crash", lambda: True, crash)
        async with fault_http_proxy(proxy) as endpoint:
            result = await sdk_call(endpoint, "flowtest.inspect_connection", {"request": {}})
        assert not result.complete and result.transport_error == "remote_protocol_error"
        assert proxy.dispatch.server_killed and proxy.dispatch.process.pid == child.pid
        assert child.returncode != 0


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/mcp",
        "http://localhost/mcp",
        "http://192.168.1.1/mcp",
        "http://127.0.0.1/other",
    ],
)
def test_fault_proxy_rejects_unowned_or_nonfixed_upstream(url):
    from scripts.selftest.io import HarnessError

    with pytest.raises(HarnessError, match="SELFTEST_FAULT_UPSTREAM_NOT_LOOPBACK"):
        FaultHTTPProxy(url, uuid4().hex, "timeout", lambda: True)


def test_server_kill_command_requires_exact_pid_start_ticks_and_nonce():
    from scripts.selftest.io import HarnessError
    from scripts.selftest.mcp_fault_contracts import ProcessIdentity
    from scripts.selftest.mcp_fault_process import process_command

    nonce = uuid4().hex
    with pytest.raises(HarnessError, match="EXACT_KILL_IDENTITY"):
        process_command("1" * 64, nonce, "kill")
    with pytest.raises(HarnessError, match="EXACT_KILL_IDENTITY"):
        process_command(
            "1" * 64,
            nonce,
            "kill",
            expected=ProcessIdentity(nonce=uuid4().hex, pid=123, start_ticks="1234"),
        )
    with pytest.raises(HarnessError, match="ARGUMENT_INVALID"):
        process_command("foreign-container", nonce, "kill")


async def test_actual_400k_catalog_is_bounded_metadata_not_a_tool_response(tmp_path):
    async with real_server(tmp_path, catalog_padding=400000) as (url, _):
        proxy = FaultHTTPProxy(url, uuid4().hex, "oversized_field", lambda: True)
        async with (
            fault_http_proxy(proxy) as endpoint,
            httpx2.AsyncClient(trust_env=False, timeout=3) as http,
            streamable_http_client(endpoint, http_client=http) as streams,
            ClientSession(streams[0], streams[1], read_timeout_seconds=2) as client,
        ):
            await client.discover()
            listing = await client.list_tools()
            assert (
                len(
                    next(
                        t for t in listing.tools if t.name == "flowtest.inspect_connection"
                    ).description
                )
                >= 400000
            )
        assert not proxy.errors


async def test_real_catalog_above_one_mib_remains_fail_closed(tmp_path):
    async with real_server(tmp_path, catalog_padding=1100000) as (url, _):
        proxy = FaultHTTPProxy(url, uuid4().hex, "oversized_field", lambda: True)
        async with fault_http_proxy(proxy) as endpoint:
            with pytest.raises(ExceptionGroup):
                async with (
                    httpx2.AsyncClient(trust_env=False, timeout=3) as http,
                    streamable_http_client(endpoint, http_client=http) as streams,
                    ClientSession(streams[0], streams[1], read_timeout_seconds=2) as client,
                ):
                    await client.discover()
                    await client.list_tools()
        assert proxy.dispatch is None and proxy.errors


async def test_large_ordinary_tool_response_keeps_256k_limit(tmp_path):
    async with real_server(tmp_path) as (url, _):
        proxy = FaultHTTPProxy(url, uuid4().hex, "oversized_field", lambda: True)
        async with fault_http_proxy(proxy) as endpoint:
            result = await sdk_call(endpoint, "flowtest.large_result", {})
        assert not result.complete and result.transport_error == "remote_protocol_error"
        assert proxy.dispatch is None and proxy.errors


async def stdio_catalog(tmp_path, padding):
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(SERVER.with_name("mcp_fault_pipe_relay.py")),
            "oversized_field",
            uuid4().hex,
            str(tmp_path / "dispatch.json"),
        ],
        env={
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "FLOWTEST_FAULT_FIXTURE_JOURNAL": str(tmp_path / "mutations.jsonl"),
            "FLOWTEST_FAULT_FIXTURE_CATALOG_PADDING": str(padding),
        },
    )
    with Path(os.devnull).open("w") as errors:
        async with (
            stdio_client(params, errlog=errors) as streams,
            ClientSession(streams[0], streams[1], read_timeout_seconds=2) as client,
        ):
            await client.discover()
            return await client.list_tools()


async def test_actual_stdio_400k_catalog_is_bounded_metadata(tmp_path):
    result = await stdio_catalog(tmp_path, 400000)
    assert (
        len(next(t for t in result.tools if t.name == "flowtest.inspect_connection").description)
        >= 400000
    )


async def test_stdio_catalog_above_one_mib_still_closes_the_owned_pipe(tmp_path):
    with pytest.raises(ExceptionGroup):
        await stdio_catalog(tmp_path, 1100000)
    assert not (tmp_path / "dispatch.json").exists()
