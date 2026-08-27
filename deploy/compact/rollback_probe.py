#!/usr/bin/env python3
"""Create and verify disposable assets for the Compact rollback drill."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from http.cookiejar import CookieJar
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


class ProbeClient:
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
        expected_status: int | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        status, content = self._request(
            Request(
                f"{self._base_url}{path}",
                data=body,
                headers=headers,
                method=method,
            )
        )
        if expected_status is not None:
            if status != expected_status:
                raise RuntimeError(f"{method} {path} returned unexpected status {status}")
            return {}
        if status >= 400:
            raise RuntimeError(f"{method} {path} returned status {status}")
        return {} if not content else cast(dict[str, Any], json.loads(content))

    def upload(self, path: str, *, token: str) -> dict[str, Any]:
        boundary = f"FlowTestRollback{secrets.token_hex(12)}"
        marker = f"FlowTest Compact rollback marker {secrets.token_hex(16)}\n".encode()
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="rollback-marker.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode() + marker + f"\r\n--{boundary}--\r\n".encode()
        status, content = self._request(
            Request(
                f"{self._base_url}{path}",
                data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                method="POST",
            )
        )
        if status >= 400:
            raise RuntimeError(f"POST {path} returned status {status}")
        return cast(dict[str, Any], json.loads(content))

    def _request(self, request: Request) -> tuple[int, bytes]:
        try:
            with self._opener.open(request, timeout=30) as response:
                return response.status, cast(bytes, response.read())
        except HTTPError as error:
            return error.code, cast(bytes, error.read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "verify-absent"))
    parser.add_argument("--project-id")
    arguments = parser.parse_args()
    if arguments.action == "verify-absent" and not arguments.project_id:
        parser.error("verify-absent requires --project-id")

    base_url = os.getenv(
        "FLOWTEST_ROLLBACK_PROBE_API_URL", "http://backend:8000/api/v1"
    )
    email = os.environ["FLOWTEST_BOOTSTRAP_ADMIN_EMAIL"]
    original_password = os.environ["FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD"]
    client = ProbeClient(base_url)
    login = client.json(
        "POST", "/auth/login", {"email": email, "password": original_password}
    )
    token = str(login["access_token"])
    active_password = original_password
    password_changed = bool(login["user"]["requires_password_change"])
    if password_changed:
        active_password = f"FlowTest-Rollback-{secrets.token_urlsafe(18)}"
        _change_password(client, token, original_password, active_password)

    try:
        if arguments.action == "create":
            result = _create_marker(client, token)
        else:
            client.json(
                "GET",
                f"/projects/{arguments.project_id}",
                token=token,
                expected_status=404,
            )
            result = {"status": "absent", "project_id": arguments.project_id}
        print(json.dumps(result))
    finally:
        if password_changed:
            _change_password(client, token, active_password, original_password)
        client.json("POST", "/auth/logout", token=token)


def _create_marker(client: ProbeClient, token: str) -> dict[str, str]:
    project = client.json(
        "POST",
        "/projects",
        {
            "name": f"S35 Rollback Probe {secrets.token_hex(6)}",
            "description": "S35 disposable rollback evidence",
        },
        token=token,
    )
    project_id = str(project["id"])
    artifact = client.upload(f"/projects/{project_id}/files", token=token)
    return {
        "status": "created",
        "project_id": project_id,
        "artifact_id": str(artifact["id"]),
    }


def _change_password(
    client: ProbeClient, token: str, current_password: str, new_password: str
) -> None:
    client.json(
        "POST",
        "/auth/change-password",
        {"current_password": current_password, "new_password": new_password},
        token=token,
    )


if __name__ == "__main__":
    main()
