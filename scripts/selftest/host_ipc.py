"""H-owned Unix socket: only MCP JSON-RPC bytes cross into the model worker."""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from pathlib import Path

import anyio
from mcp.server.stdio import stdio_server
from scripts.selftest.host_gateway import BoundedGateway
from scripts.selftest.io import HarnessError


class PrivateMCPRelay:
    def __init__(self, gateway: BoundedGateway, path: Path) -> None:
        self.gateway, self.path = gateway, path
        self.listener: socket.socket | None = None
        self.accept_task: asyncio.Task[None] | None = None
        self.connections: set[socket.socket] = set()
        self.sessions: set[asyncio.Task[None]] = set()
        self.inode: int | None = None

    async def __aenter__(self) -> PrivateMCPRelay:
        if self.path.exists() or self.path.is_symlink():
            raise HarnessError("HOST_RELAY_PATH_EXISTS")
        if self.path.parent.stat().st_mode & 0o077:
            raise HarnessError("HOST_RELAY_DIRECTORY_NOT_PRIVATE")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        self.listener = listener
        os.chmod(self.path, 0o600)
        self.inode = self.path.stat().st_ino
        listener.listen(2)
        listener.setblocking(False)
        self.accept_task = asyncio.create_task(self._accept())
        return self

    async def _accept(self) -> None:
        if self.listener is None:
            raise HarnessError("HOST_RELAY_NOT_STARTED")
        loop = asyncio.get_running_loop()
        while True:
            connection, _ = await loop.sock_accept(self.listener)
            connection.setblocking(True)
            self.connections.add(connection)
            task = asyncio.create_task(self._serve(connection))
            self.sessions.add(task)
            task.add_done_callback(self.sessions.discard)

    async def _serve(self, connection: socket.socket) -> None:
        reader = anyio.wrap_file(connection.makefile("r", encoding="utf-8"))
        writer = anyio.wrap_file(connection.makefile("w", encoding="utf-8"))
        try:
            async with stdio_server(stdin=reader, stdout=writer) as streams:
                server = self.gateway.server()
                await server.run(streams[0], streams[1], server.create_initialization_options())
        finally:
            await reader.aclose()
            await writer.aclose()
            self.connections.discard(connection)
            connection.close()

    async def __aexit__(self, *_exceptions: object) -> None:
        if self.listener:
            self.listener.close()
        if self.accept_task:
            self.accept_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.accept_task
        for connection in tuple(self.connections):
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
        for task in tuple(self.sessions):
            task.cancel()
        if self.sessions:
            await asyncio.gather(*self.sessions, return_exceptions=True)
        if self.path.exists():
            if self.path.stat().st_ino != self.inode:
                raise HarnessError("HOST_RELAY_OWNERSHIP_CHANGED")
            self.path.unlink()
