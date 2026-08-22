from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.mcp_read import MCPReadEnvelope, input_schema_hash
from app.main import app
from app.mcp.client import MCPGatewayError, MCPReadGatewayClient
from app.mcp.server import _request_token, create_mcp_server, parse_resource_uri
from app.models import Base
from app.models.access import AuditLog, Project, User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.organizations import Organization, ServiceAccount
from app.models.service_targets import Service, ServiceEndpoint
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution, WorkflowVersion
from app.services.service_accounts import ServiceAccountService


@pytest.fixture
async def mcp_context() -> AsyncIterator[dict[str, Any]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with sessions() as session:
        actor = User(
            email="mcp-admin@example.com",
            display_name="MCP administrator",
            password_hash=password_service.hash("unused-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="MCP organization",
            slug="mcp-organization",
            description="",
            enabled=True,
            created_by_id=None,
        )
        other_organization = Organization(
            name="Other organization",
            slug="other-organization",
            description="",
            enabled=True,
            created_by_id=None,
        )
        session.add_all([actor, organization, other_organization])
        await session.flush()
        organization.created_by_id = actor.id
        other_organization.created_by_id = actor.id
        project = Project(
            organization_id=organization.id,
            name="Payments",
            description="Contains internal notes that should not be exposed by MCP",
            variables={"private": "project-secret"},
            headers={"Authorization": "Bearer project-secret"},
            created_by_id=actor.id,
        )
        other_project = Project(
            organization_id=other_organization.id,
            name="Other tenant",
            created_by_id=actor.id,
        )
        session.add_all([project, other_project])
        await session.flush()
        environment = Environment(
            project_id=project.id,
            name="staging",
            base_url="https://staging.example.test/api?token=do-not-return",
            default_service_id=None,
            variables={"password": "environment-secret"},
            headers={"Cookie": "session-secret"},
            created_by_id=actor.id,
        )
        service = Service(
            project_id=project.id,
            service_key="payments-api",
            name="Payments API",
            description="",
            owner_team="payments",
            service_type="https",
            enabled=True,
            created_by_id=actor.id,
        )
        session.add_all([environment, service])
        await session.flush()
        environment.default_service_id = service.id
        endpoint = ServiceEndpoint(
            project_id=project.id,
            environment_id=environment.id,
            service_id=service.id,
            variant="blue",
            base_url="https://user:password@payments.example.test/api?token=endpoint-secret",
            enabled=True,
            tls_verify=True,
            proxy_ref="secret-proxy-ref",
            headers={"Authorization": "Bearer endpoint-secret", "X-Internal": "secret"},
            variables={"token": "endpoint-variable-secret"},
            secret_refs=["payments-token"],
            revision=3,
            created_by_id=actor.id,
        )
        definition = APIDefinition(
            project_id=project.id,
            folder_id=None,
            service_id=service.id,
            name="Create payment",
            description="",
            current_version=1,
            is_active=True,
            created_by_id=actor.id,
        )
        session.add_all([endpoint, definition])
        await session.flush()
        version = APIVersion(
            api_definition_id=definition.id,
            version=1,
            method="POST",
            path="/payments?token=contract-secret",
            query_parameters=[{"name": "customer_id", "value": "secret-customer"}],
            headers={"Authorization": "Bearer contract-secret"},
            variables={"token": "contract-variable-secret"},
            body_kind="json",
            body={"card_number": "4111111111111111"},
            auth_kind="bearer",
            auth_config={"token": "contract-auth-secret"},
            extraction_rules=[{"name": "payment_id", "kind": "jsonpath", "expression": "$.id"}],
            assertions=[
                {"kind": "json_schema", "operator": "equals", "expected": {"secret": True}}
            ],
            created_by_id=actor.id,
        )
        workflow = Workflow(
            project_id=project.id,
            folder_id=None,
            name="Payment smoke",
            description="",
            draft_definition={
                "nodes": [
                    {
                        "id": "request",
                        "type": "api",
                        "name": "Create payment",
                        "config": {
                            "api_definition_id": str(definition.id),
                            "api_version": 1,
                            "headers": {"Authorization": "Bearer workflow-secret"},
                        },
                    }
                ],
                "edges": [],
            },
            draft_revision=2,
            current_version=1,
            created_by_id=actor.id,
        )
        session.add_all([version, workflow])
        await session.flush()
        workflow_version = WorkflowVersion(
            workflow_id=workflow.id,
            version=1,
            definition=workflow.draft_definition,
            fingerprint="a" * 64,
            created_by_id=actor.id,
            published_at=now,
        )
        session.add(workflow_version)
        await session.flush()
        execution = WorkflowExecution(
            project_id=project.id,
            workflow_id=workflow.id,
            workflow_version_id=workflow_version.id,
            environment_id=environment.id,
            triggered_by_id=actor.id,
            status="failed",
            snapshot={"Authorization": "Bearer execution-secret"},
            context={"secret": "execution-context-secret"},
            error_code="ASSERTION_FAILED",
            error_message="private failure details",
            started_at=now,
            completed_at=now,
        )
        session.add(execution)
        await session.flush()
        node_execution = WorkflowNodeExecution(
            workflow_execution_id=execution.id,
            node_id="request",
            node_type="api",
            name="Create payment",
            status="failed",
            attempts=2,
            output={"token": "node-output-secret"},
            result={"body": "sensitive"},
            error_code="ASSERTION_FAILED",
            error_message="private node details",
            started_at=now,
            completed_at=now,
        )
        session.add(node_execution)
        issued = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="MCP reader",
            account_key="mcp-reader",
            scopes=["mcp:read"],
            expires_at=None,
            metadata={"purpose": "read-only tests"},
        )
        await session.commit()
        account_id = issued.account.id

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield {
            "client": client,
            "token": issued.token,
            "account_id": account_id,
            "project_id": project.id,
            "other_project_id": other_project.id,
            "environment_id": environment.id,
            "definition_id": definition.id,
            "workflow_id": workflow.id,
            "execution_id": execution.id,
            "sessions": sessions,
        }
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_mcp_read_gateway_is_tenant_scoped_and_redacted(mcp_context: dict[str, Any]) -> None:
    client = mcp_context["client"]
    headers = {"Authorization": f"Bearer {mcp_context['token']}"}

    projects = await client.get("/api/v1/mcp/read/projects", headers=headers)
    assert projects.status_code == 200, projects.text
    project_payload = projects.json()
    assert project_payload["data"]["total"] == 1
    assert project_payload["evidence_refs"]
    assert project_payload["confidence"] == 1.0
    assert project_payload["trace_id"]
    assert "project-secret" not in projects.text

    services = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/services",
        headers=headers,
    )
    assert services.status_code == 200, services.text
    service_payload = services.json()
    endpoint = service_payload["data"]["endpoints"][0]
    assert endpoint["service_key"] == "payments-api"
    assert endpoint["base_origin"] == "https://payments.example.test"
    assert endpoint["secret_ref_count"] == 1
    for secret in ("endpoint-secret", "endpoint-variable-secret", "secret-proxy-ref", "password"):
        assert secret not in services.text

    filtered_services = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/services",
        params={"environment_id": str(mcp_context["environment_id"])},
        headers={
            **headers,
            "X-MCP-Client-Version": "invalid version with spaces",
            "X-MCP-Resource-URI": "flowtest://projects/resource-project/services?secret=ignored",
        },
    )
    assert filtered_services.status_code == 200, filtered_services.text
    assert filtered_services.json()["data"]["environments"][0]["name"] == "staging"
    unknown_environment = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/services",
        params={"environment_id": str(uuid4())},
        headers=headers,
    )
    assert unknown_environment.status_code == 404

    project = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}",
        headers=headers,
    )
    assert project.status_code == 200, project.text
    assert project.json()["data"]["name"] == "Payments"

    contract = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/contracts",
        headers=headers,
    )
    assert contract.status_code == 200, contract.text
    contract_item = contract.json()["data"]["items"][0]
    assert contract_item["path"] == "/payments"
    assert contract_item["query_parameter_names"] == ["customer_id"]
    for secret in ("contract-secret", "contract-variable-secret", "4111111111111111"):
        assert secret not in contract.text

    selected_contract = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/contracts",
        params={"api_definition_id": str(mcp_context["definition_id"])},
        headers=headers,
    )
    assert selected_contract.status_code == 200, selected_contract.text
    assert selected_contract.json()["data"]["total"] == 1
    unknown_contract = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/contracts",
        params={"api_definition_id": str(uuid4())},
        headers=headers,
    )
    assert unknown_contract.status_code == 404

    draft = await client.get(
        f"/api/v1/mcp/read/workflows/{mcp_context['workflow_id']}/draft",
        headers=headers,
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["data"]["nodes"][0]["kind"] == "api"
    assert "workflow-secret" not in draft.text

    evidence = await client.get(
        f"/api/v1/mcp/read/runs/{mcp_context['execution_id']}/evidence",
        headers=headers,
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["data"]["execution"]["status"] == "failed"
    assert "execution-secret" not in evidence.text
    assert "node-output-secret" not in evidence.text
    missing_workflow = await client.get(
        f"/api/v1/mcp/read/workflows/{uuid4()}/draft",
        headers=headers,
    )
    assert missing_workflow.status_code == 404
    missing_evidence = await client.get(
        f"/api/v1/mcp/read/runs/{uuid4()}/evidence",
        headers=headers,
    )
    assert missing_evidence.status_code == 404

    cross_tenant = await client.get(
        f"/api/v1/mcp/read/projects/{mcp_context['other_project_id']}",
        headers=headers,
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    async with mcp_context["sessions"]() as session:
        account = await session.get(ServiceAccount, mcp_context["account_id"])
        assert account is not None
        assert account.last_used_at is None
        logs = list(
            (
                await session.scalars(select(AuditLog).where(AuditLog.action == "mcp.tool.read"))
            ).all()
        )
        assert len(logs) >= 5
        assert all("ftsa_" not in str(log.details) for log in logs)
        for value in (
            "project-secret",
            "endpoint-secret",
            "endpoint-variable-secret",
            "contract-secret",
            "workflow-secret",
            "execution-secret",
        ):
            assert all(value not in str(log.details) for log in logs)


@pytest.mark.asyncio
async def test_mcp_scope_and_authentication_fail_safely(mcp_context: dict[str, Any]) -> None:
    client = mcp_context["client"]
    missing = await client.get("/api/v1/mcp/read/projects")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "MCP_AUTHENTICATION_REQUIRED"

    invalid = await client.get(
        "/api/v1/mcp/read/projects",
        headers={"Authorization": "Bearer ftsa_invalid"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_SERVICE_ACCOUNT_TOKEN"

    async with mcp_context["sessions"]() as session:
        actor = await session.get(
            User, (await session.get(ServiceAccount, mcp_context["account_id"])).created_by_id
        )
        assert actor is not None
        limited = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=(await session.get(Project, mcp_context["project_id"])).organization_id,
            name="Project-only reader",
            account_key="project-only-reader",
            scopes=["project:read"],
            expires_at=None,
            metadata={},
        )
    response = await client.get(
        "/api/v1/mcp/read/projects",
        headers={"Authorization": f"Bearer {limited.token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MCP_SCOPE_REQUIRED"


@pytest.mark.asyncio
async def test_mcp_sdk_registration_and_transports() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("projects") and request.url.params.get("page") == "99":
            return httpx.Response(403, json={"error": {"code": "MCP_SCOPE_REQUIRED"}})
        payload = {
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20},
            "evidence_refs": [],
            "confidence": 1.0,
            "redactions": [],
            "trace_id": "sdk-trace",
            "warnings": [],
        }
        return httpx.Response(200, json=payload)

    async with MCPReadGatewayClient(
        base_url="http://gateway",
        token="ftsa_sdk",
        transport=httpx.MockTransport(handler),
    ) as gateway:
        server = create_mcp_server(client=gateway)
        tools = await server.list_tools()
        assert [tool.name for tool in tools] == sorted(tool.name for tool in tools)
        assert [tool.name for tool in tools] == [
            "flowtest.discover_services",
            "flowtest.inspect_contract",
            "flowtest.inspect_flow",
            "flowtest.inspect_project",
            "flowtest.inspect_run_evidence",
            "flowtest.list_projects",
        ]
        templates = await server.list_resource_templates()
        assert [template.uri_template for template in templates] == sorted(
            template.uri_template for template in templates
        )
        prompts = await server.list_prompts()
        assert [prompt.name for prompt in prompts] == sorted(prompt.name for prompt in prompts)

        tool_result = await server.call_tool("flowtest.list_projects", {})
        assert tool_result.structured_content["trace_id"] == "sdk-trace"
        for name, arguments in (
            ("flowtest.discover_services", {"project_id": "project-1", "environment_id": "env-1"}),
            (
                "flowtest.inspect_contract",
                {"project_id": "project-1", "api_definition_id": "api-1"},
            ),
            ("flowtest.inspect_flow", {"workflow_id": "workflow-1"}),
            ("flowtest.inspect_project", {"project_id": "project-1"}),
            ("flowtest.inspect_run_evidence", {"execution_id": "run-1"}),
        ):
            result = await server.call_tool(name, arguments)
            assert result.is_error is False
        for uri in (
            "flowtest://drafts/workflow-1",
            "flowtest://projects/project-1",
            "flowtest://projects/project-1/contract",
            "flowtest://projects/project-1/services",
            "flowtest://runs/run-1/evidence",
        ):
            resource_result = await server.read_resource(uri)
            assert "sdk-trace" in resource_result[0].content
        prompt_result = await server.get_prompt("triage_failure", {"execution_id": "run-1"})
        assert "只读" in prompt_result.messages[0].content.text
        assert "人工确认" in prompt_result.messages[0].content.text
        forwarded_context = SimpleNamespace(
            request_context=SimpleNamespace(
                request=SimpleNamespace(headers={"authorization": "Bearer forwarded-token"})
            )
        )
        assert _request_token(forwarded_context, gateway) == "forwarded-token"
        error_result = await server.call_tool("flowtest.list_projects", {"page": 99})
        assert error_result.structured_content["data"]["error"]["code"] == "MCP_SCOPE_REQUIRED"
        assert requests[0].headers["authorization"] == "Bearer ftsa_sdk"


def test_mcp_domain_contract_and_resource_uri_validation() -> None:
    assert input_schema_hash("list_projects") == input_schema_hash("list_projects")
    assert input_schema_hash("list_projects") != input_schema_hash("inspect_project")
    assert parse_resource_uri("flowtest://projects/p1") == ("project", "p1")
    assert parse_resource_uri("flowtest://projects/p1/services") == ("services", "p1")
    assert parse_resource_uri("flowtest://drafts/w1") == ("draft", "w1")
    with pytest.raises(ValueError):
        parse_resource_uri("https://example.test/project")
    with pytest.raises(ValidationError):
        MCPReadEnvelope(
            data={},
            evidence_refs=[],
            confidence=2,
            redactions=[],
            trace_id="trace",
            warnings=[],
        )


@pytest.mark.asyncio
async def test_mcp_client_rejects_invalid_response_without_leaking_body() -> None:
    async with MCPReadGatewayClient(
        base_url="http://gateway",
        token="ftsa_sdk",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"not-json-secret")
        ),
    ) as gateway:
        with pytest.raises(MCPGatewayError) as error:
            await gateway.list_projects()
        assert error.value.code == "MCP_GATEWAY_INVALID_RESPONSE"
        assert "not-json-secret" not in str(error.value)
