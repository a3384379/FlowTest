"""Governed change maintenance on the existing FlowSpec proposal lifecycle."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.canonical_contracts import contains_sensitive_contract_value
from app.domain.failure_repair import RepairScopeError, validate_flow_patch_scope
from app.domain.flow_spec_security import contains_sensitive_flow_spec_value
from app.domain.maintenance_proposals import FlowSpecMaintenanceProvenance
from app.models.access import User
from app.models.workflows import Workflow
from app.schemas.affected_flows import AffectedFlowsResponse
from app.schemas.flow_spec import FlowSpecImportRequest
from app.schemas.maintenance_proposals import MaintenanceProposalCreate
from app.services.affected_flows import AffectedFlowService
from app.services.flow_spec import FlowSpecChangeSetView, FlowSpecService
from app.services.projects import ProjectService
from app.services.test_contexts import TestContextService


@dataclass(frozen=True, slots=True)
class PreparedMaintenanceProposal:
    actor: User
    project_id: UUID
    workflow_id: UUID
    payload: MaintenanceProposalCreate
    import_request: FlowSpecImportRequest
    provenance: FlowSpecMaintenanceProvenance


class MaintenanceProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._contexts = TestContextService(session)
        self._flow_specs = FlowSpecService(session)

    async def prepare(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        payload: MaintenanceProposalCreate,
    ) -> PreparedMaintenanceProposal:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        _validate_input(payload, project_id)
        await self._target(project_id, workflow_id, payload.expected_target_revision)
        await self._require_context(actor, project_id, payload)
        analysis = await AffectedFlowService(self._session).analyze(
            actor=actor,
            project_id=project_id,
            context_id=payload.context_id,
            before_revision=payload.before_revision,
            after_revision=payload.after_revision,
            impact_run_id=payload.impact_run_id,
            page=1,
            page_size=1,
            workflow_id=workflow_id,
        )
        evidence_refs = _explicit_evidence(analysis, workflow_id)
        exported = await self._flow_specs.export(
            actor=actor, project_id=project_id, workflow_id=workflow_id, version=None
        )
        proposed = await self._flow_specs.validate(
            actor=actor, project_id=project_id, spec=payload.proposed_spec
        )
        try:
            scope = validate_flow_patch_scope(
                before=exported.pipeline.spec,
                after=proposed.spec,
                kind=payload.kind,
                acknowledge_oracle_weakening=payload.acknowledge_oracle_weakening,
            )
        except RepairScopeError as error:
            raise AppError(
                code="MAINTENANCE_PATCH_FORBIDDEN", message=str(error), status_code=422
            ) from error
        provenance = FlowSpecMaintenanceProvenance(
            context_id=payload.context_id,
            before_context_revision_id=analysis.before_revision_id,
            before_context_fingerprint=analysis.before_fingerprint,
            context_revision_id=analysis.after_revision_id,
            context_fingerprint=analysis.after_fingerprint,
            workflow_id=workflow_id,
            expected_target_revision=payload.expected_target_revision,
            impact_run_id=payload.impact_run_id,
            patch_kind=payload.kind,
            rationale=payload.rationale,
            evidence_refs=evidence_refs,
            analysis_complete=analysis.analysis_complete,
            diagnostic_codes=tuple(sorted({item.code for item in analysis.diagnostics})),
            oracle_weakening=scope.oracle_weakening,
        )
        return PreparedMaintenanceProposal(
            actor=actor,
            project_id=project_id,
            workflow_id=workflow_id,
            payload=payload.model_copy(deep=True),
            import_request=FlowSpecImportRequest(spec=proposed.spec, workflow_id=workflow_id),
            provenance=provenance,
        )

    async def persist(
        self, prepared: PreparedMaintenanceProposal
    ) -> tuple[FlowSpecChangeSetView, FlowSpecMaintenanceProvenance]:
        # Re-read authoritative state after the idempotency claim commits its transaction.
        refreshed = await self.prepare(
            actor=prepared.actor,
            project_id=prepared.project_id,
            workflow_id=prepared.workflow_id,
            payload=prepared.payload,
        )
        view = await self._flow_specs.create_import(
            actor=refreshed.actor,
            project_id=refreshed.project_id,
            payload=refreshed.import_request,
            maintenance_provenance=refreshed.provenance,
            commit=False,
        )
        return view, refreshed.provenance

    async def _target(self, project_id: UUID, workflow_id: UUID, revision: int) -> Workflow:
        workflow = await self._session.scalar(
            select(Workflow)
            .where(
                Workflow.id == workflow_id,
                Workflow.project_id == project_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if workflow is None:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="目标工作流不存在", status_code=404)
        if workflow.draft_revision != revision:
            raise AppError(
                code="MAINTENANCE_TARGET_STALE",
                message="目标草稿版本已变化, 请重新生成维护提案",
                status_code=409,
            )
        return workflow

    async def _require_context(
        self, actor: User, project_id: UUID, payload: MaintenanceProposalCreate
    ) -> None:
        await self._contexts.require_proposable(
            actor=actor,
            project_id=project_id,
            context_id=payload.context_id,
            revision_number=payload.after_revision,
        )


def _validate_input(payload: MaintenanceProposalCreate, project_id: UUID) -> None:
    if contains_sensitive_contract_value(payload.rationale) or contains_sensitive_flow_spec_value(
        payload.proposed_spec
    ):
        raise AppError(
            code="MAINTENANCE_SENSITIVE_INPUT_FORBIDDEN",
            message="维护提案不能包含敏感值, 请使用 secret:// 引用",
            status_code=422,
        )
    if payload.proposed_spec.project_id not in {None, project_id}:
        raise AppError(
            code="MAINTENANCE_PROJECT_MISMATCH",
            message="维护 FlowSpec 不属于当前项目",
            status_code=422,
        )
    if payload.before_revision >= payload.after_revision:
        raise AppError(
            code="MAINTENANCE_REVISION_ORDER_INVALID",
            message="维护提案必须比较向前推进的两个上下文版本",
            status_code=422,
        )


def _explicit_evidence(analysis: AffectedFlowsResponse, workflow_id: UUID) -> tuple[str, ...]:
    if any(
        item.code
        in {
            "ANALYSIS_BUDGET_EXCEEDED",
            "RESULT_TRUNCATED",
            "WORKFLOW_INVALID",
            "API_UNRESOLVED",
            "NODE_NOT_ANALYZED",
            "WORKFLOW_NODE_BUDGET_EXCEEDED",
        }
        for item in analysis.diagnostics
    ):
        raise AppError(
            code="MAINTENANCE_ANALYSIS_INCOMPLETE",
            message="目标分析存在未解析或截断结果, 不能创建维护提案",
            status_code=409,
        )
    refs = {
        reason.source_ref
        for workflow in analysis.affected_workflows
        if workflow.workflow_id == workflow_id
        for reason in workflow.reasons
        if reason.match_strength in {"instance", "portable"}
        and reason.knowledge_relation != "heuristic"
    }
    if not refs:
        raise AppError(
            code="MAINTENANCE_EXPLICIT_EVIDENCE_REQUIRED",
            message="维护提案需要精确 Operation 影响证据; 启发式或单独资产选择不能授权 Patch",
            status_code=409,
        )
    return tuple(sorted(refs))
