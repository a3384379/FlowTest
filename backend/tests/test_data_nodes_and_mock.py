import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.data_nodes import (
    CredentialKind,
    DataNodeValidationError,
    validate_read_only_sql,
    validate_redis_read,
)
from app.domain.mock_services import (
    MockRequestContext,
    MockTemplateError,
    compile_mock_path,
    match_mock_conditions,
    render_mock_template,
)
from app.domain.network import OutboundNetworkPolicy
from app.engine.contracts import WorkflowDefinition
from app.engine.scheduler import ExecutionContext, NodeExecutionError, WorkflowScheduler
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.data_sources import Credential
from app.services import data_nodes as data_node_module
from app.services.credentials import CredentialMaterial, CredentialService
from app.services.data_nodes import (
    DataNodeRunner,
    InfrastructureDataNodeRunner,
    PreparedDataNode,
)
from app.services.workflow_runtime import WorkflowNodeExecutor

ADMIN_EMAIL = "data-admin@example.com"
ADMIN_PASSWORD = "data-password-123!"


@dataclass(frozen=True, slots=True)
class DataTestContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]


@pytest.fixture
async def data_context() -> AsyncIterator[DataTestContext]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Data administrator",
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
        yield DataTestContext(client, sessions)
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id, name FROM users WHERE id = :id",
        "WITH active AS (SELECT id FROM users) SELECT * FROM active",
        "SELECT 1;",
    ],
)
def test_read_only_sql_accepts_select_queries(query: str) -> None:
    assert validate_read_only_sql(query, CredentialKind.POSTGRESQL).startswith(("SELECT", "WITH"))


@pytest.mark.parametrize(
    "query",
    [
        "",
        "UPDATE users SET admin = true",
        "DELETE FROM users",
        "CREATE TABLE unsafe(id int)",
        "SELECT 1; SELECT 2",
        "BEGIN",
        "SELECT (",
        "WITH deleted AS (DELETE FROM users RETURNING id) SELECT * FROM deleted",
    ],
)
def test_read_only_sql_rejects_writes_and_multiple_statements(query: str) -> None:
    with pytest.raises(DataNodeValidationError):
        validate_read_only_sql(query, CredentialKind.MYSQL)


def test_read_only_sql_rejects_oversized_queries() -> None:
    with pytest.raises(DataNodeValidationError, match="100 KB"):
        validate_read_only_sql("x" * 100_001, CredentialKind.POSTGRESQL)


def test_redis_read_whitelist_and_argument_bounds() -> None:
    assert validate_redis_read("get", ["session:1"]).value == "GET"
    assert validate_redis_read("ZRANGE", ["score", "0", "999"]).value == "ZRANGE"
    for command, arguments in (
        ("SET", ["key", "value"]),
        ("SCAN", ["0"]),
        ("GET", []),
        ("GET", [""]),
        ("ZRANGE", ["score", "0", "1000"]),
        ("ZRANGE", ["score", "start", "1"]),
        ("HGET", ["hash"]),
    ):
        with pytest.raises(DataNodeValidationError):
            validate_redis_read(command, arguments)


def test_rule_based_mock_path_conditions_and_template() -> None:
    matcher = compile_mock_path("/users/{user_id}")
    match = matcher.fullmatch("/users/42")
    assert match is not None
    context = MockRequestContext(
        path=match.groupdict(),
        query={"mode": "full", "tenant": "commerce"},
        headers={"X-Contract": "on"},
        body={"profile": {"name": "Alice"}},
    )
    assert match_mock_conditions({"mode": "full"}, {"x-contract": "on"}, context)
    assert render_mock_template(
        {
            "id": "{{path.user_id}}",
            "tenant": "{{query.tenant}}",
            "name": "{{body.profile.name}}",
            "summary": "user={{path.user_id}}",
        },
        context,
    ) == {
        "id": "42",
        "tenant": "commerce",
        "name": "Alice",
        "summary": "user=42",
    }
    for invalid in ("users/{id}", "/users/{id}/{id}", "/users/{bad-name}", "/users//1"):
        with pytest.raises(MockTemplateError):
            compile_mock_path(invalid)
    with pytest.raises(MockTemplateError):
        render_mock_template("{{body.missing}}", context)


@pytest.mark.asyncio
async def test_credential_api_is_write_only_encrypted_and_audited(
    data_context: DataTestContext,
) -> None:
    client = data_context.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers)
    secret = "postgres-super-secret"
    created = await client.post(
        "/api/v1/credentials",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "订单只读库",
            "kind": "postgresql",
            "host": "db.example.com",
            "database_name": "orders",
            "username": "flowtest_reader",
            "secret": secret,
            "tls_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    metadata = created.json()
    assert metadata["port"] == 5432
    assert "secret" not in metadata and "ciphertext" not in metadata

    listed = await client.get(
        "/api/v1/credentials",
        params={"project_id": project_id},
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json() == [metadata]
    assert secret not in listed.text
    duplicate = await client.post(
        "/api/v1/credentials",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "订单只读库",
            "kind": "postgresql",
            "host": "duplicate.example.com",
            "database_name": "orders",
            "secret": "duplicate-secret",
        },
    )
    assert duplicate.status_code == 409

    async with data_context.sessions() as session:
        stored = await session.get(Credential, UUID(metadata["id"]))
        assert stored is not None
        assert secret.encode() not in stored.ciphertext
        material = await CredentialService(session).load_material(
            project_id=stored.project_id,
            credential_id=stored.id,
        )
        assert material.secret == secret
        with pytest.raises(AppError, match="不存在"):
            await CredentialService(session).load_material(
                project_id=uuid4(),
                credential_id=stored.id,
            )

    updated = await client.patch(
        f"/api/v1/credentials/{metadata['id']}",
        headers=headers,
        json={
            "name": "订单副本只读库",
            "secret": "rotated-secret",
            "host": "DB2.EXAMPLE.COM.",
            "port": 5544,
            "database_name": "orders_replica",
            "username": "replica_reader",
            "tls_enabled": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["host"] == "db2.example.com"
    assert updated.json()["port"] == 5544
    assert updated.json()["database_name"] == "orders_replica"
    assert updated.json()["tls_enabled"] is False
    assert "rotated-secret" not in updated.text

    invalid_database = await client.patch(
        f"/api/v1/credentials/{metadata['id']}",
        headers=headers,
        json={"database_name": ""},
    )
    assert invalid_database.status_code == 422

    deleted = await client.delete(f"/api/v1/credentials/{metadata['id']}", headers=headers)
    assert deleted.status_code == 204
    missing = await client.patch(
        f"/api/v1/credentials/{metadata['id']}",
        headers=headers,
        json={"name": "missing"},
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_mock_service_dispatch_scenarios_templates_and_redacted_logs(
    data_context: DataTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = data_context.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers)
    service = await client.post(
        f"/api/v1/projects/{project_id}/mock-services",
        headers=headers,
        json={"name": "用户契约 Mock", "slug": "users-contract", "description": "S17"},
    )
    assert service.status_code == 201, service.text
    service_id = service.json()["id"]
    services = await client.get(
        f"/api/v1/projects/{project_id}/mock-services",
        headers=headers,
    )
    assert services.status_code == 200
    assert services.json()[0]["id"] == service_id
    duplicate_service = await client.post(
        f"/api/v1/projects/{project_id}/mock-services",
        headers=headers,
        json={"name": "用户契约 Mock", "slug": "users-contract-duplicate"},
    )
    assert duplicate_service.status_code == 409
    missing_service = await client.get(
        f"/api/v1/projects/{project_id}/mock-services/{uuid4()}/routes",
        headers=headers,
    )
    assert missing_service.status_code == 404
    route_payload = {
        "name": "查询用户成功场景",
        "method": "POST",
        "path_pattern": "/users/{user_id}",
        "query_conditions": {"mode": "full"},
        "header_conditions": {"X-Contract": "on"},
        "response_status": 201,
        "response_headers": {"X-Mock": "FlowTest"},
        "response_body": {
            "id": "{{path.user_id}}",
            "tenant": "{{query.tenant}}",
            "name": "{{body.profile.name}}",
        },
        "delay_ms": 1,
        "scenario": "happy",
        "priority": 10,
        "is_enabled": True,
    }
    route = await client.post(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
        headers=headers,
        json=route_payload,
    )
    assert route.status_code == 201, route.text
    route_id = route.json()["id"]
    duplicate_route = await client.post(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
        headers=headers,
        json=route_payload,
    )
    assert duplicate_route.status_code == 409
    invalid_path = await client.post(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
        headers=headers,
        json={**route_payload, "name": "无效路径", "path_pattern": "users/{id}"},
    )
    assert invalid_path.status_code == 422
    missing_route = await client.delete(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes/{uuid4()}",
        headers=headers,
    )
    assert missing_route.status_code == 404

    dispatched = await client.post(
        "/api/v1/mock/users-contract/users/42",
        params={"mode": "full", "tenant": "commerce", "_scenario": "happy", "token": "q"},
        headers={
            "X-Contract": "on",
            "Authorization": "Bearer should-not-be-stored",
        },
        json={"profile": {"name": "Alice"}, "password": "body-secret"},
    )
    assert dispatched.status_code == 201, dispatched.text
    assert dispatched.headers["x-mock"] == "FlowTest"
    assert dispatched.json() == {"id": "42", "tenant": "commerce", "name": "Alice"}
    unmatched_path = await client.post(
        "/api/v1/mock/users-contract/other/42",
        params={"_scenario": "happy"},
    )
    assert unmatched_path.status_code == 404

    unmatched = await client.get("/api/v1/mock/users-contract/unknown")
    assert unmatched.status_code == 404
    assert unmatched.json() == {"error": "没有匹配的 Mock 路由"}

    routes = await client.get(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
        headers=headers,
    )
    assert routes.status_code == 200
    assert routes.json()[0]["id"] == route_id
    logs = await client.get(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/request-logs",
        headers=headers,
    )
    assert logs.status_code == 200
    assert logs.json()["total"] == 3
    matched_log = next(item for item in logs.json()["items"] if item["matched"])
    assert matched_log["headers"]["authorization"] == "***"
    assert matched_log["query_parameters"]["token"] == "***"
    assert matched_log["body"]["password"] == "***"
    assert "should-not-be-stored" not in logs.text
    assert "body-secret" not in logs.text

    for index, forbidden_header in enumerate(
        ("Connection", "Content-Type", "Set-Cookie", "Location"),
        start=1,
    ):
        invalid_header = {
            **route_payload,
            "name": f"危险 Header {index}",
            "response_headers": {forbidden_header: "unsafe"},
        }
        rejected = await client.post(
            f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
            headers=headers,
            json=invalid_header,
        )
        assert rejected.status_code == 422

    broken_template = {
        **route_payload,
        "name": "缺失模板值",
        "path_pattern": "/broken",
        "query_conditions": {},
        "header_conditions": {},
        "scenario": None,
        "response_body": {"value": "{{body.missing}}"},
    }
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
            headers=headers,
            json=broken_template,
        )
    ).status_code == 201
    assert (await client.post("/api/v1/mock/users-contract/broken", json={})).status_code == 500

    oversized_template = {
        **broken_template,
        "name": "超限响应",
        "path_pattern": "/oversized",
        "response_body": {"value": "x" * 100},
    }
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
            headers=headers,
            json=oversized_template,
        )
    ).status_code == 201
    monkeypatch.setattr(settings, "inline_body_limit_bytes", 16)
    assert (await client.post("/api/v1/mock/users-contract/oversized")).status_code == 500

    route_payload["response_status"] = 202
    updated_route = await client.put(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes/{route_id}",
        headers=headers,
        json=route_payload,
    )
    assert updated_route.status_code == 200
    assert updated_route.json()["response_status"] == 202
    assert (
        await client.delete(
            f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes/{route_id}",
            headers=headers,
        )
    ).status_code == 204
    disabled = await client.patch(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}",
        headers=headers,
        json={
            "name": "用户契约 Mock 已更新",
            "is_enabled": False,
            "description": "disabled",
        },
    )
    assert disabled.status_code == 200
    assert (await client.get("/api/v1/mock/users-contract/users/42")).status_code == 404


@pytest.mark.asyncio
async def test_data_node_runner_rejects_kind_mismatch_and_unsafe_operations() -> None:
    postgres = _credential(CredentialKind.POSTGRESQL)
    redis = _credential(CredentialKind.REDIS)
    runner = InfrastructureDataNodeRunner(OutboundNetworkPolicy())
    with pytest.raises(NodeExecutionError, match="SQL 节点"):
        await runner.execute_sql(redis, "SELECT 1", {}, 1)
    with pytest.raises(NodeExecutionError, match="Redis 节点"):
        await runner.execute_redis(postgres, "GET", ["key"], 1)
    with pytest.raises(NodeExecutionError, match="仅允许 SELECT"):
        await runner.execute_sql(postgres, "DELETE FROM users", {}, 1)
    with pytest.raises(NodeExecutionError, match="白名单"):
        await runner.execute_redis(redis, "SET", ["key", "value"], 1)


@pytest.mark.asyncio
async def test_data_node_runner_uses_bounded_read_only_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = RecordingOutboundGuard()
    sql_engine = FakeSqlEngine(rows=[{"id": 42, "amount": Decimal("12.50")}])
    monkeypatch.setattr(data_node_module, "_sql_engine", lambda _credential: sql_engine)
    runner = InfrastructureDataNodeRunner(
        OutboundNetworkPolicy(),
        outbound_guard=guard,  # type: ignore[arg-type]
    )
    postgres = replace(_credential(CredentialKind.POSTGRESQL), tls_enabled=False)

    sql_result = await runner.execute_sql(
        postgres,
        "SELECT id, amount FROM orders WHERE id = :id",
        {"id": 42},
        2,
    )

    assert sql_result == {"row_count": 1, "rows": [{"id": 42, "amount": "12.50"}]}
    assert sql_engine.connection.executed == ["SET TRANSACTION READ ONLY"]
    assert sql_engine.connection.streamed == [
        ("SELECT id, amount FROM orders WHERE id = :id", {"id": 42})
    ]
    assert sql_engine.disposed

    redis_client = FakeRedisClient(result={"order": b"cached"})
    monkeypatch.setattr(data_node_module, "Redis", lambda **_kwargs: redis_client)
    redis = _credential(CredentialKind.REDIS)
    redis_result = await runner.execute_redis(redis, "get", ["order:42"], 2)

    assert redis_result == {"command": "GET", "result": {"order": "cached"}}
    assert redis_client.commands == [("GET", ("order:42",))]
    assert redis_client.closed
    assert guard.targets == [(postgres.host, postgres.port), (redis.host, redis.port)]


@pytest.mark.asyncio
async def test_data_node_runner_rejects_dns_rebinding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql_engine = FakeSqlEngine(peer="127.0.0.1")
    monkeypatch.setattr(data_node_module, "_sql_engine", lambda _credential: sql_engine)
    runner = InfrastructureDataNodeRunner(
        OutboundNetworkPolicy(),
        outbound_guard=RecordingOutboundGuard(),  # type: ignore[arg-type]
    )

    with pytest.raises(NodeExecutionError) as captured:
        await runner.execute_sql(
            _credential(CredentialKind.POSTGRESQL),
            "SELECT 1",
            {},
            1,
        )

    assert captured.value.code == "DNS_REBINDING_BLOCKED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "timeout_seconds", "expected_code"),
    [
        ("driver", 1, "SQL_EXECUTION_FAILED"),
        ("timeout", 0, "DATA_NODE_TIMEOUT"),
    ],
)
async def test_data_node_runner_normalizes_sql_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    timeout_seconds: int,
    expected_code: str,
) -> None:
    engine = (
        FakeSqlEngine(connect_error=SQLAlchemyError("driver detail"))
        if failure == "driver"
        else FakeSqlEngine(connect_delay=0.01)
    )
    monkeypatch.setattr(data_node_module, "_sql_engine", lambda _credential: engine)
    runner = InfrastructureDataNodeRunner(
        OutboundNetworkPolicy(),
        outbound_guard=RecordingOutboundGuard(),  # type: ignore[arg-type]
    )

    with pytest.raises(NodeExecutionError) as captured:
        await runner.execute_sql(
            _credential(CredentialKind.POSTGRESQL),
            "SELECT 1",
            {},
            timeout_seconds,
        )

    assert captured.value.code == expected_code
    assert "driver detail" not in captured.value.message
    assert engine.disposed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "timeout_seconds", "expected_code"),
    [
        ("server", 1, "REDIS_EXECUTION_FAILED"),
        ("timeout", 0, "DATA_NODE_TIMEOUT"),
    ],
)
async def test_data_node_runner_normalizes_redis_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    timeout_seconds: int,
    expected_code: str,
) -> None:
    client = (
        FakeRedisClient(error=RedisError("server detail"))
        if failure == "server"
        else FakeRedisClient(delay=0.01)
    )
    monkeypatch.setattr(data_node_module, "Redis", lambda **_kwargs: client)
    runner = InfrastructureDataNodeRunner(
        OutboundNetworkPolicy(),
        outbound_guard=RecordingOutboundGuard(),  # type: ignore[arg-type]
    )

    with pytest.raises(NodeExecutionError) as captured:
        await runner.execute_redis(
            _credential(CredentialKind.REDIS),
            "GET",
            ["key"],
            timeout_seconds,
        )

    assert captured.value.code == expected_code
    assert "server detail" not in captured.value.message
    assert client.closed


@pytest.mark.asyncio
async def test_data_node_runner_rejects_blocked_network_targets() -> None:
    runner = InfrastructureDataNodeRunner(
        OutboundNetworkPolicy(),
        outbound_guard=BlockedOutboundGuard(),  # type: ignore[arg-type]
    )
    with pytest.raises(NodeExecutionError) as captured:
        await runner.execute_sql(
            _credential(CredentialKind.POSTGRESQL),
            "SELECT 1",
            {},
            1,
        )
    assert captured.value.code == "OUTBOUND_HOST_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_sql_adapter_enforces_row_limit_and_builds_pinned_drivers() -> None:
    connection = FakeSqlConnection(rows=[{"id": index} for index in range(1001)])
    with pytest.raises(NodeExecutionError, match="1000"):
        await data_node_module._read_rows(connection, "SELECT id FROM items", {})  # type: ignore[arg-type]

    postgres = data_node_module._sql_engine(
        replace(_credential(CredentialKind.POSTGRESQL), tls_enabled=False)
    )
    mysql = data_node_module._sql_engine(_credential(CredentialKind.MYSQL))
    assert postgres.url.drivername == "postgresql+asyncpg"
    assert mysql.url.drivername == "mysql+asyncmy"
    await postgres.dispose()
    await mysql.dispose()


class RecordingOutboundGuard:
    def __init__(self) -> None:
        self.targets: list[tuple[str, int]] = []

    async def enforce_target(
        self,
        host: str,
        port: int,
        _policy: OutboundNetworkPolicy,
    ) -> tuple[str, ...]:
        self.targets.append((host, port))
        return ("203.0.113.10",)


class BlockedOutboundGuard:
    async def enforce_target(
        self,
        _host: str,
        _port: int,
        _policy: OutboundNetworkPolicy,
    ) -> tuple[str, ...]:
        raise AppError(code="OUTBOUND_HOST_NOT_ALLOWED", message="目标地址不在允许范围内")


class FakeSqlEngine:
    def __init__(
        self,
        *,
        rows: list[dict[str, object]] | None = None,
        connect_error: SQLAlchemyError | None = None,
        connect_delay: float = 0,
        peer: str = "203.0.113.10",
    ) -> None:
        self.connection = FakeSqlConnection(rows=rows or [], peer=peer)
        self.connect_error = connect_error
        self.connect_delay = connect_delay
        self.disposed = False

    def connect(self) -> "FakeConnectionContext":
        return FakeConnectionContext(self)

    async def dispose(self) -> None:
        self.disposed = True


class FakeConnectionContext:
    def __init__(self, engine: FakeSqlEngine) -> None:
        self.engine = engine

    async def __aenter__(self) -> "FakeSqlConnection":
        if self.engine.connect_delay:
            await asyncio.sleep(self.engine.connect_delay)
        if self.engine.connect_error:
            raise self.engine.connect_error
        return self.engine.connection

    async def __aexit__(self, *_errors: object) -> None:
        return None


class FakeSqlConnection:
    def __init__(
        self,
        *,
        rows: list[dict[str, object]],
        peer: str = "203.0.113.10",
    ) -> None:
        self.rows = rows
        self.executed: list[str] = []
        self.streamed: list[tuple[str, dict[str, JsonValue]]] = []
        self.raw_connection = FakeRawConnection(peer)

    async def get_raw_connection(self) -> "FakeRawConnection":
        return self.raw_connection

    def begin(self) -> "FakeTransactionContext":
        return FakeTransactionContext()

    async def execute(self, statement: object) -> None:
        self.executed.append(str(statement))

    async def stream(
        self,
        statement: object,
        parameters: dict[str, JsonValue],
    ) -> "FakeStreamResult":
        self.streamed.append((str(statement), parameters))
        return FakeStreamResult(self.rows)


class FakeTransactionContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_errors: object) -> None:
        return None


class FakeStreamResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> "FakeStreamResult":
        return self

    async def fetchmany(self, size: int) -> list[dict[str, object]]:
        return self.rows[:size]


class FakeRedisClient:
    def __init__(
        self,
        *,
        result: object = None,
        error: RedisError | None = None,
        delay: float = 0,
    ) -> None:
        self.result = result
        self.error = error
        self.delay = delay
        self.commands: list[tuple[str, tuple[str, ...]]] = []
        self.closed = False
        self.connection = FakeRedisConnection("203.0.113.10")

    async def initialize(self) -> "FakeRedisClient":
        return self

    async def execute_command(self, command: str, *arguments: str) -> object:
        self.commands.append((command, arguments))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result

    async def aclose(self) -> None:
        self.closed = True


class FakeRawConnection:
    def __init__(self, peer: str) -> None:
        self.driver_connection = FakeDriverConnection(peer)


class FakeDriverConnection:
    def __init__(self, peer: str) -> None:
        self._transport = FakeTransport(peer)


class FakeRedisConnection:
    def __init__(self, peer: str) -> None:
        self._writer = FakeWriter(peer)


class FakeWriter:
    def __init__(self, peer: str) -> None:
        self.transport = FakeTransport(peer)


class FakeTransport:
    def __init__(self, peer: str) -> None:
        self.peer = peer

    def get_extra_info(self, name: str) -> tuple[str, int] | None:
        return (self.peer, 5432) if name == "peername" else None


def test_data_node_results_are_json_safe_and_size_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert data_node_module._json_value(None) is None
    assert data_node_module._json_value(Decimal("12.50")) == "12.50"
    assert data_node_module._json_value(date(2026, 8, 10)) == "2026-08-10"
    assert cast(
        str,
        data_node_module._json_value(datetime(2026, 8, 10, tzinfo=UTC)),
    ).endswith("+00:00")
    assert data_node_module._json_value(b"hello") == "hello"
    assert data_node_module._json_value({1: ("a", Decimal("2"))}) == {"1": ["a", "2"]}
    assert cast(str, data_node_module._json_value(object())).startswith("<object object")
    output: dict[str, JsonValue] = {"rows": []}
    assert data_node_module._bounded_output(output) is output
    monkeypatch.setattr(settings, "inline_body_limit_bytes", 1)
    with pytest.raises(NodeExecutionError, match="2 MB"):
        data_node_module._bounded_output({"rows": ["large"]})


@pytest.mark.asyncio
async def test_workflow_sql_and_redis_nodes_use_fixed_credentials_and_runtime_variables() -> None:
    postgres = _credential(CredentialKind.POSTGRESQL)
    redis = _credential(CredentialKind.REDIS)
    data_runner = RecordingDataRunner()
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
                {
                    "id": "sql",
                    "type": "sql",
                    "name": "查询订单",
                    "position": {"x": 180, "y": 0},
                    "config": {
                        "credential_id": str(postgres.id),
                        "query": "SELECT id FROM orders WHERE id = :order_id",
                        "parameters": {"order_id": "{{order_id}}"},
                    },
                },
                {
                    "id": "redis",
                    "type": "redis",
                    "name": "查询缓存",
                    "position": {"x": 360, "y": 0},
                    "config": {
                        "credential_id": str(redis.id),
                        "command": "GET",
                        "arguments": ["{{redis_key}}"],
                    },
                },
                {"id": "end", "type": "end", "name": "结束", "position": {"x": 540, "y": 0}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "sql"},
                {"id": "e2", "source": "sql", "target": "redis"},
                {"id": "e3", "source": "redis", "target": "end"},
            ],
        }
    )
    async with httpx.AsyncClient() as client:
        executor = WorkflowNodeExecutor(
            client,
            {},
            definition,
            OutboundNetworkPolicy(),
            data_nodes={
                "sql": PreparedDataNode(postgres),
                "redis": PreparedDataNode(redis),
            },
            data_runner=data_runner,
        )
        result = await WorkflowScheduler(executor).run(
            definition,
            context=ExecutionContext(runtime_variables={"order_id": 42, "redis_key": "order:42"}),
        )
    assert result.status.value == "passed"
    assert data_runner.sql_parameters == {"order_id": 42}
    assert data_runner.redis_arguments == ["order:42"]
    outputs = cast(dict[str, JsonValue], result.context["node_outputs"])
    sql_output = cast(dict[str, JsonValue], outputs["sql"])
    assert sql_output["rows"] == [{"id": 42}]


class RecordingDataRunner(DataNodeRunner):
    def __init__(self) -> None:
        self.sql_parameters: Mapping[str, JsonValue] = {}
        self.redis_arguments: list[str] = []

    async def execute_sql(
        self,
        credential: CredentialMaterial,
        query: str,
        parameters: Mapping[str, JsonValue],
        timeout_seconds: int,
    ) -> JsonValue:
        assert credential.kind is CredentialKind.POSTGRESQL
        assert query.startswith("SELECT")
        assert timeout_seconds == 30
        self.sql_parameters = parameters
        return {"row_count": 1, "rows": [{"id": parameters["order_id"]}]}

    async def execute_redis(
        self,
        credential: CredentialMaterial,
        command: str,
        arguments: list[str],
        timeout_seconds: int,
    ) -> JsonValue:
        assert credential.kind is CredentialKind.REDIS
        assert command == "GET"
        assert timeout_seconds == 30
        self.redis_arguments = arguments
        return {"command": command, "result": "cached"}


def _credential(kind: CredentialKind) -> CredentialMaterial:
    return CredentialMaterial(
        id=uuid4(),
        project_id=uuid4(),
        name=f"{kind.value}-credential",
        kind=kind,
        host=f"{kind.value}.example.com",
        port={
            CredentialKind.POSTGRESQL: 5432,
            CredentialKind.MYSQL: 3306,
            CredentialKind.REDIS: 6379,
        }[kind],
        database_name="flowtest",
        username="reader",
        secret="encrypted-at-rest",
        tls_enabled=True,
    )


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": f"Data project {uuid4().hex[:8]}", "description": "S17"},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["id"])
