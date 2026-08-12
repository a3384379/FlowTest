import copy
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.event_protocols import (
    MAX_EVENT_MESSAGES,
    MAX_EVENT_WAIT_SECONDS,
    MAX_WEBSOCKET_SUBPROTOCOLS,
    EventSourceKind,
    KafkaOffset,
    WebSocketPayloadKind,
)
from app.domain.expressions import SafeExpressionError, evaluate_safe_expression
from app.engine.contracts import WorkflowNode
from app.engine.protocol_nodes import _BINDING_INPUT, _set_path
from app.engine.scheduler import ExecutionContext, NodeExecutionError

TopicName = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]+$", min_length=1, max_length=249)]
SessionKey = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$", max_length=120)]


class KafkaProduceCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    topic: TopicName
    value: JsonValue
    key: str | None = Field(default=None, max_length=8_192)
    headers: dict[str, str] = Field(default_factory=dict)
    correlation_header: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=512)
    schema_id: UUID | None = None
    message_type: str | None = Field(default=None, max_length=512)
    timeout_seconds: int = Field(default=30, ge=1, le=MAX_EVENT_WAIT_SECONDS)

    @model_validator(mode="after")
    def validate_correlation(self) -> "KafkaProduceCapabilityConfig":
        if (self.correlation_header is None) != (self.correlation_id is None):
            raise ValueError("Kafka Correlation Header 和 ID 必须同时提供")
        return self


class KafkaConsumeCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    topic: TopicName
    offset: KafkaOffset = KafkaOffset.LATEST
    maximum_messages: int = Field(default=1, ge=1, le=MAX_EVENT_MESSAGES)
    correlation_header: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=512)
    schema_id: UUID | None = None
    message_type: str | None = Field(default=None, max_length=512)
    timeout_seconds: int = Field(default=30, ge=1, le=MAX_EVENT_WAIT_SECONDS)

    @model_validator(mode="after")
    def validate_correlation(self) -> "KafkaConsumeCapabilityConfig":
        if (self.correlation_header is None) != (self.correlation_id is None):
            raise ValueError("Kafka Correlation Header 和 ID 必须同时提供")
        return self


class WebSocketConnectCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    session_key: SessionKey
    headers: dict[str, str] = Field(default_factory=dict)
    subprotocols: tuple[str, ...] = Field(default=(), max_length=MAX_WEBSOCKET_SUBPROTOCOLS)
    timeout_seconds: int = Field(default=30, ge=1, le=MAX_EVENT_WAIT_SECONDS)


class WebSocketSendCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_key: SessionKey
    payload_kind: WebSocketPayloadKind = WebSocketPayloadKind.JSON
    message: JsonValue


class WebSocketAwaitCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_key: SessionKey
    correlation_expression: str | None = Field(default=None, max_length=500)
    correlation_value: JsonValue = None
    maximum_messages: int = Field(default=1, ge=1, le=MAX_EVENT_MESSAGES)
    timeout_seconds: int = Field(default=30, ge=1, le=MAX_EVENT_WAIT_SECONDS)


class WebSocketCloseCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_key: SessionKey
    code: int = Field(default=1000, ge=1000, le=4999)
    reason: str = Field(default="", max_length=123)


class WebSocketExchangeCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    payload_kind: WebSocketPayloadKind = WebSocketPayloadKind.JSON
    message: JsonValue
    headers: dict[str, str] = Field(default_factory=dict)
    subprotocols: tuple[str, ...] = Field(default=(), max_length=MAX_WEBSOCKET_SUBPROTOCOLS)
    correlation_expression: str | None = Field(default=None, max_length=500)
    correlation_value: JsonValue = None
    maximum_messages: int = Field(default=1, ge=1, le=MAX_EVENT_MESSAGES)
    timeout_seconds: int = Field(default=30, ge=1, le=MAX_EVENT_WAIT_SECONDS)


EventCapabilityConfig = (
    KafkaProduceCapabilityConfig
    | KafkaConsumeCapabilityConfig
    | WebSocketConnectCapabilityConfig
    | WebSocketSendCapabilityConfig
    | WebSocketAwaitCapabilityConfig
    | WebSocketCloseCapabilityConfig
    | WebSocketExchangeCapabilityConfig
)


@dataclass(frozen=True, slots=True)
class PreparedEventNode:
    source_id: UUID
    source_kind: EventSourceKind
    endpoints: tuple[str, ...]
    schema_registry_url: str | None
    source_version: int
    source_hash: str
    schema_id: UUID | None = None
    schema_version: int | None = None
    schema_hash: str | None = None
    schema_content: bytes | None = None
    schema_summary: dict[str, JsonValue] | None = None


_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "kafka.produce": KafkaProduceCapabilityConfig,
    "kafka.consume": KafkaConsumeCapabilityConfig,
    "websocket.connect": WebSocketConnectCapabilityConfig,
    "websocket.send": WebSocketSendCapabilityConfig,
    "websocket.await": WebSocketAwaitCapabilityConfig,
    "websocket.close": WebSocketCloseCapabilityConfig,
    "websocket.exchange": WebSocketExchangeCapabilityConfig,
}


def parse_event_config(node: WorkflowNode) -> EventCapabilityConfig:
    if node.capability_id is None or node.configuration is None:
        raise ValueError("Event capability configuration is missing")
    model = _CONFIG_MODELS.get(node.capability_id)
    if model is None or node.capability_version != "3.0.0":
        raise ValueError("Node is not a supported event capability")
    return model.model_validate(node.configuration)  # type: ignore[return-value]


def resolve_event_config(node: WorkflowNode, context: ExecutionContext) -> EventCapabilityConfig:
    if node.configuration is None:
        raise NodeExecutionError(code="INVALID_EVENT_CONFIG", message="事件节点配置缺失")
    configuration = copy.deepcopy(node.configuration)
    source = context.snapshot()
    for binding in node.bindings or ():
        if _BINDING_INPUT.fullmatch(binding.input) is None or not _binding_target_allowed(
            node.capability_id, binding.input
        ):
            raise NodeExecutionError(
                code="INVALID_CAPABILITY_BINDING",
                message=f"绑定目标 {binding.input} 无效",
            )
        try:
            value = evaluate_safe_expression(binding.expression, source)
        except SafeExpressionError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error
        if value is None:
            raise NodeExecutionError(
                code="CAPABILITY_BINDING_SOURCE_MISSING",
                message=f"绑定表达式 {binding.expression} 未找到值",
            )
        _set_path(configuration, binding.input.split("."), value)
    model = _CONFIG_MODELS.get(node.capability_id or "")
    if model is None or node.capability_version != "3.0.0":
        raise NodeExecutionError(
            code="CAPABILITY_RUNTIME_UNAVAILABLE",
            message="当前 Runner 不支持该事件能力版本",
        )
    try:
        return model.model_validate(configuration)  # type: ignore[return-value]
    except ValueError as error:
        raise NodeExecutionError(
            code="INVALID_EVENT_CONFIG",
            message="事件节点绑定后的配置无效",
        ) from error


def _binding_target_allowed(capability_id: str | None, target: str) -> bool:
    if capability_id == "kafka.produce":
        return (
            target == "value" or target.startswith("value.") or target in {"key", "correlation_id"}
        )
    if capability_id == "kafka.consume":
        return target == "correlation_id"
    if capability_id in {"websocket.send", "websocket.exchange"}:
        return target == "message" or target.startswith("message.")
    if capability_id == "websocket.await":
        return target == "correlation_value"
    return False
