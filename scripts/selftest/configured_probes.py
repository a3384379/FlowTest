"""Install all grants first; freeze the final runner before collecting any new pack."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from scripts.selftest import mcp_fault_run, quality_run, review_boundary_run
from scripts.selftest.configured_probe_observer import (
    SPECS,
    ConfiguredPack,
    ConfiguredReport,
    observe,
)
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import StackBinding, verify_binding
from scripts.selftest.mcp_fault_setup import PreparedFault
from scripts.selftest.mcp_fault_setup import prepare as prepare_fault
from scripts.selftest.mcp_fault_verify import verify as verify_fault
from scripts.selftest.mcp_fault_verify import write_reports as write_fault
from scripts.selftest.quality_setup import PreparedQuality
from scripts.selftest.quality_setup import prepare as prepare_quality
from scripts.selftest.review_boundary_setup import PreparedReview
from scripts.selftest.review_boundary_setup import prepare as prepare_review


@dataclass(frozen=True, repr=False)
class PreparedGroup:
    fault: PreparedFault
    quality: PreparedQuality
    review: PreparedReview


class GroupResult(Contract):
    exit_code: Literal[0, 1, 2]
    reports: tuple[ConfiguredReport, ...]
    reason_codes: tuple[str, ...] = ()
    claim: Literal["configured_mcp_negative_packs_only"] = "configured_mcp_negative_packs_only"
    trust: Literal["local_untrusted"] = "local_untrusted"


def require_same_owned_stack(earlier: StackBinding, current: StackBinding) -> None:
    if earlier.model_dump(mode="json", exclude={"runner_container_id"}) != current.model_dump(
        mode="json", exclude={"runner_container_id"}
    ):
        raise HarnessError("SELFTEST_CONFIGURED_GROUP_STACK_DRIFT")


async def prepare_all(directory: Path, output: Path) -> PreparedGroup:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    fault = await prepare_fault(directory, output / "faults")
    quality = await prepare_quality(directory, output / "quality")
    review = await prepare_review(directory, output / "review")
    current = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(current, directory)
    for prepared in (fault, quality, review):
        require_same_owned_stack(prepared.binding, current)
    # This happens before any fault/quality/review SDK observation. No sealed
    # evidence or frozen runner identity is rewritten after execution.
    selected = PreparedGroup(
        replace(fault, binding=current),
        replace(quality, binding=current),
        replace(review, binding=current),
    )
    write_json(
        output / "collection-binding.json",
        {
            "stack": current.model_dump(mode="json"),
            "manifest_digests": [
                canonical_digest(item.manifest.model_dump(mode="json"))
                for item in (fault, quality, review)
            ],
            "phase": "all_grants_installed_before_collection",
        },
    )
    return selected


def _observed(
    pack: ConfiguredPack, prepared: PreparedFault | PreparedQuality | PreparedReview, output: Path
) -> ConfiguredReport:
    spec = next(item for item in SPECS if item.name == pack)
    manifest = prepared.manifest
    report = observe(
        spec,
        output / pack / "public",
        batch_key=manifest.batch_key,
        scenario_ids=tuple(r.scenario_id for r in manifest.scenarios),
        deadline=manifest.expires_at,
    )
    write_json(output / pack / "public/verification.json", report)
    independent = output / pack / "public/configured-o"
    for filename in ("execution.junit.xml", "verification.junit.xml"):
        source = independent / filename
        if not source.exists():
            raise HarnessError("SELFTEST_CONFIGURED_OBSERVER_JUNIT_MISSING")
        shutil.copyfile(source, output / pack / "public" / filename)
    return report


def _only_disposal(report: ConfiguredReport) -> bool:
    return (
        report.exit_code == 2
        and len(report.findings) == 1
        and report.findings[0].code == "OWNED_ASSET_DISPOSAL_PENDING"
        and report.findings[0].status == "incomplete"
        and all(r.verification_status == "matched" and not r.findings for r in report.scenarios)
    )


async def run(directory: Path, output: Path) -> GroupResult:
    group = await prepare_all(directory, output)
    reports = []
    evidence = await mcp_fault_run.execute(group.fault)
    write_json(output / "faults/public/evidence.json", evidence)
    write_fault(
        verify_fault(group.fault.manifest, evidence, group.fault.authority),
        evidence,
        output / "faults/public",
    )
    reports.append(_observed("faults", group.fault, output))
    if _only_disposal(reports[-1]):
        await quality_run.collect_prepared(group.quality, directory, output / "quality")
        reports.append(_observed("quality", group.quality, output))
    if len(reports) == 2 and _only_disposal(reports[-1]):
        await review_boundary_run.collect_prepared(group.review, directory, output / "review")
        reports.append(_observed("review", group.review, output))
    result = GroupResult(
        exit_code=2 if len(reports) == 3 and all(_only_disposal(r) for r in reports) else 1,
        reports=tuple(reports),
    )
    write_json(output / "group-verification.json", result)
    return result


def finalize(directory: Path, output: Path) -> GroupResult:
    from scripts.selftest.mcp_fault_contracts import FaultManifest
    from scripts.selftest.mcp_probe_contracts import ProbeAuthority
    from scripts.selftest.quality_contracts import QualityManifest
    from scripts.selftest.review_boundary_contracts import ReviewManifest

    mcp_fault_run.finalize(directory, output / "faults")
    quality_run.finalize(directory, output / "quality")
    review_boundary_run.finalize(directory, output / "review")
    models: tuple[type[FaultManifest] | type[QualityManifest] | type[ReviewManifest], ...] = (
        FaultManifest,
        QualityManifest,
        ReviewManifest,
    )
    reports = []
    for spec, model in zip(SPECS, models, strict=True):
        public = output / spec.name / "public"
        manifest = model.model_validate(read_json(public / "manifest.json"))
        authority = ProbeAuthority.model_validate(read_json(public / "authority.json"))
        if authority.manifest_digest != canonical_digest(manifest.model_dump(mode="json")):
            raise HarnessError("SELFTEST_CONFIGURED_FINALIZER_MANIFEST_MISMATCH")
        reports.append(
            observe(
                spec,
                public,
                batch_key=manifest.batch_key,
                scenario_ids=tuple(r.scenario_id for r in manifest.scenarios),
                deadline=manifest.expires_at,
            )
        )
        write_json(public / "verification.json", reports[-1])
    result = GroupResult(
        exit_code=0 if all(r.exit_code == 0 for r in reports) else 2, reports=tuple(reports)
    )
    write_json(output / "group-verification.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="先统一配置再冻结执行身份的MCP故障/质量/审核验收; 不调用模型"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    args = parser.parse_args()
    existing = args.output.exists()
    try:
        result = (
            finalize(args.directory, args.output)
            if args.finalize_disposable
            else asyncio.run(run(args.directory, args.output))
        )
    except FileExistsError as error:
        result = GroupResult(exit_code=1, reports=(), reason_codes=failure_codes(error))
    except (HarnessError, OSError, ValueError, TimeoutError, ExceptionGroup) as error:
        result = GroupResult(exit_code=2, reports=(), reason_codes=failure_codes(error))
        if not existing:
            write_json(args.output / "group-verification.json", result)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
