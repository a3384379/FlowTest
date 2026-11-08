"""Exact expected HTTP routes and bodies, independently derived from the frozen fixture."""

import copy
from dataclasses import dataclass
from typing import Literal

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import JsonObject, object_value, objects_value, text_value
from scripts.selftest.mcp_governance_verify import Finding, failure
from scripts.selftest.review_boundary_contracts import (
    ReviewManifest,
    ReviewObservation,
    ReviewScenario,
)

Method = Literal["GET", "POST", "PUT", "PATCH"]


@dataclass(frozen=True)
class ExpectedHTTP:
    method: Method
    path: str
    request_digest: str


def _expected(method: Method, path: str, body: JsonObject | None = None) -> ExpectedHTTP:
    return ExpectedHTTP(method, path, canonical_digest(body))


def _preview(
    manifest: ReviewManifest, row: ReviewObservation, root: str
) -> tuple[ExpectedHTTP, ...]:
    scope = manifest.scope
    body: JsonObject = {
        "environment_id": str(scope.fixture_environment_id),
        "executor_service_account_id": str(manifest.writer_machine_id),
        "budget": {
            "max_nodes": 10,
            "max_requests": 2,
            "max_dataset_rows": 1,
            "max_parallelism": 1,
            "max_runtime_seconds": 30,
        },
        "ttl_seconds": 180,
    }
    return (
        _expected("POST", root + "/preview-approvals", body),
        _expected(
            "POST",
            root + "/review",
            {"accept": True, "note": "review_mode=ci_fixture; 仅允许受限Preview"},
        ),
        _expected(
            "POST",
            root + "/preview-approvals",
            {**body, "environment_id": str(scope.production_environment_id)},
        ),
        _expected("POST", root + "/preview-approvals", body),
    )


def _high(row: ReviewObservation, root: str) -> tuple[ExpectedHTTP, ...]:
    item = objects_value(row.proposal_result["items"])[0]
    path = root + f"/items/{text_value(item['id'])}/accept"
    changed = copy.deepcopy(object_value(item["proposed_content"]))
    objects_value(changed["oracles"])[0]["expected"] = 201
    approval: JsonObject = {"approval_id": str(row.approval_id)}
    return (
        _expected("POST", root + "/approve", {"note": "只批准冻结原文; review_mode=ci_fixture"}),
        _expected("POST", path, {**approval, "content": changed}),
        _expected("POST", path, approval),
    )


def _partial(row: ReviewObservation, root: str) -> tuple[ExpectedHTTP, ...]:
    items = objects_value(row.proposal_result["items"])
    paths = [root + f"/items/{text_value(item['id'])}/accept" for item in items]
    return (
        _expected("POST", paths[0], {}),
        _expected("POST", paths[1], {}),
        _expected("GET", root),
        _expected("POST", paths[2], {}),
        _expected("POST", paths[0], {}),
    )


def expected_requests(
    manifest: ReviewManifest, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[ExpectedHTTP, ...]:
    project = str(manifest.scope.project_id)
    flow_root = f"/projects/{project}/flow-specs/change-sets/{row.proposal_id}"
    workflow = f"/projects/{project}/workflows/{row.workflow_id}"
    controlled = f"/mcp/write/change-sets/{row.proposal_id}"
    if scenario.action == "preview_cancel":
        return _preview(manifest, row, flow_root)
    if scenario.action == "unknown_publish":
        return (
            _expected("POST", flow_root + "/apply"),
            _expected("POST", workflow + "/versions", {"change_note": "本轮受限fixture发布"}),
            _expected("GET", workflow + "/versions"),
        )
    if scenario.action == "stale_proposal":
        return (
            _expected(
                "POST", flow_root + "/review", {"accept": True, "note": "review_mode=ci_fixture"}
            ),
            _expected(
                "PATCH",
                workflow,
                {
                    "expected_revision": 1,
                    "name": manifest.batch_key + "-" + scenario.transport + ":human-edit",
                },
            ),
            _expected("POST", flow_root + "/apply"),
        )
    if scenario.action == "stale_approval":
        return _high(row, controlled)
    if scenario.action == "concurrent_accept":
        item = objects_value(row.proposal_result["items"])[0]
        same = _expected("POST", controlled + f"/items/{text_value(item['id'])}/accept", {})
        return (same, same)
    return _partial(row, controlled)


def http_bindings(
    manifest: ReviewManifest, scenario: ReviewScenario, row: ReviewObservation
) -> tuple[Finding, ...]:
    required = expected_requests(manifest, scenario, row)
    actual = tuple(ExpectedHTTP(item.method, item.path, item.request_digest) for item in row.http)
    if actual != required:
        return (failure("REVIEW_EXACT_HTTP_REQUEST_BINDING_MISMATCH"),)
    return ()
