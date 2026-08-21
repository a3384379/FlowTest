import asyncio
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.domain.runtime_profiles import RuntimeProfile

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
    if settings.runtime_profile is RuntimeProfile.STANDALONE:
        await asyncio.to_thread(_ensure_local_storage)
        return
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
    if settings.runtime_profile is RuntimeProfile.STANDALONE:
        await asyncio.to_thread(_check_local_storage)
        return
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


class LocalObjectStorage(ObjectStorage):
    """Filesystem-backed object storage used by the Standalone profile."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or _local_storage_root()).resolve()

    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._put_sync, key, content, content_type)

    async def get(self, *, key: str) -> StoredObject:
        return await asyncio.to_thread(self._get_sync, key)

    async def delete(self, *, key: str) -> None:
        await asyncio.to_thread(self._delete_sync, key)

    def _put_sync(self, key: str, content: bytes, content_type: str) -> None:
        target = self._path_for_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        metadata = target.with_name(f".{target.name}.content-type")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
            metadata.write_text(
                content_type.strip() or "application/octet-stream", encoding="utf-8"
            )
        finally:
            temporary.unlink(missing_ok=True)

    def _get_sync(self, key: str) -> StoredObject:
        target = self._path_for_key(key)
        content = target.read_bytes()
        metadata = target.with_name(f".{target.name}.content-type")
        content_type = (
            metadata.read_text(encoding="utf-8")
            if metadata.exists()
            else "application/octet-stream"
        )
        return StoredObject(content=content, content_type=content_type)

    def _delete_sync(self, key: str) -> None:
        target = self._path_for_key(key)
        target.unlink(missing_ok=True)
        target.with_name(f".{target.name}.content-type").unlink(missing_ok=True)

    def _path_for_key(self, key: str) -> Path:
        normalized = PurePosixPath(key.replace("\\", "/"))
        if not key.strip() or normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Object key must be a relative path")
        candidate = (self._root / Path(*normalized.parts)).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as error:
            raise ValueError("Object key escapes storage root") from error
        return candidate


def create_object_storage() -> ObjectStorage:
    if settings.runtime_profile is RuntimeProfile.STANDALONE:
        return LocalObjectStorage()
    return ObjectStorage()


def _local_storage_root() -> Path:
    return Path(settings.data_dir).expanduser().resolve() / "artifacts"


def _ensure_local_storage() -> None:
    _local_storage_root().mkdir(parents=True, exist_ok=True)


def _check_local_storage() -> None:
    root = _local_storage_root()
    if not root.is_dir():
        raise FileNotFoundError("Standalone artifact directory does not exist")
    probe = root / ".flowtest-readiness"
    try:
        probe.touch(exist_ok=True)
    finally:
        probe.unlink(missing_ok=True)


object_storage = create_object_storage()
