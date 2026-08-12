import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import (
    get_pact_broker_source,
    get_provider_interaction_verifier,
)
from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.contract_hub import (
    PactContractError,
    PactDocument,
    PactTransportError,
    ProviderInteractionResult,
    ProviderVerificationEvidence,
    load_pact_document,
    normalize_contract_origin,
    response_mismatch_codes,
    service_key_for_name,
)
from app.domain.network import OutboundNetworkPolicy
from app.http.contract_hub import HttpPactBrokerSource, HttpProviderInteractionVerifier
from app.main import app
from app.models import Base
from app.models.access import User

ADMIN_EMAIL = "contract-hub-admin@example.com"
ADMIN_PASSWORD = "contract-hub-password-123!"


@dataclass(slots=True)
class FakeVerifier:
    async def verify(
        self,
        *,
        target_base_url: str,
        pact: PactDocument,
        network_policy: OutboundNetworkPolicy,
    ) -> ProviderVerificationEvidence:
        del network_policy
        failed = "fail" in target_base_url
        results = tuple(
            ProviderInteractionResult(
                interaction_index=index,
                description=interaction.description,
                status="failed" if failed else "passed",
                mismatch_codes=("BODY_MISMATCH",) if failed else (),
            )
            for index, interaction in enumerate(pact.interactions)
        )
        return ProviderVerificationEvidence(
            status="failed" if failed else "passed",
            interaction_results=results,
        )


@dataclass(slots=True)
class FakeBroker:
    content: bytes
    error: PactTransportError | None = None

    async def fetch_pact(
        self,
        *,
        consumer: str,
        provider: str,
        consumer_version: str,
        network_policy: OutboundNetworkPolicy,
    ) -> bytes:
        del consumer, provider, consumer_version, network_policy
        if self.error is not None:
            raise self.error
        return self.content


@dataclass(slots=True)
class ContractHubContext:
    client: AsyncClient
    broker: FakeBroker


@pytest.fixture
async def contract_hub_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[ContractHubContext]:
    monkeypatch.setattr(settings, "feature_contract_hub_enabled", True)
    monkeypatch.setattr(settings, "pact_broker_base_url", "https://pact.example.test")
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
                display_name="Contract hub administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    broker = FakeBroker(_pact_document())

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_provider_interaction_verifier] = FakeVerifier
    app.dependency_overrides[get_pact_broker_source] = lambda: broker
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield ContractHubContext(client=client, broker=broker)
    app.dependency_overrides.clear()
    await engine.dispose()


def test_pact_document_exact_contract_and_input_guards() -> None:
    pact = load_pact_document(_pact_document())
    assert pact.consumer == "Web Client"
    assert pact.provider == "Orders API"
    assert pact.specification_version == "3.0.0"
    assert pact.sha256 == load_pact_document(_pact_document()).sha256
    assert service_key_for_name("订单 API") == service_key_for_name("订单 API")
    assert normalize_contract_origin("http://orders-api:8000/") == "http://orders-api:8000"

    expected = pact.interactions[0].response
    assert (
        response_mismatch_codes(
            expected,
            actual_status=200,
            actual_headers={"content-type": "application/json"},
            actual_body={"status": "ok"},
        )
        == ()
    )
    assert response_mismatch_codes(
        expected,
        actual_status=500,
        actual_headers={},
        actual_body={"status": "failed"},
    ) == ("STATUS_MISMATCH", "HEADER_MISMATCH", "BODY_MISMATCH")

    invalid_documents = [
        b"{",
        b"[]",
        json.dumps({"consumer": {"name": "Web"}, "provider": {"name": "API"}}).encode(),
        _mutated_pact({"interactions": ["invalid"]}),
        _mutated_pact({"interactions": _pact_payload()["interactions"] * 501}),
        _mutated_pact({"matchingRules": {}}),
        _mutated_pact({"messages": [{"description": "message"}]}),
        _mutated_pact({}, consumer={"name": ""}),
        _mutated_pact({}, consumer={"name": "x" * 161}),
        _mutated_interaction({"description": ""}),
        _mutated_interaction({"request": None}),
        _mutated_pact({}, request={"path": None}),
        _mutated_pact({}, request={"path": "/health?api_token=hidden"}),
        _mutated_pact({}, response={"status": "200"}),
        _mutated_pact({}, request={"headers": []}),
        _mutated_pact({}, request={"headers": {"Bad Header": "value"}}),
        _mutated_pact({}, request={"headers": {"X-Test": 1}}),
        _mutated_pact({}, request={"headers": {"Authorization": "Bearer hidden"}}),
        _mutated_pact({}, request={"query": "api_token=hidden"}),
        _mutated_pact({}, request={"query": []}),
        _mutated_pact({}, request={"query": {"api_key": "hidden"}}),
        _mutated_pact({}, request={"query": {"tag": ["valid", 1]}}),
        _mutated_pact({}, request={"body": {"password": "hidden"}}),
        _mutated_pact({}, request={"method": "TRACE"}),
        _mutated_pact({}, response={"headers": {"Set-Cookie": "secret=true"}}),
        _mutated_interaction({"providerStates": [""]}),
        _mutated_interaction({"providerStates": ["state"] * 11}),
    ]
    for content in invalid_documents:
        with pytest.raises(PactContractError):
            load_pact_document(content)

    too_many_query_fields = "&".join(f"field{index}=x" for index in range(101))
    with pytest.raises(PactContractError, match="100"):
        load_pact_document(_mutated_pact({}, request={"query": too_many_query_fields}))
    with pytest.raises(PactContractError, match="5 MB"):
        load_pact_document(b" " * (5 * 1024 * 1024 + 1))

    deeply_nested: object = "leaf"
    for _ in range(66):
        deeply_nested = {"node": deeply_nested}
    with pytest.raises(PactContractError, match="复杂度"):
        load_pact_document(_mutated_pact({}, request={"body": deeply_nested}))

    query_pact = load_pact_document(
        _mutated_interaction(
            {
                "providerState": "订单存在",
                "request": {
                    "method": "POST",
                    "path": "/orders",
                    "query": {"page": "1", "tag": ["a", "b"]},
                    "body": [1, {"status": "ready"}],
                },
                "response": {"status": 200, "body": ["ok"]},
            }
        )
    )
    assert query_pact.interactions[0].provider_states == ("订单存在",)
    assert query_pact.interactions[0].request.query == {"page": "1", "tag": ["a", "b"]}
    assert (
        response_mismatch_codes(
            query_pact.interactions[0].response,
            actual_status=200,
            actual_headers={},
            actual_body=["ok"],
        )
        == ()
    )

    repeated_query = load_pact_document(
        _mutated_pact(
            {"metadata": {"pact-specification": {"version": "4.0.0"}}},
            request={"query": "tag=a&tag=b&tag=c"},
        )
    )
    assert repeated_query.specification_version == "4.0.0"
    assert repeated_query.interactions[0].request.query == {"tag": ["a", "b", "c"]}
    assert load_pact_document(_mutated_pact({"metadata": None})).specification_version == "3.0.0"

    for invalid_origin in ("ftp://example.test", "https://user:secret@example.test/path"):
        with pytest.raises(PactTransportError, match="Origin"):
            normalize_contract_origin(invalid_origin)


@pytest.mark.asyncio
async def test_contract_hub_api_unifies_pact_openapi_and_deployment_decisions(
    contract_hub_context: ContractHubContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = contract_hub_context.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers)
    root = f"/api/v1/projects/{project_id}/contract-hub"

    empty = await client.get(f"{root}/summary", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["service_count"] == 0
    assert empty.json()["broker_available"] is True

    provider = await client.post(
        f"{root}/services",
        headers=headers,
        json={
            "service_key": "orders-api",
            "display_name": "Orders API",
            "description": "订单 Provider",
        },
    )
    assert provider.status_code == 201, provider.text
    provider_id = provider.json()["id"]
    duplicate = await client.post(
        f"{root}/services",
        headers=headers,
        json={"service_key": "orders-api", "display_name": "Other Orders"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SERVICE_CATALOG_ENTRY_EXISTS"

    uploaded = await _upload_pact(client, headers, root)
    assert uploaded.status_code == 201, uploaded.text
    pact = uploaded.json()
    assert pact["provider_service_id"] == provider_id
    assert pact["interaction_count"] == 1
    repeated = await _upload_pact(client, headers, root)
    assert repeated.status_code == 201
    assert repeated.json()["id"] == pact["id"]

    pacts = await client.get(f"{root}/pacts", headers=headers)
    services = await client.get(f"{root}/services?page_size=1", headers=headers)
    graph = await client.get(f"{root}/service-graph", headers=headers)
    assert pacts.json()["total"] == 1
    assert services.json()["total"] == 2
    assert len(services.json()["items"]) == 1
    assert len(graph.json()["nodes"]) == 2
    assert graph.json()["edges"][0]["latest_status"] == "pending"

    unknown = await _deployment_check(client, headers, root, provider_id, "1.0.0")
    assert unknown.status_code == 201
    assert unknown.json()["decision"] == "unknown"

    failed = await client.post(
        f"{root}/pacts/{pact['id']}/verify",
        headers=headers,
        json={
            "provider_version": "1.0.0",
            "target_base_url": "https://fail.example.test",
        },
    )
    assert failed.status_code == 201, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["results"][0]["mismatch_codes"] == ["BODY_MISMATCH"]
    unsafe = await _deployment_check(client, headers, root, provider_id, "1.0.0")
    assert unsafe.json()["decision"] == "unsafe"

    passed = await client.post(
        f"{root}/pacts/{pact['id']}/verify",
        headers=headers,
        json={
            "provider_version": "2.0.0",
            "target_base_url": "https://provider.example.test",
        },
    )
    assert passed.status_code == 201
    assert passed.json()["status"] == "passed"
    invalid_target = await client.post(
        f"{root}/pacts/{pact['id']}/verify",
        headers=headers,
        json={
            "provider_version": "2.0.0",
            "target_base_url": "https://user:secret@provider.example.test/path",
        },
    )
    assert invalid_target.status_code == 422
    assert invalid_target.json()["error"]["code"] == "PROVIDER_TARGET_INVALID"
    openapi = await client.post(
        f"/api/v1/projects/{project_id}/contract-runs",
        headers=headers,
        files={"document": ("orders-openapi.json", _openapi_document(), "application/json")},
        data={"provider_service_id": provider_id, "provider_version": "2.0.0"},
    )
    assert openapi.status_code == 201, openapi.text
    assert openapi.json()["provider_service_id"] == provider_id
    invalid_openapi_binding = await client.post(
        f"/api/v1/projects/{project_id}/contract-runs",
        headers=headers,
        files={"document": ("orders-openapi.json", _openapi_document(), "application/json")},
        data={"provider_service_id": provider_id, "provider_version": " "},
    )
    assert invalid_openapi_binding.status_code == 422
    assert invalid_openapi_binding.json()["error"]["code"] == "CONTRACT_PROVIDER_BINDING_INVALID"
    safe = await _deployment_check(client, headers, root, provider_id, "2.0.0")
    assert safe.json()["decision"] == "safe"

    summary = await client.get(f"{root}/summary", headers=headers)
    matrix = await client.get(f"{root}/compatibility/{provider_id}", headers=headers)
    checks = await client.get(f"{root}/deployment-checks?page_size=2", headers=headers)
    assert summary.json() == {
        "service_count": 2,
        "openapi_contract_count": 1,
        "pact_contract_count": 1,
        "pending_verification_count": 0,
        "failed_verification_count": 1,
        "breaking_change_count": 0,
        "broker_available": True,
    }
    assert matrix.json()["provider_versions"] == ["2.0.0", "1.0.0"]
    assert [cell["status"] for cell in matrix.json()["rows"][0]["cells"]] == [
        "passed",
        "failed",
    ]
    assert checks.json()["total"] == 3
    assert len(checks.json()["items"]) == 2

    imported = await client.post(
        f"{root}/pacts/import-broker",
        headers=headers,
        json={
            "consumer": "Web Client",
            "provider": "Orders API",
            "consumer_version": "broker-1",
        },
    )
    assert imported.status_code == 201
    assert imported.json()["source_type"] == "broker"

    contract_hub_context.broker.content = _mutated_pact(
        {}, consumer={"name": "Unexpected Consumer"}
    )
    mismatch = await client.post(
        f"{root}/pacts/import-broker",
        headers=headers,
        json={
            "consumer": "Web Client",
            "provider": "Orders API",
            "consumer_version": "broker-2",
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "PACT_BROKER_COORDINATE_MISMATCH"
    contract_hub_context.broker.error = PactTransportError("PACT_BROKER_FAILED", "失败")
    failed_broker = await client.post(
        f"{root}/pacts/import-broker",
        headers=headers,
        json={
            "consumer": "Web Client",
            "provider": "Orders API",
            "consumer_version": "broker-3",
        },
    )
    assert failed_broker.status_code == 502
    assert failed_broker.json()["error"]["code"] == "PACT_BROKER_FAILED"

    monkeypatch.setattr(settings, "pact_broker_base_url", "")
    disabled_broker = await client.post(
        f"{root}/pacts/import-broker",
        headers=headers,
        json={
            "consumer": "Web Client",
            "provider": "Orders API",
            "consumer_version": "broker-4",
        },
    )
    assert disabled_broker.status_code == 409
    assert disabled_broker.json()["error"]["code"] == "PACT_BROKER_DISABLED"

    monkeypatch.setattr(settings, "feature_contract_hub_enabled", False)
    disabled = await client.get(f"{root}/summary", headers=headers)
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "CONTRACT_HUB_DISABLED"


@pytest.mark.asyncio
async def test_http_provider_verifier_uses_fixed_origin_and_exact_matching() -> None:
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.read(4096)
        requests.append(request)
        body = b"{}" if request.startswith(b"POST /_pact/provider-states") else b'{"status":"ok"}'
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])

    class AllowGuard:
        async def enforce(self, url: str, policy: OutboundNetworkPolicy) -> tuple[str, ...]:
            del url, policy
            return ("127.0.0.1",)

    verifier = HttpProviderInteractionVerifier(
        request_timeout_seconds=2,
        guard=AllowGuard(),  # type: ignore[arg-type]
    )
    pact_value = json.loads(_pact_document())
    pact_value["interactions"][0]["providerStates"] = [{"name": "订单存在"}]
    pact = load_pact_document(json.dumps(pact_value).encode())
    try:
        evidence = await verifier.verify(
            target_base_url=f"http://127.0.0.1:{port}",
            pact=pact,
            network_policy=OutboundNetworkPolicy(),
        )
    finally:
        server.close()
        await server.wait_closed()

    assert evidence.status == "passed"
    assert len(requests) == 2
    assert requests[0].startswith(b"POST /_pact/provider-states")
    assert requests[1].startswith(b"GET /health")
    with pytest.raises(PactTransportError, match="Origin"):
        await verifier.verify(
            target_base_url="https://user:secret@example.test/path?token=hidden",
            pact=pact,
            network_policy=OutboundNetworkPolicy(),
        )

    class BlockGuard:
        async def enforce(self, url: str, policy: OutboundNetworkPolicy) -> tuple[str, ...]:
            del url, policy
            raise AppError(code="OUTBOUND_REQUEST_BLOCKED", message="blocked", status_code=422)

    blocked_verifier = HttpProviderInteractionVerifier(
        request_timeout_seconds=2,
        guard=BlockGuard(),  # type: ignore[arg-type]
    )
    blocked = await blocked_verifier.verify(
        target_base_url="http://provider.example.test",
        pact=pact,
        network_policy=OutboundNetworkPolicy(),
    )
    assert blocked.status == "failed"
    assert blocked.interaction_results[0].mismatch_codes == ("OUTBOUND_REQUEST_BLOCKED",)

    broker = HttpPactBrokerSource(
        base_url="https://pact.example.test",
        token="write-only-token",
        request_timeout_seconds=2,
        guard=BlockGuard(),  # type: ignore[arg-type]
    )
    with pytest.raises(PactTransportError, match="出站策略") as blocked_broker:
        await broker.fetch_pact(
            consumer="Web Client",
            provider="Orders API",
            consumer_version="1.0.0",
            network_policy=OutboundNetworkPolicy(),
        )
    assert blocked_broker.value.code == "PACT_BROKER_TARGET_BLOCKED"


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Contract hub project", "description": "S27"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _upload_pact(client: AsyncClient, headers: dict[str, str], root: str):
    return await client.post(
        f"{root}/pacts",
        headers=headers,
        files={"document": ("web-orders.json", _pact_document(), "application/json")},
        data={"consumer_version": "web-1.0.0"},
    )


async def _deployment_check(
    client: AsyncClient,
    headers: dict[str, str],
    root: str,
    provider_id: str,
    provider_version: str,
):
    return await client.post(
        f"{root}/deployment-checks",
        headers=headers,
        json={
            "provider_service_id": provider_id,
            "provider_version": provider_version,
        },
    )


def _pact_payload() -> dict[str, object]:
    return {
        "consumer": {"name": "Web Client"},
        "provider": {"name": "Orders API"},
        "interactions": [
            {
                "description": "读取健康状态",
                "request": {"method": "GET", "path": "/health"},
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": {"status": "ok"},
                },
            }
        ],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }


def _pact_document() -> bytes:
    return json.dumps(_pact_payload(), ensure_ascii=False).encode()


def _mutated_pact(
    root: dict[str, object],
    *,
    consumer: dict[str, object] | None = None,
    request: dict[str, object] | None = None,
    response: dict[str, object] | None = None,
) -> bytes:
    value = _pact_payload()
    value.update(root)
    if consumer is not None:
        value["consumer"] = consumer
    interaction = value["interactions"][0]  # type: ignore[index]
    if request:
        interaction["request"].update(request)  # type: ignore[index, union-attr]
    if response:
        interaction["response"].update(response)  # type: ignore[index, union-attr]
    return json.dumps(value, ensure_ascii=False).encode()


def _mutated_interaction(updates: dict[str, object]) -> bytes:
    value = _pact_payload()
    interactions = value["interactions"]
    assert isinstance(interactions, list)
    interaction = interactions[0]
    assert isinstance(interaction, dict)
    interaction.update(updates)
    return json.dumps(value, ensure_ascii=False).encode()


def _openapi_document() -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Orders API", "version": "2.0.0"},
            "paths": {
                "/health": {
                    "get": {
                        "operationId": "getHealth",
                        "responses": {
                            "200": {
                                "description": "Healthy",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["status"],
                                            "properties": {"status": {"type": "string"}},
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
