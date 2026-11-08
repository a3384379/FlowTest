"""Safe dependency metadata for CI observers; never response/context values."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifacts import Artifact
from app.models.workflows import Workflow, WorkflowExecution, WorkflowVersion
from app.schemas.execution_evidence import (
    APIBindingEvidenceResponse,
    DatasetBindingEvidenceResponse,
    DatasetChildReferenceEvidenceResponse,
    SubflowBindingEvidenceResponse,
)

BindingReader = Callable[
    [UUID, dict[str, object]], Awaitable[tuple[tuple[APIBindingEvidenceResponse, ...], bool]]
]


@dataclass(frozen=True)
class AdditionalEvidence:
    dataset: DatasetBindingEvidenceResponse | None
    children: tuple[DatasetChildReferenceEvidenceResponse, ...]
    children_total: int
    children_complete: bool
    subflows: tuple[SubflowBindingEvidenceResponse, ...]
    subflows_complete: bool


class AdditionalExecutionEvidence:
    def __init__(self, session: AsyncSession, bindings: BindingReader) -> None:
        self._session = session
        self._bindings = bindings

    async def collect(self, project: UUID, execution: WorkflowExecution) -> AdditionalEvidence:
        children, total, complete = await self._children(project, execution.id)
        subflows, sources_complete = await self._subflows(project, execution.snapshot)
        dataset = await self._dataset(project, execution.snapshot)
        complete = complete and (not children or dataset is not None)
        if execution.parent_execution_id is None and dataset is not None:
            complete = complete and dataset.row_count == total
        return AdditionalEvidence(
            dataset,
            children,
            total,
            complete,
            subflows,
            sources_complete,
        )

    async def _children(
        self, project: UUID, execution: UUID
    ) -> tuple[tuple[DatasetChildReferenceEvidenceResponse, ...], int, bool]:
        query = select(WorkflowExecution).where(
            WorkflowExecution.project_id == project,
            WorkflowExecution.parent_execution_id == execution,
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        )
        rows = (
            await self._session.scalars(
                query.order_by(WorkflowExecution.dataset_row_index).limit(500)
            )
        ).all()
        valid = [
            row
            for row in rows
            if row.dataset_row_index is not None and 0 <= row.dataset_row_index < 500
        ]
        children = tuple(
            DatasetChildReferenceEvidenceResponse(
                execution_id=row.id, row_index=row.dataset_row_index, status=row.status
            )
            for row in valid
        )
        return children, total, len(children) == total

    async def _dataset(
        self, project: UUID, snapshot: dict[str, object]
    ) -> DatasetBindingEvidenceResponse | None:
        value = snapshot.get("dataset")
        if not isinstance(value, dict):
            return None
        identity = _uuid(value.get("artifact_id"))
        count = value.get("row_count")
        if identity is None or type(count) is not int or not 1 <= count <= 500:
            return None
        artifact = await self._session.get(Artifact, identity)
        if (
            artifact is None
            or artifact.project_id != project
            or artifact.sha256 != value.get("sha256")
        ):
            return None
        return DatasetBindingEvidenceResponse(
            artifact_id=identity, sha256=artifact.sha256, row_count=count
        )

    async def _subflows(
        self, project: UUID, snapshot: dict[str, object]
    ) -> tuple[tuple[SubflowBindingEvidenceResponse, ...], bool]:
        pending: list[tuple[tuple[str, ...], dict[str, object]]] = [((), snapshot)]
        result: list[SubflowBindingEvidenceResponse] = []
        complete = True
        while pending and len(result) < 100:
            path, parent = pending.pop()
            children = parent.get("subflows", {})
            if not isinstance(children, dict):
                complete = False
                continue
            for name, child in children.items():
                if (
                    not isinstance(name, str)
                    or not 1 <= len(name) <= 128
                    or not isinstance(child, dict)
                    or len(path) >= 5
                ):
                    complete = False
                    continue
                binding = await self._subflow(project, (*path, name), child)
                if binding is None:
                    complete = False
                    continue
                result.append(binding)
                pending.append(((*path, name), child))
                if len(result) >= 100:
                    break
        return tuple(sorted(result, key=lambda value: value.path)), complete and not pending

    async def _subflow(
        self, project: UUID, path: tuple[str, ...], snapshot: dict[str, object]
    ) -> SubflowBindingEvidenceResponse | None:
        value = snapshot.get("workflow")
        if not isinstance(value, dict):
            return None
        workflow_id, version_id = _uuid(value.get("id")), _uuid(value.get("version_id"))
        if workflow_id is None or version_id is None:
            return None
        workflow = await self._session.get(Workflow, workflow_id)
        version = await self._session.get(WorkflowVersion, version_id)
        if (
            workflow is None
            or workflow.project_id != project
            or version is None
            or version.workflow_id != workflow.id
            or version.version != value.get("version")
            or version.fingerprint != value.get("fingerprint")
        ):
            return None
        apis, complete = await self._bindings(project, snapshot)
        return SubflowBindingEvidenceResponse(
            path=path,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            workflow_version=version.version,
            workflow_fingerprint=version.fingerprint,
            api_bindings=apis[:500],
            complete=complete and len(apis) <= 500,
        )


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
