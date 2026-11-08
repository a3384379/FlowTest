"""Real locked-SDK attempts over the candidate's dedicated pipes or HTTP process."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client._transport import ReadStream, WriteStream
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp.types import CallToolResult
from mcp_types import JSONRPCRequest
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, object_value, read_json, text_value
from scripts.selftest.mcp_container_http import container_http_gateway
from scripts.selftest.mcp_fault_contracts import (
    DispatchReceipt,
    FaultObservation,
    FaultResult,
    FaultScenario,
    FrameReceipt,
    ProcessIdentity,
    ProcessRemovalProof,
)
from scripts.selftest.mcp_fault_http import FaultHTTPProxy, fault_http_proxy
from scripts.selftest.mcp_fault_process import control, kill
from scripts.selftest.mcp_fault_setup import PreparedFault, arguments
from scripts.selftest.mcp_negative_runner import _catalog
from scripts.selftest.mcp_negative_wire import RecordingRead, RecordingWrite, WireJournal
from scripts.selftest.mcp_probe_reader import ProbeReader


class FaultWire(WireJournal):
    def __init__(self, prepared: PreparedFault) -> None:
        super().__init__(prepared.budget.reserve_tool)
        self.prepared = prepared
        self.frames: list[FrameReceipt] = []

    def sent(self, item: SessionMessage) -> None:
        if isinstance(item.message, JSONRPCRequest):
            if not self.prepared.budget.reserve():
                raise HarnessError("SELFTEST_FAULT_RPC_BUDGET_EXHAUSTED")
            self.frames.append(
                FrameReceipt(
                    request_id=item.message.id,
                    frame_digest=canonical_digest(
                        item.message.model_dump(mode="json", by_alias=True, exclude_unset=True)
                    ),
                )
            )
        super().sent(item)


def error_result(error: BaseException) -> FaultResult:
    if isinstance(error, BaseExceptionGroup):
        leaves = tuple(error_result(item) for item in error.exceptions)
        if not leaves or any(item != leaves[0] for item in leaves):
            raise HarnessError("SELFTEST_FAULT_UNEXPECTED_ERROR_GROUP") from error
        return leaves[0]
    if isinstance(error, MCPError):
        return FaultResult(complete=False, rpc_error_code=error.code)
    if isinstance(error, httpx2.RemoteProtocolError):
        return FaultResult(complete=False, transport_error="remote_protocol_error")
    raise HarnessError("SELFTEST_FAULT_UNEXPECTED_CLIENT_ERROR") from error


def tool_result(returned: CallToolResult, name: str) -> FaultResult:
    raw = object_value(returned.structured_content or {})
    data = object_value(raw.get("data", raw))
    error = object_value(data.get("error", {}))
    texts = [part.text for part in returned.content if part.type == "text"]
    invalid = (
        len(texts) == 1
        and texts[0].startswith("Error executing tool " + name + ":")
        and "validation error" in texts[0]
    )
    return FaultResult.model_validate(
        {
            "complete": True,
            "trace_present": bool(
                raw.get("trace_id") or data.get("trace_id") or error.get("trace_id")
            ),
            "tool_error": returned.is_error,
            "business_code": error.get("code"),
            "text_marker": "invalid_arguments" if invalid else None,
            "result_digest": canonical_digest(
                returned.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
        }
    )


async def invoke(
    client: ClientSession, prepared: PreparedFault, scenario: FaultScenario
) -> FaultResult:
    name, body = arguments(prepared.manifest.project_id, prepared.manifest.batch_key, scenario)
    returned = await client.call_tool(
        name, body, read_timeout_seconds=2 if scenario.fault == "timeout" else 10
    )
    if not isinstance(returned, CallToolResult):
        raise HarnessError("SELFTEST_FAULT_TOOL_RESULT_INVALID")
    return tool_result(returned, name)


class Attempt:
    def __init__(self, prepared: PreparedFault, scenario: FaultScenario) -> None:
        self.prepared, self.scenario = prepared, scenario
        self.wire = FaultWire(prepared)
        self.catalog: str | None = None
        self.names: tuple[str, ...] = ()
        self.result: FaultResult | None = None

    async def client(
        self, streams: tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]
    ) -> None:
        async with ClientSession(
            RecordingRead(streams[0], self.wire),
            RecordingWrite(streams[1], self.wire),
            read_timeout_seconds=10,
        ) as client:
            await client.discover()
            self.catalog, self.names, _ = await _catalog(client)
            self.result = await invoke(client, self.prepared, self.scenario)

    async def stdio(self, nonce: str, output: Path, token: str) -> DispatchReceipt:
        path = output / "dispatch.json"
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "scripts.selftest.mcp_fault_stdio",
                "--container",
                self.prepared.binding.runner_container_id,
                "--nonce",
                nonce,
                "--fault",
                self.scenario.fault,
                "--receipt",
                str(path),
            ],
            cwd=Path(__file__).resolve().parents[2],
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": token,
            },
        )
        try:
            with Path(os.devnull).open("w") as errors:
                try:
                    async with stdio_client(params, errlog=errors) as streams:
                        await self.client(streams)
                except (MCPError, httpx2.RemoteProtocolError, ExceptionGroup) as error:
                    self.result = error_result(error)
        finally:
            removed = await control(self.prepared.binding.runner_container_id, nonce, "stop")
            if removed.get("removed") is not True:
                raise HarnessError("SELFTEST_FAULT_STDIO_CLEANUP_INCOMPLETE")
        if path.with_name("dispatch-error.json").exists():
            raise HarnessError(text_value(read_json(path.with_name("dispatch-error.json"))["code"]))
        observed = DispatchReceipt.model_validate(read_json(path))
        return await self.removed(observed, "stdio")

    async def removed(self, observed: DispatchReceipt, kind: str) -> DispatchReceipt:
        if observed.process is None:
            raise HarnessError("SELFTEST_FAULT_PROCESS_START_RECEIPT_MISSING")
        raw = await control(
            self.prepared.binding.runner_container_id,
            observed.process.nonce,
            "gone",
            kind=kind,
            expected=observed.process,
        )
        if (
            raw.pop("removed", None) is not True
            or ProcessIdentity.model_validate(raw) != observed.process
        ):
            raise HarnessError("SELFTEST_FAULT_PROCESS_REMOVAL_IDENTITY_MISMATCH")
        return observed.model_copy(
            update={
                "process_cleanup_complete": True,
                "removal": ProcessRemovalProof(
                    process=observed.process, removed=True, observed_at=datetime.now(UTC)
                ),
            }
        )

    async def http(self, nonce: str, output: Path, token: str) -> DispatchReceipt:
        async with container_http_gateway(
            self.prepared.binding,
            self.prepared.directory,
            output / "gateway",
            deadline=self.prepared.manifest.expires_at,
        ) as gateway:

            async def crash() -> ProcessIdentity:
                identity = ProcessIdentity(
                    nonce=gateway.nonce,
                    pid=gateway.process.pid,
                    start_ticks=gateway.process.start_ticks,
                )
                return await kill(gateway.container_id, identity, kind="http")

            proxy = FaultHTTPProxy(
                gateway.url,
                nonce,
                self.scenario.fault,
                self.prepared.budget.reserve,
                crash,
                ProcessIdentity(
                    nonce=gateway.nonce,
                    pid=gateway.process.pid,
                    start_ticks=gateway.process.start_ticks,
                ),
            )
            async with (
                fault_http_proxy(proxy) as endpoint,
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=15
                ) as http,
            ):
                try:
                    async with streamable_http_client(endpoint, http_client=http) as streams:
                        await self.client(streams)
                except (MCPError, httpx2.RemoteProtocolError, ExceptionGroup) as error:
                    self.result = error_result(error)
        cleanup = read_json(output / "gateway/gateway-cleanup.json")
        if proxy.errors and proxy.errors[0].startswith("SELFTEST_"):
            raise HarnessError(proxy.errors[0])
        if proxy.dispatch is None or proxy.errors or cleanup.get("completed") is not True:
            raise HarnessError("SELFTEST_FAULT_HTTP_DISPATCH_OR_CLEANUP_INCOMPLETE")
        return await self.removed(proxy.dispatch, "http")


async def observe(
    prepared: PreparedFault, reader: ProbeReader, scenario: FaultScenario
) -> FaultObservation:
    from uuid import uuid4

    started = datetime.now(UTC)
    before = await reader.snapshot()
    attempt = Attempt(prepared, scenario)
    output = prepared.state / "private/sdk" / scenario.scenario_id
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    token = (
        prepared.inactive_token
        if scenario.fault == "inactive_account_creator"
        else prepared.fixture.writer_token
    )
    nonce = uuid4().hex
    dispatch = await (
        attempt.stdio(nonce, output, token)
        if scenario.transport == "stdio"
        else attempt.http(nonce, output, token)
    )
    after = await reader.snapshot()
    if attempt.result is None or attempt.catalog is None:
        raise HarnessError("SELFTEST_FAULT_ATTEMPT_NOT_DISPATCHED")
    return FaultObservation(
        scenario_id=scenario.scenario_id,
        transport=scenario.transport,
        sdk_version="2.2.0",
        started_at=started,
        completed_at=datetime.now(UTC),
        catalog_fingerprint=attempt.catalog,
        tool_names=attempt.names,
        requests=tuple(attempt.wire.requests),
        responses=tuple(attempt.wire.responses),
        frames=tuple(attempt.wire.frames),
        dispatch=dispatch,
        result=attempt.result,
        before=before,
        after=after,
    )
