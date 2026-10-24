"""Run O with a minimal environment; a stale green report can never substitute for O."""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.selftest.io import HarnessError, read_json
from scripts.selftest.local_stack import ROOT
from scripts.selftest.mcp_governance_verify import Verdict, failure
from scripts.selftest.quality_contracts import QualityManifest
from scripts.selftest.quality_verify import QualityReport, write_reports


def observe(public: Path) -> QualityReport:
    manifest = QualityManifest.model_validate(read_json(public / "manifest.json"))
    blocked = QualityReport(
        batch_key=manifest.batch_key,
        exit_code=2,
        findings=(failure("QUALITY_OBSERVER_PROCESS_UNAVAILABLE", True),),
        scenarios=tuple(
            Verdict(scenario_id=r.scenario_id, verification_status="incomplete", findings=())
            for r in manifest.scenarios
        ),
    )
    destination = public / "independent-o"
    write_reports(blocked, None, destination)
    command = [
        sys.executable,
        "-m",
        "scripts.selftest.quality_verify",
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
            raise HarnessError("QUALITY_OBSERVER_DEADLINE_EXCEEDED")
        result = subprocess.run(  # noqa: S603 -- fixed trusted module and typed paths
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
        report = QualityReport.model_validate(read_json(destination / "verification.json"))
        if result.returncode != report.exit_code or (
            report.batch_key,
            tuple(r.scenario_id for r in report.scenarios),
        ) != (manifest.batch_key, tuple(r.scenario_id for r in manifest.scenarios)):
            raise HarnessError("QUALITY_OBSERVER_RECEIPT_MISMATCH")
    except (OSError, ValueError, subprocess.SubprocessError, HarnessError):
        report = blocked
    write_reports(report, None, public)
    return report
