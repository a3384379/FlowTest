#!/usr/bin/env python3
"""Run the S4 import, authentication, and file acceptance flow."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any, cast
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

    def json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        content = self._request(
            Request(
                f"{self._base_url}{path}",
                data=body,
                headers={
                    **self._headers(token, content_type="application/json"),
                    **(extra_headers or {}),
                },
                method=method,
            )
        )
        return {} if not content else json.loads(content)

    def multipart(
        self,
        path: str,
        *,
        field: str,
        filename: str,
        content: bytes,
        content_type: str,
        fields: dict[str, str] | None = None,
        token: str,
    ) -> dict[str, Any]:
        boundary = f"FlowTest{secrets.token_hex(12)}"
        body = _multipart_body(
            boundary=boundary,
            field=field,
            filename=filename,
            content=content,
            content_type=content_type,
            fields=fields or {},
        )
        response = self._request(
            Request(
                f"{self._base_url}{path}",
                data=body,
                headers=self._headers(
                    token,
                    content_type=f"multipart/form-data; boundary={boundary}",
                ),
                method="POST",
            )
        )
        return cast(dict[str, Any], json.loads(response))

    def download(self, path: str, *, token: str) -> bytes:
        return self._request(
            Request(
                f"{self._base_url}{path}",
                headers=self._headers(token),
                method="GET",
            )
        )

    def _request(self, request: Request) -> bytes:
        try:
            with self._opener.open(request, timeout=310) as response:
                return cast(bytes, response.read())
        except HTTPError as error:
            details = error.read().decode(errors="replace")
            raise RuntimeError(
                f"{request.method} {request.full_url} failed with {error.code}: {details}"
            ) from error

    @staticmethod
    def _headers(token: str | None, *, content_type: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers


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
        result = _run_acceptance(client, config, token)
        print(json.dumps({"status": "passed", **result}))
    finally:
        if password_changed:
            _change_password(client, token, active_password, config.password)
        client.json("POST", "/auth/logout", token=token)


def _run_acceptance(client: APIClient, config: SmokeConfig, token: str) -> dict[str, str]:
    project = client.json(
        "POST",
        "/projects",
        {"name": f"S4 Smoke {secrets.token_hex(5)}", "description": "S4 acceptance"},
        token=token,
    )
    project_id = str(project["id"])
    _allow_compose_target(client, token, project_id, config.target_url)
    environment = client.json(
        "POST",
        f"/projects/{project_id}/environments",
        {"name": "Compose Mock", "base_url": config.target_url},
        token=token,
    )
    environment_id = str(environment["id"])
    _verify_import(client, token, project_id)
    upload_execution = _verify_upload(client, token, project_id, environment_id)
    _verify_bearer(client, token, project_id, environment_id)
    download_execution = _verify_download(client, token, project_id, environment_id)
    return {
        "project_id": project_id,
        "upload_execution_id": str(upload_execution["execution"]["id"]),
        "download_execution_id": str(download_execution["execution"]["id"]),
    }


def _verify_import(client: APIClient, token: str, project_id: str) -> None:
    document = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Smoke", "version": "1.0.0"},
            "paths": {"/health": {"get": {"summary": "Mock 健康检查"}}},
        }
    ).encode()
    first = client.multipart(
        f"/projects/{project_id}/imports",
        field="document",
        filename="smoke-openapi.json",
        content=document,
        content_type="application/json",
        fields={"source_type": "auto"},
        token=token,
    )
    repeated = client.multipart(
        f"/projects/{project_id}/imports",
        field="document",
        filename="smoke-openapi.json",
        content=document,
        content_type="application/json",
        fields={"source_type": "auto"},
        token=token,
    )
    if first["added"] != 1 or repeated["unchanged"] != 1:
        raise RuntimeError("import fingerprint de-duplication failed")


def _verify_upload(
    client: APIClient, token: str, project_id: str, environment_id: str
) -> dict[str, Any]:
    content = b"flowtest-smoke-upload"
    artifact = client.multipart(
        f"/projects/{project_id}/files",
        field="file",
        filename="payload.txt",
        content=content,
        content_type="text/plain",
        token=token,
    )
    definition = _create_api(
        client,
        token,
        project_id,
        name="Mock 文件上传",
        method="POST",
        path="/upload",
        body_kind="multipart",
        body={
            "fields": {"source": "smoke"},
            "files": [{"field": "file", "artifact_id": artifact["id"]}],
        },
    )
    result = _execute(
        client,
        token,
        project_id,
        str(definition["definition"]["id"]),
        environment_id,
        [
            {"kind": "status_code", "operator": "equals", "expected": 200},
            {
                "kind": "jsonpath",
                "operator": "equals",
                "target": "$.size",
                "expected": len(content),
            },
        ],
    )
    _assert_passed(result, "multipart upload")
    return result


def _verify_bearer(client: APIClient, token: str, project_id: str, environment_id: str) -> None:
    client.json(
        "PUT",
        f"/projects/{project_id}/secrets",
        {"name": "MOCK_TOKEN", "value": "mock-token", "environment_id": environment_id},
        token=token,
    )
    definition = _create_api(
        client,
        token,
        project_id,
        name="Mock Bearer",
        method="GET",
        path="/users/me",
        auth={"kind": "bearer", "values": {"token": "{{secret.MOCK_TOKEN}}"}},
    )
    result = _execute(
        client,
        token,
        project_id,
        str(definition["definition"]["id"]),
        environment_id,
        [
            {"kind": "status_code", "operator": "equals", "expected": 200},
            {
                "kind": "jmespath",
                "operator": "equals",
                "target": "data.id",
                "expected": "user-001",
            },
        ],
    )
    _assert_passed(result, "bearer authentication")
    if "mock-token" in json.dumps(result["execution"]):
        raise RuntimeError("bearer token leaked into execution history")


def _verify_download(
    client: APIClient, token: str, project_id: str, environment_id: str
) -> dict[str, Any]:
    content = b"flowtest-download"
    definition = _create_api(
        client,
        token,
        project_id,
        name="Mock 文件下载",
        method="GET",
        path="/download",
    )
    result = _execute(
        client,
        token,
        project_id,
        str(definition["definition"]["id"]),
        environment_id,
        [
            {"kind": "file_size", "operator": "equals", "expected": len(content)},
            {
                "kind": "file_sha256",
                "operator": "equals",
                "expected": hashlib.sha256(content).hexdigest(),
            },
            {
                "kind": "content_type",
                "operator": "equals",
                "expected": "application/octet-stream",
            },
        ],
    )
    _assert_passed(result, "file download")
    artifact_id = result["execution"]["response_artifact_id"]
    downloaded = client.download(f"/projects/{project_id}/files/{artifact_id}", token=token)
    if downloaded != content:
        raise RuntimeError("downloaded response artifact content does not match")
    return result


def _create_api(
    client: APIClient,
    token: str,
    project_id: str,
    *,
    name: str,
    method: str,
    path: str,
    body_kind: str = "none",
    body: Any = None,
    auth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/apis",
        {
            "name": name,
            "request": {
                "method": method,
                "path": path,
                "body_kind": body_kind,
                "body": body,
                "auth": auth or {"kind": "none", "values": {}},
            },
        },
        token=token,
    )


def _execute(
    client: APIClient,
    token: str,
    project_id: str,
    definition_id: str,
    environment_id: str,
    assertions: list[dict[str, Any]],
) -> dict[str, Any]:
    return client.json(
        "POST",
        f"/projects/{project_id}/apis/{definition_id}/execute",
        {"environment_id": environment_id, "assertions": assertions},
        token=token,
    )


def _assert_passed(result: dict[str, Any], label: str) -> None:
    if result["execution"]["status"] != "passed":
        raise RuntimeError(f"{label} execution failed: {json.dumps(result)}")
    if not all(item["passed"] for item in result["assertions"]):
        raise RuntimeError(f"{label} assertions failed")


def _change_password(client: APIClient, token: str, current: str, new: str) -> None:
    client.json(
        "POST",
        "/auth/change-password",
        {"current_password": current, "new_password": new},
        token=token,
    )


def _allow_compose_target(
    client: APIClient,
    token: str,
    project_id: str,
    target_url: str,
) -> None:
    target_host = urlsplit(target_url).hostname or "mock-target"
    client.json(
        "PUT",
        f"/projects/{project_id}/security-policy",
        {
            "allowed_hosts": [target_host],
            "allowed_private_cidrs": ["172.16.0.0/12"],
        },
        token=token,
    )


def _multipart_body(
    *,
    boundary: str,
    field: str,
    filename: str,
    content: bytes,
    content_type: str,
    fields: dict[str, str],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n').encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks)


if __name__ == "__main__":
    main()
