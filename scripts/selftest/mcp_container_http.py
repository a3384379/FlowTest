"""Candidate HTTP gateway through owned Docker exec byte pipes; no candidate H imports."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError
from scripts.selftest.contracts import Contract
from scripts.selftest.io import HarnessError, write_json
from scripts.selftest.local_stack import StackBinding, verify_binding

# Fixed trusted byte-pump/control code. It is executed inside the already verified
# candidate container; only gateway mode imports its app. No input body is logged.
REMOTE = r"""
import contextlib, json, os, signal, socket, sys, threading, time
mode, nonce, port, key = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
root = '/tmp/flowtest-mcp-probe-'
gateway = root + 'http-' + str(port) + '.json'
path = gateway if key == 'gateway' else root + nonce + '-' + key + '.json'
def ticks(pid):
    try:
        return open('/proc/' + str(pid) + '/stat').read().split()[21]
    except FileNotFoundError:
        return None
def owned(value):
    return value['nonce'] == nonce and ticks(value['pid']) == value['start_ticks']
def load(selected):
    with open(selected) as stream:
        value = json.load(stream)
    if value['nonce'] != nonce or value['port'] != port:
        raise RuntimeError('ownership mismatch')
    return value
def store():
    value = {'nonce':nonce, 'pid':os.getpid(), 'start_ticks':ticks(os.getpid()), 'port':port}
    descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream)
    return value
def cleanup(value):
    with contextlib.suppress(FileNotFoundError):
        current = load(path)
        if current == value:
            os.unlink(path)
def listening(value):
    if not owned(value):
        return False
    with open('/proc/net/tcp') as stream:
        rows = [line.split() for line in stream.readlines()[1:]]
        address = '0100007F:' + format(port, '04X')
        inodes = {row[9] for row in rows if row[1] == address and row[3] == '0A'}
    for name in os.listdir('/proc/' + str(value['pid']) + '/fd'):
        with contextlib.suppress(FileNotFoundError):
            link = os.readlink('/proc/' + str(value['pid']) + '/fd/' + name)
            if link.startswith('socket:[') and link[8:-1] in inodes:
                return True
    return False
if mode == 'gateway':
    with socket.socket() as check:
        check.bind(('127.0.0.1', port))
    value = store()
    try:
        sys.argv = ['flowtest-mcp', '--transport', 'streamable-http',
            '--api-base-url', 'http://127.0.0.1:8000', '--host', '127.0.0.1',
            '--port', str(port), '--path', '/mcp']
        from app.mcp.cli import main
        main()
    finally:
        cleanup(value)
elif mode == 'probe':
    value = load(path)
    print(json.dumps(value | {'alive':owned(value), 'listening':listening(value)}))
elif mode == 'stop':
    try:
        value = load(path)
    except FileNotFoundError:
        print(json.dumps({'nonce':nonce, 'key':key, 'removed':True}))
    else:
        if owned(value):
            os.kill(value['pid'], signal.SIGTERM)
            for _ in range(50):
                if not owned(value):
                    break
                time.sleep(0.1)
        if owned(value):
            os.kill(value['pid'], signal.SIGKILL)
            for _ in range(20):
                if not owned(value):
                    break
                time.sleep(0.1)
        if owned(value):
            raise RuntimeError('owned process survived')
        cleanup(value)
        print(json.dumps({'nonce':nonce, 'key':key, 'removed':not os.path.exists(path)}))
elif mode == 'relay':
    parent = load(gateway)
    if not listening(parent):
        raise RuntimeError('gateway not owned')
    value = store()
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=15) as connection:
            def send():
                try:
                    while True:
                        chunk = os.read(0, 65536)
                        if not chunk:
                            break
                        connection.sendall(chunk)
                finally:
                    with contextlib.suppress(OSError):
                        connection.shutdown(socket.SHUT_WR)
            threading.Thread(target=send, daemon=True).start()
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
    finally:
        cleanup(value)
else:
    raise RuntimeError('unsupported fixed mode')
"""


class GatewayProcess(Contract):
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    pid: int = Field(ge=1)
    start_ticks: str = Field(pattern=r"^[0-9]+$")
    port: Literal[8766]
    alive: Literal[True]
    listening: Literal[True]


class ProcessRemoval(Contract):
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    key: str = Field(pattern=r"^gateway$|^[0-9a-f]{32}$")
    removed: Literal[True]


@dataclass(frozen=True)
class GatewayEndpoint:
    url: str
    container_id: str
    nonce: str
    process: GatewayProcess


def command(container_id: str, mode: str, nonce: str, key: str = "gateway") -> list[str]:
    if (
        re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
        or mode not in {"gateway", "probe", "stop", "relay"}
        or re.fullmatch(r"gateway|[0-9a-f]{32}", key) is None
    ):
        raise HarnessError("SELFTEST_CONTAINER_GATEWAY_ARGUMENT_INVALID")
    docker = shutil.which("docker")
    if docker is None:
        raise HarnessError("SELFTEST_DOCKER_UNAVAILABLE")
    return [
        docker,
        "exec",
        "--interactive",
        container_id,
        "python",
        "-c",
        REMOTE,
        mode,
        nonce,
        "8766",
        key,
    ]


async def _process(
    container: str, mode: str, nonce: str, key: str = "gateway", *, pipes: bool = False
) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *command(container, mode, nonce, key),
        env={"PATH": os.environ.get("PATH", "")},
        stdin=asyncio.subprocess.PIPE if pipes else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE
        if pipes or mode in {"probe", "stop"}
        else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def _control(
    container: str, mode: str, nonce: str, key: str = "gateway"
) -> dict[str, object]:
    process = await _process(container, mode, nonce, key)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise HarnessError("SELFTEST_CONTAINER_GATEWAY_CONTROL_TIMEOUT") from None
    if process.returncode or len(output) > 2048:
        raise HarnessError("SELFTEST_CONTAINER_GATEWAY_CONTROL_FAILED")
    value = json.loads(output)
    if not isinstance(value, dict):
        raise HarnessError("SELFTEST_CONTAINER_GATEWAY_CONTROL_INVALID")
    return value


async def _ready(container: str, nonce: str, child: asyncio.subprocess.Process) -> GatewayProcess:
    for _ in range(50):
        if child.returncode is not None:
            raise HarnessError("SELFTEST_CONTAINER_GATEWAY_START_FAILED")
        try:
            receipt = GatewayProcess.model_validate(await _control(container, "probe", nonce))
        except (HarnessError, ValueError):
            await asyncio.sleep(0.1)
        else:
            if receipt.nonce != nonce:
                raise HarnessError("SELFTEST_CONTAINER_GATEWAY_NONCE_MISMATCH")
            return receipt
    raise HarnessError("SELFTEST_CONTAINER_GATEWAY_START_TIMEOUT")


async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()


class GatewayRelay:
    def __init__(self, container: str, nonce: str, deadline: datetime) -> None:
        self.container, self.nonce, self.deadline = container, nonce, deadline
        self.keys: list[str] = []
        self.children: list[asyncio.subprocess.Process] = []
        self.tasks: set[asyncio.Task[None]] = set()

    def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self.connection(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            if len(self.keys) >= 500:
                raise HarnessError("SELFTEST_CONTAINER_RELAY_CONNECTION_LIMIT")
            key = uuid4().hex
            self.keys.append(key)
            child = await _process(self.container, "relay", self.nonce, key, pipes=True)
            self.children.append(child)
            if child.stdin is None or child.stdout is None:
                raise HarnessError("SELFTEST_CONTAINER_RELAY_PIPE_UNAVAILABLE")
            remaining = min(45, (self.deadline - datetime.now(UTC)).total_seconds())
            async with asyncio.timeout(max(0, remaining)):
                await asyncio.gather(_copy(reader, child.stdin), _copy(child.stdout, writer))
        except (OSError, TimeoutError, HarnessError):
            # Only bytes are relayed; neither network data nor exceptions are logged.
            pass
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def stop(self) -> tuple[ProcessRemoval, ...]:
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        removals: list[ProcessRemoval] = []
        incomplete = False
        for key in (*self.keys, "gateway"):
            try:
                receipt = ProcessRemoval.model_validate(
                    await _control(self.container, "stop", self.nonce, key)
                )
                if receipt.nonce != self.nonce or receipt.key != key:
                    raise HarnessError("SELFTEST_CONTAINER_GATEWAY_CLEANUP_MISMATCH")
            except (HarnessError, ValidationError, OSError, TimeoutError):
                incomplete = True
            else:
                removals.append(receipt)
        for child in self.children:
            try:
                await asyncio.wait_for(child.wait(), timeout=5)
            except TimeoutError:
                child.kill()
                await child.wait()
                incomplete = True
        if incomplete:
            raise HarnessError("SELFTEST_CONTAINER_GATEWAY_CLEANUP_INCOMPLETE")
        return tuple(removals)


@asynccontextmanager
async def container_http_gateway(
    binding: StackBinding, directory: Path, output: Path, *, deadline: datetime
) -> AsyncIterator[GatewayEndpoint]:
    verify_binding(binding, directory)
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if not 0 < remaining <= 600:
        raise HarnessError("SELFTEST_CONTAINER_GATEWAY_DEADLINE_EXPIRED")
    nonce = uuid4().hex
    write_json(output / "gateway-cleanup.json", {"nonce": nonce, "completed": False})
    child = await _process(binding.runner_container_id, "gateway", nonce)
    relay = GatewayRelay(binding.runner_container_id, nonce, deadline)
    server: asyncio.Server | None = None
    try:
        async with asyncio.timeout(min(15, remaining)):
            receipt = await _ready(binding.runner_container_id, nonce, child)
        write_json(output / "gateway-start.json", receipt)
        server = await asyncio.start_server(relay.accept, "127.0.0.1", 0, limit=65536)
        port = server.sockets[0].getsockname()[1]
        yield GatewayEndpoint(
            f"http://127.0.0.1:{port}/mcp", binding.runner_container_id, nonce, receipt
        )
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()
        removals = await relay.stop()
        await asyncio.wait_for(child.wait(), timeout=5)
        write_json(
            output / "gateway-cleanup.json",
            {
                "nonce": nonce,
                "processes": [row.model_dump(mode="json") for row in removals],
                "completed": True,
            },
        )
