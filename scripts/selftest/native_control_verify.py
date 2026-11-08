"""Independent frozen native-control rubric; no product schema or H credential import."""

import argparse
import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import JsonValue
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    objects_value,
    read_json,
    write_json,
)
from scripts.selftest.native_control_contracts import (
    ControlVariant,
    NativeControlCheck,
    NativeControlEvidence,
    NativeControlFreeze,
    NativeControlManifest,
    NativeControlPack,
    NativeControlReport,
)

# Literal pre-execution pack identity; never derive a golden from an observed Run.
PACK_DIGEST = "4b2a7512e528ede036f9c8b5ad0774f684eb94f6fd328b9481ecd2bcc0171541"
INCOMPLETE = frozenset(
    {
        "OWNED_ASSET_DISPOSAL_PENDING",
        "NATIVE_CONTROL_EVIDENCE_MISSING",
        "NATIVE_CONTROL_CLEANUP_INCOMPLETE",
        "NATIVE_CONTROL_BATCH_EXPIRED",
        "NATIVE_CONTROL_HARNESS_FAILED",
    }
)


def load_pack(path: Path) -> NativeControlPack:
    pack = NativeControlPack.model_validate(read_json(path))
    if canonical_digest(pack.model_dump(mode="json")) != PACK_DIGEST:
        raise HarnessError("NATIVE_CONTROL_PACK_CHANGED")
    if tuple(pack.variants) != get_args(ControlVariant):
        raise HarnessError("NATIVE_CONTROL_DENOMINATOR_CHANGED")
    return pack


def proposal_definition(definition: JsonObject) -> JsonObject:
    """Only declared structural optionals use exclude_none; JSON literal values stay exact."""
    result = copy.deepcopy(definition)
    graphs = [result, *objects_value(result.get("regions", []))]
    for graph in graphs:
        for node in objects_value(graph["nodes"]):
            for key in ("capability_id", "capability_version", "configuration", "bindings"):
                if node.get(key) is None:
                    node.pop(key, None)
        for edge in objects_value(graph["edges"]):
            if edge.get("condition") is None:
                edge.pop("condition", None)
    return result


def _pending_item(pending: JsonObject) -> JsonObject:
    items = objects_value(pending["items"])
    if len(items) != 1:
        raise HarnessError("NATIVE_CONTROL_PROPOSAL_ITEM_SET_CHANGED")
    return items[0]


def check_pending(
    frozen: NativeControlManifest,
    pack: NativeControlPack,
    request: JsonObject,
    proposal: JsonObject,
    replay: JsonObject,
    pending: JsonObject,
) -> list[str]:
    expected: JsonObject = {
        "project_id": str(frozen.project_id),
        "name": frozen.batch_key,
        "description": "隔离自测; 独立审核模式 ci_fixture; 不代表模型或真人验收",
        "definition": pack.definition,
    }
    if request != {"request": expected, "idempotency_key": frozen.batch_key + ":proposal"}:
        return ["NATIVE_CONTROL_REQUEST_CHANGED"]
    item = _pending_item(pending)
    content = {
        "name": frozen.batch_key,
        "description": expected["description"],
        "definition": proposal_definition(pack.definition),
    }
    fingerprint = canonical_digest(content)
    if (
        canonical_digest(item["proposed_content"]),
        pending.get("source_fingerprint"),
        proposal.get("proposed_fingerprint"),
    ) != (fingerprint,) * 3:
        return ["NATIVE_CONTROL_PROPOSED_CONTENT_CHANGED"]
    if (
        pending.get("project_id"),
        pending.get("status"),
        pending.get("source_type"),
        pending.get("actor_type"),
        pending.get("created_by_id"),
        pending.get("source_ref"),
    ) != (
        str(frozen.project_id),
        "draft",
        "mcp",
        "service_account",
        str(frozen.mcp_actor_id),
        f"mcp://projects/{frozen.project_id}/control-workflows",
    ):
        return ["NATIVE_CONTROL_PROPOSAL_IDENTITY_CHANGED"]
    expected_item = ("workflow", "create", "pending", None, None, None)
    if (
        tuple(
            item.get(key)
            for key in (
                "item_type",
                "action",
                "review_status",
                "target_resource_id",
                "materialized_resource_type",
                "materialized_resource_id",
            )
        )
        != expected_item
    ):
        return ["NATIVE_CONTROL_PROPOSAL_NOT_PENDING"]
    if (
        proposal.get("project_id"),
        proposal.get("status"),
        proposal.get("item_id"),
        proposal.get("idempotency_replayed"),
        pending.get("id"),
    ) != (str(frozen.project_id), "draft", item["id"], False, proposal.get("proposal_id")):
        return ["NATIVE_CONTROL_PROPOSAL_RECEIPT_CHANGED"]
    if replay != {**proposal, "idempotency_replayed": True}:
        return ["NATIVE_CONTROL_IDEMPOTENCY_CHANGED"]
    return []


def _accepted(frozen: NativeControlManifest, source: NativeControlFreeze) -> list[str]:
    item = _pending_item(source.accepted)
    pending = _pending_item(source.pending)
    if (
        item.get("id"),
        item.get("review_status"),
        item.get("reviewed_by_id"),
        item.get("materialized_resource_type"),
        item.get("materialized_resource_id"),
    ) != (pending["id"], "accepted", str(frozen.reviewer_id), "workflow", source.draft.get("id")):
        return ["NATIVE_CONTROL_INDEPENDENT_REVIEW_MISSING"]
    if item.get("reviewed_at") is None or canonical_digest(
        item["proposed_content"]
    ) != canonical_digest(pending["proposed_content"]):
        return ["NATIVE_CONTROL_REVIEW_CONTENT_CHANGED"]
    keys = ("id", "project_id", "source_type", "actor_type", "created_by_id", "source_fingerprint")
    if any(source.pending.get(key) != source.accepted.get(key) for key in keys):
        return ["NATIVE_CONTROL_ACCEPTED_SOURCE_CHANGED"]
    return []


def _assets(
    frozen: NativeControlManifest, pack: NativeControlPack, source: NativeControlFreeze
) -> list[str]:
    draft, published = source.draft, source.published
    expected = canonical_digest(pack.definition)
    if (
        canonical_digest(draft["draft_definition"]) != expected
        or canonical_digest(published["definition"]) != expected
    ):
        return ["NATIVE_CONTROL_REGIONS_CHANGED_OR_FLATTENED"]
    if (
        draft.get("project_id"),
        draft.get("current_version"),
        draft.get("draft_revision"),
        published.get("workflow_id"),
        published.get("version"),
    ) != (str(frozen.project_id), None, 1, draft.get("id"), 1):
        return ["NATIVE_CONTROL_PUBLICATION_BOUNDARY_CHANGED"]
    case = source.case
    definition = object_value(case.version["definition"])
    expected_case = {
        "workflow_id": draft["id"],
        "workflow_version": 1,
        "environment_id": str(frozen.environment_id),
        "runtime_variables": {},
        "runtime_headers": {},
    }
    if any(definition.get(key) != value for key, value in expected_case.items()):
        return ["NATIVE_CONTROL_CASE_REFERENCE_CHANGED"]
    if any(definition.get(key) for key in ("dataset", "dataset_artifact_id", "tags")):
        return ["NATIVE_CONTROL_CASE_DATASET_UNEXPECTED"]
    if (
        case.case.get("project_id"),
        case.version.get("test_case_id"),
        case.version.get("version"),
    ) != (str(frozen.project_id), case.case.get("id"), 1):
        return ["NATIVE_CONTROL_CASE_IDENTITY_CHANGED"]
    return []


def check_freeze(
    frozen: NativeControlManifest, pack: NativeControlPack, source: NativeControlFreeze
) -> list[str]:
    result = check_pending(
        frozen, pack, source.request, source.proposal, source.replay, source.pending
    )
    result += _accepted(frozen, source) + _assets(frozen, pack, source)
    if any(
        (
            source.before_workflow_ids,
            source.pending_workflow_ids,
            source.pending_execution_ids,
            source.before_execution_ids,
        )
    ):
        result.append("NATIVE_CONTROL_PROPOSAL_CREATED_EXECUTION_OR_WORKFLOW")
    if not frozen.created_at <= source.selection.frozen_at <= source.frozen_at <= frozen.expires_at:
        result.append("NATIVE_CONTROL_FREEZE_TIME_CHANGED")
    selection = source.selection
    if selection.project_id != frozen.project_id or len(selection.cases) != 1:
        return [*result, "NATIVE_CONTROL_SELECTION_CHANGED"]
    case = selection.cases[0]
    snapshot: JsonObject = {
        "target_type": "case",
        "target_id": source.case.case["id"],
        "target_version": 1,
        "definition": source.case.version["definition"],
        "source_suite": {"id": str(selection.suite_id), "version": 1},
    }
    if str(case.case_id) != source.case.case["id"] or (
        case.version,
        selection.suite_version,
        case.target_snapshot_digest,
    ) != (1, 1, canonical_digest(snapshot)):
        result.append("NATIVE_CONTROL_PINNED_CASE_CHANGED")
    return result + _suite_and_plan(frozen, source)


def _suite_and_plan(frozen: NativeControlManifest, source: NativeControlFreeze) -> list[str]:
    selection = source.selection
    suite, plan = source.suite, source.plan
    expected_suite = {"items": [{"test_case_id": source.case.case["id"], "test_case_version": 1}]}
    if (
        suite.get("test_suite_id"),
        suite.get("version"),
        suite.get("fingerprint"),
        suite.get("definition"),
    ) != (str(selection.suite_id), 1, selection.suite_fingerprint, expected_suite):
        return ["NATIVE_CONTROL_PUBLISHED_SUITE_CHANGED"]
    if (plan.get("id"), plan.get("project_id"), plan.get("created_by_id")) != (
        str(selection.plan_id),
        str(frozen.project_id),
        str(frozen.reviewer_id),
    ):
        return ["NATIVE_CONTROL_FROZEN_PLAN_CHANGED"]
    items = objects_value(plan["items"])
    expected = {
        "target_type": "suite",
        "target_id": str(selection.suite_id),
        "target_version": 1,
        "max_retries": 0,
        "runtime_variables": {},
        "runtime_headers": {},
    }
    if len(items) != 1 or any(items[0].get(key) != value for key, value in expected.items()):
        return ["NATIVE_CONTROL_SUITE_PLAN_BINDING_CHANGED"]
    return []


def _plan(
    frozen: NativeControlManifest, source: NativeControlFreeze, evidence: NativeControlEvidence
) -> list[str]:
    raw = evidence.plan_run
    execution = evidence.execution
    if raw is None or execution is None:
        return ["NATIVE_CONTROL_EVIDENCE_MISSING"]
    items = objects_value(raw["items"])
    selection = source.selection
    if (
        raw.get("project_id"),
        raw.get("test_plan_id"),
        raw.get("status"),
        raw.get("trigger_type"),
        raw.get("total"),
        raw.get("has_more"),
        raw.get("truncated"),
    ) != (
        str(frozen.project_id),
        str(selection.plan_id),
        "passed",
        "manual",
        1,
        False,
        False,
    ) or len(items) != 1:
        return ["NATIVE_CONTROL_PLAN_IDENTITY_CHANGED"]
    item, case = items[0], selection.cases[0]
    expected: JsonObject = {
        "target_type": "case",
        "target_id": str(case.case_id),
        "target_version": 1,
        "target_snapshot_digest": case.target_snapshot_digest,
        "workflow_id": source.draft["id"],
        "workflow_version": 1,
        "environment_id": str(frozen.environment_id),
        "status": "passed",
        "attempts": 1,
        "execution_id": str(execution.id),
        "execution_ids": [str(execution.id)],
        "attempts_complete": True,
    }
    if any(item.get(key) != value for key, value in expected.items()):
        return ["NATIVE_CONTROL_PLAN_CASE_OR_ATTEMPTS_CHANGED"]
    raw_execution = evidence.raw_execution or {}
    if (
        raw_execution.get("source_case_id"),
        raw_execution.get("source_case_version"),
        raw_execution.get("source_plan_run_item_id"),
    ) != (str(case.case_id), 1, item.get("id")):
        return ["NATIVE_CONTROL_EXECUTION_CASE_SOURCE_CHANGED"]
    return []


def _execution(
    frozen: NativeControlManifest, source: NativeControlFreeze, evidence: NativeControlEvidence
) -> list[str]:
    execution = evidence.execution
    if execution is None:
        return ["NATIVE_CONTROL_EVIDENCE_MISSING"]
    identity = (
        str(execution.project_id),
        str(execution.workflow_id),
        str(execution.workflow_version_id),
        str(execution.environment_id),
        execution.workflow_fingerprint,
    )
    if identity != (
        str(frozen.project_id),
        source.draft["id"],
        source.published["id"],
        str(frozen.environment_id),
        source.published["fingerprint"],
    ):
        return ["NATIVE_CONTROL_EXECUTION_VERSION_CHANGED"]
    if (
        execution.status,
        execution.main_status,
        execution.error_code,
        execution.run_purpose,
        execution.api_sources,
    ) != ("passed", "passed", None, "standard", ()):
        return ["NATIVE_CONTROL_EXECUTION_OUTCOME_CHANGED"]
    if (
        execution.parent_execution_id is not None
        or execution.dataset is not None
        or execution.children
        or execution.subflows
    ):
        return ["NATIVE_CONTROL_UNEXPECTED_EXECUTION_TOPOLOGY"]
    if not all(
        (execution.children_complete, execution.subflows_complete, execution.nested_nodes_complete)
    ):
        return ["NATIVE_CONTROL_EXECUTION_PAGE_INCOMPLETE"]
    if (
        not source.frozen_at
        <= execution.started_at
        <= (execution.completed_at or frozen.expires_at)
        <= evidence.collected_at
        <= frozen.expires_at
        or execution.completed_at is None
    ):
        return ["NATIVE_CONTROL_EXECUTION_TIME_CHANGED"]
    expected_nodes = {"start": "start", "parallel": "capability", "end": "end"}
    actual = {node.node_id: node.node_type for node in execution.nodes}
    if actual != expected_nodes or len(execution.nodes) != 3:
        return ["NATIVE_CONTROL_NATIVE_NODES_CHANGED"]
    if any(
        (node.status, node.phase, node.attempts, node.error_code, node.assertions)
        != ("passed", "main", 1, None, ())
        for node in execution.nodes
    ):
        return ["NATIVE_CONTROL_NATIVE_NODE_OUTCOME_CHANGED"]
    return _raw_projection(evidence)


def _raw_projection(evidence: NativeControlEvidence) -> list[str]:
    execution, raw = evidence.execution, evidence.raw_execution
    if execution is None or raw is None:
        return ["NATIVE_CONTROL_EVIDENCE_MISSING"]
    expected = execution.model_dump(
        mode="json", exclude={"id", "nodes", "nested_nodes", "api_sources"}
    )
    expected.update(
        {
            "execution_id": str(execution.id),
            "api_bindings": [],
            "bindings_complete": True,
            "node_total": 3,
            "nested_node_total": 2,
            "truncated": False,
            "children_total": 0,
        }
    )
    if any(raw.get(key) != value for key, value in expected.items()):
        return ["NATIVE_CONTROL_RAW_EXECUTION_CHANGED"]
    for field in ("nodes", "nested_nodes"):
        rows = objects_value(raw[field])
        if any(row.get("assertions_complete") is not True for row in rows):
            return ["NATIVE_CONTROL_ASSERTION_PAGE_INCOMPLETE"]
        normalized: list[JsonValue] = [
            {key: value for key, value in row.items() if key != "assertions_complete"}
            for row in rows
        ]
        typed = [row.model_dump(mode="json") for row in getattr(execution, field)]
        if canonical_digest(normalized) != canonical_digest(typed):
            return ["NATIVE_CONTROL_RAW_NODE_CHANGED"]
    return []


def _branches(pack: NativeControlPack, evidence: NativeControlEvidence) -> list[str]:
    execution, page = evidence.execution, evidence.control_page
    if execution is None or page is None or len(evidence.control_details) != 2:
        return ["NATIVE_CONTROL_EVIDENCE_MISSING"]
    expected = [
        {"ordinal": row.ordinal, "status": row.status, "test_verdict": row.test_verdict}
        for row in pack.branches
    ]
    if (
        page.get("execution_id"),
        page.get("node_id"),
        page.get("kind"),
        page.get("items"),
        page.get("total"),
        page.get("has_more"),
        page.get("truncated"),
        page.get("page"),
        page.get("page_size"),
    ) != (str(execution.id), "parallel", "branch", expected, 2, False, False, 1, 100):
        return ["NATIVE_CONTROL_BRANCH_PAGE_CHANGED"]
    nested = {node.node_id: node for node in execution.nested_nodes}
    if len(nested) != 2 or len(execution.nested_nodes) != 2:
        return ["NATIVE_CONTROL_NESTED_CHECKPOINTS_MISSING"]
    result: list[str] = []
    for golden, row in zip(pack.branches, evidence.control_details, strict=True):
        payload = object_value(row["payload"])
        node = nested.get(golden.instance_id)
        if (
            row.get("kind"),
            row.get("ordinal"),
            row.get("status"),
            row.get("test_verdict"),
            payload.get("branch_id"),
            payload.get("definition_index"),
        ) != ("branch", golden.ordinal, "passed", "passed", golden.branch_id, golden.ordinal):
            result.append("NATIVE_CONTROL_BRANCH_DETAIL_CHANGED")
        if (payload.get("status"), payload.get("test_verdict"), payload.get("outputs")) != (
            "passed",
            "passed",
            {},
        ):
            result.append("NATIVE_CONTROL_BRANCH_PAYLOAD_CHANGED")
        nodes = objects_value(payload["nodes"])
        if len(nodes) != 1 or any(
            nodes[0].get(key) != value
            for key, value in {
                "node_id": golden.node_id,
                "instance_id": golden.instance_id,
                "status": "passed",
                "error_code": None,
            }.items()
        ):
            result.append("NATIVE_CONTROL_BRANCH_NODE_CHANGED")
        if node is None or (
            node.node_type,
            node.phase,
            node.status,
            node.attempts,
            node.error_code,
            node.assertions,
        ) != ("delay", "main", "passed", 1, None, ()):
            result.append("NATIVE_CONTROL_NESTED_NODE_CHANGED")
    return result


def _export(
    frozen: NativeControlManifest,
    pack: NativeControlPack,
    source: NativeControlFreeze,
    evidence: NativeControlEvidence,
    variant: ControlVariant,
) -> list[str]:
    rows = [row for row in evidence.exports if row.variant == variant]
    if len(rows) != 1:
        return ["NATIVE_CONTROL_EVIDENCE_MISSING"]
    row, version = rows[0], None if variant == "regions4_draft" else 1
    path = f"/projects/{frozen.project_id}/flow-specs/workflows/{source.draft['id']}/export" + (
        "?version=1" if version else ""
    )
    if (
        str(row.workflow_id),
        row.version,
        row.path,
        row.status,
        row.error_code,
        row.trace_present,
    ) != (source.draft["id"], version, path, pack.export_status, pack.export_error_code, True):
        return ["NATIVE_CONTROL_EXPORT_BOUNDARY_CHANGED"]
    if (
        row.before_definition_digest != canonical_digest(pack.definition)
        or row.after_definition_digest != row.before_definition_digest
    ):
        return ["NATIVE_CONTROL_EXPORT_FLATTENED_OR_MUTATED"]
    if row.before_execution_ids or row.after_execution_ids:
        return ["NATIVE_CONTROL_EXPORT_CREATED_EXECUTION"]
    return []


def _calls(
    frozen: NativeControlManifest, source: NativeControlFreeze, evidence: NativeControlEvidence
) -> list[str]:
    calls = evidence.calls
    if len(calls) != 2 or evidence.admitted_tool_calls != 2:
        return ["NATIVE_CONTROL_COMPLETE_TOOL_TRAIL_MISSING"]
    for call, phase, response in zip(
        calls, ("native:proposal", "native:replay"), (source.proposal, source.replay), strict=True
    ):
        if (
            call.batch_key,
            call.scenario_id,
            call.phase,
            call.tool_name,
            call.request_digest,
            call.result_digest,
            call.success,
        ) != (
            frozen.batch_key,
            "ST-MCP-023",
            phase,
            "flowtest.propose_control_workflow",
            canonical_digest(source.request),
            canonical_digest(response),
            True,
        ):
            return ["NATIVE_CONTROL_TOOL_SOURCE_CHANGED"]
        if not frozen.created_at <= call.completed_at <= source.frozen_at:
            return ["NATIVE_CONTROL_CALL_TIME_CHANGED"]
    if calls[0].call_id == calls[1].call_id or calls[0].catalog_digest != calls[1].catalog_digest:
        return ["NATIVE_CONTROL_TOOL_ATTEMPT_REPLAY"]
    return []


def _disposal(
    frozen: NativeControlManifest, evidence: NativeControlEvidence, now: datetime
) -> list[str]:
    receipt = evidence.disposal
    if receipt is None:
        return ["OWNED_ASSET_DISPOSAL_PENDING"]
    expected = frozen.required_disposal.model_dump()
    if receipt.model_dump(include=set(expected)) != expected or not all(
        (receipt.containers_absent, receipt.volumes_absent, receipt.networks_absent)
    ):
        return ["NATIVE_CONTROL_DISPOSAL_IDENTITY_CHANGED"]
    if not evidence.collected_at <= receipt.removed_at <= now:
        return ["NATIVE_CONTROL_DISPOSAL_TIME_CHANGED"]
    return []


def _identity(
    frozen: NativeControlManifest,
    pack: NativeControlPack,
    evidence: NativeControlEvidence,
    now: datetime,
) -> list[str]:
    result: list[str] = []
    if (
        canonical_digest(pack.model_dump(mode="json")) != frozen.pack_digest
        or frozen.pack_digest != PACK_DIGEST
        or tuple(pack.variants) != get_args(ControlVariant)
    ):
        result.append("NATIVE_CONTROL_FROZEN_PACK_CHANGED")
    if evidence.manifest_digest != canonical_digest(frozen.model_dump(mode="json")):
        result.append("NATIVE_CONTROL_MANIFEST_CHANGED")
    if (
        now.tzinfo is None
        or now > frozen.expires_at
        or not frozen.created_at <= evidence.collected_at <= frozen.expires_at
    ):
        result.append("NATIVE_CONTROL_BATCH_EXPIRED")
    if evidence.failure_code:
        result.append("NATIVE_CONTROL_HARNESS_FAILED")
    if (
        evidence.rejected_requests
        or evidence.rejected_tool_calls
        or evidence.admitted_request_upper_bound > 500
    ):
        result.append("NATIVE_CONTROL_BUDGET_EXCEEDED")
    cleanup = evidence.cleanup
    if cleanup is None or cleanup.status != "completed":
        result.append("NATIVE_CONTROL_CLEANUP_INCOMPLETE")
    elif evidence.frozen is not None and (
        cleanup.project_id != frozen.project_id
        or cleanup.plan_id != evidence.frozen.selection.plan_id
        or not cleanup.launch_requested
        or str(cleanup.run_id) != (evidence.plan_run or {}).get("run_id")
    ):
        result.append("NATIVE_CONTROL_CLEANUP_IDENTITY_CHANGED")
    return result + _disposal(frozen, evidence, now)


def _verify(
    frozen: NativeControlManifest,
    pack: NativeControlPack,
    evidence: NativeControlEvidence,
    now: datetime,
) -> NativeControlReport:
    findings = _identity(frozen, pack, evidence, now)
    checks: list[NativeControlCheck] = []
    source = evidence.frozen
    common = (
        ["NATIVE_CONTROL_EVIDENCE_MISSING"]
        if source is None
        else check_freeze(frozen, pack, source) + _calls(frozen, source, evidence)
    )
    for variant in get_args(ControlVariant):
        errors = list(common)
        if source is not None:
            errors += (
                (
                    _plan(frozen, source, evidence)
                    + _execution(frozen, source, evidence)
                    + _branches(pack, evidence)
                )
                if variant == "native_control_chain"
                else _export(frozen, pack, source, evidence, variant)
            )
        unique = tuple(dict.fromkeys(errors))
        checks.append(
            NativeControlCheck(
                variant=variant,
                status="matched"
                if not unique
                else "incomplete"
                if set(unique) <= INCOMPLETE
                else "mismatched",
                findings=unique,
            )
        )
    all_errors = findings + [code for row in checks for code in row.findings]
    failed = bool(set(all_errors) - INCOMPLETE)
    return NativeControlReport(
        batch_key=frozen.batch_key,
        pack_digest=frozen.pack_digest,
        manifest_digest=evidence.manifest_digest,
        verdict="passed" if not all_errors else "failed" if failed else "blocked",
        exit_code=0 if not all_errors else 1 if failed else 2,
        findings=tuple(dict.fromkeys(findings)),
        scenarios=tuple(checks),
    )


def verify(
    frozen: NativeControlManifest,
    pack: NativeControlPack,
    evidence: NativeControlEvidence,
    *,
    now: datetime | None = None,
) -> NativeControlReport:
    try:
        return _verify(frozen, pack, evidence, now or datetime.now(UTC))
    except (HarnessError, KeyError, TypeError, ValueError):
        return NativeControlReport(
            batch_key=frozen.batch_key,
            pack_digest=frozen.pack_digest,
            manifest_digest=evidence.manifest_digest,
            verdict="blocked",
            exit_code=2,
            findings=("NATIVE_CONTROL_EVIDENCE_INVALID",),
            scenarios=tuple(
                NativeControlCheck(
                    variant=variant,
                    status="incomplete",
                    findings=("NATIVE_CONTROL_EVIDENCE_INVALID",),
                )
                for variant in get_args(ControlVariant)
            ),
        )


def write_reports(
    report: NativeControlReport, evidence: NativeControlEvidence, directory: Path
) -> None:
    write_json(directory / "verification.json", report)
    for raw in (True, False):
        root = Element(
            "testsuite", name="native-control-execution" if raw else "native-control-verification"
        )
        if raw:
            case = SubElement(root, "testcase", name="native_control_chain")
            if evidence.execution is None or evidence.execution.status != "passed":
                SubElement(case, "failure", message="原生执行未通过")
        else:
            for row in report.scenarios:
                case = SubElement(root, "testcase", name=row.variant)
                if row.status != "matched":
                    SubElement(case, "failure", message=",".join(row.findings))
            if report.findings:
                SubElement(
                    SubElement(root, "testcase", name="batch-global"),
                    "failure",
                    message=",".join(report.findings),
                )
        root.set("tests", str(len(root)))
        (directory / ("execution.junit.xml" if raw else "verification.junit.xml")).write_bytes(
            tostring(root, encoding="utf-8", xml_declaration=True)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="独立核验原生控制提案与区域导出边界")
    for name in ("manifest", "evidence", "pack", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    frozen = NativeControlManifest.model_validate(read_json(args.manifest))
    evidence = NativeControlEvidence.model_validate(read_json(args.evidence))
    report = verify(frozen, load_pack(args.pack), evidence)
    args.output.mkdir(parents=True, exist_ok=True)
    write_reports(report, evidence, args.output)
    raise SystemExit(report.exit_code)


if __name__ == "__main__":
    main()
