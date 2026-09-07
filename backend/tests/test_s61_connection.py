import json
import tomllib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from test_mcp_read import mcp_context as mcp_context

from app.main import app
from app.mcp import cli, setup
from app.mcp.client import MCPReadGatewayClient
from app.mcp.server import _request_token, create_mcp_server
from app.models.access import User
from app.models.organizations import Organization, ServiceAccount
from app.schemas.mcp_connection import MCP_CONNECTION_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "", "Basic not-a-machine-token"])
async def test_http_request_never_inherits_process_identity(authorization: str | None) -> None:
    received: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={"data": {}, "confidence": 1, "trace_id": "fixture"},
        )

    async with MCPReadGatewayClient(
        base_url="http://gateway",
        token="ftsa_process_identity_must_not_be_used",
        transport=httpx.MockTransport(handler),
    ) as client:
        headers = {} if authorization is None else {"authorization": authorization}
        context = SimpleNamespace(
            request_context=SimpleNamespace(request=SimpleNamespace(headers=headers))
        )
        await client.list_projects(token=_request_token(context, client))
    assert received == [None]


@pytest.mark.asyncio
async def test_connection_requires_machine_identity_before_organization_metadata(
    mcp_context: dict[str, Any],
) -> None:
    fixture = mcp_context
    denied = await fixture["client"].post("/api/v1/mcp/connection", json={})
    assert denied.status_code == 401
    assert str(fixture["organization_id"]) not in denied.text
    response = await fixture["client"].post(
        "/api/v1/mcp/connection",
        headers={"Authorization": f"Bearer {fixture['token']}"},
        json={},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["principal_type"] == "service_account"
    assert result["organization_id"] == str(fixture["organization_id"])
    assert result["credential_status"] == "valid"
    assert fixture["token"] not in response.text
    assert result["trace_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "revoked", "disabled", "organization_disabled"])
async def test_connection_invalid_account_exposes_no_organization(
    mcp_context: dict[str, Any],
    state: str,
) -> None:
    async with mcp_context["sessions"]() as session:
        account = await session.get(ServiceAccount, mcp_context["account_id"])
        if state == "expired":
            account.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif state == "revoked":
            account.revoked_at = datetime.now(UTC)
        elif state == "disabled":
            account.enabled = False
        else:
            organization = await session.get(Organization, mcp_context["organization_id"])
            organization.enabled = False
        await session.commit()
    response = await mcp_context["client"].post(
        "/api/v1/mcp/connection",
        json={},
        headers={"Authorization": f"Bearer {mcp_context['token']}"},
    )
    assert response.status_code == 401
    assert str(mcp_context["organization_id"]) not in response.text
    assert mcp_context["token"] not in response.text


@pytest.mark.asyncio
async def test_connection_strict_contract_and_scope_recovery(mcp_context: dict[str, Any]) -> None:
    client = mcp_context["client"]
    headers = {"Authorization": f"Bearer {mcp_context['write_token']}"}
    response = await client.post("/api/v1/mcp/connection", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["next_action"] == "request_scope"
    assert "read_authorized_assets" not in response.json()["available_actions"]
    assert (await client.get("/api/v1/mcp/read/projects", headers=headers)).status_code == 403
    assert (
        await client.post(
            "/api/v1/mcp/connection", headers=headers, json={"organization_id": "other"}
        )
    ).status_code == 422
    response = await client.post(
        "/api/v1/mcp/connection",
        headers=headers,
        json={"expected_contract_version": "unsupported-v999"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTRACT_VERSION_UNSUPPORTED"
    response = await client.post(
        "/api/v1/mcp/connection",
        json={},
        headers={"Authorization": f"Bearer {mcp_context['human_token']}"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sdk_http_identity_is_per_request_and_browser_independent(
    mcp_context: dict[str, Any],
) -> None:
    fixture = mcp_context
    async with MCPReadGatewayClient(
        base_url="http://test",
        token=fixture["token"],
        transport=httpx.ASGITransport(app=app),
    ) as gateway:
        server = create_mcp_server(client=gateway)
        http_app = server.streamable_http_app(json_response=True, stateless_http=True)
        async with (
            http_app.router.lifespan_context(http_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=http_app),
                base_url="http://127.0.0.1:8765",
                headers={"Accept": "application/json, text/event-stream"},
            ) as client,
        ):
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "flowtest.inspect_connection", "arguments": {"request": {}}},
            }
            denied = await client.post("/mcp", json=request)
            assert denied.status_code == 200, denied.text
            diagnostic = denied.json()["result"]["structuredContent"]["data"][
                "connection_diagnostic"
            ]
            assert diagnostic["code"] == "AUTH_REQUIRED"
            assert str(fixture["organization_id"]) not in denied.text
            for token, next_action in [
                (fixture["token"], "inspect_projects"),
                (fixture["write_token"], "request_scope"),
            ]:
                response = await client.post(
                    "/mcp",
                    json=request,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Cookie": "session=expired-browser-session",
                    },
                )
                assert response.status_code == 200, response.text
                result = response.json()["result"]["structuredContent"]
                assert result["next_action"] == next_action
                assert token not in response.text
            denied_again = await client.post("/mcp", json=request)
            assert "AUTH_REQUIRED" in denied_again.text
        stdio = (
            await server.call_tool("flowtest.inspect_connection", {"request": {}})
        ).structured_content
        assert stdio["organization_id"] == str(fixture["organization_id"])
        tools = await server.list_tools()
        connection = next(tool for tool in tools if tool.name == "flowtest.inspect_connection")
        assert connection.annotations.read_only_hint is True
        assert connection.annotations.destructive_hint is False


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
def test_setup_missing_identity_emits_only_safe_template(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    transport: str,
) -> None:
    monkeypatch.delenv("FLOWTEST_TEST_MACHINE_TOKEN", raising=False)
    cli.main(["setup", "--transport", transport, "--token-env-var", "FLOWTEST_TEST_MACHINE_TOKEN"])
    result = json.loads(capsys.readouterr().out)
    assert result["diagnosis"]["diagnostic"]["code"] == "AUTH_REQUIRED"
    assert result["diagnosis"]["credential_status"] == "missing"
    assert result["transport_verified"] is False
    assert result["configuration_written"] is False
    config = tomllib.loads(result["config_template"])["mcp_servers"]["flowtest"]
    if transport == "stdio":
        assert config["env_vars"] == ["FLOWTEST_TEST_MACHINE_TOKEN"]
        assert "--token" not in config["args"]
    else:
        assert config["bearer_token_env_var"] == "FLOWTEST_TEST_MACHINE_TOKEN"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--token", "ftsa_accidental_secret"],
        ["setup", "--token-env-var", "ftsa_accidental_secret"],
        ["setup", "--api-base-url", "https://ftsa_accidental_secret@example.test"],
    ],
)
def test_cli_rejects_secret_arguments_without_echoing(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.main(arguments)
    capture = capsys.readouterr()
    assert "ftsa_accidental_secret" not in capture.out + capture.err


def test_http_cli_never_loads_shared_machine_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv(setup.DEFAULT_TOKEN_ENV, "ftsa_shared_process_secret")

    def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(run=lambda **_: None)

    monkeypatch.setattr(cli, "create_mcp_server", create)
    cli.main(["--transport", "streamable-http"])
    assert calls[0]["service_account_token"] is None
    assert calls[0]["allow_process_token"] is False


@pytest.mark.asyncio
async def test_setup_uses_explicit_machine_identity_and_no_secret_output(
    mcp_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWTEST_TEST_MACHINE_TOKEN", mcp_context["token"])

    def gateway(**kwargs: Any) -> MCPReadGatewayClient:
        return MCPReadGatewayClient(**kwargs, transport=httpx.ASGITransport(app=app))

    monkeypatch.setattr(setup, "MCPReadGatewayClient", gateway)
    result = await setup._diagnose("http://test", "FLOWTEST_TEST_MACHINE_TOKEN")
    assert result.credential_status == "valid"
    assert result.connection.schema_version == MCP_CONNECTION_VERSION
    assert mcp_context["token"] not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,expected",
    [
        (401, "SERVICE_ACCOUNT_EXPIRED", "AUTH_EXPIRED"),
        (401, "INVALID_SERVICE_ACCOUNT_TOKEN", "AUTH_REQUIRED"),
        (403, "MCP_SCOPE_REQUIRED", "SCOPE_REQUIRED"),
        (403, "PROJECT_ACCESS_DENIED", "REQUEST_REJECTED"),
        (403, "FEATURE_DISABLED", "FEATURE_DISABLED"),
        (409, "CONTRACT_VERSION_UNSUPPORTED", "CONTRACT_VERSION_UNSUPPORTED"),
        (503, "MCP_GATEWAY_UNAVAILABLE", "SERVER_UNREACHABLE"),
        (200, "INVALID_PAYLOAD", "CONTRACT_VERSION_UNSUPPORTED"),
    ],
)
async def test_setup_failure_categories_are_safe_and_distinct(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
    expected: str,
) -> None:
    monkeypatch.setenv("FLOWTEST_TEST_MACHINE_TOKEN", "ftsa_fixture_only_secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer ftsa_fixture_only_secret"
        return httpx.Response(
            status, json={"error": {"code": code, "message": "untrusted-secret-body"}}
        )

    def gateway(**kwargs: Any) -> MCPReadGatewayClient:
        return MCPReadGatewayClient(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(setup, "MCPReadGatewayClient", gateway)
    result = await setup._diagnose("http://gateway", "FLOWTEST_TEST_MACHINE_TOKEN")
    assert result.diagnostic.code == expected
    assert result.connection is None
    assert "untrusted-secret-body" not in result.model_dump_json()
    assert "ftsa_fixture_only_secret" not in result.model_dump_json()


def test_stdio_explicit_empty_variable_does_not_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv(setup.DEFAULT_TOKEN_ENV, "ftsa_other_identity")
    monkeypatch.delenv("FLOWTEST_TEST_MACHINE_TOKEN", raising=False)

    def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(run=lambda **_: None)

    monkeypatch.setattr(cli, "create_mcp_server", create)
    cli.main(["--token-env-var", "FLOWTEST_TEST_MACHINE_TOKEN"])
    assert calls[0]["service_account_token"] == ""


@pytest.mark.asyncio
async def test_connection_does_not_reflect_client_secret_or_inherit_creator_scope(
    mcp_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "feature_integration_flow_enabled", False)
    async with mcp_context["sessions"]() as session:
        account = await session.get(ServiceAccount, mcp_context["account_id"])
        account.scopes = ["mcp:flow:propose", "mcp:preview:execute"]
        await session.commit()
    response = await mcp_context["client"].post(
        "/api/v1/mcp/connection",
        json={},
        headers={
            "Authorization": f"Bearer {mcp_context['token']}",
            "X-MCP-Client-Version": "ftsa_untrusted_secret",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["available_actions"] == ["inspect_connection"]
    assert result["client_contract_version"] == "unknown"
    assert result["effective_scopes"] == ["mcp:flow:propose", "mcp:preview:execute"]
    assert "ftsa_untrusted_secret" not in response.text


@pytest.mark.asyncio
async def test_machine_account_project_access_does_not_use_creator_admin(
    mcp_context: dict[str, Any],
) -> None:
    async with mcp_context["sessions"]() as session:
        account = await session.get(ServiceAccount, mcp_context["account_id"])
        actor = await session.get(User, account.created_by_id)
        actor.is_system_admin = False
        await session.commit()

    response = await mcp_context["client"].get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}",
        headers={"Authorization": f"Bearer {mcp_context['token']}"},
    )
    assert response.status_code == 200, response.text
    cross_tenant = await mcp_context["client"].get(
        f"/api/v1/mcp/read/projects/{mcp_context['other_project_id']}",
        headers={"Authorization": f"Bearer {mcp_context['token']}"},
    )
    assert cross_tenant.status_code == 404


def test_setup_rejects_secret_in_url_path_without_echoing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["setup", "--mcp-url", "https://host/ftsa_accidental_secret"])
    capture = capsys.readouterr()
    assert "ftsa_accidental_secret" not in capture.out + capture.err


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["ftsa_含非ASCII", "ftsa_bad\nheader", "ftsa_has space"])
async def test_setup_invalid_token_format_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
) -> None:
    monkeypatch.setenv("FLOWTEST_TEST_MACHINE_TOKEN", token)
    result = await setup._diagnose("http://gateway.invalid", "FLOWTEST_TEST_MACHINE_TOKEN")
    assert result.diagnostic.code == "AUTH_REQUIRED"
    assert result.connection is None
    assert token not in result.model_dump_json()
