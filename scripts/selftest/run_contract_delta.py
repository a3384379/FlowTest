"""Run only a verified owned deployment; preserve incomplete disposal until exact stop."""

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

from scripts.selftest.bootstrap import Installation, bootstrap
from scripts.selftest.contract_delta import DeltaJourney
from scripts.selftest.contract_delta_budget import DeltaAPI, DeltaBudget
from scripts.selftest.contract_delta_contracts import (
    DeltaCheck,
    DeltaEvidence,
    DeltaManifest,
    DeltaReport,
    Variant,
)
from scripts.selftest.contract_delta_verify import load_pack, verify, write_reports
from scripts.selftest.contracts import (
    Builds,
    FixtureBudgetScope,
    RequiredDisposal,
    TargetDisposalReceipt,
    canonical_digest,
)
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, PublicAPI, read_json, text_value, write_json
from scripts.selftest.local_stack import (
    ROOT,
    StackBinding,
    _verify_removed,
    private_environment,
    verify_binding,
)
from scripts.selftest.run import _protocol, _verifier_digest


def pack_path() -> Path:
    return ROOT / "selftest/packs/contract-delta-v1/pack.json"


async def _project_installation(
    api: DeltaAPI, original: Installation, binding: StackBinding, output: Path
) -> tuple[Installation, str]:
    write_json(
        output / "project-intent.json", {"status": "creating", "binding_nonce": binding.nonce}
    )
    created = await api.object(
        "POST",
        "/projects",
        {"name": output.name + ":delta-fixture", "organization_id": str(original.organization_id)},
    )
    project = text_value(created["id"])
    await api.object(
        "PUT",
        f"/projects/{project}/security-policy",
        {
            "enabled": True,
            "allowed_hosts": ["mock-target", "target"],
            "allowed_private_cidrs": [binding.private_subnet],
        },
    )
    write_json(
        output / "project-receipt.json",
        {
            "status": "created",
            "project_id": project,
            "binding_nonce": binding.nonce,
            "organization_id": str(original.organization_id),
        },
    )
    await api.object(
        "PUT",
        f"/projects/{project}/members/{original.reviewer_id}",
        {"user_id": str(original.reviewer_id), "role": "owner"},
    )
    if original.capture_viewer_id is None:
        raise HarnessError("DELTA_SCOPED_VIEWER_MISSING")
    await api.object(
        "PUT",
        f"/projects/{project}/members/{original.capture_viewer_id}",
        {"user_id": str(original.capture_viewer_id), "role": "viewer"},
    )
    environment, service = await _binding(api, project, "mock", binding.fixture_internal_url)
    target_environment, target_service = await _binding(
        api, project, "target", binding.target_internal_url
    )
    issued = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {
            "name": "delta本项目独立执行读取",
            "scopes": ["read:execution"],
            "expires_at": api.budget.deadline.isoformat(),
        },
    )
    installation = original.model_copy(
        update={
            "project_id": UUID(project),
            "fixture_environment_id": UUID(environment),
            "fixture_service_id": UUID(service),
            "target_environment_id": UUID(target_environment),
            "target_service_id": UUID(target_service),
        }
    )
    write_json(output / "installation.json", installation)
    return installation, text_value(issued["token"])


async def _binding(api: PublicAPI, project: str, key: str, url: str) -> tuple[str, str]:
    environment = await api.object(
        "POST",
        f"/projects/{project}/environments",
        {"name": "delta_" + key, "base_url": url, "classification": "test"},
    )
    service = await api.object(
        "POST",
        f"/projects/{project}/services",
        {"name": "delta_" + key, "service_key": "delta_" + key},
    )
    identifier, service_id = text_value(environment["id"]), text_value(service["id"])
    await api.object(
        "POST",
        f"/projects/{project}/environments/{identifier}/service-endpoints",
        {"service_id": service_id, "variant": "default", "base_url": url},
    )
    await api.object(
        "PATCH",
        f"/projects/{project}/environments/{identifier}",
        {"default_service_id": service_id},
    )
    return identifier, service_id


async def run(directory: Path, output: Path, transport: str = "stdio") -> int:
    if output.exists():
        raise HarnessError("DELTA_OUTPUT_ALREADY_EXISTS_NO_MUTATION_REPLAY")
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    boot = await bootstrap(binding, directory)
    output.mkdir(parents=True, mode=0o700)
    now, key, nonce = datetime.now(UTC), "delta-" + secrets.token_hex(10), secrets.token_hex(16)
    deadline = now + timedelta(seconds=600)
    budget = DeltaBudget(output, deadline)
    admin = PublicAPI(
        binding.runner_url, boot.credentials.admin_token, str(boot.installation.organization_id)
    )
    try:
        installation, reader_token = await _project_installation(
            DeltaAPI(admin, budget), boot.installation, binding, output
        )
    finally:
        await admin.close()
    pack = load_pack(pack_path())
    frozen = DeltaManifest(
        pack_digest=canonical_digest(pack.model_dump(mode="json")),
        binding_fingerprint=canonical_digest(binding.model_dump(mode="json")),
        binding_nonce=binding.nonce,
        batch_key=key,
        nonce=nonce,
        builds=Builds(
            runner=binding.candidate_image_digest,
            target=binding.candidate_image_digest,
            fixture=binding.fixture_image_digest.removeprefix("sha256:"),
            verifier=_verifier_digest(binding.runtime_profile),
        ),
        installation=installation,
        created_at=now,
        expires_at=deadline,
        scope=FixtureBudgetScope(
            parent_batch_key=key, nonce=nonce, limit=500, expires_at=deadline.timestamp()
        ),
        required_disposal=RequiredDisposal(
            project_name=binding.project_name,
            target_container_id=binding.runner_container_id,
            target_volume=binding.runner_volume,
            target_image=binding.candidate_image_digest,
            binding_nonce=binding.nonce,
        ),
    )
    write_json(output / "selection-before-protocol.json", frozen)
    pending = DeltaEvidence(
        manifest_digest=canonical_digest(frozen.model_dump(mode="json")),
        collected_at=datetime.now(UTC),
    )
    write_reports(verify(frozen, pack, pending), pending, output)
    apis = (
        PublicAPI(
            binding.runner_url,
            boot.credentials.reviewer_token,
            str(boot.installation.organization_id),
        ),
        PublicAPI(
            binding.runner_url, boot.credentials.admin_token, str(boot.installation.organization_id)
        ),
        PublicAPI(binding.runner_url, reader_token),
        PublicAPI(
            binding.runner_url,
            boot.credentials.capture_viewer_token,
            str(boot.installation.organization_id),
        ),
        PublicAPI(
            binding.observer_url,
            private_environment(directory)["FLOWTEST_SELFTEST_OBSERVER_TOKEN"],
            api_prefix="",
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
            await DeltaJourney(frozen, pack, client, *apis, output, budget=budget).run()
            return observe(output)
    finally:
        for api in apis:
            await api.close()


def finalize(directory: Path, output: Path) -> int:
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    frozen = DeltaManifest.model_validate(read_json(output / "manifest.json"))
    evidence = DeltaEvidence.model_validate(read_json(output / "evidence.json"))
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
        raise HarnessError("DELTA_OWNED_DISPOSAL_NOT_CONFIRMED")
    if frozen.binding_fingerprint != canonical_digest(binding.model_dump(mode="json")):
        raise HarnessError("DELTA_DISPOSAL_BINDING_DRIFT")
    if frozen.builds.verifier != _verifier_digest(binding.runtime_profile):
        raise HarnessError("DELTA_VERIFIER_SOURCE_CHANGED")
    expected = RequiredDisposal(
        project_name=binding.project_name,
        target_container_id=binding.runner_container_id,
        target_volume=binding.runner_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
    )
    if frozen.required_disposal != expected:
        raise HarnessError("DELTA_DISPOSAL_REQUIRED_IDENTITY_MISMATCH")
    _verify_removed(binding.project_name)
    receipt = evidence.disposal or TargetDisposalReceipt(
        **frozen.required_disposal.model_dump(),
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
    """O receives synthetic frozen files and no H, A, B, M or provider credential."""
    frozen = DeltaManifest.model_validate(read_json(output / "manifest.json"))
    evidence = DeltaEvidence.model_validate(read_json(output / "evidence.json"))
    destination = output / "observer" / uuid4().hex
    command = [
        sys.executable,
        "-m",
        "scripts.selftest.contract_delta_verify",
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
        result = subprocess.run(  # noqa: S603 -- fixed trusted module and typed local paths
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
        report = DeltaReport.model_validate(read_json(destination / "verification.json"))
        if result.returncode != report.exit_code or (
            report.manifest_digest,
            report.pack_digest,
            report.batch_key,
            tuple(row.variant for row in report.scenarios),
        ) != (evidence.manifest_digest, frozen.pack_digest, frozen.batch_key, get_args(Variant)):
            raise HarnessError("DELTA_OBSERVER_RECEIPT_MISMATCH")
    except (OSError, ValueError, subprocess.SubprocessError, HarnessError):
        report = DeltaReport(
            pack_digest=frozen.pack_digest,
            manifest_digest=evidence.manifest_digest,
            batch_key=frozen.batch_key,
            verdict="blocked",
            exit_code=2,
            findings=("DELTA_OBSERVER_PROCESS_FAILED",),
            scenarios=tuple(
                DeltaCheck(
                    variant=variant,
                    status="incomplete",
                    findings=("DELTA_OBSERVER_PROCESS_FAILED",),
                )
                for variant in get_args(Variant)
            ),
        )
        write_reports(report, evidence, output)
        return 2
    for name in ("verification.json", "verification.junit.xml", "execution.junit.xml"):
        shutil.copyfile(destination / name, output / name)
    return report.exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="真实契约变更与发布槽位自测")
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
