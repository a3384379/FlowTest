import hashlib
import json
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.event_protocols import (
    EventSchemaFormat,
    EventSourceKind,
    validate_bootstrap_servers,
    validate_event_schema,
)
from app.domain.protocols import ProtocolKind, ProtocolSchemaError, ProtoSourceFile
from app.models.access import User
from app.models.protocols import EventSource, SchemaArtifact
from app.repositories.protocols import ProtocolRepository
from app.schemas.event_protocols import EventSchemaCreate, EventSourceCreate
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.protocol_assets import ProtocolAssetService


class EventSourceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ProtocolRepository(session)
        self._projects = ProjectService(session)
        self._assets = ProtocolAssetService(session)
        self._audit = AuditService(session)

    async def create(self, *, actor: User, payload: EventSourceCreate) -> EventSource:
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        kind = EventSourceKind(payload.kind)
        endpoints = _event_endpoints(payload, kind)
        registry_url = _registry_url(payload.schema_registry_url)
        fingerprint = _source_fingerprint(kind, endpoints, registry_url)
        existing = await self._repository.find_event_source_by_hash(
            project_id=payload.project_id,
            kind=kind.value,
            config_sha256=fingerprint,
        )
        if existing is not None:
            raise AppError(
                code="EVENT_SOURCE_DUPLICATE",
                message="相同配置的事件源已存在",
                status_code=409,
                details={"existing_id": str(existing.id), "version": existing.version},
            )
        name = payload.name.strip()
        source = EventSource(
            project_id=payload.project_id,
            kind=kind.value,
            name=name,
            description=payload.description.strip(),
            version=await self._repository.next_event_source_version(
                project_id=payload.project_id,
                kind=kind.value,
                name=name,
            ),
            endpoints=list(endpoints),
            schema_registry_url=registry_url,
            config_sha256=fingerprint,
            created_by_id=actor.id,
        )
        self._repository.add_event_source(source)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=payload.project_id,
            action="event_source.created",
            resource_type="event_source",
            resource_id=source.id,
            details={"kind": source.kind, "version": source.version},
        )
        await self._session.commit()
        await self._session.refresh(source)
        return source

    async def list_sources(
        self,
        *,
        actor: User,
        project_id: UUID,
        kind: EventSourceKind | None,
        page: int,
        page_size: int,
    ) -> tuple[list[EventSource], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_event_sources(
            project_id=project_id,
            kind=kind.value if kind is not None else None,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_id: UUID,
        kind: EventSourceKind | None = None,
        editing: bool = False,
    ) -> EventSource:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=editing)
        return await self.load(project_id=project_id, source_id=source_id, kind=kind)

    async def load(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        kind: EventSourceKind | None = None,
    ) -> EventSource:
        source = await self._repository.get_event_source(source_id)
        if (
            source is None
            or source.project_id != project_id
            or (kind is not None and source.kind != kind.value)
        ):
            raise AppError(
                code="EVENT_SOURCE_NOT_FOUND",
                message="事件源版本不存在",
                status_code=404,
            )
        return source

    async def create_schema(
        self,
        *,
        actor: User,
        source: EventSource,
        payload: EventSchemaCreate,
    ) -> SchemaArtifact:
        if source.kind != EventSourceKind.KAFKA.value:
            raise AppError(
                code="EVENT_SCHEMA_KIND_MISMATCH",
                message="只有 Kafka 事件源支持消息 Schema",
                status_code=422,
            )
        try:
            validated = validate_event_schema(
                schema_format=EventSchemaFormat(payload.schema_format),
                schema=payload.schema_content,
                proto_files=tuple(
                    ProtoSourceFile(name=item.name, content=item.content)
                    for item in payload.files or []
                ),
                entrypoint=payload.entrypoint,
                registry_id=payload.registry_id,
            )
        except ProtocolSchemaError as error:
            raise AppError(
                code="INVALID_EVENT_SCHEMA",
                message=str(error),
                status_code=422,
            ) from error
        return await self._assets.create_validated(
            actor=actor,
            project_id=source.project_id,
            name=payload.name,
            description=payload.description,
            validated=validated,
        )

    async def list_schemas(
        self,
        *,
        actor: User,
        source: EventSource,
        page: int,
        page_size: int,
    ) -> tuple[list[SchemaArtifact], int]:
        return await self._assets.list(
            actor=actor,
            project_id=source.project_id,
            protocol=ProtocolKind.KAFKA,
            page=page,
            page_size=page_size,
        )


def _event_endpoints(payload: EventSourceCreate, kind: EventSourceKind) -> tuple[str, ...]:
    if kind is EventSourceKind.KAFKA:
        return validate_bootstrap_servers(tuple(payload.bootstrap_servers or ()))
    url = (payload.websocket_url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in {"ws", "wss"} or not parts.hostname or parts.username or parts.password:
        raise AppError(
            code="INVALID_WEBSOCKET_URL",
            message="WebSocket URL 必须使用 ws/wss 且不能内嵌凭据",
            status_code=422,
        )
    return (url,)


def _registry_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = value.strip().rstrip("/")
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise AppError(
            code="INVALID_SCHEMA_REGISTRY_URL",
            message="Schema Registry URL 必须使用 http/https 且不能内嵌凭据",
            status_code=422,
        )
    return url


def _source_fingerprint(
    kind: EventSourceKind,
    endpoints: tuple[str, ...],
    schema_registry_url: str | None,
) -> str:
    canonical = json.dumps(
        {
            "kind": kind.value,
            "endpoints": endpoints,
            "schema_registry_url": schema_registry_url,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
