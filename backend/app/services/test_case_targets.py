"""Resolve immutable case versions for plan and direct execution."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.api_assets import JsonValue
from app.models.api_assets import Environment
from app.models.workflows import Workflow
from app.repositories.test_assets import TestAssetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.test_assets import PublishedTestCaseDefinition


@dataclass(frozen=True, slots=True)
class ResolvedTestCaseTarget:
    case_id: UUID
    case_version: int
    workflow_id: UUID
    workflow_version: int
    environment_id: UUID
    runtime_variables: dict[str, str]
    runtime_headers: dict[str, str]
    target_snapshot: dict[str, JsonValue]


def _merge_headers(base: dict[str, str], overrides: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    for name, value in overrides.items():
        for existing in tuple(merged):
            if existing.lower() == name.lower():
                del merged[existing]
        merged[name] = value
    return merged


async def resolve_test_case_target(
    session: AsyncSession,
    *,
    project_id: UUID,
    case_id: UUID,
    case_version: int,
    runtime_variables: dict[str, str],
    runtime_headers: dict[str, str],
    suite_id: UUID | None = None,
    suite_version: int | None = None,
) -> ResolvedTestCaseTarget:
    assets = TestAssetRepository(session)
    case = await assets.get_case(case_id)
    version = await assets.find_case_version(case_id, case_version)
    if case is None or case.project_id != project_id or version is None:
        raise AppError(
            code="TEST_CASE_VERSION_NOT_FOUND", message="测试用例版本不存在", status_code=409
        )
    try:
        definition = PublishedTestCaseDefinition.model_validate(version.definition)
    except ValidationError as error:
        raise AppError(
            code="INVALID_TEST_CASE_DEFINITION",
            message="用例版本定义无效, 请修正草稿并发布新版本",
            status_code=422,
        ) from error
    workflow = await session.get(Workflow, definition.workflow_id)
    environment = await session.get(Environment, definition.environment_id)
    if (
        workflow is None
        or workflow.project_id != project_id
        or workflow.archived_at is not None
        or await WorkflowRepository(session).find_version(workflow.id, definition.workflow_version)
        is None
    ):
        raise AppError(code="WORKFLOW_VERSION_NOT_FOUND", message="流程版本不可用", status_code=409)
    if (
        environment is None
        or environment.project_id != project_id
        or environment.archived_at is not None
    ):
        raise AppError(code="ENVIRONMENT_NOT_FOUND", message="运行环境不可用", status_code=409)
    snapshot: dict[str, JsonValue] = {
        "target_type": "case",
        "target_id": str(case.id),
        "target_version": version.version,
        "definition": definition.model_dump(mode="json"),
    }
    if suite_id is not None:
        snapshot["source_suite"] = {"id": str(suite_id), "version": suite_version}
    return ResolvedTestCaseTarget(
        case_id=case.id,
        case_version=version.version,
        workflow_id=definition.workflow_id,
        workflow_version=definition.workflow_version,
        environment_id=definition.environment_id,
        runtime_variables={**definition.runtime_variables, **runtime_variables},
        runtime_headers=_merge_headers(definition.runtime_headers, runtime_headers),
        target_snapshot=snapshot,
    )
