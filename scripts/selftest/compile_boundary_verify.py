"""Independent wire compiler checks; never call the product compiler to decide correctness."""

import argparse
import json
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

from scripts.selftest.boundary_reporting import write_boundary_junit
from scripts.selftest.compile_boundary_contracts import (
    KEYS,
    CompileBoundaryEvidence,
    CompileBoundaryManifest,
    CompileBoundaryObservation,
    CompileBoundaryReport,
)
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.draft_boundary_contracts import DraftBoundaryObservation, draft_keys
from scripts.selftest.io import JsonObject, object_value, objects_value, read_json, write_json


def pure_keys() -> tuple[str, ...]:
    return tuple(
        transport + "/" + key for transport in ("stdio", "streamable-http") for key in KEYS
    )


def keys() -> tuple[str, ...]:
    return (*pure_keys(), *draft_keys())


def _draft(
    row: DraftBoundaryObservation,
    manifest: CompileBoundaryManifest,
    observations: tuple[CompileBoundaryObservation, ...],
) -> bool:
    original = next(
        (
            item
            for item in observations
            if item.transport == row.transport and item.key == "positive"
        ),
        None,
    )
    if original is None or original.response is None:
        return False
    payload = object_value(objects_value(original.response["scenarios"])[0]["executable_payload"])
    before, proposed, after = row.before, row.proposed, row.after
    return bool(
        before.complete
        and proposed.complete
        and after.complete
        and before == proposed
        and row.project_id == row.workflow_project_id == before.project_id == manifest.project_id
        and row.proposal_status_before == "draft"
        and row.proposal_review_before == "pending"
        and row.proposal_applied_before is None
        and row.proposal_review_after == "accepted"
        and row.applied_at is not None
        and row.reviewer_id == row.expected_reviewer_id
        and row.current_version is None
        and row.published_version_count == 0
        and row.proposed_digest == row.draft_digest
        and (
            row.route == "quick"
            or row.draft_digest == canonical_digest(payload["native_definition"])
        )
        and row.api_references == (row.api_id,)
        and row.api_versions == (1,)
        and row.workflow_id not in before.workflow_ids
        and set(after.workflow_ids) == {*before.workflow_ids, row.workflow_id}
        and before.model_dump(exclude={"workflow_ids"})
        == after.model_dump(exclude={"workflow_ids"})
        and set(row.proposal_ids_after) == {*row.proposal_ids_before, row.proposal_id}
        and row.call.success
        and row.call.tool_name
        == (
            "flowtest.propose_simple_flow"
            if row.route == "quick"
            else "flowtest.propose_flow_draft"
        )
        and manifest.created_at <= row.completed_at <= manifest.deadline
    )


def _ready(row: CompileBoundaryObservation) -> bool:
    response = row.response
    if response is None or response.get("readiness") != "ready":
        return False
    scenarios = objects_value(response["scenarios"])
    if len(scenarios) != 1:
        return False
    scenario = scenarios[0]
    payload = object_value(scenario["executable_payload"])
    request = row.request
    design = object_value(request["design"])
    selected = next(
        (s for s in objects_value(design["scenarios"]) if s["id"] == scenario["scenario_id"]), None
    )
    if selected is None:
        return False
    nodes = objects_value(object_value(payload["native_definition"])["nodes"])
    config = next(object_value(node["config"]) for node in nodes if node["id"] == "request")
    body = object_value(object_value(config["request_overrides"])["body"])
    expected_body = object_value(selected["request"])["body"]
    oracles = [
        oracle
        for oracle in objects_value(design["oracles"])
        if isinstance(oracle["applies_to"], list)
        and scenario["scenario_id"] in oracle["applies_to"]
    ]
    bindings = objects_value(scenario["oracle_bindings"])
    version = object_value(request["origin"])["api_version"]
    return bool(
        row.request["scenario_ids"] == [scenario["scenario_id"]]
        and object_value(response["resolved_sources"])["api_version"] == version == 1
        and list(object_value(payload["operation_version_mappings"]).values()) == [version]
        and body["kind"] == "json"
        and json.dumps(body["value"], sort_keys=True) == json.dumps(expected_body, sort_keys=True)
        and (
            row.key in {"negative", "null_field"}
            or json.dumps(body["value"], sort_keys=True)
            == json.dumps({"count": 0, "flag": False, "text": "", "optional": None}, sort_keys=True)
        )
        and config["api_definition_id"] == object_value(request["origin"])["api_definition_id"]
        and config["api_version"] == version
        and _native_graph(object_value(payload["native_definition"]), bindings)
        and config["expected_statuses"]
        == ([422] if row.key in {"negative", "null_field"} else [201])
        and {item["oracle_id"] for item in bindings} == {item["id"] for item in oracles}
        and len(bindings) == len(oracles)
        and all(_oracle_bound(oracle, bindings, nodes) for oracle in oracles)
        and object_value(scenario["case_template"])["workflow_slot"]
        == "scenario:" + str(scenario["scenario_id"])
        and "workflow_id" not in object_value(scenario["case_template"])
    )


def _native_graph(graph: JsonObject, bindings: list[JsonObject]) -> bool:
    identifiers = ["start", "request", *(str(row["node_id"]) for row in bindings), "end"]
    nodes, edges = objects_value(graph["nodes"]), objects_value(graph["edges"])
    return bool(
        len(nodes) == len(set(identifiers)) == len(identifiers)
        and {node["id"] for node in nodes} == set(identifiers)
        and all(node["phase"] == "main" for node in nodes)
        and len(edges) == len(identifiers) - 1
        and {(edge["source"], edge["target"]) for edge in edges} == set(pairwise(identifiers))
        and all(edge.get("condition") is None and edge["mappings"] == [] for edge in edges)
    )


def _oracle_bound(oracle: JsonObject, bindings: list[JsonObject], nodes: list[JsonObject]) -> bool:
    binding = next(row for row in bindings if row["oracle_id"] == oracle["id"])
    node = next((node for node in nodes if node["id"] == binding["node_id"]), None)
    if node is None or node["type"] != "assert":
        return False
    expected: JsonObject = {
        "source_node_id": "request",
        "expression": "status_code",
        "operator": "equals",
        "expected": oracle["expected"],
    }
    if oracle["kind"] == "schema":
        if oracle["expression"] != "$.body" or oracle["operator"] != "validates":
            return False
        expected.update(assertion_type="json_schema", expression="body")
    elif (
        oracle["kind"] != "status"
        or oracle["expression"] != "$.status"
        or oracle["operator"] != "equals"
    ):
        return False
    return canonical_digest(node["config"]) == canonical_digest(expected)


def _response(row: CompileBoundaryObservation) -> bool:
    if row.key == "catalog":
        return bool(
            "flowtest.compile_test_design" in row.catalog_names
            and not any(
                name in row.catalog_names
                for name in ("flowtest.run", "flowtest.publish", "flowtest.approve")
            )
        )
    if row.response is not None:
        if (
            row.response.get("persisted") is not False
            or row.response.get("execution_status") != "not_run"
        ):
            return False
        if row.key in {"positive", "reproducible", "negative", "null_field"}:
            return _ready(row)
        readiness = {
            "missing_context": "needs_input",
            "unsupported_route": "unsupported",
            "fixture_auth": "unsupported",
        }
        return row.response.get("readiness") == readiness.get(row.key)
    codes = {
        "scope_none": "MCP_SCOPE_REQUIRED",
        "scope_read": "MCP_SCOPE_REQUIRED",
        "scope_flow": "MCP_SCOPE_REQUIRED",
        "organization": "PROJECT_NOT_FOUND",
        "version": "API_VERSION_NOT_FOUND",
        "source_changed": "DESIGN_COMPILATION_SOURCE_MISMATCH",
        "context_changed": "TEST_CONTEXT_REVISION_STALE",
    }
    if row.boundary is None or row.boundary.is_error is not True:
        return False
    if row.key in {"extra_fields", "boolean_budget"}:
        return True
    return row.boundary.business_code == codes.get(row.key) and row.boundary.trace_present


def _row(manifest: CompileBoundaryManifest, row: CompileBoundaryObservation) -> bool:
    calls = row.calls
    return bool(
        row.before.complete
        and row.after.complete
        and row.before == row.after
        and row.before.project_id == manifest.project_id
        and row.request["project_id"]
        == str(manifest.foreign_project_id if row.key == "organization" else manifest.project_id)
        and row.proposal_ids_before == row.proposal_ids_after
        and row.sdk_version == "2.2.0"
        and row.protocol_version == "2026-07-28"
        and manifest.created_at <= row.completed_at <= manifest.deadline
        and (
            not calls
            if row.key == "catalog"
            else len(calls) == 1
            and calls[0].tool_name == "flowtest.compile_test_design"
            and calls[0].request_digest == canonical_digest({"request": row.request})
        )
        and _response(row)
    )


def verify(
    manifest: CompileBoundaryManifest, evidence: CompileBoundaryEvidence
) -> CompileBoundaryReport:
    expected = keys()
    reasons = []
    if (
        manifest.expected_keys != expected
        or tuple(row.transport + "/" + row.key for row in evidence.observations) != pure_keys()
        or tuple(row.transport + "/" + row.route + "_draft" for row in evidence.drafts)
        != draft_keys()
    ):
        reasons.append("COMPILE_BOUNDARY_DENOMINATOR_CHANGED")
    if evidence.manifest_digest != canonical_digest(manifest.model_dump(mode="json")):
        reasons.append("COMPILE_BOUNDARY_MANIFEST_CHANGED")
    if (
        not manifest.created_at <= evidence.collected_at <= manifest.deadline
        or manifest.deadline - manifest.created_at > timedelta(seconds=600)
        or evidence.rejected_attempts
        or evidence.tool_attempts
        < sum(len(row.calls) for row in evidence.observations) + len(evidence.drafts)
    ):
        reasons.append("COMPILE_BOUNDARY_BUDGET_OR_CLOCK_CHANGED")
    if evidence.disposal is None:
        reasons.append("OWNED_ASSET_DISPOSAL_PENDING")
    elif not (
        evidence.disposal.model_dump(
            exclude={"removed_at", "containers_absent", "volumes_absent", "networks_absent"}
        )
        == manifest.disposal.model_dump()
        and evidence.disposal.containers_absent
        and evidence.disposal.volumes_absent
        and evidence.disposal.networks_absent
        and evidence.collected_at <= evidence.disposal.removed_at <= manifest.deadline
    ):
        reasons.append("COMPILE_BOUNDARY_DISPOSAL_CHANGED")
    matched = tuple(
        row.transport + "/" + row.key for row in evidence.observations if _row(manifest, row)
    )
    matched += tuple(
        row.transport + "/" + row.route + "_draft"
        for row in evidence.drafts
        if _draft(row, manifest, evidence.observations)
    )
    for transport in ("stdio", "streamable-http"):
        positive = next(
            (
                row
                for row in evidence.observations
                if row.transport == transport and row.key == "positive"
            ),
            None,
        )
        repeated = next(
            (
                row
                for row in evidence.observations
                if row.transport == transport and row.key == "reproducible"
            ),
            None,
        )
        if positive is None or repeated is None or positive.response != repeated.response:
            reasons.append("COMPILE_BOUNDARY_NOT_REPRODUCIBLE")
    if matched != expected:
        reasons.append("COMPILE_BOUNDARY_FACTS_MISMATCH")
    return CompileBoundaryReport(
        expected_keys=expected,
        matched_keys=matched,
        reason_codes=tuple(reasons),
        exit_code=2 if reasons else 0,
    )


def write_reports(report: CompileBoundaryReport, output: Path) -> None:
    write_json(output / "verification.json", report)
    write_boundary_junit(
        output,
        report.expected_keys,
        report.reason_codes,
        purpose="纯编译和拒绝探针; 未执行目标或模型",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(
        CompileBoundaryManifest.model_validate(read_json(args.output / "manifest.json")),
        CompileBoundaryEvidence.model_validate(read_json(args.output / "evidence.json")),
    )
    write_reports(report, args.output)
    raise SystemExit(report.exit_code)
