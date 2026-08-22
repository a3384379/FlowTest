from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.flow_spec import (
    FlowSpec,
    FlowSpecCompatibilityResult,
    FlowSpecDiffItem,
    FlowSpecValidationResult,
    assess_flow_spec_compatibility,
    diff_flow_specs,
    flow_spec_fingerprint,
    flow_spec_to_workflow_definition,
    normalize_flow_spec,
    validate_flow_spec,
    workflow_definition_to_flow_spec,
)
from app.engine.contracts import WorkflowDefinition
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.workflows import Workflow
from app.repositories.workflows import WorkflowRepository
from app.schemas.flow_spec import FlowSpecImportRequest
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.workflows import WorkflowService


@dataclass(frozen=True, slots=True)
class FlowSpecPipeline:
    spec: FlowSpec
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


class FlowSpecService:
    """Application service for portable FlowSpec parsing and reviewed imports."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._workflows = WorkflowRepository(session)
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
            workflow_definition_to_flow_spec(
                definition,
                project_id=project_id,
                name=workflow.name,
                description=workflow.description,
                source_evidence=evidence,
            )
        )
        _require_pipeline_exportable(pipeline)
        return FlowSpecExport(workflow=workflow, version=version, pipeline=pipeline)

    async def validate(self, *, actor: User, project_id: UUID, spec: FlowSpec) -> FlowSpecPipeline:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        pipeline = self._pipeline(spec)
        return pipeline

    async def diff(
        self,
        *,
        actor: User,
        project_id: UUID,
        before: FlowSpec | None,
        after: FlowSpec,
    ) -> FlowSpecDiff:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        after_pipeline = self._pipeline(after)
        before_pipeline = self._pipeline(before) if before is not None else None
        return FlowSpecDiff(
            before_fingerprint=(
                before_pipeline.fingerprint if before_pipeline is not None else None
            ),
            after_fingerprint=after_pipeline.fingerprint,
            changes=diff_flow_specs(
                before_pipeline.spec if before_pipeline is not None else None,
                after_pipeline.spec,
            ),
        )

    async def create_import(
        self, *, actor: User, project_id: UUID, payload: FlowSpecImportRequest
    ) -> FlowSpecChangeSetView:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        pipeline = self._pipeline(payload.spec)
        _require_pipeline_importable(pipeline)
        target = await self._target_workflow(project_id, payload.workflow_id)
        target_snapshot = None
        target_revision = None
        before: FlowSpec | None = None
        if target is not None:
            target_revision = target.draft_revision
            before = self._target_spec(project_id, target)
            target_snapshot = flow_spec_fingerprint(before)
        snapshot = _source_snapshot(
            pipeline=pipeline,
            target_workflow_id=target.id if target is not None else None,
            target_revision=target_revision,
            target_spec=before,
        )
        change_set = AIChangeSet(
            project_id=project_id,
            impact_run_id=None,
            release_risk_id=None,
            ai_job_id=None,
            title=pipeline.spec.name,
            status="draft",
            source_snapshot=snapshot,
            source_fingerprint=pipeline.fingerprint,
            source_type="flow_spec",
            source_ref=payload.source_ref or f"flow-spec://{pipeline.fingerprint}",
            actor_type="user",
            actor_id=actor.id,
            created_by_id=actor.id,
        )
        self._session.add(change_set)
        await self._session.flush()
        item = AIChangeItem(
            change_set_id=change_set.id,
            suggestion_id=None,
            position=0,
            item_type="workflow",
            action="update" if target is not None else "create",
            title=pipeline.spec.name,
            target_resource_id=target.id if target is not None else None,
            target_snapshot_sha256=target_snapshot,
            proposed_content={"flow_spec": cast(dict[str, Any], _spec_json(pipeline.spec))},
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
                "source_fingerprint": pipeline.fingerprint,
                "target_workflow_id": str(target.id) if target is not None else None,
                "requires_review": pipeline.compatibility.requires_review,
            },
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        await self._session.refresh(item)
        return self._view(change_set, item, before=before)

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
        target_id = item.target_resource_id
        workflow: Workflow
        if target_id is None:
            workflow = await WorkflowService(self._session).create(
                actor=actor,
                project_id=project_id,
                name=pipeline.spec.name,
                description=pipeline.spec.description,
                folder_id=None,
                definition=flow_spec_to_workflow_definition(pipeline.spec),
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
                definition=flow_spec_to_workflow_definition(pipeline.spec),
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

    def _pipeline(self, spec: FlowSpec) -> FlowSpecPipeline:
        try:
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
            diff=diff_flow_specs(before, pipeline.spec),
        )

    def _target_spec(self, project_id: UUID, workflow: Workflow) -> FlowSpec:
        return workflow_definition_to_flow_spec(
            _load_definition(workflow.draft_definition),
            project_id=project_id,
            name=workflow.name,
            description=workflow.description,
            source_evidence=[f"workflow://{workflow.id}/draft/{workflow.draft_revision}"],
        )


def _load_definition(value: dict[str, Any]) -> WorkflowDefinition:
    try:
        return WorkflowDefinition.model_validate(value)
    except (TypeError, ValueError, ValidationError) as error:
        raise AppError(
            code="INVALID_WORKFLOW_DEFINITION",
            message="工作流定义无效,无法导出 FlowSpec",
            status_code=422,
        ) from error


def _source_snapshot(
    *,
    pipeline: FlowSpecPipeline,
    target_workflow_id: UUID | None,
    target_revision: int | None,
    target_spec: FlowSpec | None,
) -> dict[str, Any]:
    return {
        "flow_spec": _spec_json(pipeline.spec),
        "validation": pipeline.validation.model_dump(mode="json"),
        "compatibility": pipeline.compatibility.model_dump(mode="json"),
        "target_workflow_id": str(target_workflow_id) if target_workflow_id is not None else None,
        "target_revision": target_revision,
        "target_spec": _spec_json(target_spec) if target_spec is not None else None,
    }


def _spec_json(spec: FlowSpec) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], spec.model_dump(mode="json", by_alias=True))


def _spec_from_item(item: AIChangeItem) -> FlowSpec:
    raw = item.proposed_content.get("flow_spec")
    if not isinstance(raw, dict):
        raise AppError(
            code="FLOWSPEC_CHANGE_SET_INVALID",
            message="FlowSpec 变更项内容无效",
            status_code=409,
        )
    try:
        return FlowSpec.model_validate(raw)
    except (TypeError, ValueError, ValidationError) as error:
        raise AppError(
            code="FLOWSPEC_CHANGE_SET_INVALID",
            message="FlowSpec 变更项内容无法解析",
            status_code=409,
        ) from error


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
