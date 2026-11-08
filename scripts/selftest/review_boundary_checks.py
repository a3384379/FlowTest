"""Independent review/Preview rules from frozen public contracts and scoped metadata."""

from datetime import datetime

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, object_value, objects_value
from scripts.selftest.mcp_governance_verify import Finding, failure
from scripts.selftest.mcp_probe_contracts import ProbeAuthority, ProbeResource
from scripts.selftest.mcp_probe_reader import validate_snapshot
from scripts.selftest.review_boundary_contracts import (
    ReviewManifest,
    ReviewObservation,
    ReviewScenario,
    ReviewSource,
)


def snapshots(
    manifest: ReviewManifest,
    scenario: ReviewScenario,
    row: ReviewObservation,
    authority: ProbeAuthority,
    now: datetime,
) -> tuple[Finding, ...]:
    captured = (row.before, row.after) + ((row.checkpoint,) if row.checkpoint else ())
    for snapshot in captured:
        try:
            validate_snapshot(authority, snapshot, now=now)
        except HarnessError:
            return (failure("REVIEW_SCOPED_INVENTORY_INCOMPLETE", True),)
        if any(
            not row.started_at <= page.observed_at <= row.completed_at for page in snapshot.pages
        ):
            return (failure("REVIEW_SNAPSHOT_TIME_MISMATCH"),)
        if any(
            r.kind in {"test_plan", "test_plan_run", "test_case_version"}
            for r in snapshot.resources
        ):
            return (failure("REVIEW_UNEXPECTED_FORMAL_RUN_OR_PUBLICATION"),)
    before = {(r.kind, str(r.id)): r for r in row.before.resources}
    after = {(r.kind, str(r.id)): r for r in row.after.resources}
    additions = {key for key in after if key not in before}
    expected = {
        "preview_cancel": {"ai_change_set": 1, "workflow_execution": 1},
        "unknown_publish": {"workflow": 1, "workflow_version": 1},
        "stale_proposal": {"ai_change_set": 1},
        "stale_approval": {"ai_change_set": 1, "change_set_approval": 1, "test_design": 1},
        "concurrent_accept": {"ai_change_set": 1, "test_design": 1},
        "partial_resume": {"ai_change_set": 1, "test_design": 1, "test_case": 2},
    }[scenario.action]
    counts = {
        kind: sum(key[0] == kind for key in additions) for kind in {key[0] for key in additions}
    }
    if counts != expected or not set(before) <= set(after):
        return (failure("REVIEW_EXACT_RESOURCE_DELTA_MISMATCH"),)
    allowed_changes = (
        {("ai_change_set", str(row.proposal_id))}
        if scenario.action == "unknown_publish"
        else {("workflow", str(row.workflow_id))}
        if scenario.action == "stale_proposal"
        else set()
    )
    if any(key not in allowed_changes and after.get(key) != value for key, value in before.items()):
        return (failure("REVIEW_UNRELATED_RESOURCE_CHANGED"),)
    proposal = [
        r for r in row.after.resources if r.kind == "ai_change_set" and r.id == row.proposal_id
    ]
    if len(proposal) != 1 or proposal[0].project_id != manifest.scope.project_id:
        return (failure("REVIEW_PROPOSAL_IDENTITY_MISMATCH"),)
    if any(
        r.project_id != manifest.scope.project_id for key, r in after.items() if key in additions
    ):
        return (failure("REVIEW_CROSS_PROJECT_SIDE_EFFECT"),)
    return _items(manifest, scenario, row, proposal[0])


def _items(
    manifest: ReviewManifest,
    scenario: ReviewScenario,
    row: ReviewObservation,
    proposal: ProbeResource,
) -> tuple[Finding, ...]:
    items = proposal.items
    if proposal.status != "accepted" or len(items) != (
        3 if scenario.action == "partial_resume" else 1
    ):
        return (failure("REVIEW_PROPOSAL_FINAL_STATE_MISMATCH"),)
    if any(
        i.review_status != "accepted" or i.reviewed_by_id != manifest.reviewer_id for i in items
    ):
        return (failure("REVIEW_INDEPENDENT_REVIEWER_OR_ITEM_STATE_MISMATCH"),)
    if scenario.action in {"preview_cancel", "stale_proposal"}:
        if any(i.materialized_resource_id is not None for i in items):
            return (failure("REVIEW_UNEXPECTED_APPLY"),)
    else:
        materialization = _materialized(manifest, row, proposal)
        if materialization:
            return materialization
    if scenario.action == "stale_approval":
        approvals = [
            r
            for r in row.after.resources
            if r.kind == "change_set_approval" and r.parent_id == proposal.id
        ]
        if (
            len(approvals) != 1
            or approvals[0].id != row.approval_id
            or approvals[0].reviewed_by_id != manifest.reviewer_id
        ):
            return (failure("REVIEW_STALE_APPROVAL_BINDING_MISMATCH"),)
        expected = canonical_digest(
            object_value(objects_value(row.proposal_result["items"])[0]["proposed_content"])
        )
        if (
            items[0].proposed_document_digest != expected
            or items[0].design is None
            or items[0].design.document_digest != expected
        ):
            return (failure("REVIEW_APPROVED_CONTENT_CHANGED"),)
    if scenario.action == "partial_resume":
        return _partial(row)
    return ()


def _partial(row: ReviewObservation) -> tuple[Finding, ...]:
    if row.checkpoint is None:
        return (failure("REVIEW_PARTIAL_CHECKPOINT_MISSING", True),)
    selected = [
        r for r in row.checkpoint.resources if r.kind == "ai_change_set" and r.id == row.proposal_id
    ]
    if len(selected) != 1 or selected[0].status != "partially_reviewed":
        return (failure("REVIEW_PARTIAL_STATE_MISMATCH"),)
    if sorted(i.review_status for i in selected[0].items) != ["accepted", "accepted", "pending"]:
        return (failure("REVIEW_PARTIAL_ITEM_SET_MISMATCH"),)
    final = next(
        r for r in row.after.resources if r.id == row.proposal_id and r.kind == "ai_change_set"
    )
    old = {i.id: i for i in selected[0].items}
    if any(old[i.id].review_status == "accepted" and old[i.id] != i for i in final.items):
        return (failure("REVIEW_PARTIAL_REPLAYED_OR_REPLACED"),)
    return ()


def receipts(
    manifest: ReviewManifest, source: ReviewSource, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[Finding, ...]:
    names = {
        "preview_cancel": (
            "propose_flow_draft",
            "preview_flow_proposal",
            "preview_flow_proposal",
            "preview_flow_proposal",
            "cancel_preview",
        ),
        "unknown_publish": ("inspect_flow",),
        "stale_proposal": ("propose_flow_draft", "inspect_flow"),
        "stale_approval": ("propose_test_design",),
        "concurrent_accept": ("propose_test_design",),
        "partial_resume": ("propose_test_design",),
    }[scenario.action]
    if tuple(c.tool_name for c in row.calls) != tuple("flowtest." + name for name in names):
        return (failure("REVIEW_EXACT_SDK_CALL_SET_MISMATCH"),)
    wanted = (
        (True, True, True, False, True)
        if scenario.action == "preview_cancel"
        else (True,) * len(names)
    )
    if tuple(c.success for c in row.calls) != wanted:
        return (failure("REVIEW_SDK_RAW_OUTCOME_MISMATCH"),)
    if any(
        c.batch_key != manifest.batch_key + "-" + scenario.transport
        or c.scenario_id != scenario.scenario_id
        or c.transport != scenario.transport
        or c.sdk_version != "2.2.0"
        or c.protocol_version != "2026-07-28"
        or not row.started_at <= c.completed_at <= row.completed_at
        for c in row.calls
    ):
        return (failure("REVIEW_SDK_RECEIPT_IDENTITY_MISMATCH"),)
    if scenario.action != "unknown_publish" and (
        row.calls[0].request_digest != canonical_digest(row.proposal_arguments)
        or row.calls[0].result_digest != canonical_digest(row.proposal_envelope)
    ):
        return (failure("REVIEW_PROPOSAL_RECEIPT_BINDING_MISMATCH"),)
    raw_result = object_value(row.proposal_envelope.get("data", row.proposal_envelope))
    if (
        raw_result != row.proposal_result
        or row.proposal_arguments.get("project_id") != str(manifest.scope.project_id)
        or row.proposal_arguments.get("dry_run") is not False
    ):
        return (failure("REVIEW_PROPOSAL_RAW_SOURCE_MISMATCH"),)
    if scenario.action in {"preview_cancel", "unknown_publish", "stale_proposal"} and (
        row.proposal_arguments.get("spec") != source.spec
        or row.proposal_arguments.get("context_revision_id")
        != source.context["context_revision_id"]
    ):
        return (failure("REVIEW_FLOW_SOURCE_CHANGED"),)
    if scenario.action in {"unknown_publish", "stale_proposal"}:
        return _readback(manifest, scenario, row)
    return ()


def _readback(
    manifest: ReviewManifest, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[Finding, ...]:
    envelope = row.workflow_read_envelope
    if envelope is None or row.calls[-1].result_digest != canonical_digest(envelope):
        return (failure("REVIEW_READBACK_RECEIPT_MISSING", True),)
    data = object_value(envelope.get("data", envelope))
    expected_revision = 2 if scenario.action == "stale_proposal" else 1
    if (
        data.get("id"),
        data.get("project_id"),
        data.get("current_version"),
        data.get("draft_revision"),
    ) != (str(row.workflow_id), str(manifest.scope.project_id), 1, expected_revision):
        return (failure("REVIEW_EXACT_PUBLICATION_OR_DRAFT_MISMATCH"),)
    if (
        scenario.action == "stale_proposal"
        and data.get("name") != manifest.batch_key + "-" + scenario.transport + ":human-edit"
    ):
        return (failure("REVIEW_HUMAN_EDIT_OVERWRITTEN"),)
    return ()


def http_outcomes(scenario: ReviewScenario, row: ReviewObservation) -> tuple[Finding, ...]:
    expected = {
        "preview_cancel": (
            ("unreviewed_preview_denied", 409, "PREVIEW_REVIEW_REQUIRED"),
            ("review_preview", 200, None),
            ("production_preview_denied", 403, "PRODUCTION_PREVIEW_FORBIDDEN"),
            ("preview_approval", 201, None),
        ),
        "unknown_publish": (
            ("apply", 200, None),
            ("publish_unknown", 200, None),
            ("publish_readback", 200, None),
        ),
        "stale_proposal": (
            ("review_update", 200, None),
            ("manual_edit", 200, None),
            ("stale_apply", 409, "FLOWSPEC_TARGET_CONFLICT"),
        ),
        "stale_approval": (
            ("approve_high", 200, None),
            ("changed_content_denied", 409, "MCP_APPROVAL_CONTENT_CHANGED"),
            ("original_accepted", 200, None),
        ),
        "concurrent_accept": (
            ("concurrent_accept", 200, None),
            ("concurrent_accept", 409, "MCP_CHANGE_ITEM_ALREADY_REVIEWED"),
        ),
        "partial_resume": (
            ("partial_accept", 200, None),
            ("partial_accept", 200, None),
            ("resume_readback", 200, None),
            ("resume_accept", 200, None),
            ("reaccept_denied", 409, "MCP_CHANGE_ITEM_ALREADY_REVIEWED"),
        ),
    }[scenario.action]
    actual = tuple((r.step, r.status, r.code) for r in row.http)
    if scenario.action == "concurrent_accept":
        actual = tuple(sorted(actual, key=lambda r: r[1]))
    if actual != expected or any(r.status >= 400 and not r.trace_present for r in row.http):
        return (failure("REVIEW_EXACT_HTTP_OUTCOME_MISMATCH"),)
    if len({r.id for r in row.http}) != len(row.http) or any(
        not row.started_at <= r.started_at <= r.completed_at <= row.completed_at for r in row.http
    ):
        return (failure("REVIEW_HTTP_RECEIPT_TIME_OR_ID_MISMATCH"),)
    lost = [r for r in row.http if r.outcome == "lost_response_body"]
    if scenario.action == "unknown_publish":
        if (
            len(lost) != 1
            or lost[0].step != "publish_unknown"
            or lost[0].response_digest is not None
        ):
            return (failure("REVIEW_UNKNOWN_MUTATION_WAS_REPLAYED_OR_NOT_LOST"),)
    elif lost:
        return (failure("REVIEW_UNEXPECTED_MUTATION_LOSS"),)
    return ()


def _materialized(
    manifest: ReviewManifest, row: ReviewObservation, proposal: ProbeResource
) -> tuple[Finding, ...]:
    for item in proposal.items:
        saved = [
            r
            for r in row.after.resources
            if r.id == item.materialized_resource_id and r.kind == item.materialized_resource_type
        ]
        if len(saved) != 1 or saved[0].created_by_id != manifest.reviewer_id:
            return (failure("REVIEW_MATERIALIZATION_SOURCE_MISMATCH"),)
        if item.item_type == "test_design" and saved[0].source_change_set_id != proposal.id:
            return (failure("REVIEW_DESIGN_SOURCE_MISMATCH"),)
    return ()
