"""Independent finite product checks; original failed native executions remain failed."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.fixed_baseline import load_core_pack
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import ROOT
from scripts.selftest.product_boundary_contracts import (
    ProductBatchSnapshot,
    ProductBoundaryEvidence,
    ProductBoundaryManifest,
    ProductBoundaryObservation,
    ProductBoundaryPack,
    ProductBoundaryReport,
    ProductBoundaryRowReport,
    ProductBoundarySpec,
    ProductNativeProof,
)
from scripts.selftest.verify import verify_batch


def load_pack() -> ProductBoundaryPack:
    pack = ProductBoundaryPack.model_validate(
        read_json(ROOT / "selftest/packs/product-boundaries-v1/pack.json")
    )
    if len({row.key for row in pack.scenarios}) != len(pack.scenarios):
        raise HarnessError("PRODUCT_BOUNDARY_PACK_DUPLICATE")
    return pack


def healthy(batch: ProductBatchSnapshot) -> bool:
    return bool(
        (
            batch.phase,
            batch.verdict,
            batch.sealed_verdict,
            batch.evidence_integrity,
            batch.cleanup_status,
        )
        == ("completed", "passed", "passed", "complete", "completed")
        and len(batch.expected_scenario_ids) == len(set(batch.expected_scenario_ids)) == 8
        and set(batch.expected_scenario_ids) == set(batch.actual_scenario_ids)
        and len(batch.actual_scenario_ids) == len(batch.verification_statuses) == 8
        and set(batch.verification_statuses) == {"matched"}
        and batch.observed_statuses.count("failed") == 2
        and batch.observed_statuses.count("passed") == 6
        and len(batch.plan_run_ids) == 1
        and len(set(batch.execution_ids)) == 8
        and batch.sealed_at is not None
        and len(batch.artifact_ids) == 5
    )


def _requests(spec: ProductBoundarySpec, row: ProductBoundaryObservation) -> bool:
    return len(spec.requests) == len(row.requests) and all(
        (expected.operation, expected.status, expected.code)
        == (actual.operation, actual.status, actual.code)
        and (actual.status < 400 or actual.trace_id is not None)
        for expected, actual in zip(spec.requests, row.requests, strict=True)
    )


def _installation(row: ProductBoundaryObservation) -> bool:
    before, after = row.before, row.after
    if before is None or after is None or not before.complete or not after.complete:
        return False
    if row.key == "same_key_reinstall":
        return (
            before == after
            and len(row.installation_ids) == len(row.mapping_digests) == 2
            and len(set(row.installation_ids)) == len(set(row.mapping_digests)) == 1
        )
    return bool(
        not any(
            (
                before.api_ids,
                before.workflow_ids,
                before.case_ids,
                before.run_ids,
                before.execution_ids,
            )
        )
        and len(after.api_ids) == len(after.workflow_ids) == len(after.case_ids) == 8
        and len(after.plan_ids) == len(after.suite_ids) == 1
        and not after.run_ids
        and not after.execution_ids
        and len(row.installation_ids) == len(row.mapping_digests) == 1
    )


def _new_run(row: ProductBoundaryObservation) -> bool:
    if len(row.batches) != 2 or not all(healthy(batch) for batch in row.batches):
        return False
    first, second = row.batches
    return bool(
        first.id != second.id
        and first.installation_id == second.installation_id
        and first.project_id == second.project_id
        and first.manifest_digest != second.manifest_digest
        and not set(first.plan_run_ids) & set(second.plan_run_ids)
        and not set(first.execution_ids) & set(second.execution_ids)
    )


def _projection(row: ProductBoundaryObservation) -> bool:
    if row.key == "readonly_scope":
        expected = {
            "run_id",
            "project_id",
            "test_plan_id",
            "status",
            "trigger_type",
            "completed_at",
            "items",
            "total",
            "page",
            "page_size",
            "has_more",
            "truncated",
        }
        return set(row.safe_fields) == expected
    if row.key == "pagination":
        return len(row.listed_ids) == len(set(row.listed_ids)) == row.listed_total == 8
    if row.key == "seal_idempotent":
        return (
            len(row.batches) == 2 and healthy(row.batches[0]) and row.batches[0] == row.batches[1]
        )
    if row.key == "a_b_isolation":
        return bool(
            row.before
            and row.after
            and row.before.complete
            and row.after.complete
            and row.before.project_id != row.after.project_id
            and row.before.run_ids
            and not row.after.run_ids
            and not row.after.execution_ids
            and not row.after.api_ids
        )
    return False


def _cleanup(row: ProductBoundaryObservation) -> bool:
    if len(row.batches) != 1 or row.namespace_statuses != (404,) * 8:
        return False
    batch = row.batches[0]
    if row.key == "success_failure_cleanup":
        return healthy(batch)
    return batch.phase == "cancelled" and batch.verdict == "blocked" and not batch.plan_run_ids


def _retention(manifest: ProductBoundaryManifest, row: ProductBoundaryObservation) -> bool:
    if (
        row.before is None
        or row.after is None
        or len(row.batches) != 2
        or len(row.maintenance) != 2
    ):
        return False
    original, current = row.batches
    first, second = row.maintenance
    return bool(
        healthy(original)
        and original.id == current.id
        and current.sealed_verdict == "passed"
        and (current.verdict, current.evidence_integrity) == ("blocked", "expired")
        and current.actual_scenario_ids == original.actual_scenario_ids
        and current.execution_ids == original.execution_ids
        and row.object_statuses == (404,) * 5
        and not row.after.run_ids
        and not row.after.execution_ids
        and row.before.workflow_ids == row.after.workflow_ids
        and row.before.case_ids == row.after.case_ids
        and first.container_id == second.container_id == manifest.disposal.target_container_id
        and first.ownership_nonce == second.ownership_nonce == manifest.ownership_nonce
        and first.clock == second.clock
        and first.clock > row.observed_at
        and not first.repeat
        and second.repeat
        and first.workflow_executions_deleted >= 16
        and first.test_plan_runs_deleted >= 2
        and first.artifacts_deleted >= 10
        and first.storage_failures == second.storage_failures == 0
        and second.workflow_executions_deleted
        == second.test_plan_runs_deleted
        == second.artifacts_deleted
        == 0
    )


def _refusal(row: ProductBoundaryObservation) -> bool:
    if row.before is not None and (row.before != row.after or not row.before.complete):
        return False
    if row.key == "recursive_target":
        return "SELFTEST_RECURSION_LIMIT_REACHED" in row.safe_fields and row.before is not None
    if row.key in {"wrong_target", "environment_drift"}:
        return row.safe_fields == ("preview_blocked", "SELFTEST_ENVIRONMENT_MAPPING_INVALID")
    if row.key == "cross_run":
        return len(row.listed_ids) == len(set(row.listed_ids)) == 2
    if row.key == "nonce_expiry":
        return bool(
            len(row.batches) == 1
            and row.batches[0].phase == "expired"
            and row.batches[0].verdict == "blocked"
            and not row.batches[0].plan_run_ids
            and not row.batches[0].execution_ids
            and row.namespace_statuses == (404,) * 8
        )
    if row.key.startswith("seal_"):
        return (
            len(row.batches) == 2 and healthy(row.batches[0]) and row.batches[0] == row.batches[1]
        )
    return True


def _row(
    manifest: ProductBoundaryManifest, spec: ProductBoundarySpec, row: ProductBoundaryObservation
) -> tuple[str, ...]:
    reasons = []
    if not _requests(spec, row):
        reasons.append("PRODUCT_BOUNDARY_HTTP_CONTRACT_MISMATCH")
    if not manifest.created_at <= row.observed_at <= manifest.deadline:
        reasons.append("PRODUCT_BOUNDARY_OBSERVATION_OUTSIDE_WINDOW")
    if spec.group == "installation":
        valid = _installation(row)
    elif spec.group == "new_run":
        valid = _new_run(row)
    elif spec.group == "projection":
        valid = _projection(row)
    elif spec.group == "cleanup":
        valid = _cleanup(row)
    elif spec.group == "retention":
        valid = _retention(manifest, row)
    else:
        valid = _refusal(row)
    return tuple(reasons) + (() if valid else ("PRODUCT_BOUNDARY_INDEPENDENT_FACTS_MISMATCH",))


def verify(
    manifest: ProductBoundaryManifest, evidence: ProductBoundaryEvidence
) -> ProductBoundaryReport:
    pack = load_pack()
    reasons = []
    digest = canonical_digest(manifest.model_dump(mode="json"))
    keys = tuple(row.key for row in pack.scenarios)
    if (
        manifest.pack_digest != canonical_digest(pack.model_dump(mode="json"))
        or evidence.manifest_digest != digest
    ):
        reasons.append("PRODUCT_BOUNDARY_FROZEN_SOURCE_CHANGED")
    if manifest.expected_keys != keys or tuple(row.key for row in evidence.observations) != keys:
        reasons.append("PRODUCT_BOUNDARY_REQUIRED_SET_MISSING_OR_DUPLICATED")
    if (
        not manifest.created_at < evidence.collected_at <= manifest.deadline
        or manifest.deadline - manifest.created_at > timedelta(seconds=600)
        or evidence.rejected_attempts
        or evidence.http_attempts > 500
    ):
        reasons.append("PRODUCT_BOUNDARY_BUDGET_OR_WINDOW_CHANGED")
    reasons.extend(_native(manifest, evidence))
    if evidence.disposal is None:
        reasons.append("OWNED_ASSET_DISPOSAL_PENDING")
    elif (
        evidence.disposal.model_dump(
            exclude={"removed_at", "containers_absent", "volumes_absent", "networks_absent"}
        )
        != manifest.disposal.model_dump()
        or not evidence.disposal.containers_absent
        or not evidence.disposal.volumes_absent
        or not evidence.disposal.networks_absent
        or not evidence.collected_at <= evidence.disposal.removed_at <= manifest.deadline
    ):
        reasons.append("PRODUCT_BOUNDARY_DISPOSAL_CHANGED")
    observations = {row.key: row for row in evidence.observations}
    rows = tuple(
        ProductBoundaryRowReport(
            key=spec.key,
            reason_codes=_row(manifest, spec, observations[spec.key])
            if spec.key in observations
            else ("PRODUCT_BOUNDARY_NOT_RUN",),
        )
        for spec in pack.scenarios
    )
    return ProductBoundaryReport(
        pack_digest=manifest.pack_digest,
        manifest_digest=digest,
        expected_keys=keys,
        scenarios=rows,
        exit_code=2 if reasons or any(row.reason_codes for row in rows) else 0,
        reason_codes=tuple(reasons),
    )


def _native(
    manifest: ProductBoundaryManifest, evidence: ProductBoundaryEvidence
) -> tuple[str, ...]:
    if len(evidence.native) != 2 or len({row.manifest.batch_key for row in evidence.native}) != 2:
        return ("PRODUCT_BOUNDARY_NATIVE_BATCH_SET_INCOMPLETE",)
    snapshots = next((row.batches for row in evidence.observations if row.key == "new_run"), ())
    if len(snapshots) != 2:
        return ("PRODUCT_BOUNDARY_NATIVE_LINKS_MISSING",)
    for native in evidence.native:
        report = verify_batch(native.manifest, native.evidence, now=native.evidence.collected_at)
        if (
            report.exit_code
            or native.manifest.project_id != manifest.project_id
            or native.manifest.builds != manifest.builds
            or len(report.scenarios) != 8
            or native.manifest.pack_id != "core-v1"
            or native.manifest.pack_digest != load_core_pack().digest
            or not _native_linked(native, snapshots)
        ):
            return ("PRODUCT_BOUNDARY_NATIVE_PROOF_NOT_MATCHED",)
    return ()


def _native_linked(native: ProductNativeProof, snapshots: tuple[ProductBatchSnapshot, ...]) -> bool:
    snapshot = next(
        (row for row in snapshots if "selftest-" + row.id.hex == native.manifest.batch_key), None
    )
    if snapshot is None:
        return False
    actual = tuple(
        row.execution.id for row in native.evidence.scenarios if row.execution is not None
    )
    return (
        set(actual) == set(snapshot.execution_ids)
        and len(actual) == len(snapshot.execution_ids) == 8
    )


def write_reports(report: ProductBoundaryReport, output: Path) -> None:
    write_json(output / "verification.json", report)
    suite = Element("testsuite", name="product-boundaries", tests=str(len(report.scenarios)))
    for row in report.scenarios:
        case = SubElement(suite, "testcase", name=row.key)
        if row.reason_codes or report.reason_codes:
            SubElement(case, "failure").text = ",".join((*report.reason_codes, *row.reason_codes))
    suite.set("failures", str(sum(row.find("failure") is not None for row in suite)))
    (output / "verification.junit.xml").write_bytes(
        tostring(suite, encoding="utf-8", xml_declaration=True)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立核验真实产品边界及原生固定批次; 不授予CI信任")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(
        ProductBoundaryManifest.model_validate(read_json(args.output / "manifest.json")),
        ProductBoundaryEvidence.model_validate(read_json(args.output / "evidence.json")),
    )
    write_reports(result, args.output)
    raise SystemExit(result.exit_code)
