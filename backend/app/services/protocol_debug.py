from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.data_nodes import CredentialKind
from app.domain.protocols import ProtocolKind
from app.engine.protocol_nodes import (
    GraphQLCapabilityConfig,
    GrpcCapabilityConfig,
    PreparedProtocolNode,
    ProtocolCredentialMaterial,
)
from app.engine.scheduler import NodeExecutionError
from app.models.access import User
from app.schemas.protocols import GraphQLDebugRequest, GrpcDebugRequest
from app.services.credentials import CredentialService, ExternalCredentialSecretStore
from app.services.projects import ProjectService
from app.services.protocol_assets import ProtocolAssetService
from app.services.protocol_runtime import ProtocolExecutionResult, ProtocolRunner


class ProtocolDebugService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        external_secrets: ExternalCredentialSecretStore | None = None,
    ) -> None:
        self._assets = ProtocolAssetService(session)
        self._projects = ProjectService(session)
        self._credentials = CredentialService(session, external_secrets=external_secrets)

    async def execute_graphql(
        self,
        *,
        actor: User,
        payload: GraphQLDebugRequest,
    ) -> ProtocolExecutionResult:
        self._require_enabled()
        await self._projects.authorize(
            actor=actor,
            project_id=payload.project_id,
            editing=True,
        )
        artifact = await self._assets.load(
            project_id=payload.project_id,
            artifact_id=payload.schema_id,
            protocol=ProtocolKind.GRAPHQL,
        )
        config = GraphQLCapabilityConfig.model_validate(payload.model_dump(exclude={"project_id"}))
        prepared = PreparedProtocolNode(
            protocol=ProtocolKind.GRAPHQL,
            schema_id=artifact.id,
            schema_version=artifact.version,
            schema_hash=artifact.content_sha256,
            canonical_content=artifact.canonical_content,
        )
        return await self._execute(payload.project_id, prepared, config)

    async def execute_grpc(
        self,
        *,
        actor: User,
        payload: GrpcDebugRequest,
    ) -> ProtocolExecutionResult:
        self._require_enabled()
        await self._projects.authorize(
            actor=actor,
            project_id=payload.project_id,
            editing=True,
        )
        artifact = await self._assets.load(
            project_id=payload.project_id,
            artifact_id=payload.descriptor_id,
            protocol=ProtocolKind.GRPC,
        )
        credential = None
        if payload.credential_id is not None:
            material = await self._credentials.load_material(
                project_id=payload.project_id,
                credential_id=payload.credential_id,
            )
            if material.kind is not CredentialKind.GRPC_MTLS:
                raise AppError(
                    code="GRPC_MTLS_CREDENTIAL_REQUIRED",
                    message="mTLS 调用必须使用 gRPC mTLS Credential",
                    status_code=422,
                )
            credential = ProtocolCredentialMaterial(
                id=material.id,
                project_id=material.project_id,
                name=material.name,
                kind=material.kind,
                host=material.host,
                port=material.port,
                secret=material.secret,
            )
        config = GrpcCapabilityConfig.model_validate(payload.model_dump(exclude={"project_id"}))
        prepared = PreparedProtocolNode(
            protocol=ProtocolKind.GRPC,
            schema_id=artifact.id,
            schema_version=artifact.version,
            schema_hash=artifact.content_sha256,
            canonical_content=artifact.canonical_content,
            credential=credential,
        )
        return await self._execute(payload.project_id, prepared, config)

    async def _execute(
        self,
        project_id: UUID,
        prepared: PreparedProtocolNode,
        config: GraphQLCapabilityConfig | GrpcCapabilityConfig,
    ) -> ProtocolExecutionResult:
        policy = await self._projects.load_runtime_security_policy(project_id)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            runner = ProtocolRunner(client, policy)
            try:
                if isinstance(config, GraphQLCapabilityConfig):
                    return await runner.execute_graphql(prepared, config)
                return await runner.execute_grpc(prepared, config)
            except NodeExecutionError as error:
                raise AppError(
                    code=error.code,
                    message=error.message,
                    status_code=422 if error.code.startswith("INVALID_") else 502,
                    details={"output": error.output} if error.output is not None else None,
                ) from error

    @staticmethod
    def _require_enabled() -> None:
        if not settings.feature_multi_protocol_enabled:
            raise AppError(
                code="MULTI_PROTOCOL_DISABLED",
                message="多协议执行能力尚未启用",
                status_code=409,
            )
