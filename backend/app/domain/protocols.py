import base64
import hashlib
import json
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, cast

from google.protobuf import descriptor_pb2
from graphql import (
    GraphQLError,
    build_client_schema,
    build_schema,
    parse,
    print_schema,
    validate,
)
from graphql.language import OperationDefinitionNode
from graphql.language.ast import FieldNode, FragmentDefinitionNode, FragmentSpreadNode
from grpc_tools import protoc
from pydantic import JsonValue

MAX_SCHEMA_BYTES = 2 * 1024 * 1024
MAX_GRAPHQL_TYPES = 5_000
MAX_GRAPHQL_FIELDS = 50_000
MAX_GRAPHQL_OPERATION_FIELDS = 1_000
MAX_GRAPHQL_OPERATION_DEPTH = 20
MAX_PROTO_FILES = 50
MAX_GRPC_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_GRPC_STREAM_MESSAGES = 1_000
MAX_GRPC_STREAM_BYTES = 50 * 1024 * 1024
MAX_GRPC_STREAM_SECONDS = 300

_PROTO_IMPORT = re.compile(r'\bimport\s+(?:public\s+|weak\s+)?"([^"]+)"\s*;')
_PROTO_PACKAGE_ROOT = Path(protoc.__file__).resolve().parent / "_proto"


class ProtocolKind(StrEnum):
    GRAPHQL = "graphql"
    GRPC = "grpc"
    KAFKA = "kafka"


class SchemaSourceFormat(StrEnum):
    GRAPHQL_SDL = "graphql_sdl"
    GRAPHQL_INTROSPECTION = "graphql_introspection"
    PROTO_SOURCE = "proto_source"
    PROTO_DESCRIPTOR_SET = "proto_descriptor_set"
    GRPC_REFLECTION = "grpc_reflection"
    EVENT_AVRO = "event_avro"
    EVENT_JSON_SCHEMA = "event_json_schema"
    EVENT_PROTOBUF = "event_protobuf"


class GrpcCallType(StrEnum):
    UNARY = "unary"
    SERVER_STREAMING = "server_streaming"


class GrpcTlsMode(StrEnum):
    PLAINTEXT = "plaintext"
    TLS = "tls"
    MTLS = "mtls"


@dataclass(frozen=True, slots=True)
class ValidatedSchema:
    protocol: ProtocolKind
    source_format: SchemaSourceFormat
    canonical_content: bytes
    source_content: bytes
    summary: dict[str, JsonValue]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_content).hexdigest()


@dataclass(frozen=True, slots=True)
class ProtoSourceFile:
    name: str
    content: str


class ProtocolSchemaError(ValueError):
    """Raised when an imported protocol schema violates bounded validation rules."""


def validate_graphql_sdl(content: str) -> ValidatedSchema:
    _check_size(content.encode(), "GraphQL Schema")
    try:
        schema = build_schema(content)
    except GraphQLError as error:
        raise ProtocolSchemaError("GraphQL SDL 无效") from error
    canonical = print_schema(schema).encode()
    summary = _graphql_summary(schema.type_map.values())
    return ValidatedSchema(
        protocol=ProtocolKind.GRAPHQL,
        source_format=SchemaSourceFormat.GRAPHQL_SDL,
        canonical_content=canonical,
        source_content=content.encode(),
        summary=summary,
    )


def validate_graphql_introspection(document: dict[str, JsonValue]) -> ValidatedSchema:
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    _check_size(encoded, "GraphQL Introspection")
    payload = document.get("data", document)
    if not isinstance(payload, dict):
        raise ProtocolSchemaError("GraphQL Introspection 必须是对象")
    try:
        schema = build_client_schema(cast(Any, payload))
    except (GraphQLError, TypeError, KeyError) as error:
        raise ProtocolSchemaError("GraphQL Introspection 无效") from error
    canonical = print_schema(schema).encode()
    summary = _graphql_summary(schema.type_map.values())
    return ValidatedSchema(
        protocol=ProtocolKind.GRAPHQL,
        source_format=SchemaSourceFormat.GRAPHQL_INTROSPECTION,
        canonical_content=canonical,
        source_content=encoded,
        summary=summary,
    )


def validate_graphql_operation(schema_content: bytes, operation: str) -> str:
    _check_size(operation.encode(), "GraphQL Operation")
    try:
        schema = build_schema(schema_content.decode())
        document = parse(operation)
        errors = validate(schema, document)
    except (GraphQLError, UnicodeDecodeError) as error:
        raise ProtocolSchemaError("GraphQL Operation 无效") from error
    if errors:
        raise ProtocolSchemaError(errors[0].message)
    operations = [
        definition
        for definition in document.definitions
        if isinstance(definition, OperationDefinitionNode)
    ]
    if not operations:
        raise ProtocolSchemaError("GraphQL 文档必须包含 Query 或 Mutation")
    if any(operation_node.operation.value == "subscription" for operation_node in operations):
        raise ProtocolSchemaError("V3 暂不支持 GraphQL Subscription")
    fragments = {
        definition.name.value: definition
        for definition in document.definitions
        if isinstance(definition, FragmentDefinitionNode)
    }
    field_count, maximum_depth = _graphql_operation_shape(operations, fragments)
    if field_count > MAX_GRAPHQL_OPERATION_FIELDS:
        raise ProtocolSchemaError("GraphQL Operation 字段数超过 1000")
    if maximum_depth > MAX_GRAPHQL_OPERATION_DEPTH:
        raise ProtocolSchemaError("GraphQL Operation 深度超过 20")
    return operation.strip()


def compile_proto_sources(
    files: Iterable[ProtoSourceFile],
    *,
    entrypoint: str,
    require_service: bool = True,
) -> ValidatedSchema:
    source_files = tuple(files)
    if not 1 <= len(source_files) <= MAX_PROTO_FILES:
        raise ProtocolSchemaError("Proto 文件数量必须在 1 到 50 之间")
    normalized = {_safe_proto_name(item.name): item.content for item in source_files}
    if len(normalized) != len(source_files):
        raise ProtocolSchemaError("Proto 文件名不能重复")
    entry = _safe_proto_name(entrypoint)
    if entry not in normalized:
        raise ProtocolSchemaError("Proto 入口文件不存在")
    total = sum(len(content.encode()) for content in normalized.values())
    if total > MAX_SCHEMA_BYTES:
        raise ProtocolSchemaError("Proto 文件总大小超过 2 MB")
    _validate_proto_imports(normalized)
    with tempfile.TemporaryDirectory(prefix="flowtest-proto-") as directory:
        root = Path(directory)
        for name, content in normalized.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        descriptor_path = root / "schema.protoset"
        arguments = [
            "grpc_tools.protoc",
            f"-I{root}",
            f"-I{_PROTO_PACKAGE_ROOT}",
            f"--descriptor_set_out={descriptor_path}",
            "--include_imports",
            entry,
        ]
        if protoc.main(arguments) != 0:
            raise ProtocolSchemaError("Proto 编译失败")
        descriptor = descriptor_path.read_bytes()
    summary = describe_descriptor_set(descriptor, require_service=require_service)
    source_bundle = json.dumps(
        {"entrypoint": entry, "files": normalized},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return ValidatedSchema(
        protocol=ProtocolKind.GRPC,
        source_format=SchemaSourceFormat.PROTO_SOURCE,
        canonical_content=descriptor,
        source_content=source_bundle,
        summary=summary,
    )


def validate_descriptor_set(encoded: str) -> ValidatedSchema:
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ProtocolSchemaError("Descriptor Set 不是有效的 Base64") from error
    _check_size(content, "Descriptor Set")
    summary = describe_descriptor_set(content)
    return ValidatedSchema(
        protocol=ProtocolKind.GRPC,
        source_format=SchemaSourceFormat.PROTO_DESCRIPTOR_SET,
        canonical_content=content,
        source_content=content,
        summary=summary,
    )


def validate_reflection_descriptor_set(content: bytes, source_content: bytes) -> ValidatedSchema:
    _check_size(content, "Reflection Descriptor Set")
    _check_size(source_content, "Reflection 元数据")
    return ValidatedSchema(
        protocol=ProtocolKind.GRPC,
        source_format=SchemaSourceFormat.GRPC_REFLECTION,
        canonical_content=content,
        source_content=source_content,
        summary=describe_descriptor_set(content),
    )


def describe_descriptor_set(
    content: bytes,
    *,
    require_service: bool = True,
) -> dict[str, JsonValue]:
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    try:
        descriptor_set.ParseFromString(content)
    except Exception as error:
        raise ProtocolSchemaError("Descriptor Set 无效") from error
    if not descriptor_set.file:
        raise ProtocolSchemaError("Descriptor Set 不能为空")
    services: list[dict[str, JsonValue]] = []
    message_count = 0
    for file_descriptor in descriptor_set.file:
        message_count += len(file_descriptor.message_type)
        package_prefix = f"{file_descriptor.package}." if file_descriptor.package else ""
        for service in file_descriptor.service:
            methods = []
            for method in service.method:
                if method.client_streaming:
                    raise ProtocolSchemaError("V3 暂不支持 gRPC Client/Bidi Streaming")
                methods.append(
                    {
                        "name": method.name,
                        "call_type": (
                            GrpcCallType.SERVER_STREAMING.value
                            if method.server_streaming
                            else GrpcCallType.UNARY.value
                        ),
                        "input_type": method.input_type.lstrip("."),
                        "output_type": method.output_type.lstrip("."),
                    }
                )
            services.append(
                {
                    "name": f"{package_prefix}{service.name}",
                    "methods": cast(JsonValue, methods),
                }
            )
    if require_service and not services:
        raise ProtocolSchemaError("Descriptor Set 必须包含至少一个 gRPC Service")
    if len(services) > 1_000 or message_count > 10_000:
        raise ProtocolSchemaError("Descriptor Set 结构超过平台上限")
    return {
        "file_count": len(descriptor_set.file),
        "message_count": message_count,
        "service_count": len(services),
        "services": cast(JsonValue, services),
    }


def _graphql_summary(types: Iterable[object]) -> dict[str, JsonValue]:
    public_types = [item for item in types if not getattr(item, "name", "").startswith("__")]
    field_count = sum(len(getattr(item, "fields", {})) for item in public_types)
    if len(public_types) > MAX_GRAPHQL_TYPES or field_count > MAX_GRAPHQL_FIELDS:
        raise ProtocolSchemaError("GraphQL Schema 结构超过平台上限")
    return {
        "type_count": len(public_types),
        "field_count": field_count,
        "query_type": next(
            (
                getattr(item, "name", "")
                for item in public_types
                if getattr(item, "name", "") == "Query"
            ),
            None,
        ),
        "mutation_type": next(
            (
                getattr(item, "name", "")
                for item in public_types
                if getattr(item, "name", "") == "Mutation"
            ),
            None,
        ),
    }


def _graphql_operation_shape(
    operations: list[OperationDefinitionNode],
    fragments: dict[str, FragmentDefinitionNode],
) -> tuple[int, int]:
    count = 0
    maximum_depth = 0

    def walk(selection_set: object, depth: int, stack: frozenset[str]) -> None:
        nonlocal count, maximum_depth
        selections = getattr(selection_set, "selections", ())
        maximum_depth = max(maximum_depth, depth)
        for selection in selections:
            if isinstance(selection, FieldNode):
                count += 1
                if selection.selection_set is not None:
                    walk(selection.selection_set, depth + 1, stack)
            elif isinstance(selection, FragmentSpreadNode):
                name = selection.name.value
                if name in stack:
                    raise ProtocolSchemaError("GraphQL Fragment 不能递归")
                fragment = fragments.get(name)
                if fragment is not None:
                    walk(fragment.selection_set, depth, stack | {name})
            elif getattr(selection, "selection_set", None) is not None:
                walk(selection.selection_set, depth, stack)

    for operation in operations:
        walk(operation.selection_set, 1, frozenset())
    return count, maximum_depth


def _safe_proto_name(value: str) -> str:
    name = PurePosixPath(value.strip())
    if (
        not value.strip()
        or name.is_absolute()
        or ".." in name.parts
        or name.suffix != ".proto"
        or any(part in {"", "."} for part in name.parts)
    ):
        raise ProtocolSchemaError("Proto 文件名无效")
    return str(name)


def _validate_proto_imports(files: dict[str, str]) -> None:
    known = set(files)
    for content in files.values():
        for imported in _PROTO_IMPORT.findall(content):
            try:
                normalized = _safe_proto_name(imported)
            except ProtocolSchemaError as error:
                raise ProtocolSchemaError(f"Proto Import 不存在或不受信任: {imported}") from error
            if normalized not in known and not normalized.startswith("google/protobuf/"):
                raise ProtocolSchemaError(f"Proto Import 不存在或不受信任: {normalized}")


def _check_size(content: bytes, label: str) -> None:
    if not content:
        raise ProtocolSchemaError(f"{label} 不能为空")
    if len(content) > MAX_SCHEMA_BYTES:
        raise ProtocolSchemaError(f"{label} 超过 2 MB 上限")
