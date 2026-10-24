"""Narrow CI fixture reviewer using the existing review and publish APIs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import JsonValue
from scripts.selftest.contracts import Contract, ProposalEvidence, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    text_value,
    write_json,
)


class ReviewedWorkflow(Contract):
    workflow: JsonObject
    version: JsonObject
    proposal: ProposalEvidence


class ReviewedCase(Contract):
    case: JsonObject
    version: JsonObject
    proposal: ProposalEvidence


def _difference_paths(expected: JsonValue, actual: JsonValue, path: str = "$") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[str] = []
        for key in sorted(expected.keys() | actual.keys()):
            child = path + "." + key
            if key not in expected or key not in actual:
                differences.append(child)
            else:
                differences.extend(_difference_paths(expected[key], actual[key], child))
        return differences[:200]
    if isinstance(expected, list) and isinstance(actual, list):
        differences = [path + ".length"] if len(expected) != len(actual) else []
        for index, (left, right) in enumerate(zip(expected, actual, strict=False)):
            differences.extend(_difference_paths(left, right, f"{path}[{index}]"))
        return differences[:200]
    return [] if canonical_digest(expected) == canonical_digest(actual) else [path]


def _same_definition(
    expected: JsonObject, actual: JsonObject, *, output_dir: Path, stage: str
) -> None:
    if canonical_digest(expected) != canonical_digest(actual):
        write_json(
            output_dir / "review-difference.json",
            {
                "stage": stage,
                "expected_digest": canonical_digest(expected),
                "actual_digest": canonical_digest(actual),
                "difference_paths": [str(path) for path in _difference_paths(expected, actual)],
            },
        )
        raise HarnessError("SELFTEST_REVIEW_DEFINITION_CHANGED")


def _fixture_graph(definition: JsonObject, expected_api_ids: tuple[str, ...]) -> None:
    nodes = objects_value(definition["nodes"])
    if not nodes or len(nodes) > 500:
        raise HarnessError("SELFTEST_REVIEW_NODE_BUDGET")
    allowed = {"start", "api", "assert", "extract", "variable", "end"}
    if any(node["type"] not in allowed for node in nodes):
        raise HarnessError("SELFTEST_REVIEW_NODE_TYPE_BLOCKED")
    actual_apis = {
        text_value(object_value(node["config"])["api_definition_id"])
        for node in nodes
        if node["type"] == "api"
    }
    if actual_apis != set(expected_api_ids):
        raise HarnessError("SELFTEST_REVIEW_API_SCOPE_MISMATCH")


async def review_flow(
    api: PublicAPI,
    *,
    project_id: str,
    reviewer_id: str,
    proposal_id: str,
    expected_definition: JsonObject,
    expected_api_ids: tuple[str, ...],
    output_dir: Path,
) -> ReviewedWorkflow:
    _fixture_graph(expected_definition, expected_api_ids)
    base = f"/projects/{project_id}/flow-specs/change-sets/{proposal_id}"
    visual = await api.object("GET", base + "/visual-proposal")
    proposal = object_value(visual["proposal"])
    if proposal["project_id"] != project_id or proposal["review_status"] != "pending":
        raise HarnessError("SELFTEST_REVIEW_PROPOSAL_NOT_PENDING")
    _same_definition(
        expected_definition,
        object_value(visual["proposed_definition"]),
        output_dir=output_dir,
        stage="visual_proposal",
    )
    accepted = await api.object(
        "POST",
        base + "/review",
        {"accept": True, "note": "隔离自测受控审核; review_mode=ci_fixture"},
    )
    if accepted["source_fingerprint"] != proposal["source_fingerprint"]:
        raise HarnessError("SELFTEST_REVIEW_SOURCE_CHANGED")
    applied = await api.object("POST", base + "/apply")
    workflow_id = text_value(applied["workflow_id"])
    workflow = await api.object("GET", f"/projects/{project_id}/workflows/{workflow_id}")
    _same_definition(
        expected_definition,
        object_value(workflow["draft_definition"]),
        output_dir=output_dir,
        stage="workflow_draft",
    )
    version = await api.object(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        {"change_note": "本轮 MCP 生成自测固定版本"},
    )
    _same_definition(
        expected_definition,
        object_value(version["definition"]),
        output_dir=output_dir,
        stage="workflow_version",
    )
    sealed = await api.object("GET", base)
    if (
        sealed["reviewed_by_id"] != reviewer_id
        or sealed["review_status"] != "accepted"
        or sealed["applied_at"] is None
    ):
        raise HarnessError("SELFTEST_REVIEW_RECEIPT_INCOMPLETE")
    evidence = ProposalEvidence(
        project_id=UUID(project_id),
        proposal_id=UUID(proposal_id),
        route="flow_spec",
        review_status="accepted",
        materialized_resource_id=UUID(workflow_id),
        content_fingerprint=text_value(sealed["source_fingerprint"]),
        review_mode="ci_fixture",
        reviewer_id=UUID(reviewer_id),
    )
    result = ReviewedWorkflow(workflow=workflow, version=version, proposal=evidence)
    write_json(output_dir / "reviewed-workflow.json", result)
    return result


async def review_case(
    api: PublicAPI,
    *,
    project_id: str,
    reviewer_id: str,
    proposal_id: str,
    expected_definition: JsonObject,
    output_dir: Path,
) -> ReviewedCase:
    base = f"/mcp/write/change-sets/{proposal_id}"
    initial = object_value((await api.object("GET", base))["data"])
    if initial["project_id"] != project_id:
        raise HarnessError("SELFTEST_CASE_PROPOSAL_PROJECT_MISMATCH")
    governance = object_value(initial["governance"])
    if governance.get("manual_approval_required") is True:
        raise HarnessError("SELFTEST_FIXTURE_REVIEW_HIGH_RISK_BLOCKED")
    items = objects_value(initial["items"])
    cases = [item for item in items if item["item_type"] == "test_case"]
    if (
        len(cases) != 1
        or len(items) != 2
        or any(item["item_type"] not in {"test_case", "test_design"} for item in items)
    ):
        raise HarnessError("SELFTEST_CASE_PROPOSAL_ITEM_SCOPE")
    content = object_value(cases[0]["proposed_content"])
    _same_definition(
        expected_definition,
        object_value(content["definition"]),
        output_dir=output_dir,
        stage="case_proposal",
    )
    for item in items:
        if item["review_status"] != "pending":
            raise HarnessError("SELFTEST_CASE_REVIEW_NOT_PENDING")
        await api.object(
            "POST",
            base + f"/items/{item['id']}/accept",
            {"note": "隔离自测受控审核; review_mode=ci_fixture"},
        )
    sealed = object_value((await api.object("GET", base))["data"])
    accepted = next(item for item in objects_value(sealed["items"]) if item["id"] == cases[0]["id"])
    if accepted["review_status"] != "accepted" or accepted["reviewed_by_id"] != reviewer_id:
        raise HarnessError("SELFTEST_CASE_REVIEW_RECEIPT_INCOMPLETE")
    case_id = text_value(accepted["materialized_resource_id"])
    case = await api.object("GET", f"/projects/{project_id}/test-cases/{case_id}")
    _same_definition(
        expected_definition,
        object_value(case["draft_definition"]),
        output_dir=output_dir,
        stage="case_draft",
    )
    version = await api.object(
        "POST",
        f"/projects/{project_id}/test-cases/{case_id}/versions",
        {"change_note": "本轮 MCP 生成用例固定版本"},
    )
    _same_definition(
        expected_definition,
        object_value(version["definition"]),
        output_dir=output_dir,
        stage="case_version",
    )
    evidence = ProposalEvidence(
        project_id=UUID(project_id),
        proposal_id=UUID(proposal_id),
        item_id=UUID(text_value(accepted["id"])),
        route="controlled_write",
        review_status="accepted",
        materialized_resource_id=UUID(case_id),
        content_fingerprint=text_value(sealed["source_fingerprint"]),
        review_mode="ci_fixture",
        reviewer_id=UUID(reviewer_id),
    )
    result = ReviewedCase(case=case, version=version, proposal=evidence)
    write_json(output_dir / "reviewed-case.json", result)
    return result
