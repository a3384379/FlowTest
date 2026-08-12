import io
import json
import struct
from typing import cast

from fastavro import parse_schema, schemaless_reader, schemaless_writer
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.message import DecodeError, Message
from jsonschema import Draft202012Validator, ValidationError
from pydantic import JsonValue

from app.domain.event_protocols import MAX_EVENT_MESSAGE_BYTES, EventSchemaFormat
from app.engine.scheduler import NodeExecutionError

_CONFLUENT_MAGIC_BYTE = 0


def encode_event_value(
    value: JsonValue,
    *,
    schema_content: bytes | None,
    schema_summary: dict[str, JsonValue] | None,
    message_type: str | None,
) -> bytes:
    if schema_content is None or schema_summary is None:
        encoded = _json_bytes(value)
    else:
        schema_format = EventSchemaFormat(str(schema_summary["event_schema_format"]))
        registry_id = _registry_id(schema_summary)
        if schema_format is EventSchemaFormat.AVRO:
            encoded = _encode_avro(value, schema_content)
        elif schema_format is EventSchemaFormat.JSON_SCHEMA:
            encoded = _encode_json_schema(value, schema_content)
        else:
            encoded = _encode_protobuf(value, schema_content, message_type)
        if registry_id is not None:
            encoded = _confluent_frame(
                registry_id, encoded, protobuf=schema_format is EventSchemaFormat.PROTOBUF
            )
    if len(encoded) > MAX_EVENT_MESSAGE_BYTES:
        raise NodeExecutionError(
            code="EVENT_MESSAGE_TOO_LARGE",
            message="事件消息超过 4 MB 上限",
        )
    return encoded


def decode_event_value(
    payload: bytes,
    *,
    schema_content: bytes | None,
    schema_summary: dict[str, JsonValue] | None,
    message_type: str | None,
) -> JsonValue:
    if len(payload) > MAX_EVENT_MESSAGE_BYTES:
        raise NodeExecutionError(
            code="EVENT_MESSAGE_TOO_LARGE",
            message="事件消息超过 4 MB 上限",
        )
    if schema_content is None or schema_summary is None:
        return _decode_json_or_text(payload)
    schema_format = EventSchemaFormat(str(schema_summary["event_schema_format"]))
    registry_id = _registry_id(schema_summary)
    content = _strip_confluent_frame(
        payload,
        expected_schema_id=registry_id,
        protobuf=schema_format is EventSchemaFormat.PROTOBUF,
    )
    if schema_format is EventSchemaFormat.AVRO:
        return _decode_avro(content, schema_content)
    if schema_format is EventSchemaFormat.JSON_SCHEMA:
        value = _decode_json(content)
        _validate_json_schema(value, schema_content)
        return value
    return _decode_protobuf(content, schema_content, message_type)


def _encode_avro(value: JsonValue, schema_content: bytes) -> bytes:
    try:
        schema = parse_schema(json.loads(schema_content))
        buffer = io.BytesIO()
        schemaless_writer(buffer, schema, value)
        return buffer.getvalue()
    except (ValueError, TypeError, KeyError) as error:
        raise NodeExecutionError(
            code="INVALID_AVRO_MESSAGE",
            message="消息与 Avro Schema 不匹配",
        ) from error


def _decode_avro(payload: bytes, schema_content: bytes) -> JsonValue:
    try:
        schema = parse_schema(json.loads(schema_content))
        return cast(JsonValue, schemaless_reader(io.BytesIO(payload), schema))
    except (ValueError, TypeError, KeyError, EOFError, IndexError) as error:
        raise NodeExecutionError(
            code="INVALID_AVRO_MESSAGE",
            message="Avro 消息无法按固定 Schema 解码",
        ) from error


def _encode_json_schema(value: JsonValue, schema_content: bytes) -> bytes:
    _validate_json_schema(value, schema_content)
    return _json_bytes(value)


def _validate_json_schema(value: JsonValue, schema_content: bytes) -> None:
    try:
        schema = json.loads(schema_content)
        Draft202012Validator(schema).validate(value)
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise NodeExecutionError(
            code="INVALID_JSON_SCHEMA_MESSAGE",
            message="消息与 JSON Schema 不匹配",
        ) from error


def _encode_protobuf(
    value: JsonValue,
    descriptor_content: bytes,
    message_type: str | None,
) -> bytes:
    message_class = _protobuf_message_class(descriptor_content, message_type)
    message = message_class()
    if not isinstance(value, dict):
        raise NodeExecutionError(
            code="INVALID_PROTOBUF_MESSAGE",
            message="Protobuf 消息必须是 JSON 对象",
        )
    try:
        json_format.ParseDict(value, message, ignore_unknown_fields=False)
        return message.SerializeToString()
    except (json_format.ParseError, TypeError) as error:
        raise NodeExecutionError(
            code="INVALID_PROTOBUF_MESSAGE",
            message="消息与 Protobuf Schema 不匹配",
        ) from error


def _decode_protobuf(
    payload: bytes,
    descriptor_content: bytes,
    message_type: str | None,
) -> JsonValue:
    message_class = _protobuf_message_class(descriptor_content, message_type)
    try:
        message = message_class.FromString(payload)
    except DecodeError as error:
        raise NodeExecutionError(
            code="INVALID_PROTOBUF_MESSAGE",
            message="Protobuf 消息无法按固定 Schema 解码",
        ) from error
    return cast(
        JsonValue,
        json_format.MessageToDict(
            message,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        ),
    )


def _protobuf_message_class(
    descriptor_content: bytes,
    message_type: str | None,
) -> type[Message]:
    if not message_type:
        raise NodeExecutionError(
            code="PROTOBUF_MESSAGE_TYPE_REQUIRED",
            message="Protobuf 消息必须指定完整 Message Type",
        )
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    try:
        descriptor_set.ParseFromString(descriptor_content)
        pool = descriptor_pool.DescriptorPool()
        pending = list(descriptor_set.file)
        while pending:
            progressed = False
            for file_descriptor in tuple(pending):
                try:
                    pool.AddSerializedFile(  # type: ignore[no-untyped-call]
                        file_descriptor.SerializeToString()
                    )
                except TypeError:
                    continue
                pending.remove(file_descriptor)
                progressed = True
            if not progressed:
                raise ValueError("Descriptor dependencies are incomplete")
        descriptor = pool.FindMessageTypeByName(message_type)  # type: ignore[no-untyped-call]
        return message_factory.GetMessageClass(descriptor)
    except (DecodeError, KeyError, ValueError) as error:
        raise NodeExecutionError(
            code="PROTOBUF_MESSAGE_TYPE_NOT_FOUND",
            message="固定 Schema 中不存在指定的 Protobuf Message Type",
        ) from error


def _registry_id(summary: dict[str, JsonValue]) -> int | None:
    value = summary.get("registry_id")
    return value if isinstance(value, int) and value > 0 else None


def _confluent_frame(schema_id: int, payload: bytes, *, protobuf: bool) -> bytes:
    framing = struct.pack(">BI", _CONFLUENT_MAGIC_BYTE, schema_id)
    return framing + (b"\x00" if protobuf else b"") + payload


def _strip_confluent_frame(
    payload: bytes,
    *,
    expected_schema_id: int | None,
    protobuf: bool,
) -> bytes:
    if expected_schema_id is None:
        return payload
    minimum = 6 if protobuf else 5
    if len(payload) < minimum or payload[0] != _CONFLUENT_MAGIC_BYTE:
        raise NodeExecutionError(
            code="SCHEMA_REGISTRY_FRAME_MISSING",
            message="消息缺少 Schema Registry Wire Format",
        )
    actual_schema_id = struct.unpack(">I", payload[1:5])[0]
    if actual_schema_id != expected_schema_id:
        raise NodeExecutionError(
            code="SCHEMA_REGISTRY_ID_MISMATCH",
            message="消息 Schema ID 与执行 Snapshot 不一致",
        )
    if protobuf and payload[5] != 0:
        raise NodeExecutionError(
            code="PROTOBUF_MESSAGE_INDEX_UNSUPPORTED",
            message="当前只支持 Registry Schema 的首个 Protobuf Message",
        )
    return payload[minimum:]


def _json_bytes(value: JsonValue) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _decode_json(payload: bytes) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(payload))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NodeExecutionError(
            code="INVALID_JSON_EVENT_MESSAGE",
            message="事件消息不是有效 JSON",
        ) from error


def _decode_json_or_text(payload: bytes) -> JsonValue:
    try:
        decoded = payload.decode()
    except UnicodeDecodeError:
        return {"encoding": "hex", "value": payload.hex()}
    try:
        return cast(JsonValue, json.loads(decoded))
    except json.JSONDecodeError:
        return decoded
