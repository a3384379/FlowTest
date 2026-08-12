from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.protocols import ProtoFileInput

EventSourceName = Annotated[str, Field(min_length=1, max_length=160)]


class EventSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    kind: Literal["kafka", "websocket"]
    name: EventSourceName
    description: str = Field(default="", max_length=4000)
    bootstrap_servers: list[str] | None = Field(default=None, min_length=1, max_length=10)
    websocket_url: str | None = Field(default=None, min_length=6, max_length=2048)
    schema_registry_url: str | None = Field(default=None, min_length=8, max_length=2048)

    @model_validator(mode="after")
    def validate_target(self) -> "EventSourceCreate":
        if self.kind == "kafka":
            if not self.bootstrap_servers or self.websocket_url is not None:
                raise ValueError("Kafka 事件源必须且只能提供 Bootstrap Server")
        elif self.websocket_url is None or self.bootstrap_servers is not None:
            raise ValueError("WebSocket 事件源必须且只能提供 WebSocket URL")
        if self.kind != "kafka" and self.schema_registry_url is not None:
            raise ValueError("只有 Kafka 事件源可以配置 Schema Registry")
        return self


class EventSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    kind: Literal["kafka", "websocket"]
    name: str
    description: str
    version: int
    endpoints: list[str]
    schema_registry_url: str | None
    config_sha256: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class EventSchemaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: EventSourceName
    description: str = Field(default="", max_length=4000)
    schema_format: Literal["avro", "json_schema", "protobuf"]
    schema_content: str | None = Field(default=None, alias="schema")
    entrypoint: str | None = Field(default=None, max_length=240)
    files: list[ProtoFileInput] | None = Field(default=None, max_length=50)
    registry_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_source(self) -> "EventSchemaCreate":
        if self.schema_format == "protobuf":
            if not self.entrypoint or not self.files or self.schema_content is not None:
                raise ValueError("Protobuf 事件 Schema 必须提供 entrypoint 和 files")
        elif self.schema_content is None or self.entrypoint is not None or self.files:
            raise ValueError("Avro/JSON Schema 必须且只能提供 schema")
        return self


class RegistrySchemaImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: EventSourceName
    description: str = Field(default="", max_length=4000)
    subject: str = Field(min_length=1, max_length=512)
    version: int | Literal["latest"] = "latest"
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class KafkaProduceDebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    topic: str = Field(pattern=r"^[A-Za-z0-9._-]+$", min_length=1, max_length=249)
    value: JsonValue
    key: str | None = Field(default=None, max_length=8_192)
    headers: dict[str, str] = Field(default_factory=dict)
    correlation_header: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=512)
    schema_id: UUID | None = None
    message_type: str | None = Field(default=None, max_length=512)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class KafkaConsumeDebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    topic: str = Field(pattern=r"^[A-Za-z0-9._-]+$", min_length=1, max_length=249)
    offset: Literal["earliest", "latest"] = "latest"
    maximum_messages: int = Field(default=1, ge=1, le=1000)
    correlation_header: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=512)
    schema_id: UUID | None = None
    message_type: str | None = Field(default=None, max_length=512)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class WebSocketExchangeDebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    payload_kind: Literal["json", "text"] = "json"
    message: JsonValue
    headers: dict[str, str] = Field(default_factory=dict)
    subprotocols: list[str] = Field(default_factory=list, max_length=10)
    correlation_expression: str | None = Field(default=None, max_length=500)
    correlation_value: JsonValue = None
    maximum_messages: int = Field(default=1, ge=1, le=1000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class EventDebugResponse(BaseModel):
    output: JsonValue
    duration_ms: int = Field(ge=0)
