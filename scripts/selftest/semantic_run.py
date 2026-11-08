"""Owned-stack semantic review entry; final green requires observed full disposal."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.selftest.bootstrap import bootstrap
from scripts.selftest.contracts import Builds
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import (
    StackBinding,
    _verify_removed,
    private_environment,
    verify_binding,
)
from scripts.selftest.mcp_probe_evidence import DisposalReceipt
from scripts.selftest.run import _protocol, _verifier_digest
from scripts.selftest.semantic_contracts import SemanticEvidence, SemanticManifest, SemanticReport
from scripts.selftest.semantic_pack import execute_semantic_pack
from scripts.selftest.semantic_verify import verify_semantic, write_semantic_reports


def finalize(directory: Path, output: Path) -> SemanticReport:
    manifest = SemanticManifest.model_validate(read_json(output / "manifest.json"))
    evidence = SemanticEvidence.model_validate(read_json(output / "evidence.json"))
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    if manifest.stack.model_dump(mode="json") != binding.model_dump(mode="json"):
        raise HarnessError("SELFTEST_SEMANTIC_DISPOSAL_STACK_CHANGED")
    if read_json(directory / "ownership.json") != {
        "project_name": binding.project_name,
        "nonce": binding.nonce,
    } or read_json(directory / "cleanup.json") != {
        "project_name": binding.project_name,
        "status": "completed",
    }:
        raise HarnessError("SELFTEST_SEMANTIC_DISPOSAL_OWNERSHIP_MISMATCH")
    if manifest.builds.verifier != _verifier_digest(binding.runtime_profile):
        raise HarnessError("SELFTEST_SEMANTIC_VERIFIER_SOURCE_CHANGED")
    _verify_removed(binding.project_name)
    if evidence.disposal is None:
        original = output / "evidence.pre-disposal.json"
        if not original.exists():
            write_json(original, evidence)
        evidence = evidence.model_copy(
            update={
                "disposal": DisposalReceipt(
                    project_name=binding.project_name,
                    binding_nonce=binding.nonce,
                    runner_volume=binding.runner_volume,
                    target_volume=binding.target_volume,
                    candidate_image_digest=binding.candidate_image_digest,
                    removed_at=datetime.now(UTC),
                    containers_absent=True,
                    volumes_absent=True,
                    networks_absent=True,
                )
            }
        )
        write_json(output / "evidence.json", evidence)
    report = verify_semantic(manifest, evidence)
    write_semantic_reports(report, evidence, output)
    return report


async def execute(directory: Path, output: Path, transport: str) -> SemanticReport:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    boot = await bootstrap(binding, directory)
    private = private_environment(directory)
    started = datetime.now(UTC)
    deadline = started + timedelta(seconds=600)
    batch, nonce = "semantic-" + secrets.token_hex(10), secrets.token_hex(24)
    project = str(boot.installation.organization_id)
    reviewer = PublicAPI(binding.runner_url, boot.credentials.reviewer_token, project)
    reader = PublicAPI(binding.runner_url, boot.credentials.observer_token)
    observer = PublicAPI(
        binding.observer_url, private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"], api_prefix=""
    )
    try:
        async with _protocol(
            binding,
            transport,
            boot.credentials.mcp_token,
            batch,
            output / "sdk",
            stack_directory=directory,
            deadline=deadline,
        ) as client:
            _, _, report = await execute_semantic_pack(
                client,
                reviewer,
                reader,
                observer,
                installation=boot.installation,
                binding=binding,
                batch_key=batch,
                nonce=nonce,
                builds=Builds(
                    runner=binding.candidate_image_digest,
                    target=binding.candidate_image_digest,
                    fixture=binding.fixture_image_digest.removeprefix("sha256:"),
                    verifier=_verifier_digest(binding.runtime_profile),
                ),
                output_dir=output,
                deadline=deadline,
            )
        return report
    finally:
        await reviewer.close()
        await reader.close()
        await observer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="真实SDK语义审核负向自测; 不调用模型")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    report = (
        finalize(args.directory, args.output)
        if args.finalize_disposable
        else asyncio.run(execute(args.directory, args.output, args.transport))
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
