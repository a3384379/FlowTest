"""Build bounded read-only projections without exporting payloads or authentication data."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion
from app.models.durable_execution import ExecutionCheckpoint
from app.models.tasking import TestPlanRunItem
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution
from app.repositories.tasking import TaskingRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.execution_evidence import (
    APIBindingEvidenceResponse,
    AssertionEvidenceResponse,
    ControlRecordEvidenceResponse,
    ControlRecordsEvidenceResponse,
    ExecutionEvidenceResponse,
    NodeEvidenceResponse,
    PlanItemEvidenceResponse,
    PlanRunEvidenceResponse,
)
from app.services.projects import ProjectService


class ExecutionEvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._workflows = WorkflowRepository(session)
        self._tasking = TaskingRepository(session)

    async def plan_run(
        self, *, actor: User, project_id: UUID, run_id: UUID, page: int, page_size: int
    ) -> PlanRunEvidenceResponse:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        run = await self._tasking.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="TEST_PLAN_RUN_NOT_FOUND", message="计划运行不存在", status_code=404
            )
        query = select(TestPlanRunItem).where(TestPlanRunItem.test_plan_run_id == run_id)
        total = int(
            await self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        )
        rows = (
            await self._session.scalars(
                query.order_by(TestPlanRunItem.position)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = tuple([await self._plan_item(item) for item in rows])
        return PlanRunEvidenceResponse(
            run_id=run.id,
            project_id=project_id,
            test_plan_id=run.test_plan_id,
            status=run.status,
            trigger_type=run.trigger_type,
            completed_at=_aware(run.completed_at),
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=page * page_size < total,
            truncated=total > 100000,
        )

    async def _plan_item(self, item: TestPlanRunItem) -> PlanItemEvidenceResponse:
        query = (
            select(WorkflowExecution.id)
            .where(WorkflowExecution.source_plan_run_item_id == item.id)
            .order_by(WorkflowExecution.started_at, WorkflowExecution.id)
        )
        ids = tuple((await self._session.scalars(query.limit(101))).all())
        return PlanItemEvidenceResponse(
            id=item.id,
            target_type=item.target_type,
            target_id=item.target_id,
            target_version=item.target_version,
            target_snapshot_digest=_digest(item.target_snapshot),
            workflow_id=item.workflow_id,
            workflow_version=item.workflow_version,
            environment_id=item.environment_id,
            status=item.status,
            attempts=item.attempts,
            execution_id=item.workflow_execution_id,
            execution_ids=ids[:100],
            attempts_complete=len(ids) == item.attempts and len(ids) <= 100,
        )

    async def execution(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> ExecutionEvidenceResponse:
        execution = await self._execution(actor, project_id, execution_id)
        query = select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.workflow_execution_id == execution_id
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        )
        nodes = (
            await self._session.scalars(
                query.order_by(WorkflowNodeExecution.created_at, WorkflowNodeExecution.id).limit(
                    1000
                )
            )
        ).all()
        bindings, complete = await self._api_bindings(project_id, execution.snapshot)
        nested_nodes, nested_total = await self._nested_nodes(project_id, execution_id)
        workflow = execution.snapshot.get("workflow")
        fingerprint = workflow.get("fingerprint") if isinstance(workflow, dict) else None
        from app.services.execution_evidence_additional import AdditionalExecutionEvidence

        additional = await AdditionalExecutionEvidence(self._session, self._api_bindings).collect(
            project_id, execution
        )
        return ExecutionEvidenceResponse(
            parent_execution_id=execution.parent_execution_id,
            dataset_row_index=execution.dataset_row_index,
            dataset=additional.dataset,
            children=additional.children,
            children_total=additional.children_total,
            children_complete=additional.children_complete,
            subflows=additional.subflows,
            subflows_complete=additional.subflows_complete,
            execution_id=execution.id,
            project_id=execution.project_id,
            workflow_id=execution.workflow_id,
            workflow_version_id=execution.workflow_version_id,
            environment_id=execution.environment_id,
            status=execution.status,
            main_status=execution.main_status,
            cleanup_status=execution.cleanup_status,
            error_code=execution.error_code,
            run_purpose=execution.run_purpose,
            source_case_id=execution.source_case_id,
            source_case_version=execution.source_case_version,
            source_plan_run_item_id=execution.source_plan_run_item_id,
            started_at=_aware(execution.started_at),
            completed_at=_aware(execution.completed_at),
            snapshot_digest=_digest(execution.snapshot),
            workflow_fingerprint=_valid_digest(fingerprint),
            api_bindings=bindings,
            bindings_complete=complete,
            nodes=tuple(_node_evidence(node) for node in nodes),
            node_total=total,
            truncated=total > len(nodes),
            nested_nodes=nested_nodes,
            nested_node_total=nested_total,
            nested_nodes_complete=nested_total == len(nested_nodes),
        )

    async def _nested_nodes(
        self, project_id: UUID, execution_id: UUID
    ) -> tuple[tuple[NodeEvidenceResponse, ...], int]:
        query = select(ExecutionCheckpoint).where(
            ExecutionCheckpoint.project_id == project_id,
            ExecutionCheckpoint.execution_id == execution_id,
            ExecutionCheckpoint.node_id.startswith("__nested_request__:", autoescape=True),
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        )
        rows = (
            await self._session.scalars(
                query.order_by(ExecutionCheckpoint.node_id, ExecutionCheckpoint.attempt).limit(1000)
            )
        ).all()
        return tuple(_checkpoint_evidence(row) for row in rows), total

    async def _execution(
        self, actor: User, project_id: UUID, execution_id: UUID
    ) -> WorkflowExecution:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        execution = await self._workflows.get_execution(execution_id)
        if execution is None or execution.project_id != project_id:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND", message="工作流执行不存在", status_code=404
            )
        return execution

    async def _api_bindings(
        self, project_id: UUID, snapshot: dict[str, object]
    ) -> tuple[tuple[APIBindingEvidenceResponse, ...], bool]:
        apis = snapshot.get("apis")
        if not isinstance(apis, dict):
            return (), False
        bindings: list[APIBindingEvidenceResponse] = []
        complete = len(apis) <= 1000
        for node_id, api in list(apis.items())[:1000]:
            binding = await self._api_binding(project_id, str(node_id), api)
            if binding is None:
                complete = False
            else:
                bindings.append(binding)
        return tuple(bindings), complete

    async def _api_binding(
        self, project_id: UUID, node_id: str, api: object
    ) -> APIBindingEvidenceResponse | None:
        if not isinstance(api, dict):
            return None
        definition_id, version_id = _uuid(api.get("definition_id")), _uuid(api.get("version_id"))
        if definition_id is None or version_id is None:
            return None
        definition = await self._session.get(APIDefinition, definition_id)
        version = await self._session.get(APIVersion, version_id)
        if (
            definition is None
            or version is None
            or definition.project_id != project_id
            or version.api_definition_id != definition_id
            or version.version != api.get("version")
        ):
            return None
        return APIBindingEvidenceResponse(
            node_id=node_id,
            api_definition_id=definition_id,
            api_version_id=version_id,
            api_version=version.version,
            contract_fingerprint=_valid_digest(version.contract_fingerprint),
        )

    async def control_records(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        node_id: str,
        kind: Literal["iteration", "branch"],
        page: int,
        page_size: int,
    ) -> ControlRecordsEvidenceResponse:
        await self._execution(actor, project_id, execution_id)
        records, total = await self._workflows.list_control_records(
            execution_id=execution_id,
            node_id=node_id,
            kind=kind,
            test_verdict=None,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return ControlRecordsEvidenceResponse(
            execution_id=execution_id,
            node_id=node_id,
            kind=kind,
            items=tuple(
                ControlRecordEvidenceResponse(
                    ordinal=item.ordinal, status=item.status, test_verdict=item.test_verdict
                )
                for item in records
            ),
            total=total,
            page=page,
            page_size=page_size,
            has_more=page * page_size < total,
            truncated=total > 100000,
        )


def _node_evidence(node: WorkflowNodeExecution) -> NodeEvidenceResponse:
    assertions, complete = _assertions(node)
    return NodeEvidenceResponse(
        node_id=node.node_id,
        node_type=node.node_type,
        phase=node.phase,
        status=node.status,
        attempts=node.attempts,
        error_code=node.error_code,
        assertions=assertions,
        assertions_complete=complete,
    )


def _assertions(
    node: WorkflowNodeExecution | ExecutionCheckpoint,
) -> tuple[tuple[AssertionEvidenceResponse, ...], bool]:
    result = node.result or {}
    values = result.get("assertions")
    if isinstance(values, list) and values:
        items = [_assertion(value) for value in values[:100]]
        return tuple(item for item in items if item is not None), len(
            values
        ) <= 100 and None not in items
    output = node.output
    if node.node_type == "assert" and isinstance(output, dict):
        assertion = _assertion({**output, "name": "workflow_assertion"})
        return (() if assertion is None else (assertion,)), assertion is not None
    return (), node.node_type != "assert"


def _checkpoint_evidence(node: ExecutionCheckpoint) -> NodeEvidenceResponse:
    assertions, complete = _assertions(node)
    error = node.result.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return NodeEvidenceResponse(
        node_id=node.node_id,
        node_type=node.node_type,
        phase=node.phase,
        status=node.status,
        attempts=node.attempt,
        error_code=code if isinstance(code, str) else None,
        assertions=assertions,
        assertions_complete=complete,
    )


def _assertion(value: object) -> AssertionEvidenceResponse | None:
    if not isinstance(value, dict) or not isinstance(value.get("passed"), bool):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name or "expected" not in value or "actual" not in value:
        return None
    return AssertionEvidenceResponse(
        name=name[:200],
        passed=value["passed"],
        expected_digest=_digest(value["expected"]),
        actual_digest=_digest(value["actual"]),
    )


def _digest(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _valid_digest(value: object) -> str | None:
    if isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
        return value
    return None


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value
