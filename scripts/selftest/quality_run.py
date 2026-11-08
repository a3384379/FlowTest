"""Finite SDK quality journey; only scoped metadata reaches the independent oracle."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, integer_value, objects_value, read_json, write_json
from scripts.selftest.local_stack import StackBinding, _verify_removed
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_evidence import DisposalReceipt, StackSnapshot
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.quality_boundaries import boundary_arguments, boundary_requests
from scripts.selftest.quality_case_contracts import QualityVariant
from scripts.selftest.quality_contracts import (
    CredentialEndpoint,
    CredentialProjection,
    QualityEvidence,
    QualityManifest,
    QualityObservation,
    QualityScenario,
)
from scripts.selftest.quality_observer import observe
from scripts.selftest.quality_protocol import QualityProtocol, reserve_protocol_setup
from scripts.selftest.quality_scenarios import generate_quality_case
from scripts.selftest.quality_sessions import open_protocols
from scripts.selftest.quality_setup import PreparedQuality, prepare
from scripts.selftest.quality_verify import QualityReport, verify, write_reports
from scripts.selftest.run import _verifier_digest


async def collect_row(
    manifest: QualityManifest,
    scenario: QualityScenario,
    writer: QualityProtocol,
    reader: QualityProtocol,
    observer: ProbeReader,
    sentinel: str,
    output: Path,
) -> QualityObservation:
    started = datetime.now(UTC)
    before = await observer.snapshot()
    protocol = reader if scenario.action == "scope" else writer
    offset = len(protocol.receipts)
    generated = result = credential = None
    attack = {
        "prompt_injection": "quality-attack-001",
        "scope": "quality-attack-002",
        "target": "quality-attack-003",
    }.get(scenario.action)
    if scenario.expected_readiness is not None:
        variant = (
            "positive_control"
            if scenario.action == "prompt_injection"
            else cast(QualityVariant, scenario.action)
        )
        generated = await generate_quality_case(
            protocol,
            manifest.scope,
            variant,
            output,
            attack_material=scenario.action == "prompt_injection",
        )
    else:
        name, arguments = boundary_arguments(manifest.scope, protocol.batch_key, scenario.action)
        if scenario.action == "credential_ref":
            credential = await _credential(manifest, scenario, protocol, sentinel)
        else:
            result = await protocol.boundary_call(name, arguments, scenario_id=scenario.scenario_id)
    after = await observer.snapshot()
    observed = QualityObservation(
        scenario_id=scenario.scenario_id,
        started_at=started,
        completed_at=datetime.now(UTC),
        before=before,
        after=after,
        generated=generated,
        result=result,
        credential=credential,
        attack_id=attack,
        calls=tuple(protocol.receipts[offset:]),
    )
    write_json(output / "observation.json", observed)
    return observed


async def _credential(
    manifest: QualityManifest, scenario: QualityScenario, protocol: QualityProtocol, sentinel: str
) -> CredentialProjection:
    returned = []
    digests = []
    for name, arguments in boundary_requests(manifest.scope, protocol.batch_key, scenario.action):
        returned.append(
            await protocol.call(
                name, arguments, scenario_id=scenario.scenario_id, phase="credential_reference"
            )
        )
        digests.append(protocol.receipts[-1].result_digest)
    readiness, metadata = returned
    selected = [
        item
        for item in objects_value(metadata["endpoints"])
        if item["service_id"] == str(manifest.scope.fixture_service_id)
    ]
    if len(selected) != 1:
        raise HarnessError("SELFTEST_QUALITY_CREDENTIAL_ENDPOINT_MISMATCH")
    endpoint = CredentialEndpoint.model_validate(
        {key: selected[0][key] for key in CredentialEndpoint.model_fields}
    )
    checks = [
        check
        for check in objects_value(readiness["checks"])
        if check["name"] == "business_test_credentials"
    ]
    return CredentialProjection(
        reference_count=integer_value(selected[0]["secret_ref_count"]),
        verified=len(checks) == 1 and checks[0]["state"] == "ready",
        sentinel_leaked=sentinel in json.dumps(returned, ensure_ascii=False),
        result_digest=digests[0],
        metadata_digest=digests[1],
        endpoint=endpoint,
    )


async def collect_transport(
    manifest: QualityManifest,
    transport: str,
    writer: ProtocolClient,
    reader: ProtocolClient,
    observer: ProbeReader,
    budget: ProtocolHttpBudget,
    sentinel: str,
    output: Path,
) -> tuple[QualityObservation, ...]:
    wrapped_writer = QualityProtocol(writer, budget, manifest.expires_at)
    wrapped_reader = QualityProtocol(reader, budget, manifest.expires_at)
    rows = []
    for scenario in manifest.scenarios:
        if scenario.transport == transport:
            rows.append(
                await collect_row(
                    manifest,
                    scenario,
                    wrapped_writer,
                    wrapped_reader,
                    observer,
                    sentinel,
                    output / scenario.scenario_id,
                )
            )
    return tuple(rows)


def evidence_for(
    prepared: PreparedQuality, rows: tuple[QualityObservation, ...], cleanup: bool
) -> QualityEvidence:
    admitted, rejected = prepared.budget.counts()
    tools, denied_tools = prepared.budget.tool_counts()
    return QualityEvidence(
        manifest_digest=canonical_digest(prepared.manifest.model_dump(mode="json")),
        authority_digest=canonical_digest(prepared.authority.model_dump(mode="json")),
        stack=StackSnapshot.model_validate(prepared.binding.model_dump(mode="json")),
        observations=rows,
        http_admitted=admitted,
        http_rejected=rejected,
        tool_attempts=tools,
        tools_rejected=denied_tools,
        protocol_cleanup_complete=cleanup,
        collected_at=datetime.now(UTC),
    )


async def execute(directory: Path, output: Path) -> QualityReport:
    prepared = await prepare(directory, output)
    return await collect_prepared(prepared, directory, output)


async def collect_prepared(
    prepared: PreparedQuality, directory: Path, output: Path
) -> QualityReport:
    manifest = prepared.manifest
    observer = ProbeReader(
        prepared.binding.runner_url,
        prepared.observer.token(),
        manifest.nonce,
        prepared.authority,
        prepared.budget.reserve,
    )
    rows: tuple[QualityObservation, ...] = ()
    cleaned = False
    try:
        remaining = (manifest.expires_at - datetime.now(UTC)).total_seconds()
        async with asyncio.timeout(max(0, remaining)):
            for transport in ("stdio", "streamable-http"):
                reserve_protocol_setup(prepared.budget)
                reserve_protocol_setup(prepared.budget)
                batch = manifest.batch_key + "-" + transport
                async with open_protocols(
                    prepared.binding,
                    transport,
                    prepared.issued.writer_token,
                    prepared.issued.tokens["reader_a"],
                    batch,
                    output / "private/sdk" / transport,
                    directory,
                    manifest.expires_at,
                ) as (writer, reader):
                    rows += await collect_transport(
                        manifest,
                        transport,
                        writer,
                        reader,
                        observer,
                        prepared.budget,
                        prepared.sentinel,
                        output / "private/scenarios",
                    )
            cleaned = True
    finally:
        await observer.close()
        evidence = evidence_for(prepared, rows, cleaned)
        report = verify(manifest, evidence, prepared.authority)
        write_reports(report, evidence, output / "public")
    return observe(output / "public")


def finalize(directory: Path, output: Path) -> QualityReport:
    public = output / "public"
    manifest = QualityManifest.model_validate(read_json(public / "manifest.json"))
    authority = ProbeAuthority.model_validate(read_json(public / "authority.json"))
    evidence = QualityEvidence.model_validate(read_json(public / "evidence.json"))
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    if evidence.stack.model_dump(mode="json") != binding.model_dump(mode="json"):
        raise HarnessError("SELFTEST_QUALITY_DISPOSAL_STACK_CHANGED")
    if read_json(directory / "ownership.json") != {
        "project_name": binding.project_name,
        "nonce": binding.nonce,
    } or read_json(directory / "cleanup.json") != {
        "project_name": binding.project_name,
        "status": "completed",
    }:
        raise HarnessError("SELFTEST_QUALITY_DISPOSAL_OWNERSHIP_MISMATCH")
    if authority.builds.verifier != _verifier_digest(binding.runtime_profile):
        raise HarnessError("SELFTEST_QUALITY_VERIFIER_SOURCE_CHANGED")
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
    parser = argparse.ArgumentParser(description="MCP设计质量与不可信材料边界自测; 不调用模型")
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
