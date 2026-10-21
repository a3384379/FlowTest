from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import String, func, or_, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_assets import APIDefinition, APIVersion
from app.models.protocols import SchemaArtifact
from app.models.workflows import WorkflowExecution
from app.schemas.ai_sources import (
    AIPublicSource,
    AIPublicSourceMetadata,
    AISourceKind,
    AISourceSummary,
)


class AISourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_sources(
        self, project_id: UUID, kind: AISourceKind, page: int, page_size: int, search: str
    ) -> tuple[list[AISourceSummary], int]:
        if kind == "api":
            return await self._list_apis(project_id, page, page_size, search)
        if kind == "schema":
            return await self._list_schemas(project_id, page, page_size, search)
        return await self._list_executions(project_id, page, page_size, search)

    async def read_source(
        self, project_id: UUID, kind: AISourceKind, source_id: UUID, version: int | None
    ) -> AIPublicSource | None:
        if kind == "api":
            return await self._api(project_id, source_id, version)
        if kind == "schema":
            return await self._schema(project_id, source_id)
        return await self._execution(project_id, source_id)

    async def _list_apis(
        self, project_id: UUID, page: int, size: int, search: str
    ) -> tuple[list[AISourceSummary], int]:
        filters = [APIDefinition.project_id == project_id]
        if search:
            filters.append(APIDefinition.name.icontains(search, autoescape=True))
        rows = await self._session.execute(
            select(
                APIDefinition.id,
                APIDefinition.name,
                APIDefinition.current_version,
                APIDefinition.created_at,
            )
            .where(*filters)
            .order_by(APIDefinition.created_at.desc(), APIDefinition.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(APIDefinition).where(*filters)
        )
        return [
            AISourceSummary(
                id=row.id,
                kind="api",
                name=row.name,
                version=row.current_version,
                created_at=row.created_at,
            )
            for row in rows
        ], int(total or 0)

    async def _list_schemas(
        self, project_id: UUID, page: int, size: int, search: str
    ) -> tuple[list[AISourceSummary], int]:
        filters = [SchemaArtifact.project_id == project_id]
        if search:
            filters.append(SchemaArtifact.name.icontains(search, autoescape=True))
        rows = await self._session.execute(
            select(
                SchemaArtifact.id,
                SchemaArtifact.name,
                SchemaArtifact.version,
                SchemaArtifact.protocol,
                SchemaArtifact.created_at,
            )
            .where(*filters)
            .order_by(SchemaArtifact.created_at.desc(), SchemaArtifact.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(SchemaArtifact).where(*filters)
        )
        return [
            AISourceSummary(
                id=row.id,
                kind="schema",
                name=row.name,
                version=row.version,
                protocol=row.protocol,
                created_at=row.created_at,
            )
            for row in rows
        ], int(total or 0)

    async def _list_executions(
        self, project_id: UUID, page: int, size: int, search: str
    ) -> tuple[list[AISourceSummary], int]:
        filters = [WorkflowExecution.project_id == project_id]
        if search:
            normalized = search.replace("-", "") or search
            filters.append(
                or_(
                    WorkflowExecution.status.icontains(search, autoescape=True),
                    func.replace(sql_cast(WorkflowExecution.id, String), "-", "").icontains(
                        normalized, autoescape=True
                    ),
                )
            )
        rows = await self._session.execute(
            select(WorkflowExecution.id, WorkflowExecution.status, WorkflowExecution.created_at)
            .where(*filters)
            .order_by(WorkflowExecution.created_at.desc(), WorkflowExecution.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(WorkflowExecution).where(*filters)
        )
        return [
            AISourceSummary(
                id=row.id,
                kind="execution",
                name=f"执行 {row.id}",
                status=row.status,
                created_at=row.created_at,
            )
            for row in rows
        ], int(total or 0)

    async def _api(
        self, project_id: UUID, source_id: UUID, version: int | None
    ) -> AIPublicSource | None:
        requested = APIVersion.version == (
            version if version is not None else APIDefinition.current_version
        )
        row = (
            await self._session.execute(
                select(
                    APIDefinition.name,
                    APIVersion.version,
                    APIVersion.method,
                    APIVersion.path,
                    APIVersion.canonical_contract,
                    APIVersion.contract_fingerprint,
                )
                .join(APIVersion, APIVersion.api_definition_id == APIDefinition.id)
                .where(
                    APIDefinition.project_id == project_id, APIDefinition.id == source_id, requested
                )
            )
        ).one_or_none()
        if row is None:
            return None
        name, revision, method, path, contract, fingerprint = row
        return AIPublicSource(
            project_id=project_id,
            metadata=AIPublicSourceMetadata(
                source_kind="api",
                source_id=source_id,
                name=name,
                version=revision,
                protocol="http",
                method=method,
                path=path,
                content_fingerprint=fingerprint,
            ),
            schema_document=cast(dict[str, JsonValue], contract) if contract else None,
            notices=[] if contract else ["该固定版本未提供完整规范契约。可补充手动 Schema。"],
        )

    async def _schema(self, project_id: UUID, source_id: UUID) -> AIPublicSource | None:
        row = (
            await self._session.execute(
                select(
                    SchemaArtifact.name,
                    SchemaArtifact.version,
                    SchemaArtifact.protocol,
                    SchemaArtifact.source_format,
                    SchemaArtifact.source_content,
                    SchemaArtifact.summary,
                    SchemaArtifact.content_sha256,
                ).where(SchemaArtifact.project_id == project_id, SchemaArtifact.id == source_id)
            )
        ).one_or_none()
        if row is None:
            return None
        name, version, protocol, source_format, content, summary, fingerprint = row
        document: dict[str, JsonValue] = {"protocol": protocol, "source_format": source_format}
        notices: list[str] = []
        if source_format in {
            "graphql_sdl",
            "graphql_introspection",
            "proto_source",
            "event_json_schema",
            "event_avro",
        }:
            try:
                document["schema_text"] = content.decode("utf-8")
            except UnicodeDecodeError:
                document["summary"] = cast(JsonValue, summary)
                notices.append("原版本文本无法按 UTF-8 读取。仅提供既有摘要。")
        else:
            document["summary"] = cast(JsonValue, summary)
            notices.append("该版本为二进制或反射产物。仅提供既有摘要。不发起反射或仓库扫描。")
        return AIPublicSource(
            project_id=project_id,
            metadata=AIPublicSourceMetadata(
                source_kind="schema",
                source_id=source_id,
                name=name,
                version=version,
                protocol=protocol,
                content_fingerprint=fingerprint,
            ),
            schema_document=document,
            notices=notices,
        )

    async def _execution(self, project_id: UUID, source_id: UUID) -> AIPublicSource | None:
        row = (
            await self._session.execute(
                select(
                    WorkflowExecution.workflow_id,
                    WorkflowExecution.workflow_version_id,
                    WorkflowExecution.status,
                    WorkflowExecution.error_code,
                    WorkflowExecution.error_message,
                    WorkflowExecution.started_at,
                    WorkflowExecution.completed_at,
                ).where(
                    WorkflowExecution.project_id == project_id, WorkflowExecution.id == source_id
                )
            )
        ).one_or_none()
        if row is None:
            return None
        workflow_id, revision_id, status, code, message, started_at, completed_at = row
        return AIPublicSource(
            project_id=project_id,
            metadata=AIPublicSourceMetadata(
                source_kind="execution",
                source_id=source_id,
                name=f"执行 {source_id}",
                workflow_id=workflow_id,
                workflow_version_id=revision_id,
                status=status,
                error_code=code,
                error_message=message,
                started_at=started_at,
                completed_at=completed_at,
            ),
            notices=["仅提供冻结执行身份、状态、时间和错误摘要。未读取运行变量、请求或响应正文。"],
        )
