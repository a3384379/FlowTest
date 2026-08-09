import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx
from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import redact
from app.engine.contracts import (
    NodeType,
    WorkflowDefinition,
    parse_api_node_config,
)
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    WorkflowRunResult,
    WorkflowScheduler,
)
from app.models.access import Folder, User
from app.models.workflows import (
    Workflow,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)
from app.repositories.api_assets import APIAssetRepository
from app.repositories.workflows import WorkflowRepository
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.workflow_runtime import WorkflowNodeExecutor
from app.services.workflow_snapshots import WorkflowSnapshotBuilder

SUPPORTED_S5_NODE_TYPES = frozenset({NodeType.START, NodeType.API, NodeType.END})
CANCELLATION_POLL_SECONDS = 0.05


class WorkflowService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workflows = WorkflowRepository(session)
        self._api_repository = APIAssetRepository(session)
        self._snapshots = WorkflowSnapshotBuilder(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def list_workflows(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[Workflow], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._workflows.list_workflows(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        description: str,
        folder_id: UUID | None,
        definition: WorkflowDefinition,
    ) -> Workflow:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        await self._validate_folder(project_id, folder_id)
        normalized_name = name.strip()
        await self._ensure_unique_name(project_id, normalized_name)
        workflow = Workflow(
            project_id=project_id,
            folder_id=folder_id,
            name=normalized_name,
            description=description.strip(),
            draft_definition=definition.model_dump(mode="json"),
            draft_revision=1,
            current_version=None,
            created_by_id=actor.id,
        )
        self._workflows.add(workflow)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.created",
            resource_type="workflow",
            resource_id=workflow.id,
        )
        await self._session.commit()
        await self._session.refresh(workflow)
        return workflow

    async def get(self, *, actor: User, project_id: UUID, workflow_id: UUID) -> Workflow:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._get_workflow(project_id, workflow_id)

    async def update_draft(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        expected_revision: int,
        name: str | None,
        description: str | None,
        folder_id: UUID | None,
        change_folder: bool,
        definition: WorkflowDefinition | None,
    ) -> Workflow:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        workflow = await self._get_workflow(project_id, workflow_id)
        if workflow.draft_revision != expected_revision:
            raise AppError(
                code="WORKFLOW_DRAFT_CONFLICT",
                message="草稿已被其他操作更新, 请刷新后重试",
                status_code=409,
                details={"current_revision": workflow.draft_revision},
            )
        if name is not None:
            normalized_name = name.strip()
            await self._ensure_unique_name(
                project_id,
                normalized_name,
                excluding_id=workflow.id,
            )
            workflow.name = normalized_name
        if description is not None:
            workflow.description = description.strip()
        if change_folder:
            await self._validate_folder(project_id, folder_id)
            workflow.folder_id = folder_id
        if definition is not None:
            workflow.draft_definition = definition.model_dump(mode="json")
        workflow.draft_revision += 1
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.draft_updated",
            resource_type="workflow",
            resource_id=workflow.id,
            details={"draft_revision": workflow.draft_revision},
        )
        await self._session.commit()
        await self._session.refresh(workflow)
        return workflow

    async def publish(self, *, actor: User, project_id: UUID, workflow_id: UUID) -> WorkflowVersion:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        workflow = await self._get_workflow(project_id, workflow_id)
        definition = self._load_definition(workflow.draft_definition)
        await self._validate_publishable(project_id, definition)
        next_version = (workflow.current_version or 0) + 1
        serialized = definition.model_dump(mode="json")
        published = WorkflowVersion(
            workflow_id=workflow.id,
            version=next_version,
            definition=serialized,
            fingerprint=_fingerprint(serialized),
            created_by_id=actor.id,
            published_at=datetime.now(UTC),
        )
        self._workflows.add(published)
        workflow.current_version = next_version
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.published",
            resource_type="workflow",
            resource_id=workflow.id,
            details={"version": next_version},
        )
        await self._session.commit()
        await self._session.refresh(published)
        return published

    async def list_versions(
        self, *, actor: User, project_id: UUID, workflow_id: UUID
    ) -> list[WorkflowVersion]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        await self._get_workflow(project_id, workflow_id)
        return await self._workflows.list_versions(workflow_id)

    async def execute(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        environment_id: UUID,
        version: int | None,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
    ) -> tuple[WorkflowExecution, list[WorkflowNodeExecution]]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        workflow = await self._get_workflow(project_id, workflow_id)
        selected = await self._select_version(workflow, version)
        definition = self._load_definition(selected.definition)
        prepared = await self._snapshots.prepare(
            actor=actor,
            project_id=project_id,
            workflow=workflow,
            version=selected,
            definition=definition,
            environment_id=environment_id,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
        )
        execution = await self._start_execution(
            actor=actor,
            project_id=project_id,
            workflow=workflow,
            version=selected,
            environment_id=environment_id,
            snapshot=prepared.snapshot,
        )
        token = CancellationToken()
        async with httpx.AsyncClient(follow_redirects=False) as client:
            scheduler = WorkflowScheduler(WorkflowNodeExecutor(client, prepared.requests))
            result = await self._run_with_cancellation_poll(
                scheduler=scheduler,
                definition=definition,
                execution=execution,
                token=token,
                runtime_variables=runtime_variables,
            )
        nodes = self._node_models(execution.id, result)
        self._workflows.add_all(nodes)
        execution.status = result.status.value
        execution.context = cast(dict[str, JsonValue], redact(result.context))
        execution.completed_at = datetime.now(UTC)
        failed = next(
            (record for record in result.records if record.status.value == "failed"), None
        )
        if failed is not None:
            execution.error_code = failed.error_code
            execution.error_message = failed.error_message
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.executed",
            resource_type="workflow_execution",
            resource_id=execution.id,
            details={"status": result.status.value, "workflow_version": selected.version},
        )
        await self._session.commit()
        await self._session.refresh(execution)
        for node in nodes:
            await self._session.refresh(node)
        return execution, nodes

    async def request_cancel(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> WorkflowExecution:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        execution = await self._get_execution(project_id, execution_id)
        if execution.status != "running":
            raise AppError(
                code="WORKFLOW_EXECUTION_FINISHED",
                message="工作流执行已结束, 不能取消",
                status_code=409,
            )
        if execution.cancel_requested_at is None:
            execution.cancel_requested_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(execution)
        return execution

    async def list_executions(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[WorkflowExecution], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._workflows.list_executions(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get_execution(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> tuple[WorkflowExecution, list[WorkflowNodeExecution]]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        execution = await self._get_execution(project_id, execution_id)
        nodes = await self._workflows.list_node_executions(execution.id)
        return execution, nodes

    async def _validate_publishable(self, project_id: UUID, definition: WorkflowDefinition) -> None:
        unsupported = sorted(
            {
                node.type.value
                for node in definition.nodes
                if node.type not in SUPPORTED_S5_NODE_TYPES
            }
        )
        if unsupported:
            raise AppError(
                code="UNSUPPORTED_NODE_TYPE",
                message="草稿包含当前版本尚未支持的节点",
                status_code=422,
                details={"node_types": unsupported},
            )
        for node in definition.nodes:
            if node.type is not NodeType.API:
                if node.config:
                    raise AppError(
                        code="INVALID_NODE_CONFIG",
                        message=f"节点 {node.name} 不接受配置项",
                        status_code=422,
                    )
                continue
            try:
                config = parse_api_node_config(node)
            except (ValidationError, ValueError) as error:
                raise AppError(
                    code="INVALID_NODE_CONFIG",
                    message=f"API 节点 {node.name} 配置无效",
                    status_code=422,
                    details={"node_id": node.id},
                ) from error
            definition_model = await self._api_repository.get_definition(config.api_definition_id)
            if definition_model is None or definition_model.project_id != project_id:
                raise AppError(
                    code="WORKFLOW_API_NOT_FOUND",
                    message=f"API 节点 {node.name} 引用的接口不存在",
                    status_code=422,
                    details={"node_id": node.id},
                )

    async def _start_execution(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow: Workflow,
        version: WorkflowVersion,
        environment_id: UUID,
        snapshot: dict[str, JsonValue],
    ) -> WorkflowExecution:
        execution = WorkflowExecution(
            project_id=project_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            environment_id=environment_id,
            triggered_by_id=actor.id,
            status="running",
            snapshot=snapshot,
            context={},
            error_code=None,
            error_message=None,
            cancel_requested_at=None,
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        self._workflows.add(execution)
        await self._session.commit()
        await self._session.refresh(execution)
        return execution

    async def _run_with_cancellation_poll(
        self,
        *,
        scheduler: WorkflowScheduler,
        definition: WorkflowDefinition,
        execution: WorkflowExecution,
        token: CancellationToken,
        runtime_variables: dict[str, str],
    ) -> WorkflowRunResult:
        task = asyncio.create_task(
            scheduler.run(
                definition,
                context=ExecutionContext(
                    runtime_variables=cast(dict[str, JsonValue], runtime_variables)
                ),
                cancellation=token,
            )
        )
        while not task.done():
            await asyncio.wait({task}, timeout=CANCELLATION_POLL_SECONDS)
            await self._session.refresh(execution, attribute_names=["cancel_requested_at"])
            if execution.cancel_requested_at is not None:
                token.cancel()
        return await task

    async def _select_version(self, workflow: Workflow, requested: int | None) -> WorkflowVersion:
        selected_number = requested or workflow.current_version
        if selected_number is None:
            raise AppError(
                code="WORKFLOW_NOT_PUBLISHED",
                message="工作流尚未发布",
                status_code=409,
            )
        version = await self._workflows.find_version(workflow.id, selected_number)
        if version is None:
            raise AppError(
                code="WORKFLOW_VERSION_NOT_FOUND",
                message="工作流版本不存在",
                status_code=404,
            )
        return version

    async def _get_workflow(self, project_id: UUID, workflow_id: UUID) -> Workflow:
        workflow = await self._workflows.get(workflow_id)
        if workflow is None or workflow.project_id != project_id:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
        return workflow

    async def _get_execution(self, project_id: UUID, execution_id: UUID) -> WorkflowExecution:
        execution = await self._workflows.get_execution(execution_id)
        if execution is None or execution.project_id != project_id:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND",
                message="工作流执行不存在",
                status_code=404,
            )
        return execution

    async def _ensure_unique_name(
        self, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        if await self._workflows.name_exists(
            project_id=project_id,
            name=name,
            excluding_id=excluding_id,
        ):
            raise AppError(
                code="WORKFLOW_NAME_EXISTS",
                message="工作流名称已存在",
                status_code=409,
            )

    async def _validate_folder(self, project_id: UUID, folder_id: UUID | None) -> None:
        if folder_id is None:
            return
        folder = await self._session.get(Folder, folder_id)
        if folder is None or folder.project_id != project_id:
            raise AppError(code="FOLDER_NOT_FOUND", message="目录不存在", status_code=404)

    @staticmethod
    def _load_definition(value: dict[str, object]) -> WorkflowDefinition:
        try:
            return WorkflowDefinition.model_validate(value)
        except ValidationError as error:
            raise AppError(
                code="INVALID_WORKFLOW_DEFINITION",
                message="工作流定义无效",
                status_code=422,
            ) from error

    @staticmethod
    def _node_models(execution_id: UUID, result: WorkflowRunResult) -> list[WorkflowNodeExecution]:
        return [
            WorkflowNodeExecution(
                workflow_execution_id=execution_id,
                node_id=record.node_id,
                node_type=record.node_type.value,
                name=record.name,
                status=record.status.value,
                attempts=record.attempts,
                output=cast(JsonValue, redact(record.output)),
                error_code=record.error_code,
                error_message=record.error_message,
                started_at=record.started_at,
                completed_at=record.completed_at,
            )
            for record in result.records
        ]


def _fingerprint(definition: dict[str, object]) -> str:
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
