"""A real isolated installer process; private credentials never appear in argv or receipts."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import Field
from scripts.selftest.bootstrap_journal import BootstrapJournal, bootstrap_lock
from scripts.selftest.contracts import Contract, Identity
from scripts.selftest.failures import failure_codes
from scripts.selftest.fixed_baseline import CorePack, install_fixed_baseline, load_core_pack
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.security_boundary_http import BoundaryAPI


class InstallWorkerRuntime(Contract):
    url: str
    project_id: UUID
    organization_id: UUID
    token: str = Field(repr=False)
    nonce: Identity
    batch_key: Identity
    deadline: datetime
    budget_path: Path
    state_directory: Path
    receipt_path: Path
    mode: Literal["normal", "hold", "partial", "unknown"]


class InstallWorkerReceipt(Contract):
    mode: Literal["normal", "hold", "partial", "unknown"]
    exit_code: Literal[0, 2, 3, 4]
    reason_codes: tuple[Identity, ...] = ()


class InterruptedAfterKnownPhase(Exception):
    pass


class WorkerAPI(BoundaryAPI):
    def __init__(self, runtime: InstallWorkerRuntime, budget: ProtocolHttpBudget) -> None:
        super().__init__(
            runtime.url, budget, runtime.deadline, runtime.token, str(runtime.organization_id)
        )
        self.mode = runtime.mode

    async def object(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        result = await super().object(method, path, payload, idempotency_key=idempotency_key)
        if self.mode == "unknown" and method == "POST" and path.endswith("/environments"):
            raise HarnessError("SELFTEST_INSTALL_UNKNOWN_POST_RESULT")
        return result


def selected_initialization_pack() -> CorePack:
    pack = load_core_pack()
    return pack.model_copy(
        update={
            "manifest": pack.manifest.model_copy(
                update={"scenario_ids": pack.manifest.scenario_ids[:1]}
            ),
            "apis": pack.apis[:1],
            "workflows": pack.workflows[:1],
            "expectations": pack.expectations[:1],
            "fixtures": pack.fixtures[:1],
        }
    )


async def _install(api: WorkerAPI, runtime: InstallWorkerRuntime) -> None:
    journal = BootstrapJournal(runtime.state_directory, runtime.nonce)
    root = f"/projects/{runtime.project_id}"
    environment = await journal.create(
        api,
        "environment",
        root + "/environments",
        {
            "name": runtime.batch_key + "-environment",
            "base_url": "https://synthetic.invalid",
            "classification": "test",
        },
    )
    matches = [
        item
        for item in objects_value(await api.request("GET", root + "/environments"))
        if item["id"] == environment["id"] and item["name"] == runtime.batch_key + "-environment"
    ]
    if len(matches) != 1:
        raise HarnessError("SELFTEST_INSTALL_ENVIRONMENT_IDENTITY_CHANGED")
    if runtime.mode == "partial":
        raise InterruptedAfterKnownPhase
    service = await journal.create(
        api,
        "service",
        root + "/services",
        {
            "name": runtime.batch_key + "-service",
            "service_key": "initialization_fixture",
        },
    )
    environment_id, service_id = text_value(environment["id"]), text_value(service["id"])
    await journal.create(
        api,
        "endpoint",
        root + f"/environments/{environment_id}/service-endpoints",
        {
            "service_id": service_id,
            "variant": "default",
            "base_url": "https://synthetic.invalid",
        },
    )
    await api.object(
        "PATCH", root + f"/environments/{environment_id}", {"default_service_id": service_id}
    )
    await install_fixed_baseline(
        api,
        project_id=str(runtime.project_id),
        environment_id=environment_id,
        service_id=service_id,
        batch_key=runtime.batch_key,
        nonce=runtime.nonce,
        output_dir=runtime.state_directory / "native",
        pack=selected_initialization_pack(),
    )


async def _barrier(runtime: InstallWorkerRuntime) -> None:
    write_json(runtime.state_directory / "lock-acquired.json", {"nonce": runtime.nonce})
    for _ in range(200):
        if (runtime.state_directory / "release.json").exists():
            return
        if datetime.now(UTC) >= runtime.deadline:
            break
        await asyncio.sleep(0.05)
    raise HarnessError("SELFTEST_INSTALL_BARRIER_DEADLINE")


async def run_worker(runtime: InstallWorkerRuntime) -> InstallWorkerReceipt:
    parsed = urlsplit(runtime.url)
    host = parsed.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if parsed.scheme != "http" or not loopback or parsed.username or parsed.password:
        raise HarnessError("SELFTEST_INSTALL_OWNED_LOOPBACK_REQUIRED")
    if runtime.receipt_path.exists():
        raise HarnessError("SELFTEST_INSTALL_WORKER_ATTEMPT_REPLAY_FORBIDDEN")
    runtime.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    budget = ProtocolHttpBudget(runtime.budget_path, runtime.nonce, runtime.deadline.timestamp())
    api = WorkerAPI(runtime, budget)
    try:
        with bootstrap_lock(runtime.state_directory, runtime.nonce):
            if runtime.mode == "hold":
                await _barrier(runtime)
            await _install(api, runtime)
        receipt = InstallWorkerReceipt(mode=runtime.mode, exit_code=0)
    except InterruptedAfterKnownPhase:
        receipt = InstallWorkerReceipt(
            mode=runtime.mode,
            exit_code=3,
            reason_codes=("SELFTEST_INSTALL_INTERRUPTED_AFTER_COMPLETED_PHASE",),
        )
    except (HarnessError, httpx.HTTPError, ValueError, OSError) as failure:
        reasons = failure_codes(failure)
        code = 4 if "SELFTEST_BOOTSTRAP_IN_PROGRESS_OR_NEEDS_REVIEW" in reasons else 2
        receipt = InstallWorkerReceipt(mode=runtime.mode, exit_code=code, reason_codes=reasons)
    finally:
        await api.close()
    write_json(runtime.receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="隔离初始化子进程")
    parser.add_argument("--runtime", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.runtime.stat().st_mode & 0o077:
        raise HarnessError("SELFTEST_INSTALL_PRIVATE_RUNTIME_PERMISSIONS")
    runtime = InstallWorkerRuntime.model_validate(read_json(arguments.runtime))
    raise SystemExit(asyncio.run(run_worker(runtime)).exit_code)


if __name__ == "__main__":
    main()
