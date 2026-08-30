from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_workflow_coordinator
from app.core.database import get_session
from app.core.security import password_service, token_service
from app.domain.test_contexts import first_sensitive_value
from app.domain.test_engineering import ContractResponse, OperationContract, fingerprint_contract
from app.main import app
from app.mcp.client import MCPReadGatewayClient
from app.mcp.server import create_mcp_server
from app.models import Base
from app.models.access import Project, User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.organizations import Organization
from app.models.service_targets import Service, ServiceEndpoint
from app.models.workflows import Workflow, WorkflowExecution
from app.schemas.test_contexts import FlowSpecProposalRequest
from app.services.service_accounts import ServiceAccountService


@pytest.fixture
async def s51_context() -> AsyncIterator[dict[str, Any]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        actor = User(
            email="s51-admin@example.test",
            display_name="S51 administrator",
            password_hash=password_service.hash("unused-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="S51 organization",
            slug="s51-organization",
            description="",
            enabled=True,
            created_by_id=None,
        )
        session.add_all([actor, organization])
        await session.flush()
        organization.created_by_id = actor.id
        project = Project(
            organization_id=organization.id,
            name="S51 project",
            created_by_id=actor.id,
        )
        other_project = Project(
            organization_id=organization.id,
            name="S51 other project",
            created_by_id=actor.id,
        )
        session.add_all([project, other_project])
        await session.flush()
        sandbox_environment = Environment(
            project_id=project.id,
            name="S51 sandbox",
            base_url="https://sandbox.example.test",
            classification="sandbox",
            variables={},
            headers={},
            created_by_id=actor.id,
        )
        production_environment = Environment(
            project_id=project.id,
            name="S51 production",
            base_url="https://production.example.test",
            classification="production",
            variables={},
            headers={},
            created_by_id=actor.id,
        )
        session.add_all([sandbox_environment, production_environment])
        await session.flush()
        account = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="S51 planner",
            account_key="s51-planner",
            scopes=["mcp:evidence:write", "mcp:flow:propose", "mcp:preview:execute"],
            expires_at=None,
            metadata={},
        )
        service = Service(
            project_id=project.id,
            service_key="orders",
            name="Orders",
            description="",
            owner_team=None,
            service_type="http",
            enabled=True,
            created_by_id=actor.id,
        )
        session.add(service)
        await session.flush()
        sandbox_environment.default_service_id = service.id
        session.add(
            ServiceEndpoint(
                project_id=project.id,
                environment_id=sandbox_environment.id,
                service_id=service.id,
                variant="default",
                base_url="https://sandbox.example.test",
                enabled=True,
                tls_verify=True,
                headers={},
                variables={},
                secret_refs=[],
                revision=1,
                created_by_id=actor.id,
            )
        )
        contract = OperationContract(
            operation="health.check",
            method="GET",
            path="/health",
            service="orders",
            responses={"200": ContractResponse(description="Healthy")},
            source_ref="contract://orders/health",
            revision="1",
        )
        contract_fingerprint = fingerprint_contract(contract)
        definition = APIDefinition(
            project_id=project.id,
            folder_id=None,
            service_id=service.id,
            name="health.check",
            description="",
            current_version=1,
            is_active=True,
            import_key="health.check",
            import_fingerprint=contract_fingerprint,
            import_source="s51-test",
            import_source_key="health.check",
            created_by_id=actor.id,
        )
        session.add(definition)
        await session.flush()
        session.add(
            APIVersion(
                api_definition_id=definition.id,
                version=1,
                method="GET",
                path="/health",
                query_parameters=[],
                headers={},
                variables={},
                body_kind="none",
                body=None,
                auth_kind="none",
                auth_config={},
                extraction_rules=[],
                assertions=[],
                canonical_contract=contract.model_dump(mode="json", by_alias=True),
                contract_fingerprint=contract_fingerprint,
                contract_completeness="complete",
                created_by_id=actor.id,
            )
        )
        workflow = Workflow(
            project_id=project.id,
            folder_id=None,
            name="Existing health flow",
            description="",
            draft_definition=_workflow_definition(definition.id),
            draft_revision=1,
            current_version=None,
            created_by_id=actor.id,
        )
        session.add(workflow)
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    coordinator = RecordingWorkflowCoordinator()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workflow_coordinator] = lambda: coordinator
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield {
            "client": client,
            "sessions": sessions,
            "project_id": project.id,
            "other_project_id": other_project.id,
            "service_id": service.id,
            "definition_id": definition.id,
            "workflow_id": workflow.id,
            "service_account_id": account.account.id,
            "sandbox_environment_id": sandbox_environment.id,
            "production_environment_id": production_environment.id,
            "coordinator": coordinator,
            "mcp_headers": {"Authorization": f"Bearer {account.token}"},
            "user_headers": {
                "Authorization": f"Bearer {token_service.create_access_token(actor.id)}",
                "X-Organization-Id": str(organization.id),
            },
        }
    app.dependency_overrides.clear()
    await engine.dispose()


class RecordingWorkflowCoordinator:
    def __init__(self) -> None:
        self.plans: list[Any] = []

    async def start(self, plan: Any) -> None:
        self.plans.append(plan)


@pytest.mark.asyncio
async def test_mcp_plan_compile_dry_run_propose_and_inspect_are_draft_only(
    s51_context: dict[str, Any],
) -> None:
    context, plan, compilation = await _plan_chain(s51_context)
    client = s51_context["client"]
    payload = _proposal_payload(s51_context, context, plan, compilation)
    headers = {**s51_context["mcp_headers"], "Idempotency-Key": "s51-preview-v1"}
    preview = await client.post("/api/v1/mcp/flow/proposals", headers=headers, json=payload)
    assert preview.status_code == 202, preview.text
    assert preview.json()["dry_run"] is True
    assert preview.json()["change_set_id"] is None
    async with s51_context["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(AIChangeSet)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkflowExecution)) == 0

    persisted_headers = {
        **s51_context["mcp_headers"],
        "Idempotency-Key": "s51-proposal-v1",
    }
    proposed = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers=persisted_headers,
        json={**payload, "dry_run": False},
    )
    assert proposed.status_code == 202, proposed.text
    change_set_id = proposed.json()["change_set_id"]
    repeated = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers=persisted_headers,
        json={**payload, "dry_run": False},
    )
    assert repeated.json()["change_set_id"] == change_set_id

    inspected = await client.get(
        f"/api/v1/mcp/flow/proposals/{change_set_id}",
        params={"project_id": str(s51_context["project_id"])},
        headers=s51_context["mcp_headers"],
    )
    assert inspected.status_code == 200, inspected.text
    inspection = inspected.json()
    assert inspection["status"] == "draft"
    assert inspection["review_status"] == "pending"
    assert inspection["applied"] is False
    assert inspection["existing_definition"] is None
    assert inspection["proposed_definition"]["nodes"]
    assert inspection["integration_plan"]["plan_fingerprint"] == plan["plan_fingerprint"]

    visual = await client.get(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/visual-proposal",
        headers=s51_context["user_headers"],
    )
    assert visual.status_code == 200, visual.text
    assert visual.json()["schema_version"] == "flowtest-visual-flow-proposal-v1"
    async with s51_context["sessions"]() as session:
        change_set = await session.get(AIChangeSet, UUID(change_set_id))
        item = await session.scalar(
            select(AIChangeItem).where(AIChangeItem.change_set_id == UUID(change_set_id))
        )
        assert change_set is not None and change_set.status == "draft"
        assert change_set.source_snapshot["integration_plan"] == plan
        assert change_set.source_snapshot["expected_target_revision"] is None
        assert item is not None and item.review_status == "pending"
        assert await session.scalar(select(func.count()).select_from(AIChangeSet)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkflowExecution)) == 0


@pytest.mark.asyncio
async def test_mcp_flow_proposal_rejects_sensitive_values_before_persistence(
    s51_context: dict[str, Any],
) -> None:
    context, plan, compilation = await _plan_chain(s51_context)
    for index, (description, secret) in enumerate(
        (
            ("使用Bearer AbCdEf1234567890进行请求", "AbCdEf1234567890"),
            ("使用password=hunter2进行请求", "hunter2"),
            ('使用password="my secret phrase"进行请求', "my secret phrase"),
            ("使用client_secret=hunter2进行请求", "hunter2"),
            ("使用db_password=hunter2进行请求", "hunter2"),
            ('提案包含 {"password":"hunter2"}', "hunter2"),
            ("使用password=abc进行请求", "abc"),
        )
    ):
        payload = _proposal_payload(s51_context, context, plan, compilation)
        payload["spec"]["description"] = description
        response = await s51_context["client"].post(
            "/api/v1/mcp/flow/proposals",
            headers={
                **s51_context["mcp_headers"],
                "Idempotency-Key": f"s51-sensitive-proposal-{index}",
            },
            json={**payload, "dry_run": False},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MCP_SENSITIVE_INPUT"
        assert secret not in response.text

    for index, parameter_name in enumerate(
        (
            "db_password",
            "private_key",
            "access_key",
            "database_credential",
            "client_secret_value",
            "db_password_value",
            "password1",
            "access_key2",
            "DBPassword",
            "credentials",
            "client_credentials",
            "passwords",
            "tokens",
        )
    ):
        named_secret_payload = _proposal_payload(s51_context, context, plan, compilation)
        named_secret_payload["spec"]["parameters"] = [
            {"name": parameter_name, "source": "constant", "value": "hunter2"}
        ]
        named_secret = await s51_context["client"].post(
            "/api/v1/mcp/flow/proposals",
            headers={
                **s51_context["mcp_headers"],
                "Idempotency-Key": f"s51-sensitive-parameter-name-{index}",
            },
            json={**named_secret_payload, "dry_run": False},
        )
        assert named_secret.status_code == 422
        assert named_secret.json()["error"]["code"] == "MCP_SENSITIVE_INPUT"
        assert "hunter2" not in named_secret.text

    legacy_variable_payload = _proposal_payload(s51_context, context, plan, compilation)
    legacy_variable_payload["spec"]["variables"] = {"access_key": "hunter2"}
    legacy_variable = await s51_context["client"].post(
        "/api/v1/mcp/flow/proposals",
        headers={
            **s51_context["mcp_headers"],
            "Idempotency-Key": "s51-sensitive-legacy-variable",
        },
        json={**legacy_variable_payload, "dry_run": False},
    )
    assert legacy_variable.status_code == 422
    assert legacy_variable.json()["error"]["code"] == "MCP_SENSITIVE_INPUT"
    assert "hunter2" not in legacy_variable.text

    safe_payload = _proposal_payload(s51_context, context, plan, compilation)
    safe_payload.pop("integration_plan")
    safe_payload.pop("compilation")
    safe_payload["spec"]["description"] = "Reviewed integration flow"
    safe_payload["spec"]["parameters"] = [
        {
            "name": "orders_token",
            "source": "secret_ref",
            "secret_ref": "secret://golden/orders-token",
        }
    ]
    validated_safe_payload = FlowSpecProposalRequest.model_validate(safe_payload)
    assert first_sensitive_value(validated_safe_payload.model_dump(mode="json")) is None
    safe_response = await s51_context["client"].post(
        "/api/v1/mcp/flow/proposals",
        headers={
            **s51_context["mcp_headers"],
            "Idempotency-Key": "s51-safe-secret-reference",
        },
        json=safe_payload,
    )
    assert safe_response.status_code == 422
    assert safe_response.json()["error"]["code"] == "FLOWSPEC_IMPORT_INVALID"
    async with s51_context["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(AIChangeSet)) == 0


@pytest.mark.asyncio
async def test_expected_revision_review_gate_tenant_scope_and_stale_apply(
    s51_context: dict[str, Any],
) -> None:
    context, plan, compilation = await _plan_chain(s51_context)
    client = s51_context["client"]
    payload = {
        **_proposal_payload(s51_context, context, plan, compilation),
        "workflow_id": str(s51_context["workflow_id"]),
        "expected_revision": 999,
        "dry_run": False,
    }
    stale_create = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={**s51_context["mcp_headers"], "Idempotency-Key": "s51-stale-create"},
        json=payload,
    )
    assert stale_create.status_code == 409
    assert stale_create.json()["error"]["code"] == "FLOWSPEC_TARGET_CONFLICT"

    proposed = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={**s51_context["mcp_headers"], "Idempotency-Key": "s51-update-v1"},
        json={**payload, "expected_revision": 1},
    )
    assert proposed.status_code == 202, proposed.text
    change_set_id = proposed.json()["change_set_id"]
    apply_before_review = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/apply",
        headers=s51_context["user_headers"],
    )
    assert apply_before_review.status_code == 409
    assert apply_before_review.json()["error"]["code"] == "FLOWSPEC_REVIEW_REQUIRED"

    foreign = await client.get(
        f"/api/v1/mcp/flow/proposals/{change_set_id}",
        params={"project_id": str(s51_context["other_project_id"])},
        headers=s51_context["mcp_headers"],
    )
    assert foreign.status_code == 404

    reviewed = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/review",
        headers=s51_context["user_headers"],
        json={"accept": True, "note": "S51 human review"},
    )
    assert reviewed.status_code == 200
    async with s51_context["sessions"]() as session:
        workflow = await session.get(Workflow, s51_context["workflow_id"])
        assert workflow is not None
        workflow.draft_revision = 2
        await session.commit()

    stale_apply = await client.post(
        f"/api/v1/projects/{s51_context['project_id']}/flow-specs/change-sets/"
        f"{change_set_id}/apply",
        headers=s51_context["user_headers"],
    )
    assert stale_apply.status_code == 409
    assert stale_apply.json()["error"]["code"] == "WORKFLOW_DRAFT_CONFLICT"
    async with s51_context["sessions"]() as session:
        workflow = await session.get(Workflow, s51_context["workflow_id"])
        change_set = await session.get(AIChangeSet, UUID(change_set_id))
        assert workflow is not None and workflow.current_version is None
        assert change_set is not None and change_set.applied_at is None
        assert await session.scalar(select(func.count()).select_from(WorkflowExecution)) == 0


@pytest.mark.asyncio
async def test_official_mcp_sdk_tools_complete_the_draft_only_chain(
    s51_context: dict[str, Any],
) -> None:
    token = s51_context["mcp_headers"]["Authorization"].removeprefix("Bearer ")
    async with MCPReadGatewayClient(
        base_url="http://test",
        token=token,
        transport=ASGITransport(app=app, raise_app_exceptions=False),
    ) as gateway:
        server = create_mcp_server(client=gateway)
        begun = (
            await server.call_tool(
                "flowtest.begin_test_context",
                {
                    "project_id": str(s51_context["project_id"]),
                    "name": "S51 MCP SDK context",
                    "objective": "Compile an MCP SDK health flow draft",
                    "required_evidence": ["contract"],
                    "contract_revisions": [
                        {"source_ref": "contract://orders/health", "revision": "1"}
                    ],
                },
            )
        ).structured_content
        plan = (
            await server.call_tool(
                "flowtest.plan_integration_test",
                {
                    "project_id": str(s51_context["project_id"]),
                    "context_id": begun["id"],
                    "context_revision_id": begun["revision"]["id"],
                    "actors": [
                        {
                            "id": "operator",
                            "role": "integration tester",
                            "evidence_refs": ["context://s51/operator"],
                        }
                    ],
                    "target_environment": {
                        "key": "s51",
                        "source_ref": "environment://s51",
                        "evidence_refs": ["environment://s51/revision/1"],
                    },
                    "operations": [{"definition_id": str(s51_context["definition_id"])}],
                },
            )
        ).structured_content
        validated = await server.call_tool("flowtest.validate_integration_plan", {"plan": plan})
        assert validated.structured_content["valid"] is True
        compilation = (
            await server.call_tool("flowtest.compile_integration_flowspec", {"plan": plan})
        ).structured_content
        assert compilation["importable"] is True
        diagnostics = await server.call_tool(
            "flowtest.explain_compiler_diagnostics", {"plan": plan}
        )
        assert diagnostics.structured_content["plan_fingerprint"] == plan["plan_fingerprint"]
        proposal_arguments = {
            "project_id": str(s51_context["project_id"]),
            "context_id": begun["id"],
            "context_revision_id": begun["revision"]["id"],
            "integration_plan": plan,
            "compilation": compilation,
            "idempotency_key": "s51-sdk-preview-v1",
            "service_mappings": {"orders": str(s51_context["service_id"])},
            "operation_mappings": {"health.check": str(s51_context["definition_id"])},
            "operation_version_mappings": {"health.check": 1},
        }
        preview = await server.call_tool("flowtest.propose_flow_draft", proposal_arguments)
        assert preview.structured_content["dry_run"] is True
        assert preview.structured_content["change_set_id"] is None
        persisted = await server.call_tool(
            "flowtest.propose_flow_draft",
            {
                **proposal_arguments,
                "idempotency_key": "s51-sdk-draft-v1",
                "dry_run": False,
            },
        )
        change_set_id = persisted.structured_content["change_set_id"]
        inspected = await server.call_tool(
            "flowtest.inspect_flow_proposal",
            {
                "project_id": str(s51_context["project_id"]),
                "change_set_id": change_set_id,
            },
        )
        assert inspected.structured_content["review_status"] == "pending"
        assert inspected.structured_content["applied"] is False

    async with s51_context["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(AIChangeSet)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkflowExecution)) == 0


async def _plan_chain(
    context: dict[str, Any],
    *,
    with_cleanup: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    client = context["client"]
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=context["mcp_headers"],
        json={
            "project_id": str(context["project_id"]),
            "name": "S51 integration context",
            "objective": "Compile a reviewed health integration flow",
            "required_evidence": ["contract"],
            "contract_revisions": [{"source_ref": "contract://orders/health", "revision": "1"}],
        },
    )
    assert begun.status_code == 201, begun.text
    context_body = begun.json()
    planned = await client.post(
        "/api/v1/mcp/flow/plans",
        headers=context["mcp_headers"],
        json={
            "project_id": str(context["project_id"]),
            "context_id": context_body["id"],
            "context_revision_id": context_body["revision"]["id"],
            "actors": [
                {
                    "id": "operator",
                    "role": "integration tester",
                    "evidence_refs": ["context://s51/operator"],
                }
            ],
            "preconditions": [],
            "target_environment": {
                "key": "s51",
                "source_ref": "environment://s51",
                "evidence_refs": ["environment://s51/revision/1"],
            },
            "operations": [{"definition_id": str(context["definition_id"])}],
            "cleanup_requirements": (
                [
                    {
                        "id": "cleanup-health",
                        "operation_ref": "health.check",
                        "cleanup_for_step_ids": ["health-check"],
                        "best_effort": False,
                        "evidence_refs": ["contract://orders/health"],
                    }
                ]
                if with_cleanup
                else []
            ),
        },
    )
    assert planned.status_code == 200, planned.text
    plan = planned.json()
    validated = await client.post(
        "/api/v1/mcp/flow/plans/validate",
        headers=context["mcp_headers"],
        json={"plan": plan},
    )
    assert validated.status_code == 200 and validated.json()["valid"] is True
    compiled = await client.post(
        "/api/v1/mcp/flow/plans/compile",
        headers=context["mcp_headers"],
        json={"plan": plan},
    )
    assert compiled.status_code == 200, compiled.text
    compilation = compiled.json()
    assert compilation["importable"] is True and compilation["flow_spec"] is not None
    explained = await client.post(
        "/api/v1/mcp/flow/plans/diagnostics",
        headers=context["mcp_headers"],
        json={"plan": plan},
    )
    assert explained.status_code == 200
    assert explained.json()["plan_fingerprint"] == plan["plan_fingerprint"]
    return context_body, plan, compilation


def _proposal_payload(
    context: dict[str, Any],
    test_context: dict[str, Any],
    plan: dict[str, Any],
    compilation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "project_id": str(context["project_id"]),
        "context_id": test_context["id"],
        "context_revision_id": test_context["revision"]["id"],
        "spec": deepcopy(compilation["flow_spec"]),
        "integration_plan": plan,
        "compilation": compilation,
        "service_mappings": {"orders": str(context["service_id"])},
        "operation_mappings": {"health.check": str(context["definition_id"])},
        "operation_version_mappings": {"health.check": 1},
    }


def _workflow_definition(definition_id: UUID) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "variables": {},
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "config": {},
            },
            {
                "id": "health",
                "type": "api",
                "name": "Health",
                "position": {"x": 180, "y": 0},
                "config": {"api_definition_id": str(definition_id), "api_version": 1},
            },
            {
                "id": "end",
                "type": "end",
                "name": "End",
                "position": {"x": 360, "y": 0},
                "config": {},
            },
        ],
        "edges": [
            {"id": "start-health", "source": "start", "target": "health"},
            {"id": "health-end", "source": "health", "target": "end"},
        ],
        "settings": {"fail_fast": True, "concurrency": 1, "default_timeout_seconds": 30},
    }
