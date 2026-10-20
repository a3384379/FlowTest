import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from graphql import build_schema, get_variable_values, parse
from graphql.language import OperationDefinitionNode

from app.domain.graphql_structure import inspect_graphql
from app.domain.grpc_structure import inspect_grpc
from app.domain.protocol_structure import StructureNodeNotFound
from app.domain.protocols import (
    ProtocolSchemaError,
    ProtoSourceFile,
    compile_proto_sources,
    validate_graphql_operation,
)

SDL = b"""schema { query: ReadRoot mutation: WriteRoot subscription: StreamRoot }
scalar Date
input Filter { id: ID! optional: Int! = 3 nested: Filter }
enum Choice { FIRST SECOND }
type ReadRoot {
 item(filter: Filter!, choice: Choice!, optional: String): User!
 date(at: Date!): String
}
type WriteRoot { rename(id: ID!): Boolean! }
type StreamRoot { updates: User }
type User { id: ID! name: String friend: User }
"""
PROTO = """syntax = "proto3"; package audit;
service Orders { rpc Get(Input) returns (Output); rpc Watch(Input) returns (stream Output); }
message Input {
 string order_id = 1; repeated int32 ids = 2; map<string,string> labels = 3;
 Choice choice = 4; oneof selected { string first = 5; int32 second = 6; }
}
message Output {
 string id = 1; message Nested { bool value = 1; } Nested nested = 2;
}
enum Choice { NONE = 0; FIRST = 1; }
"""


def descriptor() -> bytes:
    return compile_proto_sources(
        [ProtoSourceFile("orders.proto", PROTO)], entrypoint="orders.proto"
    ).canonical_content


def test_graphql_actual_roots_fields_requiredness_and_legal_sample() -> None:
    root = inspect_graphql(SDL, "root", 0, 25)
    assert [(item.label, item.type_label) for item in root.entries[:3]] == [
        ("query", "ReadRoot"),
        ("mutation", "WriteRoot"),
        ("subscription", "StreamRoot"),
    ]
    assert "不支持" in root.entries[2].description
    fields = inspect_graphql(SDL, "operation:query", 0, 1)
    assert fields.total == 2 and len(fields.entries) == 1
    field = inspect_graphql(SDL, "field:ReadRoot.item", 0, 25)
    assert field.example and field.example.operation and field.example.variables
    validate_graphql_operation(SDL, field.example.operation)
    schema = build_schema(SDL.decode())
    operation = parse(field.example.operation).definitions[0]
    assert isinstance(operation, OperationDefinitionNode)
    assert isinstance(
        get_variable_values(schema, operation.variable_definitions or (), field.example.variables),
        dict,
    )
    assert field.example.variables == {"filter": {"id": "example-id"}, "choice": "FIRST"}
    assert [(item.label, item.required) for item in field.entries] == [
        ("filter", True),
        ("choice", True),
        ("optional", False),
        ("返回类型", False),
    ]
    inputs = inspect_graphql(SDL, "type:Filter", 0, 25)
    assert [item.required for item in inputs.entries] == [True, False, False]
    assert inspect_graphql(SDL, "type:Choice", 0, 25).entries[0].label == "FIRST"
    assert inspect_graphql(SDL, "type:ID", 0, 25).total == 0
    assert inspect_graphql(SDL, "types", 0, 2).total > 2
    assert inspect_graphql(SDL, "field:User.friend", 0, 25).example is None
    assert inspect_graphql(SDL, "field:StreamRoot.updates", 0, 25).example is None
    assert inspect_graphql(SDL, "field:WriteRoot.rename", 0, 25).example.operation.startswith(
        "mutation"
    )


def test_graphql_custom_scalar_recursive_and_deep_inputs_do_not_claim_complete_examples() -> None:
    custom = inspect_graphql(SDL, "field:ReadRoot.date", 0, 25)
    assert custom.example is None and "自定义标量" in (custom.notice or "")
    with pytest.raises(ProtocolSchemaError):
        inspect_graphql(
            b"input Loop { next: Loop! } type Query { read(loop: Loop!): ID }",
            "field:Query.read",
            0,
            25,
        )
    for content in [
        b"input A { child: B! } input B { child: C! } input C { child: D! } "
        b"input D { child: E! } input E { child: F! } input F { child: G! } "
        b"input G { id: ID! } type Query { read(input: A!): ID }",
    ]:
        result = inspect_graphql(content, "field:Query.read", 0, 25)
        assert result.example is None and result.notice
    large = (
        "input Many { "
        + " ".join(f"f{i}: Int!" for i in range(105))
        + " } type Query { read(input: Many!): ID }"
    ).encode()
    assert inspect_graphql(large, "field:Query.read", 0, 25).example is None
    with pytest.raises(ProtocolSchemaError):
        inspect_graphql(b"type Broken {", "root", 0, 25)
    with pytest.raises(ProtocolSchemaError):
        inspect_graphql(b"x" * (2 * 1024 * 1024 + 1), "root", 0, 25)


@pytest.mark.parametrize(
    "node",
    [
        "operation:missing",
        "type:Absent",
        "field:ReadRoot.absent",
        "field:bad",
        "unknown",
        "type:__Schema",
    ],
)
def test_graphql_missing_paths_are_explicit(node: str) -> None:
    with pytest.raises(StructureNodeNotFound):
        inspect_graphql(SDL, node, 0, 25)


def test_grpc_service_method_types_and_valid_json_sample() -> None:
    content = descriptor()
    root = inspect_grpc(content, "root", 0, 2)
    assert root.total == 4 and len(root.entries) == 2
    methods = inspect_grpc(content, "service:audit.Orders", 0, 25)
    assert [item.type_label for item in methods.entries] == ["unary", "server_streaming"]
    result = inspect_grpc(content, "method:audit.Orders/Get", 0, 25)
    assert result.example and result.example.request is not None
    assert [item.type_label for item in result.entries] == ["audit.Input", "audit.Output"]
    pool = descriptor_pool.DescriptorPool()
    for file in descriptor_pb2.FileDescriptorSet.FromString(content).file:
        pool.AddSerializedFile(file.SerializeToString())
    request = message_factory.GetMessageClass(pool.FindMessageTypeByName("audit.Input"))()
    json_format.ParseDict(result.example.request, request)
    assert result.example.request["orderId"] == ""
    assert "second" not in result.example.request
    assert (
        inspect_grpc(content, "method:audit.Orders/Watch", 0, 25).example.call_type
        == "server_streaming"
    )
    fields = inspect_grpc(content, "message:audit.Input", 0, 25)
    assert fields.entries[0].label == "orderId" and fields.entries[0].type_label == "string"
    assert fields.entries[1].type_label == "int32 repeated"
    assert "map<" in fields.entries[2].type_label
    assert "oneof" in fields.entries[4].description
    assert inspect_grpc(content, "message:audit.Output", 0, 25).entries[-1].label == "Nested"
    assert inspect_grpc(content, "enum:audit.Choice", 0, 25).entries[0].label == "NONE"


def test_grpc_unsupported_stream_recursive_inputs_and_broken_contract_are_honest() -> None:
    document = descriptor_pb2.FileDescriptorSet.FromString(descriptor())
    document.file[0].service[0].method[0].client_streaming = True
    content = document.SerializeToString()
    assert "不支持" in inspect_grpc(content, "service:audit.Orders", 0, 25).entries[0].type_label
    result = inspect_grpc(content, "method:audit.Orders/Get", 0, 25)
    assert result.example is None and "不支持" in (result.notice or "")
    recursive = compile_proto_sources(
        [
            ProtoSourceFile(
                "loop.proto",
                'syntax="proto3"; service S { rpc Get(Loop) returns(Loop); } '
                "message Loop { Loop next = 1; }",
            )
        ],
        entrypoint="loop.proto",
    )
    assert inspect_grpc(recursive.canonical_content, "method:S/Get", 0, 25).example is None
    for content in [b"", b"broken", descriptor_pb2.FileDescriptorSet().SerializeToString()]:
        with pytest.raises(ProtocolSchemaError):
            inspect_grpc(content, "root", 0, 25)
    with pytest.raises(StructureNodeNotFound):
        inspect_grpc(descriptor(), "message:absent", 0, 25)
    with pytest.raises(StructureNodeNotFound):
        inspect_grpc(descriptor(), "unknown", 0, 25)


def test_graphql_error_path_resolves_alias_and_fragment_to_actual_custom_root() -> None:
    from app.domain.graphql_structure import locate_graphql_error_root

    operation = (
        "query Pick($id: ID!) { ...RootFields } "
        "fragment RootFields on ReadRoot { alias: item(filter: {id: $id}, choice: FIRST) { id } }"
    )
    assert (
        locate_graphql_error_root(SDL, operation, "Pick", ["alias", 0, "id"])
        == "field:ReadRoot.item"
    )
    assert (
        locate_graphql_error_root(SDL, 'mutation { changed: rename(id: "42") }', None, ["changed"])
        == "field:WriteRoot.rename"
    )
    for path in [[], [0], ["absent"]]:
        with pytest.raises(ProtocolSchemaError):
            locate_graphql_error_root(SDL, operation, "Pick", path)
    with pytest.raises(ProtocolSchemaError):
        locate_graphql_error_root(SDL, operation, "Unknown", ["alias"])


def test_error_root_location_bounds_tokens_and_fragment_traversal_without_execution_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import protocols
    from app.domain.graphql_structure import locate_graphql_error_root

    def forbidden(*args: object, **kwargs: object) -> str:
        raise AssertionError("Root location must not expand/validate a complete execution")

    monkeypatch.setattr(protocols, "validate_graphql_operation", forbidden)
    fragments = [
        'fragment F0 on ReadRoot { alias: item(filter: {id: "42"}, choice: FIRST) { id } }'
    ]
    fragments.extend(
        f"fragment F{i} on ReadRoot {{ ...F{i - 1} ...F{i - 1} }}" for i in range(1, 24)
    )
    operation = "query { ...F23 } " + " ".join(fragments)
    assert locate_graphql_error_root(SDL, operation, None, ["alias", "id"]) == "field:ReadRoot.item"
    for operation in [
        "query { ...F } fragment F on ReadRoot { ...F }",
        "query { ...Missing }",
        "{ " + " date " * 26000 + " }",
    ]:
        with pytest.raises(ProtocolSchemaError):
            locate_graphql_error_root(SDL, operation, None, ["alias"])


@pytest.mark.parametrize(
    "operation",
    [
        "query Pick { alias: a } query Pick { alias: b }",
        "query Pick { ...F } fragment F on Query { alias: a } fragment F on Query { alias: b }",
    ],
)
def test_error_root_does_not_guess_between_duplicate_operation_or_fragment_names(
    operation: str,
) -> None:
    from app.domain.graphql_structure import locate_graphql_error_root

    with pytest.raises(ProtocolSchemaError):
        locate_graphql_error_root(
            b"type Query { a: String b: String }", operation, "Pick", ["alias"]
        )


def test_invalid_stored_schema_does_not_generate_a_claimed_legal_sample() -> None:
    with pytest.raises(ProtocolSchemaError):
        inspect_graphql(
            b"enum Empty type Query { read(value: Empty!): String }", "field:Query.read", 0, 25
        )
