import base64
import hashlib
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.core.storage import StoredObject
from app.main import app
from app.models import Base
from app.models.access import User

ADMIN_EMAIL = "file-admin@example.com"
ADMIN_PASSWORD = "file-password-123!"


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}

    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = StoredObject(content=content, content_type=content_type)

    async def get(self, *, key: str) -> StoredObject:
        return self.objects[key]

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
async def file_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    storage = MemoryObjectStorage()
    monkeypatch.setattr("app.services.artifacts.object_storage", storage)
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="File administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()
    await test_engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_artifact_upload_multipart_execution_and_download(file_client: AsyncClient) -> None:
    headers = await _login_headers(file_client)
    project_id, environment_id = await _create_context(file_client, headers)
    upload = await file_client.post(
        f"/api/v1/projects/{project_id}/files",
        headers=headers,
        files={"file": ("../payload.txt", b"flowtest-file", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    artifact = upload.json()
    assert artifact["filename"] == "payload.txt"
    assert artifact["sha256"] == hashlib.sha256(b"flowtest-file").hexdigest()

    definition_id = await _create_api(
        file_client,
        headers,
        project_id,
        name="Upload file",
        method="POST",
        path="/upload",
        body_kind="multipart",
        body={
            "fields": {"note": "sample"},
            "files": [{"field": "file", "artifact_id": artifact["id"]}],
        },
    )
    received: list[httpx.Request] = []

    def upload_handler(request: httpx.Request) -> Response:
        received.append(request)
        return Response(200, json={"uploaded": True})

    respx.post("http://target.example.com/upload").mock(side_effect=upload_handler)
    execution = await _execute(file_client, headers, project_id, definition_id, environment_id)
    assert execution.status_code == 200, execution.text
    assert execution.json()["execution"]["status"] == "passed"
    content_type = received[0].headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b"flowtest-file" in received[0].content
    assert b'filename="payload.txt"' in received[0].content
    assert b'name="note"' in received[0].content

    listing = await file_client.get(f"/api/v1/projects/{project_id}/files", headers=headers)
    assert listing.json()["total"] == 1
    download = await file_client.get(
        f"/api/v1/projects/{project_id}/files/{artifact['id']}", headers=headers
    )
    assert download.content == b"flowtest-file"
    assert "payload.txt" in download.headers["content-disposition"]


@respx.mock
@pytest.mark.asyncio
async def test_binary_response_is_externalized_and_file_assertions_run(
    file_client: AsyncClient,
) -> None:
    headers = await _login_headers(file_client)
    project_id, environment_id = await _create_context(file_client, headers)
    definition_id = await _create_api(
        file_client,
        headers,
        project_id,
        name="Download report",
        method="GET",
        path="/download",
    )
    content = b"\x00flowtest-binary"
    digest = hashlib.sha256(content).hexdigest()
    respx.get("http://target.example.com/download").mock(
        return_value=Response(
            200,
            content=content,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="report.bin"',
            },
        )
    )
    execution = await file_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/execute",
        headers=headers,
        json={
            "environment_id": environment_id,
            "assertions": [
                {"kind": "file_size", "operator": "equals", "expected": len(content)},
                {"kind": "file_sha256", "operator": "equals", "expected": digest},
                {
                    "kind": "content_type",
                    "operator": "equals",
                    "expected": "application/octet-stream",
                },
            ],
        },
    )
    assert execution.status_code == 200, execution.text
    detail = execution.json()
    assert detail["execution"]["status"] == "passed"
    artifact_id = detail["execution"]["response_artifact_id"]
    assert detail["execution"]["response_body"] == {
        "artifact_id": artifact_id,
        "filename": "report.bin",
        "content_type": "application/octet-stream",
        "size_bytes": len(content),
        "sha256": digest,
    }
    assert all(result["passed"] for result in detail["assertions"])
    download = await file_client.get(
        f"/api/v1/projects/{project_id}/files/{artifact_id}", headers=headers
    )
    assert download.content == content


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "auth", "expected_header", "expected_query"),
    [
        (
            "/bearer",
            {"kind": "bearer", "values": {"token": "bearer-secret"}},
            ("authorization", "Bearer bearer-secret"),
            None,
        ),
        (
            "/basic",
            {
                "kind": "basic",
                "values": {"username": "tester", "password": "basic-secret"},
            },
            (
                "authorization",
                f"Basic {base64.b64encode(b'tester:basic-secret').decode()}",
            ),
            None,
        ),
        (
            "/api-key-header",
            {
                "kind": "api_key",
                "values": {"name": "X-Access-Key", "value": "key-secret", "in": "header"},
            },
            ("x-access-key", "key-secret"),
            None,
        ),
        (
            "/api-key-query",
            {
                "kind": "api_key",
                "values": {"name": "access_key", "value": "query-secret", "in": "query"},
            },
            None,
            ("access_key", "query-secret"),
        ),
    ],
)
async def test_authentication_modes_are_sent_and_redacted(
    file_client: AsyncClient,
    path: str,
    auth: dict[str, Any],
    expected_header: tuple[str, str] | None,
    expected_query: tuple[str, str] | None,
) -> None:
    headers = await _login_headers(file_client)
    project_id, environment_id = await _create_context(file_client, headers)
    definition_id = await _create_api(
        file_client,
        headers,
        project_id,
        name=f"Auth {path}",
        method="GET",
        path=path,
        auth=auth,
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> Response:
        seen.append(request)
        return Response(200, json={"ok": True})

    respx.get(url__startswith=f"http://target.example.com{path}").mock(side_effect=handler)
    execution = await _execute(file_client, headers, project_id, definition_id, environment_id)
    assert execution.status_code == 200, execution.text
    if expected_header:
        assert seen[0].headers[expected_header[0]] == expected_header[1]
    if expected_query:
        assert parse_qs(urlsplit(str(seen[0].url)).query)[expected_query[0]] == [expected_query[1]]
    persisted = execution.json()["execution"]
    assert "secret" not in str(persisted["request_headers"])
    assert "secret" not in persisted["request_url"]


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_context(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    project = await client.post(
        "/api/v1/projects", headers=headers, json={"name": "File execution"}
    )
    assert project.status_code == 201
    project_id = str(project.json()["id"])
    environment = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "Target", "base_url": "http://target.example.com"},
    )
    assert environment.status_code == 201
    return project_id, str(environment.json()["id"])


async def _create_api(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    name: str,
    method: str,
    path: str,
    body_kind: str = "none",
    body: object = None,
    auth: dict[str, Any] | None = None,
) -> str:
    response = await client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": name,
            "request": {
                "method": method,
                "path": path,
                "body_kind": body_kind,
                "body": body,
                "auth": auth or {"kind": "none", "values": {}},
            },
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["definition"]["id"])


async def _execute(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    definition_id: str,
    environment_id: str,
):
    return await client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/execute",
        headers=headers,
        json={
            "environment_id": environment_id,
            "assertions": [{"kind": "status_code", "operator": "equals", "expected": 200}],
        },
    )
