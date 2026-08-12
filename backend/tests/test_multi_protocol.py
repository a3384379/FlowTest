import base64
import json
from collections.abc import AsyncIterator
from uuid import uuid4

import grpc
import httpx
import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from graphql import build_schema
from graphql.utilities import introspection_from_schema
from grpc_reflection.v1alpha import reflection
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.data_nodes import CredentialKind
from app.domain.network import OutboundNetworkPolicy
from app.domain.protocols import (
    GrpcCallType,
    GrpcTlsMode,
    ProtocolKind,
    ProtocolSchemaError,
    ProtoSourceFile,
    compile_proto_sources,
    validate_descriptor_set,
    validate_graphql_introspection,
    validate_graphql_operation,
    validate_graphql_sdl,
    validate_reflection_descriptor_set,
)
from app.engine.contracts import WorkflowNode
from app.engine.protocol_nodes import (
    GraphQLCapabilityConfig,
    GrpcCapabilityConfig,
    PreparedProtocolNode,
    ProtocolCredentialMaterial,
    parse_protocol_config,
    resolve_capability_configuration,
    resolve_protocol_config,
)
from app.engine.scheduler import ExecutionContext, NodeExecutionError
from app.main import app
from app.models import Base
from app.models.access import User
from app.services import grpc_reflection as grpc_reflection_module
from app.services.grpc_reflection import _split_endpoint, fetch_reflection_descriptor
from app.services.protocol_debug import ProtocolDebugService
from app.services.protocol_runtime import (
    ProtocolExecutionResult,
    ProtocolRunner,
    _descriptor_pool,
    _grpc_contract,
    _grpc_metadata,
    _mtls_material,
    _safe_headers,
    build_grpc_channel,
)

ADMIN_EMAIL = "protocol-admin@example.com"
ADMIN_PASSWORD = "protocol-password-123!"

GRAPHQL_SDL = """
type Query { user(id: ID!): User! }
type Mutation { renameUser(id: ID!, name: String!): User! }
type User { id: ID!, name: String! }
"""

PROTO_SOURCE = """
syntax = "proto3";
package flowtest.echo.v1;

service EchoService {
  rpc Echo(EchoRequest) returns (EchoReply);
  rpc Watch(EchoRequest) returns (stream EchoReply);
}

message EchoRequest { string message = 1; }
message EchoReply { string message = 1; int32 sequence = 2; }
"""


class AllowAllGuard:
    async def enforce(self, url: str, policy: OutboundNetworkPolicy) -> tuple[str, ...]:
        del url, policy
        return ("127.0.0.1",)


@pytest.fixture
async def protocol_client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="Protocol administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


def test_graphql_schema_and_operation_are_validated_and_bounded() -> None:
    schema = validate_graphql_sdl(GRAPHQL_SDL)

    operation = validate_graphql_operation(
        schema.canonical_content,
        "query User($id: ID!) { user(id: $id) { id name } }",
    )

    assert operation.startswith("query User")
    assert schema.summary["type_count"] >= 3
    with pytest.raises(ProtocolSchemaError, match="Subscription"):
        validate_graphql_operation(
            validate_graphql_sdl(
                "type Query { ok: Boolean } type Subscription { ping: String }"
            ).canonical_content,
            "subscription { ping }",
        )
    with pytest.raises(ProtocolSchemaError):
        validate_graphql_operation(schema.canonical_content, "query { missing }")


def test_proto_compiler_pins_descriptor_and_rejects_unsafe_imports() -> None:
    compiled = compile_proto_sources(
        [ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE)],
        entrypoint="echo.proto",
    )

    assert compiled.protocol is ProtocolKind.GRPC
    assert compiled.summary["service_count"] == 1
    services = compiled.summary["services"]
    assert isinstance(services, list)
    assert services[0]["name"] == "flowtest.echo.v1.EchoService"
    with pytest.raises(ProtocolSchemaError, match="不受信任"):
        compile_proto_sources(
            [
                ProtoSourceFile(
                    name="unsafe.proto",
                    content='syntax = "proto3"; import "/etc/passwd.proto";',
                )
            ],
            entrypoint="unsafe.proto",
        )


def test_alternative_schema_formats_are_normalized_and_bounded() -> None:
    introspection = introspection_from_schema(build_schema(GRAPHQL_SDL))
    graphql = validate_graphql_introspection(introspection)
    compiled = compile_proto_sources(
        [ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE)],
        entrypoint="echo.proto",
    )
    protoset = validate_descriptor_set(base64.b64encode(compiled.canonical_content).decode())

    assert graphql.summary["mutation_type"] == "Mutation"
    assert protoset.sha256 == compiled.sha256
    with pytest.raises(ProtocolSchemaError, match="SDL 无效"):
        validate_graphql_sdl("not graphql")
    with pytest.raises(ProtocolSchemaError, match="Introspection 必须是对象"):
        validate_graphql_introspection({"data": "invalid"})  # type: ignore[dict-item]
    with pytest.raises(ProtocolSchemaError, match="Introspection 无效"):
        validate_graphql_introspection({"__schema": {}})
    with pytest.raises(ProtocolSchemaError, match="never used"):
        validate_graphql_operation(graphql.canonical_content, "fragment UserFields on User { id }")
    with pytest.raises(ProtocolSchemaError, match="Loop"):
        validate_graphql_operation(
            graphql.canonical_content,
            'query { user(id: "1") { ...Loop } } fragment Loop on User { ...Loop }',
        )
    with pytest.raises(ProtocolSchemaError, match="Base64"):
        validate_descriptor_set("not-base64")
    with pytest.raises(ProtocolSchemaError, match="不能为空"):
        validate_descriptor_set("")


@pytest.mark.parametrize(
    ("files", "entrypoint", "message"),
    [
        ([], "service.proto", "数量"),
        ([ProtoSourceFile(name="../bad.proto", content=PROTO_SOURCE)], "../bad.proto", "文件名"),
        ([ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE)], "missing.proto", "入口"),
        (
            [
                ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE),
                ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE),
            ],
            "echo.proto",
            "重复",
        ),
        (
            [
                ProtoSourceFile(
                    name="echo.proto",
                    content='syntax = "proto3"; import "missing.proto";',
                )
            ],
            "echo.proto",
            "不受信任",
        ),
    ],
)
def test_proto_source_bundle_rejects_invalid_boundaries(
    files: list[ProtoSourceFile],
    entrypoint: str,
    message: str,
) -> None:
    with pytest.raises(ProtocolSchemaError, match=message):
        compile_proto_sources(files, entrypoint=entrypoint)


def test_descriptor_rejects_client_streaming_and_missing_services() -> None:
    with pytest.raises(ProtocolSchemaError, match="至少一个"):
        validate_descriptor_set(
            base64.b64encode(
                descriptor_pb2.FileDescriptorSet(
                    file=[descriptor_pb2.FileDescriptorProto(name="empty.proto")]
                ).SerializeToString()
            ).decode()
        )
    client_streaming = PROTO_SOURCE.replace(
        "rpc Echo(EchoRequest)",
        "rpc Echo(stream EchoRequest)",
    )
    with pytest.raises(ProtocolSchemaError, match="Client/Bidi"):
        compile_proto_sources(
            [ProtoSourceFile(name="stream.proto", content=client_streaming)],
            entrypoint="stream.proto",
        )


def test_protocol_binding_only_changes_typed_request_fields() -> None:
    node = WorkflowNode.model_validate(
        {
            "id": "graphql",
            "type": "capability",
            "name": "查询用户",
            "position": {"x": 0, "y": 0},
            "capability_id": "graphql.request",
            "capability_version": "3.0.0",
            "configuration": {
                "schema_id": str(uuid4()),
                "endpoint": "https://api.example.com/graphql",
                "operation": "query User($id: ID!) { user(id: $id) { id } }",
                "variables": {"id": "initial"},
            },
            "bindings": [
                {
                    "input": "variables.id",
                    "expression": "node_outputs.rest.body.id",
                }
            ],
        }
    )
    context = ExecutionContext()
    context.record_output("rest", {"body": {"id": "42"}})

    assert isinstance(parse_protocol_config(node), GraphQLCapabilityConfig)
    resolved = resolve_protocol_config(node, context)

    assert isinstance(resolved, GraphQLCapabilityConfig)
    assert resolved.variables["id"] == "42"
    forbidden = node.model_copy(
        update={
            "bindings": [
                node.bindings[0].model_copy(update={"input": "endpoint"})  # type: ignore[index]
            ]
        }
    )
    with pytest.raises(NodeExecutionError, match="绑定目标"):
        resolve_protocol_config(forbidden, context)


def test_protocol_binding_reports_missing_invalid_and_conflicting_values() -> None:
    node = WorkflowNode.model_validate(
        {
            "id": "grpc",
            "type": "capability",
            "name": "查询用户",
            "position": {"x": 0, "y": 0},
            "capability_id": "grpc.call",
            "capability_version": "3.0.0",
            "configuration": {
                "descriptor_id": str(uuid4()),
                "endpoint": "grpc.example.com:443",
                "service": "flowtest.UserService",
                "method": "GetUser",
                "request": {"user": "scalar"},
                "call_type": "unary",
            },
            "bindings": [
                {
                    "input": "request.user.id",
                    "expression": "node_outputs.rest.body.id",
                }
            ],
        }
    )
    context = ExecutionContext()
    context.record_output("rest", {"body": {"id": "42"}})

    assert isinstance(parse_protocol_config(node), GrpcCapabilityConfig)
    with pytest.raises(NodeExecutionError, match="现有配置冲突"):
        resolve_protocol_config(node, context)
    missing = node.model_copy(
        update={
            "bindings": [
                node.bindings[0].model_copy(update={"expression": "node_outputs.unknown.id"})  # type: ignore[index]
            ]
        }
    )
    with pytest.raises(NodeExecutionError, match="未找到值"):
        resolve_protocol_config(missing, context)
    invalid_expression = node.model_copy(
        update={
            "bindings": [
                node.bindings[0].model_copy(update={"expression": "unknown_function(@)"})  # type: ignore[index]
            ]
        }
    )
    with pytest.raises(NodeExecutionError):
        resolve_protocol_config(invalid_expression, context)
    malformed = node.model_copy(
        update={"configuration": {"descriptor_id": str(uuid4())}, "bindings": []}
    )
    with pytest.raises(NodeExecutionError, match="配置无效"):
        resolve_protocol_config(malformed, context)
    unsupported = node.model_copy(update={"capability_id": "unsupported", "bindings": []})
    with pytest.raises(NodeExecutionError, match="不支持"):
        resolve_protocol_config(unsupported, context)
    with pytest.raises(ValueError, match="not a supported"):
        parse_protocol_config(unsupported)
    without_configuration = node.model_copy(update={"configuration": None})
    with pytest.raises(ValueError, match="missing"):
        resolve_capability_configuration(without_configuration, context)

    grpc_configuration = {
        "descriptor_id": str(uuid4()),
        "endpoint": "grpc.example.com:443",
        "service": "flowtest.UserService",
        "method": "GetUser",
        "request": {},
        "call_type": "unary",
    }
    with pytest.raises(ValueError, match="mTLS"):
        GrpcCapabilityConfig.model_validate({**grpc_configuration, "tls_mode": "mtls"})
    with pytest.raises(ValueError, match="mTLS"):
        GrpcCapabilityConfig.model_validate(
            {
                **grpc_configuration,
                "tls_mode": "tls",
                "credential_id": str(uuid4()),
            }
        )


@pytest.mark.asyncio
async def test_graphql_runner_executes_query_and_reports_schema_pin() -> None:
    schema = validate_graphql_sdl(GRAPHQL_SDL)

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={"data": {"user": {"id": payload["variables"]["id"], "name": "Alice"}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = ProtocolRunner(
            client,
            OutboundNetworkPolicy(),
            outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
        )
        result = await runner.execute_graphql(
            PreparedProtocolNode(
                protocol=ProtocolKind.GRAPHQL,
                schema_id=uuid4(),
                schema_version=3,
                schema_hash=schema.sha256,
                canonical_content=schema.canonical_content,
            ),
            GraphQLCapabilityConfig(
                schema_id=uuid4(),
                endpoint="https://api.example.com/graphql",
                operation="query User($id: ID!) { user(id: $id) { id name } }",
                variables={"id": "42"},
            ),
        )

    assert result.output["body"]["data"]["user"]["id"] == "42"
    assert result.output["schema_version"] == 3


@pytest.mark.asyncio
async def test_graphql_runner_normalizes_protocol_failures() -> None:
    schema = validate_graphql_sdl(GRAPHQL_SDL)
    prepared = PreparedProtocolNode(
        protocol=ProtocolKind.GRAPHQL,
        schema_id=uuid4(),
        schema_version=1,
        schema_hash=schema.sha256,
        canonical_content=schema.canonical_content,
    )
    config = GraphQLCapabilityConfig(
        schema_id=prepared.schema_id,
        endpoint="https://api.example.com/graphql",
        operation="query User($id: ID!) { user(id: $id) { id } }",
        operation_name="User",
        variables={"id": "42"},
    )

    async def assert_failure(response: httpx.Response, code: str) -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: response)
        ) as client:
            runner = ProtocolRunner(
                client,
                OutboundNetworkPolicy(),
                outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
            )
            with pytest.raises(NodeExecutionError) as captured:
                await runner.execute_graphql(prepared, config)
            assert captured.value.code == code

    await assert_failure(
        httpx.Response(200, json={"errors": [{"message": "failed"}]}), "GRAPHQL_ERRORS"
    )
    await assert_failure(httpx.Response(502, json={"detail": "failed"}), "GRAPHQL_REQUEST_FAILED")
    await assert_failure(httpx.Response(200, content=b"not-json"), "GRAPHQL_REQUEST_FAILED")
    await assert_failure(
        httpx.Response(200, content=b'"' + b"x" * (2 * 1024 * 1024) + b'"'),
        "GRAPHQL_RESPONSE_TOO_LARGE",
    )

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)) as client:
        runner = ProtocolRunner(
            client,
            OutboundNetworkPolicy(),
            outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
        )
        with pytest.raises(NodeExecutionError) as timeout:
            await runner.execute_graphql(prepared, config)
        assert timeout.value.code == "GRAPHQL_TIMEOUT"
        with pytest.raises(NodeExecutionError) as invalid_operation:
            await runner.execute_graphql(
                prepared,
                config.model_copy(update={"operation": "query { missing }"}),
            )
        assert invalid_operation.value.code == "INVALID_GRAPHQL_OPERATION"


def test_protocol_runtime_rejects_invalid_grpc_contracts_and_sensitive_transport() -> None:
    compiled = compile_proto_sources(
        [ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE)],
        entrypoint="echo.proto",
    )
    unary = _grpc_config(443, GrpcCallType.UNARY, "Echo").model_copy(
        update={"endpoint": "grpc.example.com:443"}
    )
    with pytest.raises(NodeExecutionError, match="不存在"):
        _grpc_contract(
            compiled.canonical_content,
            unary.model_copy(update={"method": "Missing"}),
        )

    with pytest.raises(NodeExecutionError, match="调用类型"):
        _grpc_contract(
            compiled.canonical_content,
            unary.model_copy(update={"call_type": GrpcCallType.SERVER_STREAMING}),
        )
    with pytest.raises(NodeExecutionError, match="消息"):
        _grpc_contract(
            compiled.canonical_content,
            unary.model_copy(update={"request": {"unknown": "value"}}),
        )
    missing_dependency = descriptor_pb2.FileDescriptorSet(
        file=[
            descriptor_pb2.FileDescriptorProto(
                name="broken.proto",
                dependency=["missing.proto"],
            )
        ]
    )
    with pytest.raises(NodeExecutionError, match="依赖"):
        _descriptor_pool(missing_dependency.SerializeToString())
    with pytest.raises(NodeExecutionError, match="Descriptor Set"):
        _descriptor_pool(b"\xff")

    assert _grpc_metadata({"X-Trace-ID": "trace"}) == (("x-trace-id", "trace"),)
    for metadata in ({"token-bin": "value"}, {"bad key": "value"}, {"x": "x" * 8_193}):
        with pytest.raises(NodeExecutionError, match="Metadata"):
            _grpc_metadata(metadata)
    assert _safe_headers({"X-Trace": "safe"}) == {"X-Trace": "safe"}
    for headers in ({"Host": "evil"}, {"X-Test": "bad\nvalue"}, {"": "empty"}):
        with pytest.raises(NodeExecutionError, match="Header"):
            _safe_headers(headers)

    credential = ProtocolCredentialMaterial(
        id=uuid4(),
        project_id=uuid4(),
        name="mTLS",
        kind=CredentialKind.GRPC_MTLS,
        host="grpc.example.com",
        port=443,
        secret=json.dumps(
            {
                "private_key_pem": "private",
                "certificate_chain_pem": "certificate",
                "root_certificate_pem": "root",
            }
        ),
    )
    assert _mtls_material("grpc.example.com:443", credential) == (
        b"root",
        b"private",
        b"certificate",
    )
    with pytest.raises(NodeExecutionError, match="缺少"):
        _mtls_material("grpc.example.com:443", None)
    with pytest.raises(NodeExecutionError, match="固定目标"):
        _mtls_material("other.example.com:443", credential)
    with pytest.raises(NodeExecutionError, match="内容无效"):
        _mtls_material(
            "grpc.example.com:443",
            ProtocolCredentialMaterial(
                id=credential.id,
                project_id=credential.project_id,
                name=credential.name,
                kind=credential.kind,
                host=credential.host,
                port=credential.port,
                secret="{}",
            ),
        )


@pytest.mark.asyncio
async def test_grpc_channel_builds_tls_and_mtls_transports() -> None:
    tls_channel = build_grpc_channel(
        endpoint="grpc.example.com:443",
        tls_mode=GrpcTlsMode.TLS,
        credential=None,
    )
    credential = ProtocolCredentialMaterial(
        id=uuid4(),
        project_id=uuid4(),
        name="mTLS",
        kind=CredentialKind.GRPC_MTLS,
        host="grpc.example.com",
        port=443,
        secret=json.dumps(
            {
                "private_key_pem": "private",
                "certificate_chain_pem": "certificate",
            }
        ),
    )
    mtls_channel = build_grpc_channel(
        endpoint="grpc.example.com:443",
        tls_mode=GrpcTlsMode.MTLS,
        credential=credential,
    )

    await tls_channel.close()
    await mtls_channel.close()


@pytest.mark.asyncio
async def test_grpc_runner_supports_unary_and_bounded_server_streaming() -> None:
    compiled = compile_proto_sources(
        [ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE)],
        entrypoint="echo.proto",
    )
    pool = _pool(compiled.canonical_content)
    request_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("flowtest.echo.v1.EchoRequest")
    )
    response_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("flowtest.echo.v1.EchoReply")
    )

    async def echo(request: object, context: object) -> object:
        del context
        return response_class(message=request.message, sequence=1)

    async def watch(request: object, context: object) -> AsyncIterator[object]:
        del context
        for sequence in range(3):
            yield response_class(message=request.message, sequence=sequence)

    server = grpc.aio.server()
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "flowtest.echo.v1.EchoService",
                {
                    "Echo": grpc.unary_unary_rpc_method_handler(
                        echo,
                        request_deserializer=request_class.FromString,
                        response_serializer=lambda value: value.SerializeToString(),
                    ),
                    "Watch": grpc.unary_stream_rpc_method_handler(
                        watch,
                        request_deserializer=request_class.FromString,
                        response_serializer=lambda value: value.SerializeToString(),
                    ),
                },
            ),
        )
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    prepared = PreparedProtocolNode(
        protocol=ProtocolKind.GRPC,
        schema_id=uuid4(),
        schema_version=7,
        schema_hash=compiled.sha256,
        canonical_content=compiled.canonical_content,
    )
    try:
        async with httpx.AsyncClient() as client:
            runner = ProtocolRunner(
                client,
                OutboundNetworkPolicy(),
                outbound_guard=AllowAllGuard(),  # type: ignore[arg-type]
            )
            unary = await runner.execute_grpc(
                prepared,
                _grpc_config(port, GrpcCallType.UNARY, "Echo"),
            )
            streaming = await runner.execute_grpc(
                prepared,
                _grpc_config(port, GrpcCallType.SERVER_STREAMING, "Watch"),
            )
    finally:
        await server.stop(grace=0)

    assert unary.output["messages"] == [{"message": "hello", "sequence": 1}]
    assert streaming.output["message_count"] == 3
    assert streaming.output["schema_hash"] == compiled.sha256


@pytest.mark.asyncio
async def test_grpc_reflection_imports_an_immutable_descriptor() -> None:
    compiled = compile_proto_sources(
        [ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE)],
        entrypoint="echo.proto",
    )
    pool = _pool(compiled.canonical_content)
    server = grpc.aio.server()
    reflection.enable_server_reflection(
        ("flowtest.echo.v1.EchoService", reflection.SERVICE_NAME),
        server,
        pool=pool,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        descriptor = await fetch_reflection_descriptor(channel, timeout=5)
    finally:
        await channel.close()
        await server.stop(grace=0)

    validated = validate_reflection_descriptor_set(descriptor, b'{"tls_mode":"plaintext"}')

    assert validated.summary["service_count"] == 1
    assert validated.source_format.value == "grpc_reflection"


@pytest.mark.asyncio
async def test_grpc_reflection_api_applies_network_policy_and_persists_version(
    protocol_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = compile_proto_sources(
        [ProtoSourceFile(name="echo.proto", content=PROTO_SOURCE)],
        entrypoint="echo.proto",
    )
    pool = _pool(compiled.canonical_content)
    server = grpc.aio.server()
    reflection.enable_server_reflection(
        ("flowtest.echo.v1.EchoService", reflection.SERVICE_NAME),
        server,
        pool=pool,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    async def allow_target(
        host: str,
        target_port: int,
        policy: OutboundNetworkPolicy,
    ) -> tuple[str, ...]:
        del policy
        assert host == "127.0.0.1"
        assert target_port == port
        return (host,)

    monkeypatch.setattr(settings, "feature_multi_protocol_enabled", True)
    monkeypatch.setattr(
        grpc_reflection_module.outbound_request_guard,
        "enforce_target",
        allow_target,
    )
    headers = await _login_headers(protocol_client)
    project = await protocol_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Reflection 项目", "description": "S23"},
    )
    try:
        imported = await protocol_client.post(
            "/api/v1/grpc/descriptors/reflection",
            headers=headers,
            json={
                "project_id": project.json()["id"],
                "name": "Reflection 用户服务",
                "endpoint": f"127.0.0.1:{port}",
                "tls_mode": "plaintext",
            },
        )
    finally:
        await server.stop(grace=0)

    assert imported.status_code == 201, imported.text
    assert imported.json()["source_format"] == "grpc_reflection"
    assert imported.json()["summary"]["service_count"] == 1
    with pytest.raises(AppError, match="包含端口"):
        _split_endpoint("missing-port")
    with pytest.raises(AppError, match="端口无效"):
        _split_endpoint("host:invalid")


@pytest.mark.asyncio
async def test_protocol_asset_api_versions_schema_and_rejects_duplicates(
    protocol_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_multi_protocol_enabled", True)
    headers = await _login_headers(protocol_client)
    project = await protocol_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "多协议项目", "description": "S23"},
    )
    project_id = project.json()["id"]
    payload = {
        "project_id": project_id,
        "name": "用户 GraphQL",
        "source_format": "graphql_sdl",
        "sdl": GRAPHQL_SDL,
    }

    created = await protocol_client.post("/api/v1/graphql/schemas", headers=headers, json=payload)
    duplicate = await protocol_client.post("/api/v1/graphql/schemas", headers=headers, json=payload)
    listed = await protocol_client.get(
        "/api/v1/graphql/schemas",
        headers=headers,
        params={"project_id": project_id},
    )
    grpc_created = await protocol_client.post(
        "/api/v1/grpc/descriptors",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "用户 gRPC",
            "source_format": "proto_source",
            "entrypoint": "echo.proto",
            "files": [{"name": "echo.proto", "content": PROTO_SOURCE}],
        },
    )
    grpc_listed = await protocol_client.get(
        "/api/v1/grpc/descriptors",
        headers=headers,
        params={"project_id": project_id},
    )

    async def fake_execute(
        _service: ProtocolDebugService,
        _project_id: object,
        prepared: PreparedProtocolNode,
        _config: object,
    ) -> ProtocolExecutionResult:
        return ProtocolExecutionResult(
            output={
                "schema_version": prepared.schema_version,
                "schema_hash": prepared.schema_hash,
            },
            duration_ms=1,
        )

    monkeypatch.setattr(ProtocolDebugService, "_execute", fake_execute)
    graphql_debug = await protocol_client.post(
        "/api/v1/graphql/execute",
        headers=headers,
        json={
            "project_id": project_id,
            "schema_id": created.json()["id"],
            "endpoint": "https://api.example.com/graphql",
            "operation": "query User($id: ID!) { user(id: $id) { id } }",
            "variables": {"id": "42"},
        },
    )
    grpc_debug = await protocol_client.post(
        "/api/v1/grpc/execute",
        headers=headers,
        json={
            "project_id": project_id,
            "descriptor_id": grpc_created.json()["id"],
            "endpoint": "grpc.example.com:443",
            "service": "flowtest.echo.v1.EchoService",
            "method": "Echo",
            "request": {"message": "hello"},
            "call_type": "unary",
            "tls_mode": "tls",
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["version"] == 1
    assert len(created.json()["content_sha256"]) == 64
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SCHEMA_ARTIFACT_DUPLICATE"
    assert listed.json()["total"] == 1
    assert grpc_created.status_code == 201, grpc_created.text
    assert grpc_listed.json()["total"] == 1
    assert graphql_debug.status_code == 200, graphql_debug.text
    assert graphql_debug.json()["schema_version"] == 1
    assert grpc_debug.status_code == 200, grpc_debug.text

    monkeypatch.setattr(settings, "feature_multi_protocol_enabled", False)
    disabled = await protocol_client.post(
        "/api/v1/graphql/execute",
        headers=headers,
        json={
            "project_id": project_id,
            "schema_id": created.json()["id"],
            "endpoint": "https://api.example.com/graphql",
            "operation": "query User($id: ID!) { user(id: $id) { id } }",
        },
    )
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "MULTI_PROTOCOL_DISABLED"


@pytest.mark.asyncio
async def test_grpc_mtls_credential_is_validated_and_write_only(
    protocol_client: AsyncClient,
) -> None:
    headers = await _login_headers(protocol_client)
    project = await protocol_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "mTLS 项目", "description": "S23"},
    )
    project_id = project.json()["id"]
    payload = {
        "project_id": project_id,
        "name": "用户服务 mTLS",
        "kind": "grpc_mtls",
        "host": "grpc.example.com",
        "secret": json.dumps(
            {
                "private_key_pem": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
                "certificate_chain_pem": (
                    "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----"
                ),
            }
        ),
    }

    created = await protocol_client.post("/api/v1/credentials", headers=headers, json=payload)
    invalid = await protocol_client.post(
        "/api/v1/credentials",
        headers=headers,
        json={**payload, "name": "无效证书", "secret": "{}"},
    )

    assert created.status_code == 201, created.text
    assert created.json()["port"] == 443
    assert "private_key_pem" not in created.text
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_GRPC_MTLS_CREDENTIAL"


def _pool(content: bytes) -> descriptor_pool.DescriptorPool:
    descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(content)
    pool = descriptor_pool.DescriptorPool()
    for file_descriptor in descriptor_set.file:
        pool.AddSerializedFile(file_descriptor.SerializeToString())
    return pool


def _grpc_config(port: int, call_type: GrpcCallType, method: str) -> GrpcCapabilityConfig:
    return GrpcCapabilityConfig(
        descriptor_id=uuid4(),
        endpoint=f"127.0.0.1:{port}",
        service="flowtest.echo.v1.EchoService",
        method=method,
        request={"message": "hello"},
        call_type=call_type,
    )


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
