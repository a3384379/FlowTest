#!/usr/bin/env python3
"""Run the S47 generated-test, MCP, multi-service, and FlowSpec acceptance flow."""

from __future__ import annotations

import json
import os
import secrets
from typing import Any, cast
from urllib.request import urlopen

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _api_request, _start_and_wait


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json(
        "POST", "/auth/login", {"email": config.email, "password": config.password}
    )
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(
        cast(dict[str, Any], login["user"])["requires_password_change"]
    )
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


def _run_acceptance(
    client: APIClient, config: SmokeConfig, human_token: str
) -> dict[str, str]:
    source = _create_portable_project(
        client, config, human_token, "Source", ("orders", "billing")
    )
    source_workflow = _create_multi_service_workflow(client, human_token, source)
    source_execution = _publish_and_execute(
        client, human_token, source, source_workflow
    )
    flow_spec = _export_and_validate_flow_spec(
        client, human_token, source, source_workflow
    )

    target = _create_portable_project(
        client, config, human_token, "Target", ("orders-v2", "billing-v2")
    )
    imported_workflow = _import_review_apply(
        client, human_token, target, flow_spec, source_keys=("orders", "billing")
    )
    imported_execution = _publish_and_execute(
        client, human_token, target, imported_workflow
    )

    generated_workflows, mcp_trace, change_regression_id = (
        _verify_test_engineering_and_mcp(client, human_token, source)
    )
    generated_executions = []
    for workflow, scenario in generated_workflows:
        generated_executions.append(
            _publish_and_execute(client, human_token, source, workflow)
        )
        _verify_target_receipt(scenario)
    return {
        "source_project_id": str(source["project"]["id"]),
        "target_project_id": str(target["project"]["id"]),
        "source_execution_id": str(source_execution["execution"]["id"]),
        "imported_execution_id": str(imported_execution["execution"]["id"]),
        "generated_execution_id": str(generated_executions[0]["execution"]["id"]),
        "negative_execution_count": str(len(generated_executions)),
        "mcp_trace_id": mcp_trace,
        "change_regression_id": change_regression_id,
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
    for index, service_key in enumerate(service_keys):
        logical_key = ("orders", "billing")[index]
        service = client.json(
            "POST",
            f"/projects/{project_id}/services",
            {"service_key": service_key, "name": f"{label} {logical_key}"},
            token=token,
        )
        variant = ("blue", "canary")[index]
        client.json(
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
    return {
        "project": project,
        "environment": environment,
        "services": services,
        "apis": apis,
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
    if (
        not validated["validation"]["valid"]
        or validated["fingerprint"] != exported["fingerprint"]
    ):
        raise RuntimeError(
            f"S47 FlowSpec validation or fingerprint was unstable: {validated}"
        )
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
    operation_refs = {
        str(item["service_ref"]): str(item["ref"]) for item in spec["operations"]
    }
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
    api_id = str(
        cast(list[dict[str, Any]], baseline_import["results"])[0]["definition_id"]
    )
    baseline_generation = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/generate",
        {
            "api_definition_id": api_id,
            "generation_policy": {"max_scenarios": 1000},
        },
        token=human_token,
    )
    baseline_scenarios = cast(
        list[dict[str, Any]], baseline_generation["design"]["scenarios"]
    )
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
    baseline_workflow_id = str(cast(list[str], baseline_applied["workflow_ids"])[0])
    client.json(
        "POST",
        f"/projects/{project_id}/workflows/{baseline_workflow_id}/versions",
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
    current_api_id = str(
        cast(list[dict[str, Any]], current_import["results"])[0]["definition_id"]
    )
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
        client, human_token, project, project_id, api_id, generation["design"]
    )
    workflow_ids = cast(list[str], applied["workflow_ids"])
    if len(workflow_ids) != len(selected):
        raise RuntimeError(
            "S47.1 reviewed proposal did not materialize every selected scenario"
        )
    return (
        [
            ({"id": workflow_id}, scenario)
            for workflow_id, scenario in zip(workflow_ids, selected)
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
    run = client.json(
        "POST",
        f"/projects/{project_id}/change-regressions",
        {
            "title": "S47.1 maximum 100 to 999",
            "source_ref": "openapi://s47-1/orders",
            "candidate_ref": "contract:s47-1-current",
            "openapi_diffs": [
                {
                    "baseline_run_id": baseline_run["id"],
                    "current_run_id": current_run["id"],
                }
            ],
            "test_plan_id": plan["id"],
            "release_policy_id": policy["id"],
        },
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
    if values != {999, 1000}:
        raise RuntimeError(f"S47.1 semantic gaps were not 999/1000: {design}")
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
    return str(run["id"])


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
        raise RuntimeError(
            f"S47 MCP dry-run/idempotency contract failed: {first}, {second}"
        )
    return str(read["trace_id"])


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
        raise RuntimeError(
            f"S47.1 invalid body boundary did not reach target: {receipt}"
        )
    if kind == "invalid_type" and receipt["dry_run"] != "invalid":
        raise RuntimeError(f"S47.1 query mutation did not reach target: {receipt}")
    if kind == "format_invalid" and receipt["tenant_id"] != "not-a-uuid":
        raise RuntimeError(f"S47.1 path mutation did not reach target: {receipt}")
    if kind == "required_omitted" and receipt["tenant_header_present"] is not False:
        raise RuntimeError(f"S47.1 header omission did not reach target: {receipt}")
    if kind == "auth_missing" and receipt["authorization_present"] is not False:
        raise RuntimeError(f"S47.1 auth disable did not reach target: {receipt}")


def _s471_openapi(*, maximum: int) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S47.1 Orders", "version": "1.0.0"},
            "components": {
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}
            },
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
