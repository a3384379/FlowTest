import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.governance import IdempotencyRecord
from app.models.organizations import Organization
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_contexts import TestContextRevision as ContextRevisionModel
from app.services import test_contexts as test_context_service
from app.services.service_accounts import ServiceAccountService


@pytest.fixture
async def s49_context() -> AsyncIterator[dict[str, Any]]:
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
            email="s49-admin@example.test",
            display_name="S49 administrator",
            password_hash=password_service.hash("unused-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="S49 organization",
            slug="s49-organization",
            description="",
            enabled=True,
            created_by_id=None,
        )
        other_organization = Organization(
            name="S49 other organization",
            slug="s49-other-organization",
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
            name="S49 project",
            created_by_id=actor.id,
        )
        other_project = Project(
            organization_id=other_organization.id,
            name="S49 other project",
            created_by_id=actor.id,
        )
        session.add_all([project, other_project])
        await session.flush()
        evidence = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="S49 evidence",
            account_key="s49-evidence",
            scopes=["mcp:evidence:write"],
            expires_at=None,
            metadata={},
        )
        flow = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="S49 flow",
            account_key="s49-flow",
            scopes=["mcp:flow:propose"],
            expires_at=None,
            metadata={},
        )
        legacy_write = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="S49 legacy writer",
            account_key="s49-legacy-writer",
            scopes=["mcp:write"],
            expires_at=None,
            metadata={},
        )
        combined = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="S49 combined",
            account_key="s49-combined",
            scopes=["mcp:evidence:write", "mcp:flow:propose"],
            expires_at=None,
            metadata={},
        )
        await session.commit()

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
            "project_id": project.id,
            "other_project_id": other_project.id,
            "evidence_token": evidence.token,
            "flow_token": flow.token,
            "write_token": legacy_write.token,
            "combined_token": combined.token,
            "combined_account_id": combined.account.id,
        }
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_context_revisions_are_immutable_scoped_and_secret_safe(
    s49_context: dict[str, Any],
) -> None:
    client = s49_context["client"]
    evidence_headers = _headers(s49_context["evidence_token"])
    legacy_headers = _headers(s49_context["write_token"])
    begin_payload = {
        "project_id": str(s49_context["project_id"]),
        "name": "支付集成上下文",
        "objective": "验证创建与查询支付记录",
        "required_evidence": ["contract"],
    }
    blank = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=evidence_headers,
        json={**begin_payload, "name": "   "},
    )
    assert blank.status_code == 422

    forbidden = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=legacy_headers,
        json=begin_payload,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "MCP_SCOPE_REQUIRED"

    sensitive_objective = "password=raw-context-secret"
    rejected_objective = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=evidence_headers,
        json={**begin_payload, "objective": sensitive_objective},
    )
    assert rejected_objective.status_code == 422
    assert rejected_objective.json()["error"]["code"] == "TEST_CONTEXT_SENSITIVE_INPUT"
    assert sensitive_objective not in rejected_objective.text

    raw_phone = "+8613800138000"
    rejected_knowledge = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=evidence_headers,
        json={
            **begin_payload,
            "knowledge_snapshot": {
                "nodes": [
                    {
                        "id": "customer",
                        "kind": "entity",
                        "label": "Customer",
                        "facts": [{"name": "contact", "value": raw_phone}],
                    }
                ]
            },
        },
    )
    assert rejected_knowledge.status_code == 422
    assert rejected_knowledge.json()["error"]["code"] == "TEST_CONTEXT_SENSITIVE_INPUT"
    assert raw_phone not in rejected_knowledge.text

    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=evidence_headers,
        json=begin_payload,
    )
    assert begun.status_code == 201, begun.text
    initial = begun.json()
    context_id = initial["id"]
    initial_fingerprint = initial["revision"]["fingerprint"]
    assert initial["status"] == "collecting"
    assert initial["current_revision"] == 1

    envelope = _evidence_envelope(
        project_id=str(s49_context["project_id"]),
        statement="The create operation returns an identifier used by the query operation.",
    )
    ingested = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=evidence_headers,
        json={"envelope": envelope},
    )
    assert ingested.status_code == 201, ingested.text
    current = ingested.json()
    assert current["status"] == "ready"
    assert current["current_revision"] == 2
    assert len(current["evidence_items"]) == 1
    assert "statement" not in current["evidence_items"][0]

    inspected = await client.get(
        f"/api/v1/mcp/evidence/contexts/{context_id}", headers=evidence_headers
    )
    requirements = await client.get(
        f"/api/v1/mcp/evidence/contexts/{context_id}/requirements",
        headers=evidence_headers,
    )
    assert inspected.json()["revision"]["fingerprint"] == current["revision"]["fingerprint"]
    assert requirements.json()["missing"] == []
    assert requirements.json()["complete"] is True
    async with s49_context["sessions"]() as session:
        revisions = list(
            (
                await session.scalars(
                    select(ContextRevisionModel)
                    .where(ContextRevisionModel.context_id == UUID(context_id))
                    .order_by(ContextRevisionModel.revision)
                )
            ).all()
        )
        assert [revision.revision for revision in revisions] == [1, 2]
        assert revisions[0].fingerprint == initial_fingerprint
        revisions[0].fingerprint = "f" * 64
        with pytest.raises(ValueError, match="immutable"):
            await session.flush()
        await session.rollback()

    cross_tenant_begin = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=evidence_headers,
        json={
            **begin_payload,
            "repository_revisions": [
                {
                    "source_ref": (
                        f"flowtest://projects/{s49_context['other_project_id']}/repository"
                    ),
                    "revision": "abc1234",
                }
            ],
        },
    )
    assert cross_tenant_begin.status_code == 404
    assert cross_tenant_begin.json()["error"]["code"] == "EXTERNAL_EVIDENCE_CROSS_TENANT"

    cross_tenant = _evidence_envelope(
        project_id=str(s49_context["other_project_id"]),
        statement="A finding from another tenant must not be visible.",
    )
    rejected = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=evidence_headers,
        json={"envelope": cross_tenant},
    )
    assert rejected.status_code == 404
    assert rejected.json()["error"]["code"] == "EXTERNAL_EVIDENCE_CROSS_TENANT"

    secret = _evidence_envelope(
        project_id=str(s49_context["project_id"]),
        statement="Authorization: Bearer raw-token-value",
    )
    leaked = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=evidence_headers,
        json={"envelope": secret},
    )
    assert leaked.status_code == 422
    assert "raw-token-value" not in leaked.text

    conflict_statement = "The API description and observed behavior disagree on the status code."
    conflict = _evidence_envelope(
        project_id=str(s49_context["project_id"]),
        statement=conflict_statement,
        semantic_role="conflict",
    )
    conflict_id = "untrusted-conflict-marker"
    conflict["findings"][0]["id"] = conflict_id
    _refresh_finding_fingerprint(conflict["findings"][0])
    conflicted = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=evidence_headers,
        json={"envelope": conflict},
    )
    assert conflicted.status_code == 201
    assert conflicted.json()["status"] == "conflicted"
    assert conflict_statement not in conflicted.text
    assert conflict_id not in conflicted.text

    closed = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/close", headers=evidence_headers
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    after_close = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=evidence_headers,
        json={"envelope": envelope},
    )
    assert after_close.status_code == 409
    assert after_close.json()["error"]["code"] == "TEST_CONTEXT_CLOSED"


@pytest.mark.asyncio
async def test_context_revision_capacity_errors_are_bounded(
    s49_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = s49_context["client"]
    headers = _headers(s49_context["evidence_token"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": str(s49_context["project_id"]),
            "name": "Capacity context",
            "objective": "Verify bounded revision growth",
            "required_evidence": ["contract"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]

    monkeypatch.setattr(test_context_service, "MAX_CONTEXT_EVIDENCE_ITEMS", 1)
    first = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={
            "envelope": _evidence_envelope(
                project_id=str(s49_context["project_id"]),
                statement="The first bounded finding.",
            )
        },
    )
    assert first.status_code == 201, first.text
    evidence_overflow = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={
            "envelope": _evidence_envelope(
                project_id=str(s49_context["project_id"]),
                statement="The second bounded finding.",
            )
        },
    )
    _assert_capacity_error(evidence_overflow)

    monkeypatch.setattr(test_context_service, "MAX_CONTEXT_EVIDENCE_ITEMS", 2000)
    monkeypatch.setattr(test_context_service, "MAX_CONTEXT_CONFLICTS", 0)
    conflict_overflow = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={
            "envelope": _evidence_envelope(
                project_id=str(s49_context["project_id"]),
                statement="A bounded conflict.",
                semantic_role="conflict",
            )
        },
    )
    _assert_capacity_error(conflict_overflow)

    monkeypatch.setattr(test_context_service, "MAX_CONTEXT_CONFLICTS", 100)
    monkeypatch.setattr(test_context_service, "MAX_CONTEXT_REVISION_REFERENCES", 1)
    reference_envelope = _evidence_envelope(
        project_id=str(s49_context["project_id"]),
        statement="A finding from another contract revision.",
    )
    reference_envelope["source"] = {
        "ref": "contract://refunds",
        "revision": "contract-v2",
    }
    reference_envelope["findings"][0]["source_ref"] = "contract://refunds"
    reference_envelope["findings"][0]["source_revision"] = "contract-v2"
    _refresh_finding_fingerprint(reference_envelope["findings"][0])
    reference_overflow = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": reference_envelope},
    )
    _assert_capacity_error(reference_overflow)


@pytest.mark.asyncio
async def test_flow_proposal_adapter_is_draft_only_dry_run_and_idempotent(
    s49_context: dict[str, Any],
) -> None:
    client = s49_context["client"]
    context = await _ready_context(s49_context)
    payload = {
        "project_id": str(s49_context["project_id"]),
        "context_id": context["id"],
        "context_revision_id": context["revision"]["id"],
        "spec": _flow_spec("S49 integration draft"),
    }
    missing_key = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers=_headers(s49_context["flow_token"]),
        json=payload,
    )
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    legacy = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={**_headers(s49_context["write_token"]), "Idempotency-Key": "s49-legacy"},
        json=payload,
    )
    assert legacy.status_code == 403

    preview = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={**_headers(s49_context["flow_token"]), "Idempotency-Key": "s49-preview"},
        json=payload,
    )
    assert preview.status_code == 202, preview.text
    assert preview.json()["dry_run"] is True
    assert preview.json()["change_set_id"] is None
    async with s49_context["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(AIChangeSet)) == 0
        assert await session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0

    persisted_payload = {**payload, "dry_run": False}
    missing_project_key = "s49-missing-project"
    missing_project = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={
            **_headers(s49_context["flow_token"]),
            "Idempotency-Key": missing_project_key,
        },
        json={**persisted_payload, "project_id": str(uuid4())},
    )
    assert missing_project.status_code == 404
    assert missing_project.json()["error"]["code"] == "TEST_CONTEXT_NOT_FOUND"
    async with s49_context["sessions"]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.idempotency_key == missing_project_key)
            )
            == 0
        )

    proposal_headers = {
        **_headers(s49_context["flow_token"]),
        "Idempotency-Key": "s49-proposal-v1",
    }
    proposed = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers=proposal_headers,
        json=persisted_payload,
    )
    assert proposed.status_code == 202, proposed.text
    body = proposed.json()
    assert body["status"] == "draft"
    assert body["context_fingerprint"] == context["revision"]["fingerprint"]
    repeated = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers=proposal_headers,
        json=persisted_payload,
    )
    assert repeated.status_code == 202
    assert repeated.json()["change_set_id"] == body["change_set_id"]
    conflict = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers=proposal_headers,
        json={**persisted_payload, "spec": _flow_spec("Different proposal")},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    async with s49_context["sessions"]() as session:
        change_set = await session.get(AIChangeSet, UUID(body["change_set_id"]))
        assert change_set is not None
        item = await session.scalar(
            select(AIChangeItem).where(AIChangeItem.change_set_id == change_set.id)
        )
        assert change_set.status == "draft"
        assert change_set.actor_type == "service_account"
        assert change_set.source_ref.startswith("mcp://")
        assert change_set.source_snapshot["context_revision_id"] == context["revision"]["id"]
        assert (
            change_set.source_snapshot["context_fingerprint"] == context["revision"]["fingerprint"]
        )
        assert item is not None and item.review_status == "pending"
        assert await session.scalar(select(func.count()).select_from(AIChangeSet)) == 1

    async with s49_context["sessions"]() as session:
        model = await session.get(ContextModel, UUID(context["id"]))
        assert model is not None
        model.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    expired = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={
            **_headers(s49_context["flow_token"]),
            "Idempotency-Key": "s49-expired",
        },
        json={**payload, "dry_run": False},
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "TEST_CONTEXT_EXPIRED"


async def _ready_context(context: dict[str, Any]) -> dict[str, Any]:
    response = await context["client"].post(
        "/api/v1/mcp/evidence/contexts",
        headers=_headers(context["evidence_token"]),
        json={
            "project_id": str(context["project_id"]),
            "name": "Proposal context",
            "objective": "Create a reviewed multi-operation flow draft",
            "required_evidence": ["contract"],
            "contract_revisions": [
                {"source_ref": "contract://payments", "revision": "contract-v1"}
            ],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready"
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _flow_spec(name: str) -> dict[str, Any]:
    return {
        "schema_version": "flowtest-flow-spec-v1",
        "name": name,
        "nodes": [
            {"id": "start", "kind": "start", "name": "Start"},
            {"id": "end", "kind": "end", "name": "End"},
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
    }


def _evidence_envelope(
    *, project_id: str, statement: str, semantic_role: str = "normative"
) -> dict[str, Any]:
    subject_ref = f"flowtest://projects/{project_id}/operations/create-payment"
    finding = {
        "id": "contract-binding",
        "kind": "binding",
        "semantic_role": semantic_role,
        "source_ref": "contract://payments",
        "source_revision": "contract-v1",
        "subject_ref": subject_ref,
        "source_path": "$.responses.201.id",
        "source_content": "interface_description",
        "content_role": "untrusted_data",
        "statement": statement,
        "confidence": 0.98,
        "deterministic": True,
    }
    _refresh_finding_fingerprint(finding)
    return {
        "schema_version": "flowtest-external-evidence-v1",
        "provider": {"type": "contract", "name": "contract-reader", "version": "1.0.0"},
        "source": {"ref": "contract://payments", "revision": "contract-v1"},
        "subject_ref": subject_ref,
        "findings": [finding],
        "redactions": [{"path": "$.examples", "method": "removed", "reason": "PII"}],
        "warnings": [],
        "confidence": 0.98,
        "deterministic": True,
    }


def _refresh_finding_fingerprint(finding: dict[str, Any]) -> None:
    payload = {key: value for key, value in finding.items() if key != "semantic_fingerprint"}
    finding["semantic_fingerprint"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _assert_capacity_error(response: Any) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TEST_CONTEXT_CAPACITY_EXCEEDED"
