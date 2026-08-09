#!/usr/bin/env python3
"""Run the S3 single-API acceptance flow against a live Compose stack."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


@dataclass(frozen=True, slots=True)
class SmokeConfig:
    api_url: str
    email: str
    password: str
    target_url: str

    @classmethod
    def from_environment(cls) -> SmokeConfig:
        return cls(
            api_url=os.getenv("FLOWTEST_SMOKE_API_URL", "http://localhost:8000/api/v1"),
            email=os.getenv("FLOWTEST_SMOKE_ADMIN_EMAIL", "admin@flowtest.dev"),
            password=os.getenv("FLOWTEST_SMOKE_ADMIN_PASSWORD", "FlowTest-Change-Me-123!"),
            target_url=os.getenv("FLOWTEST_SMOKE_TARGET_URL", "http://mock-target:8080"),
        )


class APIClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        token: str | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=310) as response:
                content = response.read()
        except HTTPError as error:
            details = error.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path} failed with {error.code}: {details}") from error
        return {} if not content else json.loads(content)


def main() -> None:
    config = SmokeConfig.from_environment()
    client = APIClient(config.api_url)
    login = client.call(
        "POST",
        "/auth/login",
        {"email": config.email, "password": config.password},
    )
    token = str(login["access_token"])
    active_password = config.password
    password_changed = bool(login["user"]["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-Smoke-{secrets.token_urlsafe(18)}"
        _change_password(client, token, config.password, active_password)

    project_id = ""
    try:
        project = client.call(
            "POST",
            "/projects",
            {
                "name": f"S3 Smoke {secrets.token_hex(5)}",
                "description": "Automated S3 acceptance data",
            },
            token=token,
        )
        project_id = str(project["id"])
        target_host = urlsplit(config.target_url).hostname or "mock-target"
        client.call(
            "PUT",
            f"/projects/{project_id}/security-policy",
            {
                "allowed_hosts": [target_host],
                "allowed_private_cidrs": ["172.16.0.0/12"],
            },
            token=token,
        )
        environment = client.call(
            "POST",
            f"/projects/{project_id}/environments",
            {
                "name": "Compose Mock",
                "base_url": config.target_url,
                "variables": {},
                "headers": {},
            },
            token=token,
        )
        definition = _create_login_api(client, token, project_id)
        result = _execute_login_api(
            client,
            token,
            project_id,
            str(definition["definition"]["id"]),
            str(environment["id"]),
        )
        _verify_result(result)
        history = client.call(
            "GET", f"/projects/{project_id}/executions?page=1&page_size=20", token=token
        )
        if not any(item["id"] == result["execution"]["id"] for item in history["items"]):
            raise RuntimeError("execution was not persisted in history")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "project_id": project_id,
                    "execution_id": result["execution"]["id"],
                    "assertions": len(result["assertions"]),
                }
            )
        )
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.call("POST", "/auth/logout", token=token)


def _change_password(client: APIClient, token: str, current: str, new: str) -> None:
    client.call(
        "POST",
        "/auth/change-password",
        {"current_password": current, "new_password": new},
        token=token,
    )


def _create_login_api(client: APIClient, token: str, project_id: str) -> dict[str, Any]:
    return client.call(
        "POST",
        f"/projects/{project_id}/apis",
        {
            "name": "Mock 登录",
            "description": "S3 acceptance request",
            "folder_id": None,
            "request": {
                "method": "POST",
                "path": "/auth/login",
                "query_parameters": [],
                "headers": {"Content-Type": "application/json"},
                "body_kind": "json",
                "body": {"username": "tester", "password": "flowtest"},
                "auth": {"kind": "none", "values": {}},
            },
        },
        token=token,
    )


def _execute_login_api(
    client: APIClient,
    token: str,
    project_id: str,
    definition_id: str,
    environment_id: str,
) -> dict[str, Any]:
    return client.call(
        "POST",
        f"/projects/{project_id}/apis/{definition_id}/execute",
        {
            "environment_id": environment_id,
            "timeout_seconds": 30,
            "assertions": [
                {"kind": "status_code", "operator": "equals", "expected": 200},
                {
                    "kind": "response_time",
                    "operator": "less_than",
                    "expected": 3000,
                },
                {
                    "kind": "header",
                    "operator": "contains",
                    "target": "content-type",
                    "expected": "application/json",
                },
                {
                    "kind": "jsonpath",
                    "operator": "equals",
                    "target": "$.data.token",
                    "expected": "mock-token",
                },
                {
                    "kind": "jmespath",
                    "operator": "equals",
                    "target": "data.user_id",
                    "expected": "user-001",
                },
                {
                    "kind": "json_schema",
                    "expected": {
                        "type": "object",
                        "required": ["code", "data"],
                        "properties": {
                            "code": {"const": 0},
                            "data": {"type": "object"},
                        },
                    },
                },
            ],
        },
        token=token,
    )


def _verify_result(result: dict[str, Any]) -> None:
    execution = result["execution"]
    if execution["status"] != "passed":
        raise RuntimeError(f"unexpected execution status: {execution['status']}")
    if execution["request_body"]["password"] != "***":
        raise RuntimeError("request password was persisted without redaction")
    if not result["assertions"] or not all(item["passed"] for item in result["assertions"]):
        raise RuntimeError("one or more assertions failed")


if __name__ == "__main__":
    main()
