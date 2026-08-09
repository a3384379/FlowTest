import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.domain.api_assets import BodyKind, HttpMethod
from app.domain.scopes import HeaderScope
from app.main import app
from app.models import Base
from app.models.access import User
from app.services.api_assets import PreparedHeader, PreparedRequest
from app.services.executions import _redact_request_url, _send_request

ADMIN_EMAIL = "execution-admin@example.com"
ADMIN_PASSWORD = "execution-password-123!"


@pytest.fixture
async def execution_client() -> AsyncIterator[AsyncClient]:
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
                display_name="Execution administrator",
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
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await test_engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_execute_assert_and_read_history(execution_client: AsyncClient) -> None:
    headers = await _login_headers(execution_client)
    project_id, environment_id, definition_id = await _create_execution_assets(
        execution_client, headers
    )
    target = respx.post("http://target.example.com/users").mock(
        return_value=Response(
            200,
            json={"user": {"id": 42, "name": "Alice"}, "token": "response-token"},
            headers={"Content-Type": "application/json", "Set-Cookie": "session=secret"},
        )
    )
    assertions = [
        {"kind": "status_code", "expected": 200},
        {"kind": "response_time", "operator": "less_than", "expected": 10000},
        {
            "kind": "header",
            "operator": "contains",
            "target": "content-type",
            "expected": "json",
        },
        {"kind": "jsonpath", "target": "$.user.id", "expected": 42},
        {"kind": "jmespath", "target": "user.name", "expected": "Alice"},
        {
            "kind": "json_schema",
            "expected": {
                "type": "object",
                "required": ["user"],
                "properties": {"user": {"type": "object"}},
            },
        },
    ]
    executed = await execution_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/execute",
        headers=headers,
        json={"environment_id": environment_id, "assertions": assertions},
    )

    assert executed.status_code == 200, executed.text
    detail = executed.json()
    assert detail["execution"]["status"] == "passed"
    assert detail["execution"]["response_status"] == 200
    assert detail["execution"]["request_headers"]["Authorization"] == "***"
    assert detail["execution"]["request_headers"]["Cookie"] == "***"
    assert detail["execution"]["request_body"] == {"password": "***", "token": "***"}
    assert detail["execution"]["response_headers"]["set-cookie"] == "***"
    assert detail["execution"]["response_body"]["token"] == "***"
    assert len(detail["assertions"]) == 6
    assert all(item["passed"] for item in detail["assertions"])
    assert target.called
    sent_request = target.calls.last.request
    assert sent_request.headers["Authorization"] == "Bearer request-secret"
    assert sent_request.headers["Cookie"] == "session=literal-cookie"
    assert json.loads(sent_request.content) == {
        "password": "request-secret",
        "token": "literal-token",
    }

    failed = await execution_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/execute",
        headers=headers,
        json={
            "environment_id": environment_id,
            "assertions": [{"kind": "status_code", "expected": 201}],
        },
    )
    assert failed.json()["execution"]["status"] == "failed"
    assert failed.json()["assertions"][0]["passed"] is False

    history = await execution_client.get(
        f"/api/v1/projects/{project_id}/executions", headers=headers
    )
    assert history.status_code == 200
    assert history.json()["total"] == 2
    execution_id = detail["execution"]["id"]
    loaded = await execution_client.get(
        f"/api/v1/projects/{project_id}/executions/{execution_id}", headers=headers
    )
    assert loaded.status_code == 200
    assert len(loaded.json()["assertions"]) == 6


@respx.mock
@pytest.mark.asyncio
async def test_timeout_and_large_response_are_persisted_as_errors(
    execution_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await _login_headers(execution_client)
    project_id, environment_id, definition_id = await _create_execution_assets(
        execution_client, headers, path="/slow", method="GET", body=None
    )
    route = respx.get("http://target.example.com/slow")
    route.side_effect = httpx.ReadTimeout("timed out")
    timed_out = await execution_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/execute",
        headers=headers,
        json={"environment_id": environment_id, "timeout_seconds": 1},
    )
    assert timed_out.json()["execution"]["status"] == "error"
    assert timed_out.json()["execution"]["error_code"] == "REQUEST_TIMEOUT"

    monkeypatch.setattr(settings, "artifact_limit_bytes", settings.inline_body_limit_bytes)
    route.side_effect = None
    route.return_value = Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
    too_large = await execution_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/execute",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert too_large.json()["execution"]["error_code"] == "RESPONSE_TOO_LARGE"
    assert too_large.json()["execution"]["response_size_bytes"] == 2 * 1024 * 1024 + 1

    route.return_value = None
    route.side_effect = httpx.ConnectError("target URL contained token=literal-secret")
    network_error = await execution_client.post(
        f"/api/v1/projects/{project_id}/apis/{definition_id}/execute",
        headers=headers,
        json={"environment_id": environment_id},
    )
    assert network_error.json()["execution"]["error_code"] == "NETWORK_ERROR"
    assert network_error.json()["execution"]["error_message"] == "无法连接目标服务"
    assert "literal-secret" not in network_error.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "body_kind", "body"),
    [
        (HttpMethod.GET, BodyKind.NONE, None),
        (HttpMethod.POST, BodyKind.JSON, {"value": 1}),
        (HttpMethod.PUT, BodyKind.RAW, "raw-body"),
        (HttpMethod.PATCH, BodyKind.FORM, {"field": "value"}),
        (HttpMethod.DELETE, BodyKind.NONE, None),
    ],
)
async def test_http_sender_supports_all_v1_methods(
    method: HttpMethod, body_kind: BodyKind, body: Any
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> Response:
        seen.append(request)
        return Response(204)

    async with AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await _send_request(
            client,
            PreparedRequest(
                method=method,
                url="http://target.example.com/resource",
                headers=(PreparedHeader("X-Test", "value", source=HeaderScope.RUNTIME),),
                body=body,
                variables=(),
            ),
            body_kind=body_kind,
            timeout_seconds=30,
        )

    assert response.status_code == 204
    assert seen[0].method == method.value


def test_sensitive_query_parameters_are_redacted() -> None:
    redacted = _redact_request_url(
        "https://target.example.com/resource?token=literal&Password=hidden&safe=visible"
    )

    assert parse_qs(urlsplit(redacted).query) == {
        "token": ["***"],
        "Password": ["***"],
        "safe": ["visible"],
    }


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_execution_assets(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    path: str = "/users",
    method: str = "POST",
    body: Any = None,
) -> tuple[str, str, str]:
    project = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": f"Execution {path}"},
    )
    project_id = project.json()["id"]
    environment = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "Target", "base_url": "http://target.example.com"},
    )
    environment_id = environment.json()["id"]
    secret = await client.put(
        f"/api/v1/projects/{project_id}/secrets",
        headers=headers,
        json={
            "name": "TOKEN",
            "value": "request-secret",
            "environment_id": environment_id,
        },
    )
    assert secret.status_code == 200
    request_body = body
    body_kind = "none"
    if body is None and method == "POST":
        request_body = {"password": "{{secret.TOKEN}}", "token": "literal-token"}
        body_kind = "json"
    definition = await client.post(
        f"/api/v1/projects/{project_id}/apis",
        headers=headers,
        json={
            "name": "Target API",
            "request": {
                "method": method,
                "path": path,
                "headers": {
                    "Authorization": "Bearer {{secret.TOKEN}}",
                    "Cookie": "session=literal-cookie",
                },
                "body_kind": body_kind,
                "body": request_body,
            },
        },
    )
    assert definition.status_code == 201, definition.text
    return project_id, environment_id, definition.json()["definition"]["id"]
