#!/usr/bin/env python3
"""Backup, restore, and verify the configured S3 bucket with a versioned hash manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "restore", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--replace", action="store_true")
    arguments = parser.parse_args()
    client = _client()
    bucket = os.getenv("FLOWTEST_S3_BUCKET", "flowtest-artifacts")
    _ensure_bucket(client, bucket)
    if arguments.action == "backup":
        _backup(client, bucket, arguments.directory)
    elif arguments.action == "restore":
        _restore(client, bucket, arguments.directory, replace=arguments.replace)
    else:
        _verify(client, bucket, arguments.directory)


def _client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("FLOWTEST_S3_ENDPOINT_URL", "http://localhost:9000"),
        aws_access_key_id=os.getenv("FLOWTEST_S3_ACCESS_KEY", "flowtest"),
        aws_secret_access_key=os.getenv("FLOWTEST_S3_SECRET_KEY", "flowtest-local-secret"),
        region_name="us-east-1",
    )


def _ensure_bucket(client: Any, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)


def _backup(client: Any, bucket: str, directory: Path) -> None:
    objects_dir = directory / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for summary in page.get("Contents", []):
            key = str(summary["Key"])
            response = client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read()
            filename = _encoded_key(key)
            (objects_dir / filename).write_bytes(content)
            manifest.append(
                {
                    "key": key,
                    "file": filename,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content_type": str(response.get("ContentType", "application/octet-stream")),
                }
            )
    manifest.sort(key=lambda item: str(item["key"]))
    (directory / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "objects": manifest}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"status": "backed_up", "objects": len(manifest)}))


def _restore(client: Any, bucket: str, directory: Path, *, replace: bool) -> None:
    manifest = _manifest(directory)
    if replace:
        _empty_bucket(client, bucket)
    for item in manifest:
        content = _verified_content(directory, item)
        client.put_object(
            Bucket=bucket,
            Key=item["key"],
            Body=content,
            ContentType=item["content_type"],
        )
    print(json.dumps({"status": "restored", "objects": len(manifest)}))


def _verify(client: Any, bucket: str, directory: Path) -> None:
    manifest = _manifest(directory)
    expected = {item["key"]: item for item in manifest}
    actual = _remote_keys(client, bucket)
    if actual != set(expected):
        raise RuntimeError("restored object keys differ from the backup manifest")
    for key, item in expected.items():
        content = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise RuntimeError(f"restored object hash mismatch: {key}")
    print(json.dumps({"status": "verified", "objects": len(manifest)}))


def _manifest(directory: Path) -> list[dict[str, str]]:
    document = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("objects"), list):
        raise ValueError("unsupported storage backup manifest")
    required = {"key", "file", "size", "sha256", "content_type"}
    result: list[dict[str, str]] = []
    for raw_item in document["objects"]:
        if not isinstance(raw_item, dict) or not required.issubset(raw_item):
            raise ValueError("invalid storage backup entry")
        result.append({key: str(raw_item[key]) for key in required})
    return result


def _verified_content(directory: Path, item: dict[str, str]) -> bytes:
    filename = item["file"]
    if filename != _encoded_key(item["key"]):
        raise ValueError("storage backup file name does not match its object key")
    content = (directory / "objects" / filename).read_bytes()
    if len(content) != int(item["size"]):
        raise ValueError(f"storage backup size mismatch: {item['key']}")
    if hashlib.sha256(content).hexdigest() != item["sha256"]:
        raise ValueError(f"storage backup hash mismatch: {item['key']}")
    return content


def _empty_bucket(client: Any, bucket: str) -> None:
    keys = _remote_keys(client, bucket)
    for offset in range(0, len(keys), 1000):
        batch = sorted(keys)[offset : offset + 1000]
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )


def _remote_keys(client: Any, bucket: str) -> set[str]:
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        keys.update(str(item["Key"]) for item in page.get("Contents", []))
    return keys


def _encoded_key(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=") + ".bin"


if __name__ == "__main__":
    main()
