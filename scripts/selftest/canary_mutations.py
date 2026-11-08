"""Deliberately corrupt copies of actual deployment evidence; never edit the originals."""

from copy import deepcopy

from scripts.selftest.io import HarnessError, JsonObject, object_value, objects_value


def _executions(row: JsonObject) -> list[JsonObject]:
    return [object_value(row["execution"]), *objects_value(row["attempts"])]


def _assertion_row(evidence: JsonObject) -> JsonObject:
    for row in objects_value(evidence["scenarios"]):
        execution = object_value(row["execution"])
        if execution["error_code"] == "WORKFLOW_ASSERTION_FAILED":
            return row
    raise HarnessError("CANARY_ASSERTION_FAILURE_SOURCE_MISSING")


def _set_changes(kind: str, manifest: JsonObject, evidence: JsonObject) -> bool:
    rows = objects_value(evidence["scenarios"])
    if kind == "missing":
        evidence["scenarios"] = [row for row in rows[1:]]
    elif kind == "duplicate":
        evidence["scenarios"] = [*rows, deepcopy(rows[0])]
    elif kind == "zero":
        evidence["scenarios"] = []
    elif kind == "required_subset":
        manifest["required_scenario_set"] = []
    else:
        return False
    return True


def _availability_changes(kind: str, evidence: JsonObject) -> bool:
    rows = objects_value(evidence["scenarios"])
    if kind in {"quarantined", "parent_passed_child_running"}:
        for row in rows:
            source = object_value(row["provenance"])
            object_value(source["run"])["status"] = (
                "quarantined" if kind == "quarantined" else "running"
            )
    elif kind in {"skipped", "unexecuted"}:
        for execution in _executions(_assertion_row(evidence)):
            for node in objects_value(execution["nodes"]):
                if node["node_type"] == "assert":
                    node.update(status="skipped", attempts=0, assertions=[])
    elif kind == "truncated":
        rows[0]["truncated"] = True
    elif kind == "missing_attempt":
        rows[0]["attempts"] = []
    elif kind == "missing_receipt":
        rows[0]["journal"] = None
    else:
        return False
    return True


def _page_changes(kind: str, evidence: JsonObject) -> bool:
    if kind != "missing_page":
        return False
    selected = next(
        (row for row in objects_value(evidence["scenarios"]) if row["control_pages"]), None
    )
    if selected is None:
        raise HarnessError("CANARY_CONTROL_PAGE_SOURCE_MISSING")
    selected["control_pages"] = []
    return True


def _identity_changes(kind: str, evidence: JsonObject) -> bool:
    if kind == "build":
        object_value(evidence["builds"])["target"] = "sha256:" + "0" * 64
    elif kind == "manifest":
        evidence["pack_digest"] = "0" * 64
    elif kind == "ci_attempt":
        evidence["ci_attempt"] = 99999
    elif kind == "nonce":
        evidence["nonce"] = "foreign-nonce"
    elif kind == "replay":
        evidence["collected_at"] = "2000-01-01T00:00:00Z"
    elif kind == "digest_mismatch":
        row = objects_value(evidence["scenarios"])[0]
        for execution in _executions(row):
            execution["workflow_fingerprint"] = "0" * 64
    elif kind == "old_run":
        row = objects_value(evidence["scenarios"])[0]
        for execution in _executions(row):
            execution["id"] = "00000000-0000-4000-8000-000000000001"
    else:
        return False
    return True


def _assertion_changes(kind: str, evidence: JsonObject) -> bool:
    if kind not in {
        "wrong_code",
        "wrong_node",
        "wrong_phase",
        "timeout",
        "missing_assertion",
        "junit_zero",
    }:
        return False
    for execution in _executions(_assertion_row(evidence)):
        if kind in {"wrong_code", "timeout", "junit_zero"}:
            execution["error_code"] = "NODE_TIMEOUT" if kind == "timeout" else "HTTP_5XX"
        for node in objects_value(execution["nodes"]):
            if node["node_type"] != "assert":
                continue
            if kind == "wrong_node":
                node["node_id"] = "foreign_assertion_node"
            elif kind == "wrong_phase":
                node["phase"] = "cleanup"
            elif kind == "missing_assertion":
                node["assertions"] = []
    return True


def _source_changes(kind: str, evidence: JsonObject) -> bool:
    if kind not in {"delete_case", "delete_tool_receipt"}:
        return False
    source = object_value(objects_value(evidence["scenarios"])[0]["provenance"])
    if kind == "delete_case":
        object_value(source["case"])["id"] = "00000000-0000-4000-8000-000000000002"
    else:
        source["calls"] = [row for row in objects_value(source["calls"])[1:]]
    return True


def mutate(kind: str, manifest: JsonObject, evidence: JsonObject) -> None:
    if not (
        _set_changes(kind, manifest, evidence)
        or _availability_changes(kind, evidence)
        or _identity_changes(kind, evidence)
        or _assertion_changes(kind, evidence)
        or _source_changes(kind, evidence)
        or _page_changes(kind, evidence)
    ):
        raise HarnessError("CANARY_UNKNOWN_MUTATION")
