from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.protocols import (
    ProtocolKind,
    ProtocolSchemaError,
    ProtoSourceFile,
    SchemaSourceFormat,
    ValidatedSchema,
    compile_proto_sources,
    validate_descriptor_set,
    validate_graphql_introspection,
    validate_graphql_sdl,
)
from app.models.access import User
from app.models.protocols import SchemaArtifact
from app.repositories.protocols import ProtocolRepository
from app.schemas.protocols import GraphQLSchemaCreate, GrpcDescriptorCreate
from app.services.audit import AuditService
from app.services.projects import ProjectService


class ProtocolAssetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ProtocolRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_graphql(
        self,
        *,
        actor: User,
        payload: GraphQLSchemaCreate,
    ) -> SchemaArtifact:
        validated = self._validate_graphql(payload)
        return await self._create(
            actor=actor,
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            validated=validated,
        )

    async def create_grpc(
        self,
        *,
        actor: User,
        payload: GrpcDescriptorCreate,
    ) -> SchemaArtifact:
        validated = self._validate_grpc(payload)
        return await self._create(
            actor=actor,
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            validated=validated,
        )

    async def create_validated(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        description: str,
        validated: ValidatedSchema,
    ) -> SchemaArtifact:
        return await self._create(
            actor=actor,
            project_id=project_id,
            name=name,
            description=description,
            validated=validated,
        )

    async def list(
        self,
        *,
        actor: User,
        project_id: UUID,
        protocol: ProtocolKind,
        page: int,
        page_size: int,
    ) -> tuple[list[SchemaArtifact], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_artifacts(
            project_id=project_id,
            protocol=protocol.value,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(
        self,
        *,
        actor: User,
        project_id: UUID,
        artifact_id: UUID,
        protocol: ProtocolKind | None = None,
    ) -> SchemaArtifact:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self.load(project_id=project_id, artifact_id=artifact_id, protocol=protocol)

    async def load(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        protocol: ProtocolKind | None = None,
    ) -> SchemaArtifact:
        artifact = await self._repository.get(artifact_id)
        if (
            artifact is None
            or artifact.project_id != project_id
            or (protocol is not None and artifact.protocol != protocol.value)
        ):
            raise AppError(
                code="SCHEMA_ARTIFACT_NOT_FOUND",
                message="协议 Schema 版本不存在",
                status_code=404,
            )
        return artifact

    async def _create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        description: str,
        validated: ValidatedSchema,
    ) -> SchemaArtifact:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        existing = await self._repository.find_by_hash(
            project_id=project_id,
            protocol=validated.protocol.value,
            content_sha256=validated.sha256,
        )
        if existing is not None:
            raise AppError(
                code="SCHEMA_ARTIFACT_DUPLICATE",
                message="相同内容的协议 Schema 已存在",
                status_code=409,
                details={"existing_id": str(existing.id), "version": existing.version},
            )
        normalized_name = name.strip()
        artifact = SchemaArtifact(
            project_id=project_id,
            protocol=validated.protocol.value,
            name=normalized_name,
            description=description.strip(),
            version=await self._repository.next_version(
                project_id=project_id,
                protocol=validated.protocol.value,
                name=normalized_name,
            ),
            source_format=validated.source_format.value,
            content_sha256=validated.sha256,
            canonical_content=validated.canonical_content,
            source_content=validated.source_content,
            summary=validated.summary,
            created_by_id=actor.id,
        )
        self._repository.add(artifact)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="schema_artifact.created",
            resource_type="schema_artifact",
            resource_id=artifact.id,
            details={
                "protocol": artifact.protocol,
                "name": artifact.name,
                "version": artifact.version,
                "sha256": artifact.content_sha256,
            },
        )
        await self._session.commit()
        await self._session.refresh(artifact)
        return artifact

    @staticmethod
    def _validate_graphql(payload: GraphQLSchemaCreate) -> ValidatedSchema:
        try:
            if payload.source_format == SchemaSourceFormat.GRAPHQL_SDL.value:
                return validate_graphql_sdl(payload.sdl or "")
            return validate_graphql_introspection(payload.introspection or {})
        except ProtocolSchemaError as error:
            raise AppError(
                code="INVALID_GRAPHQL_SCHEMA",
                message=str(error),
                status_code=422,
            ) from error

    @staticmethod
    def _validate_grpc(payload: GrpcDescriptorCreate) -> ValidatedSchema:
        try:
            if payload.source_format == SchemaSourceFormat.PROTO_SOURCE.value:
                return compile_proto_sources(
                    (
                        ProtoSourceFile(name=item.name, content=item.content)
                        for item in payload.files or []
                    ),
                    entrypoint=payload.entrypoint or "",
                )
            return validate_descriptor_set(payload.descriptor_set_base64 or "")
        except ProtocolSchemaError as error:
            raise AppError(
                code="INVALID_GRPC_DESCRIPTOR",
                message=str(error),
                status_code=422,
            ) from error
