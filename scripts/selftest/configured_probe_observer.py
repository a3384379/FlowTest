"""The three configured packs share a credential-free, stale-report-safe O boundary."""

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from scripts.selftest.contracts import Contract
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import ROOT
from scripts.selftest.mcp_governance_verify import Finding, Verdict, failure

ConfiguredPack = Literal["faults", "quality", "review"]
Claim = Literal[
    "transport_fault_negative_only",
    "generation_quality_negative_only",
    "review_recovery_and_preview_only",
]


@dataclass(frozen=True)
class ProbeSpec:
    name: ConfiguredPack
    module: str
    count: int
    claim: Claim


SPECS = (
    ProbeSpec("faults", "scripts.selftest.mcp_fault_verify", 14, "transport_fault_negative_only"),
    ProbeSpec("quality", "scripts.selftest.quality_verify", 18, "generation_quality_negative_only"),
    ProbeSpec(
        "review", "scripts.selftest.review_boundary_verify", 12, "review_recovery_and_preview_only"
    ),
)


class ConfiguredReport(Contract):
    batch_key: str
    exit_code: Literal[0, 1, 2]
    findings: tuple[Finding, ...]
    scenarios: tuple[Verdict, ...]
    claim: Claim
    trust: Literal["local_untrusted"] = "local_untrusted"


def observe(
    spec: ProbeSpec,
    public: Path,
    *,
    batch_key: str,
    scenario_ids: tuple[str, ...],
    deadline: datetime,
) -> ConfiguredReport:
    if len(scenario_ids) != spec.count or len(set(scenario_ids)) != spec.count:
        raise HarnessError("SELFTEST_CONFIGURED_OBSERVER_DENOMINATOR_MISMATCH")
    blocked = ConfiguredReport(
        batch_key=batch_key,
        exit_code=2,
        findings=(failure("CONFIGURED_OBSERVER_PROCESS_UNAVAILABLE", True),),
        scenarios=tuple(
            Verdict(scenario_id=identifier, verification_status="incomplete", findings=())
            for identifier in scenario_ids
        ),
        claim=spec.claim,
    )
    destination = public / "configured-o"
    write_json(destination / "verification.json", blocked)
    for name in ("execution.junit.xml", "verification.junit.xml"):
        (destination / name).unlink(missing_ok=True)
    command = [
        sys.executable,
        "-m",
        spec.module,
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
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise HarnessError("SELFTEST_CONFIGURED_OBSERVER_DEADLINE_EXCEEDED")
        child = subprocess.run(  # noqa: S603 -- fixed trusted O module and typed paths
            command,
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
        report = ConfiguredReport.model_validate(read_json(destination / "verification.json"))
        if (
            report.batch_key,
            report.claim,
            report.exit_code,
            tuple(r.scenario_id for r in report.scenarios),
        ) != (batch_key, spec.claim, child.returncode, scenario_ids):
            raise HarnessError("SELFTEST_CONFIGURED_OBSERVER_RECEIPT_MISMATCH")
        if report.exit_code == 0 and (
            report.findings
            or any(r.verification_status != "matched" or r.findings for r in report.scenarios)
        ):
            raise HarnessError("SELFTEST_CONFIGURED_OBSERVER_FALSE_SUCCESS")
    except (OSError, ValueError, subprocess.SubprocessError, HarnessError):
        report = blocked
    return report
