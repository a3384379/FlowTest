import asyncio
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import httpx
import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import JsonValue, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_trace_id
from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.core.logging import redact
from app.domain.api_assets import BodyKind
from app.domain.data_nodes import (
    CredentialKind,
    DataNodeValidationError,
    validate_read_only_sql,
    validate_redis_read,
)
from app.domain.durable_execution import is_resumable_checkpoint
from app.domain.event_protocols import EventSourceKind
from app.domain.expressions import SafeExpressionError, validate_safe_expression
from app.domain.governance import QuotaDimension
from app.domain.protocols import (
    GrpcCallType,
    ProtocolKind,
    ProtocolSchemaError,
    validate_graphql_operation,
)
from app.domain.sandbox_preview import PreviewBudget, WorkflowRunPurpose
from app.domain.test_assets import VersionChange, version_changes
from app.engine.capabilities import builtin_capability_registry, legacy_node_adapter
from app.engine.contracts import (
    ApiNodeConfig,
    ApiNodeMultipartBody,
    AssertNodeConfig,
    CleanupRunWhen,
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
    WorkflowPhase,
    parse_node_config,
)
from app.engine.event_nodes import (
    KafkaConsumeCapabilityConfig,
    KafkaProduceCapabilityConfig,
    WebSocketAwaitCapabilityConfig,
    WebSocketCloseCapabilityConfig,
    WebSocketConnectCapabilityConfig,
    WebSocketExchangeCapabilityConfig,
    WebSocketSendCapabilityConfig,
    parse_event_config,
)
from app.engine.protocol_nodes import (
    GraphQLCapabilityConfig,
    GrpcCapabilityConfig,
    parse_protocol_config,
)
from app.engine.scheduler import (
    CancellationToken,
    ExecutionContext,
    NodeRunRecord,
    NodeStatusCallback,
    RequestBudget,
    WorkflowRunResult,
    WorkflowScheduler,
    node_type_consumes_request,
)
from app.models.access import Folder, Project, User
from app.models.artifacts import Artifact
from app.models.runner_fabric import RunnerTask
from app.models.workflows import (
    Workflow,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)
from app.observability.tracing import TracingNodeExecutor, workflow_span
from app.repositories.api_assets import APIAssetRepository
from app.repositories.data_sources import DataSourceRepository
from app.repositories.workflows import WorkflowRepository
from app.runner.results import (
    RunnerBatchExecutionResult,
    RunnerExecutionResult,
    RunnerSingleExecutionResult,
)
from app.services.audit import AuditService
from app.services.credentials import ExternalCredentialSecretStore
from app.services.datasets import WorkflowDatasetService
from app.services.durable_execution import DurableExecutionService, checkpoint_to_node_record
from app.services.encryption_keys import active_key_reference_for_project
from app.services.event_sources import EventSourceService
from app.services.organization_governance import OrganizationQuotaService
from app.services.projects import ProjectService
from app.services.protocol_assets import ProtocolAssetService
from app.services.workflow_runtime import PreparedSubflow, WorkflowNodeExecutor
from app.services.workflow_snapshots import (
    PreparedExecution,
    PreparedWorkflow,
    WorkflowSnapshotBuilder,
)

SUPPORTED_NODE_TYPES = frozenset(NodeType)
CANCELLATION_POLL_SECONDS = 0.05
DATASET_CONCURRENCY = 5
_PREVIEW_UNCLASSIFIED_CAPABILITIES = frozenset(
    {
        "graphql.request",
        "grpc.call",
        "kafka.produce",
        "kafka.consume",
        "websocket.connect",
        "websocket.send",
        "websocket.await",
        "websocket.close",
        "websocket.exchange",
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowRunPlan:
    execution_id: UUID
    actor_id: UUID
    project_id: UUID
    workflow_version: int
    definition: WorkflowDefinition
    prepared: PreparedExecution
    runtime_variables: dict[str, str]
    request_budget: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowBatchPlan:
    execution_id: UUID
    actor_id: UUID
    project_id: UUID
    workflow_version: int
    children: tuple[WorkflowRunPlan, ...]
    concurrency: int = DATASET_CONCURRENCY
    max_runtime_seconds: int | None = None
    cleanup_timeout_seconds: int | None = None


WorkflowExecutionPlan = WorkflowRunPlan | WorkflowBatchPlan


@dataclass(frozen=True, slots=True)
class WorkflowVersionDiff:
    from_version: int
    to_version: int
    changes: tuple[VersionChange, ...]


class WorkflowService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        secrets: SecretBox = secret_box,
        external_secrets: ExternalCredentialSecretStore | None = None,
    ) -> None:
        self._session = session
        self._workflows = WorkflowRepository(session)
        self._api_repository = APIAssetRepository(session)
        self._data_sources = DataSourceRepository(session)
        self._snapshots = WorkflowSnapshotBuilder(session, external_secrets=external_secrets)
        self._datasets = WorkflowDatasetService(session)
        self._projects = ProjectService(session)
        self._protocol_assets = ProtocolAssetService(session)
        self._event_sources = EventSourceService(session)
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
        commit: bool = True,
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
            draft_definition=definition.model_dump(mode="json", exclude_none=True),
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
        if commit:
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
        commit: bool = True,
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
            workflow.draft_definition = definition.model_dump(mode="json", exclude_none=True)
        workflow.draft_revision += 1
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="workflow.draft_updated",
            resource_type="workflow",
            resource_id=workflow.id,
            details={"draft_revision": workflow.draft_revision},
        )
        if commit:
            await self._session.commit()
            await self._session.refresh(workflow)
        else:
            await self._session.flush()
        return workflow

    async def publish(self, *, actor: User, project_id: UUID, workflow_id: UUID) -> WorkflowVersion:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        workflow = await self._get_workflow_for_update(project_id, workflow_id)
        definition = self._load_definition(workflow.draft_definition)
        await self._validate_publishable(project_id, workflow.id, definition)
        definition = await self._pin_api_versions(definition)
        next_version = (workflow.current_version or 0) + 1
        serialized = definition.model_dump(mode="json", exclude_none=True)
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

    async def _pin_api_versions(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        nodes: list[WorkflowNode] = []
        for node in definition.nodes:
            if node.effective_type is not NodeType.API:
                nodes.append(node)
                continue
            config = parse_node_config(legacy_node_adapter.as_legacy_node(node))
            if not isinstance(config, ApiNodeConfig) or config.api_version is not None:
                nodes.append(node)
                continue
            api_definition = await self._api_repository.get_definition(config.api_definition_id)
            if api_definition is None:
                nodes.append(node)
                continue
            nodes.append(_with_api_version(node, api_definition.current_version))
        return definition.model_copy(update={"nodes": nodes})

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
        if execution.run_purpose == WorkflowRunPurpose.PREVIEW.value:
            raise AppError(
                code="PREVIEW_REPLAY_FORBIDDEN",
                message="Sandbox Preview 不支持节点重放, 请重新审批后发起新预览",
                status_code=409,
            )
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

    async def prepare_preview_execution(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID | None,
        change_set_id: UUID,
        approval_id: UUID,
        proposal_fingerprint: str,
        context_fingerprint: str,
        definition: WorkflowDefinition,
        environment_id: UUID,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        budget: PreviewBudget,
    ) -> tuple[WorkflowExecution, WorkflowExecutionPlan]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        if workflow_id is not None:
            await self._get_workflow(project_id, workflow_id)
        bounded = _bounded_preview_definition(definition, budget)
        await self._validate_publishable(project_id, workflow_id or change_set_id, bounded)
        prepared = await self._snapshots.prepare_preview(
            actor=actor,
            project_id=project_id,
            workflow_id=workflow_id,
            definition=bounded,
            fingerprint=proposal_fingerprint,
            environment_id=environment_id,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
        )
        prepared = _bounded_preview_prepared_workflow(prepared, budget)
        _validate_preview_target_classification(bounded, prepared.runs[0].subflows)
        request_limits = _preview_request_limits(bounded, prepared, budget)
        await self._ensure_execution_capacity(project_id)
        execution, plan = self._preview_execution_plan(
            actor=actor,
            project_id=project_id,
            workflow_id=workflow_id,
            change_set_id=change_set_id,
            approval_id=approval_id,
            proposal_fingerprint=proposal_fingerprint,
            context_fingerprint=context_fingerprint,
            definition=bounded,
            environment_id=environment_id,
            prepared=prepared,
            runtime_variables=runtime_variables,
            budget=budget,
            request_limits=request_limits,
        )
        await self._stage_execution_plan(execution, plan)
        await self._session.flush()
        return execution, plan

    async def prepare_preview_target_fingerprint(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID | None,
        change_set_id: UUID,
        proposal_fingerprint: str,
        definition: WorkflowDefinition,
        environment_id: UUID,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        budget: PreviewBudget,
    ) -> str:
        """Prepare, but do not persist, the exact targets governed by an approval."""

        if workflow_id is not None:
            await self._get_workflow(project_id, workflow_id)
        bounded = _bounded_preview_definition(definition, budget)
        await self._validate_publishable(project_id, workflow_id or change_set_id, bounded)
        prepared = await self._snapshots.prepare_preview(
            actor=actor,
            project_id=project_id,
            workflow_id=workflow_id,
            definition=bounded,
            fingerprint=proposal_fingerprint,
            environment_id=environment_id,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
        )
        prepared = _bounded_preview_prepared_workflow(prepared, budget)
        _validate_preview_target_classification(bounded, prepared.runs[0].subflows)
        _preview_request_limits(bounded, prepared, budget)
        return _prepared_preview_target_fingerprint(prepared)

    async def discard_prepared_execution(self, execution_id: UUID) -> None:
        """Remove an uncommitted preview plan rejected by the final target binding."""

        await self._session.execute(
            delete(WorkflowExecution).where(WorkflowExecution.parent_execution_id == execution_id)
        )
        await self._session.execute(
            delete(WorkflowExecution).where(WorkflowExecution.id == execution_id)
        )
        await self._session.flush()

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
        await OrganizationQuotaService(self._session).enforce(
            organization_id=project.organization_id,
            dimension=QuotaDimension.EXECUTION_CONCURRENCY,
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
        await self._stage_execution_plan(execution, plan)
        await self._session.commit()
        await self._session.refresh(execution)

    async def _stage_execution_plan(
        self, execution: WorkflowExecution, plan: WorkflowExecutionPlan
    ) -> None:
        from app.services.workflow_plan_codec import encode_execution_plan

        encrypted = self._secrets.encrypt(
            encode_execution_plan(plan),
            associated_data=_execution_plan_associated_data(execution.id),
            key_reference=await active_key_reference_for_project(
                self._session, execution.project_id
            ),
        )
        execution.run_payload_ciphertext = encrypted.ciphertext
        execution.run_payload_nonce = encrypted.nonce

    async def run_prepared(
        self,
        *,
        execution: WorkflowExecution,
        plan: WorkflowRunPlan,
        on_node_status: NodeStatusCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> tuple[WorkflowExecution, list[WorkflowNodeExecution]]:
        token = cancellation or CancellationToken()
        if execution.cancel_requested_at is not None:
            token.cancel(force=execution.force_cancel_requested_at is not None)
        network_policy = await self._projects.load_runtime_security_policy(plan.project_id)
        from app.repositories.durable_execution import DurableExecutionRepository

        checkpoint_history = await DurableExecutionRepository(self._session).list_checkpoints(
            execution.id
        )
        shared_request_budget = _remaining_preview_request_budget(
            plan.request_budget,
            tuple(checkpoint_to_node_record(item) for item in checkpoint_history),
        )
        reset_retry_budget = await DurableExecutionService(self._session).reset_retry_budget(
            execution.id
        )
        checkpoints = [item for item in checkpoint_history if is_resumable_checkpoint(item.status)]
        resume_attempts = {
            node_id: max(item.attempt for item in checkpoint_history if item.node_id == node_id)
            for node_id in {item.node_id for item in checkpoint_history}
        }
        context = ExecutionContext(
            workflow_variables=cast(dict[str, JsonValue], plan.definition.variables),
            dataset_variables=plan.prepared.dataset_variables,
            runtime_variables=cast(dict[str, JsonValue], plan.runtime_variables),
        )
        for checkpoint in checkpoints:
            context.restore_checkpoint(
                node_id=checkpoint.node_id,
                output=cast(JsonValue, checkpoint.output),
                extracted_variables=cast(dict[str, JsonValue], checkpoint.extracted_variables),
            )
        resume_records = tuple(checkpoint_to_node_record(item) for item in checkpoint_history)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            node_executor = WorkflowNodeExecutor(
                client,
                plan.prepared.requests,
                plan.definition,
                network_policy,
                subflows=plan.prepared.subflows,
                data_nodes=plan.prepared.data_nodes,
                protocol_nodes=plan.prepared.protocol_nodes,
                event_nodes=plan.prepared.event_nodes,
            )
            scheduler = WorkflowScheduler(TracingNodeExecutor(node_executor))
            try:
                with workflow_span(
                    execution_id=execution.id,
                    project_id=plan.project_id,
                    workflow_version=plan.workflow_version,
                ):
                    result = await self._run_with_cancellation_poll(
                        scheduler=scheduler,
                        definition=plan.definition,
                        execution=execution,
                        token=token,
                        workflow_variables=plan.definition.variables,
                        dataset_variables=plan.prepared.dataset_variables,
                        runtime_variables=plan.runtime_variables,
                        on_node_status=on_node_status,
                        context=context,
                        resume_records=resume_records,
                        resume_attempts=resume_attempts,
                        reset_retry_budget=reset_retry_budget,
                        shared_request_budget=shared_request_budget,
                    )
            finally:
                await node_executor.close()
        result = _with_preview_budget_usage(
            result,
            limit=plan.request_budget,
            budget=shared_request_budget,
        )
        nodes = self._node_models(execution.id, result)
        await self._workflows.replace_node_executions(execution.id, nodes)
        self._stage_run_result(execution=execution, plan=plan, result=result)
        await self._session.commit()
        await self._session.refresh(execution)
        return execution, nodes

    async def stage_remote_result(
        self,
        *,
        plan: WorkflowExecutionPlan,
        submitted: RunnerExecutionResult,
    ) -> WorkflowExecution:
        """Stage a fenced runner result in the caller's database transaction."""
        if isinstance(plan, WorkflowRunPlan) and isinstance(submitted, RunnerSingleExecutionResult):
            self._validate_remote_execution_id(plan.execution_id, submitted.execution_id)
            execution = await self.load_execution_for_run(plan.execution_id)
            nodes = self._node_models(execution.id, submitted.result.to_domain())
            await self._workflows.replace_node_executions(execution.id, nodes)
            self._stage_run_result(
                execution=execution,
                plan=plan,
                result=submitted.result.to_domain(),
            )
            return execution
        if isinstance(plan, WorkflowBatchPlan) and isinstance(
            submitted, RunnerBatchExecutionResult
        ):
            return await self._stage_remote_batch(plan, submitted)
        raise AppError(
            code="RUNNER_RESULT_PLAN_MISMATCH",
            message="Runner 结果类型与执行计划不匹配",
            status_code=409,
        )

    async def _stage_remote_batch(
        self,
        plan: WorkflowBatchPlan,
        submitted: RunnerBatchExecutionResult,
    ) -> WorkflowExecution:
        self._validate_remote_execution_id(plan.execution_id, submitted.execution_id)
        expected = {child.execution_id: child for child in plan.children}
        received = {child.execution_id: child for child in submitted.children}
        if expected.keys() != received.keys():
            raise AppError(
                code="RUNNER_BATCH_RESULT_INCOMPLETE",
                message="Runner 数据集结果与计划子执行不一致",
                status_code=409,
            )
        children: list[WorkflowExecution] = []
        for execution_id, child_plan in expected.items():
            execution = await self.load_execution_for_run(execution_id)
            nodes = self._node_models(execution.id, received[execution_id].result.to_domain())
            await self._workflows.replace_node_executions(execution.id, nodes)
            self._stage_run_result(
                execution=execution,
                plan=child_plan,
                result=received[execution_id].result.to_domain(),
            )
            children.append(execution)
        parent = await self.load_execution_for_run(plan.execution_id)
        self._stage_batch_completion(parent, children)
        return parent

    def _stage_run_result(
        self,
        *,
        execution: WorkflowExecution,
        plan: WorkflowRunPlan,
        result: WorkflowRunResult,
    ) -> None:
        execution.status = result.status.value
        execution.main_status = (result.main_status or result.status).value
        execution.cleanup_status = (
            result.cleanup_status.value if result.cleanup_status is not None else None
        )
        execution.cleanup_report = cast(
            dict[str, JsonValue],
            redact(asdict(result.cleanup_report)) if result.cleanup_report is not None else {},
        )
        execution.context = cast(dict[str, JsonValue], redact(result.context))
        execution.completed_at = datetime.now(UTC)
        if execution.run_purpose == WorkflowRunPurpose.PREVIEW.value:
            execution.preview_evidence = _preview_run_evidence(execution, plan, result)
        failed = next(
            (
                record
                for record in result.records
                if record.status.value == "failed"
                and (record.phase.value == "main" or not record.best_effort)
            ),
            None,
        )
        if failed is not None:
            execution.error_code = failed.error_code
            execution.error_message = failed.error_message
        self._audit.record(
            actor_user_id=plan.actor_id,
            project_id=plan.project_id,
            action=(
                "sandbox_preview.executed"
                if execution.run_purpose == WorkflowRunPurpose.PREVIEW.value
                else "workflow.executed"
            ),
            resource_type="workflow_execution",
            resource_id=execution.id,
            details={
                "status": result.status.value,
                "main_status": execution.main_status,
                "cleanup_status": execution.cleanup_status,
                "cleanup_warning_count": len(
                    result.cleanup_report.warnings if result.cleanup_report is not None else ()
                ),
                "workflow_version": plan.workflow_version,
            },
        )

    @staticmethod
    def _validate_remote_execution_id(expected: UUID, received: UUID) -> None:
        if expected != received:
            raise AppError(
                code="RUNNER_RESULT_EXECUTION_MISMATCH",
                message="Runner 结果不属于当前执行",
                status_code=409,
            )

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
            node_executor = WorkflowNodeExecutor(
                client,
                prepared.requests,
                definition,
                network_policy,
                subflows=prepared.subflows,
                data_nodes=prepared.data_nodes,
                protocol_nodes=prepared.protocol_nodes,
                event_nodes=prepared.event_nodes,
            )
            try:
                result = await WorkflowScheduler(TracingNodeExecutor(node_executor)).run(
                    definition,
                    context=ExecutionContext(
                        workflow_variables=cast(dict[str, JsonValue], definition.variables),
                        dataset_variables=prepared.dataset_variables,
                        runtime_variables=cast(dict[str, JsonValue], runtime_variables),
                    ),
                    selected_node_ids=selected_node_ids,
                )
            finally:
                await node_executor.close()
        return WorkflowRunResult(
            status=result.status,
            records=tuple(
                replace(
                    record,
                    output=cast(JsonValue, redact(record.output)),
                    result=record.result.model_copy(
                        update={"output": cast(JsonValue, redact(record.result.output))}
                    ),
                )
                for record in result.records
            ),
            context=cast(dict[str, JsonValue], redact(result.context)),
            main_status=result.main_status,
            cleanup_status=result.cleanup_status,
            cleanup_report=result.cleanup_report,
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
        execution = await self.stage_runtime_failed(
            execution_id,
            error_code="WORKFLOW_RUNTIME_ERROR",
            error_message="工作流运行服务发生内部错误",
        )
        await self._session.commit()
        await self._session.refresh(execution)
        return execution

    async def stage_runtime_failed(
        self,
        execution_id: UUID,
        *,
        error_code: str,
        error_message: str,
    ) -> WorkflowExecution:
        execution = await self.load_execution_for_run(execution_id)
        execution.status = "failed"
        execution.error_code = error_code
        execution.error_message = error_message
        execution.completed_at = datetime.now(UTC)
        children = await self._workflows.list_child_executions(execution_id)
        for child in children:
            if child.status not in {"queued", "running"}:
                continue
            child.status = "cancelled"
            child.error_code = error_code
            child.error_message = error_message
            child.completed_at = execution.completed_at
        return execution

    async def cancel_incomplete_batch(
        self,
        execution_id: UUID,
        *,
        error_code: str = "DATASET_RUNNER_STOPPED",
        error_message: str = "数据集子执行在运行服务停止时被取消",
    ) -> None:
        children = await self._workflows.list_child_executions(execution_id)
        completed_at = datetime.now(UTC)
        for child in children:
            if child.status not in {"queued", "running"}:
                continue
            child.status = "cancelled"
            child.error_code = error_code
            child.error_message = error_message
            child.cancel_requested_at = child.cancel_requested_at or completed_at
            child.completed_at = completed_at
        await self._session.commit()

    async def request_cancel(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        force: bool = False,
        reason: str | None = None,
    ) -> WorkflowExecution:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        if force and (reason is None or not reason.strip()):
            raise AppError(
                code="FORCE_CANCEL_REASON_REQUIRED",
                message="强制取消必须提供审计原因",
                status_code=422,
            )
        execution = await self._get_execution(project_id, execution_id)
        if execution.status not in {"queued", "running"}:
            raise AppError(
                code="WORKFLOW_EXECUTION_FINISHED",
                message="工作流执行已结束, 不能取消",
                status_code=409,
            )
        changed = execution.cancel_requested_at is None or (
            force and execution.force_cancel_requested_at is None
        )
        if changed:
            requested_at = execution.cancel_requested_at or datetime.now(UTC)
            execution.cancel_requested_at = requested_at
            if force:
                execution.force_cancel_requested_at = datetime.now(UTC)
                execution.force_cancel_reason = reason.strip() if reason is not None else None
            await self._workflows.request_child_cancellation(execution.id, requested_at)
            for child in await self._workflows.list_child_executions(execution.id):
                if force and child.status in {"queued", "running"}:
                    child.force_cancel_requested_at = execution.force_cancel_requested_at
                    child.force_cancel_reason = execution.force_cancel_reason
                if child.status != "queued":
                    continue
                child.status = "cancelled"
                child.error_code = "WORKFLOW_CANCELLED"
                child.error_message = "数据集子执行在排队期间被取消"
                child.cancel_requested_at = requested_at
                child.completed_at = requested_at
            if execution.status == "queued":
                execution.status = "cancelled"
                execution.error_code = "WORKFLOW_CANCELLED"
                execution.error_message = "工作流在排队期间被取消"
                execution.completed_at = requested_at
                task = await self._session.scalar(
                    select(RunnerTask).where(RunnerTask.execution_id == execution.id)
                )
                if task is not None and task.status == "queued":
                    task.status = "cancelled"
                    task.completed_at = requested_at
            self._audit.record(
                actor_user_id=actor.id,
                project_id=project_id,
                action=(
                    "workflow.force_cancel_requested" if force else "workflow.cancel_requested"
                ),
                resource_type="workflow_execution",
                resource_id=execution.id,
                details={
                    "force": force,
                    "reason_present": bool(reason),
                },
            )
            await self._session.commit()
            await self._session.refresh(execution)
        return execution

    async def list_executions(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[WorkflowExecution], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._workflows.list_executions(
            project_id=project_id,
            workflow_id=workflow_id,
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
        if not children or any(child.status in {"queued", "running"} for child in children):
            raise AppError(
                code="DATASET_EXECUTION_INCOMPLETE",
                message="数据集子执行尚未全部完成",
                status_code=409,
            )
        self._stage_batch_completion(execution, children)
        await self._session.commit()
        await self._session.refresh(execution)
        return execution

    def _stage_batch_completion(
        self, execution: WorkflowExecution, children: list[WorkflowExecution]
    ) -> None:
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
        if execution.run_purpose == WorkflowRunPurpose.PREVIEW.value:
            execution.preview_evidence = _preview_batch_evidence(execution, children)
        self._audit.record(
            actor_user_id=execution.triggered_by_id,
            project_id=execution.project_id,
            action=(
                "sandbox_preview.dataset_executed"
                if execution.run_purpose == WorkflowRunPurpose.PREVIEW.value
                else "workflow.dataset_executed"
            ),
            resource_type="workflow_execution",
            resource_id=execution.id,
            details=cast(dict[str, JsonValue], execution.context["dataset_summary"]),
        )

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
        self._validate_websocket_session_graph(definition)
        for edge in definition.edges:
            for mapping in edge.mappings:
                self._validate_jmespath(mapping.source.path, edge.id)
        if any(node.effective_type is NodeType.DATASET for node in definition.nodes):
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
            if node.type is NodeType.CAPABILITY:
                if not settings.feature_capability_sdk_enabled:
                    raise AppError(
                        code="CAPABILITY_SDK_DISABLED",
                        message="V3 Capability SDK 尚未启用",
                        status_code=409,
                    )
                invocation = legacy_node_adapter.compile(node)
                builtin_capability_registry.require(
                    invocation.capability_id,
                    invocation.capability_version,
                )
                if node.capability_id in {"graphql.request", "grpc.call"}:
                    if not settings.feature_multi_protocol_enabled:
                        raise AppError(
                            code="MULTI_PROTOCOL_DISABLED",
                            message="多协议执行能力尚未启用",
                            status_code=409,
                        )
                    protocol_config = parse_protocol_config(node)
                    await self._validate_protocol_node(project_id, node, protocol_config)
                    return
                if node.capability_id and node.capability_id.startswith(("kafka.", "websocket.")):
                    if not settings.feature_event_protocols_enabled:
                        raise AppError(
                            code="EVENT_PROTOCOLS_DISABLED",
                            message="Kafka 与 WebSocket 执行能力尚未启用",
                            status_code=409,
                        )
                    event_config = parse_event_config(node)
                    await self._validate_event_node(project_id, node, event_config)
                    return
            config = parse_node_config(legacy_node_adapter.as_legacy_node(node))
        except AppError:
            raise
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

    async def _validate_protocol_node(
        self,
        project_id: UUID,
        node: WorkflowNode,
        config: GraphQLCapabilityConfig | GrpcCapabilityConfig,
    ) -> None:
        if isinstance(config, GraphQLCapabilityConfig):
            artifact = await self._protocol_assets.load(
                project_id=project_id,
                artifact_id=config.schema_id,
                protocol=ProtocolKind.GRAPHQL,
            )
            try:
                validate_graphql_operation(artifact.canonical_content, config.operation)
            except ProtocolSchemaError as error:
                raise AppError(
                    code="INVALID_GRAPHQL_OPERATION",
                    message=str(error),
                    status_code=422,
                    details={"node_id": node.id},
                ) from error
            return
        artifact = await self._protocol_assets.load(
            project_id=project_id,
            artifact_id=config.descriptor_id,
            protocol=ProtocolKind.GRPC,
        )
        if not _grpc_method_matches(artifact.summary, config):
            raise AppError(
                code="GRPC_METHOD_NOT_FOUND",
                message="gRPC 方法不存在或调用类型与 Descriptor 不一致",
                status_code=422,
                details={"node_id": node.id},
            )

    async def _validate_event_node(
        self,
        project_id: UUID,
        node: WorkflowNode,
        config: object,
    ) -> None:
        if isinstance(config, (KafkaProduceCapabilityConfig, KafkaConsumeCapabilityConfig)):
            await self._event_sources.load(
                project_id=project_id,
                source_id=config.source_id,
                kind=EventSourceKind.KAFKA,
            )
            if config.schema_id is not None:
                artifact = await self._protocol_assets.load(
                    project_id=project_id,
                    artifact_id=config.schema_id,
                    protocol=ProtocolKind.KAFKA,
                )
                if (
                    artifact.summary.get("event_schema_format") == "protobuf"
                    and not config.message_type
                ):
                    raise AppError(
                        code="PROTOBUF_MESSAGE_TYPE_REQUIRED",
                        message="Protobuf Kafka 节点必须指定 Message Type",
                        status_code=422,
                        details={"node_id": node.id},
                    )
            return
        if isinstance(
            config, (WebSocketConnectCapabilityConfig, WebSocketExchangeCapabilityConfig)
        ):
            await self._event_sources.load(
                project_id=project_id,
                source_id=config.source_id,
                kind=EventSourceKind.WEBSOCKET,
            )
        if (
            isinstance(
                config,
                (WebSocketAwaitCapabilityConfig, WebSocketExchangeCapabilityConfig),
            )
            and config.correlation_expression is not None
        ):
            try:
                validate_safe_expression(config.correlation_expression)
            except SafeExpressionError as error:
                raise AppError(
                    code=error.code,
                    message=error.message,
                    status_code=422,
                    details={"node_id": node.id},
                ) from error

    @staticmethod
    def _validate_websocket_session_graph(definition: WorkflowDefinition) -> None:
        session_nodes: dict[str, list[tuple[WorkflowNode, object]]] = {}
        for node in definition.nodes:
            if node.type is not NodeType.CAPABILITY or node.capability_id not in {
                "websocket.connect",
                "websocket.send",
                "websocket.await",
                "websocket.close",
            }:
                continue
            config = parse_event_config(node)
            if not isinstance(
                config,
                (
                    WebSocketConnectCapabilityConfig,
                    WebSocketSendCapabilityConfig,
                    WebSocketAwaitCapabilityConfig,
                    WebSocketCloseCapabilityConfig,
                ),
            ):
                continue
            session_key = config.session_key
            session_nodes.setdefault(session_key, []).append((node, config))
        for session_key, entries in session_nodes.items():
            connects = [
                item for item in entries if isinstance(item[1], WebSocketConnectCapabilityConfig)
            ]
            closes = [
                item for item in entries if isinstance(item[1], WebSocketCloseCapabilityConfig)
            ]
            if len(connects) != 1 or len(closes) != 1:
                raise AppError(
                    code="INVALID_WEBSOCKET_SESSION_GRAPH",
                    message="每个 WebSocket Session 必须包含一个 Connect 和一个 Close",
                    status_code=422,
                    details={"session_key": session_key},
                )
            connect_node = connects[0][0]
            close_node = closes[0][0]
            close_scope = _upstream_node_ids(definition, close_node.id, include_target=True)
            if connect_node.id not in close_scope or any(
                node.id not in close_scope for node, _config in entries
            ):
                raise AppError(
                    code="INVALID_WEBSOCKET_SESSION_GRAPH",
                    message="WebSocket Session 节点必须位于 Connect 到 Close 的同一依赖链",
                    status_code=422,
                    details={"session_key": session_key},
                )
            for node, session_config in entries:
                if isinstance(session_config, WebSocketConnectCapabilityConfig):
                    continue
                upstream = _upstream_node_ids(definition, node.id, include_target=False)
                if connect_node.id not in upstream:
                    raise AppError(
                        code="INVALID_WEBSOCKET_SESSION_GRAPH",
                        message="WebSocket 操作必须依赖对应的 Connect 节点",
                        status_code=422,
                        details={"session_key": session_key, "node_id": node.id},
                    )

    async def _validate_resource_node(
        self,
        project_id: UUID,
        node: WorkflowNode,
        config: object,
    ) -> None:
        if isinstance(config, ApiNodeConfig):
            await self._validate_api_node_resource(project_id, node, config)
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

    async def _validate_api_node_resource(
        self,
        project_id: UUID,
        node: WorkflowNode,
        config: ApiNodeConfig,
    ) -> None:
        definition = await self._api_repository.get_definition(config.api_definition_id)
        if definition is None or definition.project_id != project_id:
            raise AppError(
                code="WORKFLOW_API_NOT_FOUND",
                message=f"API 节点 {node.name} 引用的接口不存在",
                status_code=422,
                details={"node_id": node.id},
            )
        if config.api_version is not None:
            version = await self._api_repository.get_version(
                definition_id=config.api_definition_id,
                version=config.api_version,
            )
            if version is None:
                raise AppError(
                    code="WORKFLOW_API_VERSION_NOT_FOUND",
                    message=f"API 节点 {node.name} 引用的接口版本不存在",
                    status_code=422,
                    details={"node_id": node.id, "api_version": config.api_version},
                )
        body_override = config.request_overrides.body
        if body_override is None or body_override.kind is not BodyKind.MULTIPART:
            return
        multipart = ApiNodeMultipartBody.model_validate(body_override.value)
        for file in multipart.files:
            artifact = await self._session.get(Artifact, file.artifact_id)
            if artifact is None or artifact.project_id != project_id:
                raise AppError(
                    code="ARTIFACT_NOT_FOUND",
                    message=f"API 节点 {node.name} 引用的文件不存在",
                    status_code=422,
                    details={"node_id": node.id, "artifact_id": str(file.artifact_id)},
                )

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
            if isinstance(config, AssertNodeConfig) and config.expected_source_node_id is not None:
                self._validate_control_source(
                    definition,
                    {item.id for item in definition.nodes},
                    node.id,
                    config.expected_source_node_id,
                )
                self._validate_jmespath(cast(str, config.expected_expression), node.id)
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
                if kind not in {CredentialKind.POSTGRESQL, CredentialKind.MYSQL}:
                    raise DataNodeValidationError("SQL 节点必须使用 PostgreSQL/MySQL Credential")
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
            if node.effective_type not in {NodeType.SUBFLOW, NodeType.FOR_EACH}:
                continue
            config = parse_node_config(legacy_node_adapter.as_legacy_node(node))
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
            if any(item.effective_type is NodeType.DATASET for item in nested.nodes):
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

    def _preview_execution_plan(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID | None,
        change_set_id: UUID,
        approval_id: UUID,
        proposal_fingerprint: str,
        context_fingerprint: str,
        definition: WorkflowDefinition,
        environment_id: UUID,
        prepared: PreparedWorkflow,
        runtime_variables: dict[str, str],
        budget: PreviewBudget,
        request_limits: tuple[int, ...],
    ) -> tuple[WorkflowExecution, WorkflowExecutionPlan]:
        def new_execution(
            snapshot: dict[str, JsonValue],
            execution_budget: PreviewBudget,
            *,
            parent_execution_id: UUID | None = None,
            dataset_row_index: int | None = None,
        ) -> WorkflowExecution:
            return self._preview_execution_model(
                actor=actor,
                project_id=project_id,
                workflow_id=workflow_id,
                change_set_id=change_set_id,
                approval_id=approval_id,
                proposal_fingerprint=proposal_fingerprint,
                context_fingerprint=context_fingerprint,
                environment_id=environment_id,
                snapshot=snapshot,
                budget=execution_budget,
                parent_execution_id=parent_execution_id,
                dataset_row_index=dataset_row_index,
            )

        if len(prepared.runs) == 1:
            execution = new_execution(prepared.runs[0].snapshot, budget)
            self._workflows.add(execution)
            return execution, self._run_plan(
                execution=execution,
                actor=actor,
                project_id=project_id,
                workflow_version=0,
                definition=definition,
                prepared=prepared.runs[0],
                runtime_variables=runtime_variables,
                request_budget=request_limits[0],
            )
        parent = new_execution(prepared.snapshot, budget)
        children = [
            new_execution(
                run.snapshot,
                budget.model_copy(update={"max_requests": request_limit}),
                parent_execution_id=parent.id,
                dataset_row_index=index,
            )
            for index, (run, request_limit) in enumerate(
                zip(prepared.runs, request_limits, strict=True)
            )
        ]
        self._workflows.add(parent)
        self._workflows.add_all(children)
        plans = tuple(
            self._run_plan(
                execution=child,
                actor=actor,
                project_id=project_id,
                workflow_version=0,
                definition=definition,
                prepared=run,
                runtime_variables=runtime_variables,
                request_budget=request_limit,
            )
            for child, run, request_limit in zip(
                children, prepared.runs, request_limits, strict=True
            )
        )
        return parent, WorkflowBatchPlan(
            execution_id=parent.id,
            actor_id=actor.id,
            project_id=project_id,
            workflow_version=0,
            children=plans,
            concurrency=budget.max_parallelism,
            max_runtime_seconds=budget.max_runtime_seconds,
            cleanup_timeout_seconds=budget.max_runtime_seconds,
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
    def _preview_execution_model(
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID | None,
        change_set_id: UUID,
        approval_id: UUID,
        proposal_fingerprint: str,
        context_fingerprint: str,
        environment_id: UUID,
        snapshot: dict[str, JsonValue],
        budget: PreviewBudget,
        parent_execution_id: UUID | None = None,
        dataset_row_index: int | None = None,
    ) -> WorkflowExecution:
        return WorkflowExecution(
            id=uuid4(),
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_version_id=None,
            environment_id=environment_id,
            triggered_by_id=actor.id,
            parent_execution_id=parent_execution_id,
            dataset_row_index=dataset_row_index,
            run_purpose=WorkflowRunPurpose.PREVIEW.value,
            source_change_set_id=change_set_id,
            preview_approval_id=approval_id,
            preview_budget=budget.model_dump(mode="json"),
            preview_evidence={
                "proposal_fingerprint": proposal_fingerprint,
                "context_fingerprint": context_fingerprint,
                "approval_id": str(approval_id),
                "trace_id": get_trace_id(),
                "redactions": [],
            },
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
        request_budget: int | None = None,
    ) -> WorkflowRunPlan:
        return WorkflowRunPlan(
            execution_id=execution.id,
            actor_id=actor.id,
            project_id=project_id,
            workflow_version=workflow_version,
            definition=definition,
            prepared=prepared,
            runtime_variables=dict(runtime_variables),
            request_budget=request_budget,
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
        context: ExecutionContext | None = None,
        resume_records: tuple[NodeRunRecord, ...] = (),
        resume_attempts: dict[str, int] | None = None,
        reset_retry_budget: bool = False,
        shared_request_budget: RequestBudget | None = None,
    ) -> WorkflowRunResult:
        task = asyncio.create_task(
            scheduler.run(
                definition,
                context=context
                or ExecutionContext(
                    workflow_variables=cast(dict[str, JsonValue], workflow_variables),
                    dataset_variables=dataset_variables,
                    runtime_variables=cast(dict[str, JsonValue], runtime_variables),
                ),
                cancellation=token,
                on_node_status=on_node_status,
                resume_records=resume_records,
                resume_attempts=resume_attempts,
                reset_retry_budget=reset_retry_budget,
                shared_request_budget=shared_request_budget,
            )
        )
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=CANCELLATION_POLL_SECONDS)
                await self._session.refresh(
                    execution,
                    attribute_names=[
                        "cancel_requested_at",
                        "force_cancel_requested_at",
                    ],
                )
                if execution.cancel_requested_at is not None:
                    token.cancel(force=execution.force_cancel_requested_at is not None)
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
                phase=record.phase.value,
                best_effort=record.best_effort,
                status=record.status.value,
                attempts=record.attempts,
                output=cast(JsonValue, redact(record.output)),
                result=cast(
                    dict[str, JsonValue],
                    redact(record.result.model_dump(mode="json")),
                ),
                error_code=record.error_code,
                error_message=record.error_message,
                started_at=record.started_at,
                completed_at=record.completed_at,
            )
            for record in result.records
        ]


def _with_api_version(node: WorkflowNode, version: int) -> WorkflowNode:
    if node.type is NodeType.CAPABILITY:
        return node.model_copy(
            update={"configuration": {**(node.configuration or {}), "api_version": version}}
        )
    return node.model_copy(update={"config": {**node.config, "api_version": version}})


def _fingerprint(definition: dict[str, object]) -> str:
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _bounded_preview_definition(
    definition: WorkflowDefinition,
    budget: PreviewBudget,
) -> WorkflowDefinition:
    cleanup_nodes = [node for node in definition.nodes if node.phase is WorkflowPhase.CLEANUP]
    if (
        not _preview_cleanup_covers_all_outcomes(cleanup_nodes)
        or definition.run_policy.force_cancel_skips_cleanup
    ):
        raise AppError(
            code="PREVIEW_CLEANUP_REQUIRED",
            message="Sandbox Preview 必须提供覆盖成功、失败和取消的 Cleanup",
            status_code=409,
        )
    settings = definition.settings.model_copy(
        update={"concurrency": min(definition.settings.concurrency, budget.max_parallelism)}
    )
    policy = definition.run_policy
    run_policy = policy.model_copy(
        update={
            "request_budget": min(
                policy.request_budget or budget.max_requests, budget.max_requests
            ),
            "cleanup_request_budget": min(
                policy.cleanup_request_budget or budget.max_requests,
                budget.max_requests,
            ),
            "max_runtime_seconds": min(
                policy.max_runtime_seconds or budget.max_runtime_seconds,
                budget.max_runtime_seconds,
            ),
            "force_cancel_skips_cleanup": False,
        }
    )
    return definition.model_copy(update={"settings": settings, "run_policy": run_policy})


def _preview_cleanup_covers_all_outcomes(cleanup_nodes: list[WorkflowNode]) -> bool:
    required = {
        CleanupRunWhen.SUCCESS,
        CleanupRunWhen.FAILURE,
        CleanupRunWhen.CANCEL,
    }
    coverage: dict[tuple[str, ...], set[CleanupRunWhen]] = {}
    for node in cleanup_nodes:
        outcomes = coverage.setdefault(tuple(sorted(node.cleanup_for)), set())
        if node.run_when is CleanupRunWhen.ALWAYS:
            outcomes.update(required)
        else:
            outcomes.add(node.run_when)
    return bool(coverage) and all(required <= outcomes for outcomes in coverage.values())


def _prepared_preview_target_fingerprint(prepared: PreparedWorkflow) -> str:
    return _preview_target_fingerprint_for_runs(prepared.runs)


def _preview_plan_target_fingerprint(plan: WorkflowExecutionPlan) -> str:
    runs = (
        tuple(child.prepared for child in plan.children)
        if isinstance(plan, WorkflowBatchPlan)
        else (plan.prepared,)
    )
    return _preview_target_fingerprint_for_runs(runs)


def _preview_target_fingerprint_for_runs(
    runs: tuple[PreparedExecution, ...],
) -> str:
    payload = [_prepared_execution_target_payload(run) for run in runs]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        settings.secret_key.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def _prepared_execution_target_payload(prepared: PreparedExecution) -> dict[str, JsonValue]:
    return {
        "requests": {
            node_id: {
                "method": request.request.method.value,
                "url": request.request.url,
                "target_snapshot": request.request.target_snapshot,
            }
            for node_id, request in sorted(prepared.requests.items())
        },
        "subflows": {
            node_id: _prepared_subflow_target_payload(subflow)
            for node_id, subflow in sorted(prepared.subflows.items())
        },
    }


def _prepared_subflow_target_payload(subflow: PreparedSubflow) -> dict[str, JsonValue]:
    return {
        "requests": {
            node_id: {
                "method": request.request.method.value,
                "url": request.request.url,
                "target_snapshot": request.request.target_snapshot,
            }
            for node_id, request in sorted(subflow.requests.items())
        },
        "subflows": {
            node_id: _prepared_subflow_target_payload(child)
            for node_id, child in sorted(subflow.subflows.items())
        },
    }


def _validate_preview_target_classification(
    definition: WorkflowDefinition,
    subflows: dict[str, PreparedSubflow],
) -> None:
    unclassified = [
        node.id
        for node in definition.nodes
        if node.effective_type in {NodeType.SQL, NodeType.REDIS}
        or node.capability_id in _PREVIEW_UNCLASSIFIED_CAPABILITIES
    ]
    if unclassified:
        raise AppError(
            code="PREVIEW_TARGET_CLASSIFICATION_REQUIRED",
            message="Sandbox Preview Beta 仅允许绑定所选 Test/Sandbox Environment 的 API Target",
            status_code=409,
            details={"unclassified_target_node_ids": sorted(unclassified)},
        )
    for prepared in subflows.values():
        _validate_preview_target_classification(prepared.definition, prepared.subflows)


def _bounded_preview_prepared_workflow(
    prepared: PreparedWorkflow,
    budget: PreviewBudget,
) -> PreparedWorkflow:
    runs = tuple(_bounded_preview_prepared_execution(run, budget) for run in prepared.runs)
    return replace(
        prepared,
        snapshot=_preview_snapshot_with_subflows(prepared.snapshot, runs[0].subflows),
        runs=runs,
    )


def _bounded_preview_prepared_execution(
    prepared: PreparedExecution,
    budget: PreviewBudget,
) -> PreparedExecution:
    subflows = {
        node_id: _bounded_preview_subflow(subflow, budget)
        for node_id, subflow in prepared.subflows.items()
    }
    return replace(
        prepared,
        snapshot=_preview_snapshot_with_subflows(prepared.snapshot, subflows),
        subflows=subflows,
    )


def _bounded_preview_subflow(
    prepared: PreparedSubflow,
    budget: PreviewBudget,
) -> PreparedSubflow:
    definition = _bounded_preview_definition(prepared.definition, budget)
    subflows = {
        node_id: _bounded_preview_subflow(subflow, budget)
        for node_id, subflow in prepared.subflows.items()
    }
    return replace(
        prepared,
        definition=definition,
        subflows=subflows,
        snapshot=_preview_subflow_snapshot(prepared.snapshot, definition, subflows),
    )


def _preview_subflow_snapshot(
    snapshot: dict[str, JsonValue],
    definition: WorkflowDefinition,
    subflows: dict[str, PreparedSubflow],
) -> dict[str, JsonValue]:
    bounded = _preview_snapshot_with_subflows(snapshot, subflows)
    workflow = bounded.get("workflow")
    if not isinstance(workflow, dict):
        return bounded
    serialized_definition = workflow.get("definition")
    if not isinstance(serialized_definition, dict):
        return bounded
    bounded_definition = {
        **serialized_definition,
        "settings": definition.settings.model_dump(mode="json"),
        "run_policy": definition.run_policy.model_dump(mode="json"),
    }
    return {
        **bounded,
        "workflow": {**workflow, "definition": bounded_definition},
    }


def _preview_snapshot_with_subflows(
    snapshot: dict[str, JsonValue],
    subflows: dict[str, PreparedSubflow],
) -> dict[str, JsonValue]:
    return {
        **snapshot,
        "subflows": {node_id: subflow.snapshot for node_id, subflow in subflows.items()},
    }


def _preview_request_limits(
    definition: WorkflowDefinition,
    prepared: PreparedWorkflow,
    budget: PreviewBudget,
) -> tuple[int, ...]:
    node_count = len(definition.nodes)
    row_count = len(prepared.runs)
    if node_count > budget.max_nodes or row_count > budget.max_dataset_rows:
        raise AppError(
            code="PREVIEW_BUDGET_EXCEEDED",
            message="Sandbox Preview 结构超过审批预算",
            status_code=422,
            details={"nodes": node_count, "dataset_rows": row_count},
        )
    per_row_minimum = max(
        1,
        sum(node_type_consumes_request(node.effective_type) for node in definition.nodes),
    )
    minimum = per_row_minimum * row_count
    if minimum > budget.max_requests:
        raise AppError(
            code="PREVIEW_BUDGET_EXCEEDED",
            message="Sandbox Preview 最小请求次数超过审批预算",
            status_code=422,
            details={"minimum_requests": minimum, "max_requests": budget.max_requests},
        )
    remainder = budget.max_requests - minimum
    quotient, extra = divmod(remainder, row_count)
    return tuple(
        per_row_minimum + quotient + (1 if index < extra else 0) for index in range(row_count)
    )


def _preview_run_evidence(
    execution: WorkflowExecution,
    plan: WorkflowRunPlan,
    result: WorkflowRunResult,
) -> dict[str, JsonValue]:
    bindings = [
        {
            "node_id": record.node_id,
            "attempt": observation.attempt,
            "mappings": [item.model_dump(mode="json") for item in observation.mappings],
        }
        for record in result.records
        for observation in record.result.observations
        if observation.mappings
    ]
    assertions = [
        {
            "node_id": record.node_id,
            "assertions": [item.model_dump(mode="json") for item in record.result.assertions],
        }
        for record in result.records
        if record.result.assertions
    ]
    redactions = sorted(
        {path for record in result.records for path in record.result.redacted_paths}
    )
    request_usage = result.context.get("preview_request_budget", {})
    completed_at = execution.completed_at or datetime.now(UTC)
    return cast(
        dict[str, JsonValue],
        redact(
            {
                **execution.preview_evidence,
                "execution_snapshot": execution.snapshot,
                "binding_trace": bindings,
                "assert_result": assertions,
                "cleanup_result": execution.cleanup_report,
                "budget_usage": {
                    "nodes": len(plan.definition.nodes),
                    "requests": request_usage,
                    "dataset_rows": 1,
                    "parallelism_limit": plan.definition.settings.concurrency,
                    "runtime_seconds": _elapsed_seconds(execution.started_at, completed_at),
                },
                "redactions": redactions,
            }
        ),
    )


def _preview_batch_evidence(
    execution: WorkflowExecution,
    children: list[WorkflowExecution],
) -> dict[str, JsonValue]:
    completed_at = execution.completed_at or datetime.now(UTC)
    request_used = sum(
        int(child.preview_evidence.get("budget_usage", {}).get("requests", {}).get("used", 0))
        for child in children
    )
    return cast(
        dict[str, JsonValue],
        redact(
            {
                **execution.preview_evidence,
                "execution_snapshot": execution.snapshot,
                "binding_trace": [
                    {
                        "dataset_row_index": child.dataset_row_index,
                        "items": child.preview_evidence.get("binding_trace", []),
                    }
                    for child in children
                ],
                "assert_result": [
                    {
                        "dataset_row_index": child.dataset_row_index,
                        "items": child.preview_evidence.get("assert_result", []),
                    }
                    for child in children
                ],
                "cleanup_result": [
                    {
                        "dataset_row_index": child.dataset_row_index,
                        "result": child.preview_evidence.get("cleanup_result", {}),
                    }
                    for child in children
                ],
                "budget_usage": {
                    "nodes": execution.preview_budget.get("max_nodes"),
                    "requests": {
                        "limit": execution.preview_budget.get("max_requests"),
                        "used": request_used,
                        "remaining": max(
                            0,
                            int(execution.preview_budget.get("max_requests", 0)) - request_used,
                        ),
                    },
                    "dataset_rows": len(children),
                    "parallelism_limit": execution.preview_budget.get("max_parallelism"),
                    "runtime_seconds": _elapsed_seconds(execution.started_at, completed_at),
                },
                "redactions": sorted(
                    {
                        str(path)
                        for child in children
                        for path in child.preview_evidence.get("redactions", [])
                    }
                ),
            }
        ),
    )


def _remaining_preview_request_budget(
    limit: int | None,
    records: tuple[NodeRunRecord, ...],
) -> RequestBudget | None:
    if limit is None:
        return None
    attempts: dict[str, int] = {}
    for record in records:
        if node_type_consumes_request(record.node_type):
            attempts[record.node_id] = max(attempts.get(record.node_id, 0), record.attempts)
    return RequestBudget(max(limit - sum(attempts.values()), 0))


def _elapsed_seconds(started_at: datetime, completed_at: datetime) -> float:
    start = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
    end = completed_at.replace(tzinfo=UTC) if completed_at.tzinfo is None else completed_at
    return max(0.0, (end - start).total_seconds())


def _with_preview_budget_usage(
    result: WorkflowRunResult,
    *,
    limit: int | None,
    budget: RequestBudget | None,
) -> WorkflowRunResult:
    if limit is None or budget is None:
        return result
    context = {
        **result.context,
        "preview_request_budget": {
            "limit": limit,
            "used": limit - budget.remaining,
            "remaining": budget.remaining,
        },
    }
    return replace(result, context=cast(dict[str, JsonValue], context))


def _grpc_method_matches(
    summary: dict[str, object],
    config: GrpcCapabilityConfig,
) -> bool:
    services = summary.get("services")
    if not isinstance(services, list):
        return False
    expected = (
        GrpcCallType.SERVER_STREAMING.value
        if config.call_type is GrpcCallType.SERVER_STREAMING
        else GrpcCallType.UNARY.value
    )
    for service in services:
        if not isinstance(service, dict) or service.get("name") != config.service:
            continue
        methods = service.get("methods")
        if not isinstance(methods, list):
            return False
        return any(
            isinstance(method, dict)
            and method.get("name") == config.method
            and method.get("call_type") == expected
            for method in methods
        )
    return False


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
