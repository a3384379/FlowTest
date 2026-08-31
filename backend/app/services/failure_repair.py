from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.canonical_contracts import contains_sensitive_contract_value
from app.domain.failure_repair import (
    FailureDiagnosis,
    RepairScopeError,
    diagnose_failure,
    validate_repair_scope,
)
from app.domain.failure_triage import FailureSignal
from app.engine.results import NodeResult
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.test_contexts import TestContextRevision
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution
from app.repositories.workflows import WorkflowRepository
from app.schemas.failure_repair import RepairProposalCreate
from app.schemas.flow_spec import FlowSpecImportRequest
from app.services.flow_spec import (
    FlowSpecChangeSetView,
    FlowSpecRepairProvenance,
    FlowSpecService,
)
from app.services.projects import ProjectService
from app.services.test_contexts import ProposableContext, TestContextService


@dataclass(frozen=True, slots=True)
class FailureDiagnosisView:
    execution: WorkflowExecution
    workflow_id: UUID | None
    diagnosis: FailureDiagnosis


@dataclass(frozen=True, slots=True)
class PreparedRepairProposal:
    actor: User
    project_id: UUID
    execution_id: UUID
    diagnosis: FailureDiagnosis
    import_request: FlowSpecImportRequest
    provenance: FlowSpecRepairProvenance


class FailureRepairService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._workflows = WorkflowRepository(session)
        self._contexts = TestContextService(session)
        self._flow_specs = FlowSpecService(session)

    async def diagnose(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> FailureDiagnosisView:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._diagnosis_view(project_id, execution_id)

    async def _diagnosis_view(self, project_id: UUID, execution_id: UUID) -> FailureDiagnosisView:
        execution = await self._execution(project_id, execution_id)
        _require_terminal_failure(execution)
        nodes = await self._execution_nodes(execution)
        diagnosis = diagnose_failure(_failure_signals(execution, nodes))
        return FailureDiagnosisView(
            execution=execution,
            workflow_id=await self._target_workflow_id(execution),
            diagnosis=diagnosis,
        )

    async def prepare_repair_proposal(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution_id: UUID,
        payload: RepairProposalCreate,
    ) -> PreparedRepairProposal:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        if contains_sensitive_contract_value(payload.rationale):
            raise AppError(
                code="REPAIR_SENSITIVE_INPUT_FORBIDDEN",
                message="修复理由不能包含凭据、个人标识或其他敏感值",
                status_code=422,
            )
        view = await self._diagnosis_view(project_id, execution_id)
        workflow = await self._target_workflow(project_id, view.workflow_id)
        if workflow.draft_revision != payload.expected_target_revision:
            raise AppError(
                code="REPAIR_TARGET_STALE",
                message="目标工作流草稿版本已变化, 请重新生成修复 Proposal",
                status_code=409,
                details={"current_revision": workflow.draft_revision},
            )
        context = await self._repair_context(
            actor=actor,
            project_id=project_id,
            execution=view.execution,
            requested_revision_id=payload.context_revision_id,
        )
        exported = await self._flow_specs.export(
            actor=actor,
            project_id=project_id,
            workflow_id=workflow.id,
            version=None,
        )
        proposed = await self._flow_specs.validate(
            actor=actor,
            project_id=project_id,
            spec=payload.proposed_spec,
        )
        if proposed.spec.project_id not in {None, project_id}:
            raise AppError(
                code="REPAIR_PROJECT_MISMATCH",
                message="修复 FlowSpec 不属于当前项目",
                status_code=422,
            )
        try:
            scope = validate_repair_scope(
                before=exported.pipeline.spec,
                after=proposed.spec,
                diagnosis=view.diagnosis,
                kind=payload.kind,
                acknowledge_oracle_weakening=payload.acknowledge_oracle_weakening,
            )
        except RepairScopeError as error:
            raise AppError(
                code="REPAIR_PROPOSAL_FORBIDDEN",
                message=str(error),
                status_code=422,
            ) from error
        provenance = FlowSpecRepairProvenance(
            execution_id=execution_id,
            context_revision_id=context.revision.id,
            context_fingerprint=context.revision.fingerprint,
            expected_target_revision=payload.expected_target_revision,
            patch_kind=payload.kind,
            rationale=payload.rationale,
            diagnosis=view.diagnosis.model_dump(mode="json"),
            oracle_weakening=scope.oracle_weakening,
        )
        return PreparedRepairProposal(
            actor=actor,
            project_id=project_id,
            execution_id=execution_id,
            diagnosis=view.diagnosis,
            import_request=FlowSpecImportRequest(
                spec=proposed.spec,
                workflow_id=workflow.id,
                source_ref=f"repair://workflow-executions/{execution_id}",
            ),
            provenance=provenance,
        )

    async def persist_repair_proposal(
        self, prepared: PreparedRepairProposal
    ) -> FlowSpecChangeSetView:
        return await self._flow_specs.create_import(
            actor=prepared.actor,
            project_id=prepared.project_id,
            payload=prepared.import_request,
            repair_provenance=prepared.provenance,
        )

    async def _execution(self, project_id: UUID, execution_id: UUID) -> WorkflowExecution:
        execution = await self._workflows.get_execution(execution_id)
        if execution is None or execution.project_id != project_id:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND",
                message="工作流执行记录不存在",
                status_code=404,
            )
        return execution

    async def _execution_nodes(self, execution: WorkflowExecution) -> list[WorkflowNodeExecution]:
        nodes = await self._workflows.list_node_executions(execution.id)
        children = await self._workflows.list_child_executions(execution.id)
        for child in children:
            nodes.extend(await self._workflows.list_node_executions(child.id))
        return nodes

    async def _target_workflow_id(self, execution: WorkflowExecution) -> UUID | None:
        if execution.workflow_id is not None:
            return execution.workflow_id
        if execution.source_change_set_id is None:
            return None
        return await self._session.scalar(
            select(AIChangeItem.target_resource_id).where(
                AIChangeItem.change_set_id == execution.source_change_set_id,
                AIChangeItem.item_type == "workflow",
            )
        )

    async def _target_workflow(self, project_id: UUID, workflow_id: UUID | None) -> Workflow:
        workflow = await self._workflows.get(workflow_id) if workflow_id is not None else None
        if workflow is None or workflow.project_id != project_id:
            raise AppError(
                code="REPAIR_TARGET_REQUIRED",
                message="修复 Proposal 只能更新当前项目中的既有工作流",
                status_code=409,
            )
        return workflow

    async def _repair_context(
        self,
        *,
        actor: User,
        project_id: UUID,
        execution: WorkflowExecution,
        requested_revision_id: UUID | None,
    ) -> ProposableContext:
        revision_id = requested_revision_id or await self._source_context_revision(execution)
        if revision_id is None:
            raise AppError(
                code="REPAIR_CONTEXT_REQUIRED",
                message="修复 Proposal 必须绑定可提案的 Context Revision",
                status_code=409,
            )
        revision = await self._session.get(TestContextRevision, revision_id)
        if revision is None:
            raise AppError(
                code="REPAIR_CONTEXT_REQUIRED",
                message="修复 Proposal 的 Context Revision 不存在",
                status_code=404,
            )
        return await self._contexts.require_proposable(
            actor=actor,
            project_id=project_id,
            context_id=revision.context_id,
            revision_id=revision.id,
        )

    async def _source_context_revision(self, execution: WorkflowExecution) -> UUID | None:
        if execution.source_change_set_id is None:
            return None
        change_set = await self._session.get(AIChangeSet, execution.source_change_set_id)
        value = change_set.source_snapshot.get("context_revision_id") if change_set else None
        try:
            return UUID(value) if isinstance(value, str) else None
        except ValueError:
            return None


def _require_terminal_failure(execution: WorkflowExecution) -> None:
    if execution.status in {"queued", "running"}:
        raise AppError(
            code="FAILURE_DIAGNOSIS_PENDING",
            message="工作流执行完成后才能进行失败诊断",
            status_code=409,
        )
    if execution.status == "passed":
        raise AppError(
            code="FAILURE_DIAGNOSIS_NOT_REQUIRED",
            message="通过的工作流执行不需要失败诊断",
            status_code=409,
        )


def _failure_signals(
    execution: WorkflowExecution,
    nodes: list[WorkflowNodeExecution],
) -> list[FailureSignal]:
    failed = [node for node in nodes if node.status == "failed"]
    terminal = failed or [node for node in nodes if node.status == "cancelled"]
    if not terminal:
        return [
            FailureSignal(
                evidence_ref=f"flowtest://workflow-executions/{execution.id}",
                item_status=execution.status,
                attempts=1,
                error_code=execution.error_code,
            )
        ]
    return [_node_signal(node) for node in terminal]


def _node_signal(node: WorkflowNodeExecution) -> FailureSignal:
    result = _node_result(node.result)
    observation = result.observations[-1] if result and result.observations else None
    request_url = urlsplit(observation.request.url) if observation is not None else None
    assertions = list(result.assertions) if result is not None else []
    error = result.error if result is not None else None
    assertion_failed = node.node_type == "assert" or any(not item.passed for item in assertions)
    return FailureSignal(
        evidence_ref=f"flowtest://runs/{node.workflow_execution_id}/nodes/{node.node_id}",
        item_status=node.status,
        attempts=node.attempts,
        error_code=node.error_code or (error.code if error is not None else None),
        retryable=error.retryable if error is not None else False,
        http_status=(
            observation.response.status_code if observation and observation.response else None
        ),
        affected_service=observation.request.service_key if observation is not None else None,
        endpoint_variant=observation.request.endpoint_variant if observation is not None else None,
        affected_operation=(
            f"{observation.request.method} {request_url.path}"
            if observation is not None and request_url is not None
            else None
        ),
        response_received=bool(observation and observation.response),
        assertion_failed=assertion_failed,
        contract_assertion_failed=any(
            not item.passed and item.name.lower() in _CONTRACT_ASSERTION_NAMES
            for item in assertions
        ),
        phase=cast(Literal["main", "cleanup"], node.phase),
    )


def _node_result(value: dict[str, Any] | None) -> NodeResult | None:
    if value is None:
        return None
    try:
        return NodeResult.model_validate(value)
    except ValueError:
        return None


_CONTRACT_ASSERTION_NAMES = frozenset(
    {"response_schema", "schema", "contract", "json_schema", "openapi_schema"}
)
