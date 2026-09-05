"""Bind V6 evidence to S45, without a second lifecycle or persistence aggregate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.canonical_contracts import contains_sensitive_contract_value
from app.domain.maintenance_proposals import FlowSpecMaintenanceProvenance
from app.domain.proposal_provenance import proposal_origin
from app.models.access import User
from app.models.ai import AIChangeSet
from app.models.change_regression import ChangeRegressionRun, ChangeRegressionStage
from app.repositories.change_regression import ChangeRegressionBundle, ChangeRegressionRepository
from app.schemas.maintenance_proposals import MaintenanceProposalCreate
from app.schemas.regression_maintenance import (
    RegressionContextBinding,
    RegressionMaintenanceReview,
    RegressionMaintenanceReviewEvidence,
    RegressionMaintenanceSnapshot,
    RegressionProposalEvidence,
    maintenance_snapshot,
)
from app.services.audit import AuditService
from app.services.context_inspector import ContextInspectorService
from app.services.projects import ProjectService
from app.services.regression_maintenance_coverage import RegressionMaintenanceCoverage
from app.services.test_contexts import TestContextService

if TYPE_CHECKING:
    from app.services.maintenance_proposals import PreparedMaintenanceProposal


class RegressionMaintenanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ChangeRegressionRepository(session)

    async def prepare_proposal(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        workflow_id: UUID,
        payload: MaintenanceProposalCreate,
    ) -> PreparedMaintenanceProposal:
        from app.services.maintenance_proposals import MaintenanceProposalService

        run = await self._editable(actor, project_id, run_id)
        snapshot = _required_snapshot(run)
        if len(snapshot.proposals) >= 100:
            raise _error("PROPOSAL_LIMIT", "维护提案关联已达上限")
        prepared = await MaintenanceProposalService(self._session).prepare(
            actor=actor, project_id=project_id, workflow_id=workflow_id, payload=payload
        )
        _validate_provenance(run, snapshot, prepared.provenance)
        return prepared

    async def persist_proposal(
        self, run_id: UUID, prepared: PreparedMaintenanceProposal
    ) -> ChangeRegressionBundle:
        # Claim commits release locks. Revalidate the aggregate before creating anything.
        from app.services.maintenance_proposals import MaintenanceProposalService

        refreshed = await self.prepare_proposal(
            actor=prepared.actor,
            project_id=prepared.project_id,
            run_id=run_id,
            workflow_id=prepared.workflow_id,
            payload=prepared.payload,
        )
        view, provenance = await MaintenanceProposalService(self._session).persist(refreshed)
        run = await self._editable(prepared.actor, prepared.project_id, run_id)
        snapshot = _required_snapshot(run)
        _validate_provenance(run, snapshot, provenance)
        snapshot.proposals.append(
            RegressionProposalEvidence(
                change_set_id=view.change_set.id,
                workflow_id=provenance.workflow_id,
                review_status="pending",
                applied=False,
            )
        )
        snapshot.review = None
        snapshot.required_workflows = []
        return await self._save(run, prepared.actor, snapshot, "proposal_created", commit=False)

    async def bind(
        self, *, actor: User, project_id: UUID, run_id: UUID, payload: RegressionContextBinding
    ) -> ChangeRegressionBundle:
        # AffectedFlowService uses S45 operation resolution; keep the dependency local.
        from app.services.affected_flows import AffectedFlowService

        run = await self._editable(actor, project_id, run_id)
        previous = maintenance_snapshot(run.selection_summary)
        if previous is not None and previous.proposals:
            raise _error("CONTEXT_ALREADY_LINKED", "已有维护提案关联, 请创建新的回归链路")
        await TestContextService(self._session).require_proposable(
            actor=actor,
            project_id=project_id,
            context_id=payload.context_id,
            revision_number=payload.after_revision,
        )
        comparison = await ContextInspectorService(self._session).compare_revisions(
            actor=actor, project_id=project_id, **payload.model_dump()
        )
        affected = await AffectedFlowService(self._session).analyze(
            actor=actor,
            project_id=project_id,
            **payload.model_dump(),
            impact_run_id=run.impact_run_id,
            page=1,
            page_size=100,
        )
        reference = f"context-diff://{payload.context_id}/{comparison.before_revision_id}/{comparison.after_revision_id}"
        snapshot = RegressionMaintenanceSnapshot(
            impact_run_id=run.impact_run_id,
            context_diff_ref=reference,
            knowledge_diff_ref=f"{reference}/knowledge",
            comparison=comparison,
            affected=affected,
        )
        return await self._save(run, actor, snapshot, "context_bound")

    async def link(
        self, *, actor: User, project_id: UUID, run_id: UUID, change_set_id: UUID
    ) -> ChangeRegressionBundle:
        run = await self._editable(actor, project_id, run_id)
        snapshot = _required_snapshot(run)
        evidence = await self._proposal(run, snapshot, change_set_id)
        if change_set_id in {item.change_set_id for item in snapshot.proposals}:
            return await self._bundle(run.id)
        if len(snapshot.proposals) >= 100:
            raise _error("PROPOSAL_LIMIT", "维护提案关联已达上限")
        snapshot.proposals.append(evidence)
        snapshot.review = None
        snapshot.required_workflows = []
        return await self._save(run, actor, snapshot, "proposal_linked")

    async def review(
        self, *, actor: User, project_id: UUID, run_id: UUID, payload: RegressionMaintenanceReview
    ) -> ChangeRegressionBundle:
        run = await self._editable(actor, project_id, run_id)
        snapshot = _required_snapshot(run)
        if contains_sensitive_contract_value(payload.note):
            raise _error("SENSITIVE_NOTE", "审核说明不能包含敏感值")
        if not snapshot.affected.analysis_complete and not payload.acknowledge_incomplete_analysis:
            raise _error("ANALYSIS_REVIEW_REQUIRED", "请明确确认未覆盖诊断和人工补充检查")
        snapshot.proposals = [
            await self._proposal(run, snapshot, item.change_set_id) for item in snapshot.proposals
        ]
        _require_resolved_proposals(snapshot)
        await self._current_context(actor, run, snapshot)
        snapshot.required_workflows = await RegressionMaintenanceCoverage(self._session).freeze(
            run, snapshot
        )
        snapshot.review = RegressionMaintenanceReviewEvidence(
            actor_id=actor.id,
            reviewed_at=datetime.now(UTC),
            note=payload.note.strip(),
            acknowledged_incomplete_analysis=payload.acknowledge_incomplete_analysis,
        )
        return await self._save(run, actor, snapshot, "maintenance_reviewed")

    async def require_review(self, run: ChangeRegressionRun, actor: User) -> None:
        snapshot = maintenance_snapshot(run.selection_summary)
        if snapshot is None:
            return
        await ProjectService(self._session).authorize(
            actor=actor, project_id=run.project_id, editing=True
        )
        if snapshot.review is None:
            raise _error("REVIEW_REQUIRED", "请先审核 Context 维护证据")
        for item in snapshot.proposals:
            current = await self._proposal(run, snapshot, item.change_set_id)
            if current != item:
                raise _error("REVIEW_STALE", "维护提案状态已变化, 请重新审核")
        _require_resolved_proposals(snapshot)
        await self._current_context(actor, run, snapshot)
        await RegressionMaintenanceCoverage(self._session).require_plan(run, check_draft=True)

    async def _current_context(
        self, actor: User, run: ChangeRegressionRun, snapshot: RegressionMaintenanceSnapshot
    ) -> None:
        current = await TestContextService(self._session).require_proposable(
            actor=actor,
            project_id=run.project_id,
            context_id=snapshot.comparison.context_id,
            revision_id=snapshot.comparison.after_revision_id,
        )
        if current.revision.fingerprint != snapshot.comparison.difference.after_fingerprint:
            raise _error("CONTEXT_STALE", "固定 Context 指纹不匹配")

    async def _editable(self, actor: User, project_id: UUID, run_id: UUID) -> ChangeRegressionRun:
        await ProjectService(self._session).authorize(
            actor=actor, project_id=project_id, editing=True
        )
        run = await self._session.scalar(
            select(ChangeRegressionRun)
            .where(ChangeRegressionRun.id == run_id, ChangeRegressionRun.project_id == project_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if run is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归不存在", status_code=404
            )
        if run.status != "review_required":
            raise _error("FROZEN", "仅待审核回归允许修改维护证据")
        return run

    async def _proposal(
        self, run: ChangeRegressionRun, snapshot: RegressionMaintenanceSnapshot, change_set_id: UUID
    ) -> RegressionProposalEvidence:
        change_set = await self._session.scalar(
            select(AIChangeSet)
            .where(AIChangeSet.id == change_set_id, AIChangeSet.project_id == run.project_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if change_set is None or proposal_origin(change_set.source_snapshot) != "maintenance":
            raise _error("PROPOSAL_MISMATCH", "必须关联同一项目的可信维护提案")
        if change_set.impact_run_id != run.impact_run_id:
            raise _error("PROPOSAL_MISMATCH", "维护提案所属 Impact 不匹配")
        try:
            provenance = FlowSpecMaintenanceProvenance.model_validate(
                change_set.source_snapshot.get("maintenance")
            )
        except ValidationError as error:
            raise _error("PROPOSAL_MISMATCH", "维护提案来源证据无效") from error
        _validate_provenance(run, snapshot, provenance)
        status = change_set.status
        return RegressionProposalEvidence(
            change_set_id=change_set.id,
            workflow_id=provenance.workflow_id,
            review_status="accepted"
            if status == "accepted"
            else "rejected"
            if status == "rejected"
            else "pending",
            applied=change_set.applied_at is not None,
        )

    async def _save(
        self,
        run: ChangeRegressionRun,
        actor: User,
        snapshot: RegressionMaintenanceSnapshot,
        action: str,
        *,
        commit: bool = True,
    ) -> ChangeRegressionBundle:
        value = snapshot.model_dump(mode="json")
        run.selection_summary = {**run.selection_summary, "context_maintenance": value}
        if run.change_set_id is not None:
            from app.services.change_regression import _snapshot_fingerprint

            change_set = await self._session.get(AIChangeSet, run.change_set_id)
            if change_set is not None:
                change_set.source_snapshot = {
                    **change_set.source_snapshot,
                    "schema_version": "s47.4-change-regression-v4",
                    "context_maintenance": value,
                }
                change_set.source_fingerprint = _snapshot_fingerprint(change_set.source_snapshot)
        self._session.add(
            ChangeRegressionStage(
                regression_run_id=run.id,
                sequence=await self._repository.next_stage_sequence(run.id),
                stage="review",
                status="completed",
                actor_id=actor.id,
                details={"action": action, "context_maintenance": value},
            )
        )
        AuditService(self._session).record(
            actor_user_id=actor.id,
            project_id=run.project_id,
            action=f"change_regression.{action}",
            resource_type="change_regression_run",
            resource_id=run.id,
            details={"context_id": str(snapshot.comparison.context_id)},
        )
        if commit:
            await self._session.commit()
        else:
            await self._session.flush()
        return await self._bundle(run.id)

    async def _bundle(self, run_id: UUID) -> ChangeRegressionBundle:
        result = await self._repository.get_bundle(run_id)
        if result is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归不存在", status_code=404
            )
        return result


def _required_snapshot(run: ChangeRegressionRun) -> RegressionMaintenanceSnapshot:
    snapshot = maintenance_snapshot(run.selection_summary)
    if snapshot is None:
        raise _error("CONTEXT_REQUIRED", "请先绑定 Context 对比")
    return snapshot


def _require_resolved_proposals(snapshot: RegressionMaintenanceSnapshot) -> None:
    if any(
        item.review_status == "pending" or (item.review_status == "accepted" and not item.applied)
        for item in snapshot.proposals
    ):
        raise _error("PROPOSAL_REVIEW_PENDING", "维护提案需完成审核; 已接受提案需先应用草稿")


def _validate_provenance(
    run: ChangeRegressionRun,
    snapshot: RegressionMaintenanceSnapshot,
    provenance: FlowSpecMaintenanceProvenance,
) -> None:
    comparison = snapshot.comparison
    actual = (
        provenance.context_id,
        provenance.before_context_revision_id,
        provenance.context_revision_id,
        provenance.before_context_fingerprint,
        provenance.context_fingerprint,
        provenance.impact_run_id,
    )
    expected = (
        comparison.context_id,
        comparison.before_revision_id,
        comparison.after_revision_id,
        comparison.difference.before_fingerprint,
        comparison.difference.after_fingerprint,
        run.impact_run_id,
    )
    workflows = {item.workflow_id for item in snapshot.affected.affected_workflows}
    if actual != expected or provenance.workflow_id not in workflows:
        raise _error("PROPOSAL_MISMATCH", "维护提案与固定 Context、Impact 或受影响流程不匹配")


def _error(code: str, message: str) -> AppError:
    return AppError(code=f"REGRESSION_MAINTENANCE_{code}", message=message, status_code=409)
