"""A bounded loopback HTTP fault proxy; only IDs/digests escape its memory."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, object_value
from scripts.selftest.mcp_fault_contracts import DispatchReceipt, Fault, ProcessIdentity


def frame_bytes(value: JsonObject) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def forwarded_frame(frame: JsonObject, fault: Fault) -> bytes:
    if fault == "bad_json":
        return b"{"
    if fault == "bad_version":
        return frame_bytes({**frame, "jsonrpc": "1.0"})
    return frame_bytes(frame)


def _proposal(body: JsonObject) -> UUID | None:
    result = object_value(body.get("result", {}))
    structured = object_value(result.get("structuredContent", {}))
    data = object_value(structured.get("data", {}))
    value = data.get("id")
    return UUID(value) if isinstance(value, str) else None


def receipt(
    nonce: str,
    frame: JsonObject,
    sent: bytes,
    body: bytes,
    fault: Fault,
    *,
    status: int | None = None,
    process: ProcessIdentity | None = None,
    killed: bool = False,
    cleanup: bool = False,
) -> DispatchReceipt:
    params = object_value(frame.get("params", {}))
    parsed = object_value(json.loads(body))
    error = object_value(parsed.get("error", {}))
    return DispatchReceipt.model_validate(
        {
            "nonce": nonce,
            "observed_at": datetime.now(UTC),
            "request_id": frame["id"],
            "tool_name": params["name"],
            "arguments_digest": canonical_digest(params.get("arguments", {})),
            "sdk_frame_digest": canonical_digest(frame),
            "forwarded_digest": hashlib.sha256(sent).hexdigest(),
            "forwarded_bytes": len(sent),
            "forwarded_count": 1,
            "response_digest": canonical_digest(parsed),
            "response_result_digest": canonical_digest(parsed["result"])
            if "result" in parsed
            else None,
            "response_id": parsed.get("id"),
            "server_http_status": status,
            "server_rpc_error": error.get("code"),
            "proposal_id": _proposal(parsed) if fault == "unknown_mutation" else None,
            "fault_applied": True,
            "process": process,
            "server_killed": killed,
            "process_cleanup_complete": cleanup,
        }
    )


@dataclass(frozen=True)
class HTTPFrame:
    method: str
    headers: dict[str, str]
    body: bytes


async def _request(reader: asyncio.StreamReader) -> HTTPFrame:
    head = await reader.readuntil(b"\r\n\r\n")
    if len(head) > 16384:
        raise HarnessError("SELFTEST_FAULT_HTTP_HEADER_LIMIT")
    lines = head.decode("latin-1").split("\r\n")
    method, path, _ = lines[0].split(" ", 2)
    headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
    lowered = {k.lower(): v.strip() for k, v in headers.items()}
    size = int(lowered.get("content-length", "0"))
    if path != "/mcp" or not 0 <= size <= 262144 or "transfer-encoding" in lowered:
        raise HarnessError("SELFTEST_FAULT_HTTP_REQUEST_INVALID")
    return HTTPFrame(method, lowered, await reader.readexactly(size))


class FaultHTTPProxy:
    def __init__(
        self,
        upstream: str,
        nonce: str,
        fault: Fault,
        reserve: Callable[[], bool],
        kill_server: Callable[[], Awaitable[ProcessIdentity]] | None = None,
        process: ProcessIdentity | None = None,
    ) -> None:
        parsed = urlsplit(upstream)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path != "/mcp":
            raise HarnessError("SELFTEST_FAULT_UPSTREAM_NOT_LOOPBACK")
        self.upstream, self.nonce, self.fault = upstream, nonce, fault
        self.reserve, self.kill_server = reserve, kill_server
        self.process = process
        self.dispatch: DispatchReceipt | None = None
        self.tasks: set[asyncio.Task[None]] = set()
        self.connections = 0
        self.dispatch_count = 0
        self.errors: list[str] = []

    def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self.connection(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _forward(self, request: HTTPFrame) -> tuple[httpx.Response, JsonObject | None, bytes]:
        if not self.reserve():
            raise HarnessError("SELFTEST_FAULT_HTTP_BUDGET_EXHAUSTED")
        frame = object_value(json.loads(request.body)) if request.body else None
        armed = frame is not None and frame.get("method") == "tools/call"
        if armed:
            self.dispatch_count += 1
            if self.dispatch_count != 1:
                raise HarnessError("SELFTEST_FAULT_MUTATION_REPLAY_FORBIDDEN")
        data = forwarded_frame(frame, self.fault) if frame is not None and armed else request.body
        headers = {
            k: v
            for k, v in request.headers.items()
            if k not in {"host", "content-length", "connection"}
        }
        limit = 1048576 if frame is not None and frame.get("method") == "tools/list" else 262144
        async with (
            httpx.AsyncClient(trust_env=False, timeout=10, follow_redirects=False) as client,
            client.stream(request.method, self.upstream, content=data, headers=headers) as upstream,
        ):
            body = bytearray()
            async for chunk in upstream.aiter_bytes(chunk_size=65536):
                if len(body) + len(chunk) > limit:
                    raise HarnessError("SELFTEST_FAULT_HTTP_RESPONSE_LIMIT")
                body.extend(chunk)
            response = httpx.Response(
                upstream.status_code, headers=upstream.headers, content=bytes(body)
            )
        return response, frame if armed else None, data

    async def _fault(self, response: httpx.Response, frame: JsonObject, sent: bytes) -> bool:
        process = self.process
        if self.fault == "server_crash":
            if self.kill_server is None:
                raise HarnessError("SELFTEST_FAULT_CRASH_HANDLER_MISSING")
            process = await self.kill_server()
        self.dispatch = receipt(
            self.nonce,
            frame,
            sent,
            response.content,
            self.fault,
            status=response.status_code,
            process=process,
            killed=self.fault == "server_crash",
        )
        if self.fault == "timeout":
            await asyncio.sleep(4)
        return self.fault in {"socket_break", "server_crash", "unknown_mutation", "timeout"}

    async def connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            if self.connections > 100:
                raise HarnessError("SELFTEST_FAULT_CONNECTION_LIMIT")
            async with asyncio.timeout(12):
                request = await _request(reader)
                response, frame, data = await self._forward(request)
                if frame is not None and await self._fault(response, frame, data):
                    return
                headers = (
                    f"HTTP/1.1 {response.status_code} fault-proxy\r\n"
                    f"Content-Type: {response.headers.get('content-type', 'application/json')}\r\n"
                    f"Content-Length: {len(response.content)}\r\nConnection: close\r\n\r\n"
                )
                writer.write(headers.encode("latin-1") + response.content)
                await writer.drain()
        except (
            OSError,
            ValueError,
            TimeoutError,
            asyncio.IncompleteReadError,
            HarnessError,
        ) as error:
            self.errors.append(
                str(error) if isinstance(error, HarnessError) else type(error).__name__
            )
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def close(self) -> None:
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.dispatch is not None:
            self.dispatch = self.dispatch.model_copy(update={"process_cleanup_complete": True})


@asynccontextmanager
async def fault_http_proxy(proxy: FaultHTTPProxy) -> AsyncIterator[str]:
    server = await asyncio.start_server(proxy.accept, "127.0.0.1", 0, limit=16384)
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.close()
        await server.wait_closed()
        await proxy.close()
