from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.evidence_adapters import EntityMappingBudgetExceeded
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
    java = await client.post(
        f"/api/v1/mcp/evidence/contexts/{context_id}/java-evidence",
        headers=headers,
        json={"evidence": _java_evidence(project_id)},
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
