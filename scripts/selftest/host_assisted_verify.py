"""O checks frozen before artifacts and a separately reviewed after batch independently."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import JsonValue
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Contract,
    McpCallReceipt,
    VerificationReport,
    canonical_digest,
)
from scripts.selftest.generation_lifecycle import LifecycleAsset
from scripts.selftest.host_assisted import archived_grant
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.host_materialized import HostMaterialization, HostRevision
from scripts.selftest.host_observer import verify_host_trail
from scripts.selftest.host_product_bridge import materialized_source
from scripts.selftest.host_quality import AssistedRevision
from scripts.selftest.host_runtime_config import HostRuntimeConfig
from scripts.selftest.host_verify import (
    HostProvenanceAssessment,
    HostVerification,
    _status,
    evaluate_host_batch,
)
from scripts.selftest.io import HarnessError, read_json, text_value
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.verify import _batch_verdict, verify_batch
from scripts.selftest.verify_generation_provenance import verify_generation_provenance

from app.engine.contracts import WorkflowDefinition
from app.schemas.self_tests import AgentTaskResponse, AssistedBeforeSource, AssistedLineage
from app.schemas.test_assets import PublishedTestCaseDefinition

if TYPE_CHECKING:
    from scripts.selftest.host_prompts import HostTask


class AssistedValidatedSource(Contract):
    scenario_id: str
    variant_key: str
    calls: tuple[McpCallReceipt, ...]
    workflow_id: UUID
    workflow_fingerprint: str
    case_id: UUID
    case_fingerprint: str


class AssistedValidation(Contract):
    manifest_digest: str
    sources: tuple[AssistedValidatedSource, ...]


def _delta(
    left: JsonValue, right: JsonValue, path: str = "$"
) -> tuple[tuple[str, str | None, str | None], ...]:
    """Independent digest-only diff, including unambiguous JSON bracket keys."""
    values: list[tuple[str, str | None, str | None]] = []
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            segment = (
                "." + key
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                else "[" + json.dumps(key, ensure_ascii=False) + "]"
            )
            if key in left and key in right:
                values.extend(_delta(left[key], right[key], path + segment))
            else:
                values.append(
                    (
                        path + segment,
                        canonical_digest(left[key]) if key in left else None,
                        canonical_digest(right[key]) if key in right else None,
                    )
                )
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            values.extend(_delta(a, b, f"{path}[{index}]"))
    elif canonical_digest(left) != canonical_digest(right):
        values.append((path, canonical_digest(left), canonical_digest(right)))
    if len(values) > 200:
        raise HarnessError("HOST_ASSISTED_DIFF_TOO_LARGE")
    return tuple(values)


def _document(asset: GeneratedAsset | LifecycleAsset) -> JsonValue:
    return {
        "workflow": WorkflowDefinition.model_validate(
            asset.workflow.version["definition"]
        ).model_dump(mode="json", exclude_none=True),
        "case": PublishedTestCaseDefinition.model_validate(
            asset.case.version["definition"]
        ).model_dump(mode="json", exclude_none=True),
    }


def _artifact(snapshot: AssistedBeforeSource, directory: Path, kind: str, filename: str) -> None:
    references = [item for item in snapshot.artifacts if item.kind == kind]
    path = directory / filename
    if (
        len(references) != 1
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 1048576
    ):
        raise HarnessError("HOST_ASSISTED_BEFORE_ARTIFACT_MISSING")
    if hashlib.sha256(path.read_bytes()).hexdigest() != references[0].sha256:
        raise HarnessError("HOST_ASSISTED_BEFORE_ARTIFACT_CHANGED")


def _snapshot(
    task: AgentTaskResponse, batch: UUID, scenario: str, variant: str
) -> AssistedBeforeSource:
    matches = [
        item
        for item in task.before_sources
        if (item.batch_id, item.scenario_id, item.variant_key) == (batch, scenario, variant)
    ]
    if (
        len(matches) != 1
        or matches[0].evidence_integrity != "complete"
        or matches[0].cleanup_status != "completed"
    ):
        raise HarnessError("HOST_ASSISTED_FROZEN_BEFORE_SOURCE_MISSING")
    source = matches[0]
    if source.source_digest != canonical_digest(source.source.model_dump(mode="json")):
        raise HarnessError("HOST_ASSISTED_BEFORE_SOURCE_DIGEST_CHANGED")
    return source


def validate_assisted(
    task: AgentTaskResponse,
    materialized: HostMaterialization,
    frozen_task: HostTask,
    grant: VerifiedGrant,
    config: HostRuntimeConfig,
    directory: Path,
    manifest: BatchManifest,
) -> AssistedValidation:
    request = frozen_task.assisted
    if request is None or not materialized.revisions:
        raise HarnessError("HOST_ASSISTED_AUTHORIZED_REQUEST_MISSING")
    if (
        task.frozen_manifest is None
        or task.frozen_manifest.assisted_before_batch_id != request.before_batch_id
    ):
        raise HarnessError("HOST_ASSISTED_FROZEN_BEFORE_BATCH_CHANGED")
    chosen = {(item.scenario_id, item.variant_key): item for item in request.selections}
    assets = {(item.scenario_id, item.variant_key): item for item in materialized.assets}
    if set(chosen) != set(assets):
        raise HarnessError("HOST_ASSISTED_REQUIRED_SET_CHANGED")
    for revision in materialized.revisions:
        key = (revision.scenario_id, revision.variant_key)
        lineage = revision.lineage
        if lineage.before_batch_id != request.before_batch_id:
            raise HarnessError("HOST_ASSISTED_BEFORE_BATCH_CHANGED")
        before = _snapshot(task, lineage.before_batch_id, *key)
        origin = _snapshot(task, lineage.origin_batch_id, *key)
        previous = HostMaterialization.model_validate(
            read_json(directory.parent / str(before.batch_id) / "host-materialized.json")
        )
        root = HostMaterialization.model_validate(
            read_json(directory.parent / str(origin.batch_id) / "host-materialized.json")
        )
        _validate_archived(origin, root, config, directory.parent / str(origin.batch_id))
        candidates = [
            item for item in previous.assets if (item.scenario_id, item.variant_key) == key
        ]
        if (
            len(candidates) != 1
            or canonical_digest(candidates[0].model_dump(mode="json"))
            != before.source.generation_manifest.sha256
        ):
            raise HarnessError("HOST_ASSISTED_BEFORE_ASSET_CHANGED")
        if (
            materialized_source(previous, candidates[0], before.source.generation_manifest)
            != before.source
        ):
            raise HarnessError("HOST_ASSISTED_BEFORE_SOURCE_CHANGED")
        if materialized.trail != root.trail or materialized.host != root.host:
            raise HarnessError("HOST_ASSISTED_ORIGINAL_TRAIL_CHANGED")
        _before_identity(lineage, before, root, grant)
        expected = chosen[key]
        after = assets[key]
        if (
            lineage.authorization_digest != grant.digest
            or lineage.editor_id != expected.editor_id
            or lineage.reason_digest != canonical_digest(expected.reason)
            or lineage.before_source_digest != before.source_digest
            or lineage.workflow_reviewer_id not in grant.authorization.reviewer_ids
            or lineage.case_reviewer_id not in grant.authorization.reviewer_ids
            or after.workflow.proposal.proposal_id != expected.workflow_proposal_id
            or after.case.proposal.proposal_id != expected.case_proposal_id
            or after.case.proposal.item_id != expected.case_item_id
            or lineage.review_mode != grant.authorization.review_mode
            or after.workflow.proposal.reviewer_id != lineage.workflow_reviewer_id
            or after.case.proposal.reviewer_id != lineage.case_reviewer_id
        ):
            raise HarnessError("HOST_ASSISTED_REVIEW_ACTOR_OR_REASON_CHANGED")
        _checked_changes(revision, origin, candidates[0], after)

    return AssistedValidation(
        manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
        sources=tuple(
            AssistedValidatedSource(
                scenario_id=item.scenario_id,
                variant_key=item.variant_key,
                calls=item.calls,
                workflow_id=item.workflow.proposal.materialized_resource_id,
                workflow_fingerprint=text_value(item.workflow.version["fingerprint"]),
                case_id=item.case.proposal.materialized_resource_id,
                case_fingerprint=text_value(item.case.version["fingerprint"]),
            )
            for item in materialized.assets
        ),
    )


def _before_identity(
    lineage: AssistedLineage,
    before: AssistedBeforeSource,
    root: HostMaterialization,
    grant: VerifiedGrant,
) -> None:
    if (
        root.host.model != grant.authorization.model
        or root.host.host != grant.authorization.host_id
        or root.host.skill_digest != grant.authorization.skill_digest
    ):
        raise HarnessError("HOST_ASSISTED_ORIGIN_IDENTITY_CHANGED")
    if (
        lineage.before_workflow != before.source.workflow
        or lineage.before_case != before.source.case
        or lineage.before_workflow_proposal != before.source.workflow_proposal
        or lineage.before_case_proposal != before.source.case_proposal
        or lineage.revision_number
        != 1 + (before.source.assisted.revision_number if before.source.assisted else 0)
    ):
        raise HarnessError("HOST_ASSISTED_BEFORE_LINEAGE_CHANGED")


def _checked_changes(
    revision: HostRevision,
    origin: AssistedBeforeSource,
    before: GeneratedAsset | LifecycleAsset,
    after: GeneratedAsset | LifecycleAsset,
) -> None:
    lineage = revision.lineage
    actual = _delta(_document(before), _document(after))
    frozen = tuple((item.path, item.before_digest, item.after_digest) for item in lineage.changes)
    if actual != frozen or lineage.diff_digest != canonical_digest(
        [item.model_dump(mode="json") for item in lineage.changes]
    ):
        raise HarnessError("HOST_ASSISTED_INDEPENDENT_DIFF_CHANGED")
    if revision.origin_batch_key != origin.batch_key or (
        revision.fixture_batch_key is not None and revision.fixture_batch_key != origin.batch_key
    ):
        raise HarnessError("HOST_ASSISTED_FIXTURE_NAMESPACE_CHANGED")


def _validate_archived(
    snapshot: AssistedBeforeSource,
    root: HostMaterialization,
    config: HostRuntimeConfig,
    directory: Path,
) -> None:
    for kind, filename in (
        ("manifest", "manifest.json"),
        ("evidence", "evidence.json"),
        ("verification", "verification.json"),
    ):
        _artifact(snapshot, directory, kind, filename)
    matches = [
        item
        for item in root.assets
        if (item.scenario_id, item.variant_key) == (snapshot.scenario_id, snapshot.variant_key)
    ]
    if (
        len(matches) != 1
        or canonical_digest(matches[0].model_dump(mode="json"))
        != snapshot.source.generation_manifest.sha256
    ):
        raise HarnessError("HOST_ASSISTED_ORIGIN_ASSET_CHANGED")
    asset = matches[0]
    if materialized_source(root, asset, snapshot.source.generation_manifest) != snapshot.source:
        raise HarnessError("HOST_ASSISTED_ORIGIN_SOURCE_CHANGED")
    prior = archived_grant(config, root.host.authorized_budget_digest, asset.frozen_at)
    if any(verify_host_trail(root.trail, prior, item.calls) for item in root.assets):
        raise HarnessError("HOST_ASSISTED_UNKNOWN_BEFORE_TOOL_RESULT")
    manifest = BatchManifest.model_validate(read_json(directory / "manifest.json"))
    evidence = BatchEvidence.model_validate(read_json(directory / "evidence.json"))
    report = VerificationReport.model_validate(read_json(directory / "verification.json"))
    checked = evaluate_host_batch(
        manifest, evidence, trail=root.trail, grant=prior, now=evidence.collected_at
    ).report
    if (
        checked != report
        or report.batch_verdict != snapshot.verdict
        or manifest.batch_key != snapshot.batch_key
    ):
        raise HarnessError("HOST_ASSISTED_ARCHIVED_VERIFICATION_CHANGED")


def evaluate_assisted_batch(
    manifest: BatchManifest,
    evidence: BatchEvidence,
    *,
    validated: AssistedValidation,
    now: datetime | None = None,
) -> HostVerification:
    """Call only after validate_assisted and exact current server-source comparison."""
    if validated.manifest_digest != canonical_digest(manifest.model_dump(mode="json")):
        raise HarnessError("HOST_ASSISTED_VALIDATED_MANIFEST_CHANGED")
    sources = {(item.scenario_id, item.variant_key): item for item in validated.sources}
    for entry in evidence.scenarios:
        source = entry.provenance
        frozen = sources.get((entry.scenario_id, entry.variant_key))
        if (
            frozen is None
            or source is None
            or not source.assisted
            or source.calls != frozen.calls
            or source.workflow.id != frozen.workflow_id
            or source.workflow.fingerprint != frozen.workflow_fingerprint
            or source.case.id != frozen.case_id
            or source.case.fingerprint != frozen.case_fingerprint
        ):
            raise HarnessError("HOST_ASSISTED_VALIDATED_SOURCE_CHANGED")
    base = verify_batch(manifest, evidence, now=now)
    # Only checked lineage permits preserving original generation identities and times.
    permitted = {
        "GENERATION_ASSISTED",
        "MCP_RECEIPT_BINDING_MISMATCH",
        "MCP_RECEIPT_REPLAY",
        "GENERATION_REPLAY",
        "MCP_RECEIPT_RESULT_INVALID",
    }
    actual = {item.scenario_id: item for item in evidence.scenarios}
    expected = {item.scenario_id: item for item in manifest.scenarios}
    results, assessments = [], []
    for result in base.scenarios:
        observed = actual.get(result.scenario_id)
        if observed is None:
            results.append(result)
            assessments.append(
                HostProvenanceAssessment(
                    scenario_id=result.scenario_id,
                    variant_key=result.variant_key,
                    findings=result.findings,
                )
            )
            continue
        provenance = verify_generation_provenance(manifest, expected[result.scenario_id], observed)
        kept = tuple(item for item in provenance if item.code not in permitted)
        remaining = list(result.findings)
        for finding in provenance:
            remaining.remove(finding)
        findings = (*remaining, *kept)
        assessments.append(
            HostProvenanceAssessment(
                scenario_id=result.scenario_id, variant_key=result.variant_key, findings=kept
            )
        )
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
        integrity = "missing" if statuses & {"incomplete", "unsupported", "error"} else "complete"
    return HostVerification(
        report=base.model_copy(
            update={
                "scenarios": tuple(results),
                "batch_verdict": verdict,
                "exit_code": exit_code,
                "evidence_integrity": integrity,
            }
        ),
        provenance=tuple(assessments),
    )


def assisted_metric(
    materialized: HostMaterialization, scenario: str, variant: str, matched: bool | None
) -> AssistedRevision | None:
    found = [
        item
        for item in materialized.revisions
        if (item.scenario_id, item.variant_key) == (scenario, variant)
    ]
    if not found:
        return None
    lineage = found[0].lineage
    asset = next(
        item
        for item in materialized.assets
        if (item.scenario_id, item.variant_key) == (scenario, variant)
    )
    return AssistedRevision(
        before_proposal_id=lineage.before_workflow_proposal.change_set_id,
        after_proposal_id=asset.workflow.proposal.proposal_id,
        before_fingerprint=lineage.before_workflow.fingerprint,
        after_fingerprint=text_value(asset.workflow.version["fingerprint"]),
        reviewer_id=lineage.workflow_reviewer_id,
        reason_digest=lineage.reason_digest,
        independent_execution_match=matched,
        review_mode=lineage.review_mode,
    )
