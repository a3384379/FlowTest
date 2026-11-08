"""Finite deployed SDK-fault pack, on a verified already initialized owned stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import StackBinding, _verify_removed
from scripts.selftest.mcp_fault_contracts import FaultEvidence, FaultManifest
from scripts.selftest.mcp_fault_session import observe
from scripts.selftest.mcp_fault_setup import PreparedFault, prepare
from scripts.selftest.mcp_fault_verify import FaultReport, verify, write_reports
from scripts.selftest.mcp_governance_verify import failure
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot
from scripts.selftest.mcp_probe_reader import ProbeReader


async def execute(prepared: PreparedFault) -> FaultEvidence:
    manifest = prepared.manifest
    reader = ProbeReader(
        prepared.binding.runner_url,
        prepared.observer.token(),
        manifest.nonce,
        prepared.authority,
        prepared.budget.reserve,
    )
    rows = []
    try:
        async with asyncio.timeout(
            max(0, (manifest.expires_at - datetime.now(UTC)).total_seconds())
        ):
            for scenario in manifest.scenarios:
                row = await observe(prepared, reader, scenario)
                rows.append(row)
                write_json(
                    prepared.state / "public/partial.json",
                    {"scenarios": [item.model_dump(mode="json") for item in rows]},
                )
    finally:
        await reader.close()
    admitted, rejected = prepared.budget.counts()
    tools, tools_rejected = prepared.budget.tool_counts()
    return FaultEvidence(
        batch_key=manifest.batch_key,
        nonce=manifest.nonce,
        pack_digest=manifest.pack_digest,
        source_digest=manifest.source_digest,
        manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
        authority_digest=canonical_digest(prepared.authority.model_dump(mode="json")),
        stack=StackSnapshot.model_validate(prepared.binding.model_dump(mode="json")),
        inactive_fixture=prepared.inactive_fixture,
        scenarios=tuple(rows),
        http_admitted=admitted,
        http_rejected=rejected,
        tools_admitted=tools,
        tools_rejected=tools_rejected,
        process_cleanup_complete=all(row.dispatch.process_cleanup_complete for row in rows),
        disposal_receipt=None,
        collected_at=datetime.now(UTC),
    )


async def run(directory: Path, output: Path) -> int:
    if output.exists():
        raise HarnessError("SELFTEST_FAULT_OUTPUT_ALREADY_EXISTS")
    evidence = None
    try:
        if version("mcp") != "2.2.0":
            raise HarnessError("SELFTEST_FAULT_LOCKED_SDK_MISMATCH")
        prepared = await prepare(directory, output)
        evidence = await execute(prepared)
        write_json(output / "public/evidence.json", evidence)
        report = verify(prepared.manifest, evidence, prepared.authority)
    except (
        HarnessError,
        ValidationError,
        OSError,
        ValueError,
        TimeoutError,
        ExceptionGroup,
    ) as error:
        code = str(error) if isinstance(error, HarnessError) else "SELFTEST_FAULT_DRIVER_INCOMPLETE"
        if not code.startswith("SELFTEST_") or len(code) > 160:
            code = "SELFTEST_FAULT_DRIVER_INCOMPLETE"
        report = FaultReport(
            batch_key=output.name, exit_code=2, findings=(failure(code, True),), scenarios=()
        )
    write_reports(report, evidence, output / "public")
    return report.exit_code


def finalize(directory: Path, output: Path) -> int:
    evidence = FaultEvidence.model_validate(read_json(output / "public/evidence.json"))
    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    if stack.model_dump(mode="json", exclude={"runner_container_id"}) != evidence.stack.model_dump(
        mode="json", exclude={"runner_container_id"}
    ):
        raise HarnessError("SELFTEST_FAULT_FINALIZER_STACK_MISMATCH")
    if read_json(directory / "ownership.json") != {
        "project_name": stack.project_name,
        "nonce": stack.nonce,
    } or read_json(directory / "cleanup.json") != {
        "project_name": stack.project_name,
        "status": "completed",
    }:
        raise HarnessError("SELFTEST_FAULT_FINALIZER_OWNERSHIP_MISMATCH")
    _verify_removed(stack.project_name)
    receipt = evidence.disposal_receipt or DisposalReceipt(
        project_name=stack.project_name,
        binding_nonce=stack.nonce,
        runner_volume=stack.runner_volume,
        target_volume=stack.target_volume,
        candidate_image_digest=stack.candidate_image_digest,
        removed_at=datetime.now(UTC),
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    before = output / "public/evidence.pre-disposal.json"
    if not before.exists():
        write_json(before, evidence)
    evidence = evidence.model_copy(update={"disposal_receipt": receipt})
    manifest = FaultManifest.model_validate(read_json(output / "public/manifest.json"))
    authority = ProbeAuthority.model_validate(read_json(output / "public/authority.json"))
    report = verify(manifest, evidence, authority)
    write_json(output / "public/evidence.json", evidence)
    write_reports(report, evidence, output / "public")
    return report.exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="真实 SDK 传输故障: 已拥有隔离栈、零模型、禁止重放未知变更"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    try:
        code = (
            finalize(args.directory, args.output)
            if args.finalize_disposable
            else asyncio.run(run(args.directory, args.output))
        )
    except (HarnessError, OSError, ValidationError, ValueError):
        code = 2
    print(
        json.dumps(
            {
                "output": str(args.output / "public"),
                "exit_code": code,
                "claim": "transport_fault_negative_only",
            }
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
