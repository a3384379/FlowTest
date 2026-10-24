"""Run real duplicate claims, deliveries and SIGKILL recovery on an owned queue profile."""

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from xml.etree.ElementTree import Element, SubElement, tostring

from scripts.selftest.bootstrap import bootstrap
from scripts.selftest.collect_evidence import _journal_snapshot, journal
from scripts.selftest.contracts import (
    Builds,
    FixtureBudgetScope,
    RequiredDisposal,
    TargetDisposalReceipt,
    canonical_digest,
)
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import (
    ROOT,
    StackBinding,
    _verify_removed,
    private_environment,
    verify_binding,
)
from scripts.selftest.run import _verifier_digest
from scripts.selftest.runtime_faults import (
    Assets,
    configure,
    install,
    read_plan,
    wait_marker,
    wait_terminal,
)
from scripts.selftest.worker_fault_contracts import (
    WorkerEvidence,
    WorkerGolden,
    WorkerManifest,
    WorkerObservation,
    WorkerReport,
)
from scripts.selftest.worker_fault_control import WorkerFaultControl
from scripts.selftest.worker_fault_verify import load_pack


def observe(output: Path) -> WorkerReport:
    status = subprocess.run(  # noqa: S603 -- fixed trusted observer module and typed owned path
        [
            sys.executable,
            "-m",
            "scripts.selftest.worker_fault_verify",
            "--output",
            str(output),
        ],
        timeout=30,
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"},
        check=False,
        capture_output=True,
    )
    if status.returncode not in {0, 2}:
        failure = output / f"independent-o-failure-{uuid4().hex}.stderr"
        failure.write_bytes(status.stderr)
        failure.chmod(0o600)
        raise HarnessError("WORKER_FAULT_OBSERVER_PROCESS_FAILED")
    report = WorkerReport.model_validate(read_json(output / "verification.json"))
    if report.exit_code != status.returncode:
        raise HarnessError("WORKER_FAULT_OBSERVER_EXIT_CHANGED")
    _junit(output, report)
    return report


def _junit(output: Path, report: WorkerReport) -> None:
    for role in ("execution", "verification"):
        suite = Element("testsuite", name="worker-faults-" + role, tests="4")
        failures = 0
        for row in report.scenarios:
            case = SubElement(suite, "testcase", name="ST-RUN-004/" + row.variant)
            SubElement(case, "system-out").text = "native_status=" + str(row.native_status)
            failed = (
                row.native_status == "failed"
                if role == "execution"
                else bool(row.reason_codes or report.reason_codes)
            )
            if failed:
                SubElement(
                    case,
                    "failure",
                    message="native_failed" if role == "execution" else "independent_mismatch",
                )
                failures += 1
            elif row.native_status is None:
                SubElement(case, "skipped", message="NOT_RUN")
        if role == "verification" and report.reason_codes:
            SubElement(suite, "system-err").text = ",".join(report.reason_codes)
        suite.set("failures", str(failures))
        (output / (role + ".junit.xml")).write_bytes(
            tostring(suite, encoding="utf-8", xml_declaration=True)
        )


async def _one(
    golden: WorkerGolden,
    asset: Assets,
    manifest: WorkerManifest,
    writer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    control: WorkerFaultControl,
) -> WorkerObservation:
    path = f"/projects/{asset.project_id}/test-plans/{asset.plan_id}/runs"
    before = None
    if golden.minimum_actor_processes:
        async with control.workers.held():
            launched = await writer.object("POST", path, {})
            run_id = UUID(text_value(launched["id"]))
            queued = await read_plan(reader, asset.project_id, run_id)
            if queued.run.status != "queued" or queued.execution_ids:
                raise HarnessError("WORKER_FAULT_NOT_QUEUED_BEFORE_CLAIM")
            fault = await asyncio.to_thread(control.parallel_claims, run_id)
    else:
        launched = await writer.object("POST", path, {})
        run_id = UUID(text_value(launched["id"]))
        if golden.worker_killed:
            await wait_marker(
                observer,
                asset.batch_key,
                asset.scenario_key,
                golden.markers[-1],
                manifest.deadline,
            )
            before = await _journal_snapshot(observer, asset.batch_key, asset.scenario_key)
            fault = await asyncio.to_thread(control.kill_and_restart)
        else:
            await wait_terminal(reader, asset.project_id, run_id, manifest.deadline)
            fault = await asyncio.to_thread(control.duplicate_delivery, run_id)
    native = await wait_terminal(reader, asset.project_id, run_id, manifest.deadline)
    if len(native.execution_ids) != 1:
        raise HarnessError("WORKER_FAULT_NATIVE_ATTEMPT_SET_CHANGED")
    raw = await reader.object(
        "GET",
        f"/ci/projects/{asset.project_id}/workflow-executions/{native.execution_ids[0]}/evidence",
    )
    return WorkerObservation(
        variant=golden.variant,
        run_id=run_id,
        native=native,
        fault=fault,
        native_error_codes=(
            text_value(raw["error_code"]) if raw["error_code"] is not None else None,
        ),
        journal=await journal(
            observer, asset.batch_key, asset.scenario_key, deadline=manifest.deadline
        ),
        source_case_id=UUID(text_value(raw["source_case_id"])),
        source_workflow_id=UUID(text_value(raw["workflow_id"])),
        source_workflow_fingerprint=text_value(raw["workflow_fingerprint"]),
        pre_kill_journal=before,
    )


async def run(directory: Path, output: Path) -> WorkerReport:
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    control = WorkerFaultControl(binding, directory)
    if binding.runtime_profile not in {"full", "compact"}:
        raise HarnessError("WORKER_FAULT_REQUIRES_QUEUE_PROFILE")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    pack, digest = load_pack()
    started = datetime.now(UTC)
    deadline = started + timedelta(seconds=pack.max_runtime_seconds)
    boot = await bootstrap(binding, directory)
    project = boot.installation.project_id
    writer = PublicAPI(
        binding.runner_url,
        boot.credentials.reviewer_token,
        str(boot.installation.organization_id),
    )
    reader = PublicAPI(binding.runner_url, boot.credentials.observer_token)
    observer = PublicAPI(
        binding.observer_url,
        private_environment(directory)["FLOWTEST_SELFTEST_OBSERVER_TOKEN"],
        api_prefix="",
    )
    batch, nonce = "worker-faults-" + secrets.token_hex(8), secrets.token_hex(24)
    assets: list[Assets] = []
    try:
        for golden in pack.scenarios:
            asset = await install(
                writer,
                project=project,
                service=boot.installation.fixture_service_id,
                fixture_url=binding.fixture_internal_url,
                batch=batch,
                scenario=golden.variant,
                directory=output / golden.variant,
            )
            await configure(
                observer,
                asset,
                digest,
                slow=golden.worker_killed,
                scope=FixtureBudgetScope(
                    parent_batch_key=batch,
                    nonce=nonce,
                    limit=100,
                    expires_at=deadline.timestamp(),
                ),
            )
            assets.append(asset)
        manifest = WorkerManifest(
            pack_digest=digest,
            profile=binding.runtime_profile,
            builds=Builds(
                runner=binding.candidate_image_digest,
                target=binding.candidate_image_digest,
                fixture=binding.fixture_image_digest.removeprefix("sha256:"),
                verifier=_verifier_digest(binding.runtime_profile),
            ),
            source_digest=binding.source_digest,
            batch_key=batch,
            nonce=nonce,
            created_at=started,
            deadline=deadline,
            disposal=RequiredDisposal(
                project_name=binding.project_name,
                target_container_id=binding.runner_container_id,
                target_volume=binding.runner_volume,
                target_image=binding.candidate_image_digest,
                binding_nonce=binding.nonce,
            ),
            worker_container_ids=tuple(row.container_id for row in control.workers.identities),
            assets=tuple(assets),
        )
        write_json(output / "manifest.json", manifest)
        observations: list[WorkerObservation] = []
        async with asyncio.timeout(max(1, (deadline - datetime.now(UTC)).total_seconds())):
            for golden, asset in zip(pack.scenarios, assets, strict=True):
                observed = await _one(golden, asset, manifest, writer, reader, observer, control)
                observations.append(observed)
                write_json(
                    output / "evidence.json",
                    WorkerEvidence(
                        manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
                        collected_at=datetime.now(UTC),
                        observations=tuple(observations),
                    ),
                )
        return observe(output)
    finally:
        control.workers.resume()
        await asyncio.gather(writer.close(), reader.close(), observer.close())


def finalize(directory: Path, output: Path) -> WorkerReport:
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    manifest = WorkerManifest.model_validate(read_json(output / "manifest.json"))
    evidence = WorkerEvidence.model_validate(read_json(output / "evidence.json"))
    if (
        read_json(directory / "ownership.json")
        != {"project_name": binding.project_name, "nonce": binding.nonce}
        or read_json(directory / "cleanup.json")
        != {"project_name": binding.project_name, "status": "completed"}
        or manifest.disposal.binding_nonce != binding.nonce
        or manifest.disposal.target_container_id != binding.runner_container_id
        or manifest.disposal.project_name != binding.project_name
        or manifest.builds.verifier != _verifier_digest(binding.runtime_profile)
    ):
        raise HarnessError("WORKER_FAULT_DISPOSAL_OWNERSHIP_CHANGED")
    _verify_removed(binding.project_name)
    receipt = TargetDisposalReceipt(
        **manifest.disposal.model_dump(),
        removed_at=datetime.now(UTC),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    if not (output / "evidence.pre-disposal.json").exists():
        write_json(output / "evidence.pre-disposal.json", evidence)
    write_json(output / "evidence.json", evidence.model_copy(update={"disposal": receipt}))
    return observe(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    report = (
        finalize(args.directory, args.output)
        if args.finalize_disposable
        else asyncio.run(run(args.directory, args.output))
    )
    print(
        json.dumps(
            {
                "exit_code": report.exit_code,
                "scenario_ids": report.scenario_ids,
                "reason_codes": report.reason_codes,
            }
        )
    )
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
