from typing import cast

from graphql import (
    GraphQLEnumType,
    GraphQLError,
    GraphQLInputObjectType,
    GraphQLInputType,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLUnionType,
    Undefined,
    build_schema,
    get_named_type,
    is_composite_type,
)
from pydantic import JsonValue

from app.domain.protocol_structure import (
    InputExample,
    StructureEntry,
    StructureNodeNotFound,
    StructureView,
    check_structure_size,
    structure_page,
)
from app.domain.protocols import MAX_GRAPHQL_FIELDS, MAX_GRAPHQL_TYPES, ProtocolSchemaError


def inspect_graphql(content: bytes, node: str, offset: int, limit: int) -> StructureView:
    check_structure_size(content)
    try:
        schema = build_schema(content.decode())
        return _inspect_schema(schema, node, offset, limit)
    except (GraphQLError, UnicodeDecodeError, TypeError, RecursionError) as error:
        raise ProtocolSchemaError("存储的GraphQL契约无法解析,请核对导入版本") from error


def _inspect_schema(schema: GraphQLSchema, node: str, offset: int, limit: int) -> StructureView:
    public = [item for name, item in schema.type_map.items() if not name.startswith("__")]
    if (
        len(public) > MAX_GRAPHQL_TYPES
        or sum(len(getattr(item, "fields", {})) for item in public) > MAX_GRAPHQL_FIELDS
    ):
        raise ProtocolSchemaError("GraphQL契约结构超过平台上限")
    if node == "root":
        return structure_page(node, "GraphQL契约", _roots(schema), offset, limit)
    if node == "types":
        entries = [
            StructureEntry(f"type:{item.name}", item.name, "type", expandable=True)
            for item in sorted(public, key=lambda item: item.name)
        ]
        return structure_page(node, "全部类型", entries, offset, limit)
    if node.startswith("operation:"):
        return _operation(schema, node, offset, limit)
    if node.startswith("type:"):
        return _type(schema, node, offset, limit)
    if node.startswith("field:"):
        return _field(schema, node, offset, limit)
    raise StructureNodeNotFound("契约路径不存在")


def _roots(schema: GraphQLSchema) -> list[StructureEntry]:
    roots = [
        ("query", schema.query_type),
        ("mutation", schema.mutation_type),
        ("subscription", schema.subscription_type),
    ]
    result = [
        StructureEntry(
            f"operation:{kind}",
            kind,
            "operation",
            root.name,
            description="当前不支持Subscription调试" if kind == "subscription" else "",
            expandable=True,
        )
        for kind, root in roots
        if root
    ]
    result.append(StructureEntry("types", "全部类型", "group", expandable=True))
    return result


def _operation(schema: GraphQLSchema, node: str, offset: int, limit: int) -> StructureView:
    kind = node.removeprefix("operation:")
    roots = {
        "query": schema.query_type,
        "mutation": schema.mutation_type,
        "subscription": schema.subscription_type,
    }
    root = roots.get(kind)
    if root is None:
        raise StructureNodeNotFound("操作类型不存在")
    entries = [
        StructureEntry(
            f"field:{root.name}.{name}",
            name,
            "field",
            str(field.type),
            description=(field.description or "")[:2000],
            expandable=True,
        )
        for name, field in sorted(root.fields.items())
    ]
    return structure_page(node, f"{kind} · {root.name}", entries, offset, limit)


def _type(schema: GraphQLSchema, node: str, offset: int, limit: int) -> StructureView:
    name = node.removeprefix("type:")
    value = schema.get_type(name)
    if value is None or name.startswith("__"):
        raise StructureNodeNotFound("类型不存在")
    entries: list[StructureEntry] = []
    if isinstance(value, (GraphQLObjectType, GraphQLInterfaceType)):
        entries = [
            StructureEntry(
                f"field:{name}.{key}",
                key,
                "field",
                str(field.type),
                description=(field.description or "")[:2000],
                expandable=True,
            )
            for key, field in sorted(value.fields.items())
        ]
    elif isinstance(value, GraphQLInputObjectType):
        entries = [
            _input_entry(key, field.type, field.default_value, field.description)
            for key, field in sorted(value.fields.items())
        ]
    elif isinstance(value, GraphQLEnumType):
        entries = [
            StructureEntry(
                f"enum:{name}.{key}", key, "enum", description=(item.description or "")[:2000]
            )
            for key, item in value.values.items()
        ]
    elif isinstance(value, GraphQLUnionType):
        entries = [
            StructureEntry(f"type:{item.name}", item.name, "type", expandable=True)
            for item in value.types
        ]
    return structure_page(
        node, name, entries, offset, limit, notice=(value.description or "")[:2000] or None
    )


def _input_entry(
    name: str, value: GraphQLInputType, default: object, description: str | None
) -> StructureEntry:
    named = get_named_type(value)
    return StructureEntry(
        f"type:{named.name}",
        name,
        "input",
        str(value),
        isinstance(value, GraphQLNonNull) and default is Undefined,
        (description or "")[:2000],
        True,
    )


def _field(schema: GraphQLSchema, node: str, offset: int, limit: int) -> StructureView:
    path = node.removeprefix("field:").rsplit(".", 1)
    owner = schema.get_type(path[0])
    if (
        len(path) != 2
        or not isinstance(owner, (GraphQLObjectType, GraphQLInterfaceType))
        or path[1] not in owner.fields
    ):
        raise StructureNodeNotFound("字段不存在")
    field = owner.fields[path[1]]
    entries = [
        _input_entry(name, arg.type, arg.default_value, arg.description)
        for name, arg in field.args.items()
    ]
    output = get_named_type(field.type)
    entries.append(
        StructureEntry(
            f"type:{output.name}", "返回类型", "output", str(field.type), expandable=True
        )
    )
    example, notice = _field_example(schema, owner.name, path[1])
    return structure_page(
        node, f"{owner.name}.{path[1]}", entries, offset, limit, example=example, notice=notice
    )


def _field_example(
    schema: GraphQLSchema, owner: str, name: str
) -> tuple[InputExample | None, str | None]:
    roots = [("query", schema.query_type), ("mutation", schema.mutation_type)]
    kind = next((kind for kind, root in roots if root is not None and root.name == owner), None)
    if kind is None:
        return None, "仅Query/Mutation根字段可填入操作;其他类型用于结构浏览。"
    root = cast(GraphQLObjectType, schema.get_type(owner))
    field = root.fields[name]
    variables: dict[str, JsonValue] = {}
    definitions: list[str] = []
    arguments: list[str] = []
    try:
        budget = [100]
        for key, arg in field.args.items():
            if isinstance(arg.type, GraphQLNonNull) and arg.default_value is Undefined:
                variables[key] = _sample_input(arg.type, (), budget)
                definitions.append(f"${key}: {arg.type}")
                arguments.append(f"{key}: ${key}")
    except ProtocolSchemaError as error:
        return None, str(error)
    params = f"({', '.join(definitions)})" if definitions else ""
    args = f"({', '.join(arguments)})" if arguments else ""
    selection = " { __typename }" if is_composite_type(get_named_type(field.type)) else ""
    return InputExample(
        operation=f"{kind} FlowTestExample{params} {{ {name}{args}{selection} }}",
        variables=variables,
    ), "样例只保证契约结构;请填写业务数据后手动执行。"


def _sample_input(value: GraphQLInputType, path: tuple[str, ...], budget: list[int]) -> JsonValue:
    budget[0] -= 1
    if budget[0] < 0 or len(path) > 5:
        raise ProtocolSchemaError("输入嵌套过深或字段过多,无法生成完整样例,请按字段手工填写。")
    if isinstance(value, GraphQLNonNull):
        return _sample_input(value.of_type, path, budget)
    if isinstance(value, GraphQLList):
        return []
    if isinstance(value, GraphQLEnumType):
        return next(iter(value.values))
    if isinstance(value, GraphQLInputObjectType):
        if value.name in path:
            raise ProtocolSchemaError("必填输入包含递归,无法生成完整样例。")
        return {
            key: _sample_input(field.type, (*path, value.name), budget)
            for key, field in value.fields.items()
            if isinstance(field.type, GraphQLNonNull) and field.default_value is Undefined
        }
    if not isinstance(value, GraphQLScalarType):
        raise ProtocolSchemaError("输入类型无法生成样例")
    return _sample_scalar(value)


def _sample_scalar(value: GraphQLScalarType) -> JsonValue:
    samples: dict[str, JsonValue] = {
        "String": "example",
        "ID": "example-id",
        "Int": 1,
        "Float": 1.0,
        "Boolean": False,
    }
    if value.name not in samples:
        raise ProtocolSchemaError(f"自定义标量{value.name}未提供合法示例,请手工填写。")
    return samples[value.name]


def _locate_graphql_error_root(
    content: bytes, operation: str, operation_name: str | None, path: list[str | int]
) -> str:
    """Resolve a response alias to its actual root field without executing the operation."""
    from graphql import get_operation_ast, parse
    from graphql.language import (
        FieldNode,
        FragmentDefinitionNode,
        FragmentSpreadNode,
        InlineFragmentNode,
    )

    from app.domain.protocols import validate_graphql_operation

    validate_graphql_operation(content, operation)
    document = parse(operation)
    selected = get_operation_ast(document, operation_name)
    if selected is None or not path or not isinstance(path[0], str):
        raise ProtocolSchemaError("无法唯一定位操作或错误路径,请核对Operation Name与响应。")
    schema = build_schema(content.decode())
    roots = {"query": schema.query_type, "mutation": schema.mutation_type}
    root = roots.get(selected.operation.value)
    if root is None:
        raise ProtocolSchemaError("当前操作没有可定位的根类型")
    fragments = {
        item.name.value: item
        for item in document.definitions
        if isinstance(item, FragmentDefinitionNode)
    }
    stack = list(selected.selection_set.selections)
    names: set[str] = set()
    visited: set[str] = set()
    while stack:
        item = stack.pop()
        if isinstance(item, FieldNode) and (item.alias or item.name).value == path[0]:
            names.add(item.name.value)
        elif isinstance(item, InlineFragmentNode):
            stack.extend(item.selection_set.selections)
        elif isinstance(item, FragmentSpreadNode) and item.name.value not in visited:
            visited.add(item.name.value)
            stack.extend(fragments[item.name.value].selection_set.selections)
    if len(names) != 1 or next(iter(names)) not in root.fields:
        raise ProtocolSchemaError("错误根字段无法唯一定位,请对照操作与契约。")
    return f"field:{root.name}.{next(iter(names))}"


def locate_graphql_error_root(
    content: bytes, operation: str, operation_name: str | None, path: list[str | int]
) -> str:
    check_structure_size(content)
    try:
        return _locate_graphql_error_root(content, operation, operation_name, path)
    except (GraphQLError, UnicodeDecodeError, TypeError, RecursionError) as error:
        raise ProtocolSchemaError("操作或存储契约无法解析,不能定位错误字段。") from error
