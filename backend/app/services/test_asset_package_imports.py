from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import User
from app.repositories.test_asset_packages import TestAssetPackageRepository
from app.schemas.test_asset_packages import (
    PackageApplyRequest,
    PackageApplyResponse,
    PackageAssetPreview,
    PackageCase,
    PackageImportedAsset,
    PackagePreviewRequest,
    PackagePreviewResponse,
    PackageSuite,
)
from app.schemas.test_assets import TestCaseDefinitionInput, TestSuiteDefinitionInput
from app.services.projects import ProjectService
from app.services.test_asset_package_preview import (
    PreparedPackageImport,
    TestAssetPackagePreviewBuilder,
    map_case_definition,
    map_suite_definition,
)
from app.services.test_asset_packages import TestAssetPackageReader
from app.services.test_assets import TestCaseService, TestSuiteService


class TestAssetPackageImportService:
    def __init__(self, session: AsyncSession, reader: TestAssetPackageReader | None = None) -> None:
        self._session = session
        self._reader = reader or TestAssetPackageRepository(session)
        self._projects = ProjectService(session)
        self._cases = TestCaseService(session)
        self._suites = TestSuiteService(session)

    async def preview(
        self, *, actor: User, project_id: UUID, request: PackagePreviewRequest
    ) -> PackagePreviewResponse:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        return (
            await TestAssetPackagePreviewBuilder(self._reader).prepare(project_id, request)
        ).preview

    async def apply(
        self, *, actor: User, project_id: UUID, request: PackageApplyRequest
    ) -> PackageApplyResponse:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        reviewed = PackagePreviewRequest(
            package=request.package, choices=request.choices, bindings=request.bindings
        )
        prepared = await TestAssetPackagePreviewBuilder(self._reader).prepare(project_id, reviewed)
        _require_current_preview(prepared.preview, request.expected_preview_fingerprint)
        try:
            result = await self._apply_assets(actor, project_id, reviewed, prepared)
            await self._session.commit()
        except AppError:
            await self._session.rollback()
            raise
        except IntegrityError as error:
            await self._session.rollback()
            raise AppError(
                code="TEST_ASSET_PACKAGE_CONFLICT",
                message="资产名称或版本已变化, 整批导入已撤销, 请重新预览",
                status_code=409,
            ) from error
        return PackageApplyResponse(assets=result)

    async def _apply_assets(
        self,
        actor: User,
        project_id: UUID,
        request: PackagePreviewRequest,
        prepared: PreparedPackageImport,
    ) -> list[PackageImportedAsset]:
        result = []
        previews = {(asset.kind, asset.source_id): asset for asset in prepared.preview.assets}
        for source in request.package.cases:
            preview = previews[("case", source.id)]
            target_id = await self._case(actor, project_id, source, preview, prepared)
            preview.target_id = target_id
            result.append(_imported(preview, target_id))
        for source_suite in request.package.suites:
            preview = previews[("suite", source_suite.id)]
            target_id = await self._suite(actor, project_id, source_suite, preview, prepared)
            result.append(_imported(preview, target_id))
        return result

    async def _case(
        self,
        actor: User,
        project_id: UUID,
        source: PackageCase,
        preview: PackageAssetPreview,
        prepared: PreparedPackageImport,
    ) -> UUID:
        if preview.action == "skip":
            return _existing_id(preview)
        draft = map_case_definition(source.draft_definition, prepared.bindings)
        folder_id = prepared.bindings.folders.get(source.folder_id) if source.folder_id else None
        if preview.target_id is None:
            created = await self._cases.create(
                actor=actor,
                project_id=project_id,
                name=preview.target_name,
                description=source.description,
                folder_id=folder_id,
                tags=source.tags,
                is_template=source.is_template,
                definition=draft,
                commit=False,
            )
            target_id = created.id
        else:
            target_id = preview.target_id
        versions = {version.version: version for version in prepared.cases[source.id]}
        for mapping in preview.versions:
            if not mapping.creates_version:
                continue
            version = versions[mapping.source_version]
            await self._case_draft(actor, project_id, target_id, version.definition)
            published = await self._cases.publish(
                actor=actor,
                project_id=project_id,
                case_id=target_id,
                change_note=version.change_note,
                commit=False,
            )
            _require_version(published.version, mapping.target_version)
        await self._cases.update(
            actor=actor,
            project_id=project_id,
            case_id=target_id,
            name=preview.target_name,
            description=source.description,
            folder_id=folder_id,
            change_folder=True,
            tags=source.tags,
            is_template=source.is_template,
            definition=draft,
            commit=False,
        )
        return target_id

    async def _case_draft(
        self, actor: User, project_id: UUID, target_id: UUID, definition: TestCaseDefinitionInput
    ) -> None:
        await self._cases.update(
            actor=actor,
            project_id=project_id,
            case_id=target_id,
            name=None,
            description=None,
            folder_id=None,
            change_folder=False,
            tags=None,
            is_template=None,
            definition=definition,
            commit=False,
        )

    async def _suite(
        self,
        actor: User,
        project_id: UUID,
        source: PackageSuite,
        preview: PackageAssetPreview,
        prepared: PreparedPackageImport,
    ) -> UUID:
        if preview.action == "skip":
            return _existing_id(preview)
        draft = map_suite_definition(source.draft_definition, prepared.preview.assets)
        folder_id = prepared.bindings.folders.get(source.folder_id) if source.folder_id else None
        if preview.target_id is None:
            created = await self._suites.create(
                actor=actor,
                project_id=project_id,
                name=preview.target_name,
                description=source.description,
                folder_id=folder_id,
                tags=source.tags,
                definition=draft,
                commit=False,
            )
            target_id = created.id
        else:
            target_id = preview.target_id
        versions = {version.version: version for version in source.versions}
        for mapping in preview.versions:
            if not mapping.creates_version:
                continue
            version = versions[mapping.source_version]
            definition = map_suite_definition(version.definition, prepared.preview.assets)
            await self._suite_draft(actor, project_id, target_id, definition)
            published = await self._suites.publish(
                actor=actor,
                project_id=project_id,
                suite_id=target_id,
                change_note=version.change_note,
                commit=False,
            )
            _require_version(published.version, mapping.target_version)
        await self._suites.update(
            actor=actor,
            project_id=project_id,
            suite_id=target_id,
            name=preview.target_name,
            description=source.description,
            folder_id=folder_id,
            change_folder=True,
            tags=source.tags,
            definition=draft,
            commit=False,
        )
        return target_id

    async def _suite_draft(
        self, actor: User, project_id: UUID, target_id: UUID, definition: TestSuiteDefinitionInput
    ) -> None:
        await self._suites.update(
            actor=actor,
            project_id=project_id,
            suite_id=target_id,
            name=None,
            description=None,
            folder_id=None,
            change_folder=False,
            tags=None,
            definition=definition,
            commit=False,
        )


def _require_current_preview(preview: PackagePreviewResponse, expected: str) -> None:
    if preview.fingerprint != expected:
        raise AppError(
            code="TEST_ASSET_PACKAGE_PREVIEW_STALE",
            message="资产或资源绑定已变化, 请重新预览并确认",
            status_code=409,
        )
    if not preview.can_apply:
        raise AppError(
            code="TEST_ASSET_PACKAGE_BLOCKED",
            message="请先处理预览中的冲突与缺失绑定",
            status_code=409,
        )


def _existing_id(preview: PackageAssetPreview) -> UUID:
    if preview.target_id is None:
        raise AppError(
            code="TEST_ASSET_PACKAGE_BLOCKED", message="复用目标不存在, 请重新预览", status_code=409
        )
    return preview.target_id


def _require_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise AppError(
            code="TEST_ASSET_PACKAGE_PREVIEW_STALE",
            message="目标版本已变化, 整批导入已撤销, 请重新预览",
            status_code=409,
        )


def _imported(preview: PackageAssetPreview, target_id: UUID) -> PackageImportedAsset:
    return PackageImportedAsset(
        kind=preview.kind,
        source_id=preview.source_id,
        target_id=target_id,
        action=preview.action,
        versions=preview.versions,
    )
