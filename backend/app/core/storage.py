import asyncio
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


def create_s3_client() -> "S3Client":
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
    )


async def ensure_storage_bucket() -> None:
    client = create_s3_client()

    def ensure() -> None:
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            client.create_bucket(Bucket=settings.s3_bucket)

    await asyncio.to_thread(ensure)


async def check_storage() -> None:
    client = create_s3_client()
    await asyncio.to_thread(client.head_bucket, Bucket=settings.s3_bucket)
