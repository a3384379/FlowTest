"""Owned deployed protocol/governance negative packs; no model, bootstrap or stack start."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, JsonObject, read_json, write_json
from scripts.selftest.local_stack import StackBinding, _verify_removed
from scripts.selftest.mcp_container_http import container_http_gateway
from scripts.selftest.mcp_governance_contracts import (
    Evidence as GovernanceEvidence,
)
from scripts.selftest.mcp_governance_contracts import (
    Manifest,
    Observation,
    Pack,
)
from scripts.selftest.mcp_governance_verify import write_incomplete_reports
from scripts.selftest.mcp_negative_contracts import (
    ProtocolEvidence,
    ProtocolManifest,
    ProtocolObservation,
    ProtocolPack,
)
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_evidence import (
    DeployedEvidence,
    DisposalReceipt,
    ScenarioSnapshots,
    StackSnapshot,
)
from scripts.selftest.mcp_probe_governance import References
from scripts.selftest.mcp_probe_governance import observe as observe_governance
from scripts.selftest.mcp_probe_protocol import freeze as freeze_protocol
from scripts.selftest.mcp_probe_protocol import observe as observe_protocol
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.mcp_probe_setup import (
    PreparedFixture,
    PreparedProbe,
    ProbePack,
    _prepare_claimed,
)
from scripts.selftest.mcp_probe_transport import session
from scripts.selftest.mcp_probe_verify import verify_deployed, write_deployed_reports

ROOT = Path(__file__).resolve().parents[2]


def _profile_pack(profile: str) -> JsonObject:
    raw = read_json(ROOT / "selftest/packs/mcp-negative-v1/pack.json")
    rows = raw["scenarios"]
    if not isinstance(rows, list):
        raise HarnessError("SELFTEST_PROBE_PACK_INVALID")
    for row in rows:
        if isinstance(row, dict) and row.get("operation") == "inspect":
            expected = row.get("expected")
            if not isinstance(expected, dict):
                raise HarnessError("SELFTEST_PROBE_PACK_INVALID")
            expected["runtime_profile"] = profile
    return raw


def _freeze(
    binding: StackBinding,
    fixture: PreparedFixture,
    batch: str,
    nonce: str,
    started: datetime,
    deadline: datetime,
    kind: ProbePack,
) -> Manifest | ProtocolManifest:
    if kind == "protocol34":
        raw = _profile_pack(binding.runtime_profile)
        return freeze_protocol(
            ProtocolPack.model_validate(raw),
            canonical_digest(raw),
            fixture,
            binding.source_digest,
            batch,
            nonce,
            started,
            deadline,
        )
    raw = read_json(ROOT / "selftest/packs/mcp-governance-negative-v1/pack.json")
    pack = Pack.model_validate(raw)
    return Manifest(
        batch_key=batch,
        nonce=nonce,
        pack_digest=canonical_digest(raw),
        source_digest=binding.source_digest,
        sdk_version=pack.sdk_version,
        created_at=started,
        expires_at=deadline,
        fixture=fixture.governance,
        scenarios=pack.scenarios,
    )


def _partial(
    prepared: PreparedProbe,
    rows: list[ProtocolObservation] | list[Observation],
    snapshots: list[ScenarioSnapshots],
) -> None:
    write_json(
        prepared.state / "public/partial.json",
        {
            "scenarios": [row.model_dump(mode="json") for row in rows],
            "snapshots": [row.model_dump(mode="json") for row in snapshots],
        },
    )


async def _protocol(
    prepared: PreparedProbe, reader: ProbeReader, manifest: ProtocolManifest, gateway: str
) -> tuple[list[ProtocolObservation], list[ScenarioSnapshots]]:
    rows: list[ProtocolObservation] = []
    snapshots: list[ScenarioSnapshots] = []
    for scenario in manifest.scenarios:
        row, before, after = await observe_protocol(
            prepared,
            reader,
            scenario,
            gateway,
            prepared.state / "private/sdk" / scenario.scenario_id,
        )
        rows.append(row)
        snapshots.append(
            ScenarioSnapshots(scenario_id=scenario.scenario_id, before=before, after=after)
        )
        _partial(prepared, rows, snapshots)
    return rows, snapshots


async def _governance(
    prepared: PreparedProbe, reader: ProbeReader, manifest: Manifest, gateway: str
) -> tuple[list[Observation], list[ScenarioSnapshots]]:
    rows: list[Observation] = []
    snapshots: list[ScenarioSnapshots] = []
    for transport in ("stdio", "streamable-http"):
        references = References()
        async with session(
            prepared,
            transport,
            prepared.credentials.writer_token,
            gateway,
            prepared.state / "private/sdk" / transport,
        ) as (client, wire):
            await client.discover()
            for scenario in (row for row in manifest.scenarios if row.transport == transport):
                row, before, after, references = await observe_governance(
                    prepared, reader, manifest, scenario, client, wire, references
                )
                rows.append(row)
                snapshots.append(
                    ScenarioSnapshots(scenario_id=scenario.scenario_id, before=before, after=after)
                )
                _partial(prepared, rows, snapshots)
    return rows, snapshots


async def _execute(prepared: PreparedProbe) -> DeployedEvidence:
    model = ProtocolManifest if prepared.pack == "protocol34" else Manifest
    manifest = model.model_validate(read_json(prepared.manifest_path))
    reader = ProbeReader(
        prepared.binding.runner_url,
        prepared.credentials.observer_identity.token(),
        manifest.nonce,
        prepared.authority,
        prepared.budget.reserve,
    )
    protocol_rows: list[ProtocolObservation] = []
    governance_rows: list[Observation] = []
    snapshots: list[ScenarioSnapshots] = []
    try:
        async with asyncio.timeout((manifest.expires_at - datetime.now(UTC)).total_seconds()):
            async with container_http_gateway(
                prepared.binding,
                prepared.directory,
                prepared.state / "public/gateway",
                deadline=manifest.expires_at,
            ) as gateway:
                if isinstance(manifest, ProtocolManifest):
                    protocol_rows, snapshots = await _protocol(
                        prepared, reader, manifest, gateway.url
                    )
                else:
                    governance_rows, snapshots = await _governance(
                        prepared, reader, manifest, gateway.url
                    )
    finally:
        await reader.close()
    admitted, rejected = prepared.budget.counts()
    tools, tools_rejected = prepared.budget.tool_counts()
    now = datetime.now(UTC)
    protocol = None
    governance = None
    if isinstance(manifest, ProtocolManifest):
        protocol = ProtocolEvidence(
            batch_key=manifest.batch_key,
            nonce=manifest.nonce,
            pack_digest=manifest.pack_digest,
            source_digest=manifest.source_digest,
            scenarios=tuple(protocol_rows),
            collected_at=now,
            cleanup_complete=True,
            protocol_attempts=tools,
            http_requests=admitted,
            rejected_http_requests=rejected,
            rejected_tool_calls=tools_rejected,
        )
    else:
        governance = GovernanceEvidence(
            batch_key=manifest.batch_key,
            nonce=manifest.nonce,
            pack_digest=manifest.pack_digest,
            source_digest=manifest.source_digest,
            sdk_version=manifest.sdk_version,
            scenarios=tuple(governance_rows),
            collected_at=now,
            process_cleanup_complete=True,
            http_admitted=admitted,
            http_rejected=rejected,
            tools_admitted=tools,
            tools_rejected=tools_rejected,
        )
    cleanup = read_json(prepared.state / "public/gateway/gateway-cleanup.json")
    return DeployedEvidence(
        pack_kind=prepared.pack,
        manifest_digest=prepared.authority.manifest_digest,
        authority_digest=canonical_digest(prepared.authority.model_dump(mode="json")),
        stack=StackSnapshot.model_validate(prepared.binding.model_dump(mode="json")),
        protocol=protocol,
        governance=governance,
        snapshots=tuple(snapshots),
        gateway_cleanup_complete=cleanup.get("completed") is True,
        disposal_receipt=None,
        collected_at=now,
        request_budget_mode="conservative_outbound_plus_candidate_rpc",
        http_outbound_admitted=admitted - prepared.rpc_budget.admitted,
        candidate_rpc_admitted=prepared.rpc_budget.admitted,
        candidate_rpc_rejected=prepared.rpc_budget.rejected,
    )


async def run_deployed(directory: Path, output: Path, kind: ProbePack) -> int:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        if version("mcp") != "2.2.0":
            raise HarnessError("SELFTEST_LOCKED_SDK_VERSION_MISMATCH")
        prepared = await _prepare_claimed(directory, output, pack=kind, freeze=_freeze)
        write_json(output / "public/authority.json", prepared.authority)
        if kind == "protocol34":
            write_json(
                output / "public/derived-pack.json", _profile_pack(prepared.binding.runtime_profile)
            )
        evidence = await _execute(prepared)
        model = ProtocolManifest if kind == "protocol34" else Manifest
        manifest = model.model_validate(read_json(output / "public/manifest.json"))
        report = verify_deployed(manifest, evidence, prepared.authority)
    except (
        HarnessError,
        ValidationError,
        OSError,
        ValueError,
        TimeoutError,
        ExceptionGroup,
    ) as error:
        return write_incomplete_reports(output / "public", failure_codes(error)[0]).exit_code
    write_json(output / "public/evidence.json", evidence)
    write_deployed_reports(report, evidence, output / "public")
    return report.exit_code


def finalize_disposal(directory: Path, output: Path) -> int:
    evidence = DeployedEvidence.model_validate(read_json(output / "public/evidence.json"))
    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    if stack.model_dump(mode="json", exclude={"runner_container_id"}) != evidence.stack.model_dump(
        mode="json", exclude={"runner_container_id"}
    ):
        raise HarnessError("SELFTEST_PROBE_FINALIZER_STACK_MISMATCH")
    if read_json(directory / "ownership.json") != {
        "project_name": stack.project_name,
        "nonce": stack.nonce,
    } or read_json(directory / "cleanup.json") != {
        "project_name": stack.project_name,
        "status": "completed",
    }:
        raise HarnessError("SELFTEST_PROBE_FINALIZER_OWNERSHIP_MISMATCH")
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
    model = ProtocolManifest if evidence.pack_kind == "protocol34" else Manifest
    manifest = model.model_validate(read_json(output / "public/manifest.json"))
    authority = ProbeAuthority.model_validate(read_json(output / "public/authority.json"))
    report = verify_deployed(manifest, evidence, authority)
    write_json(output / "public/evidence.json", evidence)
    write_deployed_reports(report, evidence, output / "public")
    return report.exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="仅在已拥有并核验的隔离栈执行负向探针, 零模型调用")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pack", choices=("protocol34", "governance42"), default="protocol34")
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    if args.finalize_disposable:
        return finalize_disposal(args.directory, args.output)
    code = asyncio.run(run_deployed(args.directory, args.output, args.pack))
    print(
        json.dumps(
            {
                "output": str(args.output / "public"),
                "exit_code": code,
                "claim": "governance_negative_only",
            }
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
