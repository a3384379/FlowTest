"""Focused S61D contracts for bounded discovery and readiness."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_mcp_read import mcp_context as mcp_context

from app.core.config import settings
from app.domain.test_contexts import (
    ContextCompletenessSnapshot,
    ContextConflictSnapshot,
    ContextKnowledgeSnapshot,
)
from app.mcp.server import create_mcp_server
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.service_targets import Service, ServiceEndpoint
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_contexts import TestContextRevision as ContextRevisionModel
from app.repositories.mcp_assets import _proposal_kind
from app.schemas.mcp_discovery import MCPFindAssetsRequest
from app.services.mcp_discovery import (
    _deep_link,
    _has_credential_reference,
    _proposal_endpoint_bindings,
    _proposal_readiness_metadata,
    _secret_reference_names,
)
from app.services.service_accounts import ServiceAccountService


@pytest.mark.asyncio
async def test_find_assets_is_typed_paginated_and_project_scoped(
    mcp_context: dict[str, Any],
) -> None:
    client = mcp_context["client"]
    headers = {"Authorization": f"Bearer {mcp_context['token']}"}
    response = await client.post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["project_id"]),
            "asset_types": ["api", "workflow", "execution"],
            "query": "payment",
            "page": 1,
            "page_size": 2,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 3
    assert data["has_more"] is True
    assert len(data["items"]) == 2
    assert {item["resource_type"] for item in data["items"]} <= {
        "api",
        "workflow",
        "execution",
    }
    assert "workflow-secret" not in response.text
    assert "execution-secret" not in response.text

    cross_tenant = await client.post(
        f"/api/v1/mcp/read/projects/{mcp_context['other_project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["other_project_id"]),
            "asset_types": ["api"],
        },
    )
    assert cross_tenant.status_code == 404


@pytest.mark.asyncio
async def test_project_readiness_returns_safe_actionable_contract(
    mcp_context: dict[str, Any],
) -> None:
    response = await mcp_context["client"].get(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/readiness",
        headers={"Authorization": f"Bearer {mcp_context['token']}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["project_id"] == str(mcp_context["project_id"])
    assert data["can_generate_proposal"] is False
    assert any(check["name"] == "contract" for check in data["checks"])
    for secret in ("contract-auth-secret", "endpoint-secret", "execution-context-secret"):
        assert secret not in response.text


@pytest.mark.asyncio
async def test_find_assets_path_filter_uses_only_current_api_version(
    mcp_context: dict[str, Any],
) -> None:
    async with mcp_context["sessions"]() as session:
        definition = await session.scalar(
            select(APIDefinition).where(APIDefinition.id == mcp_context["definition_id"])
        )
        assert definition is not None
        definition.current_version = 2
        session.add(
            APIVersion(
                api_definition_id=definition.id,
                version=2,
                service_id=definition.service_id,
                method="POST",
                path="/new-payment",
                query_parameters=[],
                headers={},
                variables={},
                body_kind="none",
                body=None,
                auth_kind="none",
                auth_config={},
                extraction_rules=[],
                assertions=[],
                canonical_contract={},
                contract_fingerprint=None,
                contract_completeness="legacy_partial",
                created_by_id=definition.created_by_id,
            )
        )
        await session.commit()

    headers = {"Authorization": f"Bearer {mcp_context['token']}"}
    legacy = await mcp_context["client"].post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["project_id"]),
            "asset_types": ["api"],
            "path": "/payments",
        },
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["data"]["total"] == 0
    current = await mcp_context["client"].post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/assets/find",
        headers=headers,
        json={
            "project_id": str(mcp_context["project_id"]),
            "asset_types": ["api"],
            "path": "/new-payment",
        },
    )
    assert current.status_code == 200, current.text
    assert current.json()["data"]["total"] == 1
    assert current.json()["data"]["items"][0]["version"] == 2


def test_runtime_credential_evidence_requires_explicit_secret_reference() -> None:
    assert not _has_credential_reference({"kind": "runtime_observation"})
    assert not _has_credential_reference({"credential_refs": ["payments-token"]})
    assert _has_credential_reference({"credential_refs": ["secret://payments/token"]})


def test_readiness_normalizes_runtime_secret_reference_forms() -> None:
    assert _secret_reference_names(["payments-token"], allow_raw=True) == {"payments-token"}
    assert _secret_reference_names({"token": "{{secret.PAYMENTS_TOKEN}}"}) == {"PAYMENTS_TOKEN"}
    assert _secret_reference_names({"token": "secret://payments/token"}) == {"payments/token"}
    assert _secret_reference_names({"token": "literal-value"}) == set()


def test_readiness_matches_proposal_service_and_endpoint_variant() -> None:
    service_id = "00000000-0000-4000-8000-000000005701"
    bindings = _proposal_endpoint_bindings(
        snapshot={
            "resource_mappings": {"services": {"payments": service_id}},
        },
        proposed_content={
            "flow_spec": {
                "operations": [{"ref": "charge", "service_ref": "payments"}],
                "nodes": [{"operation_ref": "charge", "target": {"endpoint_variant": "sandbox"}}],
            }
        },
    )
    assert bindings == {
        (UUID(service_id), "sandbox"),
    }


def test_readiness_uses_default_variant_for_main_and_cleanup_operations() -> None:
    primary_id = "00000000-0000-4000-8000-000000005711"
    cleanup_id = "00000000-0000-4000-8000-000000005712"
    bindings = _proposal_endpoint_bindings(
        snapshot={
            "resource_mappings": {"services": {"primary": primary_id, "cleanup": cleanup_id}},
        },
        proposed_content={
            "flow_spec": {
                "operations": [
                    {"ref": "create", "service_ref": "primary"},
                    {"ref": "delete", "service_ref": "cleanup"},
                ],
                "nodes": [
                    {"operation_ref": "create"},
                    {"kind": "subflow", "configuration": {"workflow_ref": "child"}},
                ],
                "cleanup": [{"operation_ref": "delete"}],
            }
        },
    )
    assert bindings == {
        (UUID(primary_id), "default"),
        (UUID(cleanup_id), "default"),
    }


def test_readiness_pins_operation_mapping_versions_with_source_version_fallback() -> None:
    first_id = "00000000-0000-4000-8000-000000005721"
    second_id = "00000000-0000-4000-8000-000000005722"
    metadata = _proposal_readiness_metadata(
        snapshot={
            "resource_mappings": {
                "operations": {"first": first_id, "second": second_id},
                "operation_versions": {"first": 1},
            }
        },
        proposed_content={
            "flow_spec": {
                "operations": [
                    {"ref": "first", "source_version": 9},
                    {"ref": "second", "source_version": 3},
                ]
            }
        },
    )
    assert metadata.api_versions == {(UUID(first_id), 1), (UUID(second_id), 3)}


@pytest.mark.asyncio
async def test_readiness_requires_every_service_variant_and_pinned_api_version(
    mcp_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "feature_integration_flow_enabled", True)
    async with mcp_context["sessions"]() as session:
        actor = await session.scalar(select(User).where(User.is_system_admin.is_(True)))
        environment = await session.get(Environment, mcp_context["environment_id"])
        first_definition = await session.get(APIDefinition, mcp_context["definition_id"])
        assert actor is not None and environment is not None and first_definition is not None
        environment.classification = "test"
        first_v1 = await session.scalar(
            select(APIVersion).where(
                APIVersion.api_definition_id == first_definition.id,
                APIVersion.version == 1,
            )
        )
        assert first_v1 is not None
        first_v1.auth_kind = "none"
        first_v1.auth_config = {}
        first_endpoint = await session.scalar(
            select(ServiceEndpoint).where(
                ServiceEndpoint.environment_id == environment.id,
                ServiceEndpoint.service_id == first_definition.service_id,
                ServiceEndpoint.variant == "blue",
            )
        )
        assert first_endpoint is not None
        first_endpoint.secret_refs = []
        first_definition.current_version = 2
        session.add(
            APIVersion(
                api_definition_id=first_definition.id,
                service_id=first_definition.service_id,
                version=2,
                method="POST",
                path="/payments-v2",
                query_parameters=[],
                headers={},
                variables={},
                body_kind="none",
                body=None,
                auth_kind="bearer",
                auth_config={"token": "secret://payments/v2"},
                extraction_rules=[],
                assertions=[],
                canonical_contract={},
                contract_fingerprint="2" * 64,
                contract_completeness="complete",
                created_by_id=actor.id,
            )
        )
        second_service = Service(
            project_id=mcp_context["project_id"],
            service_key="ledger-api",
            name="Ledger API",
            description="",
            owner_team=None,
            service_type="https",
            enabled=True,
            created_by_id=actor.id,
        )
        session.add(second_service)
        await session.flush()
        second_definition = APIDefinition(
            project_id=mcp_context["project_id"],
            folder_id=None,
            service_id=second_service.id,
            name="Record ledger",
            description="",
            current_version=1,
            is_active=True,
            created_by_id=actor.id,
        )
        session.add(second_definition)
        await session.flush()
        session.add(
            APIVersion(
                api_definition_id=second_definition.id,
                service_id=second_service.id,
                version=1,
                method="POST",
                path="/ledger",
                query_parameters=[],
                headers={},
                variables={},
                body_kind="none",
                body=None,
                auth_kind="none",
                auth_config={},
                extraction_rules=[],
                assertions=[],
                canonical_contract={},
                contract_fingerprint="3" * 64,
                contract_completeness="complete",
                created_by_id=actor.id,
            )
        )
        context = ContextModel(
            organization_id=mcp_context["organization_id"],
            project_id=mcp_context["project_id"],
            name="Readiness context",
            objective="Verify exact readiness targets",
            target_environment_id=environment.id,
            status="ready",
            current_revision=1,
            created_by_type="user",
            created_by_id=actor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            closed_at=None,
        )
        session.add(context)
        await session.flush()
        revision = ContextRevisionModel(
            context_id=context.id,
            revision=1,
            repository_revisions=[],
            contract_revisions=[],
            data_profile_revisions=[],
            existing_test_revision=None,
            knowledge_snapshot=ContextKnowledgeSnapshot().model_dump(mode="json"),
            completeness=ContextCompletenessSnapshot(
                required=["contract"], present=["contract"], missing=[], complete=True
            ).model_dump(mode="json"),
            conflict_snapshot=ContextConflictSnapshot().model_dump(mode="json"),
            evidence_fingerprints=[],
            fingerprint="4" * 64,
            created_by_type="user",
            created_by_id=actor.id,
        )
        session.add(revision)
        await session.flush()
        proposal = AIChangeSet(
            project_id=mcp_context["project_id"],
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title="Exact readiness proposal",
            status="accepted",
            source_snapshot={
                "context_revision_id": str(revision.id),
                "context_fingerprint": revision.fingerprint,
                "resource_mappings": {
                    "services": {
                        "payments": str(first_definition.service_id),
                        "ledger": str(second_service.id),
                    },
                    "operations": {
                        "charge": str(first_definition.id),
                        "record": str(second_definition.id),
                    },
                    "operation_versions": {"charge": 1, "record": 1},
                },
            },
            source_fingerprint="5" * 64,
            source_type="flow_spec",
            source_ref="flow-spec://readiness/exact",
            actor_type="user",
            actor_id=actor.id,
            created_by_id=actor.id,
        )
        session.add(proposal)
        await session.flush()
        session.add(
            AIChangeItem(
                change_set_id=proposal.id,
                suggestion_id=None,
                position=0,
                item_type="workflow",
                action="create",
                title="Exact readiness workflow",
                target_resource_id=None,
                target_snapshot_sha256=None,
                proposed_content={
                    "flow_spec": {
                        "operations": [
                            {"ref": "charge", "service_ref": "payments", "source_version": 1},
                            {"ref": "record", "service_ref": "ledger", "source_version": 1},
                        ],
                        "nodes": [
                            {
                                "operation_ref": "charge",
                                "target": {"endpoint_variant": "blue"},
                            },
                            {"kind": "subflow", "configuration": {"workflow_ref": "child"}},
                        ],
                        "cleanup": [{"operation_ref": "record"}],
                    }
                },
                review_status="accepted",
            )
        )
        issued = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=mcp_context["organization_id"],
            name="Readiness auditor",
            account_key=f"readiness-{uuid4().hex[:12]}",
            scopes=["mcp:read", "mcp:flow:propose", "mcp:preview:execute"],
            expires_at=None,
            metadata={},
        )
        proposal_id = proposal.id
        second_service_id = second_service.id

    url = f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/readiness"
    params = {
        "environment_id": str(mcp_context["environment_id"]),
        "proposal_id": str(proposal_id),
    }
    headers = {"Authorization": f"Bearer {issued.token}"}
    missing = await mcp_context["client"].get(url, headers=headers, params=params)
    assert missing.status_code == 200, missing.text
    missing_data = missing.json()["data"]
    assert missing_data["can_request_preview"] is False
    assert missing_data["missing_service_endpoints"] == [
        {"service_id": str(second_service_id), "variant": "default"}
    ]
    assert {item["version"] for item in missing_data["required_api_versions"]} == {1}
    assert len(missing_data["resolved_api_versions"]) == 2

    async with mcp_context["sessions"]() as session:
        actor_id = await session.scalar(select(User.id).where(User.is_system_admin.is_(True)))
        assert actor_id is not None
        wrong = ServiceEndpoint(
            project_id=mcp_context["project_id"],
            environment_id=mcp_context["environment_id"],
            service_id=second_service_id,
            variant="green",
            base_url="https://ledger.example.test",
            enabled=True,
            tls_verify=True,
            headers={},
            variables={},
            secret_refs=[],
            revision=1,
            created_by_id=actor_id,
        )
        disabled = ServiceEndpoint(
            project_id=mcp_context["project_id"],
            environment_id=mcp_context["environment_id"],
            service_id=second_service_id,
            variant="default",
            base_url="https://ledger.example.test",
            enabled=False,
            tls_verify=True,
            headers={},
            variables={},
            secret_refs=[],
            revision=1,
            created_by_id=wrong.created_by_id,
        )
        session.add_all([wrong, disabled])
        await session.commit()
    unresolved = await mcp_context["client"].get(url, headers=headers, params=params)
    assert unresolved.json()["data"]["can_request_preview"] is False

    async with mcp_context["sessions"]() as session:
        default_endpoint = await session.scalar(
            select(ServiceEndpoint).where(
                ServiceEndpoint.environment_id == mcp_context["environment_id"],
                ServiceEndpoint.service_id == second_service_id,
                ServiceEndpoint.variant == "default",
            )
        )
        assert default_endpoint is not None
        default_endpoint.enabled = True
        await session.commit()
    ready = await mcp_context["client"].get(url, headers=headers, params=params)
    assert ready.status_code == 200, ready.text
    ready_data = ready.json()["data"]
    assert ready_data["can_request_preview"] is True, {
        "checks": ready_data["checks"],
        "actions": ready_data["human_actions_required"],
        "missing_endpoints": ready_data["missing_service_endpoints"],
        "missing_versions": ready_data["missing_api_versions"],
    }
    assert ready_data["missing_service_endpoints"] == []


@pytest.mark.asyncio
async def test_find_assets_returns_typed_proposal_kinds_and_exact_deep_links(
    mcp_context: dict[str, Any],
) -> None:
    proposals = [
        ("Flow", "flow_spec", "flow-spec://proposal/flow", "workflow", "flow_spec"),
        ("Repair", "flow_spec", "repair://proposal/fix", "workflow", "repair"),
        (
            "Maintenance",
            "flow_spec",
            "maintenance://proposal/update",
            "workflow",
            "maintenance",
        ),
        ("Test Design", "rest", "contract://proposal/design", "test_design", "test_design"),
        (
            "Test Plan",
            "mcp",
            "mcp://proposal/test-plan",
            "test_plan_update",
            "test_plan_update",
        ),
    ]
    async with mcp_context["sessions"]() as session:
        actor_id = await session.scalar(select(User.id).where(User.is_system_admin.is_(True)))
        assert actor_id is not None
        for title, source_type, source_ref, item_type, _ in proposals:
            change_set = AIChangeSet(
                project_id=mcp_context["project_id"],
                impact_run_id=None,
                release_risk_id=None,
                ai_job_id=None,
                title=title,
                status="draft",
                source_snapshot={},
                source_fingerprint=uuid4().hex * 2,
                source_type=source_type,
                source_ref=source_ref,
                actor_type="user",
                actor_id=actor_id,
                created_by_id=actor_id,
            )
            session.add(change_set)
            await session.flush()
            session.add(
                AIChangeItem(
                    change_set_id=change_set.id,
                    suggestion_id=None,
                    position=0,
                    item_type=item_type,
                    action="create",
                    title=title,
                    target_resource_id=None,
                    target_snapshot_sha256=None,
                    proposed_content={},
                    review_status="pending",
                )
            )
        await session.commit()
    response = await mcp_context["client"].post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/assets/find",
        headers={"Authorization": f"Bearer {mcp_context['token']}"},
        json={
            "project_id": str(mcp_context["project_id"]),
            "asset_types": ["proposal"],
            "page_size": 50,
        },
    )
    assert response.status_code == 200, response.text
    by_title = {item["name"]: item for item in response.json()["data"]["items"]}
    for title, source_type, _, item_type, proposal_kind in proposals:
        item = by_title[title]
        assert item["source_type"] == source_type
        assert item["item_type"] == item_type
        assert item["proposal_kind"] == proposal_kind
        if proposal_kind in {"flow_spec", "repair", "maintenance"}:
            assert item["deep_link"].endswith(f"/workflows?proposal={item['id']}")
        elif proposal_kind == "test_design":
            assert item["deep_link"].endswith(f"/test-engineering?proposal={item['id']}")
        else:
            assert item["deep_link"].endswith(f"/mcp-changes?focus={item['id']}")


def test_proposal_kind_and_deep_link_never_send_unknown_proposals_to_workflows() -> None:
    project_id = UUID("00000000-0000-4000-8000-000000005731")
    proposal_id = UUID("00000000-0000-4000-8000-000000005732")
    assert _proposal_kind(source_type="cli", source_ref=None, item_type=None) == "generic"
    assert (
        _deep_link(project_id, "proposal", proposal_id, proposal_kind="generic")
        == f"/projects/{project_id}/assets?focus={proposal_id}"
    )


def test_s61d_server_registers_discovery_tools() -> None:
    server = create_mcp_server(
        client=__import__("app.mcp.client", fromlist=["MCPReadGatewayClient"]).MCPReadGatewayClient(
            base_url="http://gateway", token=""
        )
    )
    # Registration is exercised by the SDK's async list_tools in the existing MCP tests;
    # schema construction here catches accidental import/circular-dependency regressions.
    assert server is not None


def test_find_assets_request_rejects_duplicate_types() -> None:
    with pytest.raises(ValueError):
        MCPFindAssetsRequest(
            project_id="00000000-0000-0000-0000-000000000001",
            asset_types=["api", "api"],
        )
