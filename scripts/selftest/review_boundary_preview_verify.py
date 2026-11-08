"""Independent Preview purpose, one-use, exact budget and cleanup journal oracle."""

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import JsonObject, object_value, objects_value
from scripts.selftest.mcp_governance_verify import Finding, failure
from scripts.selftest.review_boundary_contracts import (
    ReviewManifest,
    ReviewObservation,
    ReviewScenario,
    ReviewSource,
)


def verify_preview(
    manifest: ReviewManifest, source: ReviewSource, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[Finding, ...]:
    execution, approval, journal = row.preview, row.preview_approval, row.journal
    if execution is None or approval is None or journal is None or len(row.tool_results) != 1:
        return (failure("REVIEW_PREVIEW_REQUIRED_EVIDENCE_MISSING", True),)
    if (
        execution.project_id,
        execution.environment_id,
        execution.run_purpose,
        execution.source_case_id,
        execution.source_plan_run_item_id,
        execution.workflow_id,
        execution.workflow_version_id,
        execution.status,
        execution.cleanup_status,
    ) != (
        manifest.scope.project_id,
        manifest.scope.fixture_environment_id,
        "preview",
        None,
        None,
        None,
        None,
        "cancelled",
        "passed",
    ):
        return (failure("REVIEW_PREVIEW_PURPOSE_TARGET_OR_CLEANUP_MISMATCH"),)
    if row.preview_execution_ids != (execution.execution_id, execution.execution_id):
        return (failure("REVIEW_PREVIEW_IDEMPOTENT_ID_MISMATCH"),)
    if (
        not execution.bindings_complete
        or execution.truncated
        or execution.node_total != len(execution.nodes)
        or execution.children_total
        or not execution.children_complete
        or execution.nested_node_total
        or not execution.nested_nodes_complete
    ):
        return (failure("REVIEW_PREVIEW_PROJECTION_INCOMPLETE", True),)
    cleanup = [node for node in execution.nodes if node.phase == "cleanup"]
    if len(cleanup) != 1 or (
        cleanup[0].node_id,
        cleanup[0].node_type,
        cleanup[0].status,
        cleanup[0].attempts,
    ) != ("cleanup_after_cancel", "api", "passed", 1):
        return (failure("REVIEW_PREVIEW_CLEANUP_NODE_MISMATCH"),)
    if not _approval_binding(manifest, source, row):
        return (failure("REVIEW_PREVIEW_APPROVAL_BINDING_MISMATCH"),)
    expected_budget = {
        "max_nodes": 10,
        "max_requests": 2,
        "max_dataset_rows": 1,
        "max_parallelism": 1,
        "max_runtime_seconds": 30,
    }
    if approval.budget.model_dump() != expected_budget:
        return (failure("REVIEW_PREVIEW_BUDGET_CHANGED"),)
    denied = row.tool_results[0]
    if (
        denied.is_error is not False
        or denied.business_code != "PREVIEW_APPROVAL_REPLAYED"
        or not denied.trace_present
        or denied.result_digest != row.calls[3].result_digest
    ):
        return (failure("REVIEW_PREVIEW_SINGLE_USE_DENIAL_MISMATCH"),)
    return (*_target_journal(manifest, source, scenario, row), *_requests(manifest, scenario, row))


def _approval_binding(
    manifest: ReviewManifest, source: ReviewSource, row: ReviewObservation
) -> bool:
    approval, execution = row.preview_approval, row.preview
    if approval is None or execution is None:
        return False
    return (
        approval.id == row.approval_id
        and approval.project_id == manifest.scope.project_id
        and approval.change_set_id == row.proposal_id
        and approval.environment_id == manifest.scope.fixture_environment_id
        and approval.executor_id == manifest.writer_machine_id
        and approval.executor_kind == "service_account"
        and str(approval.context_revision_id) == source.context["context_revision_id"]
        and approval.context_fingerprint == source.context["context_fingerprint"]
        and approval.proposal_fingerprint == execution.workflow_fingerprint
        and approval.proposal_fingerprint == row.proposal_result.get("flow_spec_fingerprint")
    )


def _requests(
    manifest: ReviewManifest, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[Finding, ...]:
    base = manifest.batch_key + "-" + scenario.transport
    arguments: JsonObject = {
        "project_id": str(manifest.scope.project_id),
        "change_set_id": str(row.proposal_id),
        "environment_id": str(manifest.scope.fixture_environment_id),
        "approval_id": str(row.approval_id),
        "idempotency_key": base + ":preview-once",
    }
    required = (
        canonical_digest(arguments),
        canonical_digest(arguments),
        canonical_digest({**arguments, "idempotency_key": base + ":preview-reuse"}),
        canonical_digest(
            {
                "request": {
                    "project_id": str(manifest.scope.project_id),
                    "execution_id": str(row.preview_execution_ids[0]),
                }
            }
        ),
    )
    if tuple(call.request_digest for call in row.calls[1:]) != required:
        return (failure("REVIEW_PREVIEW_REQUEST_SCOPE_OR_IDEMPOTENCY_CHANGED"),)
    return ()


def _target_journal(
    manifest: ReviewManifest, source: ReviewSource, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[Finding, ...]:
    journal = row.journal
    if journal is None:
        return (failure("REVIEW_PREVIEW_JOURNAL_MISSING", True),)
    if (
        journal.batch_key,
        journal.scenario_id,
        journal.nonce,
        journal.fixture_epoch,
        journal.request_count,
        len(journal.entries),
        journal.truncated,
        journal.expired,
        journal.epoch_changed,
    ) != (
        manifest.batch_key + "-" + scenario.transport,
        "ST-MCP-022-" + scenario.transport,
        manifest.nonce,
        source.fixture_epoch,
        1,
        1,
        False,
        False,
        False,
    ):
        return (failure("REVIEW_PREVIEW_TARGET_JOURNAL_MISMATCH"),)
    request = journal.entries[0]
    path = object_value(objects_value(source.spec["operations"])[0])["path"]
    if (
        request.sequence,
        request.method,
        request.path,
        request.response_status,
        request.authorization_present,
        request.cookie_present,
        request.fixture_epoch,
    ) != (1, "GET", path, 200, False, False, source.fixture_epoch):
        return (failure("REVIEW_PREVIEW_CLEANUP_REQUEST_MISMATCH"),)
    return ()
