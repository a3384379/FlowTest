"""Run isolated O processes against copies of actual F/C/S results at their frozen clock.

This is diagnostic evidence replay, not a fresh target execution or a trusted CI seal.
The unmodified positive control must pass before any corrupted copy can count.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError
from scripts.selftest.canary_mutations import mutate
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Contract,
    VerificationReport,
    canonical_digest,
)
from scripts.selftest.io import HarnessError, JsonObject, read_json, write_json
from scripts.selftest.local_stack import ROOT
from scripts.selftest.run import _verifier_digest
from scripts.selftest.verify import verify_batch, write_report


class CanarySpec(Contract):
    key: str
    source: Literal["fixed-core", "mcp-core"]
    expected_reason: str
    acceptance_variants: tuple[str, ...]


class CanaryPack(Contract):
    pack_id: Literal["observer-canaries-v1"]
    version: Literal["1.0.0"]
    scope: str
    scenarios: tuple[CanarySpec, ...] = Field(min_length=28, max_length=28)


class CheckResult(Contract):
    exit_code: int
    reason_codes: tuple[str, ...]


class CanaryObservation(Contract):
    scenario_id: str
    acceptance_variants: tuple[str, ...]
    observer_exit_code: int
    reason_codes: tuple[str, ...]
    matched: bool


class CanaryReport(Contract):
    scope: str
    pack_digest: str
    profile: str
    verifier_digest: str
    source_hashes: dict[str, str]
    originals_unchanged: bool
    scenarios: tuple[CanaryObservation, ...]
    exit_code: int
    model_calls: Literal[0] = 0
    trust: Literal["local_untrusted"] = "local_untrusted"


def load_pack() -> CanaryPack:
    return CanaryPack.model_validate(
        read_json(ROOT / "selftest/packs/observer-canaries-v1/pack.json")
    )


def evaluate(
    manifest_input: JsonObject, evidence_input: JsonObject, clock: str
) -> tuple[CheckResult, VerificationReport | None]:
    report = None
    try:
        manifest = BatchManifest.model_validate(manifest_input)
        evidence = BatchEvidence.model_validate(evidence_input)
        report = verify_batch(
            manifest,
            evidence,
            now=datetime.fromisoformat(clock),
        )
        reasons = tuple(
            dict.fromkeys(
                [f.code for f in report.findings]
                + [f.code for row in report.scenarios for f in row.findings]
            )
        )
        code = report.exit_code
    except (ValueError, ValidationError):
        reasons, code = ("OBSERVER_INPUT_ERROR",), 2
    return CheckResult(exit_code=code, reason_codes=reasons), report


def check_one(case: Path) -> int:
    control = read_json(case / "clock.json")
    result, report = evaluate(
        read_json(case / "manifest.json"),
        read_json(case / "evidence.json"),
        str(control["verification_time"]),
    )
    if report is not None:
        write_report(report, case / "o")
    write_json(case / "result.json", result)
    return result.exit_code


def _child(case: Path) -> tuple[int, tuple[str, ...]]:
    child = subprocess.run(  # noqa: S603 -- fixed independent O module, exact diagnostic copy
        [
            sys.executable,
            "-m",
            "scripts.selftest.canary_replay",
            "--check-one",
            str(case),
        ],
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
        capture_output=True,
        timeout=30,
        check=False,
    )
    result = CheckResult.model_validate(read_json(case / "result.json"))
    if child.returncode != result.exit_code:
        raise HarnessError("CANARY_CHILD_RECEIPT_MISMATCH")
    return child.returncode, result.reason_codes


def _copy(
    directory: Path, manifest: JsonObject, evidence: JsonObject, *, clock: str
) -> tuple[int, tuple[str, ...]]:
    directory.mkdir(parents=True, mode=0o700)
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "evidence.json", evidence)
    write_json(directory / "clock.json", {"verification_time": clock})
    (directory / "execution.junit.xml").write_text(
        '<testsuite tests="1" failures="0"><testcase name="untrusted-zero" /></testsuite>\n'
    )
    return _child(directory)


def mutated_source(
    spec: CanarySpec, manifest: JsonObject, evidence: JsonObject
) -> tuple[JsonObject, JsonObject, str]:
    manifest, evidence = deepcopy(manifest), deepcopy(evidence)
    clock = str(evidence["collected_at"])
    if spec.key == "expiry":
        clock = (
            datetime.fromisoformat(str(manifest["expires_at"])) + timedelta(seconds=1)
        ).isoformat()
    else:
        mutate(spec.key, manifest, evidence)
    return manifest, evidence, clock


def _recheck_identity(
    saved: CanaryReport, pack: CanaryPack, profile: str, hashes: dict[str, str]
) -> None:
    valid = (
        saved.exit_code == 0
        and saved.originals_unchanged
        and saved.verifier_digest == _verifier_digest(profile)
        and saved.profile == profile
        and saved.pack_digest == canonical_digest(pack.model_dump(mode="json"))
        and tuple(row.scenario_id for row in saved.scenarios)
        == tuple(row.key for row in pack.scenarios)
        and saved.source_hashes == hashes
        and len(hashes) == 4
    )
    if not valid:
        raise HarnessError("CANARY_ARCHIVE_SOURCE_OR_DENOMINATOR_CHANGED")


def recheck(reports: Path, output: Path, profile: str) -> CanaryReport:
    saved = CanaryReport.model_validate(read_json(output / "verification.json"))
    pack = load_pack()
    hashes = {
        str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
        for name in {row.source for row in pack.scenarios}
        for filename in ("manifest.json", "evidence.json")
        for path in (reports / name / "round-1" / filename,)
    }
    _recheck_identity(saved, pack, profile, hashes)
    for spec, observed in zip(pack.scenarios, saved.scenarios, strict=True):
        source = reports / spec.source / "round-1"
        manifest, evidence, clock = mutated_source(
            spec, read_json(source / "manifest.json"), read_json(source / "evidence.json")
        )
        case = output / spec.key
        if (
            read_json(case / "manifest.json") != manifest
            or read_json(case / "evidence.json") != evidence
        ):
            raise HarnessError("CANARY_ARCHIVE_MUTATION_CHANGED")
        result, _ = evaluate(manifest, evidence, clock)
        if (
            not observed.matched
            or observed.acceptance_variants != spec.acceptance_variants
            or observed.observer_exit_code != result.exit_code
            or observed.reason_codes != result.reason_codes
            or spec.expected_reason not in result.reason_codes
            or result.exit_code not in (1, 2)
        ):
            raise HarnessError("CANARY_ARCHIVE_RESULT_CHANGED")
    return saved


def run(reports: Path, output: Path, profile: str) -> int:
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    frozen = _verifier_digest(profile)
    pack = load_pack()
    if not pack.scenarios or len({row.key for row in pack.scenarios}) != len(pack.scenarios):
        raise HarnessError("CANARY_DENOMINATOR_INVALID")
    sources: dict[str, tuple[JsonObject, JsonObject, str]] = {}
    hashes: dict[str, str] = {}
    for name in {row.source for row in pack.scenarios}:
        source = reports / name / "round-1"
        for filename in ("manifest.json", "evidence.json"):
            path = source / filename
            hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest, evidence = (
            read_json(source / "manifest.json"),
            read_json(source / "evidence.json"),
        )
        clock = str(evidence["collected_at"])
        code, reasons = _copy(output / "controls" / name, manifest, evidence, clock=clock)
        if code or reasons:
            raise HarnessError("CANARY_POSITIVE_CONTROL_NOT_GREEN:" + name)
        sources[name] = manifest, evidence, clock
    rows: list[CanaryObservation] = []
    for spec in pack.scenarios:
        original_manifest, original_evidence, _ = sources[spec.source]
        manifest, evidence, clock = mutated_source(spec, original_manifest, original_evidence)
        code, reasons = _copy(output / spec.key, manifest, evidence, clock=clock)
        rows.append(
            CanaryObservation(
                scenario_id=spec.key,
                acceptance_variants=spec.acceptance_variants,
                observer_exit_code=code,
                reason_codes=reasons,
                matched=code in (1, 2) and spec.expected_reason in reasons,
            )
        )
    unchanged = all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in hashes.items()
    )
    code = 0 if unchanged and all(row.matched for row in rows) else 2
    if _verifier_digest(profile) != frozen or load_pack() != pack:
        raise HarnessError("CANARY_VERIFIER_CHANGED")
    write_json(
        output / "verification.json",
        CanaryReport(
            scope=pack.scope,
            pack_digest=canonical_digest(pack.model_dump(mode="json")),
            profile=profile,
            verifier_digest=frozen,
            source_hashes=hashes,
            originals_unchanged=unchanged,
            scenarios=tuple(rows),
            exit_code=code,
        ),
    )
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="实际部署证据的独立进程反误绿回放; 不重放目标请求")
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile", choices=("full", "compact", "standalone"))
    parser.add_argument("--check-one", type=Path)
    args = parser.parse_args()
    if args.check_one is not None:
        return check_one(args.check_one)
    if args.reports is None or args.output is None or args.profile is None:
        parser.error("需要 reports、output 和 profile")
    return run(args.reports, args.output, args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
