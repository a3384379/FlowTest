#!/usr/bin/env python3
"""Run the S28 multi-source change impact and smart-selection acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _change_password


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(cast(dict[str, Any], login["user"])["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-S28-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, token: str) -> dict[str, str]:
    features = client.json("GET", "/v3/features", token=token)
    if not features.get("impact_engine") or not features.get("multi_protocol"):
        raise RuntimeError(f"S28 impact or multi-protocol feature is not enabled: {features}")
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S28 Impact {secrets.token_hex(5)}", "description": "S28 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    baseline_contract = _upload_openapi(client, token, project_id, required=False, version="1")
    current_contract = _upload_openapi(client, token, project_id, required=True, version="2")
    graphql = _create_graphql_versions(client, token, project_id)
    grpc = _create_grpc_versions(client, token, project_id)
    root = f"/projects/{project_id}/impact"
    mappings = (
        ("git", "backend/orders.py"),
        ("openapi", "POST /orders"),
        ("graphql", "Query.order"),
        ("grpc", "sample.Request.value"),
    )
    for source_kind, selector in mappings:
        client.json(
            "POST",
            f"{root}/mappings",
            {
                "source_kind": source_kind,
                "source_selector": selector,
                "target_type": "openapi_contract",
                "target_id": current_contract["id"],
            },
            token=token,
        )
    result = client.json(
        "POST",
        f"{root}/runs",
        {
            "title": "S28 Compose 四源影响分析",
            "source_ref": "compose/s28",
            "git_diff": (
                "diff --git a/backend/orders.py b/backend/orders.py\n"
                "--- a/backend/orders.py\n+++ b/backend/orders.py\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            ),
            "openapi_diffs": [
                {
                    "baseline_run_id": baseline_contract["id"],
                    "current_run_id": current_contract["id"],
                }
            ],
            "schema_diffs": [
                {
                    "baseline_artifact_id": graphql[0]["id"],
                    "current_artifact_id": graphql[1]["id"],
                },
                {
                    "baseline_artifact_id": grpc[0]["id"],
                    "current_artifact_id": grpc[1]["id"],
                },
            ],
        },
        token=token,
    )
    _verify_impact_result(result)
    run_id = str(result["id"])
    persisted = client.json("GET", f"{root}/runs/{run_id}", token=token)
    listed = client.json("GET", f"{root}/runs?page=1&page_size=20", token=token)
    catalog = client.json("GET", f"{root}/catalog", token=token)
    if persisted["source_fingerprint"] != result["source_fingerprint"]:
        raise RuntimeError("S28 persisted impact fingerprint changed")
    if listed["items"][0]["id"] != run_id or len(catalog["schemas"]) < 4:
        raise RuntimeError("S28 impact history or catalog is incomplete")
    return {
        "project_id": project_id,
        "impact_run_id": run_id,
        "source_fingerprint": str(result["source_fingerprint"]),
    }


def _verify_impact_result(result: dict[str, Any]) -> None:
    source_kinds = {item["source_kind"] for item in result["changes"]}
    if source_kinds != {"git", "openapi", "graphql", "grpc"}:
        raise RuntimeError(f"S28 did not parse every change source: {source_kinds}")
    if result["coverage"]["coverage_percent"] != 100.0 or result["coverage"]["gaps"]:
        raise RuntimeError(f"S28 coverage evidence has gaps: {result['coverage']}")
    if result["summary"]["selected_asset_count"] != 1:
        raise RuntimeError(f"S28 smart selection was not deduplicated: {result['summary']}")
    selected = result["selection"]["selected_assets"][0]
    if len(selected["change_keys"]) != 4 or len(selected["reasons"]) != 4:
        raise RuntimeError(f"S28 selection explanations are incomplete: {selected}")
    if len(result["graph"]["edges"]) != 4:
        raise RuntimeError(
            "S28 impact graph does not connect every change to the selected contract"
        )


def _upload_openapi(
    client: APIClient,
    token: str,
    project_id: str,
    *,
    required: bool,
    version: str,
) -> dict[str, Any]:
    return client.multipart(
        f"/projects/{project_id}/contract-runs",
        field="document",
        filename=f"orders-v{version}.json",
        content=_openapi_document(required=required, version=version),
        content_type="application/json",
        fields={"source_name": f"orders-v{version}.json"},
        token=token,
    )


def _create_graphql_versions(
    client: APIClient, token: str, project_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifacts = []
    for field_type in ("String", "Int"):
        artifacts.append(
            client.json(
                "POST",
                "/graphql/schemas",
                {
                    "project_id": project_id,
                    "name": "S28 Orders GraphQL",
                    "source_format": "graphql_sdl",
                    "sdl": f"type Query {{ order(id: ID!): {field_type} }}",
                },
                token=token,
            )
        )
    return artifacts[0], artifacts[1]


def _create_grpc_versions(
    client: APIClient, token: str, project_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifacts = []
    for field_type in ("string", "int64"):
        artifacts.append(
            client.json(
                "POST",
                "/grpc/descriptors",
                {
                    "project_id": project_id,
                    "name": "S28 Orders Proto",
                    "source_format": "proto_source",
                    "entrypoint": "orders.proto",
                    "files": [
                        {
                            "name": "orders.proto",
                            "content": (
                                'syntax = "proto3"; package sample; '
                                f"message Request {{ {field_type} value = 1; }} "
                                "message Reply { bool ok = 1; } "
                                "service Orders { rpc Create(Request) returns (Reply); }"
                            ),
                        }
                    ],
                },
                token=token,
            )
        )
    return artifacts[0], artifacts[1]


def _openapi_document(*, required: bool, version: str) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S28 Orders", "version": version},
            "paths": {
                "/orders": {
                    "post": {
                        "operationId": "createOrder",
                        "requestBody": {
                            "required": required,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"orderId": {"type": "string"}},
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    ).encode()


if __name__ == "__main__":
    main()
