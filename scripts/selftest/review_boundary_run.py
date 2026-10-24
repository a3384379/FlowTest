"""Owned-stack review/Preview pack; final green needs exact disposal and independent O."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import ROOT, StackBinding, _verify_removed, private_environment
from scripts.selftest.mcp_governance_verify import Verdict, failure
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.quality_protocol import QualityProtocol, reserve_protocol_setup
from scripts.selftest.review_boundary_contracts import (
    ReviewEvidence,
    ReviewManifest,
    ReviewObservation,
    ReviewSource,
)
from scripts.selftest.review_boundary_http import ReviewAPI
from scripts.selftest.review_boundary_journey import ReviewJourney
from scripts.selftest.review_boundary_preview import preview_cancel
from scripts.selftest.review_boundary_setup import PreparedReview, prepare
from scripts.selftest.review_boundary_source import prepare_source
from scripts.selftest.review_boundary_verify import ReviewReport, verify, write_reports
from scripts.selftest.run import _configure, _protocol, _verifier_digest
from scripts.selftest.security_boundary_http import BoundaryAPI


def observe(public: Path) -> ReviewReport:
    manifest = ReviewManifest.model_validate(read_json(public / "manifest.json"))
    blocked = ReviewReport(
        batch_key=manifest.batch_key,
        exit_code=2,
        findings=(failure("REVIEW_OBSERVER_PROCESS_UNAVAILABLE", True),),
        scenarios=tuple(
            Verdict(scenario_id=r.scenario_id, verification_status="incomplete", findings=())
            for r in manifest.scenarios
        ),
    )
    destination = public / "independent-o"
    write_reports(blocked, None, destination)
    arguments = [
        sys.executable,
        "-m",
        "scripts.selftest.review_boundary_verify",
        "--manifest",
        str(public / "manifest.json"),
        "--evidence",
        str(public / "evidence.json"),
        "--authority",
        str(public / "authority.json"),
        "--output",
        str(destination),
    ]
    try:
        remaining = (manifest.expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise HarnessError("SELFTEST_REVIEW_OBSERVER_DEADLINE_EXCEEDED")
        child = subprocess.run(  # noqa: S603 -- fixed trusted O module and typed paths
            arguments,
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(ROOT),
                "PYTHONUNBUFFERED": "1",
            },
            capture_output=True,
            timeout=min(30, remaining),
            check=False,
        )
        report = ReviewReport.model_validate(read_json(destination / "verification.json"))
        if (report.batch_key, report.exit_code, tuple(r.scenario_id for r in report.scenarios)) != (
            manifest.batch_key,
            child.returncode,
            tuple(r.scenario_id for r in manifest.scenarios),
        ):
            raise HarnessError("SELFTEST_REVIEW_OBSERVER_RECEIPT_MISMATCH")
    except (OSError, ValueError, subprocess.SubprocessError, HarnessError):
        report = blocked
    write_reports(report, None, public)
    return report


def evidence_for(
    prepared: PreparedReview,
    sources: tuple[ReviewSource, ...],
    rows: tuple[ReviewObservation, ...],
    cleaned: bool,
) -> ReviewEvidence:
    admitted, rejected = prepared.budget.counts()
    tools, rejected_tools = prepared.budget.tool_counts()
    return ReviewEvidence(
        manifest_digest=canonical_digest(prepared.manifest.model_dump(mode="json")),
        authority_digest=canonical_digest(prepared.authority.model_dump(mode="json")),
        stack=StackSnapshot.model_validate(prepared.binding.model_dump(mode="json")),
        sources=sources,
        observations=rows,
        http_admitted=admitted,
        http_rejected=rejected,
        tools_admitted=tools,
        tools_rejected=rejected_tools,
        protocol_cleanup_complete=cleaned,
        collected_at=datetime.now(UTC),
    )


async def execute(directory: Path, output: Path) -> ReviewReport:
    prepared = await prepare(directory, output)
    return await collect_prepared(prepared, directory, output)


async def collect_prepared(prepared: PreparedReview, directory: Path, output: Path) -> ReviewReport:
    manifest, binding, budget = prepared.manifest, prepared.binding, prepared.budget
    private = private_environment(directory)
    org = str(prepared.issued.fixture.identity.organization_a)
    reviewer = ReviewAPI(
        binding.runner_url, budget, manifest.expires_at, prepared.issued.reviewer_token, org
    )
    reader = BoundaryAPI(binding.runner_url, budget, manifest.expires_at, prepared.ci_token)
    inventory = ProbeReader(
        binding.runner_url,
        prepared.observer.token(),
        manifest.nonce,
        prepared.authority,
        budget.reserve,
    )
    observer = PublicAPI(
        binding.observer_url, private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"], api_prefix=""
    )
    sources: tuple[ReviewSource, ...] = ()
    rows: tuple[ReviewObservation, ...] = ()
    cleaned = False
    try:
        remaining = (manifest.expires_at - datetime.now(UTC)).total_seconds()
        async with asyncio.timeout(max(0, remaining)):
            for transport in ("stdio", "streamable-http"):
                reserve_protocol_setup(budget)
                # Two H fixture configuration calls and exactly one native
                # cleanup HTTP request, reserved before any Preview can execute.
                if not all(budget.reserve() for _ in range(3)):
                    raise HarnessError("SELFTEST_REVIEW_FIXTURE_BUDGET_EXHAUSTED")
                batch = manifest.batch_key + "-" + transport
                epoch = await _configure(
                    observer,
                    batch,
                    "ST-MCP-022-" + transport,
                    manifest.nonce,
                    binding.fixture_image_digest.removeprefix("sha256:"),
                )
                async with _protocol(
                    binding,
                    transport,
                    prepared.issued.writer_token,
                    batch,
                    output / "private/sdk" / transport,
                    stack_directory=directory,
                    deadline=manifest.expires_at,
                ) as raw:
                    client = QualityProtocol(raw, budget, manifest.expires_at)
                    source = await prepare_source(
                        client, manifest, output / "private/sources" / transport, epoch
                    )
                    sources += (source,)
                    journey = ReviewJourney(
                        manifest,
                        source,
                        client,
                        reviewer,
                        inventory,
                        reader,
                        output / "private/scenarios",
                    )
                    for scenario in manifest.scenarios:
                        if scenario.transport == transport:
                            row = (
                                await preview_cancel(journey, scenario, observer)
                                if scenario.action == "preview_cancel"
                                else await journey.run_row(scenario)
                            )
                            rows += (row,)
                            write_json(
                                output / "private/partial.json",
                                {"observations": [r.model_dump(mode="json") for r in rows]},
                            )
            cleaned = True
    finally:
        await reviewer.close()
        await reader.close()
        await inventory.close()
        await observer.close()
        evidence = evidence_for(prepared, sources, rows, cleaned)
        report = verify(manifest, evidence, prepared.authority)
        write_reports(report, evidence, output / "public")
    return observe(output / "public")


def finalize(directory: Path, output: Path) -> ReviewReport:
    public = output / "public"
    manifest = ReviewManifest.model_validate(read_json(public / "manifest.json"))
    authority = ProbeAuthority.model_validate(read_json(public / "authority.json"))
    evidence = ReviewEvidence.model_validate(read_json(public / "evidence.json"))
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    if evidence.stack.model_dump(mode="json") != binding.model_dump(
        mode="json"
    ) or authority.builds.verifier != _verifier_digest(binding.runtime_profile):
        raise HarnessError("SELFTEST_REVIEW_DISPOSAL_STACK_OR_VERIFIER_CHANGED")
    if read_json(directory / "ownership.json") != {
        "project_name": binding.project_name,
        "nonce": binding.nonce,
    } or read_json(directory / "cleanup.json") != {
        "project_name": binding.project_name,
        "status": "completed",
    }:
        raise HarnessError("SELFTEST_REVIEW_DISPOSAL_OWNERSHIP_MISMATCH")
    _verify_removed(binding.project_name)
    if evidence.disposal is None:
        write_json(public / "evidence.pre-disposal.json", evidence)
        receipt = DisposalReceipt(
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
        evidence = evidence.model_copy(update={"disposal": receipt})
    report = verify(manifest, evidence, authority)
    write_reports(report, evidence, public)
    return observe(public)


def main() -> int:
    parser = argparse.ArgumentParser(description="真实SDK提案审核恢复与受限Preview自测; 不调用模型")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    report = (
        finalize(args.directory, args.output)
        if args.finalize_disposable
        else asyncio.run(execute(args.directory, args.output))
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
