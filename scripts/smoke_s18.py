#!/usr/bin/env python3
"""Run the S18 contract generation, diff, coverage, and review acceptance flow."""

from __future__ import annotations

import json
import secrets
from typing import Any

from smoke_s4 import APIClient, SmokeConfig, _change_password


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.json("POST", "/auth/login", {"email": config.email, "password": config.password})
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(login["user"]["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-Smoke-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)
    try:
        result = _run_acceptance(client, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, token: str) -> dict[str, str]:
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S18 Contract {secrets.token_hex(5)}", "description": "S18 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    baseline = _upload(client, token, project_id, _schema(version="1.0.0"))
    if baseline["generated_case_count"] != 3:
        raise RuntimeError("contract generator did not create all review drafts")
    if baseline["coverage"]["operation_coverage_percent"] != 100.0:
        raise RuntimeError("contract operation coverage is incomplete")

    changed = _upload(
        client,
        token,
        project_id,
        _schema(version="2.0.0", required=True, count_type="string"),
        baseline_run_id=str(baseline["id"]),
    )
    breaking_codes = {item["code"] for item in changed["breaking_changes"]}
    if breaking_codes != {"REQUEST_REQUIRED_ADDED", "RESPONSE_TYPE_CHANGED"}:
        raise RuntimeError(f"breaking change evidence is incomplete: {sorted(breaking_codes)}")

    cases = client.json(
        "GET",
        f"/projects/{project_id}/contract-runs/{changed['id']}/generated-cases?page_size=100",
        token=token,
    )
    if cases["total"] != 3 or {item["review_status"] for item in cases["items"]} != {"pending"}:
        raise RuntimeError("generated contract cases were not held for review")
    case = cases["items"][0]
    accepted = client.json(
        "POST",
        f"/projects/{project_id}/contract-runs/{changed['id']}/generated-cases/{case['id']}/accept",
        {"name": "S18 人工审核用例", "note": "Compose 验收"},
        token=token,
    )
    if accepted["review_status"] != "accepted" or accepted["definition"]["confirmed"] is not True:
        raise RuntimeError("accepted contract draft did not become confirmed")
    try:
        client.json(
            "POST",
            f"/projects/{project_id}/contract-runs/{changed['id']}/generated-cases/{case['id']}/accept",
            {},
            token=token,
        )
    except RuntimeError as error:
        if "GENERATED_CASE_ALREADY_REVIEWED" not in str(error):
            raise
    else:
        raise RuntimeError("contract review replay was accepted")
    return {"project_id": project_id, "contract_run_id": str(changed["id"])}


def _upload(
    client: APIClient,
    token: str,
    project_id: str,
    document: bytes,
    *,
    baseline_run_id: str | None = None,
) -> dict[str, Any]:
    fields = {"source_name": "s18-team-api.json"}
    if baseline_run_id:
        fields["baseline_run_id"] = baseline_run_id
    return client.multipart(
        f"/projects/{project_id}/contract-runs",
        field="document",
        filename="s18-team-api.json",
        content=document,
        content_type="application/json",
        fields=fields,
        token=token,
    )


def _schema(*, version: str, required: bool = False, count_type: str = "integer") -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "S18 Team API", "version": version},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "required": required,
                                "schema": {"type": "integer", "minimum": 1, "maximum": 100},
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"count": {"type": count_type}},
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
