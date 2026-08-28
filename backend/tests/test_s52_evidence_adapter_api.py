from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.evidence_adapters import (
    DatabaseEvidenceSubmission,
    EntityMappingBudgetExceeded,
    JavaEvidenceSubmission,
    adapt_database_evidence,
    adapt_java_evidence,
)
from app.domain.test_contexts import (
    DatabaseExternalEvidenceStructuredData,
    finding_semantic_fingerprint,
)
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.organizations import Organization
from app.services.service_accounts import ServiceAccountService


@pytest.fixture
async def s52_context() -> AsyncIterator[dict[str, Any]]:
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
            email="s52-admin@example.test",
            display_name="S52 administrator",
            password_hash=password_service.hash("unused-password"),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        organization = Organization(
            name="S52 organization",
            slug="s52-organization",
            description="",
            enabled=True,
            created_by_id=None,
        )
        session.add_all([actor, organization])
        await session.flush()
        organization.created_by_id = actor.id
        project = Project(
            organization_id=organization.id,
            name="S52 project",
            created_by_id=actor.id,
        )
        session.add(project)
        await session.flush()
        account = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=organization.id,
            name="S52 evidence adapter",
            account_key="s52-evidence-adapter",
            scopes=["mcp:evidence:write"],
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
            "project_id": project.id,
            "token": account.token,
        }
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_java_and_database_evidence_enter_context_and_expose_mapping(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "订单实体映射上下文",
            "objective": "关联创建订单接口与数据库实体",
            "required_evidence": ["repository", "data_profile"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]

    java = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/java-evidence",
        headers=headers,
        json={"evidence": _java_evidence(project_id)},
    )
    assert java.status_code == 201, java.text
    assert java.json()["context"]["status"] == "incomplete"
    assert java.json()["context"]["revision"]["snapshot"]["repository_revisions"] == [
        {"source_ref": "repository://orders-service", "revision": "a1b2c3d4"}
    ]

    database = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/database-evidence",
        headers=headers,
        json={"evidence": _database_evidence(project_id)},
    )
    assert database.status_code == 201, database.text
    body = database.json()
    assert body["context"]["status"] == "ready"
    assert {candidate["kind"] for candidate in body["entity_mapping"]["candidates"]} >= {
        "operation_entity",
        "request_field_column",
        "response_field_column",
        "operation_state",
    }
    assert body["entity_mapping"]["conflicts"] == []
    assert all(
        candidate["selection_status"] == "proposed" and candidate["evidence_refs"]
        for candidate in body["entity_mapping"]["candidates"]
    )

    inspected = await client.get(
        f"/api/v1/mcp/evidence/contexts/{context_id}/entity-mapping",
        headers=headers,
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json() == body["entity_mapping"]


@pytest.mark.asyncio
async def test_persisted_envelope_reliability_bounds_java_mapping_candidates(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "低可靠性 Java 证据上下文",
            "objective": "验证持久化后的 Envelope 可靠性约束映射候选",
            "required_evidence": ["repository", "data_profile"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]

    java_payload = _java_evidence(project_id)
    java_payload["confidence"] = 0.2
    java_payload["deterministic"] = False
    java = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/java-evidence",
        headers=headers,
        json={"evidence": java_payload},
    )
    assert java.status_code == 201, java.text

    database = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/database-evidence",
        headers=headers,
        json={"evidence": _database_evidence(project_id)},
    )
    assert database.status_code == 201, database.text

    inspected = await client.get(
        f"/api/v1/mcp/evidence/contexts/{context_id}/entity-mapping",
        headers=headers,
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json() == database.json()["entity_mapping"]

    java_backed_kinds = {
        "operation_entity",
        "request_field_column",
        "response_field_column",
    }
    candidates = [
        candidate
        for candidate in inspected.json()["candidates"]
        if candidate["kind"] in java_backed_kinds
    ]
    assert candidates
    assert all(candidate["confidence"] <= 0.2 for candidate in candidates)
    assert all(candidate["deterministic"] is False for candidate in candidates)


@pytest.mark.asyncio
async def test_ambiguous_entity_candidates_conflict_context_without_silent_selection(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "歧义实体映射上下文",
            "objective": "验证多个实体候选必须人工确认",
            "required_evidence": ["repository"],
        },
    )
    context_id = begun.json()["id"]
    java_payload = _java_evidence(project_id)
    _add_archived_order_entity(java_payload)
    java = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/java-evidence",
        headers=headers,
        json={"evidence": java_payload},
    )
    assert java.status_code == 201, java.text

    ambiguous_payload = _database_evidence(project_id)
    second_table = {
        **ambiguous_payload["tables"][0],
        "name": "archived_orders",
        "columns": [dict(column) for column in ambiguous_payload["tables"][0]["columns"]],
    }
    ambiguous_payload["tables"].append(second_table)
    database = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/database-evidence",
        headers=headers,
        json={"evidence": ambiguous_payload},
    )

    assert database.status_code == 201, database.text
    body = database.json()
    assert body["context"]["status"] == "conflicted"
    assert body["context"]["revision"]["snapshot"]["conflict_snapshot"]["conflicts"]
    assert body["entity_mapping"]["conflicts"]
    conflicted_ids = {
        candidate_id
        for conflict in body["entity_mapping"]["conflicts"]
        for candidate_id in conflict["candidate_ids"]
    }
    assert all(
        candidate["selection_status"] == "proposed"
        for candidate in body["entity_mapping"]["candidates"]
        if candidate["id"] in conflicted_ids
    )


@pytest.mark.asyncio
async def test_generic_evidence_ingestion_synthesizes_adapter_mapping_conflicts(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "通用入口实体映射冲突上下文",
            "objective": "验证通用 Evidence 入口不会绕过映射冲突派生",
            "required_evidence": ["repository", "data_profile"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]

    java_payload = _java_evidence(project_id)
    _add_archived_order_entity(java_payload)
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload))
    java = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": java_envelope.model_dump(mode="json")},
    )
    assert java.status_code == 201, java.text

    database_payload = _database_evidence(project_id)
    second_table = {
        **database_payload["tables"][0],
        "name": "archived_orders",
        "columns": [dict(column) for column in database_payload["tables"][0]["columns"]],
    }
    database_payload["tables"].append(second_table)
    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(database_payload)
    )
    database = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": database_envelope.model_dump(mode="json")},
    )
    assert database.status_code == 201, database.text
    assert database.json()["status"] == "conflicted"

    inspected = await client.get(
        f"/api/v1/mcp/evidence/contexts/{context_id}/entity-mapping",
        headers=headers,
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["conflicts"]


@pytest.mark.asyncio
async def test_generic_table_only_database_evidence_drives_entity_mapping(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "通用表级证据上下文",
            "objective": "验证无列 Finding 时仍可推导可追溯实体映射",
            "required_evidence": ["repository", "data_profile"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]

    java_envelope = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_evidence(project_id))
    )
    java = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": java_envelope.model_dump(mode="json")},
    )
    assert java.status_code == 201, java.text

    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_evidence(project_id))
    )
    table_finding = next(
        finding
        for finding in database_envelope.findings
        if isinstance(finding.structured_data, DatabaseExternalEvidenceStructuredData)
        and finding.structured_data.claim_kind == "table"
    )
    table_only = database_envelope.model_copy(update={"findings": [table_finding]})
    database = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": table_only.model_dump(mode="json")},
    )
    assert database.status_code == 201, database.text
    assert database.json()["status"] == "ready"

    inspected = await client.get(
        f"/api/v1/mcp/evidence/contexts/{context_id}/entity-mapping",
        headers=headers,
    )
    assert inspected.status_code == 200, inspected.text
    operation_entity = next(
        candidate
        for candidate in inspected.json()["candidates"]
        if candidate["kind"] == "operation_entity"
    )
    assert operation_entity["target_ref"] == "entity://public/orders"
    assert operation_entity["evidence_refs"]


@pytest.mark.asyncio
async def test_generic_evidence_rejects_adapter_provider_mismatch(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "Provider 绑定上下文",
            "objective": "验证强类型 Adapter 不能伪造 Evidence Completeness",
            "required_evidence": ["repository", "data_profile"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]
    envelope = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_evidence(project_id))
    ).model_dump(mode="json")
    envelope["provider"]["type"] = "database"

    rejected = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": envelope},
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rejected.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_generic_evidence_rejects_sensitive_adapter_scalar(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "通用标量安全上下文",
            "objective": "验证通用入口拒绝未脱敏枚举标量",
            "required_evidence": ["repository"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]
    java_payload = _java_evidence(project_id)
    java_payload["claims"].append(
        {
            "id": "state-order",
            "kind": "enum_state",
            "source_path": "src/OrderStatus.java:3",
            "confidence": 0.98,
            "deterministic": True,
            "operation_ref": "operation://POST/api/orders",
            "enum_ref": "java://OrderStatus",
            "field_name": "status",
            "values": ["created", "cancelled"],
        }
    )
    envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)).model_dump(
        mode="json"
    )
    state = next(
        finding
        for finding in envelope["findings"]
        if finding["structured_data"]["claim_kind"] == "enum_state"
    )
    sensitive_value = "4111111111111111"
    state["structured_data"]["claim"]["values"] = [sensitive_value]

    rejected = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": envelope},
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rejected.json()["error"]["trace_id"]
    assert sensitive_value not in rejected.text

    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_evidence(project_id))
    ).model_dump(mode="json")
    column = next(
        finding
        for finding in database_envelope["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
    )
    column["structured_data"]["claim"]["masked_example"] = f"*** {sensitive_value}"

    rejected_masked_example = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": database_envelope},
    )

    assert rejected_masked_example.status_code == 422, rejected_masked_example.text
    assert rejected_masked_example.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rejected_masked_example.json()["error"]["trace_id"]
    assert sensitive_value not in rejected_masked_example.text


@pytest.mark.asyncio
async def test_generic_evidence_rejects_conflicts_when_marker_capacity_is_exhausted(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "映射冲突标记容量上下文",
            "objective": "验证冲突标记无空间时拒绝写入而非静默遗漏",
            "required_evidence": ["repository", "data_profile"],
        },
    )
    assert begun.status_code == 201, begun.text
    context_id = begun.json()["id"]

    java_payload = _java_evidence(project_id)
    _add_archived_order_entity(java_payload)
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload))
    java = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": java_envelope.model_dump(mode="json")},
    )
    assert java.status_code == 201, java.text

    database_payload = _database_evidence(project_id)
    second_table = {
        **database_payload["tables"][0],
        "name": "archived_orders",
        "columns": [dict(column) for column in database_payload["tables"][0]["columns"]],
    }
    database_payload["tables"].append(second_table)
    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(database_payload)
    )
    findings = list(database_envelope.findings)
    base_finding = findings[0]
    while len(findings) < 100:
        index = len(findings)
        provisional = base_finding.model_copy(
            update={
                "id": f"capacity-padding-{index}",
                "source_path": f"$.capacity_padding.{index}",
                "semantic_fingerprint": "0" * 64,
            }
        )
        findings.append(
            provisional.model_copy(
                update={"semantic_fingerprint": finding_semantic_fingerprint(provisional)}
            )
        )
    full_envelope = database_envelope.model_copy(update={"findings": findings})

    rejected = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/evidence",
        headers=headers,
        json={"envelope": full_envelope.model_dump(mode="json")},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "ENTITY_MAPPING_BUDGET_EXCEEDED"
    assert rejected.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_database_adapter_rejects_sensitive_or_write_input_with_trace_id(
    s52_context: dict[str, Any],
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "安全证据上下文",
            "objective": "验证数据库证据边界",
            "required_evidence": ["data_profile"],
        },
    )
    context_id = begun.json()["id"]
    payload = _database_evidence(project_id)
    payload["tables"][0]["columns"][0]["check_expression"] = "DROP TABLE orders"

    rejected = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/database-evidence",
        headers=headers,
        json={"evidence": payload},
    )

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rejected.json()["error"]["trace_id"]
    assert "DROP TABLE orders" not in rejected.text

    sensitive_value = "4111111111111111"
    masked_payload = _database_evidence(project_id)
    masked_payload["tables"][0]["columns"][0]["masked_example"] = f"*** {sensitive_value}"
    rejected_masked_example = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/database-evidence",
        headers=headers,
        json={"evidence": masked_payload},
    )

    assert rejected_masked_example.status_code == 422
    assert rejected_masked_example.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rejected_masked_example.json()["error"]["trace_id"]
    assert sensitive_value not in rejected_masked_example.text


@pytest.mark.asyncio
async def test_mapping_budget_error_uses_standard_trace_envelope(
    s52_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = s52_context["client"]
    headers = _headers(s52_context["token"])
    project_id = str(s52_context["project_id"])
    begun = await client.post(
        "/api/v1/mcp/evidence/contexts",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "映射预算上下文",
            "objective": "验证映射预算错误边界",
            "required_evidence": ["data_profile"],
        },
    )
    context_id = begun.json()["id"]

    def exceed_budget(*_args: object, **_kwargs: object) -> None:
        raise EntityMappingBudgetExceeded("synthetic mapping budget")

    monkeypatch.setattr(
        "app.services.test_contexts.with_mapping_conflict_findings",
        exceed_budget,
    )
    rejected = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/database-evidence",
        headers=headers,
        json={"evidence": _database_evidence(project_id)},
    )

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "ENTITY_MAPPING_BUDGET_EXCEEDED"
    assert rejected.json()["error"]["trace_id"]
    assert "synthetic mapping budget" not in rejected.text


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-MCP-Client-Version": "s52-test"}


def _java_evidence(project_id: str) -> dict[str, Any]:
    operation_ref = "operation://POST/api/orders"
    common = {"confidence": 0.98, "deterministic": True}
    return {
        "schema_version": "flowtest-java-evidence-v1",
        "provider": {"name": "external-code-mcp", "version": "2.1.0"},
        "source": {"ref": "repository://orders-service", "revision": "a1b2c3d4"},
        "subject_ref": f"flowtest://projects/{project_id}/operations/orders",
        "claims": [
            {
                **common,
                "id": "route-create",
                "kind": "controller_route",
                "source_path": "src/OrderController.java:20",
                "operation_ref": operation_ref,
                "controller_ref": "java://OrderController",
                "handler": "create",
                "method": "POST",
                "path": "/api/orders",
            },
            {
                **common,
                "id": "request-product",
                "kind": "dto_field",
                "source_path": "src/CreateOrderRequest.java:4",
                "operation_ref": operation_ref,
                "direction": "request",
                "dto_type": "CreateOrderRequest",
                "field_name": "productId",
                "field_type": "String",
            },
            {
                **common,
                "id": "response-id",
                "kind": "dto_field",
                "source_path": "src/OrderDto.java:3",
                "operation_ref": operation_ref,
                "direction": "response",
                "dto_type": "OrderDto",
                "field_name": "id",
                "field_type": "String",
            },
            {
                **common,
                "id": "entity-order",
                "kind": "entity",
                "source_path": "src/Order.java:4",
                "entity_ref": "entity://Order",
                "class_name": "Order",
                "table_ref": "table://public/orders",
                "operation_refs": [operation_ref],
            },
        ],
        "confidence": 0.98,
        "deterministic": True,
    }


def _add_archived_order_entity(payload: dict[str, Any]) -> None:
    payload["claims"].append(
        {
            "id": "entity-archived-order",
            "kind": "entity",
            "source_path": "src/ArchivedOrder.java:4",
            "confidence": 0.98,
            "deterministic": True,
            "entity_ref": "entity://ArchivedOrder",
            "class_name": "ArchivedOrder",
            "table_ref": "table://public.archived_orders",
            "operation_refs": ["operation://POST/api/orders"],
        }
    )


def _database_evidence(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "flowtest-database-evidence-v1",
        "provider": {"name": "external-database-mcp", "version": "3.0.0"},
        "source": {"ref": "database-profile://orders", "revision": "schema-v1"},
        "subject_ref": f"flowtest://projects/{project_id}/operations/orders",
        "tables": [
            {
                "schema_name": "public",
                "name": "orders",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "uuid",
                        "nullable": False,
                        "primary_key": True,
                        "unique": True,
                        "masked_example": "***0001",
                    },
                    {
                        "name": "product_id",
                        "data_type": "uuid",
                        "nullable": False,
                        "masked_example": "***1001",
                    },
                    {
                        "name": "status",
                        "data_type": "varchar",
                        "nullable": False,
                        "enum_values": ["created", "cancelled"],
                        "check_expression": "status IN ('created', 'cancelled')",
                        "masked_example": "***ated",
                    },
                ],
            }
        ],
        "confidence": 0.99,
        "deterministic": True,
    }
