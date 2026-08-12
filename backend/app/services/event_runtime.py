import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer
from pydantic import JsonValue
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from app.core.errors import AppError
from app.core.logging import redact
from app.domain.event_protocols import (
    MAX_EVENT_MESSAGE_BYTES,
    EventSourceKind,
    KafkaOffset,
    WebSocketPayloadKind,
)
from app.domain.expressions import SafeExpressionError, evaluate_safe_expression
from app.domain.network import OutboundNetworkPolicy
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
)
from app.engine.scheduler import NodeExecutionError
from app.services.outbound import OutboundRequestGuard, outbound_request_guard


@dataclass(frozen=True, slots=True)
class EventExecutionResult:
    output: JsonValue
    duration_ms: int


@dataclass(frozen=True, slots=True)
class KafkaRecord:
    topic: str
    partition: int
    offset: int
    timestamp_ms: int | None
    key: bytes | None
    value: bytes
    headers: tuple[tuple[str, bytes | None], ...]


class KafkaGateway(Protocol):
    async def produce(
        self,
        *,
        bootstrap_servers: tuple[str, ...],
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: tuple[tuple[str, bytes], ...],
        timeout_seconds: int,
    ) -> KafkaRecord: ...

    async def consume(
        self,
        *,
        bootstrap_servers: tuple[str, ...],
        topic: str,
        offset: KafkaOffset,
        maximum_messages: int,
        correlation_header: str | None,
        correlation_id: bytes | None,
        timeout_seconds: int,
    ) -> tuple[KafkaRecord, ...]: ...


class WebSocketConnection(Protocol):
    @property
    def subprotocol(self) -> str | None: ...

    async def send(self, message: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


WebSocketConnector = Callable[..., Awaitable[WebSocketConnection]]


class ConfluentKafkaGateway:
    async def produce(
        self,
        *,
        bootstrap_servers: tuple[str, ...],
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: tuple[tuple[str, bytes], ...],
        timeout_seconds: int,
    ) -> KafkaRecord:
        return await asyncio.to_thread(
            _produce_blocking,
            bootstrap_servers,
            topic,
            key,
            value,
            headers,
            timeout_seconds,
        )

    async def consume(
        self,
        *,
        bootstrap_servers: tuple[str, ...],
        topic: str,
        offset: KafkaOffset,
        maximum_messages: int,
        correlation_header: str | None,
        correlation_id: bytes | None,
        timeout_seconds: int,
    ) -> tuple[KafkaRecord, ...]:
        return await asyncio.to_thread(
            _consume_blocking,
            bootstrap_servers,
            topic,
            offset,
            maximum_messages,
            correlation_header,
            correlation_id,
            timeout_seconds,
        )


class EventProtocolRunner:
    def __init__(
        self,
        network_policy: OutboundNetworkPolicy,
        *,
        kafka: KafkaGateway | None = None,
        outbound_guard: OutboundRequestGuard = outbound_request_guard,
        websocket_connector: WebSocketConnector | None = None,
    ) -> None:
        self._network_policy = network_policy
        self._kafka = kafka or ConfluentKafkaGateway()
        self._outbound_guard = outbound_guard
        self._websocket_connector = websocket_connector or cast(WebSocketConnector, connect)
        self._sessions: dict[str, WebSocketConnection] = {}

    async def execute_kafka_produce(
        self,
        prepared: PreparedEventNode,
        config: KafkaProduceCapabilityConfig,
    ) -> EventExecutionResult:
        _require_kind(prepared, EventSourceKind.KAFKA)
        started = monotonic()
        await self._enforce_kafka(prepared.endpoints)
        headers = _kafka_headers(config.headers)
        if config.correlation_header and config.correlation_id:
            headers += ((config.correlation_header, config.correlation_id.encode()),)
        value = encode_event_value(
            config.value,
            schema_content=prepared.schema_content,
            schema_summary=prepared.schema_summary,
            message_type=config.message_type,
        )
        try:
            record = await self._kafka.produce(
                bootstrap_servers=prepared.endpoints,
                topic=config.topic,
                key=config.key.encode() if config.key is not None else None,
                value=value,
                headers=headers,
                timeout_seconds=config.timeout_seconds,
            )
        except (KafkaException, TimeoutError) as error:
            raise NodeExecutionError(
                code="KAFKA_PRODUCE_FAILED",
                message="Kafka Produce 失败",
            ) from error
        return EventExecutionResult(
            output={
                "protocol": "kafka",
                "operation": "produce",
                "topic": record.topic,
                "partition": record.partition,
                "offset": record.offset,
                "schema_hash": prepared.schema_hash,
                "source_hash": prepared.source_hash,
                "size_bytes": len(value),
            },
            duration_ms=_elapsed_ms(started),
        )

    async def execute_kafka_consume(
        self,
        prepared: PreparedEventNode,
        config: KafkaConsumeCapabilityConfig,
    ) -> EventExecutionResult:
        _require_kind(prepared, EventSourceKind.KAFKA)
        started = monotonic()
        await self._enforce_kafka(prepared.endpoints)
        try:
            records = await self._kafka.consume(
                bootstrap_servers=prepared.endpoints,
                topic=config.topic,
                offset=config.offset,
                maximum_messages=config.maximum_messages,
                correlation_header=config.correlation_header,
                correlation_id=(
                    config.correlation_id.encode() if config.correlation_id is not None else None
                ),
                timeout_seconds=config.timeout_seconds,
            )
        except (KafkaException, TimeoutError) as error:
            raise NodeExecutionError(
                code="KAFKA_CONSUME_FAILED",
                message="Kafka Consume 失败",
            ) from error
        decoded = [
            {
                "partition": record.partition,
                "offset": record.offset,
                "timestamp_ms": record.timestamp_ms,
                "key": record.key.decode(errors="replace") if record.key is not None else None,
                "headers": _redacted_kafka_headers(record.headers),
                "value": decode_event_value(
                    record.value,
                    schema_content=prepared.schema_content,
                    schema_summary=prepared.schema_summary,
                    message_type=config.message_type,
                ),
            }
            for record in records
        ]
        return EventExecutionResult(
            output=cast(
                JsonValue,
                {
                    "protocol": "kafka",
                    "operation": "consume",
                    "topic": config.topic,
                    "message_count": len(decoded),
                    "messages": decoded,
                    "auto_commit": False,
                    "schema_hash": prepared.schema_hash,
                    "source_hash": prepared.source_hash,
                },
            ),
            duration_ms=_elapsed_ms(started),
        )

    async def execute_websocket_connect(
        self,
        prepared: PreparedEventNode,
        config: WebSocketConnectCapabilityConfig,
    ) -> EventExecutionResult:
        _require_kind(prepared, EventSourceKind.WEBSOCKET)
        if config.session_key in self._sessions:
            raise NodeExecutionError(
                code="WEBSOCKET_SESSION_EXISTS",
                message="WebSocket Session Key 已存在",
            )
        started = monotonic()
        url = prepared.endpoints[0]
        await self._enforce_websocket(url)
        try:
            session = await self._websocket_connector(
                url,
                additional_headers=_safe_websocket_headers(config.headers),
                subprotocols=list(config.subprotocols) or None,
                open_timeout=config.timeout_seconds,
                max_size=MAX_EVENT_MESSAGE_BYTES,
            )
        except (OSError, TimeoutError, WebSocketException) as error:
            raise NodeExecutionError(
                code="WEBSOCKET_CONNECT_FAILED",
                message="WebSocket 连接失败",
            ) from error
        self._sessions[config.session_key] = session
        return EventExecutionResult(
            output={
                "protocol": "websocket",
                "operation": "connect",
                "session_key": config.session_key,
                "subprotocol": session.subprotocol,
                "source_hash": prepared.source_hash,
            },
            duration_ms=_elapsed_ms(started),
        )

    async def execute_websocket_send(
        self,
        config: WebSocketSendCapabilityConfig,
    ) -> EventExecutionResult:
        started = monotonic()
        session = self._session(config.session_key)
        message = _websocket_outbound(config.message, config.payload_kind)
        try:
            await session.send(message)
        except (OSError, WebSocketException) as error:
            self._sessions.pop(config.session_key, None)
            raise NodeExecutionError(
                code="SESSION_LOST",
                message="WebSocket Session 已丢失。请从 Connect 节点重试",
            ) from error
        return EventExecutionResult(
            output={
                "protocol": "websocket",
                "operation": "send",
                "session_key": config.session_key,
                "size_bytes": len(message.encode() if isinstance(message, str) else message),
            },
            duration_ms=_elapsed_ms(started),
        )

    async def execute_websocket_await(
        self,
        config: WebSocketAwaitCapabilityConfig,
    ) -> EventExecutionResult:
        started = monotonic()
        session = self._session(config.session_key)
        messages: list[JsonValue] = []
        try:
            async with asyncio.timeout(config.timeout_seconds):
                while len(messages) < config.maximum_messages:
                    message = _websocket_inbound(await session.recv())
                    messages.append(message)
                    if _correlation_matches(
                        message,
                        config.correlation_expression,
                        config.correlation_value,
                    ):
                        break
        except TimeoutError as error:
            raise NodeExecutionError(
                code="WEBSOCKET_AWAIT_TIMEOUT",
                message="WebSocket Await 超时",
                output={"messages": cast(JsonValue, redact(messages))},
            ) from error
        except (OSError, WebSocketException) as error:
            self._sessions.pop(config.session_key, None)
            raise NodeExecutionError(
                code="SESSION_LOST",
                message="WebSocket Session 已丢失。请从 Connect 节点重试",
            ) from error
        return EventExecutionResult(
            output=cast(
                JsonValue,
                {
                    "protocol": "websocket",
                    "operation": "await",
                    "session_key": config.session_key,
                    "message_count": len(messages),
                    "messages": redact(messages),
                },
            ),
            duration_ms=_elapsed_ms(started),
        )

    async def execute_websocket_close(
        self,
        config: WebSocketCloseCapabilityConfig,
    ) -> EventExecutionResult:
        started = monotonic()
        session = self._session(config.session_key)
        try:
            await session.close(code=config.code, reason=config.reason)
        finally:
            self._sessions.pop(config.session_key, None)
        return EventExecutionResult(
            output={
                "protocol": "websocket",
                "operation": "close",
                "session_key": config.session_key,
                "code": config.code,
            },
            duration_ms=_elapsed_ms(started),
        )

    async def execute_websocket_exchange(
        self,
        prepared: PreparedEventNode,
        config: WebSocketExchangeCapabilityConfig,
    ) -> EventExecutionResult:
        session_key = f"exchange_{uuid4().hex}"
        await self.execute_websocket_connect(
            prepared,
            WebSocketConnectCapabilityConfig(
                source_id=config.source_id,
                session_key=session_key,
                headers=config.headers,
                subprotocols=config.subprotocols,
                timeout_seconds=config.timeout_seconds,
            ),
        )
        started = monotonic()
        try:
            await self.execute_websocket_send(
                WebSocketSendCapabilityConfig(
                    session_key=session_key,
                    payload_kind=config.payload_kind,
                    message=config.message,
                )
            )
            result = await self.execute_websocket_await(
                WebSocketAwaitCapabilityConfig(
                    session_key=session_key,
                    correlation_expression=config.correlation_expression,
                    correlation_value=config.correlation_value,
                    maximum_messages=config.maximum_messages,
                    timeout_seconds=config.timeout_seconds,
                )
            )
            return EventExecutionResult(
                output={
                    **cast(dict[str, JsonValue], result.output),
                    "operation": "exchange",
                    "source_hash": prepared.source_hash,
                },
                duration_ms=_elapsed_ms(started),
            )
        finally:
            session = self._sessions.pop(session_key, None)
            if session is not None:
                await session.close()

    async def close_all(self) -> None:
        sessions = tuple(self._sessions.values())
        self._sessions.clear()
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)

    def _session(self, key: str) -> WebSocketConnection:
        session = self._sessions.get(key)
        if session is None:
            raise NodeExecutionError(
                code="SESSION_LOST",
                message="WebSocket Session 不存在。请从 Connect 节点重试",
            )
        return session

    async def _enforce_kafka(self, endpoints: tuple[str, ...]) -> None:
        for endpoint in endpoints:
            host, port_text = endpoint.rsplit(":", 1)
            try:
                await self._outbound_guard.enforce_target(
                    host.strip("[]"),
                    int(port_text),
                    self._network_policy,
                )
            except AppError as error:
                raise NodeExecutionError(code=error.code, message=error.message) from error

    async def _enforce_websocket(self, url: str) -> None:
        parts = urlsplit(url)
        try:
            await self._outbound_guard.enforce_target(
                parts.hostname or "",
                parts.port or (443 if parts.scheme == "wss" else 80),
                self._network_policy,
            )
        except AppError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error


def _produce_blocking(
    bootstrap_servers: tuple[str, ...],
    topic: str,
    key: bytes | None,
    value: bytes,
    headers: tuple[tuple[str, bytes], ...],
    timeout_seconds: int,
) -> KafkaRecord:
    producer = Producer(
        {
            "bootstrap.servers": ",".join(bootstrap_servers),
            "allow.auto.create.topics": False,
            "message.timeout.ms": timeout_seconds * 1000,
        }
    )
    delivered: list[KafkaRecord] = []
    failures: list[KafkaException] = []

    def on_delivery(error: KafkaError | None, message: Message) -> None:
        if error is not None:
            failures.append(KafkaException(error))
            return
        delivered.append(_record_from_message(message))

    producer.produce(topic, value=value, key=key, headers=list(headers), on_delivery=on_delivery)
    remaining = producer.flush(timeout_seconds)
    if failures:
        raise failures[0]
    if remaining or not delivered:
        raise TimeoutError("Kafka delivery timed out")
    return delivered[0]


def _consume_blocking(
    bootstrap_servers: tuple[str, ...],
    topic: str,
    offset: KafkaOffset,
    maximum_messages: int,
    correlation_header: str | None,
    correlation_id: bytes | None,
    timeout_seconds: int,
) -> tuple[KafkaRecord, ...]:
    consumer = Consumer(
        {
            "bootstrap.servers": ",".join(bootstrap_servers),
            "group.id": f"flowtest-{uuid4().hex}",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "allow.auto.create.topics": False,
            "auto.offset.reset": offset.value,
        }
    )
    records: list[KafkaRecord] = []
    deadline = monotonic() + timeout_seconds
    try:
        consumer.subscribe([topic])
        while len(records) < maximum_messages and monotonic() < deadline:
            message = consumer.poll(min(1.0, max(0.01, deadline - monotonic())))
            if message is None:
                continue
            message_error = message.error()
            if message_error is not None:
                if message_error.code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(message_error)
            record = _record_from_message(message)
            if _kafka_correlation_matches(record, correlation_header, correlation_id):
                records.append(record)
                if correlation_header is not None:
                    break
    finally:
        consumer.close()
    return tuple(records)


def _record_from_message(message: Message) -> KafkaRecord:
    timestamp_type, timestamp_ms = message.timestamp()
    del timestamp_type
    topic = message.topic()
    partition = message.partition()
    offset = message.offset()
    value = _message_bytes(message.value()) or b""
    return KafkaRecord(
        topic=topic or "",
        partition=partition if partition is not None else -1,
        offset=offset if offset is not None else -1,
        timestamp_ms=timestamp_ms if timestamp_ms >= 0 else None,
        key=_message_bytes(message.key()),
        value=value,
        headers=tuple(
            (name, _message_bytes(header_value)) for name, header_value in _message_headers(message)
        ),
    )


def _message_headers(message: Message) -> list[tuple[str, str | bytes | None]]:
    headers = message.headers()
    if isinstance(headers, dict):
        return list(headers.items())
    return headers or []


def _message_bytes(value: str | bytes | None) -> bytes | None:
    if isinstance(value, str):
        return value.encode()
    return value


def _kafka_correlation_matches(
    record: KafkaRecord,
    header: str | None,
    expected: bytes | None,
) -> bool:
    if header is None or expected is None:
        return True
    return any(name == header and value == expected for name, value in record.headers)


def _kafka_headers(values: dict[str, str]) -> tuple[tuple[str, bytes], ...]:
    headers: list[tuple[str, bytes]] = []
    for name, value in values.items():
        normalized = name.strip()
        if not normalized or len(normalized) > 128 or len(value.encode()) > 8_192:
            raise NodeExecutionError(code="INVALID_KAFKA_HEADER", message="Kafka Header 无效")
        headers.append((normalized, value.encode()))
    return tuple(headers)


def _redacted_kafka_headers(
    values: tuple[tuple[str, bytes | None], ...],
) -> dict[str, JsonValue]:
    decoded = {
        name: value.decode(errors="replace") if value is not None else None
        for name, value in values
    }
    return cast(dict[str, JsonValue], redact(decoded))


def _safe_websocket_headers(values: dict[str, str]) -> dict[str, str]:
    forbidden = {"host", "connection", "upgrade", "sec-websocket-key", "sec-websocket-version"}
    result: dict[str, str] = {}
    for name, value in values.items():
        normalized = name.strip()
        if (
            not normalized
            or normalized.lower() in forbidden
            or "\r" in value
            or "\n" in value
            or len(value) > 8_192
        ):
            raise NodeExecutionError(
                code="INVALID_WEBSOCKET_HEADER",
                message="WebSocket Header 无效",
            )
        result[normalized] = value
    return result


def _websocket_outbound(value: JsonValue, kind: WebSocketPayloadKind) -> str:
    if kind is WebSocketPayloadKind.TEXT:
        if not isinstance(value, str):
            raise NodeExecutionError(
                code="INVALID_WEBSOCKET_MESSAGE",
                message="Text WebSocket 消息必须是字符串",
            )
        message = value
    else:
        message = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(message.encode()) > MAX_EVENT_MESSAGE_BYTES:
        raise NodeExecutionError(
            code="EVENT_MESSAGE_TOO_LARGE",
            message="WebSocket 消息超过 4 MB 上限",
        )
    return message


def _websocket_inbound(value: str | bytes) -> JsonValue:
    if isinstance(value, bytes):
        if len(value) > MAX_EVENT_MESSAGE_BYTES:
            raise NodeExecutionError(
                code="EVENT_MESSAGE_TOO_LARGE",
                message="WebSocket 消息超过 4 MB 上限",
            )
        return {"encoding": "hex", "value": value.hex()}
    if len(value.encode()) > MAX_EVENT_MESSAGE_BYTES:
        raise NodeExecutionError(
            code="EVENT_MESSAGE_TOO_LARGE",
            message="WebSocket 消息超过 4 MB 上限",
        )
    try:
        return cast(JsonValue, json.loads(value))
    except json.JSONDecodeError:
        return value


def _correlation_matches(
    message: JsonValue,
    expression: str | None,
    expected: JsonValue,
) -> bool:
    if expression is None:
        return True
    try:
        return evaluate_safe_expression(expression, message) == expected
    except SafeExpressionError as error:
        raise NodeExecutionError(code=error.code, message=error.message) from error


def _require_kind(prepared: PreparedEventNode, expected: EventSourceKind) -> None:
    if prepared.source_kind is not expected:
        raise NodeExecutionError(
            code="EVENT_SOURCE_KIND_MISMATCH",
            message="事件源类型与节点能力不匹配",
        )


def _elapsed_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))
