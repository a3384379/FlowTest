"""Read-only affected-flow selection; never creates a maintenance lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.affected_flows import (
    KnowledgeOperationImpact,
    OperationSelector,
    affected_knowledge_operations,
    match_operation,
)
from app.domain.change_regression import OperationIdentity
from app.engine.contracts import ApiNodeConfig, NodeType, WorkflowDefinition, WorkflowNode
from app.models.access import User
from app.models.test_contexts import TestContextRevision
from app.models.workflows import Workflow
from app.schemas.affected_flows import (
    AffectedFlowDiagnostic,
    AffectedFlowReason,
    AffectedFlowsResponse,
    AffectedWorkflow,
)
from app.services.change_regression import ChangeRegressionService
from app.services.context_inspector import ContextInspectorService
from app.services.impact import ImpactService


@dataclass(frozen=True)
class _OperationChange:
    source_ref: str
    selector: OperationSelector


@dataclass
class _Scan:
    knowledge: list[KnowledgeOperationImpact]
    changes: list[_OperationChange]
    diagnostics: list[AffectedFlowDiagnostic]
    mapped_workflows: dict[UUID, list[AffectedFlowReason]] = field(default_factory=dict)
    identities: dict[tuple[UUID, int | None], OperationIdentity | None] = field(
        default_factory=dict
    )
    remaining_nodes: int = 500
    remaining_comparisons: int = 100_000
    exhausted: bool = False


class AffectedFlowService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._inspector = ContextInspectorService(session)
        self._identities = ChangeRegressionService(session)

    async def analyze(
        self,
        *,
        actor: User,
        project_id: UUID,
        context_id: UUID,
        before_revision: int,
        after_revision: int,
        impact_run_id: UUID | None,
        page: int,
        page_size: int,
        workflow_id: UUID | None = None,
    ) -> AffectedFlowsResponse:
        comparison = await self._inspector.compare_revisions(
            actor=actor,
            project_id=project_id,
            context_id=context_id,
            before_revision=before_revision,
            after_revision=after_revision,
        )
        revisions = (
            await self._session.scalars(
                select(TestContextRevision).where(
                    TestContextRevision.id.in_(
                        [
                            comparison.before_revision_id,
                            comparison.after_revision_id,
                        ]
                    )
                )
            )
        ).all()
        snapshots = {item.id: self._inspector.revision_snapshot(item) for item in revisions}
        if not {comparison.before_revision_id, comparison.after_revision_id} <= snapshots.keys():
            raise AppError(
                code="TEST_CONTEXT_REVISION_NOT_FOUND",
                message="测试上下文版本不存在",
                status_code=404,
            )
        knowledge = affected_knowledge_operations(
            snapshots[comparison.before_revision_id].knowledge_snapshot,
            snapshots[comparison.after_revision_id].knowledge_snapshot,
        )
        scan = _Scan(
            knowledge.impacts,
            [],
            [
                AffectedFlowDiagnostic(code="KNOWLEDGE_IDENTITY_AMBIGUOUS", node_id=node_id)
                for node_id in knowledge.ambiguous_operation_node_ids
            ],
        )
        await self._impact_changes(scan, actor, project_id, impact_run_id)
        if comparison.difference.changed:
            # Structural links do not prove that every evidence/provider change is mapped.
            scan.diagnostics.append(AffectedFlowDiagnostic(code="CONTEXT_CHANGE_UNMAPPED"))
        condition = Workflow.project_id == project_id
        if workflow_id is not None:
            condition &= Workflow.id == workflow_id
        workflows = list(
            (
                await self._session.scalars(
                    select(Workflow)
                    .where(condition)
                    .order_by(Workflow.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(Workflow).where(condition))
            or 0
        )
        affected: list[AffectedWorkflow] = []
        scanned: list[UUID] = []
        for workflow in workflows:
            scanned.append(workflow.id)
            reasons = await self._workflow_reasons(scan, workflow, project_id)
            if reasons:
                affected.append(
                    AffectedWorkflow(
                        workflow_id=workflow.id,
                        draft_revision=workflow.draft_revision,
                        reasons=reasons,
                    )
                )
            if scan.exhausted:
                break
        return AffectedFlowsResponse(
            analysis_scope="workflow" if workflow_id is not None else "project",
            target_workflow_id=workflow_id,
            project_id=project_id,
            context_id=context_id,
            before_revision_id=comparison.before_revision_id,
            after_revision_id=comparison.after_revision_id,
            before_fingerprint=comparison.difference.before_fingerprint,
            after_fingerprint=comparison.difference.after_fingerprint,
            page=page,
            page_size=page_size,
            total_workflows=total,
            scanned_workflow_ids=scanned,
            affected_workflows=affected,
            diagnostics=scan.diagnostics,
            analysis_complete=page == 1 and len(scanned) == total and not scan.diagnostics,
        )

    async def _impact_changes(
        self, scan: _Scan, actor: User, project_id: UUID, run_id: UUID | None
    ) -> None:
        if run_id is None:
            return
        bundle = await ImpactService(
            self._session, enabled=settings.feature_impact_engine_enabled
        ).get_run(actor=actor, project_id=project_id, run_id=run_id)
        scan.mapped_workflows = _mapped_workflows(bundle.selection.selected_assets, run_id)
        for index, change in enumerate(bundle.run.changes):
            source_ref = f"impact://{run_id}/changes/{index}"
            selector = _change_selector(change)
            if selector is None:
                scan.diagnostics.append(
                    AffectedFlowDiagnostic(
                        code="IMPACT_CHANGE_UNMAPPED",
                        source_ref=source_ref,
                    )
                )
            else:
                scan.changes.append(_OperationChange(source_ref, selector))

    async def _workflow_reasons(
        self, scan: _Scan, workflow: Workflow, project_id: UUID
    ) -> list[AffectedFlowReason]:
        reasons = list(scan.mapped_workflows.get(workflow.id, []))
        if len(reasons) > 100:
            scan.diagnostics.append(
                AffectedFlowDiagnostic(
                    code="RESULT_TRUNCATED",
                    workflow_id=workflow.id,
                )
            )
            return reasons[:100]
        definition = _workflow_definition(scan, workflow)
        if definition is None:
            return reasons
        for node in sorted(definition.nodes, key=lambda item: item.id):
            identity = await self._node_identity(scan, workflow.id, node, project_id)
            if scan.exhausted:
                return reasons
            if identity is not None:
                comparison_count = len(scan.changes) + len(scan.knowledge)
                if comparison_count > scan.remaining_comparisons:
                    _exhaust_budget(scan, workflow.id, node.id)
                    return reasons
                scan.remaining_comparisons -= comparison_count
                reasons.extend(_matching_reasons(node.id, identity, scan))
            if len(reasons) > 100:
                scan.diagnostics.append(
                    AffectedFlowDiagnostic(
                        code="RESULT_TRUNCATED",
                        workflow_id=workflow.id,
                    )
                )
                return reasons[:100]
        return reasons

    async def _node_identity(
        self, scan: _Scan, workflow_id: UUID, node: WorkflowNode, project_id: UUID
    ) -> OperationIdentity | None:
        if node.effective_type is not NodeType.API:
            if node.effective_type in {
                NodeType.SUBFLOW,
                NodeType.FOR_EACH,
                NodeType.CAPABILITY,
                NodeType.SQL,
                NodeType.REDIS,
            }:
                scan.diagnostics.append(
                    AffectedFlowDiagnostic(
                        code="NODE_NOT_ANALYZED",
                        workflow_id=workflow_id,
                        node_id=node.id,
                    )
                )
            return None
        try:
            config = ApiNodeConfig.model_validate(node.effective_config)
        except ValidationError:
            scan.diagnostics.append(
                AffectedFlowDiagnostic(
                    code="WORKFLOW_INVALID",
                    workflow_id=workflow_id,
                    node_id=node.id,
                )
            )
            return None
        key = (config.api_definition_id, config.api_version)
        if key not in scan.identities:
            if len(scan.identities) >= 100:
                _exhaust_budget(scan, workflow_id, node.id)
                return None
            try:
                scan.identities[key] = await self._identities.resolve_operation_identity(
                    project_id=project_id,
                    definition_id=config.api_definition_id,
                    version_number=config.api_version,
                )
            except (AppError, ValueError):
                scan.identities[key] = None
        identity = scan.identities[key]
        if identity is None:
            scan.diagnostics.append(
                AffectedFlowDiagnostic(
                    code="API_UNRESOLVED",
                    workflow_id=workflow_id,
                    node_id=node.id,
                )
            )
        return identity


def _exhaust_budget(scan: _Scan, workflow_id: UUID, node_id: str | None = None) -> None:
    scan.exhausted = True
    scan.diagnostics.append(
        AffectedFlowDiagnostic(
            code="ANALYSIS_BUDGET_EXCEEDED",
            workflow_id=workflow_id,
            node_id=node_id,
        )
    )


def _workflow_definition(scan: _Scan, workflow: Workflow) -> WorkflowDefinition | None:
    raw_nodes = workflow.draft_definition.get("nodes", [])
    if isinstance(raw_nodes, list):
        if len(raw_nodes) > 200:
            scan.diagnostics.append(
                AffectedFlowDiagnostic(
                    code="WORKFLOW_NODE_BUDGET_EXCEEDED",
                    workflow_id=workflow.id,
                )
            )
            return None
        if len(raw_nodes) > scan.remaining_nodes:
            _exhaust_budget(scan, workflow.id)
            return None
        scan.remaining_nodes -= len(raw_nodes)
    try:
        return WorkflowDefinition.model_validate(workflow.draft_definition)
    except ValidationError:
        scan.diagnostics.append(
            AffectedFlowDiagnostic(code="WORKFLOW_INVALID", workflow_id=workflow.id)
        )
        return None


def _change_selector(change: dict[str, Any]) -> OperationSelector | None:
    try:
        selector = OperationSelector(
            api_definition_id=change.get("api_definition_id"),
            api_version=change.get("api_version"),
            service_key=change.get("service_key"),
            method=change.get("method"),
            normalized_path=change.get("normalized_path"),
            portable_operation_ref=change.get("portable_operation_ref"),
            contract_fingerprints=tuple(
                value
                for value in (
                    change.get("baseline_contract_fingerprint"),
                    change.get("current_contract_fingerprint"),
                )
                if value is not None
            ),
        )
    except ValidationError:
        return None
    if selector.api_definition_id is None and (
        selector.method is None or selector.normalized_path is None
    ):
        return None
    return selector


def _matching_reasons(
    node_id: str, identity: OperationIdentity, scan: _Scan
) -> list[AffectedFlowReason]:
    reasons: list[AffectedFlowReason] = []
    for change in scan.changes:
        strength = match_operation(change.selector, identity)
        if strength is not None:
            reasons.append(
                AffectedFlowReason(
                    node_id=node_id,
                    source_ref=change.source_ref,
                    match_strength=strength,
                    api_definition_id=identity.api_definition_id,
                    api_version=identity.api_version,
                    contract_fingerprint=identity.contract_fingerprint,
                )
            )
        if len(reasons) > 100:
            return reasons
    for impact in scan.knowledge:
        strength = match_operation(impact.selector, identity)
        if strength is not None:
            reasons.append(
                AffectedFlowReason(
                    node_id=node_id,
                    source_ref=f"knowledge://{impact.revision_side}/{impact.operation_node_id}",
                    match_strength="candidate" if impact.heuristic else strength,
                    api_definition_id=identity.api_definition_id,
                    api_version=identity.api_version,
                    contract_fingerprint=identity.contract_fingerprint,
                    knowledge_relation="heuristic" if impact.heuristic else "explicit",
                    changed_knowledge_node_ids=impact.changed_node_ids,
                )
            )
        if len(reasons) > 100:
            return reasons
    return reasons


def _mapped_workflows(
    assets: list[dict[str, Any]], run_id: UUID
) -> dict[UUID, list[AffectedFlowReason]]:
    result: dict[UUID, list[AffectedFlowReason]] = {}
    for index, asset in enumerate(assets):
        if asset.get("target_type") != "workflow":
            continue
        try:
            workflow_id = UUID(str(asset.get("target_id")))
        except ValueError:
            continue
        version = asset.get("version")
        result.setdefault(workflow_id, []).append(
            AffectedFlowReason(
                node_id=None,
                source_ref=f"impact://{run_id}/selection/{index}",
                match_strength="explicit_asset",
                asset_version=version if type(version) is int and version >= 1 else None,
            )
        )
    return result
