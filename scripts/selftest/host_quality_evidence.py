"""Project actual native/O evidence into quality metrics; model summaries are not inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.selftest.contracts import (
    BatchEvidence,
    DigestAssertionEvidence,
    ScenarioObservation,
    canonical_digest,
)
from scripts.selftest.host_assisted_verify import assisted_metric
from scripts.selftest.host_quality import (
    HostQualityReport,
    QualityAttempt,
    QualityTaskSet,
    quality_report,
)
from scripts.selftest.host_verify import HostVerification
from scripts.selftest.io import HarnessError

if TYPE_CHECKING:
    from scripts.selftest.host_materialized import HostMaterialization


def _landed(observed: ScenarioObservation) -> tuple[str, ...] | None:
    source, execution = observed.provenance, observed.execution
    if source is None or execution is None:
        return None
    nodes = {item.node_id: item for item in execution.nodes}
    landed = []
    for binding in source.oracle_bindings:
        node = nodes.get(binding.node_id)
        if (
            node is None
            or node.phase != binding.phase
            or node.status not in {"passed", "failed"}
            or node.attempts < 1
        ):
            continue
        values = [item for item in node.assertions if item.name == binding.assertion_name]
        if len(values) != 1:
            continue
        digest = (
            values[0].expected_digest
            if isinstance(values[0], DigestAssertionEvidence)
            else canonical_digest(values[0].expected)
        )
        if digest == binding.expected_value_digest:
            landed.append(binding.oracle_id)
    return tuple(landed)


def materialized_quality(
    taskset: QualityTaskSet,
    materialized: HostMaterialization,
    evidence: BatchEvidence,
    verification: HostVerification,
) -> HostQualityReport:
    report = verification.report
    provenance = {(item.scenario_id, item.variant_key): item for item in verification.provenance}
    selected = {
        (item.task_id, item.variant_key): item
        for item in taskset.tasks
        if item.exclusion_reason is None
    }
    observed = {(item.scenario_id, item.variant_key): item for item in evidence.scenarios}
    results = {(item.scenario_id, item.variant_key): item for item in report.scenarios}
    attempts = []
    for asset in materialized.assets:
        key = (asset.scenario_id, asset.variant_key)
        if (
            key not in selected
            or key not in results
            or key not in observed
            or key not in provenance
        ):
            raise HarnessError("HOST_QUALITY_FROZEN_TASK_EVIDENCE_MISSING")
        result, actual = results[key], observed[key]
        matched = result.verification_status == "matched"
        attempts.append(
            QualityAttempt(
                task_id=key[0],
                variant_key=key[1],
                attempt_id=materialized.attempt_id,
                ordinal=1,
                generation_kind="assisted" if materialized.revisions else "model",
                review_mode=asset.workflow.proposal.review_mode,
                evidence_digest=canonical_digest(
                    {
                        "actual": actual.model_dump(mode="json"),
                        "verification": result.model_dump(mode="json"),
                    }
                ),
                protocol_available=all(
                    item.outcome == "completed" for item in materialized.trail.receipts
                ),
                design_valid=True,
                executable_asset_generated=True,
                landed_oracle_ids=_landed(actual),
                independent_execution_match=matched
                if report.evidence_integrity == "complete" and not report.findings
                else None,
                fixed_defect_detected=(
                    matched
                    and result.expected.execution_status == result.observed_status == "failed"
                )
                if selected[key].known_defect
                and report.evidence_integrity == "complete"
                and not report.findings
                else None,
                assisted=assisted_metric(
                    materialized,
                    key[0],
                    key[1],
                    matched
                    if report.evidence_integrity == "complete" and not report.findings
                    else None,
                ),
                source_complete=not report.findings
                and report.evidence_integrity == "complete"
                and not provenance[key].findings,
            )
        )
    return quality_report(taskset, tuple(attempts))
