import hashlib
import json
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import cast

from fastavro import parse_schema
from jsonschema import Draft202012Validator, SchemaError

from app.domain.protocols import (
    MAX_SCHEMA_BYTES,
    ProtocolKind,
    ProtocolSchemaError,
    ProtoSourceFile,
    SchemaSourceFormat,
    ValidatedSchema,
    compile_proto_sources,
)

MAX_EVENT_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_EVENT_MESSAGES = 1_000
MAX_EVENT_WAIT_SECONDS = 300
MAX_KAFKA_BOOTSTRAP_SERVERS = 10
MAX_WEBSOCKET_SUBPROTOCOLS = 10

_HOST_PORT = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\]):[1-9]\d{0,4}$"
)


class EventSourceKind(StrEnum):
    KAFKA = "kafka"
    WEBSOCKET = "websocket"


class EventSchemaFormat(StrEnum):
    AVRO = "avro"
    JSON_SCHEMA = "json_schema"
    PROTOBUF = "protobuf"


class KafkaOffset(StrEnum):
    EARLIEST = "earliest"
    LATEST = "latest"


class WebSocketPayloadKind(StrEnum):
    JSON = "json"
    TEXT = "text"


def validate_bootstrap_servers(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if not 1 <= len(normalized) <= MAX_KAFKA_BOOTSTRAP_SERVERS:
        raise ValueError("Kafka Bootstrap Server 数量必须在 1 到 10 之间")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Kafka Bootstrap Server 不能重复")
    if any(_HOST_PORT.fullmatch(value) is None for value in normalized):
        raise ValueError("Kafka Bootstrap Server 必须使用 host:port")
    if any(int(value.rsplit(":", 1)[1]) > 65_535 for value in normalized):
        raise ValueError("Kafka Bootstrap Server 端口无效")
    return normalized


def validate_event_schema(
    *,
    schema_format: EventSchemaFormat,
    schema: str | None = None,
    proto_files: tuple[ProtoSourceFile, ...] = (),
    entrypoint: str | None = None,
    registry_id: int | None = None,
) -> ValidatedSchema:
    if schema_format is EventSchemaFormat.PROTOBUF:
        compiled = compile_proto_sources(
            proto_files,
            entrypoint=entrypoint or "",
            require_service=False,
        )
        return ValidatedSchema(
            protocol=ProtocolKind.KAFKA,
            source_format=SchemaSourceFormat.EVENT_PROTOBUF,
            canonical_content=compiled.canonical_content,
            source_content=compiled.source_content,
            summary={
                **compiled.summary,
                "event_schema_format": schema_format.value,
                "registry_id": registry_id,
            },
        )
    if schema is None:
        raise ProtocolSchemaError("事件 Schema 内容不能为空")
    encoded = schema.encode()
    if len(encoded) > MAX_SCHEMA_BYTES:
        raise ProtocolSchemaError("事件 Schema 超过 2 MB 上限")
    try:
        document = json.loads(schema)
    except json.JSONDecodeError as error:
        raise ProtocolSchemaError("事件 Schema 不是有效 JSON") from error
    if not isinstance(document, dict):
        raise ProtocolSchemaError("事件 Schema 必须是 JSON 对象")
    try:
        if schema_format is EventSchemaFormat.AVRO:
            parse_schema(document)
            source_format = SchemaSourceFormat.EVENT_AVRO
        else:
            Draft202012Validator.check_schema(document)
            source_format = SchemaSourceFormat.EVENT_JSON_SCHEMA
    except (SchemaError, ValueError, TypeError) as error:
        raise ProtocolSchemaError(f"{schema_format.value} Schema 无效") from error
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return ValidatedSchema(
        protocol=ProtocolKind.KAFKA,
        source_format=source_format,
        canonical_content=canonical,
        source_content=encoded,
        summary={
            "event_schema_format": schema_format.value,
            "registry_id": registry_id,
            "sha256": hashlib.sha256(canonical).hexdigest(),
        },
    )


def event_schema_format(summary: Mapping[str, object]) -> EventSchemaFormat:
    return EventSchemaFormat(cast(str, summary["event_schema_format"]))
