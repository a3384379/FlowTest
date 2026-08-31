from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service, token_service
from app.domain.test_contexts import (
    ContextCompletenessSnapshot,
    ContextKnowledgeEdge,
    ContextKnowledgeFact,
    ContextKnowledgeNode,
    ContextKnowledgeSnapshot,
    ContextRevisionSnapshot,
    ExternalEvidenceFinding,
)
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.organizations import Organization, OrganizationMember
from app.models.test_contexts import ContextEvidenceItem
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_contexts import TestContextRevision as ContextRevisionModel


@pytest.fixture
async def context_inspector() -> AsyncIterator[dict[str, Any]]:
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
            email="context-inspector@example.test",
            display_name="Context Inspector administrator",
            password_hash=password_service.hash("unused-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="Context Inspector organization",
            slug="context-inspector-organization",
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
            name="Context Inspector project",
            created_by_id=actor.id,
        )
        other_project = Project(
            organization_id=organization.id,
            name="Other project",
            created_by_id=actor.id,
        )
        session.add_all([project, other_project])
        await session.flush()
        context = ContextModel(
            organization_id=organization.id,
            project_id=project.id,
            name="RuoYi 订单上下文",
            objective="检查 Controller 到 Mapper 的可追溯证据",
            target_environment_id=None,
            status="ready",
            current_revision=1,
            created_by_type="service_account",
            created_by_id=actor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            closed_at=None,
        )
        session.add(context)
        await session.flush()
        snapshot = _snapshot()
        revision = ContextRevisionModel(
            context_id=context.id,
            revision=1,
            repository_revisions=[{"source_ref": "repository://ruoyi", "revision": "ruoyi-fixed"}],
            contract_revisions=[],
            data_profile_revisions=[],
            existing_test_revision=None,
            knowledge_snapshot=snapshot.knowledge_snapshot.model_dump(mode="json"),
            completeness=snapshot.completeness.model_dump(mode="json"),
            conflict_snapshot=snapshot.conflict_snapshot.model_dump(mode="json"),
            evidence_fingerprints=["b" * 64],
            fingerprint="a" * 64,
            created_by_type="service_account",
            created_by_id=actor.id,
            created_at=datetime.now(UTC),
        )
        session.add(revision)
        await session.flush()
        finding = _finding()
        evidence = ContextEvidenceItem(
            context_revision_id=revision.id,
            source_type="repository",
            provider_name="flowtest-java-spring",
            provider_version="1.0.0",
            source_ref="repository://ruoyi",
            source_revision="ruoyi-fixed",
            subject_ref="java://com.ruoyi.OrderController.create",
            finding_payload=finding.model_dump(mode="json"),
            semantic_role="normative",
            deterministic=True,
            confidence=1.0,
            fingerprint="b" * 64,
            redactions=[],
            warnings=[{"code": "LOMBOK_REVIEW", "message": "Lombok 语义需人工确认"}],
            data_classification="internal_redacted",
            created_at=datetime.now(UTC),
            expires_at=context.expires_at,
        )
        proposal = AIChangeSet(
            project_id=project.id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title="RuoYi 订单 Flow Proposal",
            status="draft",
            source_snapshot={
                "context_revision_id": str(revision.id),
                "context_fingerprint": revision.fingerprint,
                "target_workflow_id": None,
                "target_revision": None,
            },
            source_fingerprint="c" * 64,
            source_type="flow_spec",
            source_ref=f"mcp://contexts/{context.id}/revisions/{revision.id}/flow-drafts",
            actor_type="service_account",
            actor_id=None,
            created_by_id=actor.id,
            applied_at=None,
        )
        foreign_proposal = AIChangeSet(
            project_id=other_project.id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title="其他项目伪造 Revision 关联",
            status="draft",
            source_snapshot={"context_revision_id": str(revision.id)},
            source_fingerprint="d" * 64,
            source_type="flow_spec",
            source_ref="mcp://foreign-project/flow-drafts",
            actor_type="service_account",
            actor_id=None,
            created_by_id=actor.id,
            applied_at=None,
        )
        session.add_all([evidence, proposal, foreign_proposal])
        await session.flush()
        session.add_all(
            [
                AIChangeItem(
                    change_set_id=proposal.id,
                    suggestion_id=None,
                    position=0,
                    item_type="workflow",
                    action="create",
                    title="RuoYi 订单流程",
                    target_resource_id=None,
                    target_snapshot_sha256=None,
                    proposed_content={"name": "RuoYi 订单流程"},
                    review_status="pending",
                    review_note="",
                    reviewed_by_id=None,
                    reviewed_at=None,
                    materialized_resource_type=None,
                    materialized_resource_id=None,
                ),
                AIChangeItem(
                    change_set_id=foreign_proposal.id,
                    suggestion_id=None,
                    position=0,
                    item_type="workflow",
                    action="create",
                    title="不应出现在当前项目",
                    target_resource_id=None,
                    target_snapshot_sha256=None,
                    proposed_content={"name": "不应出现在当前项目"},
                    review_status="pending",
                    review_note="",
                    reviewed_by_id=None,
                    reviewed_at=None,
                    materialized_resource_type=None,
                    materialized_resource_id=None,
                ),
            ]
        )
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
            "other_project_id": other_project.id,
            "context_id": context.id,
        }
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_project_user_can_inspect_context_evidence_knowledge_and_proposals(
    context_inspector: dict[str, Any],
) -> None:
    client = context_inspector["client"]
    project_id = context_inspector["project_id"]
    context_id = context_inspector["context_id"]
    listed = await client.get(
        f"/api/v1/projects/{project_id}/contexts",
        headers=context_inspector["headers"],
    )

    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    summary = listed.json()["items"][0]
    assert summary["name"] == "RuoYi 订单上下文"
    assert summary["status"] == "ready"
    assert summary["completeness"]["missing"] == []
    assert summary["evidence_count"] == 1
    assert summary["provider_count"] == 1
    assert summary["proposal_count"] == 1

    detail = await client.get(
        f"/api/v1/projects/{project_id}/contexts/{context_id}",
        headers=context_inspector["headers"],
    )

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["revision"]["knowledge_snapshot"]["nodes"][1]["kind"] == "state_candidate"
    assert body["providers"] == [
        {
            "source_type": "repository",
            "provider_name": "flowtest-java-spring",
            "provider_version": "1.0.0",
            "finding_count": 1,
            "deterministic_count": 1,
            "conflict_count": 0,
        }
    ]
    assert body["evidence_items"][0]["finding"]["statement"] == (
        "OrderController.create 提供 POST /orders 路由"
    )
    assert body["evidence_items"][0]["warnings"][0]["code"] == "LOMBOK_REVIEW"
    assert body["proposals"][0]["review_status"] == "pending"
    assert body["proposals"][0]["applied"] is False


@pytest.mark.asyncio
async def test_context_inspector_is_project_scoped_and_computes_expiry_without_mutation(
    context_inspector: dict[str, Any],
) -> None:
    client = context_inspector["client"]
    context_id = context_inspector["context_id"]
    other_project_id = context_inspector["other_project_id"]
    hidden = await client.get(
        f"/api/v1/projects/{other_project_id}/contexts/{context_id}",
        headers=context_inspector["headers"],
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "TEST_CONTEXT_NOT_FOUND"

    async with context_inspector["sessions"]() as session:
        context = await session.get(ContextModel, UUID(str(context_id)))
        assert context is not None
        context.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    expired = await client.get(
        f"/api/v1/projects/{context_inspector['project_id']}/contexts/{context_id}",
        headers=context_inspector["headers"],
    )
    assert expired.status_code == 200, expired.text
    assert expired.json()["status"] == "expired"

    async with context_inspector["sessions"]() as session:
        persisted = await session.get(ContextModel, UUID(str(context_id)))
        assert persisted is not None
        assert persisted.status == "ready"

    unauthenticated = await client.get(
        f"/api/v1/projects/{context_inspector['project_id']}/contexts"
    )
    assert unauthenticated.status_code == 401


def _snapshot() -> ContextRevisionSnapshot:
    return ContextRevisionSnapshot(
        repository_revisions=[{"source_ref": "repository://ruoyi", "revision": "ruoyi-fixed"}],
        knowledge_snapshot=ContextKnowledgeSnapshot(
            nodes=[
                ContextKnowledgeNode(
                    id="operation.create_order",
                    kind="operation",
                    label="POST /orders",
                    facts=[
                        ContextKnowledgeFact(
                            name="evidence_ref",
                            value=f"evidence://context/{'b' * 64}",
                        )
                    ],
                ),
                ContextKnowledgeNode(
                    id="state.order_created",
                    kind="state_candidate",
                    label="Order.CREATED",
                    facts=[
                        ContextKnowledgeFact(
                            name="evidence_ref",
                            value=f"evidence://context/{'b' * 64}",
                        )
                    ],
                ),
            ],
            edges=[
                ContextKnowledgeEdge(
                    source="operation.create_order",
                    target="state.order_created",
                    relation="allows_state",
                )
            ],
        ),
        completeness=ContextCompletenessSnapshot(
            required=["repository"],
            present=["repository"],
            missing=[],
            complete=True,
        ),
        evidence_fingerprints=["b" * 64],
    )


def _finding() -> ExternalEvidenceFinding:
    payload: dict[str, Any] = {
        "id": "route-create-order",
        "kind": "operation",
        "semantic_role": "normative",
        "source_ref": "repository://ruoyi",
        "source_revision": "ruoyi-fixed",
        "subject_ref": "java://com.ruoyi.OrderController.create",
        "source_path": "src/OrderController.java:20",
        "source_content": "structured_analysis",
        "content_role": "untrusted_data",
        "statement": "OrderController.create 提供 POST /orders 路由",
        "confidence": 1.0,
        "deterministic": True,
    }
    payload["semantic_fingerprint"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "semantic_fingerprint"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return ExternalEvidenceFinding.model_validate(payload)
