"""No credentials/config/catalog exist here; relay raw MCP bytes to one H-owned socket."""

from __future__ import annotations

import argparse
import contextlib
import os
import socket
import sys
from threading import Thread


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(args.socket)

    def responses() -> None:
        while block := connection.recv(65536):
            sys.stdout.buffer.write(block)
            sys.stdout.buffer.flush()

    reader = Thread(target=responses, daemon=True)
    reader.start()
    try:
        while block := os.read(sys.stdin.fileno(), 65536):
            connection.sendall(block)
    finally:
        with contextlib.suppress(OSError):
            connection.shutdown(socket.SHUT_WR)
        reader.join(timeout=1)
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
