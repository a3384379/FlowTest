"""Transfer durable Standalone data into an empty Compact installation.

The Standalone database is SQLite while Compact uses PostgreSQL, so copying the
SQLite file is not a valid migration.  This module writes a versioned, portable
row bundle and imports it through the checked-in SQLAlchemy metadata.  Runtime
state (sessions, retry queues and runner leases) is deliberately excluded.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from graphlib import CycleError, TopologicalSorter
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import (
    Date,
    DateTime,
    Numeric,
    Table,
    Time,
    Uuid,
    and_,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.models import Base

TRANSFER_SCHEMA_VERSION = "standalone-compact-transfer-v1"
STANDALONE_SCHEMA_REVISION = "20260823_0043"
TRANSFER_DATA_CLASSIFICATION: dict[str, list[str]] = {
    "portable": [
        "durable_domain_records",
        "audit_records",
        "artifact_objects",
        "encrypted_payloads",
    ],
    "reference_only": ["secret_references", "encryption_key_references"],
    "hashed_only": ["password_hashes", "service_account_token_hashes"],
    "excluded": [
        "env_file",
        "logs",
        "encryption_key_material",
        "plaintext_secret_values",
        "runner_runtime_state",
    ],
}

# These rows are process state, one-time authentication state, or unsupported
# Standalone features.  They must not be replayed into Compact as if they were
# durable business data.
EXCLUDED_TABLE_REASONS: dict[str, str] = {
    "environment_instances": "环境实验室实例属于临时运行状态",
    "idempotency_records": "API 幂等窗口属于临时运行状态",
    "notification_deliveries": "通知重试队列属于临时运行状态",
    "oidc_login_transactions": "OIDC 登录事务属于一次性认证状态",
    "refresh_sessions": "登录会话必须在目标环境重新建立",
    "runner_events": "Runner 事件属于 Compact/Runner Fabric 运行状态",
    "runner_leases": "Runner 租约属于临时运行状态",
    "runner_registration_tokens": "Runner 注册令牌属于安全敏感临时状态",
    "runner_tasks": "Runner 任务属于 Compact/Runner Fabric 运行状态",
}
_TYPE_TAG = "__flowtest_transfer_type__"
_MAX_ROWS_PER_INSERT = 500
_MISSING = object()


class TransferError(RuntimeError):
    """Raised when a transfer bundle is unsafe or incompatible."""


def main() -> None:
    parser = argparse.ArgumentParser(description="FlowTest Standalone→Compact data transfer")
    subparsers = parser.add_subparsers(dest="action", required=True)

    export_parser = subparsers.add_parser("export", help="从 Standalone 数据目录导出传输包")
    export_parser.add_argument("--source-data", required=True, type=Path)
    export_parser.add_argument("--output", required=True, type=Path)

    validate_parser = subparsers.add_parser("validate", help="校验传输包")
    validate_parser.add_argument("bundle", type=Path)

    import_parser = subparsers.add_parser("import", help="导入到已迁移且为空的 Compact 数据库")
    import_parser.add_argument("bundle", type=Path)
    import_parser.add_argument("--database-url", default="")

    arguments = parser.parse_args()
    if arguments.action == "export":
        summary = asyncio.run(export_bundle(arguments.source_data, arguments.output))
    elif arguments.action == "validate":
        summary = validate_bundle(arguments.bundle)
    else:
        summary = asyncio.run(import_bundle(arguments.bundle, arguments.database_url))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


async def export_bundle(source_data: Path, output: Path) -> dict[str, Any]:
    """Export durable SQLite rows and local artifacts into a new directory."""

    source_root = _require_directory(source_data, "Standalone data directory")
    database_path = _require_regular_file(source_root / "flowtest.db", "Standalone SQLite database")
    artifacts_root = source_root / "artifacts"
    if artifacts_root.is_symlink() or (artifacts_root.exists() and not artifacts_root.is_dir()):
        raise TransferError("Standalone artifact path must be a directory")
    output_root = _new_output_directory(output)
    database_root = output_root / "database"
    bundle_artifacts_root = output_root / "artifacts"
    database_root.mkdir()
    bundle_artifacts_root.mkdir()

    database_url = _sqlite_url(database_path)
    engine = create_async_engine(database_url, connect_args={"check_same_thread": False})
    try:
        async with engine.connect() as connection:
            await connection.execute(text("PRAGMA query_only = ON"))
            await _validate_source_schema(connection)
            rows_by_table, table_entries, excluded_entries = await _export_rows(
                connection, database_root
            )
            artifact_entries = _export_artifacts(
                bundle_artifacts_root,
                artifacts_root,
                rows_by_table.get("artifacts", []),
            )
    except Exception:
        shutil.rmtree(output_root, ignore_errors=True)
        raise
    finally:
        await engine.dispose()

    manifest = {
        "schema_version": TRANSFER_SCHEMA_VERSION,
        "profile": "standalone",
        "source_schema_revision": STANDALONE_SCHEMA_REVISION,
        "target_schema_revision": STANDALONE_SCHEMA_REVISION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "database": {"tables": table_entries, "excluded_tables": excluded_entries},
        "artifacts": {"objects": artifact_entries},
        "security": {
            "env_file": "excluded",
            "logs": "excluded",
            "data_encryption_key": "excluded",
            "passwords": "password_hashes_only",
            "ciphertexts": "preserved",
            "requires_same_data_encryption_key": True,
            "data_classification": TRANSFER_DATA_CLASSIFICATION,
        },
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _summary(manifest)


def validate_bundle(bundle: Path) -> dict[str, Any]:
    """Validate all manifest, row, referential and artifact integrity rules."""

    payload = _load_bundle(bundle)
    return _summary(payload.manifest, validated_rows=payload.row_count)


async def import_bundle(bundle: Path, database_url: str = "") -> dict[str, Any]:
    """Import a validated bundle into an empty, migrated Compact database."""

    payload = _load_bundle(bundle)
    target_url = database_url.strip() or os.getenv("FLOWTEST_DATABASE_URL", "").strip()
    if not target_url:
        raise TransferError("必须通过 --database-url 或 FLOWTEST_DATABASE_URL 指定 Compact 数据库")
    engine = create_async_engine(target_url, pool_pre_ping=True)
    uploaded_keys: list[str] = []
    try:
        await _validate_target_database(engine, payload)
        uploaded_keys = await _upload_artifacts(payload.manifest, payload.bundle)
        try:
            await _import_rows(engine, payload)
        except Exception:
            await _delete_uploaded_keys(uploaded_keys)
            raise
    finally:
        await engine.dispose()
    return _summary(payload.manifest, imported_rows=payload.row_count)


async def _validate_source_schema(connection: AsyncConnection) -> None:
    table_names = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    required = set(Base.metadata.tables) | {"alembic_version", "flowtest_standalone_meta"}
    missing = sorted(required - table_names)
    if missing:
        raise TransferError(f"Standalone 数据库缺少表: {', '.join(missing)}")
    revision = await connection.scalar(
        text("SELECT value FROM flowtest_standalone_meta WHERE key = 'schema_baseline'")
    )
    if str(revision) != STANDALONE_SCHEMA_REVISION:
        raise TransferError(
            f"Standalone Schema 基线不匹配: 需要 {STANDALONE_SCHEMA_REVISION}, 实际 {revision!r}"
        )
    alembic_revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    if str(alembic_revision) != STANDALONE_SCHEMA_REVISION:
        raise TransferError(
            "Standalone Alembic revision 不匹配: "
            f"需要 {STANDALONE_SCHEMA_REVISION}, 实际 {alembic_revision!r}"
        )


async def _export_rows(
    connection: AsyncConnection, database_root: Path
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    table_entries: list[dict[str, Any]] = []
    excluded_entries: list[dict[str, Any]] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        count = int(await connection.scalar(select(func.count()).select_from(table)) or 0)
        reason = EXCLUDED_TABLE_REASONS.get(table.name)
        if reason is not None:
            excluded_entries.append({"name": table.name, "rows": count, "reason": reason})
            continue
        result = await connection.execute(select(table).order_by(*tuple(table.primary_key.columns)))
        rows = [
            {str(column_name): _encode_value(value) for column_name, value in row._mapping.items()}
            for row in result
        ]
        file_name = f"database/{table.name}.jsonl"
        _write_jsonl(database_root / f"{table.name}.jsonl", rows)
        rows_by_table[table.name] = rows
        table_entries.append({"name": table.name, "file": file_name, "rows": len(rows)})
    _validate_rows_and_references(rows_by_table)
    return rows_by_table, table_entries, excluded_entries


def _export_artifacts(
    bundle_root: Path,
    source_root: Path,
    artifact_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not artifact_rows:
        return entries
    source_root = source_root.resolve()
    for row in artifact_rows:
        key = str(row.get("object_key", ""))
        source_file = _local_object_path(source_root, key)
        if not source_file.is_file() or source_file.is_symlink():
            raise TransferError(f"缺少 Artifact 内容: {key}")
        content = source_file.read_bytes()
        expected_size = int(row.get("size_bytes", -1))
        expected_hash = str(row.get("sha256", ""))
        actual_hash = hashlib.sha256(content).hexdigest()
        if len(content) != expected_size or actual_hash != expected_hash:
            raise TransferError(f"Artifact 校验失败: {key}")
        file_name = f"artifacts/{_encoded_key(key)}"
        target = bundle_root / _encoded_key(key)
        target.write_bytes(content)
        content_type = str(row.get("content_type", "application/octet-stream"))
        entries.append(
            {
                "key": key,
                "file": file_name,
                "size": len(content),
                "sha256": actual_hash,
                "content_type": content_type,
            }
        )
    entries.sort(key=lambda item: str(item["key"]))
    return entries


def _load_bundle(bundle: Path) -> BundlePayload:
    root = _require_directory(bundle, "transfer bundle")
    manifest = _read_manifest(root)
    rows_by_table, row_count = _load_database_rows(root, manifest)
    _validate_rows_and_references(rows_by_table)
    artifact_objects = _load_artifact_rows(root, manifest, rows_by_table)
    return BundlePayload(
        bundle=root,
        manifest=manifest,
        rows_by_table=rows_by_table,
        artifacts=artifact_objects,
        row_count=row_count,
    )


def _read_manifest(root: Path) -> dict[str, Any]:
    manifest_path = _require_regular_file(root / "manifest.json", "transfer manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TransferError("无法读取 transfer manifest") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != TRANSFER_SCHEMA_VERSION:
        raise TransferError("不支持的 Standalone→Compact transfer manifest")
    if manifest.get("profile") != "standalone":
        raise TransferError("transfer manifest 的 profile 不是 standalone")
    if manifest.get("source_schema_revision") != STANDALONE_SCHEMA_REVISION:
        raise TransferError("transfer manifest 的 source Schema revision 不匹配")
    if manifest.get("target_schema_revision") != STANDALONE_SCHEMA_REVISION:
        raise TransferError("transfer manifest 的 target Schema revision 不匹配")
    security = manifest.get("security")
    if not isinstance(security, dict) or security.get("env_file") != "excluded":
        raise TransferError("transfer manifest 未声明排除 .env")
    _validate_data_classification(security.get("data_classification"))
    database = manifest.get("database")
    if not isinstance(database, dict):
        raise TransferError("transfer manifest 缺少 database")
    if not isinstance(database.get("tables"), list) or not isinstance(
        database.get("excluded_tables"), list
    ):
        raise TransferError("transfer manifest 的 database 格式无效")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get("objects"), list):
        raise TransferError("transfer manifest 的 artifacts 格式无效")
    return manifest


def _validate_data_classification(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != set(TRANSFER_DATA_CLASSIFICATION):
        raise TransferError("transfer manifest 的数据分类格式无效")
    if any(
        not isinstance(values, list) or not all(isinstance(item, str) for item in values)
        for values in value.values()
    ):
        raise TransferError("transfer manifest 的数据分类格式无效")


def _load_database_rows(
    root: Path, manifest: Mapping[str, Any]
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    database = manifest["database"]
    table_documents = database["tables"]
    expected_tables = set(Base.metadata.tables) - set(EXCLUDED_TABLE_REASONS)
    actual_tables: set[str] = set()
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    row_count = 0
    for raw_entry in table_documents:
        entry = _mapping_entry(raw_entry, {"name", "file", "rows"}, "database table")
        name = str(entry["name"])
        if name not in expected_tables or name in actual_tables:
            raise TransferError(f"transfer manifest 中存在重复或未知表: {name}")
        actual_tables.add(name)
        table = Base.metadata.tables[name]
        file_path = _bundle_file(root, str(entry["file"]), "database")
        rows = _read_jsonl(file_path, table)
        if len(rows) != int(entry["rows"]):
            raise TransferError(f"表 {name} 行数不匹配")
        rows_by_table[name] = rows
        row_count += len(rows)
    if actual_tables != expected_tables:
        missing = sorted(expected_tables - actual_tables)
        raise TransferError(f"transfer manifest 缺少表: {', '.join(missing)}")
    _validate_excluded_entries(database["excluded_tables"])
    return rows_by_table, row_count


def _load_artifact_rows(
    root: Path,
    manifest: Mapping[str, Any],
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, str]]:
    artifacts = manifest["artifacts"]
    return _validate_artifacts(root, artifacts["objects"], rows_by_table["artifacts"])


def _validate_excluded_entries(entries: Sequence[Any]) -> None:
    actual = {
        str(_mapping_entry(item, {"name", "rows", "reason"}, "excluded table")["name"])
        for item in entries
    }
    if actual != set(EXCLUDED_TABLE_REASONS):
        raise TransferError("transfer manifest 的 excluded_tables 不完整")
    for item in entries:
        entry = _mapping_entry(item, {"name", "rows", "reason"}, "excluded table")
        name = str(entry["name"])
        if entry["reason"] != EXCLUDED_TABLE_REASONS[name]:
            raise TransferError(f"excluded table {name} 的原因不匹配")
        if int(entry["rows"]) < 0:
            raise TransferError(f"excluded table {name} 的行数无效")


def _validate_artifacts(
    bundle: Path,
    raw_objects: Sequence[Any],
    artifact_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    expected_by_key: dict[str, Mapping[str, Any]] = {}
    for row in artifact_rows:
        key = str(row.get("object_key", ""))
        if not key or key in expected_by_key:
            raise TransferError("Artifact 表包含空或重复 object_key")
        expected_by_key[key] = row
    actual_by_key: dict[str, dict[str, str]] = {}
    for raw_item in raw_objects:
        entry = _mapping_entry(
            raw_item, {"key", "file", "size", "sha256", "content_type"}, "artifact"
        )
        key = str(entry["key"])
        if key in actual_by_key or key not in expected_by_key:
            raise TransferError(f"Artifact manifest 与数据库不匹配: {key}")
        file_path = _bundle_file(bundle, str(entry["file"]), "artifacts")
        content = file_path.read_bytes()
        if len(content) != int(entry["size"]):
            raise TransferError(f"传输包 Artifact 大小不匹配: {key}")
        digest = hashlib.sha256(content).hexdigest()
        if digest != str(entry["sha256"]):
            raise TransferError(f"传输包 Artifact SHA-256 不匹配: {key}")
        row = expected_by_key[key]
        if int(row.get("size_bytes", -1)) != int(entry["size"]):
            raise TransferError(f"Artifact 数据库大小不匹配: {key}")
        if str(row.get("sha256", "")) != str(entry["sha256"]):
            raise TransferError(f"Artifact 数据库 SHA-256 不匹配: {key}")
        actual_by_key[key] = {key_name: str(entry[key_name]) for key_name in entry}
    if set(actual_by_key) != set(expected_by_key):
        missing = sorted(set(expected_by_key) - set(actual_by_key))
        raise TransferError(f"传输包缺少 Artifact: {', '.join(missing)}")
    return [actual_by_key[key] for key in sorted(actual_by_key)]


def _validate_rows_and_references(rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    primary_keys = _collect_primary_keys(rows_by_table)
    for name, rows in rows_by_table.items():
        _validate_table_references(name, rows, primary_keys)


def _collect_primary_keys(
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, set[str]]:
    primary_keys: dict[str, set[str]] = {}
    for name, rows in rows_by_table.items():
        table = Base.metadata.tables[name]
        keys: set[str] = set()
        for row in rows:
            key = _row_primary_key(table, row)
            if key in keys:
                raise TransferError(f"表 {name} 存在重复主键")
            keys.add(key)
        primary_keys[name] = keys
    return primary_keys


def _validate_table_references(
    name: str, rows: Sequence[Mapping[str, Any]], primary_keys: Mapping[str, set[str]]
) -> None:
    table = Base.metadata.tables[name]
    for row in rows:
        for foreign_key in table.foreign_keys:
            value = row.get(foreign_key.parent.name)
            if value is None:
                continue
            target_name = foreign_key.column.table.name
            if target_name in EXCLUDED_TABLE_REASONS:
                raise TransferError(
                    f"表 {name} 的 {foreign_key.parent.name} 引用了被排除表 {target_name}"
                )
            target_table = Base.metadata.tables[target_name]
            if len(tuple(target_table.primary_key.columns)) != 1:
                continue
            if _canonical_value(value) not in primary_keys.get(target_name, set()):
                raise TransferError(
                    f"表 {name} 的 {foreign_key.parent.name} 引用了不存在的 {target_name}"
                )


async def _validate_target_database(engine: AsyncEngine, payload: BundlePayload) -> None:
    async with engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        missing = sorted(set(Base.metadata.tables) - table_names)
        if missing:
            raise TransferError(f"Compact 数据库缺少表: {', '.join(missing)}")
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if str(revision) != STANDALONE_SCHEMA_REVISION:
            raise TransferError(
                "Compact 必须先完成 Alembic upgrade head, "
                f"需要 {STANDALONE_SCHEMA_REVISION}, 实际 {revision!r}"
            )
        non_empty: list[str] = []
        for name in payload.rows_by_table:
            table = Base.metadata.tables[name]
            count = int(await connection.scalar(select(func.count()).select_from(table)) or 0)
            if count:
                non_empty.append(f"{name}={count}")
        if non_empty:
            raise TransferError(
                "Compact 目标数据库必须为空, 请先完成新环境初始化或使用独立数据库: "
                + ", ".join(non_empty)
            )


async def _import_rows(engine: AsyncEngine, payload: BundlePayload) -> None:
    order = _import_order(payload.rows_by_table)
    async with engine.begin() as connection:
        pending_updates: list[tuple[Table, tuple[Any, ...], str, Any]] = []
        for table_name in order:
            table = Base.metadata.tables[table_name]
            rows: list[dict[str, Any]] = []
            self_columns = _self_reference_columns(table)
            for raw_row in payload.rows_by_table[table_name]:
                row = _decode_row(table, raw_row)
                primary_key = tuple(row[column.name] for column in table.primary_key.columns)
                for column in self_columns:
                    value = row.get(column.name)
                    if value is None:
                        continue
                    if column.nullable is False:
                        raise TransferError(f"表 {table.name} 的自引用列 {column.name} 必须可为空")
                    pending_updates.append((table, primary_key, column.name, value))
                    row[column.name] = None
                rows.append(row)
            for offset in range(0, len(rows), _MAX_ROWS_PER_INSERT):
                chunk = rows[offset : offset + _MAX_ROWS_PER_INSERT]
                if chunk:
                    await connection.execute(table.insert(), chunk)
        for table, primary_key, column_name, value in pending_updates:
            predicate = and_(
                *tuple(
                    column == key
                    for column, key in zip(table.primary_key.columns, primary_key, strict=True)
                )
            )
            await connection.execute(update(table).where(predicate).values({column_name: value}))


def _import_order(rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]]) -> tuple[str, ...]:
    names = set(rows_by_table)
    graph = {
        name: {
            foreign_key.column.table.name
            for foreign_key in Base.metadata.tables[name].foreign_keys
            if foreign_key.column.table.name in names and foreign_key.column.table.name != name
        }
        for name in names
    }
    try:
        return tuple(TopologicalSorter(graph).static_order())
    except CycleError as error:
        raise TransferError("transfer 数据表存在非自引用循环, 拒绝导入") from error


async def _upload_artifacts(manifest: Mapping[str, Any], bundle: Path) -> list[str]:
    raw_artifacts = manifest["artifacts"]["objects"]
    if not raw_artifacts:
        return []
    client = _s3_client()
    bucket = os.getenv("FLOWTEST_S3_BUCKET", "flowtest-artifacts")
    await asyncio.to_thread(_ensure_bucket, client, bucket)
    uploaded: list[str] = []
    try:
        for raw_item in raw_artifacts:
            entry = _mapping_entry(
                raw_item, {"key", "file", "size", "sha256", "content_type"}, "artifact"
            )
            key = str(entry["key"])
            content = (_bundle_file(bundle, str(entry["file"]), "artifacts")).read_bytes()
            exists = await asyncio.to_thread(_remote_matches, client, bucket, key, entry)
            if exists:
                continue
            await asyncio.to_thread(
                client.put_object,
                Bucket=bucket,
                Key=key,
                Body=content,
                ContentType=str(entry["content_type"]),
            )
            uploaded.append(key)
    except Exception:
        await _delete_uploaded_keys(uploaded, client=client, bucket=bucket)
        raise
    return uploaded


async def _delete_uploaded_keys(
    keys: Sequence[str], client: Any | None = None, bucket: str | None = None
) -> None:
    if not keys:
        return
    actual_client = client or _s3_client()
    actual_bucket = bucket or os.getenv("FLOWTEST_S3_BUCKET", "flowtest-artifacts")
    await asyncio.to_thread(
        actual_client.delete_objects,
        Bucket=actual_bucket,
        Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
    )


def _remote_matches(client: Any, bucket: str, key: str, entry: Mapping[str, Any]) -> bool:
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}:
            return False
        raise
    content = response["Body"].read()
    if len(content) != int(entry["size"]) or hashlib.sha256(content).hexdigest() != str(
        entry["sha256"]
    ):
        raise TransferError(f"Compact 对象存储已有同名但内容不同的 Artifact: {key}")
    return True


def _ensure_bucket(client: Any, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)


def _s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("FLOWTEST_S3_ENDPOINT_URL", "http://localhost:9000"),
        aws_access_key_id=os.getenv("FLOWTEST_S3_ACCESS_KEY", "flowtest"),
        aws_secret_access_key=os.getenv("FLOWTEST_S3_SECRET_KEY", "flowtest-local-secret"),
        region_name="us-east-1",
    )


def _read_jsonl(path: Path, table: Table) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise TransferError(f"{path} 第 {line_number} 行为空")
                try:
                    raw_row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise TransferError(f"无法解析 {path} 第 {line_number} 行") from error
                if not isinstance(raw_row, dict):
                    raise TransferError(f"{path} 第 {line_number} 行不是对象")
                known_columns = {column.name for column in table.columns}
                if set(raw_row) != known_columns:
                    raise TransferError(f"{table.name} 第 {line_number} 行列集合不匹配")
                for column in table.primary_key.columns:
                    if raw_row.get(column.name) is None:
                        raise TransferError(f"{table.name} 第 {line_number} 行缺少主键")
                rows.append(raw_row)
    except OSError as error:
        raise TransferError(f"无法读取数据库文件: {path}") from error
    return rows


def _decode_row(table: Table, row: Mapping[str, Any]) -> dict[str, Any]:
    return {column.name: _decode_value(row[column.name], column) for column in table.columns}


def _decode_value(value: Any, column: Any) -> Any:
    decoded = _decode_recursive(value)
    if decoded is None:
        return None
    column_type = column.type
    if isinstance(column_type, Uuid) and isinstance(decoded, str):
        return UUID(decoded)
    if isinstance(column_type, DateTime) and isinstance(decoded, str):
        parsed = datetime.fromisoformat(decoded)
        if column_type.timezone and parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    if (
        isinstance(column_type, Date)
        and not isinstance(column_type, DateTime)
        and isinstance(decoded, str)
    ):
        return date.fromisoformat(decoded)
    if isinstance(column_type, Time) and isinstance(decoded, str):
        return time.fromisoformat(decoded)
    if isinstance(column_type, Numeric) and isinstance(decoded, str):
        return Decimal(decoded)
    return decoded


def _decode_recursive(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_recursive(item) for item in value]
    if not isinstance(value, dict):
        return value
    tag = value.get(_TYPE_TAG)
    tagged_value = set(value) == {_TYPE_TAG, "value"}
    if tagged_value and tag == "bytes":
        return base64.b64decode(str(value["value"]).encode("ascii"), validate=True)
    if tagged_value and tag == "datetime":
        return datetime.fromisoformat(str(value["value"]))
    if tagged_value and tag == "date":
        return date.fromisoformat(str(value["value"]))
    if tagged_value and tag == "time":
        return time.fromisoformat(str(value["value"]))
    if tagged_value and tag == "decimal":
        return Decimal(str(value["value"]))
    return {str(key): _decode_recursive(item) for key, item in value.items()}


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    tagged = _encode_special_value(value)
    if tagged is not _MISSING:
        return tagged
    if isinstance(value, Mapping):
        return {str(key): _encode_value(item) for key, item in value.items()}
    if isinstance(value, Iterable):
        return [_encode_value(item) for item in value]
    raise TransferError(f"不支持的数据库值类型: {type(value).__name__}")


def _encode_special_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {_TYPE_TAG: "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {_TYPE_TAG: "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_TAG: "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {_TYPE_TAG: "time", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {_TYPE_TAG: "decimal", "value": str(value)}
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _encode_value(value.value)
    return _MISSING


def _row_primary_key(table: Table, row: Mapping[str, Any]) -> str:
    values = [row.get(column.name) for column in table.primary_key.columns]
    if any(value is None for value in values):
        raise TransferError(f"表 {table.name} 存在空主键")
    return _canonical_value(values[0] if len(values) == 1 else values)


def _canonical_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _self_reference_columns(table: Table) -> tuple[Any, ...]:
    return tuple(
        foreign_key.parent
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == table.name
    )


def _mapping_entry(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise TransferError(f"{label} manifest entry 格式无效")
    return {str(key): value[key] for key in keys}


def _bundle_file(root: Path, value: str, expected_prefix: str) -> Path:
    normalized = PurePosixPath(value)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise TransferError("transfer manifest 文件路径非法")
    if not normalized.parts or normalized.parts[0] != expected_prefix:
        raise TransferError("transfer manifest 文件路径前缀非法")
    candidate = root / Path(*normalized.parts)
    if any(part.is_symlink() for part in _path_parts(root, normalized.parts)):
        raise TransferError("transfer manifest 不允许符号链接文件")
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise TransferError("transfer manifest 文件路径越界") from error
    if not candidate.is_file() or candidate.is_symlink():
        raise TransferError(f"transfer manifest 文件不存在: {value}")
    return candidate


def _path_parts(root: Path, parts: Sequence[str]) -> tuple[Path, ...]:
    current = root
    result: list[Path] = []
    for part in parts:
        current = current / part
        result.append(current)
    return tuple(result)


def _local_object_path(root: Path, key: str) -> Path:
    normalized = PurePosixPath(key.replace("\\", "/"))
    if not key.strip() or normalized.is_absolute() or ".." in normalized.parts:
        raise TransferError("Artifact object_key 非法")
    raw_candidate = root / Path(*normalized.parts)
    if any(part.is_symlink() for part in _path_parts(root, normalized.parts)):
        raise TransferError("Artifact object_key 不允许符号链接")
    candidate = raw_candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise TransferError("Artifact object_key 越界") from error
    return candidate


def _encoded_key(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=") + ".bin"


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def _require_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise TransferError(f"{label} 不允许使用符号链接: {path}")
    resolved = expanded.resolve()
    if not resolved.is_dir():
        raise TransferError(f"{label} 不是普通目录: {path}")
    return resolved


def _require_regular_file(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise TransferError(f"{label} 不允许使用符号链接: {path}")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise TransferError(f"{label} 不是普通文件: {path}")
    return resolved


def _new_output_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() or resolved.is_symlink():
        raise TransferError(f"拒绝覆盖已有 transfer bundle: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.mkdir(mode=0o700)
    return resolved


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _summary(
    manifest: Mapping[str, Any],
    *,
    validated_rows: int | None = None,
    imported_rows: int | None = None,
) -> dict[str, Any]:
    database = manifest["database"]
    artifacts = manifest["artifacts"]["objects"]
    summary: dict[str, Any] = {
        "status": "validated" if validated_rows is not None else "exported",
        "schema_version": manifest["schema_version"],
        "tables": len(database["tables"]),
        "rows": sum(int(item["rows"]) for item in database["tables"]),
        "excluded_tables": len(database["excluded_tables"]),
        "artifacts": len(artifacts),
    }
    if validated_rows is not None:
        summary["rows"] = validated_rows
        summary["status"] = "validated"
    if imported_rows is not None:
        summary["rows"] = imported_rows
        summary["status"] = "imported"
    return summary


class BundlePayload:
    def __init__(
        self,
        *,
        bundle: Path,
        manifest: dict[str, Any],
        rows_by_table: dict[str, list[dict[str, Any]]],
        artifacts: list[dict[str, str]],
        row_count: int,
    ) -> None:
        self.bundle = bundle
        self.manifest = manifest
        self.rows_by_table = rows_by_table
        self.artifacts = artifacts
        self.row_count = row_count


if __name__ == "__main__":
    main()
