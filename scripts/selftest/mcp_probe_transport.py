"""Record actual SDK traffic from the verified container or its owned HTTP relay."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage
from mcp_types import JSONRPCRequest
from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_negative_contracts import Transport
from scripts.selftest.mcp_negative_wire import RecordingRead, RecordingWrite, WireJournal
from scripts.selftest.mcp_probe_setup import PreparedProbe


class ProbeWireJournal(WireJournal):
    def __init__(self, prepared: PreparedProbe) -> None:
        super().__init__(prepared.budget.reserve_tool)
        self.prepared = prepared

    def sent(self, item: SessionMessage) -> None:
        # These fixed probes issue at most one backend call per SDK request.
        # Even metadata-only RPCs reserve one unit, giving a conservative cap.
        if isinstance(item.message, JSONRPCRequest):
            if not self.prepared.budget.reserve():
                self.prepared.rpc_budget.rejected += 1
                raise HarnessError("SELFTEST_PROBE_CANDIDATE_RPC_BUDGET_EXHAUSTED")
            self.prepared.rpc_budget.admitted += 1
        super().sent(item)


@asynccontextmanager
async def session(
    prepared: PreparedProbe, transport: Transport, token: str, gateway_url: str, output: Path
) -> AsyncIterator[tuple[ClientSession, WireJournal]]:
    wire = ProbeWireJournal(prepared)
    container = prepared.binding.runner_container_id
    if re.fullmatch(r"[0-9a-f]{64}", container) is None:
        raise HarnessError("SELFTEST_PROBE_CONTAINER_ID_INVALID")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    if transport == "stdio":
        docker = shutil.which("docker")
        if docker is None:
            raise HarnessError("SELFTEST_DOCKER_UNAVAILABLE")
        params = StdioServerParameters(
            command=docker,
            args=[
                "exec",
                "--interactive",
                "--env",
                "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN",
                container,
                "python",
                "-c",
                "from app.mcp.cli import main; main()",
                "--api-base-url",
                "http://127.0.0.1:8000",
            ],
            env={"PATH": os.environ.get("PATH", ""), "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": token},
        )
        with Path(os.devnull).open("w") as errors:
            async with (
                stdio_client(params, errlog=errors) as streams,
                ClientSession(
                    RecordingRead(streams[0], wire), RecordingWrite(streams[1], wire)
                ) as client,
            ):
                yield client, wire
    else:

        async def reserve(_request: httpx2.Request) -> None:
            if not prepared.budget.reserve():
                raise HarnessError("SELFTEST_PROBE_HTTP_BUDGET_EXHAUSTED")

        async with (
            httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + token} if token else {},
                trust_env=False,
                timeout=15,
                event_hooks={"request": [reserve]},
            ) as http,
            streamable_http_client(gateway_url, http_client=http) as streams,
            ClientSession(
                RecordingRead(streams[0], wire), RecordingWrite(streams[1], wire)
            ) as client,
        ):
            yield client, wire
