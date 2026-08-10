import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import password_service
from app.domain.contracts import (
    ContractSchemaError,
    breaking_changes,
    contract_operations,
    load_contract_document,
)
from app.main import app
from app.models import Base
from app.models.access import User

ADMIN_EMAIL = "contract-admin@example.com"
ADMIN_PASSWORD = "contract-password-123!"


@pytest.fixture
async def contract_client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Contract administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
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
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


def test_contract_domain_detects_breaking_request_and_response_changes() -> None:
    baseline = contract_operations(load_contract_document(_baseline_document()))
    current = contract_operations(load_contract_document(_breaking_document()))
    changes = breaking_changes(baseline, current)
    assert {item.code for item in changes} == {
        "REQUEST_REQUIRED_ADDED",
        "RESPONSE_FIELD_REMOVED",
        "RESPONSE_TYPE_CHANGED",
    }
    assert all(item.severity == "breaking" for item in changes)


def test_contract_domain_rejects_external_refs_and_schema_bombs() -> None:
    external = json.loads(_baseline_document())
    external["paths"]["/users"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] = {"$ref": "https://attacker.example/schema.json"}
    with pytest.raises(ContractSchemaError, match="外部"):
        load_contract_document(json.dumps(external).encode())

    nested: object = "leaf"
    for _ in range(70):
        nested = {"child": nested}
    document = json.loads(_baseline_document())
    document["components"] = nested
    with pytest.raises(ContractSchemaError, match="深度"):
        load_contract_document(json.dumps(document).encode())


@pytest.mark.asyncio
async def test_contract_run_generates_reviewable_cases_and_breaking_diff(
    contract_client: AsyncClient,
) -> None:
    headers = await _login_headers(contract_client)
    project_id = await _create_project(contract_client, headers)
    first = await _upload_contract(contract_client, headers, project_id, _baseline_document())
    assert first.status_code == 201, first.text
    baseline = first.json()
    assert baseline["generated_case_count"] == 3
    assert baseline["coverage"]["operation_coverage_percent"] == 100.0
    assert baseline["breaking_changes"] == []

    second = await _upload_contract(
        contract_client,
        headers,
        project_id,
        _breaking_document(),
        baseline_run_id=baseline["id"],
    )
    assert second.status_code == 201, second.text
    changed = second.json()
    assert changed["baseline_run_id"] == baseline["id"]
    assert changed["diff_summary"] == {
        "added": 0,
        "changed": 1,
        "deleted": 0,
        "unchanged": 0,
    }
    assert {item["code"] for item in changed["breaking_changes"]} == {
        "REQUEST_REQUIRED_ADDED",
        "RESPONSE_FIELD_REMOVED",
        "RESPONSE_TYPE_CHANGED",
    }

    cases = await contract_client.get(
        f"/api/v1/projects/{project_id}/contract-runs/{changed['id']}/generated-cases",
        headers=headers,
    )
    assert cases.status_code == 200
    generated = cases.json()
    assert generated["total"] == 3
    assert {item["generation_kind"] for item in generated["items"]} == {
        "boundary",
        "property",
        "negative",
    }
    assert {item["review_status"] for item in generated["items"]} == {"pending"}
    assert all(item["definition"]["confirmed"] is False for item in generated["items"])

    selected = generated["items"][0]
    accepted = await contract_client.post(
        (
            f"/api/v1/projects/{project_id}/contract-runs/{changed['id']}"
            f"/generated-cases/{selected['id']}/accept"
        ),
        headers=headers,
        json={"name": "审核后的契约用例", "note": "边界数据已确认"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["review_status"] == "accepted"
    assert accepted.json()["definition"]["confirmed"] is True
    assert accepted.json()["name"] == "审核后的契约用例"

    repeated = await contract_client.post(
        (
            f"/api/v1/projects/{project_id}/contract-runs/{changed['id']}"
            f"/generated-cases/{selected['id']}/accept"
        ),
        headers=headers,
        json={},
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "GENERATED_CASE_ALREADY_REVIEWED"

    unconfirmed = generated["items"][2]
    malformed = await contract_client.post(
        (
            f"/api/v1/projects/{project_id}/contract-runs/{changed['id']}"
            f"/generated-cases/{unconfirmed['id']}/accept"
        ),
        headers=headers,
        json={"definition": {"request": {}}, "unexpected": True},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid_definition = await contract_client.post(
        (
            f"/api/v1/projects/{project_id}/contract-runs/{changed['id']}"
            f"/generated-cases/{unconfirmed['id']}/accept"
        ),
        headers=headers,
        json={"definition": {"request": {}}},
    )
    assert invalid_definition.status_code == 422
    assert invalid_definition.json()["error"]["code"] == "GENERATED_CASE_DEFINITION_INVALID"

    rejected_case = generated["items"][1]
    rejected = await contract_client.post(
        (
            f"/api/v1/projects/{project_id}/contract-runs/{changed['id']}"
            f"/generated-cases/{rejected_case['id']}/reject"
        ),
        headers=headers,
        json={"note": "当前项目不需要该属性场景"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "rejected"


@pytest.mark.asyncio
async def test_contract_run_enforces_project_isolation_and_safe_schema(
    contract_client: AsyncClient,
) -> None:
    headers = await _login_headers(contract_client)
    project_id = await _create_project(contract_client, headers)
    other_project_id = await _create_project(contract_client, headers, name="Other project")
    created = await _upload_contract(contract_client, headers, project_id, _baseline_document())
    assert created.status_code == 201
    hidden = await contract_client.get(
        f"/api/v1/projects/{other_project_id}/contract-runs/{created.json()['id']}",
        headers=headers,
    )
    assert hidden.status_code == 404

    invalid = await _upload_contract(contract_client, headers, project_id, b"openapi: 3.0.0")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "CONTRACT_SCHEMA_INVALID"


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(
    client: AsyncClient, headers: dict[str, str], *, name: str = "Contract project"
) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "description": "Contract verification"},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def _upload_contract(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    content: bytes,
    *,
    baseline_run_id: str | None = None,
):
    data = {"source_name": "team-api.json"}
    if baseline_run_id:
        data["baseline_run_id"] = baseline_run_id
    return await client.post(
        f"/api/v1/projects/{project_id}/contract-runs",
        headers=headers,
        files={"document": ("team-api.json", content, "application/json")},
        data=data,
    )


def _baseline_document() -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Team API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "integer", "minimum": 1, "maximum": 100},
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "count": {"type": "integer"},
                                                "cursor": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }
    ).encode()


def _breaking_document() -> bytes:
    document = json.loads(_baseline_document())
    operation = document["paths"]["/users"]["get"]
    operation["parameters"][0]["required"] = True
    properties = operation["responses"]["200"]["content"]["application/json"]["schema"][
        "properties"
    ]
    properties["count"]["type"] = "string"
    properties.pop("cursor")
    document["info"]["version"] = "2.0.0"
    return json.dumps(document).encode()
