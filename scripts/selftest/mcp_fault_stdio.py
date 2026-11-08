"""An actual OS-pipe relay for one owned SDK fault attempt; no frame logging."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, object_value, write_json
from scripts.selftest.mcp_fault_contracts import Fault, ProcessIdentity
from scripts.selftest.mcp_fault_http import frame_bytes, receipt
from scripts.selftest.mcp_fault_process import control, kill, process_command


class PipeRelay:
    def __init__(
        self,
        nonce: str,
        fault: Fault,
        output: Path,
        child: subprocess.Popen[bytes],
        identity: Callable[[], ProcessIdentity],
        crash: Callable[[ProcessIdentity], None],
    ) -> None:
        self.nonce, self.fault, self.output = nonce, fault, output
        self.child, self.identity, self.crash = child, identity, crash
        self.frame: JsonObject | None = None
        self.received = False
        self.rejected_replay = False
        self.catalog_ids: set[str] = set()

    def forward_input(self) -> None:
        if self.child.stdin is None:
            return
        try:
            while line := sys.stdin.buffer.readline(262145):
                if not line.endswith(b"\n") or len(line.removesuffix(b"\n")) > 262144:
                    raise HarnessError("SELFTEST_FAULT_PIPE_FRAME_LIMIT")
                frame = object_value(json.loads(line))
                if frame.get("method") == "tools/list":
                    if len(self.catalog_ids) >= 100:
                        raise HarnessError("SELFTEST_FAULT_PIPE_METADATA_LIMIT")
                    self.catalog_ids.add(canonical_digest(frame["id"]))
                if frame.get("method") == "tools/call":
                    if self.frame is not None:
                        self.rejected_replay = True
                        return
                    self.frame = frame
                # The forwarded JSON frame is canonical; its delimiter is not
                # part of forwarded_digest/forwarded_bytes in the receipt.
                self.child.stdin.write(frame_bytes(frame) + b"\n")
                self.child.stdin.flush()
        except (OSError, ValueError, HarnessError):
            return
        finally:
            with contextlib.suppress(OSError):
                self.child.stdin.close()

    def fault_response(self, line: bytes) -> bool:
        body = object_value(json.loads(line))
        if self.frame is None or body.get("id") != self.frame.get("id"):
            return False
        self.received = True
        owned = self.identity()
        killed = self.fault == "server_crash"
        if killed:
            self.crash(owned)
        observed = receipt(
            self.nonce,
            self.frame,
            frame_bytes(self.frame),
            line,
            self.fault,
            process=owned,
            killed=killed,
        )
        write_json(self.output, observed)
        if self.fault == "timeout":
            time.sleep(4)
        return self.fault in {"pipe_break", "unknown_mutation", "server_crash", "timeout"}

    def run(self) -> None:
        threading.Thread(target=self.forward_input, daemon=True).start()
        if self.child.stdout is None:
            raise HarnessError("SELFTEST_FAULT_PIPE_UNAVAILABLE")
        while line := self.child.stdout.readline(1048578):
            if not line.endswith(b"\n") or len(line.removesuffix(b"\n")) > 1048576:
                raise HarnessError("SELFTEST_FAULT_PIPE_FRAME_LIMIT")
            body = object_value(json.loads(line))
            limit = 1048576 if canonical_digest(body.get("id")) in self.catalog_ids else 262144
            if len(line.removesuffix(b"\n")) > limit:
                raise HarnessError("SELFTEST_FAULT_PIPE_FRAME_LIMIT")
            if self.fault_response(line):
                os.close(sys.stdout.fileno())
                return
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()


def serve(container: str, nonce: str, fault: Fault, output: Path) -> None:
    command = process_command(container, nonce, "serve")
    child = subprocess.Popen(  # noqa: S603 - exact allowlisted Docker/container/nonce command
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={
            "PATH": os.environ.get("PATH", ""),
            "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": os.environ.get(
                "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN", ""
            ),
        },
    )

    def identity() -> ProcessIdentity:
        return ProcessIdentity.model_validate(asyncio.run(control(container, nonce, "identity")))

    def crash(value: ProcessIdentity) -> None:
        asyncio.run(kill(container, value, kind="stdio"))

    try:
        PipeRelay(nonce, fault, output, child, identity, crash).run()
    finally:
        removed = asyncio.run(control(container, nonce, "stop"))
        if removed.get("removed") is not True:
            raise HarnessError("SELFTEST_FAULT_PIPE_CLEANUP_INCOMPLETE")
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
            raise HarnessError("SELFTEST_FAULT_PIPE_LOCAL_CLEANUP_INCOMPLETE") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="仅转发本批专属 MCP 标准输入输出管道")
    parser.add_argument("--container", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument(
        "--fault",
        required=True,
        choices=(
            "oversized_field",
            "inactive_account_creator",
            "timeout",
            "pipe_break",
            "server_crash",
            "unknown_mutation",
        ),
    )
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        serve(args.container, args.nonce, args.fault, args.receipt)
    except HarnessError as error:
        write_json(args.receipt.with_name("dispatch-error.json"), {"code": str(error)})
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
