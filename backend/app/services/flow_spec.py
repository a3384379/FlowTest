from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.flow_spec import (
    FlowSpec,
    FlowSpecCompatibilityResult,
    FlowSpecDiffItem,
    FlowSpecNodeTarget,
    FlowSpecOperation,
    FlowSpecValidationResult,
    assess_flow_spec_compatibility,
    diff_flow_spec_payloads,
    diff_flow_specs,
    flow_spec_fingerprint,
    flow_spec_to_workflow_definition,
    normalize_flow_spec,
    validate_flow_spec,
    workflow_definition_to_flow_spec,
)
from app.domain.flow_spec import FlowSpecService as PortableService
from app.domain.flow_spec_v2 import (
    FlowSpecV2,
    assess_flow_spec_v2_compatibility,
    diff_flow_specs_v2,
    flow_spec_v2_fingerprint,
    flow_spec_v2_to_workflow_definition,
    normalize_flow_spec_v2,
    validate_flow_spec_v2,
    workflow_definition_to_flow_spec_v2,
)
from app.domain.integration_plans import (
    IntegrationPlan,
    IntegrationPlanCompilation,
    compile_integration_plan,
    integration_plan_fingerprint,
    normalize_integration_plan,
)
from app.domain.test_engineering import OperationContract, fingerprint_contract
from app.engine.contracts import ApiNodeConfig, NodeType, WorkflowDefinition, WorkflowRunPolicy
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion
from app.models.service_targets import Service
from app.models.workflows import Workflow
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.flow_spec import FlowSpecImportRequest
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.workflows import WorkflowService


@dataclass(frozen=True, slots=True)
class FlowSpecPipeline:
    spec: FlowSpec | FlowSpecV2
    fingerprint: str
    validation: FlowSpecValidationResult
    compatibility: FlowSpecCompatibilityResult


@dataclass(frozen=True, slots=True)
class FlowSpecExport:
    workflow: Workflow
    version: int | None
    pipeline: FlowSpecPipeline


@dataclass(frozen=True, slots=True)
class FlowSpecDiff:
    before_fingerprint: str | None
    after_fingerprint: str
    changes: tuple[FlowSpecDiffItem, ...]


@dataclass(frozen=True, slots=True)
class FlowSpecChangeSetView:
    change_set: AIChangeSet
    item: AIChangeItem
    pipeline: FlowSpecPipeline
    diff: tuple[FlowSpecDiffItem, ...]


@dataclass(frozen=True, slots=True)
class FlowSpecChangeSetCursor:
    created_at: datetime
    id: UUID


@dataclass(frozen=True, slots=True)
class FlowSpecProposalPage:
    views: tuple[FlowSpecChangeSetView, ...]
    next_cursor: FlowSpecChangeSetCursor | None


@dataclass(frozen=True, slots=True)
class FlowSpecVisualProposal:
    view: FlowSpecChangeSetView
    existing_definition: WorkflowDefinition | None
    proposed_definition: WorkflowDefinition
    integration_plan: IntegrationPlan | None
    compilation: IntegrationPlanCompilation | None
    service_mappings: Mapping[str, UUID]
    operation_mappings: Mapping[str, UUID]
    operation_version_mappings: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class FlowSpecImportProvenance:
    context_revision_id: UUID
    context_fingerprint: str
    source_ref: str
    service_account_id: UUID
    expected_target_revision: int | None = None
    integration_plan: IntegrationPlan | None = None
    compilation: IntegrationPlanCompilation | None = None


@dataclass(frozen=True, slots=True)
class FlowSpecRepairProvenance:
    execution_id: UUID
    context_revision_id: UUID
    context_fingerprint: str
    expected_target_revision: int
    patch_kind: str
    rationale: str
    diagnosis: Mapping[str, Any]
    oracle_weakening: bool = False


@dataclass(frozen=True, slots=True)
class FlowSpecImportPreview:
    pipeline: FlowSpecPipeline
    target_workflow_id: UUID | None
    target_revision: int | None


@dataclass(frozen=True, slots=True)
class _PreparedFlowSpecImport:
    pipeline: FlowSpecPipeline
    mappings: ResolvedFlowSpecMappings
    target: Workflow | None
    target_revision: int | None
    target_snapshot: str | None
    target_definition: WorkflowDefinition | None
    before: FlowSpec | None


@dataclass(frozen=True, slots=True)
class ResolvedFlowSpecMappings:
    service_ids: Mapping[str, UUID]
    service_keys: Mapping[str, str]
    operation_ids: Mapping[str, UUID]
    operation_versions: Mapping[str, int]

    def snapshot(self) -> dict[str, dict[str, str]]:
        return {
            "services": {key: str(value) for key, value in self.service_ids.items()},
            "operations": {key: str(value) for key, value in self.operation_ids.items()},
            "operation_versions": {
                key: str(value) for key, value in self.operation_versions.items()
            },
        }


class FlowSpecService:
    """Application service for portable FlowSpec parsing and reviewed imports."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._workflows = WorkflowRepository(session)
        self._api_assets = APIAssetRepository(session)
        self._targets = ServiceTargetRepository(session)
        self._audit = AuditService(session)

    async def export(
        self,
        *,
        actor: User,
        project_id: UUID,
        workflow_id: UUID,
        version: int | None,
    ) -> FlowSpecExport:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        workflow = await self._workflows.get(workflow_id)
        if workflow is None or workflow.project_id != project_id:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
        if version is None:
            definition = _load_definition(workflow.draft_definition)
            evidence = [f"workflow://{workflow.id}/draft/{workflow.draft_revision}"]
        else:
            published = await self._workflows.find_version(workflow.id, version)
            if published is None:
                raise AppError(
                    code="WORKFLOW_VERSION_NOT_FOUND", message="工作流版本不存在", status_code=404
                )
            definition = _load_definition(published.definition)
            evidence = [f"workflow://{workflow.id}/version/{published.version}"]
        pipeline = self._pipeline(
            await self._portable_spec(
                definition=definition,
                project_id=project_id,
                name=workflow.name,
                description=workflow.description,
                evidence=evidence,
            )
        )
        _require_pipeline_exportable(pipeline)
        return FlowSpecExport(workflow=workflow, version=version, pipeline=pipeline)

    async def validate(
        self, *, actor: User, project_id: UUID, spec: FlowSpec | FlowSpecV2
    ) -> FlowSpecPipeline:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        pipeline = self._pipeline(spec)
        return pipeline

    async def diff(
        self,
        *,
        actor: User,
        project_id: UUID,
        before: FlowSpec | FlowSpecV2 | None,
        after: FlowSpec | FlowSpecV2,
    ) -> FlowSpecDiff:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        after_pipeline = self._pipeline(after)
        before_pipeline = self._pipeline(before) if before is not None else None
        return FlowSpecDiff(
            before_fingerprint=(
                before_pipeline.fingerprint if before_pipeline is not None else None
            ),
            after_fingerprint=after_pipeline.fingerprint,
            changes=_diff_documents(
                before_pipeline.spec if before_pipeline is not None else None,
                after_pipeline.spec,
            ),
        )

    async def preview_import(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: FlowSpecImportRequest,
        provenance: FlowSpecImportProvenance | None = None,
    ) -> FlowSpecImportPreview:
        prepared = await self._prepare_import(
            actor=actor,
            project_id=project_id,
            payload=payload,
        )
        _validate_expected_target_revision(prepared, provenance)
        _validate_integration_plan_provenance(prepared.pipeline, provenance)
        return FlowSpecImportPreview(
            pipeline=prepared.pipeline,
            target_workflow_id=prepared.target.id if prepared.target is not None else None,
            target_revision=prepared.target_revision,
        )

    async def create_import(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: FlowSpecImportRequest,
        provenance: FlowSpecImportProvenance | None = None,
        repair_provenance: FlowSpecRepairProvenance | None = None,
    ) -> FlowSpecChangeSetView:
        prepared = await self._prepare_import(
            actor=actor,
            project_id=project_id,
            payload=payload,
        )
        _validate_expected_target_revision(prepared, provenance, repair_provenance)
        _validate_integration_plan_provenance(prepared.pipeline, provenance)
        snapshot = _source_snapshot(
            pipeline=prepared.pipeline,
            target_workflow_id=prepared.target.id if prepared.target is not None else None,
            target_revision=prepared.target_revision,
            target_spec=prepared.before,
            target_definition=prepared.target_definition,
            resource_mappings=prepared.mappings,
            provenance=provenance,
            repair_provenance=repair_provenance,
        )
        change_set = AIChangeSet(
            project_id=project_id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title=prepared.pipeline.spec.name,
            status="draft",
            source_snapshot=snapshot,
            source_fingerprint=prepared.pipeline.fingerprint,
            source_type="flow_spec",
            source_ref=(
                provenance.source_ref
                if provenance is not None
                else payload.source_ref or f"flow-spec://{prepared.pipeline.fingerprint}"
            ),
            actor_type="service_account" if provenance is not None else "user",
            actor_id=actor.id,
            created_by_id=actor.id,
            created_at=datetime.now(UTC),
        )
        self._session.add(change_set)
        await self._session.flush()
        item = AIChangeItem(
            change_set_id=change_set.id,
            suggestion_id=None,
            position=0,
            item_type="workflow",
            action="update" if prepared.target is not None else "create",
            title=prepared.pipeline.spec.name,
            target_resource_id=prepared.target.id if prepared.target is not None else None,
            target_snapshot_sha256=prepared.target_snapshot,
            proposed_content={
                "flow_spec": cast(dict[str, Any], _spec_json(prepared.pipeline.spec))
            },
            review_status="pending",
            review_note="",
        )
        self._session.add(item)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="flow_spec.import_drafted",
            resource_type="ai_change_set",
            resource_id=change_set.id,
            details={
                "source_type": "flow_spec",
                "source_fingerprint": prepared.pipeline.fingerprint,
                "target_workflow_id": (
                    str(prepared.target.id) if prepared.target is not None else None
                ),
                "requires_review": prepared.pipeline.compatibility.requires_review,
                "service_mapping_count": len(prepared.mappings.service_ids),
                "operation_mapping_count": len(prepared.mappings.operation_ids),
                "actor_type": change_set.actor_type,
                "context_revision_id": (
                    str(provenance.context_revision_id)
                    if provenance is not None
                    else str(repair_provenance.context_revision_id)
                    if repair_provenance is not None
                    else None
                ),
                "repair_execution_id": (
                    str(repair_provenance.execution_id) if repair_provenance is not None else None
                ),
                "repair_patch_kind": (
                    repair_provenance.patch_kind if repair_provenance is not None else None
                ),
            },
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        await self._session.refresh(item)
        return self._view(change_set, item, before=prepared.before)

    async def _prepare_import(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: FlowSpecImportRequest,
    ) -> _PreparedFlowSpecImport:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        pipeline = self._pipeline(payload.spec)
        _require_pipeline_importable(pipeline)
        mappings = await self._resolve_mappings(
            project_id=project_id,
            spec=pipeline.spec,
            service_mappings=payload.service_mappings,
            operation_mappings=payload.operation_mappings,
            operation_version_mappings=payload.operation_version_mappings,
        )
        target = await self._target_workflow(project_id, payload.workflow_id)
        target_definition = (
            _load_definition(target.draft_definition) if target is not None else None
        )
        before = (
            workflow_definition_to_flow_spec(
                target_definition,
                project_id=project_id,
                name=target.name,
                description=target.description,
                source_evidence=[f"workflow://{target.id}/draft/{target.draft_revision}"],
            )
            if target is not None and target_definition is not None
            else None
        )
        return _PreparedFlowSpecImport(
            pipeline=pipeline,
            mappings=mappings,
            target=target,
            target_revision=target.draft_revision if target is not None else None,
            target_snapshot=flow_spec_fingerprint(before) if before is not None else None,
            target_definition=target_definition,
            before=before,
        )

    async def list_change_sets(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[FlowSpecChangeSetView], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        condition = (AIChangeSet.project_id == project_id) & (
            AIChangeSet.source_type == "flow_spec"
        )
        change_sets = list(
            (
                await self._session.scalars(
                    select(AIChangeSet)
                    .where(condition)
                    .order_by(AIChangeSet.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(AIChangeSet).where(condition)
        )
        views = []
        for change_set in change_sets:
            item = await self._item(change_set.id)
            if item is not None:
                views.append(self._view(change_set, item))
        return views, int(total or 0)

    async def list_proposals(
        self,
        *,
        actor: User,
        project_id: UUID,
        page_size: int,
        cursor: FlowSpecChangeSetCursor | None,
        origin: Literal["mcp"] | None = None,
    ) -> FlowSpecProposalPage:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        condition = (AIChangeSet.project_id == project_id) & (
            AIChangeSet.source_type == "flow_spec"
        )
        if origin == "mcp":
            condition &= AIChangeSet.source_ref.startswith("mcp://")
        if cursor is not None:
            condition &= or_(
                AIChangeSet.created_at < cursor.created_at,
                and_(
                    AIChangeSet.created_at == cursor.created_at,
                    AIChangeSet.id < cursor.id,
                ),
            )
        change_sets = list(
            (
                await self._session.scalars(
                    select(AIChangeSet)
                    .where(condition)
                    .order_by(AIChangeSet.created_at.desc(), AIChangeSet.id.desc())
                    .limit(page_size + 1)
                )
            ).all()
        )
        selected = change_sets[:page_size]
        views = []
        for change_set in selected:
            item = await self._item(change_set.id)
            if item is not None:
                views.append(self._view(change_set, item))
        next_cursor = (
            FlowSpecChangeSetCursor(created_at=selected[-1].created_at, id=selected[-1].id)
            if len(change_sets) > page_size and selected
            else None
        )
        return FlowSpecProposalPage(views=tuple(views), next_cursor=next_cursor)

    async def list_mcp_proposals(
        self,
        *,
        actor: User,
        project_id: UUID,
        page_size: int,
        cursor: FlowSpecChangeSetCursor | None,
    ) -> FlowSpecProposalPage:
        return await self.list_proposals(
            actor=actor,
            project_id=project_id,
            page_size=page_size,
            cursor=cursor,
            origin="mcp",
        )

    async def get_change_set(
        self, *, actor: User, project_id: UUID, change_set_id: UUID
    ) -> FlowSpecChangeSetView:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        change_set = await self._get_change_set(change_set_id, project_id)
        item = await self._item(change_set.id)
        if item is None:
            raise AppError(
                code="FLOWSPEC_CHANGE_SET_INVALID",
                message="FlowSpec 变更集缺少变更项",
                status_code=409,
            )
        return self._view(change_set, item)

    async def get_visual_proposal(
        self, *, actor: User, project_id: UUID, change_set_id: UUID
    ) -> FlowSpecVisualProposal:
        view = await self.get_change_set(
            actor=actor,
            project_id=project_id,
            change_set_id=change_set_id,
        )
        snapshot = view.change_set.source_snapshot
        mappings = await self._mappings_from_snapshot(
            project_id=project_id,
            spec=view.pipeline.spec,
            snapshot=snapshot,
        )
        plan = _integration_plan_from_snapshot(snapshot)
        compilation = compile_integration_plan(plan) if plan is not None else None
        if plan is not None and compilation is not None:
            provenance = FlowSpecImportProvenance(
                context_revision_id=plan.context_revision_id,
                context_fingerprint=plan.context_fingerprint,
                source_ref=view.change_set.source_ref or "mcp://flow-proposals/unknown",
                service_account_id=_service_account_id(snapshot),
                integration_plan=plan,
                compilation=compilation,
            )
            _validate_integration_plan_provenance(view.pipeline, provenance)
        return FlowSpecVisualProposal(
            view=view,
            existing_definition=_target_definition_from_snapshot(snapshot),
            proposed_definition=_document_to_workflow_definition(
                view.pipeline.spec,
                operation_mappings=mappings.operation_ids,
                service_keys=mappings.service_keys,
                operation_versions=mappings.operation_versions,
            ),
            integration_plan=plan,
            compilation=compilation,
            service_mappings=mappings.service_ids,
            operation_mappings=mappings.operation_ids,
            operation_version_mappings=mappings.operation_versions,
        )

    async def review(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set_id: UUID,
        accept: bool,
        note: str,
    ) -> FlowSpecChangeSetView:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        change_set = await self._get_change_set(change_set_id, project_id, for_update=True)
        item = await self._item(change_set.id, for_update=True)
        if item is None:
            raise AppError(
                code="FLOWSPEC_CHANGE_SET_INVALID",
                message="FlowSpec 变更集缺少变更项",
                status_code=409,
            )
        if item.review_status != "pending":
            raise AppError(
                code="FLOWSPEC_ALREADY_REVIEWED",
                message="FlowSpec 变更集已经完成审核",
                status_code=409,
            )
        item.review_status = "accepted" if accept else "rejected"
        item.review_note = note.strip()
        item.reviewed_by_id = actor.id
        item.reviewed_at = datetime.now(UTC)
        change_set.status = "accepted" if accept else "rejected"
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="flow_spec.reviewed",
            resource_type="ai_change_set",
            resource_id=change_set.id,
            details={"accepted": accept},
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        await self._session.refresh(item)
        return self._view(change_set, item)

    async def apply(
        self, *, actor: User, project_id: UUID, change_set_id: UUID
    ) -> tuple[FlowSpecChangeSetView, Workflow]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        change_set = await self._get_change_set(change_set_id, project_id, for_update=True)
        item = await self._item(change_set.id, for_update=True)
        if item is None:
            raise AppError(
                code="FLOWSPEC_CHANGE_SET_INVALID",
                message="FlowSpec 变更集缺少变更项",
                status_code=409,
            )
        if change_set.status != "accepted" or item.review_status != "accepted":
            raise AppError(
                code="FLOWSPEC_REVIEW_REQUIRED",
                message="FlowSpec 必须审核通过后才能应用",
                status_code=409,
            )
        if change_set.applied_at is not None or item.materialized_resource_id is not None:
            raise AppError(
                code="FLOWSPEC_ALREADY_APPLIED",
                message="FlowSpec 变更集已经应用",
                status_code=409,
            )
        pipeline = self._pipeline(_spec_from_item(item))
        _require_pipeline_importable(pipeline)
        mappings = await self._mappings_from_snapshot(
            project_id=project_id,
            spec=pipeline.spec,
            snapshot=change_set.source_snapshot,
        )
        target_id = item.target_resource_id
        workflow: Workflow
        if target_id is None:
            workflow = await WorkflowService(self._session).create(
                actor=actor,
                project_id=project_id,
                name=pipeline.spec.name,
                description=pipeline.spec.description,
                folder_id=None,
                definition=_document_to_workflow_definition(
                    pipeline.spec,
                    operation_mappings=mappings.operation_ids,
                    service_keys=mappings.service_keys,
                    operation_versions=mappings.operation_versions,
                ),
                commit=False,
            )
        else:
            target_workflow = await self._workflows.get_for_update(target_id)
            if target_workflow is None or target_workflow.project_id != project_id:
                raise AppError(
                    code="WORKFLOW_NOT_FOUND", message="目标工作流不存在", status_code=404
                )
            expected_snapshot = item.target_snapshot_sha256
            if expected_snapshot is None:
                raise AppError(
                    code="FLOWSPEC_TARGET_INVALID",
                    message="FlowSpec 缺少目标快照",
                    status_code=409,
                )
            current_snapshot = flow_spec_fingerprint(self._target_spec(project_id, target_workflow))
            if current_snapshot != expected_snapshot:
                raise AppError(
                    code="FLOWSPEC_TARGET_CONFLICT",
                    message="目标工作流草稿已发生变化,请重新导入",
                    status_code=409,
                    details={"expected_fingerprint": expected_snapshot},
                )
            expected_revision = _target_revision(change_set.source_snapshot)
            if expected_revision is None:
                raise AppError(
                    code="FLOWSPEC_TARGET_INVALID",
                    message="FlowSpec 缺少目标草稿版本",
                    status_code=409,
                )
            workflow = await WorkflowService(self._session).update_draft(
                actor=actor,
                project_id=project_id,
                workflow_id=target_workflow.id,
                expected_revision=expected_revision,
                name=pipeline.spec.name,
                description=pipeline.spec.description,
                folder_id=None,
                change_folder=False,
                definition=_document_to_workflow_definition(
                    pipeline.spec,
                    operation_mappings=mappings.operation_ids,
                    service_keys=mappings.service_keys,
                    operation_versions=mappings.operation_versions,
                ),
                commit=False,
            )
        item.materialized_resource_type = "workflow"
        item.materialized_resource_id = workflow.id
        change_set.applied_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="flow_spec.applied",
            resource_type="workflow",
            resource_id=workflow.id,
            details={"change_set_id": str(change_set.id), "fingerprint": pipeline.fingerprint},
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        await self._session.refresh(item)
        await self._session.refresh(workflow)
        return self._view(change_set, item), workflow

    def _pipeline(self, spec: FlowSpec | FlowSpecV2) -> FlowSpecPipeline:
        try:
            if isinstance(spec, FlowSpecV2):
                normalized_v2 = normalize_flow_spec_v2(spec)
                return FlowSpecPipeline(
                    spec=normalized_v2,
                    fingerprint=flow_spec_v2_fingerprint(normalized_v2),
                    validation=validate_flow_spec_v2(normalized_v2),
                    compatibility=assess_flow_spec_v2_compatibility(normalized_v2),
                )
            normalized = normalize_flow_spec(spec)
        except (TypeError, ValueError, ValidationError) as error:
            raise AppError(
                code="FLOWSPEC_PARSE_FAILED",
                message="FlowSpec 无法解析或不符合 v1 契约",
                status_code=422,
            ) from error
        validation = validate_flow_spec(normalized)
        compatibility = assess_flow_spec_compatibility(normalized)
        return FlowSpecPipeline(
            spec=normalized,
            fingerprint=flow_spec_fingerprint(normalized),
            validation=validation,
            compatibility=compatibility,
        )

    async def _resolve_mappings(
        self,
        *,
        project_id: UUID,
        spec: FlowSpec | FlowSpecV2,
        service_mappings: Mapping[str, UUID],
        operation_mappings: Mapping[str, UUID],
        operation_version_mappings: Mapping[str, int],
    ) -> ResolvedFlowSpecMappings:
        _reject_unknown_mapping_refs(
            requested=service_mappings,
            known={service.ref for service in spec.services},
            kind="Service",
        )
        _reject_unknown_mapping_refs(
            requested=operation_mappings,
            known={operation.ref for operation in spec.operations},
            kind="Operation",
        )
        _reject_unknown_mapping_refs(
            requested=operation_version_mappings,
            known={operation.ref for operation in spec.operations},
            kind="Operation Version",
        )
        service_ids: dict[str, UUID] = {}
        service_keys: dict[str, str] = {}
        for service_spec in spec.services:
            service = await self._resolve_service_mapping(
                project_id=project_id,
                portable_ref=service_spec.ref,
                requested_id=service_mappings.get(service_spec.ref),
            )
            service_ids[service_spec.ref] = service.id
            service_keys[service_spec.ref] = service.service_key
        operation_ids: dict[str, UUID] = {}
        operation_versions: dict[str, int] = {}
        for operation in spec.operations:
            definition, version = await self._resolve_operation_mapping(
                project_id=project_id,
                operation=operation,
                requested_id=operation_mappings.get(operation.ref),
                requested_version=operation_version_mappings.get(operation.ref),
                service_ids=service_ids,
            )
            operation_ids[operation.ref] = definition.id
            operation_versions[operation.ref] = version.version
        return ResolvedFlowSpecMappings(
            service_ids=service_ids,
            service_keys=service_keys,
            operation_ids=operation_ids,
            operation_versions=operation_versions,
        )

    async def _resolve_service_mapping(
        self, *, project_id: UUID, portable_ref: str, requested_id: UUID | None
    ) -> Service:
        service = (
            await self._targets.get_service(requested_id)
            if requested_id is not None
            else await self._targets.find_service_by_key(
                project_id=project_id, service_key=portable_ref
            )
        )
        if service is None or service.project_id != project_id:
            raise _mapping_error(
                code="FLOWSPEC_SERVICE_MAPPING_INVALID",
                message=f"Service {portable_ref} 未映射到目标项目资源",
                path=f"$.service_mappings.{portable_ref}",
            )
        return service

    async def _resolve_operation_mapping(
        self,
        *,
        project_id: UUID,
        operation: FlowSpecOperation,
        requested_id: UUID | None,
        requested_version: int | None,
        service_ids: Mapping[str, UUID],
    ) -> tuple[APIDefinition, APIVersion]:
        if requested_id is not None:
            definition = await self._api_assets.get_definition(requested_id)
            candidates = [definition] if definition is not None else []
        else:
            candidates = await self._operation_candidates(
                project_id=project_id,
                operation=operation,
                service_id=service_ids.get(operation.service_ref or ""),
            )
        if len(candidates) != 1 or candidates[0].project_id != project_id:
            raise _mapping_error(
                code="FLOWSPEC_OPERATION_MAPPING_INVALID",
                message=f"Operation {operation.ref} 无法唯一映射到目标项目 API",
                path=f"$.operation_mappings.{operation.ref}",
            )
        definition = candidates[0]
        version = await self._validate_operation_mapping(
            definition=definition,
            operation=operation,
            requested_version=requested_version,
            expected_service_id=service_ids.get(operation.service_ref or ""),
        )
        return definition, version

    async def _operation_candidates(
        self,
        *,
        project_id: UUID,
        operation: FlowSpecOperation,
        service_id: UUID | None,
    ) -> list[APIDefinition]:
        query = (
            select(APIDefinition, APIVersion)
            .join(APIVersion, APIVersion.api_definition_id == APIDefinition.id)
            .where(
                APIDefinition.project_id == project_id,
                APIDefinition.is_active.is_(True),
                APIVersion.method == operation.method,
                APIVersion.path == operation.path,
            )
        )
        if operation.version_strategy == "current":
            query = query.where(APIVersion.version == APIDefinition.current_version)
        elif operation.contract_fingerprint is None and operation.api_version is not None:
            query = query.where(APIVersion.version == operation.api_version)
        if service_id is not None:
            query = query.where(APIVersion.service_id == service_id)
        rows = (await self._session.execute(query)).all()
        candidates_by_id = {
            definition.id: definition
            for definition, version in rows
            if _operation_contract_matches(version, operation)
        }
        candidates = list(candidates_by_id.values())
        semantic_key = operation.ref.rsplit(":", 1)[-1]
        exact = [item for item in candidates if item.import_key == semantic_key]
        return exact if exact else candidates

    async def _validate_operation_mapping(
        self,
        *,
        definition: APIDefinition,
        operation: FlowSpecOperation,
        requested_version: int | None,
        expected_service_id: UUID | None,
    ) -> APIVersion:
        if (
            requested_version is not None
            and operation.version_strategy == "current"
            and requested_version != definition.current_version
        ):
            raise _mapping_error(
                code="FLOWSPEC_API_VERSION_INCOMPATIBLE",
                message=f"Operation {operation.ref} 的目标 current version 已变化",
                path=f"$.operation_version_mappings.{operation.ref}",
            )
        version_number = requested_version
        if version_number is None:
            version_number = _default_operation_version(definition, operation)
        version_query = select(APIVersion).where(APIVersion.api_definition_id == definition.id)
        if version_number is not None:
            version_query = version_query.where(APIVersion.version == version_number)
        elif operation.contract_fingerprint is None:
            version_query = version_query.where(APIVersion.version == operation.api_version)
        versions = list((await self._session.scalars(version_query)).all())
        if operation.contract_fingerprint is not None:
            versions = [
                version for version in versions if _operation_contract_matches(version, operation)
            ]
        if len(versions) != 1:
            raise _mapping_error(
                code="FLOWSPEC_API_VERSION_INCOMPATIBLE",
                message=f"Operation {operation.ref} 在目标 API 中没有唯一兼容版本",
                path=f"$.operation_mappings.{operation.ref}",
            )
        version = versions[0]
        if operation.contract_fingerprint is not None and not _operation_contract_matches(
            version, operation
        ):
            raise _mapping_error(
                code="FLOWSPEC_API_VERSION_INCOMPATIBLE",
                message=f"Operation {operation.ref} 的目标版本 Contract Fingerprint 不兼容",
                path=f"$.operation_version_mappings.{operation.ref}",
            )
        if (version.method, version.path) != (
            operation.method,
            operation.path,
        ):
            raise _mapping_error(
                code="FLOWSPEC_OPERATION_SEMANTICS_MISMATCH",
                message=f"Operation {operation.ref} 的 method/path 与目标 API 不一致",
                path=f"$.operation_mappings.{operation.ref}",
            )
        if expected_service_id is not None and version.service_id != expected_service_id:
            raise _mapping_error(
                code="FLOWSPEC_OPERATION_SERVICE_MISMATCH",
                message=f"Operation {operation.ref} 与目标 Service 不一致",
                path=f"$.operation_mappings.{operation.ref}",
            )
        return version

    async def _mappings_from_snapshot(
        self,
        *,
        project_id: UUID,
        spec: FlowSpec | FlowSpecV2,
        snapshot: Mapping[str, Any],
    ) -> ResolvedFlowSpecMappings:
        service_mappings, operation_mappings, operation_version_mappings = _mapping_ids(snapshot)
        return await self._resolve_mappings(
            project_id=project_id,
            spec=spec,
            service_mappings=service_mappings,
            operation_mappings=operation_mappings,
            operation_version_mappings=operation_version_mappings,
        )

    async def _target_workflow(self, project_id: UUID, workflow_id: UUID | None) -> Workflow | None:
        if workflow_id is None:
            return None
        workflow = await self._workflows.get(workflow_id)
        if workflow is None or workflow.project_id != project_id:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
        return workflow

    async def _get_change_set(
        self, change_set_id: UUID, project_id: UUID, *, for_update: bool = False
    ) -> AIChangeSet:
        query = select(AIChangeSet).where(
            AIChangeSet.id == change_set_id,
            AIChangeSet.project_id == project_id,
            AIChangeSet.source_type == "flow_spec",
        )
        if for_update:
            query = query.with_for_update()
        change_set = (await self._session.execute(query)).scalar_one_or_none()
        if change_set is None:
            raise AppError(
                code="FLOWSPEC_CHANGE_SET_NOT_FOUND",
                message="FlowSpec 变更集不存在",
                status_code=404,
            )
        return change_set

    async def _item(self, change_set_id: UUID, *, for_update: bool = False) -> AIChangeItem | None:
        query = select(AIChangeItem).where(AIChangeItem.change_set_id == change_set_id)
        if for_update:
            query = query.with_for_update()
        return (
            await self._session.execute(query.order_by(AIChangeItem.position))
        ).scalar_one_or_none()

    def _view(
        self,
        change_set: AIChangeSet,
        item: AIChangeItem,
        *,
        before: FlowSpec | None = None,
    ) -> FlowSpecChangeSetView:
        pipeline = self._pipeline(_spec_from_item(item))
        if before is None and item.target_resource_id is not None:
            before = _snapshot_target_spec(change_set.source_snapshot)
        return FlowSpecChangeSetView(
            change_set=change_set,
            item=item,
            pipeline=pipeline,
            diff=_diff_documents(before, pipeline.spec),
        )

    def _target_spec(self, project_id: UUID, workflow: Workflow) -> FlowSpec:
        return workflow_definition_to_flow_spec(
            _load_definition(workflow.draft_definition),
            project_id=project_id,
            name=workflow.name,
            description=workflow.description,
            source_evidence=[f"workflow://{workflow.id}/draft/{workflow.draft_revision}"],
        )

    async def _portable_spec(
        self,
        *,
        definition: WorkflowDefinition,
        project_id: UUID,
        name: str,
        description: str,
        evidence: list[str],
    ) -> FlowSpec | FlowSpecV2:
        operation_refs: dict[str, str] = {}
        targets: dict[str, FlowSpecNodeTarget] = {}
        services: dict[str, PortableService] = {}
        operations: dict[str, FlowSpecOperation] = {}
        for node in definition.nodes:
            if node.type is not NodeType.API:
                continue
            config = ApiNodeConfig.model_validate(node.config)
            api_definition, api_version = await self._portable_api_asset(
                project_id=project_id, config=config
            )
            operation_service = await self._portable_target_service(
                project_id=project_id,
                service_override=None,
                version_service_id=api_version.service_id,
            )
            target_service = await self._portable_target_service(
                project_id=project_id,
                service_override=config.service_override,
                version_service_id=api_version.service_id,
            )
            operation_service_ref = (
                operation_service.service_key if operation_service is not None else None
            )
            target_service_ref = target_service.service_key if target_service is not None else None
            operation_ref = _portable_operation_ref(
                service_ref=operation_service_ref,
                definition=api_definition,
                version=api_version,
            )
            operation_refs[node.id] = operation_ref
            targets[node.id] = FlowSpecNodeTarget(
                service_ref=target_service_ref,
                endpoint_variant=config.endpoint_variant,
            )
            operations[operation_ref] = FlowSpecOperation(
                ref=operation_ref,
                service_ref=operation_service_ref,
                name=api_definition.name,
                method=api_version.method,
                path=api_version.path,
                version_strategy="pinned" if config.api_version is not None else "current",
                source_version=api_version.version,
                contract_fingerprint=_portable_contract_fingerprint(
                    api_version,
                    service_ref=operation_service_ref,
                ),
            )
            for service in (operation_service, target_service):
                if service is not None:
                    services[service.service_key] = PortableService(
                        ref=service.service_key,
                        name=service.name,
                        service_type=service.service_type,
                    )
        converter = (
            workflow_definition_to_flow_spec_v2
            if any(node.phase.value == "cleanup" for node in definition.nodes)
            or definition.run_policy != WorkflowRunPolicy()
            else workflow_definition_to_flow_spec
        )
        return converter(
            definition,
            project_id=project_id,
            name=name,
            description=description,
            source_evidence=evidence,
            operation_refs=operation_refs,
            node_targets=targets,
            services=list(services.values()),
            operations=list(operations.values()),
        )

    async def _portable_api_asset(
        self, *, project_id: UUID, config: ApiNodeConfig
    ) -> tuple[APIDefinition, APIVersion]:
        definition = await self._api_assets.get_definition(config.api_definition_id)
        if definition is None or definition.project_id != project_id:
            raise AppError(
                code="FLOWSPEC_API_NOT_FOUND",
                message="工作流引用的 API 定义不存在于当前项目",
                status_code=422,
            )
        version_number = config.api_version or definition.current_version
        version = await self._api_assets.get_version(
            definition_id=definition.id, version=version_number
        )
        if version is None:
            raise AppError(
                code="FLOWSPEC_API_VERSION_NOT_FOUND",
                message="工作流引用的 API 版本不存在",
                status_code=422,
            )
        return definition, version

    async def _portable_target_service(
        self,
        *,
        project_id: UUID,
        service_override: str | None,
        version_service_id: UUID | None,
    ) -> Service | None:
        if service_override is not None:
            service = await self._targets.find_service_by_key(
                project_id=project_id, service_key=service_override
            )
        elif version_service_id is not None:
            service = await self._targets.get_service(version_service_id)
        else:
            return None
        if service is None or service.project_id != project_id:
            raise AppError(
                code="FLOWSPEC_SERVICE_NOT_FOUND",
                message="工作流引用的 Service 不存在于当前项目",
                status_code=422,
            )
        return service


def _load_definition(value: dict[str, Any]) -> WorkflowDefinition:
    try:
        return WorkflowDefinition.model_validate(value)
    except (TypeError, ValueError, ValidationError) as error:
        raise AppError(
            code="INVALID_WORKFLOW_DEFINITION",
            message="工作流定义无效,无法导出 FlowSpec",
            status_code=422,
        ) from error


def _portable_operation_ref(
    *, service_ref: str | None, definition: APIDefinition, version: APIVersion
) -> str:
    semantic_key = definition.import_key
    if semantic_key is None:
        payload = f"{version.method}:{version.path}".encode()
        semantic_key = sha256(payload).hexdigest()[:20]
    return f"operation:{service_ref or 'unbound'}:{semantic_key}"


def _source_snapshot(
    *,
    pipeline: FlowSpecPipeline,
    target_workflow_id: UUID | None,
    target_revision: int | None,
    target_spec: FlowSpec | None,
    target_definition: WorkflowDefinition | None,
    resource_mappings: ResolvedFlowSpecMappings,
    provenance: FlowSpecImportProvenance | None = None,
    repair_provenance: FlowSpecRepairProvenance | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "flow_spec": _spec_json(pipeline.spec),
        "validation": pipeline.validation.model_dump(mode="json"),
        "compatibility": pipeline.compatibility.model_dump(mode="json"),
        "target_workflow_id": str(target_workflow_id) if target_workflow_id is not None else None,
        "target_revision": target_revision,
        "target_spec": _spec_json(target_spec) if target_spec is not None else None,
        "target_definition": (
            target_definition.model_dump(mode="json") if target_definition is not None else None
        ),
        "resource_mappings": resource_mappings.snapshot(),
    }
    if provenance is not None:
        snapshot.update(
            {
                "proposal_schema_version": "v6-flow-proposal-source-v1",
                "context_revision_id": str(provenance.context_revision_id),
                "context_fingerprint": provenance.context_fingerprint,
                "service_account_id": str(provenance.service_account_id),
                "expected_target_revision": provenance.expected_target_revision,
            }
        )
        if provenance.integration_plan is not None and provenance.compilation is not None:
            plan = normalize_integration_plan(provenance.integration_plan)
            compilation = provenance.compilation
            snapshot.update(
                {
                    "integration_plan": plan.model_dump(mode="json"),
                    "integration_plan_fingerprint": plan.plan_fingerprint,
                    "integration_plan_compiler": {
                        "version": compilation.compiler_version,
                        "flow_spec_fingerprint": compilation.flow_spec_fingerprint,
                        "diagnostics": [
                            item.model_dump(mode="json") for item in compilation.diagnostics
                        ],
                        "passes": [item.model_dump(mode="json") for item in compilation.passes],
                        "node_evidence": [
                            item.model_dump(mode="json") for item in compilation.node_evidence
                        ],
                        "edge_evidence": [
                            item.model_dump(mode="json") for item in compilation.edge_evidence
                        ],
                    },
                }
            )
    if repair_provenance is not None:
        snapshot.update(
            {
                "proposal_schema_version": "v6-repair-proposal-source-v1",
                "context_revision_id": str(repair_provenance.context_revision_id),
                "context_fingerprint": repair_provenance.context_fingerprint,
                "repair": {
                    "execution_id": str(repair_provenance.execution_id),
                    "expected_target_revision": repair_provenance.expected_target_revision,
                    "patch_kind": repair_provenance.patch_kind,
                    "rationale": repair_provenance.rationale,
                    "oracle_weakening": repair_provenance.oracle_weakening,
                    "diagnosis": dict(repair_provenance.diagnosis),
                },
            }
        )
    return snapshot


def _validate_integration_plan_provenance(
    pipeline: FlowSpecPipeline,
    provenance: FlowSpecImportProvenance | None,
) -> None:
    if provenance is None:
        return
    plan = provenance.integration_plan
    compilation = provenance.compilation
    if (plan is None) != (compilation is None):
        raise _integration_plan_provenance_error(
            "Integration Plan 与编译结果必须同时提供",
        )
    if plan is None or compilation is None:
        return
    normalized = normalize_integration_plan(plan)
    expected = compile_integration_plan(normalized)
    consistent = (
        normalized.context_revision_id == provenance.context_revision_id
        and normalized.context_fingerprint == provenance.context_fingerprint
        and normalized.plan_fingerprint == integration_plan_fingerprint(normalized)
        and expected.importable
        and expected.flow_spec_fingerprint == pipeline.fingerprint
        and compilation == expected
    )
    if not consistent:
        raise _integration_plan_provenance_error(
            "Integration Plan 编译证据与 Context 或 FlowSpec 不一致",
        )


def _validate_expected_target_revision(
    prepared: _PreparedFlowSpecImport,
    provenance: FlowSpecImportProvenance | None,
    repair_provenance: FlowSpecRepairProvenance | None = None,
) -> None:
    if provenance is None and repair_provenance is None:
        return
    if provenance is not None and repair_provenance is not None:
        raise RuntimeError("FlowSpec import cannot combine MCP and Repair provenance")
    expected = (
        provenance.expected_target_revision
        if provenance is not None
        else repair_provenance.expected_target_revision
        if repair_provenance is not None
        else None
    )
    actual = prepared.target_revision
    if prepared.target is None and expected is not None:
        raise AppError(
            code="FLOWSPEC_EXPECTED_REVISION_INVALID",
            message="新建 Workflow Proposal 不接受 Expected Revision",
            status_code=422,
        )
    if prepared.target is not None and expected is None:
        raise AppError(
            code="FLOWSPEC_EXPECTED_REVISION_REQUIRED",
            message="更新现有 Workflow 必须提供 Expected Revision",
            status_code=422,
        )
    if expected is not None and expected != actual:
        raise AppError(
            code="FLOWSPEC_TARGET_CONFLICT",
            message="Workflow 草稿已变化,请基于最新 Revision 重新生成 Proposal",
            status_code=409,
            details={"expected_revision": expected, "actual_revision": actual},
        )


def _integration_plan_provenance_error(message: str) -> AppError:
    return AppError(
        code="INTEGRATION_PLAN_PROVENANCE_INVALID",
        message=message,
        status_code=422,
    )


def _integration_plan_from_snapshot(snapshot: Mapping[str, Any]) -> IntegrationPlan | None:
    raw = snapshot.get("integration_plan")
    if raw is None:
        return None
    try:
        return IntegrationPlan.model_validate(raw)
    except (TypeError, ValueError, ValidationError) as error:
        raise AppError(
            code="FLOWSPEC_PROPOSAL_SNAPSHOT_INVALID",
            message="Flow Proposal 的 Integration Plan 快照无效",
            status_code=409,
        ) from error


def _target_definition_from_snapshot(
    snapshot: Mapping[str, Any],
) -> WorkflowDefinition | None:
    raw = snapshot.get("target_definition")
    if raw is None:
        return None
    try:
        return WorkflowDefinition.model_validate(raw)
    except (TypeError, ValueError, ValidationError) as error:
        raise AppError(
            code="FLOWSPEC_PROPOSAL_SNAPSHOT_INVALID",
            message="Flow Proposal 的 Existing Graph 快照无效",
            status_code=409,
        ) from error


def _service_account_id(snapshot: Mapping[str, Any]) -> UUID:
    try:
        return UUID(str(snapshot["service_account_id"]))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise AppError(
            code="FLOWSPEC_PROPOSAL_SNAPSHOT_INVALID",
            message="Flow Proposal 的 Service Account 快照无效",
            status_code=409,
        ) from error


def _mapping_ids(
    snapshot: Mapping[str, Any],
) -> tuple[dict[str, UUID], dict[str, UUID], dict[str, int]]:
    raw = snapshot.get("resource_mappings")
    if not isinstance(raw, dict):
        raise _mapping_error(
            code="FLOWSPEC_MAPPING_SNAPSHOT_INVALID",
            message="FlowSpec 变更集缺少资源映射快照",
            path="$.resource_mappings",
        )
    return (
        _uuid_mapping(raw.get("services")),
        _uuid_mapping(raw.get("operations")),
        _int_mapping(raw.get("operation_versions")),
    )


def _uuid_mapping(value: object) -> dict[str, UUID]:
    if not isinstance(value, dict):
        raise _mapping_error(
            code="FLOWSPEC_MAPPING_SNAPSHOT_INVALID",
            message="FlowSpec 资源映射快照无效",
            path="$.resource_mappings",
        )
    try:
        return {str(key): UUID(str(item)) for key, item in value.items()}
    except (TypeError, ValueError, AttributeError) as error:
        raise _mapping_error(
            code="FLOWSPEC_MAPPING_SNAPSHOT_INVALID",
            message="FlowSpec 资源映射快照包含无效 UUID",
            path="$.resource_mappings",
        ) from error


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _mapping_error(
            code="FLOWSPEC_MAPPING_SNAPSHOT_INVALID",
            message="FlowSpec Operation Version 映射快照无效",
            path="$.resource_mappings.operation_versions",
        )
    try:
        result = {str(key): int(item) for key, item in value.items()}
    except (TypeError, ValueError) as error:
        raise _mapping_error(
            code="FLOWSPEC_MAPPING_SNAPSHOT_INVALID",
            message="FlowSpec Operation Version 映射包含无效版本号",
            path="$.resource_mappings.operation_versions",
        ) from error
    if any(version < 1 for version in result.values()):
        raise _mapping_error(
            code="FLOWSPEC_MAPPING_SNAPSHOT_INVALID",
            message="FlowSpec Operation Version 映射版本号必须大于零",
            path="$.resource_mappings.operation_versions",
        )
    return result


def _reject_unknown_mapping_refs(
    *, requested: Mapping[str, object], known: set[str], kind: str
) -> None:
    unknown = sorted(set(requested) - known)
    if unknown:
        raise _mapping_error(
            code="FLOWSPEC_MAPPING_UNKNOWN_REF",
            message=f"{kind} 映射包含 FlowSpec 未声明的 ref: {', '.join(unknown)}",
            path=f"$.{kind.lower()}_mappings",
        )


def _mapping_error(*, code: str, message: str, path: str) -> AppError:
    return AppError(
        code=code,
        message=message,
        status_code=422,
        details={"blockers": [{"code": code, "message": message, "path": path}]},
    )


def _portable_contract_fingerprint(
    version: APIVersion,
    *,
    service_ref: str | None,
) -> str | None:
    if not version.canonical_contract:
        return version.contract_fingerprint
    contract = OperationContract.model_validate(version.canonical_contract).model_copy(
        update={"service": service_ref}
    )
    return fingerprint_contract(contract)


def _default_operation_version(
    definition: APIDefinition,
    operation: FlowSpecOperation,
) -> int | None:
    if operation.version_strategy == "current":
        return definition.current_version
    if operation.version_strategy == "pinned":
        return operation.source_version
    return None


def _operation_contract_matches(version: APIVersion, operation: FlowSpecOperation) -> bool:
    fingerprint = operation.contract_fingerprint
    if fingerprint is None:
        return True
    return fingerprint in {
        version.contract_fingerprint,
        _portable_contract_fingerprint(
            version,
            service_ref=operation.service_ref,
        ),
    }


def _spec_json(spec: FlowSpec | FlowSpecV2) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], spec.model_dump(mode="json", by_alias=True))


def _spec_from_item(item: AIChangeItem) -> FlowSpec | FlowSpecV2:
    raw = item.proposed_content.get("flow_spec")
    if not isinstance(raw, dict):
        raise AppError(
            code="FLOWSPEC_CHANGE_SET_INVALID",
            message="FlowSpec 变更项内容无效",
            status_code=409,
        )
    try:
        if raw.get("schema_version") == "flowtest-flow-spec-v2":
            return FlowSpecV2.model_validate(raw)
        return FlowSpec.model_validate(raw)
    except (TypeError, ValueError, ValidationError) as error:
        raise AppError(
            code="FLOWSPEC_CHANGE_SET_INVALID",
            message="FlowSpec 变更项内容无法解析",
            status_code=409,
        ) from error


def _document_to_workflow_definition(
    spec: FlowSpec | FlowSpecV2,
    *,
    operation_mappings: Mapping[str, UUID],
    service_keys: Mapping[str, str],
    operation_versions: Mapping[str, int],
) -> WorkflowDefinition:
    if isinstance(spec, FlowSpecV2):
        return flow_spec_v2_to_workflow_definition(
            spec,
            operation_mappings=operation_mappings,
            service_keys=service_keys,
            operation_versions=operation_versions,
        )
    return flow_spec_to_workflow_definition(
        spec,
        operation_mappings=operation_mappings,
        service_keys=service_keys,
        operation_versions=operation_versions,
    )


def _diff_documents(
    before: FlowSpec | FlowSpecV2 | None,
    after: FlowSpec | FlowSpecV2,
) -> tuple[FlowSpecDiffItem, ...]:
    if isinstance(before, FlowSpecV2) and isinstance(after, FlowSpecV2):
        return diff_flow_specs_v2(before, after)
    if (before is None or isinstance(before, FlowSpec)) and isinstance(after, FlowSpec):
        return diff_flow_specs(before, after)
    before_payload = _spec_json(before) if before is not None else None
    return diff_flow_spec_payloads(before_payload, _spec_json(after))


def _snapshot_target_spec(snapshot: dict[str, Any]) -> FlowSpec | None:
    raw = snapshot.get("target_spec")
    if not isinstance(raw, dict):
        return None
    try:
        return FlowSpec.model_validate(raw)
    except (TypeError, ValueError, ValidationError):
        return None


def _target_revision(snapshot: dict[str, Any]) -> int | None:
    value = snapshot.get("target_revision")
    return value if isinstance(value, int) else None


def _require_pipeline_exportable(pipeline: FlowSpecPipeline) -> None:
    if not pipeline.validation.valid:
        raise AppError(
            code="FLOWSPEC_EXPORT_INVALID",
            message="工作流无法导出为有效 FlowSpec",
            status_code=422,
            details={"validation": pipeline.validation.model_dump(mode="json")},
        )


def _require_pipeline_importable(pipeline: FlowSpecPipeline) -> None:
    if not pipeline.validation.valid or not pipeline.compatibility.compatible:
        raise AppError(
            code="FLOWSPEC_IMPORT_INVALID",
            message="FlowSpec 校验或兼容性检查未通过",
            status_code=422,
            details={
                "validation": pipeline.validation.model_dump(mode="json"),
                "compatibility": pipeline.compatibility.model_dump(mode="json"),
            },
        )
