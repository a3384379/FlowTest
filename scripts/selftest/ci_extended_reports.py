"""Safe, typed summaries for independently verified extension packs."""

import hashlib
import shutil
from pathlib import Path
from typing import Literal

from scripts.selftest.bad_targets_contracts import SCENARIOS, BadTargetsResult
from scripts.selftest.bad_targets_verify import verify_bad_targets
from scripts.selftest.boundary_verify import BoundaryPack
from scripts.selftest.boundary_verify import verify as verify_boundary
from scripts.selftest.configured_probe_observer import ConfiguredReport
from scripts.selftest.contract_delta_contracts import DeltaReport
from scripts.selftest.contracts import Builds, Contract, canonical_digest
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.native_control_contracts import NativeControlReport
from scripts.selftest.run import _verifier_digest
from scripts.selftest.semantic_contracts import SemanticReport


def recheck_report(label: str, source: Path) -> Contract:
    if label == "compiler":
        from scripts.selftest.compile_boundary_contracts import (
            CompileBoundaryEvidence,
            CompileBoundaryManifest,
        )
        from scripts.selftest.compile_boundary_verify import verify as verify_compiler

        return verify_compiler(
            CompileBoundaryManifest.model_validate(read_json(source / "manifest.json")),
            CompileBoundaryEvidence.model_validate(read_json(source / "evidence.json")),
        )
    from scripts.selftest.contract_delta_contracts import DeltaEvidence, DeltaManifest
    from scripts.selftest.contract_delta_verify import load_pack
    from scripts.selftest.contract_delta_verify import verify as verify_delta
    from scripts.selftest.local_stack import ROOT
    from scripts.selftest.mcp_fault_contracts import FaultEvidence, FaultManifest
    from scripts.selftest.mcp_fault_verify import verify as verify_fault
    from scripts.selftest.native_control_contracts import (
        NativeControlEvidence,
        NativeControlManifest,
    )
    from scripts.selftest.native_control_verify import load_pack as load_control
    from scripts.selftest.native_control_verify import verify as verify_control
    from scripts.selftest.product_boundary_contracts import (
        ProductBoundaryEvidence,
        ProductBoundaryManifest,
    )
    from scripts.selftest.product_boundary_verify import verify as verify_product
    from scripts.selftest.quality_contracts import QualityEvidence, QualityManifest
    from scripts.selftest.quality_verify import verify as verify_quality
    from scripts.selftest.review_boundary_contracts import (
        ReviewEvidence,
        ReviewManifest,
    )
    from scripts.selftest.review_boundary_verify import verify as verify_review
    from scripts.selftest.semantic_contracts import SemanticEvidence, SemanticManifest
    from scripts.selftest.semantic_verify import verify_semantic
    from scripts.selftest.worker_fault_contracts import WorkerEvidence, WorkerManifest
    from scripts.selftest.worker_fault_verify import verify as verify_workers

    manifest, evidence = (
        read_json(source / "manifest.json"),
        read_json(source / "evidence.json"),
    )
    if label == "product":
        return verify_product(
            ProductBoundaryManifest.model_validate(manifest),
            ProductBoundaryEvidence.model_validate(evidence),
        )
    if label == "workers":
        return verify_workers(
            WorkerManifest.model_validate(manifest),
            WorkerEvidence.model_validate(evidence),
        )
    if label == "semantic":
        return verify_semantic(
            SemanticManifest.model_validate(manifest),
            SemanticEvidence.model_validate(evidence),
        )
    if label == "delta":
        return verify_delta(
            DeltaManifest.model_validate(manifest),
            load_pack(ROOT / "selftest/packs/contract-delta-v1/pack.json"),
            DeltaEvidence.model_validate(evidence),
        )
    if label == "control":
        return verify_control(
            NativeControlManifest.model_validate(manifest),
            load_control(ROOT / "selftest/packs/native-control-mcp-v1/pack.json"),
            NativeControlEvidence.model_validate(evidence),
        )
    authority = ProbeAuthority.model_validate(read_json(source / "authority.json"))
    if label == "faults":
        return verify_fault(
            FaultManifest.model_validate(manifest),
            FaultEvidence.model_validate(evidence),
            authority,
        )
    if label == "quality":
        return verify_quality(
            QualityManifest.model_validate(manifest),
            QualityEvidence.model_validate(evidence),
            authority,
        )
    if label == "review":
        return verify_review(
            ReviewManifest.model_validate(manifest),
            ReviewEvidence.model_validate(evidence),
            authority,
        )
    raise HarnessError("SELFTEST_EXTENDED_PACK_UNKNOWN")


class PackSummary(Contract):
    label: str
    expected_count: int
    observed_ids: tuple[str, ...]
    exit_code: Literal[0, 1, 2]
    reason_codes: tuple[str, ...]
    report_sha256: str
    source_digest: str
    candidate_image_digest: str
    fixture_image_digest: str
    verifier_digest: str
    runtime_profile: Literal["standalone", "full", "compact"]
    trust: Literal["local_untrusted"] = "local_untrusted"


def normalize(label: str, source: Path) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
    from scripts.selftest.product_boundary_contracts import ProductBoundaryReport
    from scripts.selftest.worker_fault_contracts import WorkerReport

    raw = read_json(source / "verification.json")
    if raw != recheck_report(label, source).model_dump(mode="json"):
        raise HarnessError("SELFTEST_EXTENDED_REPORT_CHANGED")
    if label == "compiler":
        from scripts.selftest.compile_boundary_contracts import CompileBoundaryReport

        compiler = CompileBoundaryReport.model_validate(raw)
        return compiler.exit_code, compiler.expected_keys, compiler.reason_codes
    if label == "product":
        product = ProductBoundaryReport.model_validate(raw)
        return (
            product.exit_code,
            tuple(row.key for row in product.scenarios),
            (
                *product.reason_codes,
                *(code for row in product.scenarios for code in row.reason_codes),
            ),
        )
    if label == "workers":
        report = WorkerReport.model_validate(raw)
        return (
            report.exit_code,
            report.scenario_ids,
            (
                *report.reason_codes,
                *(code for row in report.scenarios for code in row.reason_codes),
            ),
        )
    if label in {"faults", "quality", "review"}:
        configured = ConfiguredReport.model_validate(raw)
        reasons = tuple(f.code for f in configured.findings) + tuple(
            f.code for row in configured.scenarios for f in row.findings
        )
        if any(r.verification_status != "matched" for r in configured.scenarios) and not reasons:
            reasons = ("EXTENDED_SCENARIO_NOT_MATCHED",)
        return (
            configured.exit_code,
            tuple(r.scenario_id for r in configured.scenarios),
            reasons,
        )
    if label == "semantic":
        semantic = SemanticReport.model_validate(raw)
        return (
            semantic.exit_code,
            tuple(r.variant for r in semantic.scenarios),
            (
                *semantic.reason_codes,
                *(c for r in semantic.scenarios for c in r.reason_codes),
            ),
        )
    if label == "delta":
        delta = DeltaReport.model_validate(raw)
        return (
            delta.exit_code,
            tuple(r.variant for r in delta.scenarios),
            (
                *delta.findings,
                *(c for r in delta.scenarios for c in r.findings),
                *(
                    "EXTENDED_SCENARIO_NOT_MATCHED"
                    for r in delta.scenarios
                    if r.status != "matched"
                ),
            ),
        )
    if label == "control":
        control = NativeControlReport.model_validate(raw)
        return (
            control.exit_code,
            tuple(r.variant for r in control.scenarios),
            (
                *control.findings,
                *(c for r in control.scenarios for c in r.findings),
                *(
                    "EXTENDED_SCENARIO_NOT_MATCHED"
                    for r in control.scenarios
                    if r.status != "matched"
                ),
            ),
        )
    raise HarnessError("SELFTEST_EXTENDED_PACK_UNKNOWN")


def require_builds(source: Path, binding: StackBinding, *, configured: bool = False) -> None:
    if source.name == "compiler":
        from scripts.selftest.compile_boundary_contracts import CompileBoundaryManifest

        manifest = CompileBoundaryManifest.model_validate(read_json(source / "manifest.json"))
        if manifest.verifier_digest != _verifier_digest(binding.runtime_profile):
            raise HarnessError("SELFTEST_EXTENDED_BUILD_MISMATCH")
        require_build_identity(manifest.product.builds, binding)
        return
    if configured:
        observed = ProbeAuthority.model_validate(read_json(source / "authority.json")).builds
    else:
        observed = Builds.model_validate(read_json(source / "manifest.json")["builds"])
    require_build_identity(observed, binding)


def require_build_identity(observed: Builds, binding: StackBinding) -> None:
    if observed != Builds(
        runner=binding.candidate_image_digest,
        target=binding.candidate_image_digest,
        fixture=binding.fixture_image_digest.removeprefix("sha256:"),
        verifier=_verifier_digest(binding.runtime_profile),
    ):
        raise HarnessError("SELFTEST_EXTENDED_BUILD_MISMATCH")


def archive(
    label: str,
    count: int,
    source: Path,
    public: Path,
    binding: StackBinding,
    *,
    boundary: BoundaryPack | None = None,
) -> PackSummary:
    if boundary is None:
        code, ids, reasons = normalize(label, source)
        require_builds(source, binding, configured=label in {"faults", "quality", "review"})
    else:
        report = verify_boundary(boundary, read_json(source / "result.json"))
        if read_json(source / "frozen-stack.json") != {
            "binding": binding.model_dump(mode="json"),
            "verifier": _verifier_digest(binding.runtime_profile),
        }:
            raise HarnessError("SELFTEST_EXTENDED_BOUNDARY_BINDING_MISMATCH")
        code, ids, reasons = report.exit_code, report.scenario_ids, report.reason_codes
        if read_json(source / "verification.json") != report.model_dump(mode="json"):
            raise HarnessError("SELFTEST_EXTENDED_BOUNDARY_REPORT_CHANGED")
    if code != 0 or reasons or len(ids) != count or len(set(ids)) != count:
        raise HarnessError("SELFTEST_EXTENDED_PACK_INCOMPLETE")
    summary = PackSummary(
        label=label,
        expected_count=count,
        observed_ids=ids,
        exit_code=0,
        reason_codes=(),
        report_sha256=hashlib.sha256((source / "verification.json").read_bytes()).hexdigest(),
        source_digest=binding.source_digest,
        candidate_image_digest=binding.candidate_image_digest,
        fixture_image_digest=binding.fixture_image_digest,
        verifier_digest=_verifier_digest(binding.runtime_profile),
        runtime_profile=binding.runtime_profile,
    )
    public.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(public / f"{label}-identity.json", summary)
    shutil.copyfile(source / "verification.json", public / f"{label}-verification.json")
    for name in ("execution.junit.xml", "verification.junit.xml"):
        if not 0 < (source / name).stat().st_size <= 1024 * 1024:
            raise HarnessError("SELFTEST_EXTENDED_JUNIT_MISSING_OR_OVERSIZED")
        shutil.copyfile(source / name, public / f"{label}-{name}")
    write_json(
        public / f"{label}-identity-digest.json",
        {"digest": canonical_digest(summary.model_dump(mode="json"))},
    )
    return summary


def archive_bad_targets(source: Path, public: Path, binding: StackBinding) -> PackSummary:
    result = BadTargetsResult.model_validate(read_json(source / "badtargets-result.json"))
    if result.exit_code or verify_bad_targets(result):
        raise HarnessError("SELFTEST_EXTENDED_BADTARGETS_INCOMPLETE")
    require_build_identity(result.builds, binding)
    summary = PackSummary(
        label="badtargets",
        expected_count=3,
        observed_ids=SCENARIOS,
        exit_code=0,
        reason_codes=(),
        report_sha256=hashlib.sha256((source / "badtargets-result.json").read_bytes()).hexdigest(),
        source_digest=binding.source_digest,
        candidate_image_digest=binding.candidate_image_digest,
        fixture_image_digest=binding.fixture_image_digest,
        verifier_digest=_verifier_digest(binding.runtime_profile),
        runtime_profile=binding.runtime_profile,
    )
    public.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(public / "badtargets-identity.json", summary)
    write_json(public / "badtargets-verification.json", summary)
    for phase in ("positive", "fault"):
        for name in ("execution.junit.xml", "verification.junit.xml"):
            path = source / phase / name
            if not 0 < path.stat().st_size <= 1024 * 1024:
                raise HarnessError("SELFTEST_EXTENDED_JUNIT_MISSING_OR_OVERSIZED")
            shutil.copyfile(path, public / f"badtargets-{phase}-{name}")
    return summary
