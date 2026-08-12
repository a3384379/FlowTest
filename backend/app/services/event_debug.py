from collections.abc import Awaitable, Callable
from typing import cast
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.event_protocols import EventSourceKind
from app.domain.protocols import ProtocolKind
from app.engine.event_nodes import (
    KafkaConsumeCapabilityConfig,
    KafkaProduceCapabilityConfig,
    PreparedEventNode,
    WebSocketExchangeCapabilityConfig,
)
from app.engine.scheduler import NodeExecutionError
from app.models.access import User
from app.models.protocols import EventSource, SchemaArtifact
from app.schemas.event_protocols import (
    EventSchemaCreate,
    KafkaConsumeDebugRequest,
    KafkaProduceDebugRequest,
    RegistrySchemaImport,
    WebSocketExchangeDebugRequest,
)
from app.schemas.protocols import ProtoFileInput
from app.services.event_runtime import EventExecutionResult, EventProtocolRunner
from app.services.event_sources import EventSourceService
from app.services.outbound import outbound_request_guard
from app.services.projects import ProjectService
from app.services.protocol_assets import ProtocolAssetService

EventOperation = Callable[[EventProtocolRunner], Awaitable[EventExecutionResult]]


class EventDebugService:
    def __init__(self, session: AsyncSession) -> None:
        self._sources = EventSourceService(session)
        self._assets = ProtocolAssetService(session)
        self._projects = ProjectService(session)

    async def execute_kafka_produce(
        self,
        *,
        actor: User,
        source_id: UUID,
        payload: KafkaProduceDebugRequest,
    ) -> EventExecutionResult:
        self._require_enabled()
        source = await self._sources.get(
            actor=actor,
            project_id=payload.project_id,
            source_id=source_id,
            kind=EventSourceKind.KAFKA,
            editing=True,
        )
        prepared = await self._prepared(source, payload.schema_id)
        config = KafkaProduceCapabilityConfig(
            source_id=source.id,
            **payload.model_dump(exclude={"project_id"}),
        )
        return await self._run(
            payload.project_id,
            lambda runner: runner.execute_kafka_produce(prepared, config),
        )

    async def execute_kafka_consume(
        self,
        *,
        actor: User,
        source_id: UUID,
        payload: KafkaConsumeDebugRequest,
    ) -> EventExecutionResult:
        self._require_enabled()
        source = await self._sources.get(
            actor=actor,
            project_id=payload.project_id,
            source_id=source_id,
            kind=EventSourceKind.KAFKA,
            editing=True,
        )
        prepared = await self._prepared(source, payload.schema_id)
        config = KafkaConsumeCapabilityConfig(
            source_id=source.id,
            **payload.model_dump(exclude={"project_id"}),
        )
        return await self._run(
            payload.project_id,
            lambda runner: runner.execute_kafka_consume(prepared, config),
        )

    async def execute_websocket_exchange(
        self,
        *,
        actor: User,
        source_id: UUID,
        payload: WebSocketExchangeDebugRequest,
    ) -> EventExecutionResult:
        self._require_enabled()
        source = await self._sources.get(
            actor=actor,
            project_id=payload.project_id,
            source_id=source_id,
            kind=EventSourceKind.WEBSOCKET,
            editing=True,
        )
        prepared = await self._prepared(source, None)
        config = WebSocketExchangeCapabilityConfig(
            source_id=source.id,
            **payload.model_dump(exclude={"project_id"}),
        )
        return await self._run(
            payload.project_id,
            lambda runner: runner.execute_websocket_exchange(prepared, config),
        )

    async def import_registry_schema(
        self,
        *,
        actor: User,
        source: EventSource,
        payload: RegistrySchemaImport,
    ) -> SchemaArtifact:
        self._require_enabled()
        if source.kind != EventSourceKind.KAFKA.value or not source.schema_registry_url:
            raise AppError(
                code="SCHEMA_REGISTRY_NOT_CONFIGURED",
                message="Kafka 事件源未配置 Schema Registry",
                status_code=422,
            )
        await self._projects.authorize(actor=actor, project_id=source.project_id, editing=True)
        policy = await self._projects.load_runtime_security_policy(source.project_id)
        await outbound_request_guard.enforce(source.schema_registry_url, policy)
        version = str(payload.version)
        url = (
            f"{source.schema_registry_url}/subjects/"
            f"{quote(payload.subject, safe='')}/versions/{quote(version, safe='')}"
        )
        try:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                response = await client.get(url, timeout=payload.timeout_seconds)
                response.raise_for_status()
                document = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise AppError(
                code="SCHEMA_REGISTRY_IMPORT_FAILED",
                message="无法从 Schema Registry 导入 Schema",
                status_code=502,
            ) from error
        schema_payload = _registry_schema_payload(payload, document)
        return await self._sources.create_schema(
            actor=actor,
            source=source,
            payload=schema_payload,
        )

    async def _prepared(
        self,
        source: EventSource,
        schema_id: UUID | None,
    ) -> PreparedEventNode:
        artifact = None
        if schema_id is not None:
            artifact = await self._assets.load(
                project_id=source.project_id,
                artifact_id=schema_id,
                protocol=ProtocolKind.KAFKA,
            )
        return _prepared_event_node(source, artifact)

    async def _run(
        self,
        project_id: UUID,
        operation: EventOperation,
    ) -> EventExecutionResult:
        policy = await self._projects.load_runtime_security_policy(project_id)
        runner = EventProtocolRunner(policy)
        try:
            return await operation(runner)
        except NodeExecutionError as error:
            raise AppError(
                code=error.code,
                message=error.message,
                status_code=422 if error.code.startswith("INVALID_") else 502,
                details={"output": error.output} if error.output is not None else None,
            ) from error
        finally:
            await runner.close_all()

    @staticmethod
    def _require_enabled() -> None:
        if not settings.feature_event_protocols_enabled:
            raise AppError(
                code="EVENT_PROTOCOLS_DISABLED",
                message="Kafka 与 WebSocket 执行能力尚未启用",
                status_code=409,
            )


def _prepared_event_node(
    source: EventSource,
    artifact: SchemaArtifact | None,
) -> PreparedEventNode:
    return PreparedEventNode(
        source_id=source.id,
        source_kind=EventSourceKind(source.kind),
        endpoints=tuple(source.endpoints),
        schema_registry_url=source.schema_registry_url,
        source_version=source.version,
        source_hash=source.config_sha256,
        schema_id=artifact.id if artifact is not None else None,
        schema_version=artifact.version if artifact is not None else None,
        schema_hash=artifact.content_sha256 if artifact is not None else None,
        schema_content=artifact.canonical_content if artifact is not None else None,
        schema_summary=cast(dict[str, JsonValue], artifact.summary)
        if artifact is not None
        else None,
    )


def _registry_schema_payload(
    request: RegistrySchemaImport,
    document: object,
) -> EventSchemaCreate:
    if not isinstance(document, dict):
        raise AppError(
            code="INVALID_SCHEMA_REGISTRY_RESPONSE",
            message="Schema Registry 响应必须是对象",
            status_code=502,
        )
    schema = document.get("schema")
    schema_id = document.get("id")
    schema_type = str(document.get("schemaType", "AVRO")).upper()
    references = document.get("references", [])
    if not isinstance(schema, str) or not isinstance(schema_id, int):
        raise AppError(
            code="INVALID_SCHEMA_REGISTRY_RESPONSE",
            message="Schema Registry 响应缺少 Schema 或 ID",
            status_code=502,
        )
    if references:
        raise AppError(
            code="SCHEMA_REGISTRY_REFERENCES_UNSUPPORTED",
            message="当前版本不接受带外部引用的 Registry Schema",
            status_code=422,
        )
    values: dict[str, object] = {
        "name": request.name,
        "description": request.description,
        "registry_id": schema_id,
    }
    if schema_type == "PROTOBUF":
        values.update(
            {
                "schema_format": "protobuf",
                "entrypoint": "schema.proto",
                "files": [ProtoFileInput(name="schema.proto", content=schema)],
            }
        )
    elif schema_type == "JSON":
        values.update({"schema_format": "json_schema", "schema": schema})
    elif schema_type == "AVRO":
        values.update({"schema_format": "avro", "schema": schema})
    else:
        raise AppError(
            code="SCHEMA_REGISTRY_TYPE_UNSUPPORTED",
            message="Schema Registry 类型仅支持 AVRO、JSON、PROTOBUF",
            status_code=422,
        )
    try:
        return EventSchemaCreate.model_validate(values)
    except ValidationError as error:
        raise AppError(
            code="INVALID_SCHEMA_REGISTRY_RESPONSE",
            message="Schema Registry 响应无法转换为固定 Schema",
            status_code=502,
        ) from error
