import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import ClassVar, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.event_protocols import (
    MAX_EVENT_MESSAGE_BYTES,
    EventSchemaFormat,
    EventSourceKind,
    KafkaOffset,
    WebSocketPayloadKind,
    event_schema_format,
    validate_bootstrap_servers,
    validate_event_schema,
)
from app.domain.network import OutboundNetworkPolicy
from app.domain.protocols import ProtocolSchemaError, ProtoSourceFile
from app.engine.contracts import WorkflowNode
from app.engine.event_codec import decode_event_value, encode_event_value
from app.engine.event_nodes import (
    KafkaConsumeCapabilityConfig,
    KafkaProduceCapabilityConfig,
    PreparedEventNode,
    WebSocketAwaitCapabilityConfig,
    WebSocketCloseCapabilityConfig,
    WebSocketConnectCapabilityConfig,
    WebSocketExchangeCapabilityConfig,
    WebSocketSendCapabilityConfig,
    parse_event_config,
    resolve_event_config,
)
from app.engine.scheduler import ExecutionContext, NodeExecutionError
from app.main import app
from app.models import Base
from app.models.access import Project, User
from app.models.protocols import EventSource, SchemaArtifact
from app.schemas.event_protocols import EventSchemaCreate, EventSourceCreate, RegistrySchemaImport
from app.services import event_runtime as event_runtime_module
from app.services.event_debug import _prepared_event_node, _registry_schema_payload
from app.services.event_runtime import (
    ConfluentKafkaGateway,
    EventProtocolRunner,
    KafkaRecord,
    _correlation_matches,
    _kafka_correlation_matches,
    _kafka_headers,
    _message_bytes,
    _message_headers,
    _produce_blocking,
    _record_from_message,
    _redacted_kafka_headers,
    _safe_websocket_headers,
    _websocket_inbound,
    _websocket_outbound,
)
from app.services.event_sources import _event_endpoints, _registry_url, _source_fingerprint

ADMIN_EMAIL = "event-admin@example.com"
ADMIN_PASSWORD = "event-admin-password-123!"

AVRO_SCHEMA = json.dumps(
    {
        "type": "record",
        "name": "OrderCreated",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "amount", "type": "int"},
        ],
    }
)
JSON_SCHEMA = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string"}},
        "additionalProperties": False,
    }
)
PROTO_SCHEMA = """
syntax = "proto3";
package flowtest.events.v1;
message OrderCreated { string id = 1; int32 amount = 2; }
"""


class AllowAllGuard:
    def __init__(self) -> None:
        self.targets: list[tuple[str, int]] = []

    async def enforce_target(
        self,
        hostname: str,
        port: int,
        policy: OutboundNetworkPolicy,
    ) -> tuple[str, ...]:
        del policy
        self.targets.append((hostname, port))
        return ("10.0.0.10",)


class RejectingGuard:
    async def enforce_target(
        self,
        hostname: str,
        port: int,
        policy: OutboundNetworkPolicy,
    ) -> tuple[str, ...]:
        del hostname, port, policy
        raise AppError(code="SSRF_BLOCKED", message="target denied", status_code=422)


@dataclass
class FakeKafkaGateway:
    produced: list[dict[str, object]] = field(default_factory=list)
    records: tuple[KafkaRecord, ...] = ()
    fail_produce: bool = False
    fail_consume: bool = False

    async def produce(self, **values: object) -> KafkaRecord:
        if self.fail_produce:
            raise TimeoutError("produce timed out")
        self.produced.append(values)
        return KafkaRecord(
            topic=cast(str, values["topic"]),
            partition=2,
            offset=9,
            timestamp_ms=1_700_000_000_000,
            key=cast(bytes | None, values["key"]),
            value=cast(bytes, values["value"]),
            headers=cast(tuple[tuple[str, bytes], ...], values["headers"]),
        )

    async def consume(self, **values: object) -> tuple[KafkaRecord, ...]:
        if self.fail_consume:
            raise TimeoutError("consume timed out")
        return self.records


@dataclass
class FakeWebSocket:
    inbound: list[str | bytes]
    subprotocol: str | None = "flowtest.v1"
    sent: list[str | bytes] = field(default_factory=list)
    closed: bool = False
    fail_send: bool = False
    fail_receive: bool = False

    async def send(self, message: str | bytes) -> None:
        if self.fail_send:
            raise OSError("session disconnected")
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        if self.fail_receive:
            raise OSError("session disconnected")
        if not self.inbound:
            await _never()
        return self.inbound.pop(0)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        del code, reason
        self.closed = True


class FakeKafkaMessage:
    def __init__(
        self,
        *,
        topic: str = "orders",
        value: str | bytes | None = b'{"id":"42"}',
        headers: dict[str, str | bytes | None] | None = None,
    ) -> None:
        self._topic = topic
        self._value = value
        self._headers = headers or {"correlation-id": "42"}

    def timestamp(self) -> tuple[int, int]:
        return (1, 1_700_000_000_000)

    def value(self) -> str | bytes | None:
        return self._value

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return 1

    def offset(self) -> int:
        return 2

    def key(self) -> str:
        return "key"

    def headers(self) -> dict[str, str | bytes | None]:
        return self._headers

    def error(self) -> None:
        return None


class FakeProducer:
    configuration: ClassVar[dict[str, object]]

    def __init__(self, configuration: dict[str, object]) -> None:
        type(self).configuration = configuration

    def produce(self, topic: str, **values: object) -> None:
        callback = cast(
            Callable[[object | None, object], None],
            values["on_delivery"],
        )
        callback(None, FakeKafkaMessage(topic=topic))

    def flush(self, timeout: int) -> int:
        del timeout
        return 0


class FakeConsumer:
    configuration: ClassVar[dict[str, object]]
    subscribed: ClassVar[list[str]] = []
    closed: ClassVar[bool] = False

    def __init__(self, configuration: dict[str, object]) -> None:
        type(self).configuration = configuration
        self._messages = [FakeKafkaMessage()]

    def subscribe(self, topics: list[str]) -> None:
        type(self).subscribed = topics

    def poll(self, timeout: float) -> FakeKafkaMessage | None:
        del timeout
        return self._messages.pop(0) if self._messages else None

    def close(self) -> None:
        type(self).closed = True


@pytest.fixture
async def event_client() -> AsyncIterator[tuple[AsyncClient, UUID]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        user = User(
            email=ADMIN_EMAIL,
            display_name="Event administrator",
            password_hash=password_service.hash(ADMIN_PASSWORD),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        session.add(user)
        await session.flush()
        project = Project(
            name="Event Protocol Project",
            description="",
            created_by_id=user.id,
        )
        session.add(project)
        await session.commit()
        project_id = project.id

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client, project_id
    app.dependency_overrides.clear()
    await engine.dispose()


def test_event_schema_validation_normalizes_all_supported_formats() -> None:
    avro = validate_event_schema(schema_format=EventSchemaFormat.AVRO, schema=AVRO_SCHEMA)
    json_schema = validate_event_schema(
        schema_format=EventSchemaFormat.JSON_SCHEMA,
        schema=JSON_SCHEMA,
        registry_id=42,
    )
    protobuf = validate_event_schema(
        schema_format=EventSchemaFormat.PROTOBUF,
        proto_files=(ProtoSourceFile(name="order.proto", content=PROTO_SCHEMA),),
        entrypoint="order.proto",
        registry_id=7,
    )

    assert event_schema_format(avro.summary) is EventSchemaFormat.AVRO
    assert json_schema.summary["registry_id"] == 42
    assert protobuf.summary["message_count"] == 1
    assert protobuf.summary["event_schema_format"] == "protobuf"

    with pytest.raises(ProtocolSchemaError, match="内容不能为空"):
        validate_event_schema(schema_format=EventSchemaFormat.AVRO)
    with pytest.raises(ProtocolSchemaError, match="不是有效 JSON"):
        validate_event_schema(schema_format=EventSchemaFormat.AVRO, schema="not-json")
    with pytest.raises(ProtocolSchemaError, match="JSON 对象"):
        validate_event_schema(schema_format=EventSchemaFormat.AVRO, schema="[]")
    with pytest.raises(ProtocolSchemaError, match="avro Schema 无效"):
        validate_event_schema(schema_format=EventSchemaFormat.AVRO, schema='{"type":"bad"}')
    with pytest.raises(ProtocolSchemaError, match="json_schema Schema 无效"):
        validate_event_schema(
            schema_format=EventSchemaFormat.JSON_SCHEMA,
            schema='{"type":"definitely-invalid"}',
        )


@pytest.mark.parametrize(
    "servers",
    [(), ("broker:9092", "broker:9092"), ("missing-port",), ("broker:65536",)],
)
def test_kafka_bootstrap_validation_rejects_unbounded_or_invalid_targets(
    servers: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        validate_bootstrap_servers(servers)
    assert validate_bootstrap_servers((" broker-1:9092 ", "[2001:db8::1]:9093")) == (
        "broker-1:9092",
        "[2001:db8::1]:9093",
    )


def test_event_source_and_schema_requests_enforce_protocol_specific_shape() -> None:
    project_id = uuid4()
    kafka = EventSourceCreate(
        project_id=project_id,
        kind="kafka",
        name="Kafka",
        bootstrap_servers=["broker:9092"],
        schema_registry_url="https://registry.example.com/",
    )
    websocket = EventSourceCreate(
        project_id=project_id,
        kind="websocket",
        name="WS",
        websocket_url="wss://events.example.com/ws",
    )
    assert _event_endpoints(kafka, EventSourceKind.KAFKA) == ("broker:9092",)
    assert _event_endpoints(websocket, EventSourceKind.WEBSOCKET) == (
        "wss://events.example.com/ws",
    )
    assert _registry_url(kafka.schema_registry_url) == "https://registry.example.com"
    assert len(_source_fingerprint(EventSourceKind.KAFKA, ("broker:9092",), None)) == 64

    with pytest.raises(ValidationError):
        EventSourceCreate(
            project_id=project_id,
            kind="kafka",
            name="bad",
            websocket_url="wss://example.com/ws",
        )
    with pytest.raises(ValidationError):
        EventSourceCreate(
            project_id=project_id,
            kind="websocket",
            name="bad",
            websocket_url="wss://example.com/ws",
            schema_registry_url="https://registry.example.com",
        )
    with pytest.raises(AppError, match="ws/wss"):
        _event_endpoints(
            EventSourceCreate(
                project_id=project_id,
                kind="websocket",
                name="bad",
                websocket_url="ws://example.com/ws",
            ).model_copy(update={"websocket_url": "http://example.com"}),
            EventSourceKind.WEBSOCKET,
        )
    with pytest.raises(AppError, match="http/https"):
        _registry_url("ftp://registry.example.com")
    assert (
        EventSchemaCreate.model_validate(
            {"name": "order", "schema_format": "avro", "schema": AVRO_SCHEMA}
        ).schema_content
        == AVRO_SCHEMA
    )
    with pytest.raises(ValidationError):
        EventSchemaCreate.model_validate(
            {"name": "order", "schema_format": "protobuf", "schema": AVRO_SCHEMA}
        )
    with pytest.raises(ValidationError):
        EventSchemaCreate(name="order", schema_format="avro", files=[])


def test_event_codec_round_trips_json_avro_protobuf_and_registry_frames() -> None:
    raw = encode_event_value(
        {"id": "order-1"},
        schema_content=None,
        schema_summary=None,
        message_type=None,
    )
    assert decode_event_value(
        raw,
        schema_content=None,
        schema_summary=None,
        message_type=None,
    ) == {"id": "order-1"}

    avro = validate_event_schema(
        schema_format=EventSchemaFormat.AVRO,
        schema=AVRO_SCHEMA,
        registry_id=12,
    )
    avro_value: JsonValue = {"id": "order-1", "amount": 20}
    avro_payload = encode_event_value(
        avro_value,
        schema_content=avro.canonical_content,
        schema_summary=avro.summary,
        message_type=None,
    )
    assert avro_payload[:5] == b"\x00\x00\x00\x00\x0c"
    assert (
        decode_event_value(
            avro_payload,
            schema_content=avro.canonical_content,
            schema_summary=avro.summary,
            message_type=None,
        )
        == avro_value
    )

    protobuf = validate_event_schema(
        schema_format=EventSchemaFormat.PROTOBUF,
        proto_files=(ProtoSourceFile(name="order.proto", content=PROTO_SCHEMA),),
        entrypoint="order.proto",
        registry_id=7,
    )
    protobuf_value: JsonValue = {"id": "order-2", "amount": 30}
    protobuf_payload = encode_event_value(
        protobuf_value,
        schema_content=protobuf.canonical_content,
        schema_summary=protobuf.summary,
        message_type="flowtest.events.v1.OrderCreated",
    )
    assert protobuf_payload[:6] == b"\x00\x00\x00\x00\x07\x00"
    assert decode_event_value(
        protobuf_payload,
        schema_content=protobuf.canonical_content,
        schema_summary=protobuf.summary,
        message_type="flowtest.events.v1.OrderCreated",
    ) == {"id": "order-2", "amount": 30}


def test_event_codec_reports_schema_message_and_size_failures() -> None:
    schema = validate_event_schema(
        schema_format=EventSchemaFormat.JSON_SCHEMA,
        schema=JSON_SCHEMA,
        registry_id=4,
    )
    with pytest.raises(NodeExecutionError, match="JSON Schema"):
        encode_event_value(
            {"id": 1},
            schema_content=schema.canonical_content,
            schema_summary=schema.summary,
            message_type=None,
        )
    with pytest.raises(NodeExecutionError, match="Wire Format"):
        decode_event_value(
            b"{}",
            schema_content=schema.canonical_content,
            schema_summary=schema.summary,
            message_type=None,
        )
    with pytest.raises(NodeExecutionError, match="Schema ID"):
        decode_event_value(
            b"\x00\x00\x00\x00\x05{}",
            schema_content=schema.canonical_content,
            schema_summary=schema.summary,
            message_type=None,
        )
    with pytest.raises(NodeExecutionError, match="4 MB"):
        encode_event_value(
            "x" * MAX_EVENT_MESSAGE_BYTES,
            schema_content=None,
            schema_summary=None,
            message_type=None,
        )
    with pytest.raises(NodeExecutionError, match="Message Type"):
        encode_event_value(
            {"id": "1"},
            schema_content=b"invalid descriptor",
            schema_summary={"event_schema_format": "protobuf", "registry_id": None},
            message_type=None,
        )


def test_event_codec_rejects_corrupt_payloads_and_unknown_protobuf_types() -> None:
    json_schema = validate_event_schema(
        schema_format=EventSchemaFormat.JSON_SCHEMA,
        schema=JSON_SCHEMA,
    )
    encoded = encode_event_value(
        {"id": "42"},
        schema_content=json_schema.canonical_content,
        schema_summary=json_schema.summary,
        message_type=None,
    )
    assert decode_event_value(
        encoded,
        schema_content=json_schema.canonical_content,
        schema_summary=json_schema.summary,
        message_type=None,
    ) == {"id": "42"}
    with pytest.raises(NodeExecutionError, match="4 MB"):
        decode_event_value(
            b"x" * (MAX_EVENT_MESSAGE_BYTES + 1),
            schema_content=None,
            schema_summary=None,
            message_type=None,
        )
    with pytest.raises(NodeExecutionError, match="不是有效 JSON"):
        decode_event_value(
            b"\xff",
            schema_content=json_schema.canonical_content,
            schema_summary=json_schema.summary,
            message_type=None,
        )
    assert decode_event_value(
        b"\xff",
        schema_content=None,
        schema_summary=None,
        message_type=None,
    ) == {"encoding": "hex", "value": "ff"}

    avro = validate_event_schema(schema_format=EventSchemaFormat.AVRO, schema=AVRO_SCHEMA)
    with pytest.raises(NodeExecutionError, match="Avro Schema"):
        encode_event_value(
            {"id": "missing-amount"},
            schema_content=avro.canonical_content,
            schema_summary=avro.summary,
            message_type=None,
        )
    with pytest.raises(NodeExecutionError, match="无法按固定 Schema 解码"):
        decode_event_value(
            b"\xff",
            schema_content=avro.canonical_content,
            schema_summary=avro.summary,
            message_type=None,
        )

    protobuf = validate_event_schema(
        schema_format=EventSchemaFormat.PROTOBUF,
        proto_files=(ProtoSourceFile(name="order.proto", content=PROTO_SCHEMA),),
        entrypoint="order.proto",
        registry_id=7,
    )
    with pytest.raises(NodeExecutionError, match="JSON 对象"):
        encode_event_value(
            "not-an-object",
            schema_content=protobuf.canonical_content,
            schema_summary=protobuf.summary,
            message_type="flowtest.events.v1.OrderCreated",
        )
    with pytest.raises(NodeExecutionError, match="不存在"):
        encode_event_value(
            {},
            schema_content=protobuf.canonical_content,
            schema_summary=protobuf.summary,
            message_type="flowtest.events.v1.Missing",
        )
    with pytest.raises(NodeExecutionError, match="首个 Protobuf Message"):
        decode_event_value(
            b"\x00\x00\x00\x00\x07\x01",
            schema_content=protobuf.canonical_content,
            schema_summary=protobuf.summary,
            message_type="flowtest.events.v1.OrderCreated",
        )


def test_event_node_config_binding_and_version_rules_are_explicit() -> None:
    source_id = uuid4()
    node = _event_node(
        "kafka.produce",
        {
            "source_id": str(source_id),
            "topic": "orders.created",
            "value": {"id": "initial"},
        },
        bindings=[
            {"input": "value.id", "expression": "node_outputs.rest.body.id"},
            {"input": "key", "expression": "runtime_variables.order_key"},
        ],
    )
    context = ExecutionContext(runtime_variables={"order_key": "key-42"})
    context.record_output("rest", {"body": {"id": "42"}})

    assert isinstance(parse_event_config(node), KafkaProduceCapabilityConfig)
    resolved = resolve_event_config(node, context)
    assert isinstance(resolved, KafkaProduceCapabilityConfig)
    assert resolved.value == {"id": "42"}
    assert resolved.key == "key-42"

    with pytest.raises(ValidationError, match="Correlation"):
        KafkaProduceCapabilityConfig(
            source_id=source_id,
            topic="orders",
            value={},
            correlation_header="x-correlation-id",
        )
    with pytest.raises(ValidationError, match="Correlation"):
        KafkaConsumeCapabilityConfig(
            source_id=source_id,
            topic="orders",
            correlation_id="42",
        )
    assert node.bindings is not None
    forbidden = node.model_copy(
        update={"bindings": [node.bindings[0].model_copy(update={"input": "topic"})]}
    )
    with pytest.raises(NodeExecutionError, match="绑定目标"):
        resolve_event_config(forbidden, context)
    missing = node.model_copy(
        update={
            "bindings": [
                node.bindings[0].model_copy(update={"expression": "node_outputs.missing.id"})
            ]
        }
    )
    with pytest.raises(NodeExecutionError, match="未找到"):
        resolve_event_config(missing, context)
    unsupported = node.model_copy(update={"capability_version": "4.0.0", "bindings": []})
    with pytest.raises(ValueError, match="supported event"):
        parse_event_config(unsupported)
    with pytest.raises(NodeExecutionError, match="Runner"):
        resolve_event_config(unsupported, context)


@pytest.mark.asyncio
async def test_kafka_runner_produces_consumes_and_redacts_sensitive_headers() -> None:
    source_id = uuid4()
    record = KafkaRecord(
        topic="orders.created",
        partition=1,
        offset=4,
        timestamp_ms=10,
        key=b"key-1",
        value=b'{"id":"42"}',
        headers=(("authorization", b"Bearer private"), ("trace-id", b"trace-1")),
    )
    kafka = FakeKafkaGateway(records=(record,))
    guard = AllowAllGuard()
    runner = EventProtocolRunner(
        OutboundNetworkPolicy(),
        kafka=kafka,
        outbound_guard=guard,  # type: ignore[arg-type]
    )
    prepared = _prepared(source_id, EventSourceKind.KAFKA, ("broker.internal:9092",))
    produced = await runner.execute_kafka_produce(
        prepared,
        KafkaProduceCapabilityConfig(
            source_id=source_id,
            topic="orders.created",
            value={"id": "42"},
            key="key-1",
            headers={"trace-id": "trace-1"},
            correlation_header="correlation-id",
            correlation_id="42",
        ),
    )
    consumed = await runner.execute_kafka_consume(
        prepared,
        KafkaConsumeCapabilityConfig(
            source_id=source_id,
            topic="orders.created",
            offset=KafkaOffset.EARLIEST,
            maximum_messages=2,
        ),
    )

    produced_output = cast(dict[str, JsonValue], produced.output)
    consumed_output = cast(dict[str, JsonValue], consumed.output)
    assert produced_output["offset"] == 9
    assert kafka.produced[0]["headers"] == (
        ("trace-id", b"trace-1"),
        ("correlation-id", b"42"),
    )
    assert consumed_output["message_count"] == 1
    messages = cast(list[dict[str, JsonValue]], consumed_output["messages"])
    headers = cast(dict[str, JsonValue], messages[0]["headers"])
    assert headers["authorization"] == "***"
    assert guard.targets == [("broker.internal", 9092), ("broker.internal", 9092)]
    assert _kafka_correlation_matches(record, "trace-id", b"trace-1")
    assert not _kafka_correlation_matches(record, "trace-id", b"missing")


@pytest.mark.asyncio
async def test_kafka_runner_translates_network_and_transport_failures() -> None:
    source_id = uuid4()
    prepared = _prepared(source_id, EventSourceKind.KAFKA, ("broker:9092",))
    blocked = EventProtocolRunner(
        OutboundNetworkPolicy(),
        kafka=FakeKafkaGateway(),
        outbound_guard=RejectingGuard(),  # type: ignore[arg-type]
    )
    with pytest.raises(NodeExecutionError) as blocked_error:
        await blocked.execute_kafka_produce(
            prepared,
            KafkaProduceCapabilityConfig(source_id=source_id, topic="orders", value={}),
        )
    assert blocked_error.value.code == "SSRF_BLOCKED"

    failing = EventProtocolRunner(
        OutboundNetworkPolicy(),
        kafka=FakeKafkaGateway(fail_produce=True, fail_consume=True),
        outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
    )
    with pytest.raises(NodeExecutionError) as produce_error:
        await failing.execute_kafka_produce(
            prepared,
            KafkaProduceCapabilityConfig(source_id=source_id, topic="orders", value={}),
        )
    assert produce_error.value.code == "KAFKA_PRODUCE_FAILED"
    with pytest.raises(NodeExecutionError) as consume_error:
        await failing.execute_kafka_consume(
            prepared,
            KafkaConsumeCapabilityConfig(source_id=source_id, topic="orders"),
        )
    assert consume_error.value.code == "KAFKA_CONSUME_FAILED"


@pytest.mark.asyncio
async def test_confluent_gateway_uses_bounded_non_committing_client_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_runtime_module, "Producer", FakeProducer)
    monkeypatch.setattr(event_runtime_module, "Consumer", FakeConsumer)
    gateway = ConfluentKafkaGateway()
    record = await gateway.produce(
        bootstrap_servers=("broker:9092",),
        topic="orders",
        key=b"key",
        value=b"{}",
        headers=(("correlation-id", b"42"),),
        timeout_seconds=2,
    )
    consumed = await gateway.consume(
        bootstrap_servers=("broker:9092",),
        topic="orders",
        offset=KafkaOffset.EARLIEST,
        maximum_messages=10,
        correlation_header="correlation-id",
        correlation_id=b"42",
        timeout_seconds=2,
    )

    assert record.topic == "orders"
    assert consumed[0].key == b"key"
    assert FakeProducer.configuration["allow.auto.create.topics"] is False
    assert FakeConsumer.configuration["enable.auto.commit"] is False
    assert FakeConsumer.configuration["enable.auto.offset.store"] is False
    assert FakeConsumer.subscribed == ["orders"]
    assert FakeConsumer.closed


def test_confluent_blocking_helpers_timeout_and_normalize_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutProducer(FakeProducer):
        def produce(self, topic: str, **values: object) -> None:
            del topic, values

        def flush(self, timeout: int) -> int:
            del timeout
            return 1

    monkeypatch.setattr(event_runtime_module, "Producer", TimeoutProducer)
    with pytest.raises(TimeoutError):
        _produce_blocking(("broker:9092",), "orders", None, b"{}", (), 1)

    message = FakeKafkaMessage(value="text", headers={"trace": "42"})
    record = _record_from_message(cast(object, message))  # type: ignore[arg-type]
    assert record.value == b"text"
    assert record.headers == (("trace", b"42"),)
    assert _message_headers(cast(object, message)) == [("trace", "42")]  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_websocket_session_lifecycle_exchange_and_session_loss() -> None:
    source_id = uuid4()
    sockets = [
        FakeWebSocket(['{"id":"ignore"}', '{"id":"42"}']),
        FakeWebSocket(['{"id":"exchange"}']),
    ]

    async def connector(url: str, **options: object) -> FakeWebSocket:
        del url, options
        return sockets.pop(0)

    runner = EventProtocolRunner(
        OutboundNetworkPolicy(),
        outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
        websocket_connector=connector,
    )
    prepared = _prepared(
        source_id,
        EventSourceKind.WEBSOCKET,
        ("wss://events.example.com/ws",),
    )
    connected = await runner.execute_websocket_connect(
        prepared,
        WebSocketConnectCapabilityConfig(
            source_id=source_id,
            session_key="orders",
            headers={"x-trace": "trace-1"},
            subprotocols=("flowtest.v1",),
        ),
    )
    sent = await runner.execute_websocket_send(
        WebSocketSendCapabilityConfig(session_key="orders", message={"id": "42"})
    )
    awaited = await runner.execute_websocket_await(
        WebSocketAwaitCapabilityConfig(
            session_key="orders",
            correlation_expression="id",
            correlation_value="42",
            maximum_messages=2,
        )
    )
    closed = await runner.execute_websocket_close(
        WebSocketCloseCapabilityConfig(session_key="orders")
    )
    exchanged = await runner.execute_websocket_exchange(
        prepared,
        WebSocketExchangeCapabilityConfig(
            source_id=source_id,
            message={"request": 1},
            correlation_expression="id",
            correlation_value="exchange",
        ),
    )

    assert cast(dict[str, JsonValue], connected.output)["subprotocol"] == "flowtest.v1"
    assert cast(dict[str, JsonValue], sent.output)["size_bytes"] == 11
    assert cast(dict[str, JsonValue], awaited.output)["message_count"] == 2
    assert cast(dict[str, JsonValue], closed.output)["code"] == 1000
    assert cast(dict[str, JsonValue], exchanged.output)["operation"] == "exchange"
    with pytest.raises(NodeExecutionError) as lost:
        await runner.execute_websocket_send(
            WebSocketSendCapabilityConfig(session_key="orders", message={})
        )
    assert lost.value.code == "SESSION_LOST"


@pytest.mark.asyncio
async def test_websocket_runner_closes_sessions_and_handles_failures() -> None:
    source_id = uuid4()
    failing_send = FakeWebSocket([], fail_send=True)
    failing_receive = FakeWebSocket([], fail_receive=True)
    pending = FakeWebSocket([])
    sockets = [failing_send, failing_receive, pending]

    async def connector(url: str, **options: object) -> FakeWebSocket:
        del url, options
        return sockets.pop(0)

    runner = EventProtocolRunner(
        OutboundNetworkPolicy(),
        outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
        websocket_connector=connector,
    )
    prepared = _prepared(source_id, EventSourceKind.WEBSOCKET, ("ws://events:8080/ws",))
    for key in ("send_failure", "receive_failure", "timeout"):
        await runner.execute_websocket_connect(
            prepared,
            WebSocketConnectCapabilityConfig(source_id=source_id, session_key=key),
        )
    with pytest.raises(NodeExecutionError) as send_error:
        await runner.execute_websocket_send(
            WebSocketSendCapabilityConfig(session_key="send_failure", message="x")
        )
    assert send_error.value.code == "SESSION_LOST"
    with pytest.raises(NodeExecutionError) as receive_error:
        await runner.execute_websocket_await(
            WebSocketAwaitCapabilityConfig(session_key="receive_failure")
        )
    assert receive_error.value.code == "SESSION_LOST"
    with pytest.raises(NodeExecutionError) as timeout_error:
        await runner.execute_websocket_await(
            WebSocketAwaitCapabilityConfig(session_key="timeout", timeout_seconds=1)
        )
    assert timeout_error.value.code == "WEBSOCKET_AWAIT_TIMEOUT"
    await runner.close_all()
    assert pending.closed


@pytest.mark.asyncio
async def test_websocket_connect_rejects_duplicate_kind_network_and_transport_failures() -> None:
    source_id = uuid4()

    async def good_connector(url: str, **options: object) -> FakeWebSocket:
        del url, options
        return FakeWebSocket([])

    async def broken_connector(url: str, **options: object) -> FakeWebSocket:
        del url, options
        raise OSError("connect failed")

    prepared = _prepared(source_id, EventSourceKind.WEBSOCKET, ("wss://events/ws",))
    runner = EventProtocolRunner(
        OutboundNetworkPolicy(),
        outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
        websocket_connector=good_connector,
    )
    config = WebSocketConnectCapabilityConfig(source_id=source_id, session_key="session")
    await runner.execute_websocket_connect(prepared, config)
    with pytest.raises(NodeExecutionError) as duplicate:
        await runner.execute_websocket_connect(prepared, config)
    assert duplicate.value.code == "WEBSOCKET_SESSION_EXISTS"

    broken = EventProtocolRunner(
        OutboundNetworkPolicy(),
        outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
        websocket_connector=broken_connector,
    )
    with pytest.raises(NodeExecutionError) as connect_error:
        await broken.execute_websocket_connect(prepared, config)
    assert connect_error.value.code == "WEBSOCKET_CONNECT_FAILED"

    blocked = EventProtocolRunner(
        OutboundNetworkPolicy(),
        outbound_guard=RejectingGuard(),  # type: ignore[arg-type]
        websocket_connector=good_connector,
    )
    with pytest.raises(NodeExecutionError) as network_error:
        await blocked.execute_websocket_connect(prepared, config)
    assert network_error.value.code == "SSRF_BLOCKED"
    with pytest.raises(NodeExecutionError) as kind_error:
        await runner.execute_kafka_produce(
            prepared,
            KafkaProduceCapabilityConfig(source_id=source_id, topic="orders", value={}),
        )
    assert kind_error.value.code == "EVENT_SOURCE_KIND_MISMATCH"


def test_event_runtime_helpers_enforce_header_payload_and_correlation_rules() -> None:
    assert _kafka_headers({" trace ": "42"}) == (("trace", b"42"),)
    assert _redacted_kafka_headers((("cookie", b"private"),))["cookie"] == "***"
    assert _message_bytes("value") == b"value"
    assert _message_bytes(None) is None
    with pytest.raises(NodeExecutionError, match="Kafka Header"):
        _kafka_headers({"": "value"})
    assert _safe_websocket_headers({"x-trace": "42"}) == {"x-trace": "42"}
    with pytest.raises(NodeExecutionError, match="WebSocket Header"):
        _safe_websocket_headers({"Host": "example.com"})
    with pytest.raises(NodeExecutionError, match="WebSocket Header"):
        _safe_websocket_headers({"x-trace": "bad\r\nheader"})
    assert _websocket_outbound({"id": 1}, WebSocketPayloadKind.JSON) == '{"id":1}'
    assert _websocket_outbound("text", WebSocketPayloadKind.TEXT) == "text"
    with pytest.raises(NodeExecutionError, match="必须是字符串"):
        _websocket_outbound({"id": 1}, WebSocketPayloadKind.TEXT)
    assert _websocket_inbound(b"\x00\xff") == {"encoding": "hex", "value": "00ff"}
    assert _websocket_inbound("plain") == "plain"
    assert _websocket_inbound('{"id":"42"}') == {"id": "42"}
    assert _correlation_matches({"id": "42"}, "id", "42")
    with pytest.raises(NodeExecutionError):
        _correlation_matches({"id": "42"}, "[", "42")


def test_registry_payload_and_prepared_snapshot_preserve_schema_identity() -> None:
    request = RegistrySchemaImport(name="Order", subject="orders-value")
    avro = _registry_schema_payload(
        request,
        {"id": 11, "schemaType": "AVRO", "schema": AVRO_SCHEMA},
    )
    json_schema = _registry_schema_payload(
        request,
        {"id": 12, "schemaType": "JSON", "schema": JSON_SCHEMA},
    )
    protobuf = _registry_schema_payload(
        request,
        {"id": 13, "schemaType": "PROTOBUF", "schema": PROTO_SCHEMA},
    )
    assert avro.schema_format == "avro" and avro.registry_id == 11
    assert json_schema.schema_format == "json_schema"
    assert protobuf.schema_format == "protobuf"

    project_id = uuid4()
    actor_id = uuid4()
    source = EventSource(
        id=uuid4(),
        project_id=project_id,
        kind="kafka",
        name="Kafka",
        description="",
        version=2,
        endpoints=["broker:9092"],
        schema_registry_url="https://registry.example.com",
        config_sha256="a" * 64,
        created_by_id=actor_id,
    )
    artifact = SchemaArtifact(
        id=uuid4(),
        project_id=project_id,
        protocol="kafka",
        name="Order",
        description="",
        version=3,
        source_format="event_avro",
        content_sha256="b" * 64,
        canonical_content=b"{}",
        source_content=b"{}",
        summary={"event_schema_format": "avro", "registry_id": 11},
        created_by_id=actor_id,
    )
    prepared = _prepared_event_node(source, artifact)
    assert prepared.source_version == 2
    assert prepared.schema_version == 3
    assert prepared.schema_hash == "b" * 64

    for document in (
        "not-an-object",
        {"id": "bad", "schema": AVRO_SCHEMA},
        {"id": 1, "schema": AVRO_SCHEMA, "references": [{"name": "shared"}]},
        {"id": 1, "schemaType": "XML", "schema": "<schema />"},
    ):
        with pytest.raises(AppError):
            _registry_schema_payload(request, document)


@pytest.mark.asyncio
async def test_event_source_api_crud_schema_dedup_and_auth(
    event_client: tuple[AsyncClient, UUID],
) -> None:
    client, project_id = event_client
    assert (await client.get(f"/api/v1/event-sources?project_id={project_id}")).status_code == 401
    headers = await _login_headers(client)
    kafka_payload = {
        "project_id": str(project_id),
        "kind": "kafka",
        "name": "Orders Kafka",
        "bootstrap_servers": ["broker.example.com:9092"],
        "schema_registry_url": "https://registry.example.com",
    }
    created = await client.post("/api/v1/event-sources", headers=headers, json=kafka_payload)
    assert created.status_code == 201
    source_id = created.json()["id"]
    duplicate = await client.post("/api/v1/event-sources", headers=headers, json=kafka_payload)
    assert duplicate.status_code == 409
    listed = await client.get(
        f"/api/v1/event-sources?project_id={project_id}&kind=kafka",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    schema = await client.post(
        f"/api/v1/event-sources/{source_id}/schemas?project_id={project_id}",
        headers=headers,
        json={"name": "Order", "schema_format": "avro", "schema": AVRO_SCHEMA},
    )
    assert schema.status_code == 201
    schemas = await client.get(
        f"/api/v1/event-sources/{source_id}/schemas?project_id={project_id}",
        headers=headers,
    )
    assert schemas.status_code == 200
    assert schemas.json()["total"] == 1

    websocket = await client.post(
        "/api/v1/event-sources",
        headers=headers,
        json={
            "project_id": str(project_id),
            "kind": "websocket",
            "name": "Order WebSocket",
            "websocket_url": "wss://events.example.com/ws",
        },
    )
    assert websocket.status_code == 201
    mismatch = await client.get(
        f"/api/v1/event-sources/{websocket.json()['id']}/schemas?project_id={project_id}",
        headers=headers,
    )
    assert mismatch.status_code == 404


@pytest.mark.asyncio
async def test_event_debug_endpoints_are_feature_gated_before_network_access(
    event_client: tuple[AsyncClient, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, project_id = event_client
    headers = await _login_headers(client)
    created = await client.post(
        "/api/v1/event-sources",
        headers=headers,
        json={
            "project_id": str(project_id),
            "kind": "kafka",
            "name": "Debug Kafka",
            "bootstrap_servers": ["broker.example.com:9092"],
        },
    )
    source_id = created.json()["id"]
    monkeypatch.setattr(settings, "feature_event_protocols_enabled", False)
    response = await client.post(
        f"/api/v1/event-sources/{source_id}/kafka/produce",
        headers=headers,
        json={"project_id": str(project_id), "topic": "orders", "value": {"id": 1}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EVENT_PROTOCOLS_DISABLED"


def _event_node(
    capability_id: str,
    configuration: dict[str, object],
    *,
    bindings: list[dict[str, str]] | None = None,
) -> WorkflowNode:
    return WorkflowNode.model_validate(
        {
            "id": "event",
            "type": "capability",
            "name": "Event node",
            "position": {"x": 0, "y": 0},
            "capability_id": capability_id,
            "capability_version": "3.0.0",
            "configuration": configuration,
            "bindings": bindings or [],
        }
    )


def _prepared(
    source_id: UUID,
    kind: EventSourceKind,
    endpoints: tuple[str, ...],
) -> PreparedEventNode:
    return PreparedEventNode(
        source_id=source_id,
        source_kind=kind,
        endpoints=endpoints,
        schema_registry_url=None,
        source_version=1,
        source_hash="a" * 64,
    )


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _never() -> str:
    await __import__("asyncio").Event().wait()
    return "unreachable"
