from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import Folder, User
from app.models.api_assets import Environment
from app.models.test_assets import TestCase, TestCaseVersion, TestSuite, TestSuiteVersion
from app.models.workflows import Workflow, WorkflowVersion
from app.repositories.test_asset_packages import TestAssetPackageRepository
from app.schemas.test_asset_packages import (
    PackageCase,
    PackageCaseVersion,
    PackageEnvironment,
    PackageExportRequest,
    PackageFolder,
    PackageSuite,
    PackageSuiteVersion,
    PackageWorkflow,
    PackageWorkflowVersion,
    TestAssetPackage,
)
from app.schemas.test_assets import TestAssetKind
from app.services.projects import ProjectService

PACKAGE_MAX_BYTES = 10 * 1024 * 1024


class TestAssetPackageReader(Protocol):
    async def asset(
        self, project_id: UUID, kind: TestAssetKind, asset_id: UUID
    ) -> TestCase | TestSuite | None: ...
    async def named(
        self, project_id: UUID, kind: TestAssetKind, name: str
    ) -> TestCase | TestSuite | None: ...
    async def case_versions(self, case_id: UUID) -> list[TestCaseVersion]: ...
    async def suite_versions(self, suite_id: UUID) -> list[TestSuiteVersion]: ...
    async def workflow(self, project_id: UUID, workflow_id: UUID) -> Workflow | None: ...
    async def workflow_version(self, workflow_id: UUID, version: int) -> WorkflowVersion | None: ...
    async def environment(self, project_id: UUID, environment_id: UUID) -> Environment | None: ...
    async def folder(self, project_id: UUID, folder_id: UUID) -> Folder | None: ...


class TestAssetPackageExportService:
    def __init__(self, session: AsyncSession, reader: TestAssetPackageReader | None = None) -> None:
        self._reader = reader or TestAssetPackageRepository(session)
        self._projects = ProjectService(session)

    async def export(
        self, *, actor: User, project_id: UUID, selection: PackageExportRequest
    ) -> TestAssetPackage:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        try:
            package = await self._build(project_id, selection)
        except ValidationError as error:
            raise AppError(
                code="TEST_ASSET_PACKAGE_EXPORT_INVALID",
                message="当前资产不符合原生包契约, 请检查版本、引用与运行参数",
                status_code=422,
            ) from error
        if len(package.model_dump_json(indent=2).encode()) > PACKAGE_MAX_BYTES:
            raise AppError(
                code="TEST_ASSET_PACKAGE_TOO_LARGE",
                message="原生包超过 10 MiB, 请缩小导出选择",
                status_code=413,
            )
        return package

    async def _build(self, project_id: UUID, selection: PackageExportRequest) -> TestAssetPackage:
        suites = [
            await self._suite(project_id, asset_id) for asset_id in sorted(selection.suite_ids)
        ]
        case_ids = set(selection.case_ids)
        for suite in suites:
            definitions = [
                suite.draft_definition,
                *(version.definition for version in suite.versions),
            ]
            case_ids.update(
                item.test_case_id for definition in definitions for item in definition.items
            )
        if len(case_ids) > 500:
            raise AppError(
                code="TEST_ASSET_PACKAGE_TOO_LARGE",
                message="原生包最多包含 500 个依赖用例",
                status_code=413,
            )
        cases = [await self._case(project_id, asset_id) for asset_id in sorted(case_ids)]
        environments, workflows = await self._references(project_id, cases)
        return TestAssetPackage(
            format="flowtest-test-assets",
            format_version=1,
            source_project_id=project_id,
            cases=cases,
            suites=suites,
            folders=await self._folders(project_id, [*cases, *suites]),
            environments=environments,
            workflows=workflows,
        )

    async def _case(self, project_id: UUID, asset_id: UUID) -> PackageCase:
        model = await self._reader.asset(project_id, "case", asset_id)
        if not isinstance(model, TestCase) or model.archived_at is not None:
            raise AppError(
                code="TEST_CASE_NOT_FOUND", message="选择的用例不存在或已归档", status_code=404
            )
        return PackageCase(
            id=model.id,
            name=model.name,
            description=model.description,
            folder_id=model.folder_id,
            tags=model.tags,
            is_template=model.is_template,
            draft_definition=model.draft_definition,
            versions=[
                PackageCaseVersion(
                    version=version.version,
                    definition=version.definition,
                    fingerprint=version.fingerprint,
                    change_note=version.change_note,
                )
                for version in await self._reader.case_versions(model.id)
            ],
        )

    async def _suite(self, project_id: UUID, asset_id: UUID) -> PackageSuite:
        model = await self._reader.asset(project_id, "suite", asset_id)
        if not isinstance(model, TestSuite) or model.archived_at is not None:
            raise AppError(
                code="TEST_SUITE_NOT_FOUND", message="选择的套件不存在或已归档", status_code=404
            )
        return PackageSuite(
            id=model.id,
            name=model.name,
            description=model.description,
            folder_id=model.folder_id,
            tags=model.tags,
            draft_definition=model.draft_definition,
            versions=[
                PackageSuiteVersion(
                    version=version.version,
                    definition=version.definition,
                    fingerprint=version.fingerprint,
                    change_note=version.change_note,
                )
                for version in await self._reader.suite_versions(model.id)
            ],
        )

    async def _references(
        self, project_id: UUID, cases: list[PackageCase]
    ) -> tuple[list[PackageEnvironment], list[PackageWorkflow]]:
        definitions = [
            definition
            for case in cases
            for definition in [
                case.draft_definition,
                *(version.definition for version in case.versions),
            ]
        ]
        environments = []
        for environment_id in sorted({definition.environment_id for definition in definitions}):
            model = await self._reader.environment(project_id, environment_id)
            if model is None:
                raise AppError(
                    code="ENVIRONMENT_NOT_FOUND", message="用例引用的环境不可用", status_code=404
                )
            environments.append(PackageEnvironment(id=model.id, name=model.name))
        workflows = []
        for workflow_id in sorted({definition.workflow_id for definition in definitions}):
            numbers = {
                definition.workflow_version
                for definition in definitions
                if definition.workflow_id == workflow_id and definition.workflow_version is not None
            }
            workflows.append(await self._workflow(project_id, workflow_id, numbers))
        return environments, workflows

    async def _workflow(
        self, project_id: UUID, workflow_id: UUID, numbers: set[int]
    ) -> PackageWorkflow:
        model = await self._reader.workflow(project_id, workflow_id)
        if model is None:
            raise AppError(
                code="WORKFLOW_NOT_FOUND", message="用例引用的流程不可用", status_code=404
            )
        versions = []
        for number in sorted(numbers):
            version = await self._reader.workflow_version(workflow_id, number)
            if version is None:
                raise AppError(
                    code="WORKFLOW_VERSION_NOT_FOUND",
                    message="用例固定的流程版本不存在",
                    status_code=404,
                )
            versions.append(PackageWorkflowVersion(version=number, fingerprint=version.fingerprint))
        return PackageWorkflow(id=model.id, name=model.name, versions=versions)

    async def _folders(
        self, project_id: UUID, assets: list[PackageCase | PackageSuite]
    ) -> list[PackageFolder]:
        pending = {asset.folder_id for asset in assets if asset.folder_id is not None}
        folders: dict[UUID, PackageFolder] = {}
        while pending:
            folder_id = min(pending)
            pending.remove(folder_id)
            if folder_id in folders:
                continue
            model = await self._reader.folder(project_id, folder_id)
            if model is None:
                raise AppError(
                    code="FOLDER_NOT_FOUND", message="资产引用的目录不存在", status_code=404
                )
            folders[model.id] = PackageFolder(
                id=model.id, name=model.name, parent_id=model.parent_id
            )
            if model.parent_id is not None:
                pending.add(model.parent_id)
        return [folders[folder_id] for folder_id in sorted(folders)]
