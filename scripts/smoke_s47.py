#!/usr/bin/env python3
"""Run the S47 generated-test, MCP, multi-service, and FlowSpec acceptance flow."""

from __future__ import annotations

import json
import os
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast
from urllib.request import urlopen

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _api_request, _start_and_wait, _wait_for_completion

_CONTRACT_SECURITY_SENTINELS: Final = (
    "contract-password-sentinel",
    "contract-token-sentinel",
    "contract-person@example.test",
    "4111111111111111",
    "eyJhbGciOiJIUzI1NiJ9.c2Vuc2l0aXZl.c2lnbmF0dXJl",
)


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S47-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, config, token)
        print(json.dumps({"status": "passed", **result}, sort_keys=True))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, config: SmokeConfig, human_token: str) -> dict[str, str]:
    source = _create_portable_project(client, config, human_token, "Source", ("orders", "billing"))
    source_workflow = _create_multi_service_workflow(client, human_token, source)
    source_execution = _publish_and_execute(client, human_token, source, source_workflow)
    flow_spec = _export_and_validate_flow_spec(client, human_token, source, source_workflow)

    target = _create_portable_project(
        client, config, human_token, "Target", ("orders-v2", "billing-v2")
    )
    imported_workflow = _import_review_apply(
        client, human_token, target, flow_spec, source_keys=("orders", "billing")
    )
    imported_execution = _publish_and_execute(client, human_token, target, imported_workflow)

    generated_workflows, mcp_trace, change_regression_id = _verify_test_engineering_and_mcp(
        client, human_token, source
    )
    generated_executions = []
    for workflow, scenario in generated_workflows:
        generated_executions.append(_publish_and_execute(client, human_token, source, workflow))
        _verify_target_receipt(scenario)
    suppression_execution_ids = _verify_cross_layer_suppression(client, human_token, source)
    return {
        "source_project_id": str(source["project"]["id"]),
        "target_project_id": str(target["project"]["id"]),
        "source_execution_id": str(source_execution["execution"]["id"]),
        "imported_execution_id": str(imported_execution["execution"]["id"]),
        "generated_execution_id": str(generated_executions[0]["execution"]["id"]),
        "negative_execution_count": str(len(generated_executions)),
        "mcp_trace_id": mcp_trace,
        "change_regression_id": change_regression_id,
        "suppression_execution_count": str(len(suppression_execution_ids)),
        "suppression_execution_id": suppression_execution_ids[0],
    }


def _create_portable_project(
    client: APIClient,
    config: SmokeConfig,
    token: str,
    label: str,
    service_keys: tuple[str, str],
) -> dict[str, Any]:
    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S47 {label} {secrets.token_hex(5)}",
            "description": "S47 functional completion acceptance",
        },
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": f"{label} Compose", "base_url": config.target_url},
        token=token,
    )
    services: dict[str, dict[str, Any]] = {}
    apis: dict[str, dict[str, Any]] = {}
    endpoints: dict[str, dict[str, Any]] = {}
    for index, service_key in enumerate(service_keys):
        logical_key = ("orders", "billing")[index]
        service = client.json(
            "POST",
            f"/projects/{project_id}/services",
            {"service_key": service_key, "name": f"{label} {logical_key}"},
            token=token,
        )
        variant = ("blue", "canary")[index]
        endpoint = client.json(
            "POST",
            f"/projects/{project_id}/environments/{environment['id']}/service-endpoints",
            {
                "service_id": service["id"],
                "variant": variant,
                "base_url": config.target_url,
                "enabled": True,
            },
            token=token,
        )
        api = client.json(
            "POST",
            f"/projects/{project_id}/apis",
            {
                "name": f"{label} {logical_key} health",
                "description": "S47 portable operation",
                "service_id": service["id"],
                "request": _api_request("/health"),
            },
            token=token,
        )
        services[logical_key] = service
        apis[logical_key] = cast(dict[str, Any], api["definition"])
        endpoints[logical_key] = endpoint
    return {
        "project": project,
        "environment": environment,
        "services": services,
        "apis": apis,
        "endpoints": endpoints,
        "variants": {"orders": "blue", "billing": "canary"},
    }


def _create_multi_service_workflow(
    client: APIClient, token: str, assets: dict[str, Any]
) -> dict[str, Any]:
    apis = cast(dict[str, dict[str, Any]], assets["apis"])
    variants = cast(dict[str, str], assets["variants"])
    services = cast(dict[str, dict[str, Any]], assets["services"])
    nodes = [_node("start", "start", {})]
    for key in ("orders", "billing"):
        nodes.append(
            _node(
                key,
                "api",
                {
                    "api_definition_id": apis[key]["id"],
                    "api_version": 1,
                    "service_override": services[key]["service_key"],
                    "endpoint_variant": variants[key],
                    "expected_statuses": [200],
                },
            )
        )
    nodes.append(_node("end", "end", {}))
    return client.json(
        "POST",
        f"/projects/{assets['project']['id']}/workflows",
        {
            "name": "S47 Multi Service Workflow",
            "description": "Two services resolved through typed targets",
            "definition": {
                "schema_version": "1.0",
                "variables": {},
                "nodes": nodes,
                "edges": [
                    {"id": "start-orders", "source": "start", "target": "orders"},
                    {"id": "orders-billing", "source": "orders", "target": "billing"},
                    {"id": "billing-end", "source": "billing", "target": "end"},
                ],
                "settings": {},
            },
        },
        token=token,
    )


def _export_and_validate_flow_spec(
    client: APIClient,
    token: str,
    assets: dict[str, Any],
    workflow: dict[str, Any],
) -> dict[str, Any]:
    project_id = str(assets["project"]["id"])
    exported = client.json(
        "GET",
        f"/projects/{project_id}/flow-specs/workflows/{workflow['id']}/export",
        token=token,
    )
    spec = cast(dict[str, Any], exported["spec"])
    if len(spec["services"]) != 2 or len(spec["operations"]) != 2:
        raise RuntimeError(f"S47 FlowSpec lost multi-service semantics: {spec}")
    if str(assets["project"]["id"]) in str(exported["fingerprint"]):
        raise RuntimeError("S47 FlowSpec fingerprint contains a source instance UUID")
    validated = client.json(
        "POST",
        f"/projects/{project_id}/flow-specs/validate",
        {"spec": spec},
        token=token,
    )
    if not validated["validation"]["valid"] or validated["fingerprint"] != exported["fingerprint"]:
        raise RuntimeError(f"S47 FlowSpec validation or fingerprint was unstable: {validated}")
    return spec


def _import_review_apply(
    client: APIClient,
    token: str,
    target: dict[str, Any],
    spec: dict[str, Any],
    *,
    source_keys: tuple[str, str],
) -> dict[str, Any]:
    project_id = str(target["project"]["id"])
    services = cast(dict[str, dict[str, Any]], target["services"])
    apis = cast(dict[str, dict[str, Any]], target["apis"])
    operation_refs = {str(item["service_ref"]): str(item["ref"]) for item in spec["operations"]}
    service_mappings = {key: services[key]["id"] for key in source_keys}
    operation_mappings = {operation_refs[key]: apis[key]["id"] for key in source_keys}
    proposed = client.json(
        "POST",
        f"/projects/{project_id}/flow-specs/imports",
        {
            "spec": spec,
            "source_ref": "smoke://s47/cross-project",
            "service_mappings": service_mappings,
            "operation_mappings": operation_mappings,
        },
        token=token,
    )
    reviewed = client.json(
        "POST",
        f"/projects/{project_id}/flow-specs/change-sets/{proposed['id']}/review",
        {"accept": True, "note": "S47 cross-project mapping reviewed"},
        token=token,
    )
    if reviewed["review_status"] != "accepted":
        raise RuntimeError(f"S47 FlowSpec review failed: {reviewed}")
    applied = client.json(
        "POST",
        f"/projects/{project_id}/flow-specs/change-sets/{proposed['id']}/apply",
        token=token,
    )
    return {"id": applied["workflow_id"]}


def _verify_test_engineering_and_mcp(
    client: APIClient, human_token: str, assets: dict[str, Any]
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], str, str]:
    project = cast(dict[str, Any], assets["project"])
    project_id = str(project["id"])
    client.json(
        "PUT",
        f"/projects/{project_id}/secrets",
        {"name": "bearerAuth", "value": "mock-token"},
        token=human_token,
    )
    sensitive_api_id = _verify_contract_security(client, human_token, project_id)
    _verify_exclusive_boundary(client, human_token, assets)
    baseline_document = _s471_openapi(maximum=100)
    baseline_import = client.multipart(
        f"/projects/{project_id}/imports",
        field="document",
        filename="s47-1-orders-openapi.json",
        content=baseline_document,
        content_type="application/json",
        fields={"source_type": "openapi3"},
        token=human_token,
    )
    api_id = str(cast(list[dict[str, Any]], baseline_import["results"])[0]["definition_id"])
    baseline_generation = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/generate",
        {
            "api_definition_id": api_id,
            "generation_policy": {"max_scenarios": 1000},
        },
        token=human_token,
    )
    baseline_scenarios = cast(list[dict[str, Any]], baseline_generation["design"]["scenarios"])
    baseline_ids = [
        scenario["id"]
        for scenario in baseline_scenarios
        if scenario["kind"] in {"number_below_max", "number_at_max", "number_above_max"}
        and any(
            mutation["path"] == "body.quantity"
            for mutation in cast(list[dict[str, Any]], scenario["mutations"])
        )
    ]
    if len(baseline_ids) != 3:
        raise RuntimeError("S47.1 baseline generation did not produce 99/100/101")
    baseline_applied = _review_and_apply_generation(
        client,
        human_token,
        assets,
        api_id,
        baseline_ids,
        title="S47.1 Historical Boundaries",
    )
    baseline_workflow_ids = cast(list[str], baseline_applied["workflow_ids"])
    baseline_workflow_id = str(baseline_workflow_ids[0])
    for workflow_id in baseline_workflow_ids:
        client.json(
            "POST",
            f"/projects/{project_id}/workflows/{workflow_id}/versions",
            token=human_token,
        )
    current_document = _s471_openapi(maximum=999)
    current_import = client.multipart(
        f"/projects/{project_id}/imports",
        field="document",
        filename="s47-1-orders-openapi.json",
        content=current_document,
        content_type="application/json",
        fields={"source_type": "openapi3"},
        token=human_token,
    )
    current_api_id = str(cast(list[dict[str, Any]], current_import["results"])[0]["definition_id"])
    if current_api_id != api_id:
        raise RuntimeError("S47.1 re-import created a duplicate API definition")
    change_regression_id = _verify_change_regression(
        client,
        human_token,
        assets,
        api_id,
        baseline_workflow_id,
        baseline_document,
        current_document,
    )
    generation = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/generate",
        {
            "api_definition_id": api_id,
            "generation_policy": {"max_scenarios": 1000},
        },
        token=human_token,
    )
    scenarios = cast(list[dict[str, Any]], generation["design"]["scenarios"])
    selected = _required_s471_scenarios(scenarios)
    applied = _review_and_apply_generation(
        client,
        human_token,
        assets,
        api_id,
        [str(scenario["id"]) for scenario in selected],
        title=f"S47 Generated {secrets.token_hex(4)}",
    )
    mcp_trace = _verify_mcp_dry_run(
        client,
        human_token,
        project,
        project_id,
        api_id,
        sensitive_api_id,
        generation["design"],
    )
    workflow_ids = cast(list[str], applied["workflow_ids"])
    if len(workflow_ids) != len(selected):
        raise RuntimeError("S47.1 reviewed proposal did not materialize every selected scenario")
    return (
        [
            ({"id": workflow_id}, scenario)
            for workflow_id, scenario in zip(workflow_ids, selected, strict=True)
        ],
        mcp_trace,
        change_regression_id,
    )


def _review_and_apply_generation(
    client: APIClient,
    token: str,
    assets: dict[str, Any],
    api_definition_id: str,
    scenario_ids: list[str],
    *,
    title: str,
) -> dict[str, Any]:
    project_id = str(assets["project"]["id"])
    proposed = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/proposals",
        {
            "title": title,
            "api_definition_id": api_definition_id,
            "environment_id": assets["environment"]["id"],
            "scenario_ids": scenario_ids,
            "generation_policy": {"max_scenarios": 1000},
        },
        token=token,
    )
    if proposed["status"] != "draft" or proposed["applied"]:
        raise RuntimeError(f"S47 proposal bypassed Draft review: {proposed}")
    client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/proposals/{proposed['change_set_id']}/review",
        {"accept": True, "note": "S47 generated scenario reviewed"},
        token=token,
    )
    return client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/proposals/{proposed['change_set_id']}/apply",
        token=token,
    )


def _verify_change_regression(
    client: APIClient,
    token: str,
    assets: dict[str, Any],
    api_definition_id: str,
    mapped_workflow_id: str,
    baseline_document: bytes,
    current_document: bytes,
) -> str:
    project_id = str(assets["project"]["id"])
    baseline_run = _create_contract_run(
        client, token, project_id, baseline_document, "s47-1-baseline.json"
    )
    current_run = _create_contract_run(
        client, token, project_id, current_document, "s47-1-current.json"
    )
    client.json(
        "POST",
        f"/projects/{project_id}/impact/mappings",
        {
            "source_kind": "openapi",
            "source_selector": "POST /tenants/{tenantId}/orders",
            "target_type": "workflow",
            "target_id": mapped_workflow_id,
        },
        token=token,
    )
    plan = client.json(
        "POST",
        f"/projects/{project_id}/test-plans",
        {
            "name": f"S47.1 Semantic Plan {secrets.token_hex(4)}",
            "items": [
                {
                    "workflow_id": mapped_workflow_id,
                    "environment_id": assets["environment"]["id"],
                }
            ],
        },
        token=token,
    )
    policy = client.json(
        "POST",
        f"/projects/{project_id}/release-policies",
        {
            "name": f"S47.1 Semantic Policy {secrets.token_hex(4)}",
            "require_quality_gate": False,
            "require_contract_compatibility": False,
            "require_impact_evidence": False,
            "require_release_risk": False,
        },
        token=token,
    )
    run_payload = {
        "title": "S47.2 maximum 100 to 999",
        "source_ref": "openapi://s47-2/orders",
        "candidate_ref": "contract:s47-2-current",
        "openapi_diffs": [
            {
                "baseline_run_id": baseline_run["id"],
                "current_run_id": current_run["id"],
            }
        ],
        "test_plan_id": plan["id"],
        "release_policy_id": policy["id"],
    }
    run = client.json(
        "POST",
        f"/projects/{project_id}/change-regressions",
        run_payload,
        token=token,
    )
    if run["selection_summary"]["asset_coverage_gap_count"] != 0:
        raise RuntimeError(f"S47.1 asset mapping was not covered: {run}")
    missing = cast(list[dict[str, Any]], run["missing_tests"])
    if len(missing) != 1:
        raise RuntimeError(f"S47.1 semantic gap did not create one proposal: {run}")
    design = cast(dict[str, Any], missing[0]["proposed_content"])
    scenarios = cast(list[dict[str, Any]], design["scenarios"])
    values = {
        mutation.get("value")
        for scenario in scenarios
        for mutation in cast(list[dict[str, Any]], scenario["mutations"])
        if mutation["path"] == "body.quantity"
    }
    if values != {100, 101, 999, 1000}:
        raise RuntimeError(
            f"S47.3 Oracle-aware coverage did not preserve current-contract requirements: {design}"
        )
    scope = cast(list[dict[str, Any]], run["selection_summary"]["semantic_coverage_scopes"])[0]
    operation = cast(dict[str, Any], scope["operation"])
    target = cast(dict[str, Any], scope["target"])
    if (
        operation["api_definition_id"] != api_definition_id
        or operation["api_version"] != 2
        or not operation["contract_fingerprint"]
        or operation["method"] != "POST"
        or target["location"] != "body"
        or target["field_path"] != ["quantity"]
        or scope["project_known_coverage"] != "missing"
    ):
        raise RuntimeError(f"S47.4 v1 coverage suppressed v2 or lost operation identity: {scope}")
    selected_run = client.json(
        "POST",
        f"/projects/{project_id}/change-regressions/{run['id']}/operation-selection",
        {
            "change_key": scope["change_key"],
            "api_definition_id": api_definition_id,
            "api_version": operation["api_version"],
        },
        token=token,
    )
    regeneration = cast(
        list[dict[str, Any]],
        selected_run["selection_summary"]["operation_regenerations"],
    )[0]
    if (
        regeneration["status"] != "regenerated"
        or regeneration["contract_fingerprint"] != operation["contract_fingerprint"]
        or regeneration["scenario_count"] <= 0
        or regeneration["oracle_count"] <= 0
    ):
        raise RuntimeError(f"S47.4 Operation selection did not regenerate Proposal: {selected_run}")
    missing = cast(list[dict[str, Any]], selected_run["missing_tests"])
    design = cast(dict[str, Any], missing[0]["proposed_content"])
    scenarios = cast(list[dict[str, Any]], design["scenarios"])
    workflows_before = _workflow_ids(client, token, project_id)
    _expect_error_code(
        lambda: client.json(
            "POST",
            f"/projects/{project_id}/change-regressions/{run['id']}"
            f"/change-set-items/{missing[0]['item_id']}/accept",
            {
                "note": "S47.3 wrong target rejection",
                "materialization": {
                    "api_definition_id": assets["apis"]["billing"]["id"],
                    "environment_id": assets["environment"]["id"],
                    "scenario_ids": [scenario["id"] for scenario in scenarios],
                },
            },
            token=token,
        ),
        "CHANGE_REGRESSION_TARGET_MISMATCH",
    )
    accepted = client.json(
        "POST",
        f"/projects/{project_id}/change-regressions/{run['id']}"
        f"/change-set-items/{missing[0]['item_id']}/accept",
        {
            "note": "S47.1 semantic boundary reviewed",
            "materialization": {
                "api_definition_id": api_definition_id,
                "environment_id": assets["environment"]["id"],
                "scenario_ids": [scenario["id"] for scenario in scenarios],
            },
        },
        token=token,
    )
    accepted_item = cast(list[dict[str, Any]], accepted["missing_tests"])[0]
    if accepted_item["materialized_resource_type"] != "test_design_bundle":
        raise RuntimeError(f"S47.1 semantic proposal did not materialize: {accepted}")
    materialized_workflows = _workflow_ids(client, token, project_id) - workflows_before
    if not materialized_workflows:
        raise RuntimeError("S47.2 semantic proposal did not create executable Workflows")
    for workflow_id in materialized_workflows:
        client.json(
            "POST",
            f"/projects/{project_id}/workflows/{workflow_id}/versions",
            token=token,
        )
    scoped_payload = {
        **run_payload,
        "title": "S47.2 current TestPlan semantic scope",
        "candidate_ref": "contract:s47-2-current-plan-scope",
    }
    scoped_run = client.json(
        "POST",
        f"/projects/{project_id}/change-regressions",
        scoped_payload,
        token=token,
    )
    scoped = cast(
        list[dict[str, Any]],
        scoped_run["selection_summary"]["semantic_coverage_scopes"],
    )[0]
    recommendations = cast(
        list[dict[str, Any]], scoped_run["selection_summary"]["current_plan_recommendations"]
    )
    if (
        scoped["project_known_coverage"] != "covered"
        or scoped["current_test_plan_coverage"] != "missing"
        or not recommendations
        or recommendations[0]["action"] != "add_project_known_test_to_current_plan"
    ):
        raise RuntimeError(f"S47.2 current TestPlan scope was incorrect: {scoped_run}")
    _verify_current_plan_gate(client, token, project_id, scoped_run)
    return str(scoped_run["id"])


def _verify_current_plan_gate(
    client: APIClient,
    token: str,
    project_id: str,
    scoped_run: dict[str, Any],
) -> None:
    gaps = cast(list[dict[str, Any]], scoped_run["selection_summary"]["current_plan_gaps"])
    if not gaps or scoped_run["selection_summary"]["unresolved_current_plan_gap_count"] <= 0:
        raise RuntimeError(f"S47.3 current TestPlan gate did not identify blockers: {scoped_run}")
    _expect_error_code(
        lambda: client.json(
            "POST",
            f"/projects/{project_id}/change-regressions/{scoped_run['id']}/approve",
            {"note": "S47.3 unresolved plan gap must block"},
            token=token,
        ),
        "CHANGE_REGRESSION_PLAN_GAP_UNRESOLVED",
    )
    expiry = (datetime.now(UTC) + timedelta(seconds=3)).isoformat()
    for gap in gaps:
        first_revision = client.json(
            "POST",
            f"/projects/{project_id}/change-regressions/{scoped_run['id']}/semantic-gap-waivers",
            {
                "gap_key": gap["gap_key"],
                "reason": "S47.4 Compose 首次临时人工逐项风险豁免",
                "expires_at": expiry,
            },
            token=token,
        )
        active = [
            item
            for item in first_revision["semantic_gap_waivers"]
            if item["active"] and item["gap_key"] == gap["gap_key"]
        ]
        if len(active) != 1 or active[0]["revision"] != 1:
            raise RuntimeError(f"S47.4 first waiver revision was not active: {first_revision}")
    time.sleep(3.5)
    renewed_run = scoped_run
    for gap in gaps:
        renewed_run = client.json(
            "POST",
            f"/projects/{project_id}/change-regressions/{scoped_run['id']}/semantic-gap-waivers",
            {
                "gap_key": gap["gap_key"],
                "reason": "S47.4 原豁免过期后人工复核并续签补偿性回归",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            token=token,
        )
    active_revisions = [item for item in renewed_run["semantic_gap_waivers"] if item["active"]]
    if (
        {item["revision"] for item in active_revisions} != {2}
        or not all(item["supersedes_waiver_id"] for item in active_revisions)
        or len(renewed_run["semantic_gap_waivers"]) != len(gaps) * 2
    ):
        raise RuntimeError(f"S47.4 waiver revision lifecycle was incorrect: {renewed_run}")
    approved = client.json(
        "POST",
        f"/projects/{project_id}/change-regressions/{scoped_run['id']}/approve",
        {"note": "S47.4 audited renewed per-gap waivers"},
        token=token,
    )
    if approved["selection_summary"]["waived_current_plan_gap_count"] != len(gaps):
        raise RuntimeError(f"S47.4 waivers did not close the plan gate: {approved}")
    client.json(
        "POST",
        f"/projects/{project_id}/change-regressions/{scoped_run['id']}/execute",
        token=token,
    )
    evidence_ready = _wait_for_change_regression_evidence(
        client, token, project_id, str(scoped_run["id"])
    )
    released = client.json(
        "POST",
        f"/projects/{project_id}/change-regressions/{scoped_run['id']}/release-gate",
        token=token,
    )
    release_waivers = cast(list[dict[str, Any]], released["evidence"]["semantic_gap_waivers"])
    if (
        evidence_ready["status"] != "evidence_ready"
        or released["status"] != "passed"
        or {item["revision"] for item in release_waivers} != {2}
    ):
        raise RuntimeError(f"S47.4 renewed waiver release evidence was incorrect: {released}")


def _wait_for_change_regression_evidence(
    client: APIClient,
    token: str,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        run = client.json(
            "GET",
            f"/projects/{project_id}/change-regressions/{run_id}",
            token=token,
        )
        if run["status"] == "evidence_ready":
            return run
        if run["status"] in {"blocked", "failed"}:
            raise RuntimeError(f"S47.4 renewed waiver execution failed: {run}")
        time.sleep(0.5)
    raise RuntimeError("S47.4 renewed waiver execution timed out")


def _expect_error_code(action: Callable[[], object], code: str) -> None:
    try:
        action()
    except RuntimeError as error:
        if code not in str(error):
            raise
        return
    raise RuntimeError(f"Expected API error {code}")


def _workflow_ids(client: APIClient, token: str, project_id: str) -> set[str]:
    page = client.json("GET", f"/projects/{project_id}/workflows?page=1&page_size=100", token=token)
    return {str(item["id"]) for item in cast(list[dict[str, Any]], page["items"])}


def _create_contract_run(
    client: APIClient,
    token: str,
    project_id: str,
    document: bytes,
    filename: str,
) -> dict[str, Any]:
    return client.multipart(
        f"/projects/{project_id}/contract-runs",
        field="document",
        filename=filename,
        content=document,
        content_type="application/json",
        token=token,
    )


def _verify_mcp_dry_run(
    client: APIClient,
    human_token: str,
    project: dict[str, Any],
    project_id: str,
    api_definition_id: str,
    sensitive_api_definition_id: str,
    design: dict[str, Any],
) -> str:
    organization_id = project.get("organization_id")
    if not organization_id:
        raise RuntimeError("S47 project is missing organization isolation")
    issued = client.json(
        "POST",
        f"/organizations/{organization_id}/service-accounts",
        {
            "name": f"S47 MCP {secrets.token_hex(4)}",
            "account_key": f"s47-{secrets.token_hex(8)}",
            "scopes": ["mcp:read", "mcp:write", "project:read", "project:write"],
        },
        token=human_token,
    )
    mcp_token = str(issued["token"])
    read = client.json(
        "POST",
        f"/mcp/read/projects/{project_id}/test-design/generate",
        {"api_definition_id": api_definition_id},
        token=mcp_token,
    )
    if read["data"]["fingerprint"] == "" or not read["evidence_refs"]:
        raise RuntimeError(f"S47 MCP read did not return traceable generation: {read}")
    sensitive_read = client.json(
        "POST",
        f"/mcp/read/projects/{project_id}/test-design/generate",
        {"api_definition_id": sensitive_api_definition_id},
        token=mcp_token,
    )
    _assert_no_contract_sentinels(sensitive_read, "MCP response")
    source_evidence = client.json(
        "POST",
        f"/mcp/read/projects/{project_id}/evidence/source",
        {
            "repository_url": "https://example.test/s47-4-conditional.git",
            "commit": "abcdef1234567",
            "allowlist_paths": ["app"],
            "files": [
                {
                    "path": "app/limits.py",
                    "language": "python",
                    "content": (
                        "def validate_limit(mode, limit):\n"
                        '    if mode == "special":\n'
                        "        assert limit <= 10\n"
                    ),
                }
            ],
        },
        token=mcp_token,
    )
    findings = cast(list[dict[str, Any]], source_evidence["data"]["findings"])
    conditional = [
        finding
        for finding in findings
        if finding["structured_data"].get("context") == "conditional-assert"
    ]
    if (
        len(conditional) != 1
        or conditional[0]["kind"] != "supporting_condition"
        or conditional[0]["deterministic"] is not False
        or conditional[0]["structured_data"].get("requires_review") is not True
        or any(
            finding["kind"] == "validation_constraint"
            and finding["structured_data"].get("maximum") == 10
            for finding in findings
        )
    ):
        raise RuntimeError(f"S47.4 conditional AST leaked a global boundary: {source_evidence}")
    key = f"s47-preview-{secrets.token_hex(8)}"
    payload = {
        "project_id": project_id,
        "idempotency_key": key,
        "dry_run": True,
        "title": "S47 MCP Preview",
        "source_ref": "mcp://controlled-writes/s47-smoke",
        "confidence": 1,
        "risk_level": "low",
        "design": design,
        "test_cases": [],
    }
    first = client.json("POST", "/mcp/write/change-sets", payload, token=mcp_token)
    second = client.json("POST", "/mcp/write/change-sets", payload, token=mcp_token)
    preview = cast(dict[str, Any], first["data"])
    if (
        first["data"] != second["data"]
        or preview["preview"] is not True
        or preview["persisted"] is not False
        or preview["project_id"] != project_id
        or preview["item_count"] != 1
        or not preview["design_fingerprint"]
    ):
        raise RuntimeError(f"S47 MCP dry-run/idempotency contract failed: {first}, {second}")
    return str(read["trace_id"])


def _verify_contract_security(client: APIClient, token: str, project_id: str) -> str:
    imported = client.multipart(
        f"/projects/{project_id}/imports",
        field="document",
        filename="s47-2-contract-security.json",
        content=_s472_sensitive_openapi(),
        content_type="application/json",
        fields={"source_type": "openapi3"},
        token=token,
    )
    definition_id = str(cast(list[dict[str, Any]], imported["results"])[0]["definition_id"])
    detail = client.json("GET", f"/projects/{project_id}/apis/{definition_id}", token=token)
    if detail["version"]["contract_completeness"] != "redacted_partial":
        raise RuntimeError("S47.2 sensitive Enum did not mark the contract redacted_partial")
    _assert_no_contract_sentinels(detail, "API response")
    generated = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/generate",
        {"api_definition_id": definition_id},
        token=token,
    )
    if generated["contract_completeness"] != "redacted_partial":
        raise RuntimeError("S47.2 Test Engineering lost contract redaction completeness")
    _assert_no_contract_sentinels(generated, "TestDesign")
    return definition_id


def _verify_exclusive_boundary(client: APIClient, token: str, assets: dict[str, Any]) -> None:
    project_id = str(assets["project"]["id"])
    imported = client.multipart(
        f"/projects/{project_id}/imports",
        field="document",
        filename="s47-2-exclusive.json",
        content=_s472_exclusive_openapi(),
        content_type="application/json",
        fields={"source_type": "openapi3"},
        token=token,
    )
    definition_id = str(cast(list[dict[str, Any]], imported["results"])[0]["definition_id"])
    generated = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/generate",
        {"api_definition_id": definition_id, "generation_policy": {"max_scenarios": 100}},
        token=token,
    )
    scenarios = cast(list[dict[str, Any]], generated["design"]["scenarios"])
    expected = {
        ("number_below_exclusive_max", "body.upper"): 998,
        ("number_at_exclusive_max", "body.upper"): 999,
        ("number_at_exclusive_min", "body.lower"): 1,
        ("number_above_exclusive_min", "body.lower"): 2,
    }
    selected: list[dict[str, Any]] = []
    for (kind, path), expected_value in expected.items():
        scenario = next(
            (
                item
                for item in scenarios
                if item["kind"] == kind
                and any(
                    mutation["path"] == path and mutation.get("value") == expected_value
                    for mutation in cast(list[dict[str, Any]], item["mutations"])
                )
            ),
            None,
        )
        if scenario is None:
            raise RuntimeError(f"S47.2 exclusive boundary is missing {kind}:{path}")
        selected.append(scenario)
    applied = _review_and_apply_generation(
        client,
        token,
        assets,
        definition_id,
        [str(scenario["id"]) for scenario in selected],
        title=f"S47.2 Exclusive Boundary {secrets.token_hex(4)}",
    )
    workflow_ids = cast(list[str], applied["workflow_ids"])
    for workflow_id, scenario in zip(workflow_ids, selected, strict=True):
        _publish_and_execute(client, token, assets, {"id": workflow_id})
        _verify_exclusive_receipt(scenario)


def _assert_no_contract_sentinels(payload: object, boundary: str) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if any(value in encoded for value in _CONTRACT_SECURITY_SENTINELS):
        raise RuntimeError(f"S47.2 canonical contract leaked a sensitive value at {boundary}")


def _required_s471_scenarios(
    scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required = (
        ("number_at_max", "body.quantity"),
        ("number_above_max", "body.quantity"),
        ("invalid_type", "query.dryRun"),
        ("format_invalid", "path.tenantId"),
        ("required_omitted", "header.X-Tenant-Id"),
        ("auth_missing", "auth"),
    )
    selected: list[dict[str, Any]] = []
    for kind, path in required:
        match = next(
            (
                scenario
                for scenario in scenarios
                if scenario["kind"] == kind
                and any(
                    mutation["path"] == path
                    for mutation in cast(list[dict[str, Any]], scenario["mutations"])
                )
            ),
            None,
        )
        if match is None:
            raise RuntimeError(f"S47.1 generated design is missing {kind} for {path}")
        selected.append(match)
    return selected


def _verify_cross_layer_suppression(
    client: APIClient, token: str, assets: dict[str, Any]
) -> list[str]:
    project_id = str(assets["project"]["id"])
    environment_id = str(assets["environment"]["id"])
    layer_headers = {
        "Authorization": "Bearer layer-sentinel",
        "X-Tenant-Id": "layer-sentinel",
        "Cookie": "session=layer-sentinel; keep=layer",
    }
    client.json(
        "PUT",
        f"/projects/{project_id}/configuration",
        {"variables": {}, "headers": layer_headers},
        token=token,
    )
    client.json(
        "PATCH",
        f"/projects/{project_id}/environments/{environment_id}",
        {"headers": layer_headers},
        token=token,
    )
    endpoint_id = str(assets["endpoints"]["orders"]["id"])
    client.json(
        "PATCH",
        f"/projects/{project_id}/service-endpoints/{endpoint_id}",
        {"headers": layer_headers},
        token=token,
    )
    cases: list[
        tuple[
            str,
            dict[str, Any],
            list[dict[str, Any]],
            dict[str, str],
            dict[str, str],
            dict[str, Any],
        ]
    ] = [
        (
            "bearer-cross-layer",
            {"kind": "bearer", "values": {"token": "api-bearer-sentinel"}},
            [{"name": "api_key", "value": "api-query-sentinel", "enabled": True}],
            {
                "Authorization": "Bearer api-sentinel",
                "X-Tenant-Id": "api-sentinel",
                "Cookie": "session=api-sentinel; keep=api",
                "X-Service-Metadata": "orders",
            },
            {
                "Authorization": "Bearer runtime-sentinel",
                "X-Tenant-Id": "runtime-sentinel",
                "Cookie": "session=runtime-sentinel; keep=runtime",
            },
            {
                "auth_mode": "disabled",
                "suppressed_headers": ["x-tenant-id"],
                "suppressed_query_parameters": ["api_key"],
                "suppressed_cookies": ["session"],
            },
        ),
        (
            "basic-auth",
            {
                "kind": "basic",
                "values": {
                    "username": "basic-user-sentinel",
                    "password": "basic-password-sentinel",
                },
            },
            [],
            {"X-Service-Metadata": "orders"},
            {},
            {"auth_mode": "disabled"},
        ),
        (
            "api-key-query",
            {
                "kind": "api_key",
                "values": {
                    "in": "query",
                    "name": "api_key",
                    "value": "query-auth-sentinel",
                },
            },
            [{"name": "api_key", "value": "api-query-sentinel", "enabled": True}],
            {"X-Service-Metadata": "orders"},
            {},
            {"auth_mode": "disabled"},
        ),
        (
            "api-key-cookie",
            {
                "kind": "api_key",
                "values": {
                    "in": "cookie",
                    "name": "auth_session",
                    "value": "cookie-auth-sentinel",
                },
            },
            [],
            {
                "Cookie": "auth_session=api-sentinel; keep=api",
                "X-Service-Metadata": "orders",
            },
            {"Cookie": "auth_session=runtime-sentinel; keep=runtime"},
            {"auth_mode": "disabled"},
        ),
    ]
    return [
        _execute_suppression_case(
            client,
            token,
            assets,
            label=label,
            auth=auth,
            query_parameters=query_parameters,
            api_headers=api_headers,
            runtime_headers=runtime_headers,
            request_overrides=request_overrides,
        )
        for (
            label,
            auth,
            query_parameters,
            api_headers,
            runtime_headers,
            request_overrides,
        ) in cases
    ]


def _execute_suppression_case(
    client: APIClient,
    token: str,
    assets: dict[str, Any],
    *,
    label: str,
    auth: dict[str, Any],
    query_parameters: list[dict[str, Any]],
    api_headers: dict[str, str],
    runtime_headers: dict[str, str],
    request_overrides: dict[str, Any],
) -> str:
    project_id = str(assets["project"]["id"])
    effective_overrides = {
        "suppressed_headers": ["x-tenant-id"],
        "suppressed_query_parameters": ["api_key"],
        "suppressed_cookies": ["session"],
        **request_overrides,
    }
    definition = cast(
        dict[str, Any],
        client.json(
            "POST",
            f"/projects/{project_id}/apis",
            {
                "name": f"S47.2 suppression {label} {secrets.token_hex(3)}",
                "service_id": assets["services"]["orders"]["id"],
                "request": {
                    "method": "POST",
                    "path": "/s47-2/inspect",
                    "query_parameters": query_parameters,
                    "headers": api_headers,
                    "body_kind": "none",
                    "body": None,
                    "auth": auth,
                },
            },
            token=token,
        )["definition"],
    )
    workflow = client.json(
        "POST",
        f"/projects/{project_id}/workflows",
        {
            "name": f"S47.2 suppression {label} {secrets.token_hex(3)}",
            "definition": {
                "schema_version": "1.0",
                "variables": {},
                "nodes": [
                    _node("start", "start", {}),
                    _node(
                        "api",
                        "api",
                        {
                            "api_definition_id": definition["id"],
                            "api_version": 1,
                            "endpoint_variant": assets["variants"]["orders"],
                            "expected_statuses": [200],
                            "request_overrides": effective_overrides,
                        },
                    ),
                    _node("end", "end", {}),
                ],
                "edges": [
                    {"id": "start-api", "source": "start", "target": "api"},
                    {"id": "api-end", "source": "api", "target": "end"},
                ],
                "settings": {},
            },
        },
        token=token,
    )
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    started = client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/executions",
        {
            "environment_id": assets["environment"]["id"],
            "runtime_headers": runtime_headers,
        },
        token=token,
    )
    detail = _wait_for_completion(client, token, project_id, str(started["id"]))
    if detail["execution"]["status"] != "passed":
        raise RuntimeError(f"S47.2 suppression execution failed: {detail}")
    suppression = detail["execution"]["snapshot"]["apis"]["api"]["target"]["request_suppression"]
    if suppression["auth_mode"] != "disabled":
        raise RuntimeError(f"S47.2 auth mode was not snapshotted: {suppression}")
    encoded_snapshot = json.dumps(detail["execution"]["snapshot"], sort_keys=True)
    if "sentinel" in encoded_snapshot:
        paths = _matching_string_paths(detail["execution"]["snapshot"], "sentinel")
        raise RuntimeError(
            "S47.2 execution snapshot retained a credential sentinel at " + ", ".join(paths)
        )
    receipt = _read_s472_receipt()
    if any(
        receipt[key]
        for key in (
            "authorization_present",
            "tenant_header_present",
            "api_key_present",
            "auth_cookie_present",
        )
    ):
        raise RuntimeError(f"S47.2 {label} suppression leaked a carrier to the target: {receipt}")
    if receipt["service_metadata"] != "orders":
        raise RuntimeError(f"S47.2 service metadata was lost: {receipt}")
    return str(started["id"])


def _matching_string_paths(value: Any, marker: str, *, path: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [
            matched
            for key, child in value.items()
            for matched in _matching_string_paths(child, marker, path=f"{path}.{key}")
        ]
    if isinstance(value, list):
        return [
            matched
            for index, child in enumerate(value)
            for matched in _matching_string_paths(child, marker, path=f"{path}[{index}]")
        ]
    if isinstance(value, str) and marker in value:
        return [path]
    return []


def _read_s472_receipt() -> dict[str, Any]:
    public_target = os.environ.get(
        "FLOWTEST_SMOKE_PUBLIC_TARGET_URL", "http://127.0.0.1:8080"
    ).rstrip("/")
    with urlopen(f"{public_target}/s47-2/requests/last", timeout=10) as response:
        return cast(dict[str, Any], json.loads(response.read()))


def _verify_exclusive_receipt(scenario: dict[str, Any]) -> None:
    public_target = os.environ.get(
        "FLOWTEST_SMOKE_PUBLIC_TARGET_URL", "http://127.0.0.1:8080"
    ).rstrip("/")
    with urlopen(f"{public_target}/s47-2/exclusive/last", timeout=10) as response:
        receipt = cast(dict[str, Any], json.loads(response.read()))
    mutation = cast(list[dict[str, Any]], scenario["mutations"])[0]
    field = str(mutation["path"]).removeprefix("body.")
    if cast(dict[str, Any], receipt["body"]).get(field) != mutation.get("value"):
        raise RuntimeError(f"S47.2 exclusive boundary did not reach the target: {receipt}")


def _verify_target_receipt(scenario: dict[str, Any]) -> None:
    public_target = os.environ.get(
        "FLOWTEST_SMOKE_PUBLIC_TARGET_URL", "http://127.0.0.1:8080"
    ).rstrip("/")
    with urlopen(f"{public_target}/s47-1/requests/last", timeout=10) as response:
        receipt = cast(dict[str, Any], json.loads(response.read()))
    kind = str(scenario["kind"])
    if kind == "number_at_max" and receipt["body"]["quantity"] != 999:
        raise RuntimeError(f"S47.1 body boundary did not reach target: {receipt}")
    if kind == "number_above_max" and receipt["body"]["quantity"] != 1000:
        raise RuntimeError(f"S47.1 invalid body boundary did not reach target: {receipt}")
    if kind == "invalid_type" and receipt["dry_run"] != "invalid":
        raise RuntimeError(f"S47.1 query mutation did not reach target: {receipt}")
    if kind == "format_invalid" and receipt["tenant_id"] != "not-a-uuid":
        raise RuntimeError(f"S47.1 path mutation did not reach target: {receipt}")
    if kind == "required_omitted" and receipt["tenant_header_present"] is not False:
        raise RuntimeError(f"S47.1 header omission did not reach target: {receipt}")
    if kind == "auth_missing" and receipt["authorization_present"] is not False:
        raise RuntimeError(f"S47.1 auth disable did not reach target: {receipt}")


def _s472_sensitive_openapi() -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S47.2 Contract Security", "version": "1.0.0"},
            "paths": {
                "/s47-2/security-contract": {
                    "post": {
                        "operationId": "verifyContractSecurity",
                        "parameters": [
                            {
                                "name": "contact",
                                "in": "query",
                                "schema": {
                                    "type": "string",
                                    "example": _CONTRACT_SECURITY_SENTINELS[2],
                                },
                            }
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "password": {
                                                "type": "string",
                                                "example": _CONTRACT_SECURITY_SENTINELS[0],
                                            },
                                            "token": {
                                                "type": "string",
                                                "default": _CONTRACT_SECURITY_SENTINELS[1],
                                            },
                                            "card": {
                                                "type": "string",
                                                "const": _CONTRACT_SECURITY_SENTINELS[3],
                                            },
                                            "credential": {
                                                "type": "string",
                                                "enum": [
                                                    "NORMAL",
                                                    _CONTRACT_SECURITY_SENTINELS[4],
                                                ],
                                            },
                                            "nested": {
                                                "type": "array",
                                                "items": {
                                                    "oneOf": [
                                                        {
                                                            "type": "string",
                                                            "example": _CONTRACT_SECURITY_SENTINELS[
                                                                1
                                                            ],
                                                        },
                                                        {"type": "integer"},
                                                    ]
                                                },
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "safe",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "allOf": [
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "email": {
                                                            "type": "string",
                                                            "example": _CONTRACT_SECURITY_SENTINELS[
                                                                2
                                                            ],
                                                        }
                                                    },
                                                }
                                            ]
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        },
        ensure_ascii=False,
    ).encode()


def _s472_exclusive_openapi() -> bytes:
    return json.dumps(
        {
            "openapi": "3.1.0",
            "info": {"title": "S47.2 Exclusive", "version": "1.0.0"},
            "paths": {
                "/s47-2/exclusive": {
                    "post": {
                        "operationId": "verifyExclusiveBoundary",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["upper", "lower"],
                                        "properties": {
                                            "upper": {
                                                "type": "integer",
                                                "exclusiveMaximum": 999,
                                            },
                                            "lower": {
                                                "type": "integer",
                                                "exclusiveMinimum": 1,
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {"description": "valid"},
                            "400": {"description": "invalid"},
                        },
                    }
                }
            },
        },
        ensure_ascii=False,
    ).encode()


def _s471_openapi(*, maximum: int) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S47.1 Orders", "version": "1.0.0"},
            "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
            "paths": {
                "/tenants/{tenantId}/orders": {
                    "post": {
                        "operationId": "createTenantOrder",
                        "security": [{"bearerAuth": []}],
                        "parameters": [
                            {
                                "name": "tenantId",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            },
                            {
                                "name": "dryRun",
                                "in": "query",
                                "schema": {"type": "boolean"},
                            },
                            {
                                "name": "X-Tenant-Id",
                                "in": "header",
                                "required": True,
                                "schema": {"type": "string", "minLength": 1},
                            },
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["quantity", "type", "profile"],
                                        "properties": {
                                            "quantity": {
                                                "type": "integer",
                                                "minimum": 1,
                                                "maximum": maximum,
                                            },
                                            "type": {
                                                "type": "string",
                                                "enum": ["NORMAL", "PRIORITY"],
                                            },
                                            "remark": {
                                                "type": "string",
                                                "maxLength": 20,
                                            },
                                            "profile": {
                                                "type": "object",
                                                "required": ["display_name"],
                                                "properties": {
                                                    "display_name": {
                                                        "type": "string",
                                                        "minLength": 1,
                                                    }
                                                },
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "created",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["id", "accepted"],
                                            "properties": {
                                                "id": {"type": "string"},
                                                "accepted": {"type": "boolean"},
                                            },
                                        }
                                    }
                                },
                            },
                            "400": {"description": "invalid request"},
                            "401": {"description": "unauthorized"},
                        },
                    }
                }
            },
        },
        ensure_ascii=False,
    ).encode()


def _publish_and_execute(
    client: APIClient, token: str, assets: dict[str, Any], workflow: dict[str, Any]
) -> dict[str, Any]:
    project_id = str(assets["project"]["id"])
    workflow_id = str(workflow["id"])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{workflow_id}/versions",
        token=token,
    )
    result = _start_and_wait(
        client,
        token,
        project_id,
        workflow_id,
        str(assets["environment"]["id"]),
    )
    if result["execution"]["status"] != "passed":
        raise RuntimeError(f"S47 workflow execution failed: {result}")
    return result


def _node(node_id: str, node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": node_id.title(),
        "position": {"x": 0, "y": 0},
        "config": config,
    }


if __name__ == "__main__":
    main()
