from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.ai import REDACTED, AIInputError, sanitize_ai_input
from app.engine.contracts import AssertNodeConfig, NodeType, WorkflowDefinition
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet, AIJob, AISuggestion
from app.models.quality_intelligence import ReleaseRisk
from app.models.test_assets import TestCase
from app.models.workflows import Workflow
from app.repositories.ai_change_sets import AIChangeSetRepository
from app.repositories.impact import ImpactRepository
from app.schemas.ai_change_sets import (
    AIChangeSetCreate,
    AITestCaseDraftCreate,
    AITestCaseDraftUpdate,
    AIWorkflowDraftCreate,
    AIWorkflowDraftUpdate,
)
from app.schemas.test_assets import TestCaseDefinitionInput
from app.services.ai import AIJobDispatcher
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.test_assets import TestCaseService
from app.services.workflows import WorkflowService

logger = logging.getLogger(__name__)
PROMPT_TEMPLATE_VERSION = "s30-change-set-v1"
MAX_CHANGE_SET_ITEMS = 50
MAX_REVIEW_CONTENT_BYTES = 256 * 1024
_CONTROL_FIELDS = frozenset({"action", "target_id", "target_type"})
_MISSING_REDACTED_SOURCE = object()


@dataclass(frozen=True, slots=True)
class AssertionSemantics:
    node_id: str
    source_node_id: str
    expression: str
    operator: str
    expected: JsonValue
    bindings: tuple[tuple[str, str], ...]


class AIChangeSetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = AIChangeSetRepository(session)
        self._impacts = ImpactRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create(
        self,
        *,
        actor: User,
        payload: AIChangeSetCreate,
        dispatcher: AIJobDispatcher,
    ) -> AIChangeSet:
        _require_enabled()
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        impact = await self._impacts.get_run_bundle(payload.impact_run_id)
        risk = await self._repository.get_risk(payload.release_risk_id)
        if impact is None or impact.run.project_id != payload.project_id:
            raise AppError(code="IMPACT_RUN_NOT_FOUND", message="影响分析不存在", status_code=404)
        if (
            risk is None
            or risk.project_id != payload.project_id
            or risk.impact_run_id != payload.impact_run_id
        ):
            raise AppError(
                code="RELEASE_RISK_NOT_FOUND", message="发布风险快照不存在", status_code=404
            )
        metadata = await self._source_metadata(risk, impact.run.changes)
        try:
            sanitized = sanitize_ai_input(schema_document=None, metadata=metadata, sample=None)
        except AIInputError as error:
            raise AppError(code="AI_INPUT_INVALID", message=str(error), status_code=422) from error
        job = AIJob(
            project_id=payload.project_id,
            job_type="change_set",
            status="pending",
            sanitized_input=sanitized.payload,
            input_sha256=sanitized.sha256,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            model_name=settings.ai_model,
            sample_included=False,
            token_usage={},
            created_by_id=actor.id,
        )
        self._session.add(job)
        await self._session.flush()
        change_set = AIChangeSet(
            project_id=payload.project_id,
            impact_run_id=payload.impact_run_id,
            release_risk_id=payload.release_risk_id,
            ai_job_id=job.id,
            title=payload.title.strip(),
            status="generating",
            source_snapshot=sanitized.payload,
            source_fingerprint=sanitized.sha256,
            created_by_id=actor.id,
        )
        self._repository.add_change_set(change_set)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=payload.project_id,
            action="ai.change_set_created",
            resource_type="ai_change_set",
            resource_id=change_set.id,
            details={
                "ai_job_id": str(job.id),
                "impact_run_id": str(payload.impact_run_id),
                "release_risk_id": str(payload.release_risk_id),
                "source_fingerprint": sanitized.sha256,
                "redacted_paths": list(sanitized.redacted_paths),
            },
        )
        await self._session.commit()
        await self._session.refresh(change_set)
        try:
            dispatcher.start_ai_job(job.id)
        except Exception as error:
            logger.exception("AI change set dispatch failed", extra={"ai_job_id": str(job.id)})
            job.status = "failed"
            job.error_code = "AI_QUEUE_UNAVAILABLE"
            job.error_message = "AI 任务队列暂时不可用"
            job.completed_at = datetime.now(UTC)
            change_set.status = "failed"
            await self._session.commit()
            raise AppError(
                code="AI_QUEUE_UNAVAILABLE", message="AI 任务队列暂时不可用", status_code=503
            ) from error
        return change_set

    async def list_change_sets(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[AIChangeSet], int]:
        _require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_change_sets(
            project_id=project_id, offset=(page - 1) * page_size, limit=page_size
        )

    async def get(
        self, *, actor: User, change_set_id: UUID
    ) -> tuple[AIChangeSet, list[AIChangeItem]]:
        _require_enabled()
        change_set = await self._get_change_set(change_set_id)
        await self._projects.authorize(actor=actor, project_id=change_set.project_id, editing=False)
        return change_set, await self._repository.list_items(change_set.id)

    async def review_item(
        self,
        *,
        actor: User,
        change_set_id: UUID,
        item_id: UUID,
        accept: bool,
        edited_content: dict[str, JsonValue] | None,
        note: str,
    ) -> tuple[AIChangeSet, AIChangeItem]:
        _require_enabled()
        change_set = await self._repository.get_change_set_for_update(change_set_id)
        if change_set is None:
            raise AppError(
                code="AI_CHANGE_SET_NOT_FOUND", message="AI 变更集不存在", status_code=404
            )
        await self._projects.authorize(actor=actor, project_id=change_set.project_id, editing=True)
        item = await self._repository.get_item_for_update(item_id)
        if item is None or item.change_set_id != change_set_id:
            raise AppError(
                code="AI_CHANGE_ITEM_NOT_FOUND", message="AI 变更项不存在", status_code=404
            )
        if item.review_status != "pending":
            raise AppError(
                code="AI_CHANGE_ITEM_ALREADY_REVIEWED",
                message="AI 变更项已经完成审核",
                status_code=409,
            )
        if not accept and edited_content is not None:
            raise AppError(
                code="AI_REJECT_EDIT_FORBIDDEN", message="拒绝变更项时不能修改内容", status_code=422
            )
        content = _review_content(
            edited_content
            if edited_content is not None
            else cast(dict[str, JsonValue], item.proposed_content)
        )
        if accept:
            resource_type, resource_id = await self._materialize(
                actor=actor, change_set=change_set, item=item, content=content
            )
            item.materialized_resource_type = resource_type
            item.materialized_resource_id = resource_id
        item.proposed_content = content
        item.review_status = "accepted" if accept else "rejected"
        item.review_note = note.strip()
        item.reviewed_by_id = actor.id
        item.reviewed_at = datetime.now(UTC)
        suggestion = await self._session.get(AISuggestion, item.suggestion_id)
        if suggestion is not None:
            suggestion.review_status = item.review_status
            suggestion.review_note = item.review_note
            suggestion.reviewed_by_id = actor.id
            suggestion.reviewed_at = item.reviewed_at
            suggestion.accepted_resource_type = item.materialized_resource_type
            suggestion.accepted_resource_id = item.materialized_resource_id
        items = await self._repository.list_items(change_set.id)
        change_set.status = _review_status(items)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=change_set.project_id,
            action=f"ai.change_item_{item.review_status}",
            resource_type="ai_change_item",
            resource_id=item.id,
            details={
                "change_set_id": str(change_set.id),
                "item_type": item.item_type,
                "action": item.action,
                "materialized_resource_type": item.materialized_resource_type,
                "materialized_resource_id": (
                    str(item.materialized_resource_id) if item.materialized_resource_id else None
                ),
            },
        )
        await self._session.commit()
        await self._session.refresh(item)
        await self._session.refresh(change_set)
        return change_set, item

    async def _source_metadata(
        self, risk: ReleaseRisk, raw_changes: list[dict[str, Any]]
    ) -> dict[str, JsonValue]:
        failure_clusters = await self._repository.list_failure_clusters(
            risk.id, limit=MAX_CHANGE_SET_ITEMS
        )
        targets = []
        editable_recommendations = []
        target_keys: set[tuple[str, UUID]] = set()
        for recommended in risk.recommended_tests:
            target_type = recommended.get("target_type")
            target_id_value = recommended.get("target_id")
            if target_type not in {"test_case", "workflow"} or not isinstance(target_id_value, str):
                continue
            try:
                target_id = UUID(target_id_value)
            except ValueError:
                continue
            target_key = (target_type, target_id)
            if target_key in target_keys:
                continue
            target = await self._target_snapshot(target_type, target_id, risk.project_id)
            if target is not None:
                targets.append(target)
                editable_recommendations.append(recommended)
                target_keys.add(target_key)
                if len(targets) == MAX_CHANGE_SET_ITEMS:
                    break
        return {
            "task": "draft_change_set",
            "impact": {
                "run_id": str(risk.impact_run_id),
                "changes": cast(JsonValue, raw_changes[:200]),
            },
            "release_risk": {
                "id": str(risk.id),
                "score": risk.score,
                "risk_level": risk.risk_level,
                "factors": cast(JsonValue, risk.factors),
                "evidence": cast(JsonValue, risk.evidence_snapshot),
                "failure_clusters": cast(
                    JsonValue,
                    [
                        {
                            "fingerprint": cluster.fingerprint,
                            "title": cluster.title,
                            "failure_category": cluster.failure_category,
                            "error_code": cluster.error_code,
                            "node_type": cluster.node_type,
                            "occurrence_count": cluster.occurrence_count,
                            "baseline_count": cluster.baseline_count,
                            "affected_workflow_ids": cluster.affected_workflow_ids,
                            "affected_workflow_names": cluster.affected_workflow_names,
                            "confidence": cluster.confidence,
                            "regression_percent": cluster.regression_percent,
                            "recommendation": cluster.recommendation,
                        }
                        for cluster in failure_clusters
                    ],
                ),
                "recommended_tests": cast(JsonValue, editable_recommendations),
            },
            "allowed_targets": cast(JsonValue, targets),
            "review_policy": {
                "draft_only": True,
                "automatic_publish": False,
                "automatic_execute": False,
                "max_items": MAX_CHANGE_SET_ITEMS,
            },
        }

    async def _target_snapshot(
        self, target_type: str, target_id: UUID, project_id: UUID
    ) -> dict[str, JsonValue] | None:
        if target_type == "test_case":
            target = await self._repository.get_test_case(target_id)
            if target is None or target.project_id != project_id:
                return None
            return {
                "target_type": "test_case",
                "target_id": str(target.id),
                "name": target.name,
                "description": target.description,
                "tags": cast(JsonValue, target.tags),
                "current_version": target.current_version,
                "draft_definition": _target_definition_for_ai("test_case", target.draft_definition),
                "snapshot_sha256": _target_hash(target),
            }
        workflow = await self._repository.get_workflow(target_id)
        if workflow is None or workflow.project_id != project_id:
            return None
        return {
            "target_type": "workflow",
            "target_id": str(workflow.id),
            "name": workflow.name,
            "description": workflow.description,
            "current_version": workflow.current_version,
            "draft_revision": workflow.draft_revision,
            "draft_definition": _target_definition_for_ai("workflow", workflow.draft_definition),
            "snapshot_sha256": _target_hash(workflow),
        }

    async def _materialize(
        self,
        *,
        actor: User,
        change_set: AIChangeSet,
        item: AIChangeItem,
        content: dict[str, JsonValue],
    ) -> tuple[str, UUID]:
        if item.action == "create":
            if item.item_type == "test_case":
                created_case = await _create_test_case(
                    self._session, actor, change_set.project_id, item.title, content
                )
                return "test_case", created_case.id
            if item.item_type == "workflow":
                created_workflow = await _create_workflow(
                    self._session, actor, change_set.project_id, item.title, content
                )
                return "workflow", created_workflow.id
            raise AppError(
                code="AI_CHANGE_ITEM_INVALID",
                message="Assertion 只能修改现有 Workflow 草稿",
                status_code=422,
            )
        if item.target_resource_id is None:
            raise AppError(
                code="AI_CHANGE_ITEM_INVALID", message="更新项缺少目标资产", status_code=422
            )
        if item.item_type == "test_case":
            test_case = await self._repository.get_test_case_for_update(item.target_resource_id)
            _ensure_target(test_case, change_set.project_id, item.target_snapshot_sha256)
            if test_case is None:
                raise RuntimeError("validated test case target is missing")
            updated_case = await _update_test_case(self._session, actor, test_case, content)
            return "test_case", updated_case.id
        workflow = await self._repository.get_workflow_for_update(item.target_resource_id)
        _ensure_target(workflow, change_set.project_id, item.target_snapshot_sha256)
        if workflow is None:
            raise RuntimeError("validated workflow target is missing")
        updated_workflow = await _update_workflow(
            self._session,
            actor,
            workflow,
            content,
            require_assertion_change=item.item_type == "assertion",
        )
        return "workflow", updated_workflow.id

    async def _get_change_set(self, change_set_id: UUID) -> AIChangeSet:
        change_set = await self._repository.get_change_set(change_set_id)
        if change_set is None:
            raise AppError(
                code="AI_CHANGE_SET_NOT_FOUND", message="AI 变更集不存在", status_code=404
            )
        return change_set


async def materialize_change_set_items(
    session: AsyncSession, job: AIJob, suggestions: list[AISuggestion]
) -> None:
    repository = AIChangeSetRepository(session)
    change_set = await repository.get_change_set_by_job_for_update(job.id)
    if change_set is None:
        raise ValueError("change set is missing for AI job")
    if len(suggestions) > MAX_CHANGE_SET_ITEMS:
        raise ValueError("change set contains too many items")
    allowed_targets = _allowed_targets(change_set)
    items = []
    update_targets: set[tuple[str, UUID]] = set()
    for suggestion in suggestions:
        content = cast(dict[str, JsonValue], suggestion.content)
        action = content.get("action")
        if action not in {"create", "update"}:
            raise ValueError("change item action is invalid")
        item_type = suggestion.suggestion_type
        if item_type not in {"test_case", "workflow", "assertion"}:
            raise ValueError("change item type is invalid")
        target_id = _change_target_id(content.get("target_id"))
        expected_type = "workflow" if item_type == "assertion" else item_type
        if action == "create" and (target_id is not None or item_type == "assertion"):
            raise ValueError("create change item target is invalid")
        target_key = (expected_type, target_id) if target_id is not None else None
        if action == "update" and (target_key is None or target_key not in allowed_targets):
            raise ValueError("update target is not an allowed impacted asset")
        if action == "update" and target_key in update_targets:
            raise ValueError("change set contains duplicate update targets")
        if action == "update" and target_key is not None:
            update_targets.add(target_key)
        target_hash = allowed_targets[target_key] if target_key is not None else None
        proposal = {key: value for key, value in content.items() if key not in _CONTROL_FIELDS}
        items.append(
            AIChangeItem(
                change_set_id=change_set.id,
                suggestion_id=suggestion.id,
                position=suggestion.position,
                item_type=item_type,
                action=action,
                title=suggestion.title,
                target_resource_id=target_id,
                target_snapshot_sha256=target_hash,
                proposed_content=proposal,
                review_status="pending",
            )
        )
    repository.add_items(items)
    change_set.status = "draft"


async def mark_change_set_failed(session: AsyncSession, job_id: UUID) -> None:
    change_set = await AIChangeSetRepository(session).get_change_set_by_job_for_update(job_id)
    if change_set is not None:
        change_set.status = "failed"


def _require_enabled() -> None:
    if not settings.feature_quality_intelligence_enabled:
        raise AppError(
            code="QUALITY_INTELLIGENCE_DISABLED", message="质量智能未启用", status_code=503
        )
    if not settings.feature_ai_enabled:
        raise AppError(code="AI_DISABLED", message="AI 助手未启用", status_code=503)


def _allowed_targets(change_set: AIChangeSet) -> dict[tuple[str, UUID], str]:
    metadata = change_set.source_snapshot.get("metadata")
    raw_targets = metadata.get("allowed_targets") if isinstance(metadata, dict) else None
    allowed: dict[tuple[str, UUID], str] = {}
    if not isinstance(raw_targets, list):
        return allowed
    for target in raw_targets:
        if not isinstance(target, dict):
            continue
        target_type = target.get("target_type")
        target_id = _change_target_id(target.get("target_id"))
        snapshot_sha256 = target.get("snapshot_sha256")
        if (
            target_type in {"test_case", "workflow"}
            and target_id is not None
            and isinstance(snapshot_sha256, str)
            and len(snapshot_sha256) == 64
        ):
            allowed[(target_type, target_id)] = snapshot_sha256
    return allowed


def _change_target_id(value: JsonValue | None) -> UUID | None:
    if value in {None, ""}:
        return None
    try:
        return UUID(str(value))
    except ValueError as error:
        raise ValueError("change item target id is invalid") from error


def _target_hash(target: TestCase | Workflow) -> str:
    if isinstance(target, TestCase):
        payload: dict[str, JsonValue] = {
            "id": str(target.id),
            "updated_at": target.updated_at.isoformat(),
            "definition": target.draft_definition,
        }
    else:
        payload = {
            "id": str(target.id),
            "draft_revision": target.draft_revision,
            "definition": target.draft_definition,
        }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _target_definition_for_ai(
    target_type: Literal["test_case", "workflow"], definition: dict[str, Any]
) -> dict[str, JsonValue]:
    safe_definition = cast(dict[str, JsonValue], dict(definition))
    if target_type == "test_case":
        for field in ("runtime_variables", "runtime_headers"):
            _redact_runtime_map(safe_definition, field)
        return safe_definition
    _redact_runtime_map(safe_definition, "variables")
    nodes = safe_definition.get("nodes")
    if isinstance(nodes, list):
        safe_definition["nodes"] = [_workflow_node_for_ai(node) for node in nodes]
    return safe_definition


def _redact_runtime_map(container: dict[str, JsonValue], field: str) -> None:
    values = container.get(field)
    if isinstance(values, dict):
        container[field] = {str(key): REDACTED for key in values}
    elif field in container:
        container[field] = REDACTED


def _workflow_node_for_ai(node: JsonValue) -> JsonValue:
    if not isinstance(node, dict):
        return node
    safe_node = cast(dict[str, JsonValue], dict(node))
    for field in ("config", "configuration"):
        if field in safe_node:
            safe_node[field] = _redact_runtime_structure(safe_node[field])
    return safe_node


def _redact_runtime_structure(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {str(key): _redact_runtime_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_runtime_structure(item) for item in value]
    return REDACTED


def _rehydrate_test_case_definition(
    definition: TestCaseDefinitionInput | None, current_definition: dict[str, Any]
) -> TestCaseDefinitionInput | None:
    if definition is None:
        return None
    proposed = cast(dict[str, JsonValue], definition.model_dump(mode="json", exclude_none=True))
    try:
        current = cast(
            dict[str, JsonValue],
            TestCaseDefinitionInput.model_validate(current_definition).model_dump(
                mode="json", exclude_none=True
            ),
        )
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_TEST_CASE_DRAFT_INVALID",
            message="现有 Test Case 草稿格式无效",
            status_code=409,
        ) from error
    for field in ("runtime_variables", "runtime_headers"):
        proposed[field] = (
            _restore_redacted_value(proposed[field], current[field])
            if field in definition.model_fields_set
            else current[field]
        )
    return TestCaseDefinitionInput.model_validate(proposed)


def _rehydrate_workflow_definition(
    definition: WorkflowDefinition | None, current_definition: dict[str, Any]
) -> WorkflowDefinition | None:
    if definition is None:
        return None
    proposed = cast(dict[str, JsonValue], definition.model_dump(mode="json", exclude_none=True))
    try:
        current = cast(
            dict[str, JsonValue],
            WorkflowDefinition.model_validate(current_definition).model_dump(
                mode="json", exclude_none=True
            ),
        )
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_WORKFLOW_DRAFT_INVALID",
            message="现有 Workflow 草稿格式无效",
            status_code=409,
        ) from error
    proposed["variables"] = (
        _restore_redacted_value(proposed.get("variables", {}), current.get("variables", {}))
        if "variables" in definition.model_fields_set
        else current.get("variables", {})
    )
    current_nodes = {
        str(node.get("id")): node
        for node in cast(list[dict[str, JsonValue]], current.get("nodes", []))
    }
    proposed_nodes = cast(list[dict[str, JsonValue]], proposed.get("nodes", []))
    model_nodes = {node.id: node for node in definition.nodes}
    for node in proposed_nodes:
        current_node = current_nodes.get(str(node.get("id")), {})
        model_node = model_nodes.get(str(node.get("id")))
        for field in ("config", "configuration"):
            if model_node is not None and field not in model_node.model_fields_set:
                if field in current_node:
                    node[field] = current_node[field]
            elif field in node:
                node[field] = _restore_redacted_value(
                    node[field], current_node.get(field, _MISSING_REDACTED_SOURCE)
                )
    return WorkflowDefinition.model_validate(proposed)


def _restore_redacted_value(
    proposed: JsonValue, current: JsonValue | object = _MISSING_REDACTED_SOURCE
) -> JsonValue:
    if proposed == REDACTED:
        if current is _MISSING_REDACTED_SOURCE:
            raise AppError(
                code="AI_REDACTED_VALUE_INVALID",
                message="AI 草稿包含无法从当前目标恢复的脱敏值",
                status_code=422,
            )
        return cast(JsonValue, current)
    if isinstance(proposed, dict):
        current_mapping = current if isinstance(current, dict) else {}
        return {
            str(key): _restore_redacted_value(
                value, current_mapping.get(str(key), _MISSING_REDACTED_SOURCE)
            )
            for key, value in proposed.items()
        }
    if isinstance(proposed, list):
        current_items = current if isinstance(current, list) else []
        return [
            _restore_redacted_value(
                value,
                current_items[index] if index < len(current_items) else _MISSING_REDACTED_SOURCE,
            )
            for index, value in enumerate(proposed)
        ]
    return proposed


def _ensure_target(
    target: TestCase | Workflow | None, project_id: UUID, expected_hash: str | None
) -> None:
    if target is None or target.project_id != project_id:
        raise AppError(
            code="AI_CHANGE_TARGET_NOT_FOUND", message="AI 变更目标不存在", status_code=404
        )
    if expected_hash is None or _target_hash(target) != expected_hash:
        raise AppError(
            code="AI_CHANGE_TARGET_CONFLICT",
            message="目标草稿已变化。请重新生成 AI 变更集",
            status_code=409,
        )


def _review_content(content: dict[str, JsonValue]) -> dict[str, JsonValue]:
    encoded = json.dumps(content, ensure_ascii=False).encode()
    if len(encoded) > MAX_REVIEW_CONTENT_BYTES:
        raise AppError(code="AI_REVIEW_TOO_LARGE", message="审核内容超过 256 KB", status_code=422)
    try:
        sanitized = sanitize_ai_input(
            schema_document=None, metadata={"content": content}, sample=None
        ).payload["metadata"]
    except AIInputError as error:
        raise AppError(code="AI_REVIEW_INVALID", message=str(error), status_code=422) from error
    if not isinstance(sanitized, dict) or not isinstance(sanitized.get("content"), dict):
        raise AppError(code="AI_REVIEW_INVALID", message="审核内容格式无效", status_code=422)
    return cast(dict[str, JsonValue], sanitized["content"])


async def _create_test_case(
    session: AsyncSession,
    actor: User,
    project_id: UUID,
    title: str,
    content: dict[str, JsonValue],
) -> TestCase:
    create = _test_case_create(title, content)
    return await TestCaseService(session).create(
        actor=actor,
        project_id=project_id,
        name=create.name,
        description=create.description,
        folder_id=None,
        tags=create.tags,
        is_template=False,
        definition=create.definition,
        commit=False,
    )


async def _update_test_case(
    session: AsyncSession, actor: User, target: TestCase, content: dict[str, JsonValue]
) -> TestCase:
    update = _test_case_update(content)
    definition = _rehydrate_test_case_definition(update.definition, target.draft_definition)
    return await TestCaseService(session).update(
        actor=actor,
        project_id=target.project_id,
        case_id=target.id,
        name=update.name,
        description=update.description,
        folder_id=None,
        change_folder=False,
        tags=update.tags,
        is_template=None,
        definition=definition,
        commit=False,
    )


async def _create_workflow(
    session: AsyncSession,
    actor: User,
    project_id: UUID,
    title: str,
    content: dict[str, JsonValue],
) -> Workflow:
    create = _workflow_create(title, content)
    return await WorkflowService(session).create(
        actor=actor,
        project_id=project_id,
        name=create.name,
        description=create.description,
        folder_id=None,
        definition=create.definition,
        commit=False,
    )


async def _update_workflow(
    session: AsyncSession,
    actor: User,
    target: Workflow,
    content: dict[str, JsonValue],
    *,
    require_assertion_change: bool = False,
) -> Workflow:
    if require_assertion_change and content.get("definition") is None:
        raise AppError(
            code="AI_ASSERTION_DRAFT_INVALID",
            message="AI Assertion 变更必须提供包含断言节点的完整 Workflow 草稿",
            status_code=422,
        )
    update = _workflow_update(content)
    definition = _rehydrate_workflow_definition(update.definition, target.draft_definition)
    if require_assertion_change:
        _validate_assertion_workflow_change(target, definition)
    return await WorkflowService(session).update_draft(
        actor=actor,
        project_id=target.project_id,
        workflow_id=target.id,
        expected_revision=target.draft_revision,
        name=update.name,
        description=update.description,
        folder_id=None,
        change_folder=False,
        definition=definition,
        commit=False,
    )


def _validate_assertion_workflow_change(
    target: Workflow, definition: WorkflowDefinition | None
) -> None:
    try:
        proposed_assertions = _assertion_semantics(definition) if definition is not None else []
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_ASSERTION_DRAFT_INVALID",
            message="AI Assertion 变更包含无效的断言配置",
            status_code=422,
        ) from error
    if not proposed_assertions:
        raise AppError(
            code="AI_ASSERTION_DRAFT_INVALID",
            message="AI Assertion 变更必须提供包含断言节点的完整 Workflow 草稿",
            status_code=422,
        )
    try:
        current = WorkflowDefinition.model_validate(target.draft_definition)
        current_assertions = _assertion_semantics(current)
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_WORKFLOW_DRAFT_INVALID",
            message="现有 Workflow 草稿格式无效",
            status_code=409,
        ) from error
    if proposed_assertions == current_assertions:
        raise AppError(
            code="AI_ASSERTION_DRAFT_INVALID",
            message="AI Assertion 变更必须实际修改断言节点",
            status_code=422,
        )


def _assertion_semantics(definition: WorkflowDefinition) -> list[AssertionSemantics]:
    assertions = []
    for node in definition.nodes:
        if node.effective_type is not NodeType.ASSERT:
            continue
        config = AssertNodeConfig.model_validate(node.effective_config)
        assertions.append(
            AssertionSemantics(
                node_id=node.id,
                source_node_id=config.source_node_id,
                expression=config.expression,
                operator=config.operator.value,
                expected=config.expected,
                bindings=tuple(
                    sorted((binding.input, binding.expression) for binding in node.bindings or [])
                ),
            )
        )
    return sorted(assertions, key=lambda assertion: assertion.node_id)


def _test_case_create(title: str, content: dict[str, JsonValue]) -> AITestCaseDraftCreate:
    try:
        return AITestCaseDraftCreate.model_validate(
            {
                "name": title,
                "description": "由 AI Change Set 生成。待人工复核",
                "tags": [],
                **content,
            }
        )
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_TEST_CASE_DRAFT_INVALID",
            message="AI Test Case 创建内容必须符合受支持的草稿字段",
            status_code=422,
        ) from error


def _workflow_create(title: str, content: dict[str, JsonValue]) -> AIWorkflowDraftCreate:
    try:
        return AIWorkflowDraftCreate.model_validate(
            {
                "name": title,
                "description": "由 AI Change Set 生成。待人工复核",
                **content,
            }
        )
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_WORKFLOW_DRAFT_INVALID",
            message="AI Workflow 创建内容必须符合受支持的草稿字段",
            status_code=422,
        ) from error


def _test_case_update(content: dict[str, JsonValue]) -> AITestCaseDraftUpdate:
    try:
        update = AITestCaseDraftUpdate.model_validate(content)
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_TEST_CASE_DRAFT_INVALID",
            message="AI Test Case 更新必须符合受支持的草稿字段",
            status_code=422,
        ) from error
    if not any(
        value is not None
        for value in (update.name, update.description, update.tags, update.definition)
    ):
        raise AppError(
            code="AI_TEST_CASE_DRAFT_INVALID",
            message="AI Test Case 更新必须至少修改一个草稿字段",
            status_code=422,
        )
    return update


def _workflow_update(content: dict[str, JsonValue]) -> AIWorkflowDraftUpdate:
    try:
        update = AIWorkflowDraftUpdate.model_validate(content)
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_WORKFLOW_DRAFT_INVALID",
            message="AI Workflow 更新必须符合受支持的草稿字段",
            status_code=422,
        ) from error
    if not any(value is not None for value in (update.name, update.description, update.definition)):
        raise AppError(
            code="AI_WORKFLOW_DRAFT_INVALID",
            message="AI Workflow 更新必须至少修改一个草稿字段",
            status_code=422,
        )
    return update


def _review_status(items: list[AIChangeItem]) -> str:
    accepted = sum(item.review_status == "accepted" for item in items)
    rejected = sum(item.review_status == "rejected" for item in items)
    pending = len(items) - accepted - rejected
    if pending:
        return "partially_reviewed" if accepted or rejected else "draft"
    return "accepted" if accepted else "rejected"
