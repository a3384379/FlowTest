import json
from collections.abc import AsyncIterator
from typing import Any

import grpc
from google.protobuf import descriptor_pb2
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.data_nodes import CredentialKind
from app.domain.protocols import (
    GrpcTlsMode,
    ProtocolSchemaError,
    validate_reflection_descriptor_set,
)
from app.engine.protocol_nodes import ProtocolCredentialMaterial
from app.models.access import User
from app.models.protocols import SchemaArtifact
from app.schemas.protocols import GrpcReflectionCreate
from app.services.credentials import CredentialService, ExternalCredentialSecretStore
from app.services.outbound import outbound_request_guard
from app.services.projects import ProjectService
from app.services.protocol_assets import ProtocolAssetService
from app.services.protocol_runtime import build_grpc_channel


class GrpcReflectionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        external_secrets: ExternalCredentialSecretStore | None = None,
    ) -> None:
        self._assets = ProtocolAssetService(session)
        self._projects = ProjectService(session)
        self._credentials = CredentialService(session, external_secrets=external_secrets)

    async def import_descriptor(
        self,
        *,
        actor: User,
        payload: GrpcReflectionCreate,
    ) -> SchemaArtifact:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        policy = await self._projects.load_runtime_security_policy(payload.project_id)
        host, port = _split_endpoint(payload.endpoint)
        await outbound_request_guard.enforce_target(host, port, policy)
        credential = await self._load_credential(payload)
        channel = build_grpc_channel(
            endpoint=payload.endpoint,
            tls_mode=GrpcTlsMode(payload.tls_mode),
            credential=credential,
        )
        try:
            descriptor = await fetch_reflection_descriptor(channel, payload.timeout_seconds)
        except grpc.aio.AioRpcError as error:
            raise AppError(
                code=f"GRPC_REFLECTION_{error.code().name}",
                message="gRPC Reflection 请求失败",
                status_code=502,
            ) from error
        finally:
            await channel.close()
        metadata = json.dumps(
            {"endpoint": payload.endpoint, "tls_mode": payload.tls_mode},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        try:
            validated = validate_reflection_descriptor_set(descriptor, metadata)
        except ProtocolSchemaError as error:
            raise AppError(
                code="INVALID_GRPC_DESCRIPTOR",
                message=str(error),
                status_code=422,
            ) from error
        return await self._assets.create_validated(
            actor=actor,
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            validated=validated,
        )

    async def _load_credential(
        self,
        payload: GrpcReflectionCreate,
    ) -> ProtocolCredentialMaterial | None:
        if payload.credential_id is None:
            return None
        material = await self._credentials.load_material(
            project_id=payload.project_id,
            credential_id=payload.credential_id,
        )
        if material.kind is not CredentialKind.GRPC_MTLS:
            raise AppError(
                code="GRPC_MTLS_CREDENTIAL_REQUIRED",
                message="mTLS Reflection 必须使用 gRPC mTLS Credential",
                status_code=422,
            )
        return ProtocolCredentialMaterial(
            id=material.id,
            project_id=material.project_id,
            name=material.name,
            kind=material.kind,
            host=material.host,
            port=material.port,
            secret=material.secret,
        )

    @staticmethod
    def _require_enabled() -> None:
        if not settings.feature_multi_protocol_enabled:
            raise AppError(
                code="MULTI_PROTOCOL_DISABLED",
                message="多协议执行能力尚未启用",
                status_code=409,
            )


async def fetch_reflection_descriptor(channel: grpc.aio.Channel, timeout: int) -> bytes:
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    response = await _reflection_request(
        stub,
        reflection_pb2.ServerReflectionRequest(list_services=""),
        timeout,
    )
    services = [
        item.name
        for item in response.list_services_response.service
        if not item.name.startswith("grpc.reflection.")
    ]
    if not services:
        raise AppError(
            code="GRPC_REFLECTION_EMPTY",
            message="gRPC Reflection 未返回业务 Service",
            status_code=422,
        )
    files: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    for service in services[:1_000]:
        response = await _reflection_request(
            stub,
            reflection_pb2.ServerReflectionRequest(file_containing_symbol=service),
            timeout,
        )
        for serialized in response.file_descriptor_response.file_descriptor_proto:
            descriptor = descriptor_pb2.FileDescriptorProto.FromString(serialized)
            files[descriptor.name] = descriptor
    descriptor_set = descriptor_pb2.FileDescriptorSet(file=list(files.values()))
    return descriptor_set.SerializeToString()


async def _reflection_request(
    stub: Any,
    request: Any,
    timeout: int,
) -> Any:
    call = stub.ServerReflectionInfo(_single_request(request), timeout=timeout)
    async for response in call:
        if response.HasField("error_response"):
            raise AppError(
                code="GRPC_REFLECTION_REJECTED",
                message="gRPC 服务拒绝 Reflection 请求",
                status_code=422,
                details={"error_code": response.error_response.error_code},
            )
        return response
    raise AppError(
        code="GRPC_REFLECTION_EMPTY",
        message="gRPC Reflection 未返回响应",
        status_code=422,
    )


async def _single_request(request: Any) -> AsyncIterator[Any]:
    yield request


def _split_endpoint(endpoint: str) -> tuple[str, int]:
    host, separator, port_value = endpoint.rpartition(":")
    if not separator or not host:
        raise AppError(
            code="INVALID_GRPC_ENDPOINT", message="gRPC Endpoint 必须包含端口", status_code=422
        )
    try:
        port = int(port_value)
    except ValueError as error:
        raise AppError(
            code="INVALID_GRPC_ENDPOINT", message="gRPC Endpoint 端口无效", status_code=422
        ) from error
    return host, port
