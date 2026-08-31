from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.context import reset_tenant_context, set_tenant_context
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service, token_service
from app.domain.tenant import TenantContext
from app.domain.test_contexts import (
    ContextCompletenessSnapshot,
    ContextConflictSnapshot,
    ContextKnowledgeSnapshot,
)
from app.engine.contracts import (
    CleanupRunWhen,
    NodeType,
    Position,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPhase,
)
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.ai import AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.organizations import Organization, OrganizationMember
from app.models.service_targets import Service, ServiceEndpoint
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_contexts import TestContextRevision as ContextRevisionModel
from app.models.workflows import (
    Workflow,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)
from app.schemas.failure_repair import RepairProposalCreate
from app.services.failure_repair import FailureRepairService


@pytest.fixture
async def failure_repair_api() -> AsyncIterator[dict[str, Any]]:
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
            email="failure-repair@example.test",
            display_name="Failure Repair owner",
            password_hash=password_service.hash("unused-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="Failure Repair organization",
            slug="failure-repair-organization",
            description="",
            enabled=True,
            created_by_id=None,
        )
        session.add_all([actor, organization])
        await session.flush()
        organization.created_by_id = actor.id
        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=actor.id,
                role="owner",
            )
        )
        project = Project(
            organization_id=organization.id,
            name="Failure Repair project",
            created_by_id=actor.id,
        )
        session.add(project)
        await session.flush()
        service = Service(
            project_id=project.id,
            service_key="repair-api",
            name="Repair API",
            description="",
            owner_team=None,
            service_type="https",
            enabled=True,
            created_by_id=actor.id,
        )
        session.add(service)
        await session.flush()
        environment = Environment(
            project_id=project.id,
            name="Repair sandbox",
            base_url="https://sandbox.example.test",
            classification="test",
            default_service_id=service.id,
            variables={},
            headers={},
            created_by_id=actor.id,
        )
        api = APIDefinition(
            project_id=project.id,
            folder_id=None,
            service_id=service.id,
            name="Repair resource",
            description="",
            current_version=1,
            is_active=True,
            import_key=None,
            import_fingerprint=None,
            import_source=None,
            import_source_key=None,
            created_by_id=actor.id,
        )
        session.add(api)
        await session.flush()
        api_versions = [
            APIVersion(
                api_definition_id=api.id,
                service_id=service.id,
                version=version_number,
                method="DELETE",
                path="/fixtures",
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
                contract_fingerprint=fingerprint,
                contract_completeness="complete",
                created_by_id=actor.id,
            )
            for version_number, fingerprint in ((1, "c" * 64), (2, "d" * 64))
        ]
        session.add_all(api_versions)
        definition = _definition(api.id)
        workflow = Workflow(
            project_id=project.id,
            folder_id=None,
            name="Repair target",
            description="",
            draft_definition=definition.model_dump(mode="json"),
            draft_revision=1,
            current_version=1,
            created_by_id=actor.id,
        )
        session.add_all([environment, workflow])
        await session.flush()
        session.add(
            ServiceEndpoint(
                project_id=project.id,
                environment_id=environment.id,
                service_id=service.id,
                variant="default",
                base_url=environment.base_url,
                enabled=True,
                connect_timeout_ms=5000,
                read_timeout_ms=30000,
                tls_verify=True,
                proxy_ref=None,
                headers={},
                variables={},
                secret_refs=[],
                health_check_path=None,
                health_expected_status=None,
                revision=1,
                created_by_id=actor.id,
            )
        )
        version = WorkflowVersion(
            workflow_id=workflow.id,
            version=1,
            definition=definition.model_dump(mode="json"),
            fingerprint="a" * 64,
            created_by_id=actor.id,
            published_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()
        execution = WorkflowExecution(
            project_id=project.id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            environment_id=environment.id,
            triggered_by_id=actor.id,
            parent_execution_id=None,
            dataset_row_index=None,
            run_purpose="standard",
            source_change_set_id=None,
            preview_approval_id=None,
            preview_budget={},
            preview_evidence={},
            status="failed",
            main_status="failed",
            cleanup_status=None,
            cleanup_report={},
            snapshot={
                "schema_version": "1.0",
                "workflow": {
                    "id": str(workflow.id),
                    "version_id": str(version.id),
                    "version": 1,
                    "fingerprint": version.fingerprint,
                    "definition": definition.model_dump(mode="json"),
                },
            },
            context={},
            error_code="TEST_DATA_MISSING",
            error_message="缺少测试数据",
            started_at=datetime.now(UTC) - timedelta(seconds=1),
            completed_at=datetime.now(UTC),
        )
        session.add(execution)
        await session.flush()
        session.add_all(
            [
                WorkflowNodeExecution(
                    workflow_execution_id=execution.id,
                    node_id="start",
                    node_type="start",
                    name="Start",
                    phase="main",
                    best_effort=False,
                    status="failed",
                    attempts=1,
                    output=None,
                    result=None,
                    error_code="TEST_DATA_MISSING",
                    error_message="缺少测试数据",
                    started_at=execution.started_at,
                    completed_at=execution.completed_at,
                ),
                WorkflowNodeExecution(
                    workflow_execution_id=execution.id,
                    node_id="end",
                    node_type="end",
                    name="End",
                    phase="main",
                    best_effort=False,
                    status="cancelled",
                    attempts=0,
                    output=None,
                    result=None,
                    error_code="UPSTREAM_FAILED",
                    error_message="上游节点失败",
                    started_at=execution.started_at,
                    completed_at=execution.completed_at,
                ),
            ]
        )
        context = ContextModel(
            organization_id=organization.id,
            project_id=project.id,
            name="Repair context",
            objective="修复失败工作流",
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
        completeness = ContextCompletenessSnapshot(
            required=["contract"],
            present=["contract"],
            missing=[],
            complete=True,
        )
        revision = ContextRevisionModel(
            context_id=context.id,
            revision=1,
            repository_revisions=[],
            contract_revisions=[],
            data_profile_revisions=[],
            existing_test_revision=None,
            knowledge_snapshot=ContextKnowledgeSnapshot().model_dump(mode="json"),
            completeness=completeness.model_dump(mode="json"),
            conflict_snapshot=ContextConflictSnapshot().model_dump(mode="json"),
            evidence_fingerprints=[],
            fingerprint="b" * 64,
            created_by_type="user",
            created_by_id=actor.id,
            created_at=datetime.now(UTC),
        )
        session.add(revision)
        await session.commit()
        token = token_service.create_access_token(actor.id)

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
            "sessions": sessions,
            "headers": {"Authorization": f"Bearer {token}"},
            "project_id": project.id,
            "organization_id": organization.id,
            "execution_id": execution.id,
            "workflow_id": workflow.id,
            "environment_id": environment.id,
            "context_revision_id": revision.id,
        }
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_s58_diagnoses_failure_and_creates_reviewable_repreview_proposal(
    failure_repair_api: dict[str, Any],
) -> None:
    client: AsyncClient = failure_repair_api["client"]
    project_id = failure_repair_api["project_id"]
    execution_id = failure_repair_api["execution_id"]
    workflow_id = failure_repair_api["workflow_id"]
    headers = failure_repair_api["headers"]

    diagnosed = await client.get(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/failure-diagnosis",
        headers=headers,
    )
    assert diagnosed.status_code == 200, diagnosed.text
    diagnosis = diagnosed.json()["diagnosis"]
    assert diagnosis["triage"]["primary_classification"] == "BAD_TEST_DATA"
    assert diagnosis["repair_policy"]["allowed_kinds"] == ["data", "binding"]
    assert diagnosis["repair_policy"]["product_defect_guard"] is False

    exported = await client.get(
        f"/api/v1/projects/{project_id}/flow-specs/workflows/{workflow_id}/export",
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    spec = exported.json()["spec"]
    spec["variables"] = {"customer_id": "fixture-customer"}
    request = {
        "kind": "data",
        "proposed_spec": spec,
        "expected_target_revision": 1,
        "context_revision_id": str(failure_repair_api["context_revision_id"]),
        "rationale": "补充失败执行缺失的确定性测试数据",
    }
    created = await client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/repair-proposals",
        headers={**headers, "Idempotency-Key": "s58-data-repair"},
        json=request,
    )
    assert created.status_code == 201, created.text
    proposal = created.json()["proposal"]
    assert proposal["review_status"] == "pending"
    assert proposal["target_workflow_id"] == str(workflow_id)
    assert proposal["spec"]["variables"] == {"customer_id": "fixture-customer"}

    duplicate = await client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/repair-proposals",
        headers={**headers, "Idempotency-Key": "s58-data-repair"},
        json=request,
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["proposal"]["id"] == proposal["id"]

    accepted = await client.post(
        f"/api/v1/projects/{project_id}/flow-specs/change-sets/{proposal['id']}/review",
        headers=headers,
        json={"accept": True, "note": "确认数据修复范围"},
    )
    assert accepted.status_code == 200, accepted.text
    approval = await client.post(
        f"/api/v1/projects/{project_id}/flow-specs/change-sets/{proposal['id']}/preview-approvals",
        headers=headers,
        json={"environment_id": str(failure_repair_api["environment_id"])},
    )
    assert approval.status_code == 201, approval.text
    assert approval.json()["change_set_id"] == proposal["id"]

    async with failure_repair_api["sessions"]() as session:
        change_set = await session.scalar(
            select(AIChangeSet).where(AIChangeSet.id == UUID(proposal["id"]))
        )
        assert change_set is not None
        assert change_set.source_snapshot["proposal_schema_version"] == (
            "v6-repair-proposal-source-v1"
        )
        assert change_set.source_snapshot["repair"]["patch_kind"] == "data"
        assert change_set.source_snapshot["repair"]["execution_id"] == str(execution_id)
        assert change_set.source_snapshot["repair"]["expected_target_revision"] == 1


@pytest.mark.asyncio
async def test_s58_rejects_sensitive_repair_rationale_before_persistence(
    failure_repair_api: dict[str, Any],
) -> None:
    client: AsyncClient = failure_repair_api["client"]
    project_id = failure_repair_api["project_id"]
    execution_id = failure_repair_api["execution_id"]
    workflow_id = failure_repair_api["workflow_id"]
    headers = failure_repair_api["headers"]
    exported = await client.get(
        f"/api/v1/projects/{project_id}/flow-specs/workflows/{workflow_id}/export",
        headers=headers,
    )
    spec = exported.json()["spec"]
    spec["variables"] = {"customer_id": "fixture-customer"}

    rejected = await client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/repair-proposals",
        headers={**headers, "Idempotency-Key": "s58-sensitive-rationale"},
        json={
            "kind": "data",
            "proposed_spec": spec,
            "expected_target_revision": 1,
            "context_revision_id": str(failure_repair_api["context_revision_id"]),
            "rationale": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature",
        },
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "REPAIR_SENSITIVE_INPUT_FORBIDDEN"
    async with failure_repair_api["sessions"]() as session:
        proposals = list((await session.scalars(select(AIChangeSet))).all())
        assert proposals == []


@pytest.mark.asyncio
async def test_s58_rejects_pinned_version_and_contract_fingerprint_mismatch(
    failure_repair_api: dict[str, Any],
) -> None:
    client: AsyncClient = failure_repair_api["client"]
    project_id = failure_repair_api["project_id"]
    execution_id = failure_repair_api["execution_id"]
    workflow_id = failure_repair_api["workflow_id"]
    headers = failure_repair_api["headers"]

    async with failure_repair_api["sessions"]() as session:
        execution = await session.get(WorkflowExecution, execution_id)
        assert execution is not None
        execution.error_code = "RESPONSE_SCHEMA_MISMATCH"
        execution.error_message = "响应契约与固定版本不一致"
        failed_node = await session.scalar(
            select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_execution_id == execution_id,
                WorkflowNodeExecution.node_id == "start",
            )
        )
        assert failed_node is not None
        failed_node.error_code = "RESPONSE_SCHEMA_MISMATCH"
        failed_node.error_message = "响应契约与固定版本不一致"
        await session.commit()

    exported = await client.get(
        f"/api/v1/projects/{project_id}/flow-specs/workflows/{workflow_id}/export",
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    spec = exported.json()["spec"]
    assert spec["operations"][0]["source_version"] == 1
    assert spec["operations"][0]["contract_fingerprint"] == "c" * 64
    spec["operations"][0]["source_version"] = 2

    rejected = await client.post(
        f"/api/v1/projects/{project_id}/workflow-executions/{execution_id}/repair-proposals",
        headers={**headers, "Idempotency-Key": "s58-contract-version-mismatch"},
        json={
            "kind": "contract_drift",
            "proposed_spec": spec,
            "expected_target_revision": 1,
            "context_revision_id": str(failure_repair_api["context_revision_id"]),
            "rationale": "验证固定版本必须与契约指纹匹配",
        },
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "FLOWSPEC_API_VERSION_INCOMPATIBLE"
    async with failure_repair_api["sessions"]() as session:
        proposals = list((await session.scalars(select(AIChangeSet))).all())
        assert proposals == []


@pytest.mark.asyncio
async def test_s58_rechecks_target_revision_after_idempotency_preflight(
    failure_repair_api: dict[str, Any],
) -> None:
    client: AsyncClient = failure_repair_api["client"]
    project_id = failure_repair_api["project_id"]
    execution_id = failure_repair_api["execution_id"]
    workflow_id = failure_repair_api["workflow_id"]
    exported = await client.get(
        f"/api/v1/projects/{project_id}/flow-specs/workflows/{workflow_id}/export",
        headers=failure_repair_api["headers"],
    )
    spec = exported.json()["spec"]
    spec["variables"] = {"customer_id": "fixture-customer"}
    payload = RepairProposalCreate.model_validate(
        {
            "kind": "data",
            "proposed_spec": spec,
            "expected_target_revision": 1,
            "context_revision_id": failure_repair_api["context_revision_id"],
            "rationale": "验证持久化前再次检查目标草稿版本",
        }
    )

    async with failure_repair_api["sessions"]() as session:
        actor = await session.scalar(
            select(User).where(User.email == "failure-repair@example.test")
        )
        assert actor is not None
        context_token = set_tenant_context(
            TenantContext(
                organization_id=failure_repair_api["organization_id"],
                actor_id=actor.id,
                role=None,
                is_system_admin=True,
            )
        )
        try:
            service = FailureRepairService(session)
            prepared = await service.prepare_repair_proposal(
                actor=actor,
                project_id=project_id,
                execution_id=execution_id,
                payload=payload,
            )
            workflow = await session.get(Workflow, workflow_id)
            assert workflow is not None
            workflow.draft_revision = 2
            await session.commit()

            with pytest.raises(AppError) as error_info:
                await service.persist_repair_proposal(prepared)
        finally:
            reset_tenant_context(context_token)
        assert error_info.value.code == "FLOWSPEC_TARGET_CONFLICT"


def _definition(api_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version="2.0",
        nodes=[
            WorkflowNode(
                id="start",
                type=NodeType.START,
                name="Start",
                position=Position(x=0, y=0),
            ),
            WorkflowNode(
                id="api",
                type=NodeType.API,
                name="Create fixture",
                position=Position(x=100, y=0),
                config={"api_definition_id": str(api_id), "api_version": 1},
            ),
            WorkflowNode(
                id="end",
                type=NodeType.END,
                name="End",
                position=Position(x=200, y=0),
            ),
            WorkflowNode(
                id="cleanup",
                type=NodeType.API,
                name="Delete fixture",
                position=Position(x=100, y=160),
                config={"api_definition_id": str(api_id), "api_version": 1},
                phase=WorkflowPhase.CLEANUP,
                run_when=CleanupRunWhen.ALWAYS,
                cleanup_for=["api"],
                best_effort=True,
            ),
        ],
        edges=[
            WorkflowEdge(id="start-api", source="start", target="api"),
            WorkflowEdge(id="api-end", source="api", target="end"),
        ],
    )
