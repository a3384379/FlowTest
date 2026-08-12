import json
from dataclasses import dataclass
from time import monotonic
from typing import cast

import grpc
import httpx
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from google.protobuf.message import DecodeError, Message
from pydantic import JsonValue

from app.core.errors import AppError
from app.core.logging import redact
from app.domain.data_nodes import CredentialKind
from app.domain.network import OutboundNetworkPolicy
from app.domain.protocols import (
    MAX_GRPC_MESSAGE_BYTES,
    MAX_GRPC_STREAM_BYTES,
    MAX_GRPC_STREAM_MESSAGES,
    GrpcCallType,
    GrpcTlsMode,
    ProtocolSchemaError,
    validate_graphql_operation,
)
from app.engine.protocol_nodes import (
    GraphQLCapabilityConfig,
    GrpcCapabilityConfig,
    PreparedProtocolNode,
    ProtocolCredentialMaterial,
)
from app.engine.scheduler import NodeExecutionError
from app.services.outbound import OutboundRequestGuard, outbound_request_guard


@dataclass(frozen=True, slots=True)
class ProtocolExecutionResult:
    output: JsonValue
    duration_ms: int


class ProtocolRunner:
    def __init__(
        self,
        client: httpx.AsyncClient,
        network_policy: OutboundNetworkPolicy,
        *,
        outbound_guard: OutboundRequestGuard = outbound_request_guard,
    ) -> None:
        self._client = client
        self._network_policy = network_policy
        self._outbound_guard = outbound_guard

    async def execute_graphql(
        self,
        prepared: PreparedProtocolNode,
        config: GraphQLCapabilityConfig,
    ) -> ProtocolExecutionResult:
        started = monotonic()
        try:
            operation = validate_graphql_operation(prepared.canonical_content, config.operation)
        except ProtocolSchemaError as error:
            raise NodeExecutionError(
                code="INVALID_GRAPHQL_OPERATION", message=str(error)
            ) from error
        await self._enforce(config.endpoint)
        try:
            response = await self._client.post(
                config.endpoint,
                headers=_safe_headers(config.headers),
                json={
                    "query": operation,
                    "variables": config.variables,
                    **({"operationName": config.operation_name} if config.operation_name else {}),
                },
                timeout=config.timeout_seconds,
            )
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise NodeExecutionError(
                    code="GRAPHQL_RESPONSE_TOO_LARGE",
                    message="GraphQL 响应超过 2 MB 上限",
                )
            payload = cast(JsonValue, response.json())
        except NodeExecutionError:
            raise
        except httpx.TimeoutException as error:
            raise NodeExecutionError(code="GRAPHQL_TIMEOUT", message="GraphQL 请求超时") from error
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            raise NodeExecutionError(
                code="GRAPHQL_REQUEST_FAILED",
                message="GraphQL 请求失败或响应不是有效 JSON",
            ) from error
        output = cast(
            JsonValue,
            {
                "protocol": "graphql",
                "status_code": response.status_code,
                "body": cast(JsonValue, redact(payload)),
                "schema_version": prepared.schema_version,
                "schema_hash": prepared.schema_hash,
            },
        )
        if isinstance(payload, dict) and payload.get("errors"):
            raise NodeExecutionError(
                code="GRAPHQL_ERRORS",
                message="GraphQL 响应包含错误",
                output=output,
            )
        return ProtocolExecutionResult(output=output, duration_ms=_elapsed_ms(started))

    async def execute_grpc(
        self,
        prepared: PreparedProtocolNode,
        config: GrpcCapabilityConfig,
    ) -> ProtocolExecutionResult:
        started = monotonic()
        await self._enforce(
            f"{'https' if config.tls_mode is not GrpcTlsMode.PLAINTEXT else 'http'}://{config.endpoint}"
        )
        request, response_class, path = _grpc_contract(prepared.canonical_content, config)
        channel = build_grpc_channel(
            endpoint=config.endpoint,
            tls_mode=config.tls_mode,
            credential=prepared.credential,
        )
        try:
            if config.call_type is GrpcCallType.UNARY:
                output = await _execute_unary(channel, path, request, response_class, config)
            else:
                output = await _execute_server_stream(
                    channel, path, request, response_class, config
                )
        except grpc.aio.AioRpcError as error:
            raise NodeExecutionError(
                code=f"GRPC_{error.code().name}",
                message="gRPC 调用失败",
                output={"details": error.details()[:500]},
            ) from error
        finally:
            await channel.close()
        return ProtocolExecutionResult(
            output=cast(
                JsonValue,
                {
                    "protocol": "grpc",
                    "service": config.service,
                    "method": config.method,
                    "call_type": config.call_type.value,
                    "messages": output,
                    "message_count": len(output),
                    "schema_version": prepared.schema_version,
                    "schema_hash": prepared.schema_hash,
                },
            ),
            duration_ms=_elapsed_ms(started),
        )

    async def _enforce(self, url: str) -> None:
        try:
            await self._outbound_guard.enforce(url, self._network_policy)
        except AppError as error:
            raise NodeExecutionError(code=error.code, message=error.message) from error


def _grpc_contract(
    descriptor_content: bytes,
    config: GrpcCapabilityConfig,
) -> tuple[Message, type[Message], str]:
    pool = _descriptor_pool(descriptor_content)
    try:
        service = pool.FindServiceByName(config.service)  # type: ignore[no-untyped-call]
        method = service.methods_by_name[config.method]
    except KeyError as error:
        raise NodeExecutionError(
            code="GRPC_METHOD_NOT_FOUND",
            message="Descriptor 中不存在指定的 gRPC 方法",
        ) from error
    expected_call_type = (
        GrpcCallType.SERVER_STREAMING if method.server_streaming else GrpcCallType.UNARY
    )
    if method.client_streaming or expected_call_type is not config.call_type:
        raise NodeExecutionError(
            code="GRPC_CALL_TYPE_MISMATCH",
            message="调用类型与 Descriptor 不一致",
        )
    request_class = message_factory.GetMessageClass(method.input_type)
    response_class = message_factory.GetMessageClass(method.output_type)
    request = request_class()
    try:
        json_format.ParseDict(config.request, request, ignore_unknown_fields=False)
    except (json_format.ParseError, TypeError) as error:
        raise NodeExecutionError(
            code="INVALID_GRPC_MESSAGE",
            message="gRPC 请求消息与 Descriptor 不匹配",
        ) from error
    if request.ByteSize() > MAX_GRPC_MESSAGE_BYTES:
        raise NodeExecutionError(
            code="GRPC_MESSAGE_TOO_LARGE",
            message="gRPC 单条消息超过 4 MB 上限",
        )
    return request, response_class, f"/{service.full_name}/{method.name}"


def _descriptor_pool(content: bytes) -> descriptor_pool.DescriptorPool:
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    try:
        descriptor_set.ParseFromString(content)
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
                raise NodeExecutionError(
                    code="INVALID_GRPC_DESCRIPTOR",
                    message="Descriptor 依赖不完整",
                )
        return pool
    except DecodeError as error:
        raise NodeExecutionError(
            code="INVALID_GRPC_DESCRIPTOR",
            message="Descriptor Set 无效",
        ) from error


def build_grpc_channel(
    *,
    endpoint: str,
    tls_mode: GrpcTlsMode,
    credential: ProtocolCredentialMaterial | None,
) -> grpc.aio.Channel:
    options = (
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    )
    if tls_mode is GrpcTlsMode.PLAINTEXT:
        return grpc.aio.insecure_channel(endpoint, options=options)
    if tls_mode is GrpcTlsMode.TLS:
        return grpc.aio.secure_channel(
            endpoint,
            grpc.ssl_channel_credentials(),
            options=options,
        )
    root, private_key, certificate_chain = _mtls_material(endpoint, credential)
    credentials = grpc.ssl_channel_credentials(
        root_certificates=root,
        private_key=private_key,
        certificate_chain=certificate_chain,
    )
    return grpc.aio.secure_channel(endpoint, credentials, options=options)


def _mtls_material(
    endpoint: str,
    credential: ProtocolCredentialMaterial | None,
) -> tuple[bytes | None, bytes, bytes]:
    if credential is None or credential.kind is not CredentialKind.GRPC_MTLS:
        raise NodeExecutionError(
            code="GRPC_MTLS_CREDENTIAL_REQUIRED",
            message="mTLS 调用缺少有效 Credential",
        )
    if f"{credential.host}:{credential.port}" != endpoint:
        raise NodeExecutionError(
            code="GRPC_MTLS_TARGET_MISMATCH",
            message="mTLS Credential 只能用于其固定目标",
        )
    try:
        material = json.loads(credential.secret)
        private_key = material["private_key_pem"].encode()
        certificate_chain = material["certificate_chain_pem"].encode()
        root_value = material.get("root_certificate_pem")
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as error:
        raise NodeExecutionError(
            code="INVALID_GRPC_MTLS_CREDENTIAL",
            message="mTLS Credential 内容无效",
        ) from error
    root = root_value.encode() if isinstance(root_value, str) and root_value else None
    return root, private_key, certificate_chain


async def _execute_unary(
    channel: grpc.aio.Channel,
    path: str,
    request: Message,
    response_class: type[Message],
    config: GrpcCapabilityConfig,
) -> list[JsonValue]:
    call = channel.unary_unary(
        path,
        request_serializer=lambda value: value.SerializeToString(),
        response_deserializer=response_class.FromString,
    )
    response = await call(
        request,
        timeout=config.timeout_seconds,
        metadata=_grpc_metadata(config.metadata),
    )
    return [_message_json(response)]


async def _execute_server_stream(
    channel: grpc.aio.Channel,
    path: str,
    request: Message,
    response_class: type[Message],
    config: GrpcCapabilityConfig,
) -> list[JsonValue]:
    call_factory = channel.unary_stream(
        path,
        request_serializer=lambda value: value.SerializeToString(),
        response_deserializer=response_class.FromString,
    )
    call = call_factory(
        request,
        timeout=config.timeout_seconds,
        metadata=_grpc_metadata(config.metadata),
    )
    messages: list[JsonValue] = []
    total_bytes = 0
    async for message in call:
        size = message.ByteSize()
        if size > MAX_GRPC_MESSAGE_BYTES:
            raise NodeExecutionError(
                code="GRPC_MESSAGE_TOO_LARGE",
                message="gRPC 单条消息超过 4 MB 上限",
            )
        total_bytes += size
        if len(messages) >= MAX_GRPC_STREAM_MESSAGES or total_bytes > MAX_GRPC_STREAM_BYTES:
            call.cancel()
            raise NodeExecutionError(
                code="GRPC_STREAM_LIMIT_EXCEEDED",
                message="gRPC 流超过 1000 条或 50 MB 上限",
            )
        messages.append(_message_json(message))
    return messages


def _message_json(message: Message) -> JsonValue:
    return cast(
        JsonValue,
        json_format.MessageToDict(
            message,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        ),
    )


def _grpc_metadata(values: dict[str, str]) -> tuple[tuple[str, str], ...]:
    metadata: list[tuple[str, str]] = []
    for key, value in values.items():
        normalized = key.strip().lower()
        if (
            not normalized
            or normalized.endswith("-bin")
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789-_."
                for character in normalized
            )
            or len(value) > 8_192
        ):
            raise NodeExecutionError(
                code="INVALID_GRPC_METADATA",
                message="gRPC Metadata 无效或超过上限",
            )
        metadata.append((normalized, value))
    return tuple(metadata)


def _safe_headers(values: dict[str, str]) -> dict[str, str]:
    forbidden = {"host", "content-length", "transfer-encoding", "connection"}
    headers: dict[str, str] = {}
    for key, value in values.items():
        normalized = key.strip()
        if not normalized or normalized.lower() in forbidden or "\r" in value or "\n" in value:
            raise NodeExecutionError(
                code="INVALID_GRAPHQL_HEADER",
                message="GraphQL Header 无效",
            )
        headers[normalized] = value
    return headers


def _elapsed_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))
