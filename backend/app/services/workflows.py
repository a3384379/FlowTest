import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import httpx
import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import JsonValue, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.core.logging import redact
from app.domain.data_nodes import (
    CredentialKind,
    DataNodeValidationError,
    validate_read_only_sql,
    validate_redis_read,
)
from app.domain.expressions import SafeExpressionError, validate_safe_expression
from app.domain.test_assets import VersionChange, version_changes
from app.engine.contracts import (
    ApiNodeConfig,
    AssertNodeConfig,
    ConditionNodeConfig,
    DatasetNodeConfig,
    ExtractNodeConfig,
    ForEachNodeConfig,
    NodeType,
    RedisNodeConfig,
    SqlNodeConfig,
    SubFlowNodeConfig,
    WorkflowDefinition,
    WorkflowNode,
    parse_node_config,
)
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    NodeStatusCallback,
    WorkflowRunResult,
    WorkflowScheduler,
)
from app.models.access import Folder, Project, User
from app.models.artifacts import Artifact
from app.models.workflows import (
    Workflow,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)
from app.repositories.api_assets import APIAssetRepository
from app.repositories.data_sources import DataSourceRepository
from app.repositories.workflows import WorkflowRepository
from app.services.audit import AuditService
from app.services.datasets import WorkflowDatasetService
from app.services.projects import ProjectService
from app.services.workflow_runtime import WorkflowNodeExecutor
from app.services.workflow_snapshots import (
    PreparedExecution,
    PreparedWorkflow,
    WorkflowSnapshotBuilder,
)

SUPPORTED_NODE_TYPES = frozenset(NodeType)
CANCELLATION_POLL_SECONDS = 0.05
DATASET_CONCURRENCY = 5


@dataclass(frozen=True, slots=True)
class WorkflowRunPlan:
    execution_id: UUID
    actor_id: UUID
    project_id: UUID
    workflow_version: int
    definition: WorkflowDefinition
    prepared: PreparedExecution
    runtime_variables: dict[str, str]


@dataclass(frozen=True, slots=True)
class WorkflowBatchPlan:
    execution_id: UUID
    actor_id: UUID
    project_id: UUID
    workflow_version: int
    children: tuple[WorkflowRunPlan, ...]
    concurrency: int = DATASET_CONCURRENCY


WorkflowExecutionPlan = WorkflowRunPlan | WorkflowBatchPlan


@dataclass(frozen=True, slots=True)
class WorkflowVersionDiff:
    from_version: int
    to_version: int
    changes: tuple[VersionChange, ...]


class WorkflowService:
    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._workflows = WorkflowRepository(session)
        self._api_repository = APIAssetRepository(session)
        self._data_sources = DataSourceRepository(session)
        self._snapshots = WorkflowSnapshotBuilder(session)
        self._datasets = WorkflowDatasetService(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._secrets = secrets

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
        workflow = await self._get_workflow_for_update(project_id, workflow_id)
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
        workflow = await self._get_workflow_for_update(project_id, workflow_id)
        definition = self._load_definition(workflow.draft_definition)
        await self._validate_publishable(project_id, workflow.id, definition)
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

    async def diff_versions(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        from_version: int,
        to_version: int,
    ) -> WorkflowVersionDiff:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        workflow = await self._get_workflow(project_id, workflow_id)
        before = await self._find_version(workflow.id, from_version)
        after = await self._find_version(workflow.id, to_version)
        return WorkflowVersionDiff(
            from_version=from_version,
            to_version=to_version,
            changes=version_changes(
                cast(dict[str, JsonValue], before.definition),
                cast(dict[str, JsonValue], after.definition),
            ),
        )

    async def debug_to_breakpoint(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        environment_id: UUID,
        version: int | None,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        breakpoint_node_id: str,
    ) -> WorkflowRunResult:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        workflow = await self._get_workflow(project_id, workflow_id)
        selected = await self._select_version(workflow, version)
        definition = self._load_definition(selected.definition)
        scope = _upstream_node_ids(definition, breakpoint_node_id, include_target=False)
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
        if len(prepared.runs) != 1:
            raise AppError(
                code="DATASET_DEBUG_NOT_SUPPORTED",
                message="断点调试暂不支持 Dataset 批量执行",
                status_code=422,
            )
        result = await self._run_scoped(
            project_id=project_id,
            definition=definition,
            prepared=prepared.runs[0],
            runtime_variables=runtime_variables,
            selected_node_ids=scope,
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.debugged",
            resource_type="workflow",
            resource_id=workflow.id,
            details={
                "version": selected.version,
                "breakpoint_node_id": breakpoint_node_id,
            },
        )
        await self._session.commit()
        return result

    async def replay_node(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        node_id: str,
    ) -> WorkflowRunResult:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        execution = await self._get_execution(project_id, execution_id)
        plan = await self.load_execution_plan(execution.id)
        if isinstance(plan, WorkflowBatchPlan):
            raise AppError(
                code="DATASET_REPLAY_NOT_SUPPORTED",
                message="请在数据集子执行上重放节点",
                status_code=422,
            )
        scope = _upstream_node_ids(plan.definition, node_id, include_target=True)
        result = await self._run_scoped(
            project_id=project_id,
            definition=plan.definition,
            prepared=plan.prepared,
            runtime_variables=plan.runtime_variables,
            selected_node_ids=scope,
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.node_replayed",
            resource_type="workflow_execution",
            resource_id=execution.id,
            details={"node_id": node_id},
        )
        await self._session.commit()
        return result

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
        execution, plan = await self.prepare_execution(
            actor=actor,
            project_id=project_id,
            workflow_id=workflow_id,
            environment_id=environment_id,
            version=version,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
        )
        if isinstance(plan, WorkflowBatchPlan):
            raise AppError(
                code="DATASET_REQUIRES_COORDINATOR",
                message="数据集工作流必须通过后台协调器运行",
                status_code=500,
            )
        return await self.run_prepared(execution=execution, plan=plan)

    async def prepare_execution(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        environment_id: UUID,
        version: int | None,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
    ) -> tuple[WorkflowExecution, WorkflowExecutionPlan]:
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
        await self._ensure_execution_capacity(project_id)
        if prepared.snapshot["dataset"] is None:
            execution = await self._start_execution(
                actor=actor,
                project_id=project_id,
                workflow=workflow,
                version=selected,
                environment_id=environment_id,
                snapshot=prepared.runs[0].snapshot,
            )
            plan: WorkflowExecutionPlan = self._run_plan(
                execution=execution,
                actor=actor,
                project_id=project_id,
                workflow_version=selected.version,
                definition=definition,
                prepared=prepared.runs[0],
                runtime_variables=runtime_variables,
            )
        else:
            execution, plan = await self._start_dataset_execution(
                actor=actor,
                project_id=project_id,
                workflow=workflow,
                version=selected,
                environment_id=environment_id,
                definition=definition,
                prepared=prepared,
                runtime_variables=runtime_variables,
            )
        await self._persist_execution_plan(execution, plan)
        return execution, plan

    async def _ensure_execution_capacity(self, project_id: UUID) -> None:
        result = await self._session.execute(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        active = await self._session.scalar(
            select(func.count())
            .select_from(WorkflowExecution)
            .where(
                WorkflowExecution.project_id == project_id,
                WorkflowExecution.parent_execution_id.is_(None),
                WorkflowExecution.status == "running",
            )
        )
        if int(active or 0) >= project.execution_concurrency_limit:
            raise AppError(
                code="PROJECT_CONCURRENCY_EXCEEDED",
                message="项目并发执行配额已用尽",
                status_code=429,
                details={"limit": project.execution_concurrency_limit},
            )

    async def load_execution_plan(self, execution_id: UUID) -> WorkflowExecutionPlan:
        from app.services.workflow_plan_codec import decode_execution_plan

        execution = await self.load_execution_for_run(execution_id)
        if execution.run_payload_ciphertext is None or execution.run_payload_nonce is None:
            raise AppError(
                code="WORKFLOW_PLAN_NOT_FOUND",
                message="工作流执行计划不存在",
                status_code=409,
            )
        payload = self._secrets.decrypt(
            EncryptedValue(
                ciphertext=execution.run_payload_ciphertext,
                nonce=execution.run_payload_nonce,
            ),
            associated_data=_execution_plan_associated_data(execution.id),
        )
        return decode_execution_plan(payload)

    async def _persist_execution_plan(
        self, execution: WorkflowExecution, plan: WorkflowExecutionPlan
    ) -> None:
        from app.services.workflow_plan_codec import encode_execution_plan

        encrypted = self._secrets.encrypt(
            encode_execution_plan(plan),
            associated_data=_execution_plan_associated_data(execution.id),
        )
        execution.run_payload_ciphertext = encrypted.ciphertext
        execution.run_payload_nonce = encrypted.nonce
        await self._session.commit()
        await self._session.refresh(execution)

    async def run_prepared(
        self,
        *,
        execution: WorkflowExecution,
        plan: WorkflowRunPlan,
        on_node_status: NodeStatusCallback | None = None,
    ) -> tuple[WorkflowExecution, list[WorkflowNodeExecution]]:
        token = CancellationToken()
        if execution.cancel_requested_at is not None:
            token.cancel()
        network_policy = await self._projects.load_runtime_security_policy(plan.project_id)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            scheduler = WorkflowScheduler(
                WorkflowNodeExecutor(
                    client,
                    plan.prepared.requests,
                    plan.definition,
                    network_policy,
                    subflows=plan.prepared.subflows,
                    data_nodes=plan.prepared.data_nodes,
                )
            )
            result = await self._run_with_cancellation_poll(
                scheduler=scheduler,
                definition=plan.definition,
                execution=execution,
                token=token,
                workflow_variables=plan.definition.variables,
                dataset_variables=plan.prepared.dataset_variables,
                runtime_variables=plan.runtime_variables,
                on_node_status=on_node_status,
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
            actor_user_id=plan.actor_id,
            project_id=plan.project_id,
            action="workflow.executed",
            resource_type="workflow_execution",
            resource_id=execution.id,
            details={"status": result.status.value, "workflow_version": plan.workflow_version},
        )
        await self._session.commit()
        await self._session.refresh(execution)
        return execution, nodes

    async def _run_scoped(
        self,
        *,
        project_id: UUID,
        definition: WorkflowDefinition,
        prepared: PreparedExecution,
        runtime_variables: dict[str, str],
        selected_node_ids: frozenset[str],
    ) -> WorkflowRunResult:
        network_policy = await self._projects.load_runtime_security_policy(project_id)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            result = await WorkflowScheduler(
                WorkflowNodeExecutor(
                    client,
                    prepared.requests,
                    definition,
                    network_policy,
                    subflows=prepared.subflows,
                    data_nodes=prepared.data_nodes,
                )
            ).run(
                definition,
                context=ExecutionContext(
                    workflow_variables=cast(dict[str, JsonValue], definition.variables),
                    dataset_variables=prepared.dataset_variables,
                    runtime_variables=cast(dict[str, JsonValue], runtime_variables),
                ),
                selected_node_ids=selected_node_ids,
            )
        return WorkflowRunResult(
            status=result.status,
            records=tuple(
                replace(record, output=cast(JsonValue, redact(record.output)))
                for record in result.records
            ),
            context=cast(dict[str, JsonValue], redact(result.context)),
        )

    async def load_execution_for_run(self, execution_id: UUID) -> WorkflowExecution:
        execution = await self._workflows.get_execution(execution_id)
        if execution is None:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND",
                message="工作流执行不存在",
                status_code=404,
            )
        return execution

    async def mark_runtime_failed(self, execution_id: UUID) -> WorkflowExecution:
        execution = await self.load_execution_for_run(execution_id)
        execution.status = "failed"
        execution.error_code = "WORKFLOW_RUNTIME_ERROR"
        execution.error_message = "工作流运行服务发生内部错误"
        execution.completed_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(execution)
        return execution

    async def cancel_incomplete_batch(self, execution_id: UUID) -> None:
        children = await self._workflows.list_child_executions(execution_id)
        completed_at = datetime.now(UTC)
        for child in children:
            if child.status != "running":
                continue
            child.status = "cancelled"
            child.error_code = "DATASET_RUNNER_STOPPED"
            child.error_message = "数据集子执行在运行服务停止时被取消"
            child.cancel_requested_at = child.cancel_requested_at or completed_at
            child.completed_at = completed_at
        await self._session.commit()

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
            requested_at = datetime.now(UTC)
            execution.cancel_requested_at = requested_at
            await self._workflows.request_child_cancellation(execution.id, requested_at)
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
    ) -> tuple[
        WorkflowExecution,
        list[WorkflowNodeExecution],
        list[WorkflowExecution],
    ]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        execution = await self._get_execution(project_id, execution_id)
        nodes = await self._workflows.list_node_executions(execution.id)
        children = await self._workflows.list_child_executions(execution.id)
        return execution, nodes, children

    async def complete_batch(self, execution_id: UUID) -> WorkflowExecution:
        execution = await self.load_execution_for_run(execution_id)
        children = await self._workflows.list_child_executions(execution_id)
        if not children or any(child.status == "running" for child in children):
            raise AppError(
                code="DATASET_EXECUTION_INCOMPLETE",
                message="数据集子执行尚未全部完成",
                status_code=409,
            )
        counts = {
            status: sum(child.status == status for child in children)
            for status in ("passed", "failed", "cancelled")
        }
        if counts["failed"]:
            execution.status = "failed"
            execution.error_code = "DATASET_ROWS_FAILED"
            execution.error_message = f"{counts['failed']} 个数据集子执行失败"
        elif counts["cancelled"]:
            execution.status = "cancelled"
            execution.error_code = "DATASET_ROWS_CANCELLED"
            execution.error_message = f"{counts['cancelled']} 个数据集子执行已取消"
        else:
            execution.status = "passed"
        execution.context = {
            "dataset_summary": {
                "total": len(children),
                **counts,
            }
        }
        execution.completed_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=execution.triggered_by_id,
            project_id=execution.project_id,
            action="workflow.dataset_executed",
            resource_type="workflow_execution",
            resource_id=execution.id,
            details=cast(dict[str, JsonValue], execution.context["dataset_summary"]),
        )
        await self._session.commit()
        await self._session.refresh(execution)
        return execution

    async def _validate_publishable(
        self,
        project_id: UUID,
        workflow_id: UUID,
        definition: WorkflowDefinition,
    ) -> None:
        unsupported = sorted(
            {node.type.value for node in definition.nodes if node.type not in SUPPORTED_NODE_TYPES}
        )
        if unsupported:
            raise AppError(
                code="UNSUPPORTED_NODE_TYPE",
                message="草稿包含当前版本尚未支持的节点",
                status_code=422,
                details={"node_types": unsupported},
            )
        for node in definition.nodes:
            await self._validate_publishable_node(project_id, definition, node)
        for edge in definition.edges:
            for mapping in edge.mappings:
                self._validate_jmespath(mapping.source.path, edge.id)
        if any(node.type is NodeType.DATASET for node in definition.nodes):
            await self._datasets.prepare(project_id=project_id, definition=definition)
        await self._validate_subflow_graph(
            project_id=project_id,
            definition=definition,
            workflow_path=(workflow_id,),
        )

    async def _validate_publishable_node(
        self,
        project_id: UUID,
        definition: WorkflowDefinition,
        node: WorkflowNode,
    ) -> None:
        try:
            config = parse_node_config(node)
        except (ValidationError, ValueError) as error:
            raise AppError(
                code="INVALID_NODE_CONFIG",
                message=f"节点 {node.name} 配置无效",
                status_code=422,
                details={"node_id": node.id},
            ) from error
        await self._validate_resource_node(project_id, node, config)
        self._validate_control_node(definition, node, config)
        if isinstance(config, (SubFlowNodeConfig, ForEachNodeConfig)):
            await self._load_subflow_version(project_id, config)

    async def _validate_resource_node(
        self,
        project_id: UUID,
        node: WorkflowNode,
        config: object,
    ) -> None:
        if isinstance(config, ApiNodeConfig):
            definition_model = await self._api_repository.get_definition(config.api_definition_id)
            if definition_model is None or definition_model.project_id != project_id:
                raise AppError(
                    code="WORKFLOW_API_NOT_FOUND",
                    message=f"API 节点 {node.name} 引用的接口不存在",
                    status_code=422,
                    details={"node_id": node.id},
                )
        if isinstance(config, DatasetNodeConfig):
            artifact = await self._session.get(Artifact, config.artifact_id)
            if artifact is None or artifact.project_id != project_id:
                raise AppError(
                    code="ARTIFACT_NOT_FOUND",
                    message=f"Dataset 节点 {node.name} 引用的文件不存在",
                    status_code=422,
                    details={"node_id": node.id},
                )
        if isinstance(config, (SqlNodeConfig, RedisNodeConfig)):
            await self._validate_data_node(project_id, node, config)

    def _validate_control_node(
        self,
        definition: WorkflowDefinition,
        node: WorkflowNode,
        config: object,
    ) -> None:
        if isinstance(config, (ExtractNodeConfig, AssertNodeConfig, ConditionNodeConfig)):
            self._validate_control_source(
                definition,
                {node.id for node in definition.nodes},
                node.id,
                config.source_node_id,
            )
            self._validate_jmespath(config.expression, node.id)
        if isinstance(config, ForEachNodeConfig):
            self._validate_control_source(
                definition,
                {item.id for item in definition.nodes},
                node.id,
                config.source_node_id,
            )
            try:
                validate_safe_expression(config.expression)
            except SafeExpressionError as error:
                raise AppError(
                    code=error.code,
                    message=error.message,
                    status_code=422,
                    details={"node_id": node.id},
                ) from error

    async def _validate_data_node(
        self,
        project_id: UUID,
        node: WorkflowNode,
        config: SqlNodeConfig | RedisNodeConfig,
    ) -> None:
        credential = await self._data_sources.get_credential(config.credential_id)
        if credential is None or credential.project_id != project_id:
            raise AppError(
                code="CREDENTIAL_NOT_FOUND",
                message=f"数据节点 {node.name} 引用的 Credential 不存在",
                status_code=422,
                details={"node_id": node.id},
            )
        kind = CredentialKind(credential.kind)
        try:
            if isinstance(config, SqlNodeConfig):
                if kind is CredentialKind.REDIS:
                    raise DataNodeValidationError("SQL 节点不能使用 Redis Credential")
                validate_read_only_sql(config.query, kind)
            else:
                if kind is not CredentialKind.REDIS:
                    raise DataNodeValidationError("Redis 节点必须使用 Redis Credential")
                validate_redis_read(config.command, config.arguments)
        except DataNodeValidationError as error:
            raise AppError(
                code="UNSAFE_DATA_NODE",
                message=str(error),
                status_code=422,
                details={"node_id": node.id},
            ) from error

    async def _validate_subflow_graph(
        self,
        *,
        project_id: UUID,
        definition: WorkflowDefinition,
        workflow_path: tuple[UUID, ...],
    ) -> None:
        for node in definition.nodes:
            config = parse_node_config(node)
            if not isinstance(config, (SubFlowNodeConfig, ForEachNodeConfig)):
                continue
            if config.workflow_id in workflow_path:
                raise AppError(
                    code="SUBFLOW_RECURSION",
                    message="子流程调用图不能包含递归",
                    status_code=422,
                    details={
                        "node_id": node.id,
                        "workflow_path": [
                            str(item) for item in (*workflow_path, config.workflow_id)
                        ],
                    },
                )
            if len(workflow_path) >= 5:
                raise AppError(
                    code="SUBFLOW_DEPTH_EXCEEDED",
                    message="子流程最大嵌套深度为 5",
                    status_code=422,
                    details={"node_id": node.id},
                )
            version = await self._load_subflow_version(project_id, config)
            nested = self._load_definition(version.definition)
            if any(item.type is NodeType.DATASET for item in nested.nodes):
                raise AppError(
                    code="SUBFLOW_DATASET_NOT_SUPPORTED",
                    message="子流程暂不支持 Dataset 节点",
                    status_code=422,
                    details={"node_id": node.id},
                )
            await self._validate_subflow_graph(
                project_id=project_id,
                definition=nested,
                workflow_path=(*workflow_path, config.workflow_id),
            )

    async def _load_subflow_version(
        self,
        project_id: UUID,
        config: SubFlowNodeConfig | ForEachNodeConfig,
    ) -> WorkflowVersion:
        workflow = await self._workflows.get(config.workflow_id)
        version = await self._workflows.find_version(
            config.workflow_id,
            config.workflow_version,
        )
        if workflow is None or workflow.project_id != project_id or version is None:
            raise AppError(
                code="SUBFLOW_VERSION_NOT_FOUND",
                message="子流程只能引用同项目中已发布的版本",
                status_code=422,
            )
        return version

    @staticmethod
    def _validate_control_source(
        definition: WorkflowDefinition,
        node_ids: set[str],
        node_id: str,
        source_node_id: str,
    ) -> None:
        if source_node_id not in node_ids or not _is_upstream(definition, source_node_id, node_id):
            raise AppError(
                code="INVALID_NODE_SOURCE",
                message="控制节点的数据源必须是其上游节点",
                status_code=422,
                details={"node_id": node_id, "source_node_id": source_node_id},
            )

    @staticmethod
    def _validate_jmespath(expression: str, resource_id: str) -> None:
        try:
            jmespath.compile(expression)
        except JMESPathError as error:
            raise AppError(
                code="INVALID_JMESPATH",
                message="JMESPath 表达式无效",
                status_code=422,
                details={"resource_id": resource_id},
            ) from error

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
        execution = self._execution_model(
            actor=actor,
            project_id=project_id,
            workflow=workflow,
            version=version,
            environment_id=environment_id,
            snapshot=snapshot,
        )
        self._workflows.add(execution)
        await self._session.commit()
        await self._session.refresh(execution)
        return execution

    async def _start_dataset_execution(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow: Workflow,
        version: WorkflowVersion,
        environment_id: UUID,
        definition: WorkflowDefinition,
        prepared: PreparedWorkflow,
        runtime_variables: dict[str, str],
    ) -> tuple[WorkflowExecution, WorkflowBatchPlan]:
        parent = self._execution_model(
            actor=actor,
            project_id=project_id,
            workflow=workflow,
            version=version,
            environment_id=environment_id,
            snapshot=prepared.snapshot,
        )
        children = [
            self._execution_model(
                actor=actor,
                project_id=project_id,
                workflow=workflow,
                version=version,
                environment_id=environment_id,
                snapshot=run.snapshot,
                parent_execution_id=parent.id,
                dataset_row_index=index,
            )
            for index, run in enumerate(prepared.runs)
        ]
        self._workflows.add(parent)
        self._workflows.add_all(children)
        await self._session.commit()
        await self._session.refresh(parent)
        plans = tuple(
            self._run_plan(
                execution=child,
                actor=actor,
                project_id=project_id,
                workflow_version=version.version,
                definition=definition,
                prepared=run,
                runtime_variables=runtime_variables,
            )
            for child, run in zip(children, prepared.runs, strict=True)
        )
        return parent, WorkflowBatchPlan(
            execution_id=parent.id,
            actor_id=actor.id,
            project_id=project_id,
            workflow_version=version.version,
            children=plans,
        )

    @staticmethod
    def _execution_model(
        *,
        actor: User,
        project_id: UUID,
        workflow: Workflow,
        version: WorkflowVersion,
        environment_id: UUID,
        snapshot: dict[str, JsonValue],
        parent_execution_id: UUID | None = None,
        dataset_row_index: int | None = None,
    ) -> WorkflowExecution:
        return WorkflowExecution(
            id=uuid4(),
            project_id=project_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            environment_id=environment_id,
            triggered_by_id=actor.id,
            parent_execution_id=parent_execution_id,
            dataset_row_index=dataset_row_index,
            status="running",
            snapshot=snapshot,
            context={},
            error_code=None,
            error_message=None,
            cancel_requested_at=None,
            started_at=datetime.now(UTC),
            completed_at=None,
        )

    @staticmethod
    def _run_plan(
        *,
        execution: WorkflowExecution,
        actor: User,
        project_id: UUID,
        workflow_version: int,
        definition: WorkflowDefinition,
        prepared: PreparedExecution,
        runtime_variables: dict[str, str],
    ) -> WorkflowRunPlan:
        return WorkflowRunPlan(
            execution_id=execution.id,
            actor_id=actor.id,
            project_id=project_id,
            workflow_version=workflow_version,
            definition=definition,
            prepared=prepared,
            runtime_variables=dict(runtime_variables),
        )

    async def _run_with_cancellation_poll(
        self,
        *,
        scheduler: WorkflowScheduler,
        definition: WorkflowDefinition,
        execution: WorkflowExecution,
        token: CancellationToken,
        workflow_variables: dict[str, str],
        dataset_variables: dict[str, JsonValue],
        runtime_variables: dict[str, str],
        on_node_status: NodeStatusCallback | None,
    ) -> WorkflowRunResult:
        task = asyncio.create_task(
            scheduler.run(
                definition,
                context=ExecutionContext(
                    workflow_variables=cast(dict[str, JsonValue], workflow_variables),
                    dataset_variables=dataset_variables,
                    runtime_variables=cast(dict[str, JsonValue], runtime_variables),
                ),
                cancellation=token,
                on_node_status=on_node_status,
            )
        )
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=CANCELLATION_POLL_SECONDS)
                await self._session.refresh(execution, attribute_names=["cancel_requested_at"])
                if execution.cancel_requested_at is not None:
                    token.cancel()
            return await task
        except asyncio.CancelledError:
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

    async def _find_version(self, workflow_id: UUID, version: int) -> WorkflowVersion:
        model = await self._workflows.find_version(workflow_id, version)
        if model is None:
            raise AppError(
                code="WORKFLOW_VERSION_NOT_FOUND",
                message="工作流版本不存在",
                status_code=404,
            )
        return model

    async def _get_workflow(self, project_id: UUID, workflow_id: UUID) -> Workflow:
        workflow = await self._workflows.get(workflow_id)
        if workflow is None or workflow.project_id != project_id:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
        return workflow

    async def _get_workflow_for_update(self, project_id: UUID, workflow_id: UUID) -> Workflow:
        workflow = await self._workflows.get_for_update(workflow_id)
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


def _execution_plan_associated_data(execution_id: UUID) -> bytes:
    return f"workflow-execution:{execution_id}:run-plan".encode()


def _is_upstream(definition: WorkflowDefinition, source_id: str, target_id: str) -> bool:
    outgoing: dict[str, set[str]] = {node.id: set() for node in definition.nodes}
    for edge in definition.edges:
        outgoing[edge.source].add(edge.target)
    pending = [source_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(outgoing[current] - visited)
    return False


def _upstream_node_ids(
    definition: WorkflowDefinition,
    target_id: str,
    *,
    include_target: bool,
) -> frozenset[str]:
    node_ids = {node.id for node in definition.nodes}
    if target_id not in node_ids:
        raise AppError(
            code="WORKFLOW_NODE_NOT_FOUND",
            message="工作流节点不存在",
            status_code=404,
            details={"node_id": target_id},
        )
    incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in definition.edges:
        incoming[edge.target].add(edge.source)
    selected: set[str] = {target_id} if include_target else set()
    pending = list(incoming[target_id])
    while pending:
        current = pending.pop()
        if current in selected:
            continue
        selected.add(current)
        pending.extend(incoming[current] - selected)
    return frozenset(selected)
