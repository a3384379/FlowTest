"""Bounded CLI process adapter. Tests supply a synthetic executable, never a model."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from scripts.selftest.contracts import Contract, Sha256, canonical_digest
from scripts.selftest.host_contracts import HostModelSummary
from scripts.selftest.host_events import EventLedger, EventReceipt
from scripts.selftest.host_gateway import BoundedGateway
from scripts.selftest.host_ipc import PrivateMCPRelay
from scripts.selftest.host_launch import CodexLaunchPlan
from scripts.selftest.io import HarnessError, write_json


class ProcessReceipt(Contract):
    prompt_digest: Sha256
    authorization_digest: Sha256
    exit_code: int | None
    reason_code: str | None
    started_at: datetime
    completed_at: datetime
    stderr_digest: Sha256
    stderr_bytes: int
    events: tuple[EventReceipt, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    billed_cost: Literal["unknown"] = "unknown"
    summary: HostModelSummary | None = None


@dataclass(frozen=True)
class ProcessOutput:
    receipt: ProcessReceipt
    ledger: EventLedger


async def _stderr(reader: asyncio.StreamReader) -> tuple[str, int]:
    digest, count = hashlib.sha256(), 0
    while chunk := await reader.read(8192):
        digest.update(chunk)
        count += len(chunk)
        if count > 1048576:
            raise HarnessError("HOST_STDERR_BUDGET_EXCEEDED")
    return digest.hexdigest(), count


async def _events(reader: asyncio.StreamReader, ledger: EventLedger) -> None:
    while encoded := await reader.readline():
        ledger.accept(encoded)


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    # This session/group was created by this invocation; no daily process is addressed.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await asyncio.wait_for(process.wait(), timeout=3)


async def _stream(
    process: asyncio.subprocess.Process,
    prompt: str,
    ledger: EventLedger,
) -> tuple[str, int]:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise HarnessError("HOST_PROCESS_PIPE_MISSING")
    process.stdin.write(prompt.encode())
    await process.stdin.drain()
    process.stdin.close()
    stdout_task = asyncio.create_task(_events(process.stdout, ledger))
    stderr_task = asyncio.create_task(_stderr(process.stderr))
    wait_task = asyncio.create_task(process.wait())
    tasks = (stdout_task, stderr_task, wait_task)
    try:
        await asyncio.gather(*tasks)
        if wait_task.result() != 0:
            raise HarnessError("HOST_PROCESS_EXIT_NONZERO")
        return stderr_task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _stream_until_stopped(
    process: asyncio.subprocess.Process, prompt: str, ledger: EventLedger, gateway: BoundedGateway
) -> tuple[str, int]:
    stream = asyncio.create_task(_stream(process, prompt, ledger))
    stopped = asyncio.create_task(gateway.stopped.wait())
    try:
        await asyncio.wait((stream, stopped), return_when=asyncio.FIRST_COMPLETED)
        if gateway.stopped.is_set():
            raise HarnessError(
                gateway.stop_receipt.reason_code if gateway.stop_receipt else "HOST_STOPPED"
            )
        return await stream
    finally:
        for task in (stream, stopped):
            if not task.done():
                task.cancel()
        await asyncio.gather(stream, stopped, return_exceptions=True)


async def run_process(
    plan: CodexLaunchPlan,
    *,
    prompt: str,
    gateway: BoundedGateway,
    socket_path: Path,
    output_dir: Path,
) -> ProcessOutput:
    if plan.authorization_digest != canonical_digest(gateway.authorization.model_dump(mode="json")):
        raise HarnessError("HOST_PROCESS_AUTHORIZATION_CHANGED")
    if plan.prompt_digest != canonical_digest(prompt):
        raise HarnessError("HOST_PROCESS_PROMPT_CHANGED")
    if output_dir.exists():
        raise HarnessError("HOST_PROCESS_OUTPUT_MUST_BE_NEW")
    output_dir.mkdir(mode=0o700, parents=True)
    started, before = datetime.now(UTC), len(gateway.receipts)
    ledger = EventLedger(frozenset(gateway.authorization.allowed_tools))
    process: asyncio.subprocess.Process | None = None
    reason: str | None = None
    cancelled = False
    summary: HostModelSummary | None = None
    stderr_digest, stderr_count = hashlib.sha256(b"").hexdigest(), 0
    try:
        async with PrivateMCPRelay(gateway, socket_path):
            remaining = (min(plan.deadline, gateway.deadline) - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise HarnessError("HOST_DEADLINE_EXCEEDED")
            async with asyncio.timeout(remaining):
                process = await asyncio.create_subprocess_exec(
                    *plan.arguments,
                    cwd=plan.working_directory,
                    env=dict(plan.environment),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    limit=1048577,
                )
                stderr_digest, stderr_count = await _stream_until_stopped(
                    process, prompt, ledger, gateway
                )
                ledger.reconcile(tuple(gateway.receipts[before:]))
                summary = _summary(plan)
    except asyncio.CancelledError:
        reason, cancelled = "HOST_PROCESS_CANCELLED", True
    except TimeoutError:
        reason = "HOST_DEADLINE_EXCEEDED"
    except (HarnessError, OSError, ValueError) as error:
        reason = (
            str(error) if isinstance(error, HarnessError) else "HOST_PROCESS_PROTOCOL_OR_IO_ERROR"
        )
    finally:
        if process is not None:
            await _terminate(process)
    receipt = ProcessReceipt(
        prompt_digest=plan.prompt_digest,
        authorization_digest=plan.authorization_digest,
        exit_code=process.returncode if process else None,
        reason_code=reason,
        started_at=started,
        completed_at=datetime.now(UTC),
        stderr_digest=stderr_digest,
        stderr_bytes=stderr_count,
        events=tuple(ledger.receipts),
        input_tokens=ledger.input_tokens,
        output_tokens=ledger.output_tokens,
        summary=summary,
    )
    write_json(output_dir / "process.json", receipt)
    if cancelled:
        raise asyncio.CancelledError
    return ProcessOutput(receipt, ledger)


def _summary(plan: CodexLaunchPlan) -> HostModelSummary:
    index = plan.arguments.index("--output-last-message") + 1
    path = Path(plan.arguments[index])
    if path.is_symlink() or path.stat().st_size > 16384:
        raise HarnessError("HOST_MODEL_SUMMARY_INVALID")
    return HostModelSummary.model_validate_json(path.read_bytes())
