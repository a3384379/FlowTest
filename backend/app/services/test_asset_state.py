from datetime import datetime

from app.core.errors import AppError


def ensure_test_asset_active(archived_at: datetime | None) -> None:
    if archived_at is not None:
        raise AppError(
            code="TEST_ASSET_ARCHIVED",
            message="测试资产已删除,历史版本与报告仍可查看",
            status_code=409,
        )
