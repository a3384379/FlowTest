import hashlib
import io
import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import Column, Date, Numeric, Time, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.domain.access import ProjectRole
from app.models import Base
from app.operations import standalone_transfer as transfer
from app.operations.standalone_transfer import (
    STANDALONE_SCHEMA_REVISION,
    TransferError,
    _bundle_file,
    _decode_recursive,
    _decode_value,
    _delete_uploaded_keys,
    _encode_value,
    _ensure_bucket,
    _load_bundle,
    _local_object_path,
    _mapping_entry,
    _new_output_directory,
    _remote_matches,
    _require_directory,
    _require_regular_file,
    _row_primary_key,
    _s3_client,
    _upload_artifacts,
    _validate_excluded_entries,
    _validate_table_references,
    export_bundle,
    import_bundle,
    validate_bundle,
)


async def _create_database(path: Path, *, target: bool = False) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        await connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": STANDALONE_SCHEMA_REVISION},
        )
        if not target:
            await connection.execute(
                text(
                    "CREATE TABLE flowtest_standalone_meta "
                    "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO flowtest_standalone_meta (key, value) "
                    "VALUES ('schema_baseline', :revision)"
                ),
                {"revision": STANDALONE_SCHEMA_REVISION},
            )
    return engine


async def _seed_source(data_root: Path, *, include_artifact: bool = True) -> dict[str, UUID | str]:
    data_root.mkdir()
    artifacts_root = data_root / "artifacts"
    artifacts_root.mkdir()
    engine = await _create_database(data_root / "flowtest.db")
    user_id = uuid4()
    project_id = uuid4()
    folder_id = uuid4()
    child_folder_id = uuid4()
    secret_id = uuid4()
    artifact_id = uuid4()
    test_design_id = uuid4()
    artifact_key = f"projects/{project_id}/artifacts/{artifact_id}"
    content = b"standalone-transfer-test"
    async with engine.begin() as connection:
        await connection.execute(
            Base.metadata.tables["users"]
            .insert()
            .values(
                id=user_id,
                email="transfer@example.com",
                display_name="Transfer User",
                password_hash="$argon2id$v=19$m=65536$test",
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await connection.execute(
            Base.metadata.tables["projects"]
            .insert()
            .values(
                id=project_id,
                name="Transfer Project",
                description="",
                variables={"key": "value"},
                headers={},
                outbound_allowed_hosts=[],
                outbound_allowed_private_cidrs=[],
                retention_days=90,
                execution_concurrency_limit=20,
                queued_run_limit=1000,
                ai_sample_sharing_enabled=False,
                created_by_id=user_id,
            )
        )
        await connection.execute(
            Base.metadata.tables["folders"]
            .insert()
            .values(
                id=folder_id,
                project_id=project_id,
                parent_id=None,
                name="Root",
                created_by_id=user_id,
            )
        )
        await connection.execute(
            Base.metadata.tables["folders"]
            .insert()
            .values(
                id=child_folder_id,
                project_id=project_id,
                parent_id=folder_id,
                name="Child",
                created_by_id=user_id,
            )
        )
        await connection.execute(
            Base.metadata.tables["secrets"]
            .insert()
            .values(
                id=secret_id,
                project_id=project_id,
                environment_id=None,
                name="encrypted",
                ciphertext=b"ciphertext",
                nonce=b"0123456789ab",
                created_by_id=user_id,
            )
        )
        await connection.execute(
            Base.metadata.tables["test_designs"]
            .insert()
            .values(
                id=test_design_id,
                project_id=project_id,
                name="S47 Transfer Design",
                status="approved",
                intent={"key": "orders.create"},
                knowledge_graph={"nodes": [], "edges": []},
                state_model={},
                scenarios=[{"id": "scenario_happy_path", "kind": "happy_path"}],
                oracles=[{"id": "oracle_status", "expected": 200}],
                coverage={"entries": [{"dimension": "endpoint", "covered": True}]},
                evidence_refs=[
                    {
                        "id": "contract-orders",
                        "source_type": "contract",
                        "source_ref": "contract://orders.create",
                        "revision": "s47",
                    }
                ],
                warnings=[],
                confidence=1,
                review_requirements=[],
                test_case_refs=[],
                fingerprint="4" * 64,
                created_by_id=user_id,
                reviewed_by_id=user_id,
                review_note="S47 transfer fixture",
            )
        )
        if include_artifact:
            await connection.execute(
                Base.metadata.tables["artifacts"]
                .insert()
                .values(
                    id=artifact_id,
                    project_id=project_id,
                    object_key=artifact_key,
                    filename="result.txt",
                    content_type="text/plain",
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    purpose="upload",
                    created_by_id=user_id,
                )
            )
    await engine.dispose()
    if include_artifact:
        artifact_path = artifacts_root.joinpath(*artifact_key.split("/"))
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_bytes(content)
    return {
        "user_id": user_id,
        "project_id": project_id,
        "folder_id": folder_id,
        "test_design_id": test_design_id,
        "artifact_key": artifact_key,
    }


@pytest.mark.asyncio
async def test_standalone_transfer_exports_rows_and_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_data = tmp_path / "data"
    identifiers = await _seed_source(source_data)
    bundle = tmp_path / "transfer"

    exported = await export_bundle(source_data, bundle)
    assert exported == {
        "status": "exported",
        "schema_version": "standalone-compact-transfer-v1",
        "tables": 84,
        "rows": 7,
        "excluded_tables": 9,
        "artifacts": 1,
    }
    assert validate_bundle(bundle)["status"] == "validated"
    payload = _load_bundle(bundle)
    assert payload.manifest["security"]["data_classification"] == {
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
    secret = payload.rows_by_table["secrets"][0]
    assert secret["ciphertext"] == {
        "__flowtest_transfer_type__": "bytes",
        "value": "Y2lwaGVydGV4dA==",
    }
    assert identifiers["artifact_key"] in {item["key"] for item in payload.artifacts}
    assert not (bundle / ".env").exists()

    monkeypatch.setattr(sys, "argv", ["standalone_transfer", "validate", str(bundle)])
    transfer.main()
    assert json.loads(capsys.readouterr().out)["status"] == "validated"

    artifact_file = bundle / payload.artifacts[0]["file"]
    artifact_file.write_bytes(b"tampered")
    with pytest.raises(TransferError, match="Artifact"):
        validate_bundle(bundle)


@pytest.mark.asyncio
async def test_standalone_transfer_imports_self_reference_into_empty_database(
    tmp_path: Path,
) -> None:
    source_data = tmp_path / "data"
    identifiers = await _seed_source(source_data, include_artifact=False)
    source_bundle = tmp_path / "transfer"
    await export_bundle(source_data, source_bundle)

    target_engine = await _create_database(tmp_path / "target.db", target=True)
    imported = await import_bundle(source_bundle, f"sqlite+aiosqlite:///{tmp_path / 'target.db'}")
    async with target_engine.connect() as connection:
        project = await connection.scalar(
            select(Base.metadata.tables["projects"].c.name).where(
                Base.metadata.tables["projects"].c.id == identifiers["project_id"]
            )
        )
        secret = await connection.execute(
            select(Base.metadata.tables["secrets"]).where(
                Base.metadata.tables["secrets"].c.project_id == identifiers["project_id"]
            )
        )
        secret_row = secret.one()
        folders = await connection.execute(
            select(
                Base.metadata.tables["folders"].c.name, Base.metadata.tables["folders"].c.parent_id
            )
            .where(Base.metadata.tables["folders"].c.project_id == identifiers["project_id"])
            .order_by(Base.metadata.tables["folders"].c.name)
        )
        folder_rows = folders.all()
        design = (
            await connection.execute(
                select(Base.metadata.tables["test_designs"]).where(
                    Base.metadata.tables["test_designs"].c.id == identifiers["test_design_id"]
                )
            )
        ).one()
    await target_engine.dispose()
    assert imported["status"] == "imported"
    assert project == "Transfer Project"
    assert secret_row.ciphertext == b"ciphertext"
    assert folder_rows[0].parent_id is not None
    assert design.scenarios[0]["kind"] == "happy_path"
    assert design.evidence_refs[0]["source_ref"] == "contract://orders.create"


@pytest.mark.asyncio
async def test_standalone_transfer_rejects_nonempty_target(tmp_path: Path) -> None:
    source_data = tmp_path / "data"
    await _seed_source(source_data, include_artifact=False)
    bundle = tmp_path / "transfer"
    await export_bundle(source_data, bundle)

    target_engine = await _create_database(tmp_path / "target.db", target=True)
    async with target_engine.begin() as connection:
        await connection.execute(
            Base.metadata.tables["users"]
            .insert()
            .values(
                id=uuid4(),
                email="existing@example.com",
                display_name="Existing",
                password_hash="hash",
                is_active=True,
                is_system_admin=False,
                requires_password_change=False,
            )
        )
    with pytest.raises(TransferError, match="必须为空"):
        await import_bundle(bundle, f"sqlite+aiosqlite:///{tmp_path / 'target.db'}")
    await target_engine.dispose()


@pytest.mark.asyncio
async def test_standalone_transfer_requires_target_url_and_head_revision(tmp_path: Path) -> None:
    source_data = tmp_path / "data"
    await _seed_source(source_data, include_artifact=False)
    bundle = tmp_path / "transfer"
    await export_bundle(source_data, bundle)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("FLOWTEST_DATABASE_URL", raising=False)
        with pytest.raises(TransferError, match="DATABASE_URL"):
            await import_bundle(bundle)

    target_path = tmp_path / "target.db"
    target_engine = await _create_database(target_path, target=True)
    async with target_engine.begin() as connection:
        await connection.execute(text("UPDATE alembic_version SET version_num = 'old'"))
    with pytest.raises(TransferError, match="Alembic"):
        await import_bundle(bundle, f"sqlite+aiosqlite:///{target_path}")
    await target_engine.dispose()


@pytest.mark.asyncio
async def test_standalone_transfer_rejects_source_revision_and_manifest_tampering(
    tmp_path: Path,
) -> None:
    source_data = tmp_path / "data"
    await _seed_source(source_data, include_artifact=False)
    source_engine = create_async_engine(f"sqlite+aiosqlite:///{source_data / 'flowtest.db'}")
    async with source_engine.begin() as connection:
        await connection.execute(
            text("UPDATE flowtest_standalone_meta SET value = 'old' WHERE key = 'schema_baseline'")
        )
    await source_engine.dispose()
    with pytest.raises(TransferError, match="基线"):
        await export_bundle(source_data, tmp_path / "bad-baseline")

    source_engine = create_async_engine(f"sqlite+aiosqlite:///{source_data / 'flowtest.db'}")
    async with source_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE flowtest_standalone_meta SET value = :revision "
                "WHERE key = 'schema_baseline'"
            ),
            {"revision": STANDALONE_SCHEMA_REVISION},
        )
        await connection.execute(text("UPDATE alembic_version SET version_num = 'old'"))
    await source_engine.dispose()
    with pytest.raises(TransferError, match="Alembic"):
        await export_bundle(source_data, tmp_path / "bad-alembic")

    source_engine = create_async_engine(f"sqlite+aiosqlite:///{source_data / 'flowtest.db'}")
    async with source_engine.begin() as connection:
        await connection.execute(
            text("UPDATE alembic_version SET version_num = :revision"),
            {"revision": STANDALONE_SCHEMA_REVISION},
        )
    await source_engine.dispose()
    bundle = tmp_path / "transfer"
    await export_bundle(source_data, bundle)
    manifest_path = bundle / "manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    for key, value, message in (
        ("schema_version", "old", "不支持"),
        ("profile", "compact", "profile"),
        ("target_schema_revision", "old", "target"),
    ):
        tampered = json.loads(json.dumps(original))
        tampered[key] = value
        manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(TransferError, match=message):
            validate_bundle(bundle)

    tampered = json.loads(json.dumps(original))
    tampered["security"]["env_file"] = "included"
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(TransferError, match="env"):
        validate_bundle(bundle)

    tampered["security"]["env_file"] = "excluded"
    tampered["security"]["data_classification"]["excluded"] = "invalid"
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(TransferError, match="数据分类"):
        validate_bundle(bundle)
    manifest_path.write_text(json.dumps(original), encoding="utf-8")


def test_standalone_transfer_value_codec_preserves_sensitive_types() -> None:
    assert _encode_value(b"bytes") == {
        "__flowtest_transfer_type__": "bytes",
        "value": "Ynl0ZXM=",
    }
    assert _encode_value(datetime(2026, 8, 22, 1, 2, 3))["__flowtest_transfer_type__"] == "datetime"
    assert _encode_value(date(2026, 8, 22))["__flowtest_transfer_type__"] == "date"
    assert _encode_value(time(1, 2, 3))["__flowtest_transfer_type__"] == "time"
    assert _encode_value(Decimal("1.20"))["__flowtest_transfer_type__"] == "decimal"
    assert _encode_value(ProjectRole.OWNER) == "owner"
    assert _encode_value({"nested": [Decimal("2.5")]})["nested"][0]["value"] == "2.5"

    assert (
        _decode_recursive({"__flowtest_transfer_type__": "bytes", "value": "Ynl0ZXM="}) == b"bytes"
    )
    assert _decode_recursive(
        {"__flowtest_transfer_type__": "datetime", "value": "2026-08-22T01:02:03"}
    ) == datetime(2026, 8, 22, 1, 2, 3)
    assert _decode_recursive({"__flowtest_transfer_type__": "date", "value": "2026-08-22"}) == date(
        2026, 8, 22
    )
    assert _decode_recursive({"__flowtest_transfer_type__": "time", "value": "01:02:03"}) == time(
        1, 2, 3
    )
    assert _decode_recursive({"__flowtest_transfer_type__": "decimal", "value": "1.20"}) == Decimal(
        "1.20"
    )
    assert _decode_recursive(
        {"__flowtest_transfer_type__": "bytes", "value": "Ynl0ZXM=", "extra": "json"}
    ) == {"__flowtest_transfer_type__": "bytes", "value": "Ynl0ZXM=", "extra": "json"}
    assert _decode_value(str(uuid4()), Base.metadata.tables["users"].c.id).version == 4
    assert _decode_value("2026-08-22T01:02:03", Base.metadata.tables["users"].c.created_at).tzinfo
    assert _decode_value("2026-08-22", Column("d", Date())) == date(2026, 8, 22)
    assert _decode_value("01:02:03", Column("t", Time())) == time(1, 2, 3)
    assert _decode_value("1.20", Column("n", Numeric())) == Decimal("1.20")


def test_standalone_transfer_rejects_unsafe_paths_and_references(tmp_path: Path) -> None:
    with pytest.raises(TransferError):
        _mapping_entry({}, {"name"}, "entry")
    with pytest.raises(TransferError):
        _row_primary_key(Base.metadata.tables["users"], {"id": None})
    with pytest.raises(TransferError):
        _validate_excluded_entries([])
    with pytest.raises(TransferError):
        _validate_excluded_entries(
            [
                {
                    "name": name,
                    "rows": 0,
                    "reason": "wrong" if name == "runner_tasks" else reason,
                }
                for name, reason in transfer.EXCLUDED_TABLE_REASONS.items()
            ]
        )
    with pytest.raises(TransferError):
        _validate_excluded_entries(
            [
                {"name": name, "rows": -1 if name == "runner_tasks" else 0, "reason": reason}
                for name, reason in transfer.EXCLUDED_TABLE_REASONS.items()
            ]
        )
    with pytest.raises(TransferError):
        _validate_table_references(
            "release_decisions", [{"runner_task_id": "missing"}], {"users": set()}
        )
    with pytest.raises(TransferError):
        _validate_table_references(
            "projects", [{"created_by_id": "missing"}], {"users": set(), "projects": set()}
        )

    bundle_root = tmp_path / "bundle"
    (bundle_root / "database").mkdir(parents=True)
    database_file = bundle_root / "database" / "users.jsonl"
    database_file.write_text("{}\n", encoding="utf-8")
    with pytest.raises(TransferError):
        _bundle_file(bundle_root, "/etc/passwd", "database")
    with pytest.raises(TransferError):
        _bundle_file(bundle_root, "artifacts/users.jsonl", "database")
    with pytest.raises(TransferError):
        _bundle_file(bundle_root, "database/../users.jsonl", "database")
    with pytest.raises(TransferError):
        _local_object_path(bundle_root, "")
    with pytest.raises(TransferError):
        _local_object_path(bundle_root, "../outside")
    with pytest.raises(TransferError):
        _require_directory(bundle_root / "missing", "directory")
    with pytest.raises(TransferError):
        _require_regular_file(bundle_root, "file")
    with pytest.raises(TransferError):
        _new_output_directory(bundle_root)
    symlink_target = tmp_path / "target.txt"
    symlink_target.write_text("x", encoding="utf-8")
    symlink_path = tmp_path / "link.txt"
    symlink_path.symlink_to(symlink_target)
    with pytest.raises(TransferError):
        _require_regular_file(symlink_path, "file")


@pytest.mark.asyncio
async def test_standalone_transfer_uploads_and_verifies_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_data = tmp_path / "data"
    await _seed_source(source_data)
    bundle = tmp_path / "transfer"
    await export_bundle(source_data, bundle)
    payload = _load_bundle(bundle)

    class FakeS3:
        def __init__(self) -> None:
            self.bucket_exists = False
            self.objects: dict[str, bytes] = {}

        def head_bucket(self, **_kwargs: object) -> None:
            if not self.bucket_exists:
                raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

        def create_bucket(self, **_kwargs: object) -> None:
            self.bucket_exists = True

        def get_object(self, *, Key: str, **_kwargs: object) -> dict[str, object]:
            if Key not in self.objects:
                raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            return {"Body": io.BytesIO(self.objects[Key])}

        def put_object(self, *, Key: str, Body: bytes, **_kwargs: object) -> None:
            self.objects[Key] = Body

        def delete_objects(self, *, Delete: dict[str, object], **_kwargs: object) -> None:
            for item in Delete["Objects"]:  # type: ignore[index]
                self.objects.pop(str(item["Key"]), None)  # type: ignore[index]

    fake = FakeS3()
    monkeypatch.setenv("FLOWTEST_S3_BUCKET", "test-bucket")
    monkeypatch.setattr(transfer, "_s3_client", lambda: fake)
    uploaded = await _upload_artifacts(payload.manifest, payload.bundle)
    assert uploaded == [payload.artifacts[0]["key"]]
    assert await _upload_artifacts(payload.manifest, payload.bundle) == []
    assert _remote_matches(fake, "test-bucket", payload.artifacts[0]["key"], payload.artifacts[0])
    fake.objects[payload.artifacts[0]["key"]] = b"different"
    with pytest.raises(TransferError, match="同名"):
        _remote_matches(fake, "test-bucket", payload.artifacts[0]["key"], payload.artifacts[0])
    await _delete_uploaded_keys([payload.artifacts[0]["key"]], client=fake, bucket="test-bucket")
    await _delete_uploaded_keys([], client=fake, bucket="test-bucket")
    assert payload.artifacts[0]["key"] not in fake.objects
    _ensure_bucket(fake, "test-bucket")
    assert _s3_client().meta.service_model.service_name == "s3"
