"""Owned deployment entrypoint; native source and disposal identities stay exact."""

import argparse
import asyncio
import os
import secrets
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args
from uuid import UUID, uuid4

from scripts.selftest.bootstrap import bootstrap
from scripts.selftest.contract_delta_budget import DeltaAPI, DeltaBudget
from scripts.selftest.contracts import (
    Builds,
    RequiredDisposal,
    TargetDisposalReceipt,
    canonical_digest,
)
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import ROOT, StackBinding, _verify_removed, verify_binding
from scripts.selftest.native_control import NativeControlJourney
from scripts.selftest.native_control_contracts import (
    ControlVariant,
    NativeControlCheck,
    NativeControlEvidence,
    NativeControlManifest,
    NativeControlReport,
)
from scripts.selftest.native_control_verify import load_pack, verify, write_reports
from scripts.selftest.run import _protocol, _verifier_digest
from scripts.selftest.run_contract_delta import _project_installation


def pack_path() -> Path:
    return ROOT / "selftest/packs/native-control-mcp-v1/pack.json"


async def run(directory: Path, output: Path, transport: str = "stdio") -> int:
    if output.exists():
        raise HarnessError("NATIVE_CONTROL_OUTPUT_EXISTS_NO_REPLAY")
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    boot = await bootstrap(binding, directory)
    output.mkdir(parents=True, mode=0o700)
    now, key = datetime.now(UTC), "native-control-" + secrets.token_hex(8)
    deadline = now + timedelta(seconds=600)
    budget = DeltaBudget(output, deadline)
    admin = PublicAPI(
        binding.runner_url, boot.credentials.admin_token, str(boot.installation.organization_id)
    )
    try:
        installation, read_token = await _project_installation(
            DeltaAPI(admin, budget), boot.installation, binding, output
        )
        accounts = objects_value(
            await DeltaAPI(admin, budget).request(
                "GET",
                f"/organizations/{installation.organization_id}/service-accounts",
            )
        )
        selected = [item for item in accounts if item.get("id") == str(installation.mcp_account_id)]
        if len(selected) != 1:
            raise HarnessError("NATIVE_CONTROL_EXACT_MACHINE_ACCOUNT_MISSING")
        account = selected[0]
    finally:
        await admin.close()
    pack = load_pack(pack_path())
    frozen = NativeControlManifest(
        batch_key=key,
        nonce=secrets.token_hex(16),
        pack_digest=canonical_digest(pack.model_dump(mode="json")),
        binding_fingerprint=canonical_digest(binding.model_dump(mode="json")),
        binding_nonce=binding.nonce,
        builds=Builds(
            runner=binding.candidate_image_digest,
            target=binding.candidate_image_digest,
            fixture=binding.fixture_image_digest.removeprefix("sha256:"),
            verifier=_verifier_digest(binding.runtime_profile),
        ),
        project_id=installation.project_id,
        environment_id=installation.fixture_environment_id,
        reviewer_id=installation.reviewer_id,
        mcp_account_id=installation.mcp_account_id,
        mcp_actor_id=UUID(text_value(account["created_by_id"])),
        created_at=now,
        expires_at=deadline,
        required_disposal=RequiredDisposal(
            project_name=binding.project_name,
            target_container_id=binding.runner_container_id,
            target_volume=binding.runner_volume,
            target_image=binding.candidate_image_digest,
            binding_nonce=binding.nonce,
        ),
    )
    write_json(output / "selection-before-protocol.json", frozen)
    pending = NativeControlEvidence(
        manifest_digest=canonical_digest(frozen.model_dump(mode="json")),
        collected_at=datetime.now(UTC),
    )
    write_reports(verify(frozen, pack, pending), pending, output)
    apis = (
        PublicAPI(
            binding.runner_url, boot.credentials.reviewer_token, str(installation.organization_id)
        ),
        PublicAPI(binding.runner_url, read_token),
        PublicAPI(
            binding.runner_url,
            boot.credentials.capture_viewer_token,
            str(installation.organization_id),
        ),
    )
    try:
        async with _protocol(
            binding,
            transport,
            boot.credentials.mcp_token,
            key,
            output / "protocol",
            stack_directory=directory,
            deadline=deadline,
        ) as client:
            await NativeControlJourney(frozen, pack, client, *apis, output, budget=budget).run()
            return observe(output)
    finally:
        for api in apis:
            await api.close()


def finalize(directory: Path, output: Path) -> int:
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    frozen = NativeControlManifest.model_validate(read_json(output / "manifest.json"))
    evidence = NativeControlEvidence.model_validate(read_json(output / "evidence.json"))
    ownership, cleanup = (
        read_json(directory / "ownership.json"),
        read_json(directory / "cleanup.json"),
    )
    if (
        ownership.get("nonce"),
        ownership.get("project_name"),
        cleanup.get("status"),
        cleanup.get("project_name"),
    ) != (frozen.binding_nonce, binding.project_name, "completed", binding.project_name):
        raise HarnessError("NATIVE_CONTROL_OWNED_DISPOSAL_NOT_CONFIRMED")
    if frozen.binding_fingerprint != canonical_digest(binding.model_dump(mode="json")):
        raise HarnessError("NATIVE_CONTROL_DISPOSAL_BINDING_DRIFT")
    if frozen.builds.verifier != _verifier_digest(binding.runtime_profile):
        raise HarnessError("NATIVE_CONTROL_VERIFIER_SOURCE_CHANGED")
    expected = RequiredDisposal(
        project_name=binding.project_name,
        target_container_id=binding.runner_container_id,
        target_volume=binding.runner_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
    )
    if expected != frozen.required_disposal:
        raise HarnessError("NATIVE_CONTROL_DISPOSAL_REQUIRED_IDENTITY_CHANGED")
    _verify_removed(binding.project_name)
    receipt = evidence.disposal or TargetDisposalReceipt(
        **expected.model_dump(),
        removed_at=datetime.now(UTC),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    before = output / "evidence.pre-disposal.json"
    if not before.exists():
        write_json(before, evidence)
    evidence = evidence.model_copy(update={"disposal": receipt})
    write_json(output / "evidence.json", evidence)
    return observe(output)


def observe(output: Path) -> int:
    frozen = NativeControlManifest.model_validate(read_json(output / "manifest.json"))
    evidence = NativeControlEvidence.model_validate(read_json(output / "evidence.json"))
    destination = output / "observer" / uuid4().hex
    command = [
        sys.executable,
        "-m",
        "scripts.selftest.native_control_verify",
        "--manifest",
        str(output / "manifest.json"),
        "--evidence",
        str(output / "evidence.json"),
        "--pack",
        str(pack_path()),
        "--output",
        str(destination),
    ]
    try:
        result = subprocess.run(  # noqa: S603 -- fixed trusted module and typed paths
            command,
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(ROOT),
                "PYTHONUNBUFFERED": "1",
            },
            capture_output=True,
            timeout=30,
            check=False,
        )
        report = NativeControlReport.model_validate(read_json(destination / "verification.json"))
        expected = (
            evidence.manifest_digest,
            frozen.pack_digest,
            frozen.batch_key,
            get_args(ControlVariant),
        )
        if (
            result.returncode != report.exit_code
            or (
                report.manifest_digest,
                report.pack_digest,
                report.batch_key,
                tuple(row.variant for row in report.scenarios),
            )
            != expected
        ):
            raise HarnessError("NATIVE_CONTROL_OBSERVER_RECEIPT_CHANGED")
    except (OSError, ValueError, subprocess.SubprocessError, HarnessError):
        report = NativeControlReport(
            batch_key=frozen.batch_key,
            pack_digest=frozen.pack_digest,
            manifest_digest=evidence.manifest_digest,
            verdict="blocked",
            exit_code=2,
            findings=("NATIVE_CONTROL_OBSERVER_PROCESS_FAILED",),
            scenarios=tuple(
                NativeControlCheck(
                    variant=variant,
                    status="incomplete",
                    findings=("NATIVE_CONTROL_OBSERVER_PROCESS_FAILED",),
                )
                for variant in get_args(ControlVariant)
            ),
        )
        write_reports(report, evidence, output)
        return 2
    for name in ("verification.json", "verification.junit.xml", "execution.junit.xml"):
        shutil.copyfile(destination / name, output / name)
    return report.exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="原生4.0 MCP提案闭环和普通FlowSpec拒绝边界")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            finalize(args.directory, args.output)
            if args.finalize_disposable
            else asyncio.run(run(args.directory, args.output, args.transport))
        )
    except Exception as error:
        args.output.mkdir(parents=True, exist_ok=True)
        failure = args.output / "failure.json"
        if failure.exists():
            failure = args.output / ("failure-" + uuid4().hex + ".json")
        write_json(
            failure,
            {
                "failure_codes": list(failure_codes(error)),
                "outcome": "incomplete",
                "mutation_replay_allowed": False,
            },
        )
        raise SystemExit(2) from None
    raise SystemExit(result)


if __name__ == "__main__":
    main()
