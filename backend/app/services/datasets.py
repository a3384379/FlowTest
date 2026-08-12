from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.datasets import DatasetParseError, ParsedDataset, parse_dataset
from app.engine.capabilities import legacy_node_adapter
from app.engine.contracts import (
    DatasetNodeConfig,
    NodeType,
    WorkflowDefinition,
    parse_node_config,
)
from app.services.artifacts import ArtifactService


@dataclass(frozen=True, slots=True)
class PreparedDataset:
    artifact_id: UUID
    filename: str
    sha256: str
    parsed: ParsedDataset

    def snapshot(self, *, row_index: int | None = None, row: JsonValue = None) -> JsonValue:
        return {
            "artifact_id": str(self.artifact_id),
            "filename": self.filename,
            "sha256": self.sha256,
            "format": self.parsed.format.value,
            "columns": list(self.parsed.columns),
            "row_count": len(self.parsed.rows),
            "row_index": row_index,
            "row": row,
        }


class WorkflowDatasetService:
    def __init__(self, session: AsyncSession) -> None:
        self._artifacts = ArtifactService(session)

    async def prepare(
        self,
        *,
        project_id: UUID,
        definition: WorkflowDefinition,
    ) -> PreparedDataset | None:
        dataset_node = next(
            (node for node in definition.nodes if node.effective_type is NodeType.DATASET),
            None,
        )
        if dataset_node is None:
            return None
        config = parse_node_config(legacy_node_adapter.as_legacy_node(dataset_node))
        if not isinstance(config, DatasetNodeConfig):
            raise AppError(
                code="INVALID_NODE_CONFIG",
                message=f"Dataset 节点 {dataset_node.name} 配置无效",
                status_code=422,
            )
        loaded = await self._artifacts.load(
            project_id=project_id,
            artifact_id=config.artifact_id,
        )
        try:
            parsed = parse_dataset(
                filename=loaded.artifact.filename,
                content=loaded.content,
                requested_format=config.format,
                sheet_name=config.sheet_name,
            )
        except DatasetParseError as error:
            raise AppError(code=error.code, message=error.message, status_code=422) from error
        return PreparedDataset(
            artifact_id=loaded.artifact.id,
            filename=loaded.artifact.filename,
            sha256=loaded.artifact.sha256,
            parsed=parsed,
        )
