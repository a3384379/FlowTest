"""Trusted CI wrapper for mandatory negative protocol/governance deployment packs."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from scripts.selftest.contracts import Builds, Contract, Sha256, canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import BuildReceipt, StackBinding, _verify_removed
from scripts.selftest.mcp_governance_contracts import Manifest
from scripts.selftest.mcp_governance_verify import Report, write_incomplete_reports
from scripts.selftest.mcp_negative_contracts import ProtocolManifest
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_evidence import DeployedEvidence
from scripts.selftest.mcp_probe_run import _profile_pack
from scripts.selftest.mcp_probe_setup import builds
from scripts.selftest.mcp_probe_verify import verify_deployed, write_deployed_reports

if TYPE_CHECKING:
    from scripts.selftest_ci import BatchSummary, RunPaths, StageResult

ProbePack = Literal["protocol34", "governance42"]
PACKS: tuple[ProbePack, ProbePack] = ("protocol34", "governance42")
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProbeBundle:
    manifest: Manifest | ProtocolManifest
    evidence: DeployedEvidence
    authority: ProbeAuthority
    report: Report


class ProbeFirstReceipt(Contract):
    pack_kind: ProbePack
    manifest_digest: Sha256
    authority_digest: Sha256
    evidence_digest: Sha256
    report_digest: Sha256


class ProbeArchiveIdentity(Contract):
    pack_kind: ProbePack
    batch_key: str
    pack_digest: Sha256
    source_digest: Sha256
    runtime_profile: Literal["full", "compact", "standalone"]
    builds: Builds
    scenario_count: Literal[34, 42]
    manifest_sha256: Sha256
    evidence_sha256: Sha256
    authority_digest: Sha256
    claim: Literal["governance_negative_only"] = "governance_negative_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


def _output(paths: RunPaths, pack: ProbePack) -> Path:
    return paths.directory / ("probe-" + pack)


def _command(paths: RunPaths, pack: ProbePack, *, finalize: bool) -> list[str]:
    args = [
        paths.python,
        "-m",
        "scripts.selftest.mcp_probe_run",
        "--directory",
        str(paths.stack),
        "--output",
        str(_output(paths, pack)),
        "--pack",
        pack,
    ]
    return [*args, "--finalize-disposable"] if finalize else args


def _binding(paths: RunPaths) -> StackBinding:
    binding = StackBinding.model_validate(read_json(paths.stack / "stack.json"))
    receipt = BuildReceipt.model_validate(read_json(paths.stack / "build-receipt.json"))
    if binding.runtime_profile != paths.profile or any(
        getattr(binding, field) != getattr(receipt, field) for field in type(receipt).model_fields
    ):
        raise HarnessError("SELFTEST_CI_PROBE_STACK_BUILD_MISMATCH")
    return binding


def _bundle(paths: RunPaths, pack: ProbePack) -> ProbeBundle:
    public = _output(paths, pack) / "public"
    model = ProtocolManifest if pack == "protocol34" else Manifest
    manifest = model.model_validate(read_json(public / "manifest.json"))
    evidence = DeployedEvidence.model_validate(read_json(public / "evidence.json"))
    authority = ProbeAuthority.model_validate(read_json(public / "authority.json"))
    report = Report.model_validate(read_json(public / "verification.json"))
    binding = _binding(paths)
    if evidence.pack_kind != pack or evidence.stack.model_dump(
        exclude={"runner_container_id"}
    ) != binding.model_dump(exclude={"runner_container_id"}):
        raise HarnessError("SELFTEST_CI_PROBE_BINDING_MISMATCH")
    if authority.runtime_profile != paths.profile or authority.builds != builds(binding):
        raise HarnessError("SELFTEST_CI_PROBE_PROFILE_OR_BUILD_MISMATCH")
    raw = (
        _profile_pack(paths.profile)
        if pack == "protocol34"
        else read_json(ROOT / "selftest/packs/mcp-governance-negative-v1/pack.json")
    )
    rows = raw.get("scenarios")
    if not isinstance(rows, list):
        raise HarnessError("SELFTEST_CI_PROBE_PACK_INVALID")
    expected = [row["scenario_id"] for row in rows if isinstance(row, dict)]
    count = 34 if pack == "protocol34" else 42
    if (
        len(expected) != count
        or len(set(expected)) != count
        or manifest.pack_digest != canonical_digest(raw)
        or [row.scenario_id for row in manifest.scenarios] != expected
        or [row.scenario_id for row in report.scenarios] != expected
        or report.batch_key != manifest.batch_key
        or manifest.source_digest != binding.source_digest
    ):
        raise HarnessError("SELFTEST_CI_PROBE_DENOMINATOR_OR_SOURCE_MISMATCH")
    checked = verify_deployed(manifest, evidence, authority, now=datetime.now(UTC))
    if checked != report:
        raise HarnessError("SELFTEST_CI_PROBE_REPORT_NOT_REPRODUCIBLE")
    return ProbeBundle(manifest, evidence, authority, report)


def _pending(bundle: ProbeBundle) -> bool:
    return (
        bundle.report.exit_code == 2
        and len(bundle.report.findings) == 1
        and bundle.report.findings[0].code == "OWNED_ASSET_DISPOSAL_PENDING"
        and bundle.report.findings[0].status == "incomplete"
        and bundle.evidence.disposal_receipt is None
        and all(
            row.verification_status == "matched" and not row.findings
            for row in bundle.report.scenarios
        )
    )


def _first(bundle: ProbeBundle) -> ProbeFirstReceipt:
    return ProbeFirstReceipt(
        pack_kind=bundle.evidence.pack_kind,
        manifest_digest=canonical_digest(bundle.manifest.model_dump(mode="json")),
        authority_digest=canonical_digest(bundle.authority.model_dump(mode="json")),
        evidence_digest=canonical_digest(bundle.evidence.model_dump(mode="json")),
        report_digest=canonical_digest(bundle.report.model_dump(mode="json")),
    )


def _archive_probe_failure(
    paths: RunPaths,
    pack: ProbePack,
    phase: Literal["before-disposal", "finalization"],
    error: BaseException,
) -> None:
    destination = paths.public / f"probe-{pack}-{phase}-failure"
    write_incomplete_reports(destination, failure_codes(error)[0])
    try:
        source = _output(paths, pack) / "public/verification.json"
        if source.stat().st_size > 1048576:
            raise HarnessError("SELFTEST_CI_PROBE_PUBLIC_REPORT_TOO_LARGE")
        report = Report.model_validate(read_json(source))
    except (HarnessError, OSError, ValueError) as report_error:
        write_incomplete_reports(
            destination / "source-report-unavailable", failure_codes(report_error)[0]
        )
    else:
        write_json(destination / "observed-verification.json", report)


def run_probe_stages(paths: RunPaths, stages: list[StageResult]) -> int:
    from scripts.selftest_ci import StageResult, command

    for pack in PACKS:
        code: int | None = None
        try:
            if _output(paths, pack).exists():
                raise HarnessError("SELFTEST_CI_PROBE_OUTPUT_ALREADY_EXISTS")
            code = command(
                _command(paths, pack, finalize=False),
                log=paths.directory / f"private-logs/probe-{pack}.log",
                timeout=660,
            )
            stages.append(StageResult(f"{pack}-before-disposal", code))
            bundle = _bundle(paths, pack)
            if code != 2 or not _pending(bundle):
                raise HarnessError("SELFTEST_CI_PROBE_PRE_DISPOSAL_INCOMPLETE")
            public = _output(paths, pack) / "public"
            write_json(public / "ci-first.json", _first(bundle))
            # Keep the original blocked report immutable alongside post-disposal output.
            write_json(public / "verification.pre-disposal.json", bundle.report)
        except (HarnessError, OSError, ValueError, subprocess.SubprocessError) as error:
            _archive_probe_failure(paths, pack, "before-disposal", error)
            if code is None:
                stages.append(StageResult(f"{pack}-before-disposal", 2))
            return 2
    return 0


def _owned_disposed(paths: RunPaths) -> None:
    binding = _binding(paths)
    if read_json(paths.stack / "ownership.json") != {
        "project_name": binding.project_name,
        "nonce": binding.nonce,
    } or read_json(paths.stack / "cleanup.json") != {
        "project_name": binding.project_name,
        "status": "completed",
    }:
        raise HarnessError("SELFTEST_CI_PROBE_OWNED_DISPOSAL_REQUIRED")
    _verify_removed(binding.project_name)


def _before_finalize(paths: RunPaths, pack: ProbePack) -> ProbeFirstReceipt:
    first = ProbeFirstReceipt.model_validate(
        read_json(_output(paths, pack) / "public/ci-first.json")
    )
    bundle = _bundle(paths, pack)
    if not _pending(bundle) or _first(bundle) != first:
        raise HarnessError("SELFTEST_CI_PROBE_FIRST_OBSERVATION_CHANGED")
    return first


def _after_finalize(paths: RunPaths, pack: ProbePack, first: ProbeFirstReceipt) -> ProbeBundle:
    bundle = _bundle(paths, pack)
    before = DeployedEvidence.model_validate(
        read_json(_output(paths, pack) / "public/evidence.pre-disposal.json")
    )
    restored = bundle.evidence.model_copy(update={"disposal_receipt": None})
    first_report = Report.model_validate(
        read_json(_output(paths, pack) / "public/verification.pre-disposal.json")
    )
    if (
        canonical_digest(before.model_dump(mode="json")) != first.evidence_digest
        or canonical_digest(first_report.model_dump(mode="json")) != first.report_digest
        or canonical_digest(restored.model_dump(mode="json")) != first.evidence_digest
        or canonical_digest(bundle.manifest.model_dump(mode="json")) != first.manifest_digest
        or canonical_digest(bundle.authority.model_dump(mode="json")) != first.authority_digest
        or bundle.report.exit_code != 0
        or bundle.report.findings
        or bundle.evidence.disposal_receipt is None
        or any(
            row.verification_status != "matched" or row.findings for row in bundle.report.scenarios
        )
    ):
        raise HarnessError("SELFTEST_CI_PROBE_FINALIZATION_INCOMPLETE")
    return bundle


def _archive(paths: RunPaths, pack: ProbePack, bundle: ProbeBundle) -> None:
    public = _output(paths, pack) / "public"
    paths.public.mkdir(parents=True, exist_ok=True)
    identity = ProbeArchiveIdentity(
        pack_kind=pack,
        batch_key=bundle.manifest.batch_key,
        pack_digest=bundle.manifest.pack_digest,
        source_digest=bundle.manifest.source_digest,
        runtime_profile=paths.profile,
        builds=bundle.authority.builds,
        scenario_count=34 if pack == "protocol34" else 42,
        manifest_sha256=hashlib.sha256((public / "manifest.json").read_bytes()).hexdigest(),
        evidence_sha256=hashlib.sha256((public / "evidence.json").read_bytes()).hexdigest(),
        authority_digest=canonical_digest(bundle.authority.model_dump(mode="json")),
    )
    write_json(paths.public / f"probe-{pack}-identity.json", identity)
    with tempfile.TemporaryDirectory(prefix="flowtest-ci-probe-") as location:
        directory = Path(location)
        write_deployed_reports(bundle.report, bundle.evidence, directory)
        for name in ("verification.json", "execution.junit.xml", "verification.junit.xml"):
            source = directory / name
            if source.stat().st_size > 1048576:
                raise HarnessError("SELFTEST_CI_PROBE_PUBLIC_REPORT_TOO_LARGE")
            shutil.copyfile(source, paths.public / f"probe-{pack}-{name}")


def finalize_probe_stages(
    paths: RunPaths, cleanup: str, stages: list[StageResult]
) -> tuple[BatchSummary, ...]:
    from scripts.selftest_ci import BatchSummary, StageResult, command

    results: list[BatchSummary] = []
    for pack in PACKS:
        try:
            if cleanup != "completed":
                raise HarnessError("SELFTEST_CI_PROBE_OWNED_DISPOSAL_REQUIRED")
            _owned_disposed(paths)
            first = _before_finalize(paths, pack)
            code = command(
                _command(paths, pack, finalize=True),
                log=paths.directory / f"private-logs/probe-{pack}-disposal.log",
                timeout=60,
            )
            stages.append(StageResult(f"{pack}-after-disposal", code))
            if code:
                raise HarnessError("SELFTEST_CI_PROBE_FINALIZER_FAILED")
            bundle = _after_finalize(paths, pack, first)
            _archive(paths, pack, bundle)
            results.append(BatchSummary(pack, 0, "passed", bundle.manifest.batch_key))
        except (HarnessError, OSError, ValueError, subprocess.SubprocessError) as error:
            _archive_probe_failure(paths, pack, "finalization", error)
            stages.append(StageResult(f"{pack}-verification", 2))
            results.append(BatchSummary(pack, 2, "blocked"))
    return tuple(results)
