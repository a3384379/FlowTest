from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.storage import check_storage, ensure_storage_bucket


async def test_existing_storage_bucket_is_reused() -> None:
    client = Mock()
    with patch("app.core.storage.create_s3_client", return_value=client):
        await ensure_storage_bucket()

    client.head_bucket.assert_called_once_with(Bucket=settings.s3_bucket)
    client.create_bucket.assert_not_called()


async def test_missing_storage_bucket_is_created() -> None:
    client = Mock()
    client.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": "missing"}},
        "HeadBucket",
    )
    with patch("app.core.storage.create_s3_client", return_value=client):
        await ensure_storage_bucket()

    client.create_bucket.assert_called_once_with(Bucket=settings.s3_bucket)


async def test_unexpected_storage_error_is_raised() -> None:
    client = Mock()
    client.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
        "HeadBucket",
    )
    with (
        patch("app.core.storage.create_s3_client", return_value=client),
        pytest.raises(ClientError),
    ):
        await ensure_storage_bucket()


async def test_storage_health_checks_bucket() -> None:
    client = Mock()
    with patch("app.core.storage.create_s3_client", return_value=client):
        await check_storage()

    client.head_bucket.assert_called_once_with(Bucket=settings.s3_bucket)
