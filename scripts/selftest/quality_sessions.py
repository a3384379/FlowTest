"""Two SDK identities share one owned HTTP gateway and close before its disposal."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime
from pathlib import Path

from scripts.selftest.io import HarnessError
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_container_http import container_http_gateway
from scripts.selftest.mcp_protocol_runner import ProtocolClient, http_protocol
from scripts.selftest.run import _protocol


@asynccontextmanager
async def open_protocols(
    binding: StackBinding,
    transport: str,
    writer_token: str,
    reader_token: str,
    batch_key: str,
    output: Path,
    directory: Path,
    deadline: datetime,
) -> AsyncIterator[tuple[ProtocolClient, ProtocolClient]]:
    if not writer_token or not reader_token or writer_token == reader_token:
        raise HarnessError("SELFTEST_QUALITY_DISTINCT_IDENTITIES_REQUIRED")
    async with AsyncExitStack() as contexts:
        if transport == "streamable-http":
            endpoint = await contexts.enter_async_context(
                container_http_gateway(binding, directory, output / "gateway", deadline=deadline)
            )
            writer = await contexts.enter_async_context(
                http_protocol(
                    url=endpoint.url,
                    token=writer_token,
                    batch_key=batch_key,
                    output_dir=output / "writer",
                )
            )
            reader = await contexts.enter_async_context(
                http_protocol(
                    url=endpoint.url,
                    token=reader_token,
                    batch_key=batch_key,
                    output_dir=output / "reader",
                )
            )
        else:
            writer = await contexts.enter_async_context(
                _protocol(
                    binding,
                    transport,
                    writer_token,
                    batch_key,
                    output / "writer",
                    stack_directory=directory,
                    deadline=deadline,
                )
            )
            reader = await contexts.enter_async_context(
                _protocol(
                    binding,
                    transport,
                    reader_token,
                    batch_key,
                    output / "reader",
                    stack_directory=directory,
                    deadline=deadline,
                )
            )
        yield writer, reader
