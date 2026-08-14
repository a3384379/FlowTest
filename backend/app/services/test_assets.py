from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.api_assets import JsonValue
from app.domain.test_assets import VersionChange, definition_fingerprint, version_changes
from app.models.access import Folder, User
from app.models.api_assets import Environment
from app.models.test_assets import (
    TestCase,
    TestCaseVersion,
    TestSuite,
    TestSuiteVersion,
    TestSuiteVersionItem,
)
from app.models.workflows import Workflow
from app.repositories.test_assets import TestAssetRepository
from app.repositories.workflows import WorkflowRepository
from app.schemas.test_assets import (
    PublishedTestCaseDefinition,
    PublishedTestSuiteDefinition,
    PublishedTestSuiteItem,
    TestCaseDefinitionInput,
    TestSuiteDefinitionInput,
)
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class AssetVersionDiff:
    from_version: int
    to_version: int
    changes: tuple[VersionChange, ...]


class TestCaseService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._assets = TestAssetRepository(session)
        self._workflows = WorkflowRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        description: str,
        folder_id: UUID | None,
        tags: list[str],
        is_template: bool,
        definition: TestCaseDefinitionInput,
        commit: bool = True,
    ) -> TestCase:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_name = name.strip()
        await self._ensure_unique_name(project_id, normalized_name)
        await _validate_folder(self._session, project_id, folder_id)
        await self._validate_definition(project_id, definition)
        model = TestCase(
            project_id=project_id,
            folder_id=folder_id,
            name=normalized_name,
            description=description.strip(),
            tags=_normalize_tags(tags),
            is_template=is_template,
            draft_definition=_json_definition(definition),
            current_version=None,
            created_by_id=actor.id,
        )
        self._assets.add(model)
        await self._session.flush()
        self._record(actor, model, "test_case.created")
        if commit:
            await self._session.commit()
            await self._session.refresh(model)
        return model

    async def list_cases(
        self,
        *,
        actor: User,
        project_id: UUID,
        search: str | None,
        tag: str | None,
        is_template: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TestCase], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._assets.list_cases(
            project_id=project_id,
            search=search.strip() if search else None,
            tag=tag,
            is_template=is_template,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(self, *, actor: User, project_id: UUID, case_id: UUID) -> TestCase:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._get_project_case(project_id, case_id)

    async def update(
        self,
        *,
        actor: User,
        project_id: UUID,
        case_id: UUID,
        name: str | None,
        description: str | None,
        folder_id: UUID | None,
        change_folder: bool,
        tags: list[str] | None,
        is_template: bool | None,
        definition: TestCaseDefinitionInput | None,
        commit: bool = True,
    ) -> TestCase:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        model = await self._get_project_case_for_update(project_id, case_id)
        if name is not None:
            normalized_name = name.strip()
            await self._ensure_unique_name(project_id, normalized_name, excluding_id=model.id)
            model.name = normalized_name
        if description is not None:
            model.description = description.strip()
        if change_folder:
            await _validate_folder(self._session, project_id, folder_id)
            model.folder_id = folder_id
        if tags is not None:
            model.tags = _normalize_tags(tags)
        if is_template is not None:
            model.is_template = is_template
        if definition is not None:
            await self._validate_definition(project_id, definition)
            model.draft_definition = _json_definition(definition)
        self._record(actor, model, "test_case.updated")
        if commit:
            await self._session.commit()
            await self._session.refresh(model)
        else:
            await self._session.flush()
        return model

    async def publish(
        self,
        *,
        actor: User,
        project_id: UUID,
        case_id: UUID,
        change_note: str,
    ) -> TestCaseVersion:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        model = await self._get_project_case_for_update(project_id, case_id)
        definition = TestCaseDefinitionInput.model_validate(model.draft_definition)
        published = await self._published_definition(project_id, definition)
        payload = _json_definition(published)
        version_number = (model.current_version or 0) + 1
        version = TestCaseVersion(
            test_case_id=model.id,
            version=version_number,
            definition=payload,
            fingerprint=definition_fingerprint(payload),
            change_note=change_note.strip(),
            created_by_id=actor.id,
        )
        self._assets.add(version)
        model.current_version = version_number
        self._record(
            actor,
            model,
            "test_case.published",
            details={"version": version_number},
        )
        await self._session.commit()
        await self._session.refresh(version)
        return version

    async def list_versions(
        self, *, actor: User, project_id: UUID, case_id: UUID
    ) -> list[TestCaseVersion]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        await self._get_project_case(project_id, case_id)
        return await self._assets.list_case_versions(case_id)

    async def diff(
        self,
        *,
        actor: User,
        project_id: UUID,
        case_id: UUID,
        from_version: int,
        to_version: int,
    ) -> AssetVersionDiff:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        await self._get_project_case(project_id, case_id)
        before = await self._get_version(case_id, from_version)
        after = await self._get_version(case_id, to_version)
        return AssetVersionDiff(
            from_version,
            to_version,
            version_changes(
                cast(dict[str, JsonValue], before.definition),
                cast(dict[str, JsonValue], after.definition),
            ),
        )

    async def clone(self, *, actor: User, project_id: UUID, case_id: UUID, name: str) -> TestCase:
        source = await self.get(actor=actor, project_id=project_id, case_id=case_id)
        return await self.create(
            actor=actor,
            project_id=project_id,
            name=name,
            description=source.description,
            folder_id=source.folder_id,
            tags=source.tags,
            is_template=False,
            definition=TestCaseDefinitionInput.model_validate(source.draft_definition),
        )

    async def bulk_move(
        self,
        *,
        actor: User,
        project_id: UUID,
        case_ids: list[UUID],
        folder_id: UUID | None,
    ) -> int:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        await _validate_folder(self._session, project_id, folder_id)
        cases = [await self._get_project_case(project_id, case_id) for case_id in case_ids]
        for model in cases:
            model.folder_id = folder_id
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_case.bulk_moved",
            resource_type="test_case",
            resource_id=None,
            details={"count": len(cases), "folder_id": str(folder_id) if folder_id else None},
        )
        await self._session.commit()
        return len(cases)

    async def _validate_definition(
        self, project_id: UUID, definition: TestCaseDefinitionInput
    ) -> None:
        workflow = await self._session.get(Workflow, definition.workflow_id)
        if workflow is None or workflow.project_id != project_id:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
        environment = await self._session.get(Environment, definition.environment_id)
        if environment is None or environment.project_id != project_id:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        if (
            definition.workflow_version is not None
            and await self._workflows.find_version(workflow.id, definition.workflow_version) is None
        ):
            raise AppError(
                code="WORKFLOW_VERSION_NOT_FOUND",
                message="工作流版本不存在",
                status_code=404,
            )

    async def _published_definition(
        self, project_id: UUID, definition: TestCaseDefinitionInput
    ) -> PublishedTestCaseDefinition:
        await self._validate_definition(project_id, definition)
        workflow = await self._session.get(Workflow, definition.workflow_id)
        if workflow is None:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="工作流不存在", status_code=404)
        version = definition.workflow_version or workflow.current_version
        if version is None or await self._workflows.find_version(workflow.id, version) is None:
            raise AppError(
                code="WORKFLOW_NOT_PUBLISHED",
                message="测试用例只能引用已发布的工作流版本",
                status_code=409,
            )
        return PublishedTestCaseDefinition(
            workflow_id=workflow.id,
            workflow_version=version,
            environment_id=definition.environment_id,
            runtime_variables=dict(definition.runtime_variables),
            runtime_headers=dict(definition.runtime_headers),
        )

    async def _get_project_case(self, project_id: UUID, case_id: UUID) -> TestCase:
        model = await self._assets.get_case(case_id)
        if model is None or model.project_id != project_id:
            raise AppError(code="TEST_CASE_NOT_FOUND", message="测试用例不存在", status_code=404)
        return model

    async def _get_project_case_for_update(self, project_id: UUID, case_id: UUID) -> TestCase:
        model = await self._assets.get_case_for_update(case_id)
        if model is None or model.project_id != project_id:
            raise AppError(code="TEST_CASE_NOT_FOUND", message="测试用例不存在", status_code=404)
        return model

    async def _get_version(self, case_id: UUID, version: int) -> TestCaseVersion:
        model = await self._assets.find_case_version(case_id, version)
        if model is None:
            raise AppError(
                code="TEST_CASE_VERSION_NOT_FOUND",
                message="测试用例版本不存在",
                status_code=404,
            )
        return model

    async def _ensure_unique_name(
        self, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        if await self._assets.case_name_exists(
            project_id=project_id, name=name, excluding_id=excluding_id
        ):
            raise AppError(
                code="TEST_CASE_NAME_EXISTS",
                message="测试用例名称已存在",
                status_code=409,
            )

    def _record(
        self,
        actor: User,
        model: TestCase,
        action: str,
        *,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=model.project_id,
            action=action,
            resource_type="test_case",
            resource_id=model.id,
            details=details,
        )


class TestSuiteService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._assets = TestAssetRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        description: str,
        folder_id: UUID | None,
        tags: list[str],
        definition: TestSuiteDefinitionInput,
    ) -> TestSuite:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_name = name.strip()
        await self._ensure_unique_name(project_id, normalized_name)
        await _validate_folder(self._session, project_id, folder_id)
        await self._validate_definition(project_id, definition, require_published=False)
        model = TestSuite(
            project_id=project_id,
            folder_id=folder_id,
            name=normalized_name,
            description=description.strip(),
            tags=_normalize_tags(tags),
            draft_definition=_json_definition(definition),
            current_version=None,
            created_by_id=actor.id,
        )
        self._assets.add(model)
        await self._session.flush()
        self._record(actor, model, "test_suite.created")
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def list_suites(
        self,
        *,
        actor: User,
        project_id: UUID,
        search: str | None,
        tag: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TestSuite], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._assets.list_suites(
            project_id=project_id,
            search=search.strip() if search else None,
            tag=tag,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(self, *, actor: User, project_id: UUID, suite_id: UUID) -> TestSuite:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._get_project_suite(project_id, suite_id)

    async def update(
        self,
        *,
        actor: User,
        project_id: UUID,
        suite_id: UUID,
        name: str | None,
        description: str | None,
        folder_id: UUID | None,
        change_folder: bool,
        tags: list[str] | None,
        definition: TestSuiteDefinitionInput | None,
    ) -> TestSuite:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        model = await self._get_project_suite(project_id, suite_id)
        if name is not None:
            normalized_name = name.strip()
            await self._ensure_unique_name(project_id, normalized_name, excluding_id=model.id)
            model.name = normalized_name
        if description is not None:
            model.description = description.strip()
        if change_folder:
            await _validate_folder(self._session, project_id, folder_id)
            model.folder_id = folder_id
        if tags is not None:
            model.tags = _normalize_tags(tags)
        if definition is not None:
            await self._validate_definition(project_id, definition, require_published=False)
            model.draft_definition = _json_definition(definition)
        self._record(actor, model, "test_suite.updated")
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def publish(
        self,
        *,
        actor: User,
        project_id: UUID,
        suite_id: UUID,
        change_note: str,
    ) -> TestSuiteVersion:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        suite = await self._get_project_suite_for_update(project_id, suite_id)
        definition = TestSuiteDefinitionInput.model_validate(suite.draft_definition)
        published = await self._published_definition(project_id, definition)
        payload = _json_definition(published)
        version_number = (suite.current_version or 0) + 1
        version = TestSuiteVersion(
            test_suite_id=suite.id,
            version=version_number,
            definition=payload,
            fingerprint=definition_fingerprint(payload),
            change_note=change_note.strip(),
            created_by_id=actor.id,
        )
        self._assets.add(version)
        await self._session.flush()
        self._assets.add_all(
            [
                TestSuiteVersionItem(
                    test_suite_version_id=version.id,
                    test_case_id=item.test_case_id,
                    test_case_version=item.test_case_version,
                    position=position,
                )
                for position, item in enumerate(published.items)
            ]
        )
        suite.current_version = version_number
        self._record(
            actor,
            suite,
            "test_suite.published",
            details={"version": version_number, "item_count": len(published.items)},
        )
        await self._session.commit()
        await self._session.refresh(version)
        return version

    async def list_versions(
        self, *, actor: User, project_id: UUID, suite_id: UUID
    ) -> list[TestSuiteVersion]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        await self._get_project_suite(project_id, suite_id)
        return await self._assets.list_suite_versions(suite_id)

    async def diff(
        self,
        *,
        actor: User,
        project_id: UUID,
        suite_id: UUID,
        from_version: int,
        to_version: int,
    ) -> AssetVersionDiff:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        await self._get_project_suite(project_id, suite_id)
        before = await self._get_version(suite_id, from_version)
        after = await self._get_version(suite_id, to_version)
        return AssetVersionDiff(
            from_version,
            to_version,
            version_changes(
                cast(dict[str, JsonValue], before.definition),
                cast(dict[str, JsonValue], after.definition),
            ),
        )

    async def clone(self, *, actor: User, project_id: UUID, suite_id: UUID, name: str) -> TestSuite:
        source = await self.get(actor=actor, project_id=project_id, suite_id=suite_id)
        return await self.create(
            actor=actor,
            project_id=project_id,
            name=name,
            description=source.description,
            folder_id=source.folder_id,
            tags=source.tags,
            definition=TestSuiteDefinitionInput.model_validate(source.draft_definition),
        )

    async def bulk_move(
        self,
        *,
        actor: User,
        project_id: UUID,
        suite_ids: list[UUID],
        folder_id: UUID | None,
    ) -> int:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        await _validate_folder(self._session, project_id, folder_id)
        suites = [await self._get_project_suite(project_id, suite_id) for suite_id in suite_ids]
        for model in suites:
            model.folder_id = folder_id
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="test_suite.bulk_moved",
            resource_type="test_suite",
            resource_id=None,
            details={"count": len(suites), "folder_id": str(folder_id) if folder_id else None},
        )
        await self._session.commit()
        return len(suites)

    async def _validate_definition(
        self,
        project_id: UUID,
        definition: TestSuiteDefinitionInput,
        *,
        require_published: bool,
    ) -> None:
        ids = [item.test_case_id for item in definition.items]
        if len(ids) != len(set(ids)):
            raise AppError(
                code="TEST_SUITE_DUPLICATE_CASE",
                message="测试套件不能重复引用同一测试用例",
                status_code=422,
            )
        for item in definition.items:
            case = await self._assets.get_case(item.test_case_id)
            if case is None or case.project_id != project_id:
                raise AppError(
                    code="TEST_CASE_NOT_FOUND", message="测试用例不存在", status_code=404
                )
            version = item.test_case_version or case.current_version
            if require_published and (
                version is None or await self._assets.find_case_version(case.id, version) is None
            ):
                raise AppError(
                    code="TEST_CASE_NOT_PUBLISHED",
                    message="测试套件只能引用已发布的测试用例版本",
                    status_code=409,
                )
            if (
                item.test_case_version is not None
                and await self._assets.find_case_version(case.id, item.test_case_version) is None
            ):
                raise AppError(
                    code="TEST_CASE_VERSION_NOT_FOUND",
                    message="测试用例版本不存在",
                    status_code=404,
                )

    async def _published_definition(
        self, project_id: UUID, definition: TestSuiteDefinitionInput
    ) -> PublishedTestSuiteDefinition:
        await self._validate_definition(project_id, definition, require_published=True)
        items: list[PublishedTestSuiteItem] = []
        for item in definition.items:
            case = await self._assets.get_case(item.test_case_id)
            if case is None:
                raise AppError(
                    code="TEST_CASE_NOT_FOUND", message="测试用例不存在", status_code=404
                )
            version = item.test_case_version or case.current_version
            if version is None:
                raise AppError(
                    code="TEST_CASE_NOT_PUBLISHED",
                    message="测试用例尚未发布",
                    status_code=409,
                )
            items.append(PublishedTestSuiteItem(test_case_id=case.id, test_case_version=version))
        return PublishedTestSuiteDefinition(items=items)

    async def _get_project_suite(self, project_id: UUID, suite_id: UUID) -> TestSuite:
        model = await self._assets.get_suite(suite_id)
        if model is None or model.project_id != project_id:
            raise AppError(code="TEST_SUITE_NOT_FOUND", message="测试套件不存在", status_code=404)
        return model

    async def _get_project_suite_for_update(self, project_id: UUID, suite_id: UUID) -> TestSuite:
        model = await self._assets.get_suite_for_update(suite_id)
        if model is None or model.project_id != project_id:
            raise AppError(code="TEST_SUITE_NOT_FOUND", message="测试套件不存在", status_code=404)
        return model

    async def _get_version(self, suite_id: UUID, version: int) -> TestSuiteVersion:
        model = await self._assets.find_suite_version(suite_id, version)
        if model is None:
            raise AppError(
                code="TEST_SUITE_VERSION_NOT_FOUND",
                message="测试套件版本不存在",
                status_code=404,
            )
        return model

    async def _ensure_unique_name(
        self, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        if await self._assets.suite_name_exists(
            project_id=project_id, name=name, excluding_id=excluding_id
        ):
            raise AppError(
                code="TEST_SUITE_NAME_EXISTS",
                message="测试套件名称已存在",
                status_code=409,
            )

    def _record(
        self,
        actor: User,
        model: TestSuite,
        action: str,
        *,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=model.project_id,
            action=action,
            resource_type="test_suite",
            resource_id=model.id,
            details=details,
        )


async def _validate_folder(session: AsyncSession, project_id: UUID, folder_id: UUID | None) -> None:
    if folder_id is None:
        return
    folder = await session.get(Folder, folder_id)
    if folder is None or folder.project_id != project_id:
        raise AppError(code="FOLDER_NOT_FOUND", message="目录不存在", status_code=404)


def _normalize_tags(tags: list[str]) -> list[str]:
    return sorted({tag.strip() for tag in tags if tag.strip()})


type AssetDefinition = (
    TestCaseDefinitionInput
    | PublishedTestCaseDefinition
    | TestSuiteDefinitionInput
    | PublishedTestSuiteDefinition
)


def _json_definition(definition: AssetDefinition) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], definition.model_dump(mode="json"))
