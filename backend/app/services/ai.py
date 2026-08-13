from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.access import ProjectCapability, ProjectRole
from app.domain.ai import (
    AIInputError,
    sanitize_ai_input,
    suggestion_output_schema,
)
from app.engine.contracts import WorkflowDefinition
from app.models.access import User
from app.models.ai import AIJob, AISuggestion
from app.models.test_assets import TestCase
from app.models.workflows import Workflow
from app.repositories.ai import AIRepository
from app.schemas.ai import AIJobCreateRequest
from app.schemas.ai_change_sets import change_set_output_schema, decode_change_set_content
from app.schemas.test_assets import TestCaseDefinitionInput
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.test_assets import TestCaseService
from app.services.workflows import WorkflowService

logger = logging.getLogger(__name__)
PROMPT_TEMPLATE_VERSION = "s21-v1"
MAX_REVIEW_CONTENT_BYTES = 256 * 1024
_ALLOWED_SUGGESTIONS = {
    "schema_cases": frozenset({"test_case", "assertion"}),
    "assertion_suggestions": frozenset({"assertion"}),
    "workflow_draft": frozenset({"workflow"}),
    "failure_analysis": frozenset({"failure_analysis"}),
    "change_set": frozenset({"test_case", "assertion", "workflow"}),
}


class AIJobDispatcher(Protocol):
    def start_ai_job(self, job_id: UUID) -> None: ...


class AIProvider(Protocol):
    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult: ...


class AIProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AIProviderResult:
    payload: dict[str, JsonValue]
    token_usage: dict[str, int]


class AIJobService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = AIRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def status(self, *, actor: User, project_id: UUID) -> tuple[bool, str | None, bool]:
        access = await self._projects.authorize(actor=actor, project_id=project_id)
        model = settings.ai_model if settings.feature_ai_enabled else None
        return settings.feature_ai_enabled, model, access.project.ai_sample_sharing_enabled

    async def update_sample_sharing(self, *, actor: User, project_id: UUID, enabled: bool) -> bool:
        access = await self._projects.authorize(
            actor=actor,
            project_id=project_id,
            capability=ProjectCapability.MANAGE_SECURITY,
        )
        access.project.ai_sample_sharing_enabled = enabled
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="ai.sample_sharing_updated",
            resource_type="project",
            resource_id=project_id,
            details={"enabled": enabled},
        )
        await self._session.commit()
        return enabled

    async def create(
        self,
        *,
        actor: User,
        payload: AIJobCreateRequest,
        dispatcher: AIJobDispatcher,
    ) -> AIJob:
        _require_ai_enabled()
        access = await self._projects.authorize(
            actor=actor, project_id=payload.project_id, editing=True
        )
        _authorize_sample(access.role, access.project.ai_sample_sharing_enabled, payload.sample)
        try:
            sanitized = sanitize_ai_input(
                schema_document=payload.schema_document,
                metadata=payload.metadata,
                sample=payload.sample,
            )
        except AIInputError as error:
            raise AppError(code="AI_INPUT_INVALID", message=str(error), status_code=422) from error
        job = AIJob(
            project_id=payload.project_id,
            job_type=payload.job_type,
            status="pending",
            sanitized_input=sanitized.payload,
            input_sha256=sanitized.sha256,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            model_name=settings.ai_model,
            sample_included=sanitized.sample_included,
            token_usage={},
            created_by_id=actor.id,
        )
        self._repository.add_job(job)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=payload.project_id,
            action="ai.job_created",
            resource_type="ai_job",
            resource_id=job.id,
            details={
                "job_type": job.job_type,
                "input_sha256": job.input_sha256,
                "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                "model": job.model_name,
                "sample_included": job.sample_included,
                "redacted_paths": list(sanitized.redacted_paths),
            },
        )
        await self._session.commit()
        await self._session.refresh(job)
        await self._dispatch(job, dispatcher)
        return job

    async def list_jobs(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[AIJob], int]:
        await self._projects.authorize(actor=actor, project_id=project_id)
        return await self._repository.list_jobs(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get_job(self, *, actor: User, job_id: UUID) -> AIJob:
        job = await self._get_job(job_id)
        await self._projects.authorize(actor=actor, project_id=job.project_id)
        return job

    async def list_suggestions(self, *, actor: User, job_id: UUID) -> list[AISuggestion]:
        job = await self.get_job(actor=actor, job_id=job_id)
        if job.status != "completed":
            return []
        return await self._repository.list_suggestions(job.id)

    async def review(
        self,
        *,
        actor: User,
        suggestion_id: UUID,
        accept: bool,
        edited_content: dict[str, JsonValue] | None,
        note: str,
    ) -> AISuggestion:
        suggestion = await self._repository.get_suggestion_for_update(suggestion_id)
        if suggestion is None:
            raise AppError(code="AI_SUGGESTION_NOT_FOUND", message="AI 建议不存在", status_code=404)
        job = await self._get_job(suggestion.job_id)
        await self._projects.authorize(actor=actor, project_id=job.project_id, editing=True)
        _validate_pending_suggestion(suggestion, job)
        if not accept and edited_content is not None:
            raise AppError(
                code="AI_REJECT_EDIT_FORBIDDEN", message="拒绝建议时不能修改内容", status_code=422
            )
        content = _review_content(edited_content or cast(dict[str, JsonValue], suggestion.content))
        suggestion.content = content
        suggestion.review_status = "accepted" if accept else "rejected"
        suggestion.review_note = note.strip()
        suggestion.reviewed_by_id = actor.id
        suggestion.reviewed_at = datetime.now(UTC)
        if accept:
            await self._materialize(actor=actor, project_id=job.project_id, suggestion=suggestion)
        await self._record_review(actor=actor, project_id=job.project_id, suggestion=suggestion)
        return suggestion

    async def _dispatch(self, job: AIJob, dispatcher: AIJobDispatcher) -> None:
        try:
            dispatcher.start_ai_job(job.id)
        except Exception as error:
            logger.exception("AI job dispatch failed", extra={"ai_job_id": str(job.id)})
            job.status = "failed"
            job.error_code = "AI_QUEUE_UNAVAILABLE"
            job.error_message = "AI 任务队列暂时不可用"
            job.completed_at = datetime.now(UTC)
            await self._session.commit()
            raise AppError(
                code="AI_QUEUE_UNAVAILABLE", message="AI 任务队列暂时不可用", status_code=503
            ) from error

    async def _materialize(
        self, *, actor: User, project_id: UUID, suggestion: AISuggestion
    ) -> None:
        if suggestion.suggestion_type == "workflow":
            workflow = await _create_workflow_draft(
                session=self._session,
                actor=actor,
                project_id=project_id,
                title=suggestion.title,
                content=cast(dict[str, JsonValue], suggestion.content),
            )
            suggestion.accepted_resource_type = "workflow"
            suggestion.accepted_resource_id = workflow.id
        elif suggestion.suggestion_type == "test_case":
            test_case = await _create_test_case_draft(
                session=self._session,
                actor=actor,
                project_id=project_id,
                title=suggestion.title,
                content=cast(dict[str, JsonValue], suggestion.content),
            )
            suggestion.accepted_resource_type = "test_case"
            suggestion.accepted_resource_id = test_case.id

    async def _record_review(
        self, *, actor: User, project_id: UUID, suggestion: AISuggestion
    ) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action=f"ai.suggestion_{suggestion.review_status}",
            resource_type="ai_suggestion",
            resource_id=suggestion.id,
            details={
                "suggestion_type": suggestion.suggestion_type,
                "accepted_resource_type": suggestion.accepted_resource_type,
                "accepted_resource_id": (
                    str(suggestion.accepted_resource_id)
                    if suggestion.accepted_resource_id
                    else None
                ),
            },
        )
        await self._session.commit()
        await self._session.refresh(suggestion)

    async def _get_job(self, job_id: UUID) -> AIJob:
        job = await self._repository.get_job(job_id)
        if job is None:
            raise AppError(code="AI_JOB_NOT_FOUND", message="AI 任务不存在", status_code=404)
        return job


class AIJobRunner:
    def __init__(self, session: AsyncSession, provider: AIProvider) -> None:
        self._session = session
        self._provider = provider
        self._repository = AIRepository(session)
        self._audit = AuditService(session)

    async def run(self, job_id: UUID) -> AIJob:
        job = await self._repository.get_job_for_update(job_id)
        if job is None:
            raise AppError(code="AI_JOB_NOT_FOUND", message="AI 任务不存在", status_code=404)
        if job.status != "pending":
            return job
        job.status = "running"
        job.started_at = datetime.now(UTC)
        await self._session.commit()
        try:
            result = await self._provider.generate(
                job_type=job.job_type,
                sanitized_input=cast(dict[str, JsonValue], job.sanitized_input),
                output_schema=_output_schema(job.job_type),
            )
            suggestions = _validated_suggestions(job, result.payload)
            if job.job_type == "change_set":
                from app.services.ai_change_sets import materialize_change_set_items

                self._repository.add_suggestions(suggestions)
                await self._session.flush()
                await materialize_change_set_items(self._session, job, suggestions)
        except AIProviderError as error:
            return await self._fail(job, code=error.code, message=error.message)
        except (SchemaError, ValidationError, AIInputError, ValueError, TypeError):
            logger.info("AI response validation failed", extra={"ai_job_id": str(job.id)})
            return await self._fail(
                job, code="AI_RESPONSE_INVALID", message="AI 建议未通过结构或脱敏校验"
            )
        if job.job_type != "change_set":
            self._repository.add_suggestions(suggestions)
        job.status = "completed"
        job.token_usage = result.token_usage
        job.completed_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=job.created_by_id,
            project_id=job.project_id,
            action="ai.job_completed",
            resource_type="ai_job",
            resource_id=job.id,
            details={
                "model": job.model_name,
                "prompt_template_version": job.prompt_template_version,
                "input_sha256": job.input_sha256,
                "token_usage": result.token_usage,
                "suggestion_count": len(suggestions),
            },
        )
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def _fail(self, job: AIJob, *, code: str, message: str) -> AIJob:
        job.status = "failed"
        job.error_code = code
        job.error_message = message[:500]
        job.completed_at = datetime.now(UTC)
        if job.job_type == "change_set":
            from app.services.ai_change_sets import mark_change_set_failed

            await mark_change_set_failed(self._session, job.id)
        self._audit.record(
            actor_user_id=job.created_by_id,
            project_id=job.project_id,
            action="ai.job_failed",
            resource_type="ai_job",
            resource_id=job.id,
            details={"error_code": code, "input_sha256": job.input_sha256},
        )
        await self._session.commit()
        await self._session.refresh(job)
        return job


def _require_ai_enabled() -> None:
    if not settings.feature_ai_enabled:
        raise AppError(code="AI_DISABLED", message="AI 助手未启用", status_code=503)


def _authorize_sample(
    role: ProjectRole | None, sample_sharing_enabled: bool, sample: JsonValue | None
) -> None:
    if sample is None:
        return
    if not sample_sharing_enabled:
        raise AppError(
            code="AI_SAMPLE_SHARING_DISABLED",
            message="项目未开启脱敏样本共享",
            status_code=403,
        )
    if role not in {None, ProjectRole.OWNER}:
        raise AppError(
            code="AI_SAMPLE_OWNER_REQUIRED",
            message="仅项目 Owner 可以提交脱敏样本",
            status_code=403,
        )


def _validated_suggestions(job: AIJob, payload: dict[str, JsonValue]) -> list[AISuggestion]:
    schema = _output_schema(job.job_type)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    raw_suggestions = payload.get("suggestions")
    if not isinstance(raw_suggestions, list):
        raise ValueError("suggestions must be a list")
    allowed = _ALLOWED_SUGGESTIONS[job.job_type]
    suggestions: list[AISuggestion] = []
    for position, raw in enumerate(raw_suggestions):
        if not isinstance(raw, dict) or raw.get("type") not in allowed:
            raise ValueError("suggestion type is not allowed for this job")
        suggestion_type = str(raw["type"])
        raw_content = raw.get("content")
        if not isinstance(raw_content, dict):
            raise ValueError("suggestion content must be an object")
        content = (
            decode_change_set_content(suggestion_type, raw_content)
            if job.job_type == "change_set"
            else raw_content
        )
        sanitized = sanitize_ai_input(
            schema_document=None,
            metadata={"title": raw["title"], "content": content},
            sample=None,
        ).payload["metadata"]
        if not isinstance(sanitized, dict) or not isinstance(sanitized.get("content"), dict):
            raise ValueError("suggestion content must be an object")
        suggestions.append(
            AISuggestion(
                job_id=job.id,
                position=position,
                suggestion_type=suggestion_type,
                title=str(sanitized["title"])[:200],
                content=sanitized["content"],
                review_status="pending",
            )
        )
    return suggestions


def _output_schema(job_type: str) -> dict[str, JsonValue]:
    if job_type == "change_set":
        return change_set_output_schema(settings.ai_max_suggestions)
    return suggestion_output_schema(settings.ai_max_suggestions)


def _validate_pending_suggestion(suggestion: AISuggestion, job: AIJob) -> None:
    if job.status != "completed":
        raise AppError(code="AI_JOB_NOT_COMPLETED", message="AI 任务尚未完成", status_code=409)
    if job.job_type == "change_set":
        raise AppError(
            code="AI_CHANGE_SET_REVIEW_REQUIRED",
            message="请通过 AI 变更集逐项审核",
            status_code=409,
        )
    if suggestion.review_status != "pending":
        raise AppError(
            code="AI_SUGGESTION_ALREADY_REVIEWED",
            message="AI 建议已经完成审核",
            status_code=409,
        )


def _review_content(content: dict[str, JsonValue]) -> dict[str, JsonValue]:
    encoded = json.dumps(content, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_REVIEW_CONTENT_BYTES:
        raise AppError(code="AI_REVIEW_TOO_LARGE", message="审核内容超过 256 KB", status_code=422)
    sanitized = sanitize_ai_input(
        schema_document=None, metadata={"content": content}, sample=None
    ).payload["metadata"]
    if not isinstance(sanitized, dict) or not isinstance(sanitized.get("content"), dict):
        raise AppError(code="AI_REVIEW_INVALID", message="审核内容格式无效", status_code=422)
    return cast(dict[str, JsonValue], sanitized["content"])


async def _create_workflow_draft(
    *,
    session: AsyncSession,
    actor: User,
    project_id: UUID,
    title: str,
    content: dict[str, JsonValue],
) -> Workflow:
    try:
        definition = WorkflowDefinition.model_validate(content.get("definition"))
        folder_id = _optional_uuid(content.get("folder_id"))
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_WORKFLOW_DRAFT_INVALID", message="AI Workflow 草稿格式无效", status_code=422
        ) from error
    return await WorkflowService(session).create(
        actor=actor,
        project_id=project_id,
        name=str(content.get("name") or title)[:200],
        description=str(content.get("description") or "由 AI 建议生成。需人工复核"),
        folder_id=folder_id,
        definition=definition,
        commit=False,
    )


async def _create_test_case_draft(
    *,
    session: AsyncSession,
    actor: User,
    project_id: UUID,
    title: str,
    content: dict[str, JsonValue],
) -> TestCase:
    try:
        definition = TestCaseDefinitionInput.model_validate(content.get("definition"))
        folder_id = _optional_uuid(content.get("folder_id"))
        tags_value = content.get("tags", [])
        if not isinstance(tags_value, list) or not all(isinstance(tag, str) for tag in tags_value):
            raise ValueError("invalid tags")
    except (TypeError, ValueError) as error:
        raise AppError(
            code="AI_TEST_CASE_DRAFT_INVALID", message="AI Test Case 草稿格式无效", status_code=422
        ) from error
    return await TestCaseService(session).create(
        actor=actor,
        project_id=project_id,
        name=str(content.get("name") or title)[:200],
        description=str(content.get("description") or "由 AI 建议生成。需人工复核"),
        folder_id=folder_id,
        tags=cast(list[str], tags_value),
        is_template=False,
        definition=definition,
        commit=False,
    )


def _optional_uuid(value: JsonValue | None) -> UUID | None:
    if value in {None, ""}:
        return None
    return UUID(str(value))
