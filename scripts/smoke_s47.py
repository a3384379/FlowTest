#!/usr/bin/env python3
"""Run the S47 generated-test, MCP, multi-service, and FlowSpec acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password
from smoke_s5 import _api_request, _start_and_wait


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

    generated_workflow, mcp_trace = _verify_test_engineering_and_mcp(client, human_token, source)
    generated_execution = _publish_and_execute(client, human_token, source, generated_workflow)
    return {
        "source_project_id": str(source["project"]["id"]),
        "target_project_id": str(target["project"]["id"]),
        "source_execution_id": str(source_execution["execution"]["id"]),
        "imported_execution_id": str(imported_execution["execution"]["id"]),
        "generated_execution_id": str(generated_execution["execution"]["id"]),
        "mcp_trace_id": mcp_trace,
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
) -> tuple[dict[str, Any], str]:
    project = cast(dict[str, Any], assets["project"])
    project_id = str(project["id"])
    api_id = str(cast(dict[str, dict[str, Any]], assets["apis"])["orders"]["id"])
    contract = {
        "operation": "orders.health",
        "method": "GET",
        "path": "/health",
        "responses": {"200": {"description": "healthy"}},
    }
    generation = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/generate",
        {"contract": contract},
        token=human_token,
    )
    happy = next(
        item
        for item in cast(list[dict[str, Any]], generation["design"]["scenarios"])
        if item["kind"] == "happy_path"
    )
    proposed = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/proposals",
        {
            "title": f"S47 Generated {secrets.token_hex(4)}",
            "api_definition_id": api_id,
            "environment_id": assets["environment"]["id"],
            "contract": contract,
            "scenario_ids": [happy["id"]],
        },
        token=human_token,
    )
    if proposed["status"] != "draft" or proposed["applied"]:
        raise RuntimeError(f"S47 proposal bypassed Draft review: {proposed}")
    client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/proposals/{proposed['change_set_id']}/review",
        {"accept": True, "note": "S47 generated scenario reviewed"},
        token=human_token,
    )
    applied = client.json(
        "POST",
        f"/projects/{project_id}/test-engineering/proposals/{proposed['change_set_id']}/apply",
        token=human_token,
    )
    mcp_trace = _verify_mcp_dry_run(
        client, human_token, project, project_id, contract, generation["design"]
    )
    return {"id": applied["workflow_ids"][0]}, mcp_trace


def _verify_mcp_dry_run(
    client: APIClient,
    human_token: str,
    project: dict[str, Any],
    project_id: str,
    contract: dict[str, Any],
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
        {"contract": contract},
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
        raise RuntimeError(f"S47 MCP dry-run/idempotency contract failed: {first}, {second}")
    return str(read["trace_id"])


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
