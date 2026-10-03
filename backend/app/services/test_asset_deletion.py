from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.access import User
from app.models.test_assets import TestCase, TestSuite
from app.repositories.test_asset_deletion import TestAssetDeletionRepository
from app.schemas.test_assets import (
    AssetDeleteTarget,
    AssetDeletionPreviewResponse,
    AssetDeletionPreviewTarget,
    AssetDeletionResponse,
    AssetReference,
    TestAssetKind,
)
from app.services.audit import AuditService
from app.services.projects import ProjectService


class TestAssetDeletionReader(Protocol):
    async def selected_for_update(
        self, *, project_id: UUID, kind: TestAssetKind, asset_ids: list[UUID]
    ) -> list[TestCase | TestSuite]: ...
    async def references(
        self, *, project_id: UUID, kind: TestAssetKind, asset_id: UUID
    ) -> list[AssetReference]: ...


class TestAssetDeletionService:
    def __init__(
        self, session: AsyncSession, reader: TestAssetDeletionReader | None = None
    ) -> None:
        self._session = session
        self._reader = reader or TestAssetDeletionRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def preview(
        self, *, actor: User, project_id: UUID, kind: TestAssetKind, asset_ids: list[UUID]
    ) -> AssetDeletionPreviewResponse:
        models = await self._selected(actor, project_id, kind, asset_ids)
        targets = []
        for model in models:
            refs = (
                []
                if model.archived_at is not None
                else await self._reader.references(
                    project_id=project_id, kind=kind, asset_id=model.id
                )
            )
            targets.append(
                AssetDeletionPreviewTarget(
                    asset=_delete_target(model),
                    archived=model.archived_at is not None,
                    references=refs,
                )
            )
        return AssetDeletionPreviewResponse(targets=targets)

    async def delete_one(
        self,
        *,
        actor: User,
        project_id: UUID,
        kind: TestAssetKind,
        asset_id: UUID,
        target: AssetDeleteTarget,
    ) -> AssetDeletionResponse:
        if asset_id != target.id:
            raise AppError(
                code="TEST_ASSET_DELETE_SCOPE_MISMATCH",
                message="删除对象与确认选择不一致",
                status_code=422,
            )
        return await self.delete(actor=actor, project_id=project_id, kind=kind, targets=[target])

    async def delete(
        self,
        *,
        actor: User,
        project_id: UUID,
        kind: TestAssetKind,
        targets: list[AssetDeleteTarget],
    ) -> AssetDeletionResponse:
        models = await self._selected(actor, project_id, kind, [target.id for target in targets])
        expected = {target.id: target for target in targets}
        for model in models:
            await self._validate_deletion(project_id, kind, model, expected[model.id])
        now = datetime.now(UTC)
        for model in models:
            if model.archived_at is None:
                model.archived_at = now
                self._audit.record(
                    actor_user_id=actor.id,
                    project_id=project_id,
                    action=f"test_{kind}.archived",
                    resource_type=f"test_{kind}",
                    resource_id=model.id,
                    details={"historical_data_retained": True},
                )
        await self._session.commit()
        return AssetDeletionResponse(archived_ids=[model.id for model in models])

    async def _selected(
        self, actor: User, project_id: UUID, kind: TestAssetKind, asset_ids: list[UUID]
    ) -> list[TestCase | TestSuite]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        models = await self._reader.selected_for_update(
            project_id=project_id, kind=kind, asset_ids=asset_ids
        )
        if not asset_ids or len(models) != len(asset_ids):
            raise AppError(
                code="TEST_ASSET_NOT_FOUND",
                message="选中的测试资产不存在或不属于当前项目",
                status_code=404,
            )
        return models

    async def _validate_deletion(
        self,
        project_id: UUID,
        kind: TestAssetKind,
        model: TestCase | TestSuite,
        target: AssetDeleteTarget,
    ) -> None:
        if model.archived_at is not None:
            return
        if _delete_target(model) != target:
            raise AppError(
                code="TEST_ASSET_DELETE_STALE",
                message="测试资产已变化,请重新查看删除预览",
                status_code=409,
                details={"asset_id": str(model.id)},
            )
        refs = await self._reader.references(project_id=project_id, kind=kind, asset_id=model.id)
        if refs:
            raise AppError(
                code="TEST_ASSET_IN_USE",
                message="测试资产仍被套件、计划或活动执行引用,不能删除",
                status_code=409,
                details={
                    "asset_id": str(model.id),
                    "references": [ref.model_dump(mode="json") for ref in refs],
                },
            )


def _delete_target(model: TestCase | TestSuite) -> AssetDeleteTarget:
    updated = (
        model.updated_at.replace(tzinfo=UTC)
        if model.updated_at.tzinfo is None
        else model.updated_at.astimezone(UTC)
    )
    return AssetDeleteTarget(
        id=model.id,
        expected_name=model.name,
        expected_draft_fingerprint=model.draft_fingerprint,
        expected_version=model.current_version,
        expected_updated_at=updated,
    )
