"""Real MCP transports using the repository's locked SDK and bounded receipts."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx2
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, PaginatedRequestParams
from pydantic import JsonValue
from scripts.selftest.contracts import McpCallReceipt, canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, JsonObject, object_value, write_json


class ProtocolClient:
    def __init__(
        self,
        session: ClientSession,
        transport: Literal["stdio", "streamable-http"],
        batch_key: str,
        output_dir: Path,
    ) -> None:
        self.session = session
        self.transport = transport
        self.batch_key = batch_key
        self.output_dir = output_dir
        self.catalog_digest = ""
        self.tools: frozenset[str] = frozenset()
        self.tool_schemas: dict[str, JsonObject] = {}
        self.receipts: list[McpCallReceipt] = []
        self.attempt_count = 0
        self.max_tool_calls = 100
        self.last_structured_result: JsonObject | None = None

    async def discover(self) -> None:
        # The locked SDK negotiates modern protocol metadata here; initialize is legacy-only.
        discovery = await self.session.discover()
        tools: list[JsonValue] = []
        cursor: str | None = None
        for _ in range(20):
            listing = await self.session.list_tools(
                params=PaginatedRequestParams(cursor=cursor) if cursor else None
            )
            tools.extend(tool.model_dump(mode="json", by_alias=True) for tool in listing.tools)
            cursor = listing.next_cursor
            if cursor is None:
                break
        if cursor is not None:
            raise HarnessError("SELFTEST_MCP_CATALOG_TRUNCATED")
        names = [str(object_value(tool)["name"]) for tool in tools]
        if len(names) != len(set(names)):
            raise HarnessError("SELFTEST_MCP_DUPLICATE_TOOL")
        self.tools = frozenset(names)
        self.tool_schemas = {
            str(object_value(tool)["name"]): object_value(object_value(tool)["inputSchema"])
            for tool in tools
        }
        self.catalog_digest = canonical_digest(tools)
        write_json(
            self.output_dir / "mcp-catalog.json",
            {
                "discovery": discovery.model_dump(mode="json"),
                "tools": tools,
                "catalog_digest": self.catalog_digest,
                "sdk_version": version("mcp"),
                "protocol_version": self.session.protocol_version,
                "transport": self.transport,
            },
        )

    async def call(
        self, tool_name: str, arguments: JsonObject, *, scenario_id: str, phase: str
    ) -> JsonObject:
        self.last_structured_result = None
        if tool_name not in self.tools:
            raise HarnessError(f"SELFTEST_MCP_TOOL_UNAVAILABLE:{tool_name}")
        if self.attempt_count >= self.max_tool_calls:
            raise HarnessError("SELFTEST_MCP_CALL_BUDGET_EXCEEDED")
        schema = self.tool_schemas.get(tool_name)
        if schema is None or not Draft202012Validator(schema).is_valid(arguments):
            write_json(
                self.output_dir / "mcp-failure.json",
                {"tool_name": tool_name, "phase": phase, "error_code": "INVALID_TOOL_ARGUMENTS"},
            )
            raise HarnessError("SELFTEST_MCP_ARGUMENTS_INVALID")
        self.attempt_count += 1
        try:
            result = await self.session.call_tool(
                tool_name, arguments=arguments, read_timeout_seconds=45
            )
            if not isinstance(result, CallToolResult) or result.structured_content is None:
                raise HarnessError("SELFTEST_MCP_STRUCTURED_RESULT_MISSING")
            structured = object_value(result.structured_content)
            self.last_structured_result = structured
            data = object_value(structured.get("data", structured))
        except (Exception, asyncio.CancelledError) as error:
            self._record(
                tool_name,
                arguments,
                scenario_id=scenario_id,
                phase=phase,
                result_digest=canonical_digest(
                    {"response_received": False, "failure_codes": list(failure_codes(error))}
                ),
                success=False,
            )
            raise
        success = not result.is_error and "error" not in data
        self._record(
            tool_name,
            arguments,
            scenario_id=scenario_id,
            phase=phase,
            result_digest=canonical_digest(structured),
            success=success,
        )
        if not success:
            error_value = data.get("error")
            candidate = error_value.get("code") if isinstance(error_value, dict) else None
            code = (
                candidate
                if isinstance(candidate, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", candidate)
                else "UNKNOWN"
            )
            write_json(
                self.output_dir / "mcp-failure.json",
                {"tool_name": tool_name, "phase": phase, "error_code": code},
            )
            raise HarnessError(f"SELFTEST_MCP_CALL_REJECTED_{code}")
        return data

    def _record(
        self,
        tool_name: str,
        arguments: JsonObject,
        *,
        scenario_id: str,
        phase: str,
        result_digest: str,
        success: bool,
    ) -> None:
        receipt = McpCallReceipt(
            call_id=str(uuid4()),
            batch_key=self.batch_key,
            scenario_id=scenario_id,
            phase=phase,
            tool_name=tool_name,
            transport=self.transport,
            sdk_version=version("mcp"),
            protocol_version=self.session.protocol_version or "unknown",
            request_digest=canonical_digest(arguments),
            result_digest=result_digest,
            catalog_digest=self.catalog_digest,
            completed_at=datetime.now(UTC),
            success=success,
        )
        self.receipts.append(receipt)
        write_json(self.output_dir / "mcp-calls" / f"{receipt.call_id}.json", receipt)


@asynccontextmanager
async def stdio_protocol(
    *, python: Path, backend: Path, api_url: str, token: str, batch_key: str, output_dir: Path
) -> AsyncIterator[ProtocolClient]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(backend),
        "PYTHONUNBUFFERED": "1",
        "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": token,
    }
    parameters = StdioServerParameters(
        command=str(python),
        args=["-c", "from app.mcp.cli import main; main()", "--api-base-url", api_url],
        cwd=backend,
        env=environment,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "mcp-stderr.log").open("w", encoding="utf-8") as errors:
        async with stdio_client(parameters, errlog=errors) as streams:
            async with ClientSession(*streams) as session:
                client = ProtocolClient(session, "stdio", batch_key, output_dir)
                await client.discover()
                yield client


@asynccontextmanager
async def container_stdio_protocol(
    *, container_id: str, token: str, batch_key: str, output_dir: Path
) -> AsyncIterator[ProtocolClient]:
    """Run the candidate gateway inside its container; keep the H/O imports trusted."""
    if re.fullmatch(r"[0-9a-f]{12,64}", container_id) is None:
        raise HarnessError("SELFTEST_MCP_CONTAINER_ID_INVALID")
    docker = shutil.which("docker")
    if docker is None:
        raise HarnessError("SELFTEST_DOCKER_UNAVAILABLE")
    parameters = StdioServerParameters(
        command=docker,
        args=[
            "exec",
            "--interactive",
            "--env",
            "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN",
            container_id,
            "python",
            "-c",
            "from app.mcp.cli import main; main()",
            "--api-base-url",
            "http://127.0.0.1:8000",
        ],
        env={
            "PATH": os.environ.get("PATH", ""),
            "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": token,
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "mcp-container-stderr.log").open("w", encoding="utf-8") as errors:
        async with stdio_client(parameters, errlog=errors) as streams:
            async with ClientSession(*streams) as session:
                client = ProtocolClient(session, "stdio", batch_key, output_dir)
                await client.discover()
                yield client


@asynccontextmanager
async def http_protocol(
    *, url: str, token: str, batch_key: str, output_dir: Path
) -> AsyncIterator[ProtocolClient]:
    async with (
        httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=45, trust_env=False
        ) as transport,
        streamable_http_client(url, http_client=transport) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        client = ProtocolClient(session, "streamable-http", batch_key, output_dir)
        await client.discover()
        yield client


@asynccontextmanager
async def isolated_http_protocol(
    *, python: Path, backend: Path, api_url: str, token: str, batch_key: str, output_dir: Path
) -> AsyncIterator[ProtocolClient]:
    """Own one HTTP server process; every tool request carries its own machine Bearer."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "mcp-http-stderr.log").open("w", encoding="utf-8") as errors:
        process = await asyncio.create_subprocess_exec(
            str(python),
            "-c",
            "from app.mcp.cli import main; main()",
            "--transport",
            "streamable-http",
            "--api-base-url",
            api_url,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--path",
            "/mcp",
            cwd=backend,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(backend),
                "PYTHONUNBUFFERED": "1",
            },
            stdout=errors,
            stderr=errors,
        )
        try:
            await _wait_http_process(process, port)
            async with http_protocol(
                url=f"http://127.0.0.1:{port}/mcp",
                token=token,
                batch_key=batch_key,
                output_dir=output_dir,
            ) as client:
                yield client
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def _wait_http_process(process: asyncio.subprocess.Process, port: int) -> None:
    for _ in range(100):
        if process.returncode is not None:
            raise HarnessError("SELFTEST_MCP_HTTP_SERVER_EXITED")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.1)
        else:
            writer.close()
            await writer.wait_closed()
            return
    raise HarnessError("SELFTEST_MCP_HTTP_SERVER_START_DEADLINE")
