#!/usr/bin/env python3
"""Run the S27 Pact, provider verification, and release decision acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from smoke_s4 import APIClient, SmokeConfig, _allow_compose_target, _change_password


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
        active_password = f"FlowTest-S27-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, config, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(
    client: APIClient, config: SmokeConfig, token: str
) -> dict[str, str]:
    features = client.json("GET", "/v3/features", token=token)
    if not features.get("contract_hub"):
        raise RuntimeError("S27 contract hub feature is not enabled")
    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S27 Contract Hub {secrets.token_hex(5)}",
            "description": "S27 acceptance",
        },
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)

    pact = _upload_pact(
        client, token, project_id, version="web-1", expected_status="ok"
    )
    provider_id = str(pact["provider_service_id"])
    graph = client.json(
        "GET", f"/projects/{project_id}/contract-hub/service-graph", token=token
    )
    if len(graph["nodes"]) != 2 or graph["edges"][0]["latest_status"] != "pending":
        raise RuntimeError(
            "S27 Pact import did not create the pending service dependency graph"
        )

    verification = _verify(
        client,
        token,
        project_id,
        str(pact["id"]),
        provider_version="1.0.0",
        target_base_url=config.target_url,
    )
    if verification["status"] != "passed" or verification["passed_count"] != 1:
        raise RuntimeError(
            f"S27 real Compose provider verification failed: {verification}"
        )
    openapi = _upload_openapi(client, token, project_id, provider_id, "1.0.0")
    if openapi["provider_service_id"] != provider_id or openapi["breaking_changes"]:
        raise RuntimeError("S27 OpenAPI contract was not bound to the provider release")

    safe = _deployment_check(client, token, project_id, provider_id, "1.0.0")
    if safe["decision"] != "safe" or safe["evidence"]["evaluated_contract_count"] != 2:
        raise RuntimeError(f"S27 unified safe release decision is incomplete: {safe}")

    incompatible = _upload_pact(
        client,
        token,
        project_id,
        version="web-2",
        expected_status="maintenance",
    )
    failed = _verify(
        client,
        token,
        project_id,
        str(incompatible["id"]),
        provider_version="2.0.0",
        target_base_url=config.target_url,
    )
    if (
        failed["status"] != "failed"
        or "BODY_MISMATCH" not in failed["results"][0]["mismatch_codes"]
    ):
        raise RuntimeError("S27 exact provider mismatch evidence is missing")
    unsafe = _deployment_check(client, token, project_id, provider_id, "2.0.0")
    if unsafe["decision"] != "unsafe" or not unsafe["evidence"]["blockers"]:
        raise RuntimeError("S27 incompatible release was not blocked")

    matrix = client.json(
        "GET",
        f"/projects/{project_id}/contract-hub/compatibility/{provider_id}",
        token=token,
    )
    summary = client.json(
        "GET", f"/projects/{project_id}/contract-hub/summary", token=token
    )
    statuses = {cell["status"] for row in matrix["rows"] for cell in row["cells"]}
    if not {"passed", "failed"}.issubset(statuses):
        raise RuntimeError(f"S27 compatibility matrix is incomplete: {matrix}")
    if summary["openapi_contract_count"] != 1 or summary["pact_contract_count"] != 2:
        raise RuntimeError(f"S27 unified contract summary is incomplete: {summary}")
    return {
        "project_id": project_id,
        "provider_service_id": provider_id,
        "safe_check_id": str(safe["id"]),
        "unsafe_check_id": str(unsafe["id"]),
    }


def _upload_pact(
    client: APIClient,
    token: str,
    project_id: str,
    *,
    version: str,
    expected_status: str,
) -> dict[str, Any]:
    return client.multipart(
        f"/projects/{project_id}/contract-hub/pacts",
        field="document",
        filename=f"web-orders-{version}.json",
        content=_pact_document(expected_status),
        content_type="application/json",
        fields={"consumer_version": version},
        token=token,
    )


def _verify(
    client: APIClient,
    token: str,
    project_id: str,
    pact_id: str,
    *,
    provider_version: str,
    target_base_url: str,
) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/contract-hub/pacts/{pact_id}/verify",
        {"provider_version": provider_version, "target_base_url": target_base_url},
        token=token,
    )


def _upload_openapi(
    client: APIClient,
    token: str,
    project_id: str,
    provider_id: str,
    provider_version: str,
) -> dict[str, Any]:
    return client.multipart(
        f"/projects/{project_id}/contract-runs",
        field="document",
        filename="orders-openapi.json",
        content=_openapi_document(provider_version),
        content_type="application/json",
        fields={
            "provider_service_id": provider_id,
            "provider_version": provider_version,
            "source_name": "orders-openapi.json",
        },
        token=token,
    )


def _deployment_check(
    client: APIClient,
    token: str,
    project_id: str,
    provider_id: str,
    provider_version: str,
) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/contract-hub/deployment-checks",
        {"provider_service_id": provider_id, "provider_version": provider_version},
        token=token,
    )


def _pact_document(expected_status: str) -> bytes:
    return json.dumps(
        {
            "consumer": {"name": "S27 Web Client"},
            "provider": {"name": "S27 Mock Target"},
            "interactions": [
                {
                    "description": "读取 Compose 健康状态",
                    "request": {"method": "GET", "path": "/health"},
                    "response": {"status": 200, "body": {"status": expected_status}},
                }
            ],
            "metadata": {"pactSpecification": {"version": "3.0.0"}},
        },
        ensure_ascii=False,
    ).encode()


def _openapi_document(version: str) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S27 Mock Target", "version": version},
            "paths": {
                "/health": {
                    "get": {
                        "operationId": "getHealth",
                        "responses": {
                            "200": {
                                "description": "Healthy",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["status"],
                                            "properties": {
                                                "status": {"type": "string"}
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }
    ).encode()


if __name__ == "__main__":
    main()
