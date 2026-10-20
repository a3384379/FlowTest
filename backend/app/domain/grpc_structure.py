from typing import cast

from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.descriptor import Descriptor, EnumDescriptor, FieldDescriptor, MethodDescriptor
from google.protobuf.message import DecodeError
from pydantic import JsonValue

from app.domain.protocol_structure import (
    InputExample,
    StructureEntry,
    StructureNodeNotFound,
    StructureView,
    check_structure_size,
    structure_page,
)
from app.domain.protocols import MAX_PROTO_FILES, ProtocolSchemaError


def inspect_grpc(content: bytes, node: str, offset: int, limit: int) -> StructureView:
    check_structure_size(content)
    try:
        pool, files = _pool(content)
        return _inspect(pool, files, node, offset, limit)
    except (DecodeError, TypeError, RecursionError) as error:
        raise ProtocolSchemaError("存储的Descriptor无法解析或依赖不完整") from error
    except KeyError as error:
        raise StructureNodeNotFound("Descriptor路径不存在") from error


def _pool(
    content: bytes,
) -> tuple[descriptor_pool.DescriptorPool, list[descriptor_pb2.FileDescriptorProto]]:
    document = descriptor_pb2.FileDescriptorSet.FromString(content)
    if not 1 <= len(document.file) <= MAX_PROTO_FILES:
        raise ProtocolSchemaError("Descriptor文件数超出1到50的浏览上限")
    _check_descriptor_shape(list(document.file))
    pool = descriptor_pool.DescriptorPool()
    pending = list(document.file)
    while pending:
        previous = len(pending)
        for item in tuple(pending):
            try:
                pool.AddSerializedFile(item.SerializeToString())  # type: ignore[no-untyped-call]
            except TypeError:
                continue
            pending.remove(item)
        if len(pending) == previous:
            raise ProtocolSchemaError("Descriptor依赖不完整,无法浏览结构")
    return pool, list(document.file)


def _check_descriptor_shape(files: list[descriptor_pb2.FileDescriptorProto]) -> None:
    if sum(len(file.service) for file in files) > 1000:
        raise ProtocolSchemaError("Descriptor服务数量超过1000项浏览上限")
    pending = [message for file in files for message in file.message_type]
    messages = fields = 0
    while pending:
        message = pending.pop()
        messages += 1
        fields += len(message.field)
        if messages > 10000 or fields > 50000:
            raise ProtocolSchemaError("Descriptor消息或字段数量超过浏览上限")
        pending.extend(message.nested_type)


def _inspect(
    pool: descriptor_pool.DescriptorPool,
    files: list[descriptor_pb2.FileDescriptorProto],
    node: str,
    offset: int,
    limit: int,
) -> StructureView:
    if node == "root":
        entries: list[StructureEntry] = []
        for file in files:
            prefix = f"{file.package}." if file.package else ""
            entries.extend(
                StructureEntry(
                    f"service:{prefix}{item.name}",
                    f"{prefix}{item.name}",
                    "service",
                    expandable=True,
                )
                for item in file.service
            )
            entries.extend(
                StructureEntry(
                    f"message:{prefix}{item.name}",
                    f"{prefix}{item.name}",
                    "message",
                    expandable=True,
                )
                for item in file.message_type
            )
            entries.extend(
                StructureEntry(
                    f"enum:{prefix}{item.name}", f"{prefix}{item.name}", "enum", expandable=True
                )
                for item in file.enum_type
            )
        return structure_page(node, "gRPC契约", entries, offset, limit)
    kind, _, name = node.partition(":")
    if kind == "service":
        service = pool.FindServiceByName(name)  # type: ignore[no-untyped-call]
        entries = [
            StructureEntry(
                f"method:{service.full_name}/{method.name}",
                method.name,
                "method",
                _call_type(method),
                expandable=True,
            )
            for method in service.methods
        ]
        return structure_page(node, name, entries, offset, limit)
    if kind == "method":
        return _method(pool, node, name, offset, limit)
    if kind == "message":
        message = pool.FindMessageTypeByName(name)  # type: ignore[no-untyped-call]
        entries = [_field(field) for field in message.fields]
        entries.extend(
            StructureEntry(f"message:{item.full_name}", item.name, "message", expandable=True)
            for item in message.nested_types
            if not item.GetOptions().map_entry
        )
        entries.extend(
            StructureEntry(f"enum:{item.full_name}", item.name, "enum", expandable=True)
            for item in message.enum_types
        )
        return structure_page(node, name, entries, offset, limit)
    if kind == "enum":
        enum = pool.FindEnumTypeByName(name)  # type: ignore[no-untyped-call]
        entries = [
            StructureEntry(f"value:{item.name}", item.name, "value", str(item.number))
            for item in enum.values
        ]
        return structure_page(node, name, entries, offset, limit)
    raise StructureNodeNotFound("Descriptor路径不存在")


def _call_type(method: MethodDescriptor) -> str:
    if method.client_streaming:
        return (
            "bidi_streaming(不支持调试)"
            if method.server_streaming
            else "client_streaming(不支持调试)"
        )
    return "server_streaming" if method.server_streaming else "unary"


def _method(
    pool: descriptor_pool.DescriptorPool, node: str, name: str, offset: int, limit: int
) -> StructureView:
    service_name, _, method_name = name.rpartition("/")
    service = pool.FindServiceByName(service_name)  # type: ignore[no-untyped-call]
    method = service.methods_by_name[method_name]
    entries = [
        StructureEntry(
            f"message:{method.input_type.full_name}",
            "请求类型",
            "input",
            method.input_type.full_name,
            expandable=True,
        ),
        StructureEntry(
            f"message:{method.output_type.full_name}",
            "响应类型",
            "output",
            method.output_type.full_name,
            expandable=True,
        ),
    ]
    if method.client_streaming:
        return structure_page(
            node,
            name,
            entries,
            offset,
            limit,
            notice="当前不支持Client/Bidi Streaming调试,可只读浏览。",
        )
    try:
        sample = _message_sample(method.input_type, (), [100])
    except ProtocolSchemaError as error:
        return structure_page(node, name, entries, offset, limit, notice=str(error))
    example = InputExample(
        service=service_name,
        method=method_name,
        call_type="server_streaming" if method.server_streaming else "unary",
        request=sample,
    )
    return structure_page(
        node,
        name,
        entries,
        offset,
        limit,
        example=example,
        notice="样例只保证契约结构;请填写业务数据后手动执行。",
    )


def _field(field: FieldDescriptor) -> StructureEntry:
    if field.message_type is not None:
        target = f"message:{field.message_type.full_name}"
        type_name = field.message_type.full_name
        if field.message_type.GetOptions().map_entry:
            key_type = _scalar_type(field.message_type.fields_by_name["key"])
            value_type = _field_type(field.message_type.fields_by_name["value"])
            type_name = f"map<{key_type}, {value_type}>"
    elif field.enum_type is not None:
        target, type_name = f"enum:{field.enum_type.full_name}", field.enum_type.full_name
    else:
        target, type_name = f"field:{field.full_name}", _scalar_type(field)
    modifier = " repeated" if field.is_repeated else ""
    oneof = f";oneof {field.containing_oneof.name}" if field.containing_oneof else ""
    return StructureEntry(
        target,
        _json_field_name(field),
        "field",
        type_name + modifier,
        field.is_required,
        f"Proto字段:{field.name}{oneof}",
        field.message_type is not None or field.enum_type is not None,
    )


def _field_type(field: FieldDescriptor) -> str:
    if field.message_type:
        return cast(str, field.message_type.full_name)
    if field.enum_type:
        return cast(str, field.enum_type.full_name)
    return _scalar_type(field)


def _scalar_type(field: FieldDescriptor) -> str:
    return descriptor_pb2.FieldDescriptorProto.Type.Name(field.type).removeprefix("TYPE_").lower()


def _message_sample(
    message: Descriptor, path: tuple[str, ...], budget: list[int]
) -> dict[str, JsonValue]:
    if message.full_name in path or len(path) >= 5:
        raise ProtocolSchemaError("输入包含递归或深嵌套,无法生成完整样例,请按字段手工填写。")
    if (
        message.full_name.startswith("google.protobuf.")
        and message.full_name != "google.protobuf.Empty"
    ):
        raise ProtocolSchemaError("该Well-Known类型需按Protobuf JSON格式手工填写。")
    result: dict[str, JsonValue] = {}
    chosen: set[str] = set()
    for field in message.fields:
        if field.containing_oneof:
            if field.containing_oneof.name in chosen:
                continue
            chosen.add(field.containing_oneof.name)
        budget[0] -= 1
        if budget[0] < 0:
            raise ProtocolSchemaError("输入字段超过100项样例上限,请按字段手工填写。")
        result[_json_field_name(field)] = _sample_value(field, (*path, message.full_name), budget)
    return result


def _sample_value(field: FieldDescriptor, path: tuple[str, ...], budget: list[int]) -> JsonValue:
    if field.message_type and field.message_type.GetOptions().map_entry:
        return {}
    if field.is_repeated:
        return []
    if field.message_type:
        return _message_sample(field.message_type, path, budget)
    if field.enum_type:
        return _enum_sample(field.enum_type)
    if field.type in (FieldDescriptor.TYPE_STRING, FieldDescriptor.TYPE_BYTES):
        return ""
    if field.type == FieldDescriptor.TYPE_BOOL:
        return False
    return 0


def _enum_sample(enum: EnumDescriptor) -> str:
    return cast(str, enum.values[0].name)


def _json_field_name(field: FieldDescriptor) -> str:
    return cast(str, getattr(field, "json_name", field.name))
