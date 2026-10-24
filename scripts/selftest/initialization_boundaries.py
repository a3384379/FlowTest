"""Two real child processes and exact public inventories characterize safe installation recovery."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

import httpx
from scripts.selftest.boundary_pack import load_boundary_pack
from scripts.selftest.boundary_reporting import write_boundary_junit
from scripts.selftest.contracts import TargetDisposalReceipt
from scripts.selftest.fixed_baseline import FixedInstallation, load_core_pack
from scripts.selftest.initialization_contracts import (
    INIT_SCENARIOS,
    InitializationEvidence,
    InitializationManifest,
    InitializationObservation,
    InitializationResult,
)
from scripts.selftest.initialization_inventory import inventory, mapping_matches
from scripts.selftest.initialization_worker import InstallWorkerReceipt, InstallWorkerRuntime
from scripts.selftest.io import HarnessError, read_json, text_value, write_json
from scripts.selftest.local_stack import ROOT, StackBinding, _verify_removed
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.security_boundary_setup import SecurityActors, security_actors
from scripts.selftest.verify_initialization_boundaries import verify_initialization_boundaries


async def _child(runtime: InstallWorkerRuntime, index: int) -> InstallWorkerReceipt:
    private = runtime.state_directory.parent
    runtime_path = private / f"runtime-{index}.json"
    write_json(runtime_path, runtime)
    error_path = private / f"child-{index}.stderr.log"
    descriptor = os.open(error_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as error:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "scripts.selftest.initialization_worker",
            "--runtime",
            str(runtime_path),
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(ROOT) + os.pathsep + str(ROOT / "backend"),
            },
            stdout=asyncio.subprocess.DEVNULL,
            stderr=error,
        )
    try:
        remaining = (runtime.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError
        code = await asyncio.wait_for(process.wait(), remaining)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), 5)
        raise
    if not runtime.receipt_path.exists():
        raise HarnessError("SELFTEST_INSTALL_WORKER_RECEIPT_MISSING")
    receipt = InstallWorkerReceipt.model_validate(read_json(runtime.receipt_path))
    if code != receipt.exit_code:
        raise HarnessError("SELFTEST_INSTALL_WORKER_EXIT_MISMATCH")
    return receipt


async def _concurrent(runtime: InstallWorkerRuntime) -> tuple[InstallWorkerReceipt, ...]:
    async with asyncio.TaskGroup() as group:
        first = group.create_task(_child(runtime.model_copy(update={"mode": "hold"}), 0))
        try:
            for _ in range(200):
                if (runtime.state_directory / "lock-acquired.json").exists():
                    break
                if first.done():
                    await first
                    raise HarnessError("SELFTEST_INSTALL_FIRST_WORKER_DID_NOT_ACQUIRE")
                await asyncio.sleep(0.05)
            else:
                raise HarnessError("SELFTEST_INSTALL_LOCK_BARRIER_MISSING")
            second = await _child(
                runtime.model_copy(
                    update={
                        "mode": "normal",
                        "receipt_path": runtime.receipt_path.with_name("second.json"),
                    }
                ),
                1,
            )
        finally:
            write_json(runtime.state_directory / "release.json", {"nonce": runtime.nonce})
    return first.result(), second


async def _case(
    actors: SecurityActors,
    runtime: InstallWorkerRuntime,
    kind: Literal["concurrent", "partial", "unknown"],
    budget: ProtocolHttpBudget,
) -> InitializationObservation:
    before = await inventory(actors.observer, runtime.project_id)
    if kind == "concurrent":
        workers = await _concurrent(runtime)
    else:
        workers = (await _child(runtime.model_copy(update={"mode": kind}), 0),)
    after = await inventory(actors.observer, runtime.project_id)
    original = _installed(runtime)
    admitted = budget.counts()[0]
    resumed = await _child(
        runtime.model_copy(
            update={"mode": "normal", "receipt_path": runtime.receipt_path.with_name("resume.json")}
        ),
        2,
    )
    after_restart = budget.counts()[0]
    workers = (*workers, resumed)
    repeated = await inventory(actors.observer, runtime.project_id)
    installed = _installed(runtime)
    matched = installed is not None and await mapping_matches(actors.observer, installed)
    return InitializationObservation(
        scenario_id="ST-INIT-" + kind,
        project_id=runtime.project_id,
        before=before,
        after=after,
        repeat=repeated,
        workers=workers,
        installation=installed,
        resumed_installation=original if kind == "concurrent" else installed,
        published_mapping_matches=matched,
        unknown_posts_before_restart=admitted if kind == "unknown" else None,
        unknown_posts_after_restart=after_restart if kind == "unknown" else None,
    )


def _installed(runtime: InstallWorkerRuntime) -> FixedInstallation | None:
    path = runtime.state_directory / "native/installation.json"
    return FixedInstallation.model_validate(read_json(path)) if path.exists() else None


async def execute_initialization_boundaries(
    *,
    binding: StackBinding,
    bootstrap_token: str,
    batch_key: str,
    output_dir: Path,
    deadline: datetime,
    transport: httpx.AsyncBaseTransport | None = None,
) -> InitializationResult:
    if (output_dir / "manifest.json").exists():
        raise HarnessError("SELFTEST_INSTALL_NEW_ATTEMPT_REQUIRED")
    remaining = (deadline - datetime.now(UTC)).total_seconds() if deadline.tzinfo else -1
    if not 0 < remaining <= 600:
        raise HarnessError("SELFTEST_INSTALL_BATCH_DEADLINE_INVALID")
    manifest = InitializationManifest(
        pack_digest=load_boundary_pack("initialization-boundaries-v1", INIT_SCENARIOS).digest,
        source_pack_digest=load_core_pack().digest,
        project_name=binding.project_name,
        nonce=binding.nonce,
        source_digest=binding.source_digest,
        profile=binding.runtime_profile,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
        created_at=datetime.now(UTC),
        deadline=deadline,
    )
    write_json(output_dir / "manifest.json", manifest)
    private = output_dir / "private-worker-state"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    budget = ProtocolHttpBudget(
        private / "shared-budget.sqlite3", binding.nonce, deadline.timestamp()
    )
    cases = []
    async with security_actors(
        binding, bootstrap_token, batch_key, budget, deadline, transport=transport
    ) as actors:
        project = await actors.owner.object(
            "POST",
            "/projects",
            {
                "name": batch_key + "-unknown",
                "organization_id": str(actors.identity.organization_id),
            },
        )
        unknown_id = UUID(text_value(project["id"]))
        await actors.owner.object(
            "PUT",
            f"/projects/{unknown_id}/members/{actors.identity.observer_id}",
            {
                "user_id": str(actors.identity.observer_id),
                "role": "viewer",
            },
        )
        projects = (*actors.identity.project_ids, unknown_id)
        for scenario, project_id in zip(INIT_SCENARIOS, projects, strict=True):
            kind = scenario.removeprefix("ST-INIT-")
            state = private / kind / "state"
            state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            runtime = InstallWorkerRuntime(
                url=binding.target_url,
                project_id=project_id,
                organization_id=actors.identity.organization_id,
                token=actors.owner_token,
                nonce=binding.nonce,
                batch_key=batch_key + "-" + kind,
                deadline=deadline,
                budget_path=private / "shared-budget.sqlite3",
                state_directory=state,
                receipt_path=state.parent / "first.json",
                mode="normal",
            )
            cases.append(
                await _case(
                    actors, runtime, cast(Literal["concurrent", "partial", "unknown"], kind), budget
                )
            )
    admitted, rejected = budget.counts()
    evidence = InitializationEvidence(
        manifest_digest=manifest.digest,
        scenarios=tuple(cases),
        http_attempts=admitted,
        rejected_attempts=rejected,
        collected_at=datetime.now(UTC),
        cleanup_status="pending",
    )
    return _persist(
        InitializationResult(
            manifest=manifest,
            evidence=evidence,
            batch_verdict="blocked",
            exit_code=2,
            reason_codes=(),
        ),
        output_dir,
    )


def _persist(result: InitializationResult, directory: Path) -> InitializationResult:
    reasons = verify_initialization_boundaries(result)
    result = result.model_copy(
        update={
            "batch_verdict": "blocked" if reasons else "passed",
            "exit_code": 2 if reasons else 0,
            "reason_codes": reasons,
        }
    )
    write_json(directory / "evidence.json", result.evidence)
    write_json(directory / "result.json", result)
    write_boundary_junit(
        directory, INIT_SCENARIOS, reasons, purpose="diagnostic_subset_initialization_no_native_run"
    )
    return result


def finalize_initialization_boundaries(
    result: InitializationResult,
    *,
    binding: StackBinding,
    stack_directory: Path,
    output_dir: Path,
) -> InitializationResult:
    manifest = result.manifest
    if (
        StackBinding.model_validate(read_json(stack_directory / "stack.json")) != binding
        or read_json(stack_directory / "ownership.json")
        != {"project_name": binding.project_name, "nonce": binding.nonce}
        or read_json(stack_directory / "cleanup.json")
        != {"project_name": binding.project_name, "status": "completed"}
        or (
            manifest.project_name,
            manifest.nonce,
            manifest.target_container_id,
            manifest.target_volume,
            manifest.target_image,
        )
        != (
            binding.project_name,
            binding.nonce,
            binding.target_container_id,
            binding.target_volume,
            binding.candidate_image_digest,
        )
    ):
        raise HarnessError("SELFTEST_INSTALL_DISPOSAL_IDENTITY_MISMATCH")
    _verify_removed(binding.project_name)
    if result.evidence.cleanup_status == "completed":
        return _persist(result, output_dir)
    if not (output_dir / "evidence.pre-disposal.json").exists():
        write_json(output_dir / "evidence.pre-disposal.json", result.evidence)
    receipt = TargetDisposalReceipt(
        project_name=binding.project_name,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
        removed_at=datetime.now(UTC),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    evidence = result.evidence.model_copy(
        update={"cleanup_status": "completed", "target_disposal": receipt}
    )
    return _persist(result.model_copy(update={"evidence": evidence}), output_dir)
