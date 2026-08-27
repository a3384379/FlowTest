import base64
import hashlib
import json
from pathlib import Path

import pytest

from app.operations.storage_transfer import summarize_remote_storage, validate_local_backup


class _StoragePaginator:
    def paginate(self, *, Bucket: str) -> list[dict[str, object]]:
        assert Bucket == "flowtest-artifacts"
        return [
            {"Contents": [{"Key": "hidden-a", "Size": 7}]},
            {
                "Contents": [
                    {"Key": "hidden-b", "Size": 11},
                    {"Key": "hidden-c", "Size": 13},
                ]
            },
        ]


class _StorageClient:
    def get_paginator(self, name: str) -> _StoragePaginator:
        assert name == "list_objects_v2"
        return _StoragePaginator()


def test_storage_summary_only_returns_aggregate_facts() -> None:
    assert summarize_remote_storage(_StorageClient(), "flowtest-artifacts") == {
        "status": "summarized",
        "objects": 3,
        "total_size_bytes": 31,
    }


def test_validate_local_storage_backup_checks_size_and_hash(tmp_path: Path) -> None:
    content = b"compact-artifact"
    _write_backup(tmp_path, key="reports/compact.html", content=content)

    assert validate_local_backup(tmp_path) == 1

    object_path = next((tmp_path / "objects").iterdir())
    object_path.write_bytes(b"corrupted-artifact")
    with pytest.raises(ValueError, match="size mismatch"):
        validate_local_backup(tmp_path)


def test_validate_local_storage_backup_rejects_manifest_file_substitution(tmp_path: Path) -> None:
    _write_backup(tmp_path, key="reports/compact.html", content=b"compact-artifact")
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["objects"][0]["file"] = "substituted.bin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="file name"):
        validate_local_backup(tmp_path)


def _write_backup(directory: Path, *, key: str, content: bytes) -> None:
    filename = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=") + ".bin"
    objects = directory / "objects"
    objects.mkdir()
    (objects / filename).write_bytes(content)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "objects": [
                    {
                        "key": key,
                        "file": filename,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "content_type": "text/html",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
