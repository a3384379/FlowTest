"""Host-only verifier extension; preserve raw failures and every ordinary source check."""

from __future__ import annotations

from datetime import datetime

from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Contract,
    Finding,
    VerificationReport,
    VerificationStatus,
)
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.host_observer import HostFrozenTrail, verify_host_generation_provenance
from scripts.selftest.verify import _batch_verdict, verify_batch
from scripts.selftest.verify_generation_provenance import verify_generation_provenance


def _status(findings: tuple[Finding, ...]) -> VerificationStatus:
    statuses = {item.status for item in findings}
    return next(
        (item for item in ("incomplete", "unsupported", "mismatched", "error") if item in statuses),
        "matched",
    )


class HostProvenanceAssessment(Contract):
    scenario_id: str
    variant_key: str
    findings: tuple[Finding, ...]


class HostVerification(Contract):
    report: VerificationReport
    provenance: tuple[HostProvenanceAssessment, ...]


def evaluate_host_batch(
    manifest: BatchManifest,
    evidence: BatchEvidence,
    *,
    trail: HostFrozenTrail,
    grant: VerifiedGrant,
    now: datetime | None = None,
) -> HostVerification:
    base = verify_batch(manifest, evidence, now=now)
    workflow_ids = {
        item.provenance.workflow_proposal.proposal_id
        for item in evidence.scenarios
        if item.provenance
    }
    case_ids = {
        item.provenance.case_proposal.proposal_id for item in evidence.scenarios if item.provenance
    }
    summaries = tuple(process.summary for process in trail.phases)
    if (
        summaries[0] is None
        or summaries[1] is None
        or set(summaries[0].proposal_ids) != workflow_ids
        or set(summaries[1].proposal_ids) != case_ids
    ):
        base = base.model_copy(
            update={
                "findings": (
                    *base.findings,
                    Finding(
                        code="HOST_PROPOSAL_SET_MISMATCH",
                        status="mismatched",
                        message="宿主全部提案与来源集合不一致",
                    ),
                )
            }
        )
    observed = {item.scenario_id: item for item in evidence.scenarios}
    expected = {item.scenario_id: item for item in manifest.scenarios}
    results = []
    assessments = []
    for result in base.scenarios:
        actual = observed.get(result.scenario_id)
        if actual is None:
            results.append(result)
            assessments.append(
                HostProvenanceAssessment(
                    scenario_id=result.scenario_id,
                    variant_key=result.variant_key,
                    findings=(
                        Finding(
                            code="HOST_PROVENANCE_OBSERVATION_MISSING",
                            status="incomplete",
                            message="独立来源观察缺失",
                        ),
                    ),
                )
            )
            continue
        extended = verify_host_generation_provenance(
            manifest, expected[result.scenario_id], actual, trail=trail, grant=grant
        )
        assessments.append(
            HostProvenanceAssessment(
                scenario_id=result.scenario_id, variant_key=result.variant_key, findings=extended
            )
        )
        # Replace provenance findings only; retain every ordinary raw-execution check.
        prior = verify_generation_provenance(manifest, expected[result.scenario_id], actual)
        remaining = list(result.findings)
        for item in prior:
            remaining.remove(item)
        findings = (*remaining, *extended)
        results.append(
            result.model_copy(
                update={"findings": findings, "verification_status": _status(findings)}
            )
        )
    statuses = {item.verification_status for item in results} | {
        item.status for item in base.findings
    }
    verdict, exit_code = _batch_verdict(statuses)
    integrity = base.evidence_integrity
    if integrity != "expired":
        integrity = "missing" if statuses & {"incomplete", "error", "unsupported"} else "complete"
    report = base.model_copy(
        update={
            "scenarios": tuple(results),
            "batch_verdict": verdict,
            "exit_code": exit_code,
            "evidence_integrity": integrity,
        }
    )

    return HostVerification(report=report, provenance=tuple(assessments))


def verify_host_batch(
    manifest: BatchManifest,
    evidence: BatchEvidence,
    *,
    trail: HostFrozenTrail,
    grant: VerifiedGrant,
    now: datetime | None = None,
) -> VerificationReport:
    return evaluate_host_batch(manifest, evidence, trail=trail, grant=grant, now=now).report
