import asyncio
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class StoredObject:
    content: bytes
    content_type: str


class ObjectStorage:
    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        client = create_s3_client()
        await asyncio.to_thread(
            client.put_object,
            Bucket=settings.s3_bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    async def get(self, *, key: str) -> StoredObject:
        client = create_s3_client()

        def download() -> StoredObject:
            response = client.get_object(Bucket=settings.s3_bucket, Key=key)
            return StoredObject(
                content=response["Body"].read(),
                content_type=str(response.get("ContentType", "application/octet-stream")),
            )

        return await asyncio.to_thread(download)

    async def delete(self, *, key: str) -> None:
        client = create_s3_client()
        await asyncio.to_thread(client.delete_object, Bucket=settings.s3_bucket, Key=key)


object_storage = ObjectStorage()
