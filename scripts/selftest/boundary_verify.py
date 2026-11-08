"""Credential-free entrypoint for exact initialization, security and expiry oracles."""

import argparse
import json
from pathlib import Path
from typing import Literal

from scripts.selftest.auth_expiry import AuthExpiryResult, verify_auth_expiry
from scripts.selftest.boundary_reporting import write_boundary_junit
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.initialization_contracts import InitializationResult
from scripts.selftest.io import JsonObject, read_json, write_json
from scripts.selftest.security_boundary_contracts import BoundaryResult
from scripts.selftest.verify_initialization_boundaries import verify_initialization_boundaries
from scripts.selftest.verify_security_boundaries import verify_security_boundaries

BoundaryPack = Literal["security", "initialization", "auth-expiry"]


class BoundaryReport(Contract):
    pack: BoundaryPack
    result_digest: str
    manifest_digest: str
    scenario_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    exit_code: Literal[0, 2]
    trust: Literal["local_untrusted"] = "local_untrusted"


def verify(pack: BoundaryPack, raw: JsonObject) -> BoundaryReport:
    if pack == "security":
        security = BoundaryResult.model_validate(raw)
        reasons = verify_security_boundaries(security)
        manifest = security.manifest.model_dump(mode="json")
        identifiers = security.manifest.expected_scenarios
    elif pack == "initialization":
        initialization = InitializationResult.model_validate(raw)
        reasons = verify_initialization_boundaries(initialization)
        manifest = initialization.manifest.model_dump(mode="json")
        identifiers = initialization.manifest.expected_scenarios
    else:
        expiry = AuthExpiryResult.model_validate(raw)
        reasons = verify_auth_expiry(expiry.manifest, expiry.evidence)
        manifest = expiry.manifest.model_dump(mode="json")
        identifiers = (expiry.manifest.scenario_id,)
    return BoundaryReport(
        pack=pack,
        result_digest=canonical_digest(raw),
        manifest_digest=canonical_digest(manifest),
        scenario_ids=identifiers,
        reason_codes=reasons,
        exit_code=2 if reasons else 0,
    )


def write_report(report: BoundaryReport, directory: Path) -> None:
    write_json(directory / "verification.json", report)
    write_boundary_junit(
        directory,
        report.scenario_ids,
        report.reason_codes,
        purpose="边界探针或Preview不表示正式用例执行",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="独立核验初始化/安全/真实认证过期证据")
    parser.add_argument(
        "--pack", choices=("security", "initialization", "auth-expiry"), required=True
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.pack, read_json(args.result))
    write_report(report, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
