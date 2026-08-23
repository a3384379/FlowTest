"""Bootstrap the current schema for the single-process runtime.

Standalone installs intentionally do not invoke a separate migration container.  The
database is created from the checked-in SQLAlchemy metadata on first start and is
stamped with the latest migration revision.  Subsequent schema changes still use
Alembic; the stamp keeps the normal migration tooling aware of the installed baseline.
"""

import json
import re
from typing import cast
from uuid import uuid4

from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.database import engine
from app.domain.canonical_contracts import (
    sanitize_contract_payload,
    semantic_contract_fingerprint,
)
from app.models import Base
from app.models.ai import AIChangeItem, AIChangeSet

BASELINE_REVISION = "20260823_0043"


async def initialize_standalone_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "INSERT OR IGNORE INTO flowtest_standalone_meta (key, value) "
                "VALUES ('schema_baseline', :revision)"
            ),
            {"revision": BASELINE_REVISION},
        )
        await connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        await connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "SELECT :revision WHERE NOT EXISTS (SELECT 1 FROM alembic_version)"
            ),
            {"revision": BASELINE_REVISION},
        )
        await _ensure_incremental_columns(connection)


async def _ensure_incremental_columns(connection: AsyncConnection) -> None:
    """Keep an existing offline SQLite installation bootable after an upgrade."""

    await _ensure_organization_tables(connection)
    await _ensure_governance_tables(connection)
    await _ensure_flow_spec_change_set_columns(connection)
    await _ensure_s42_controlled_write_tables(connection)
    await _ensure_s47_test_design_columns(connection)
    await _ensure_change_regression_tables(connection)
    await _add_column_if_missing(
        connection,
        table="projects",
        column="outbound_policy_enabled",
        definition="BOOLEAN NOT NULL DEFAULT 1",
    )
    await _add_column_if_missing(
        connection,
        table="environments",
        column="default_service_id",
        definition="CHAR(32)",
    )
    await _add_column_if_missing(
        connection,
        table="api_definitions",
        column="service_id",
        definition="CHAR(32)",
    )
    await _add_column_if_missing(
        connection,
        table="api_versions",
        column="variables",
        definition="JSON NOT NULL DEFAULT '{}'",
    )
    await _add_column_if_missing(
        connection,
        table="api_versions",
        column="canonical_contract",
        definition="JSON NOT NULL DEFAULT '{}'",
    )
    await _add_column_if_missing(
        connection,
        table="api_versions",
        column="contract_fingerprint",
        definition="VARCHAR(64)",
    )
    await _add_column_if_missing(
        connection,
        table="api_versions",
        column="contract_completeness",
        definition="VARCHAR(32) NOT NULL DEFAULT 'legacy_partial'",
    )
    await _ensure_s471_api_version_contracts(connection)
    await _sanitize_s472_api_version_contracts(connection)
    await _add_column_if_missing(
        connection,
        table="api_call_executions",
        column="target_snapshot",
        definition="JSON NOT NULL DEFAULT '{}'",
    )
    for table in ("projects", "audit_logs", "runner_pools"):
        await _add_column_if_missing(
            connection,
            table=table,
            column="organization_id",
            definition="CHAR(32)",
        )
    await _ensure_default_organization(connection)
    await _ensure_default_targets(connection)
    await connection.execute(
        text(
            "UPDATE flowtest_standalone_meta SET value = :revision "
            "WHERE key = 'schema_baseline' AND value IN "
            "('20260822_0032', '20260822_0033', '20260822_0034', '20260822_0035', "
            "'20260822_0036', '20260822_0037', '20260822_0038', '20260822_0039', "
            "'20260823_0040', '20260823_0041', '20260823_0042')"
        ),
        {"revision": BASELINE_REVISION},
    )
    await connection.execute(
        text(
            "UPDATE alembic_version SET version_num = :revision "
            "WHERE version_num IN "
            "('20260822_0032', '20260822_0033', '20260822_0034', '20260822_0035', "
            "'20260822_0036', '20260822_0037', '20260822_0038', '20260822_0039', "
            "'20260823_0040', '20260823_0041', '20260823_0042')"
        ),
        {"revision": BASELINE_REVISION},
    )


async def _ensure_s42_controlled_write_tables(connection: AsyncConnection) -> None:
    """Create S42 tables and rebuild legacy SQLite item checks when needed."""

    await _rebuild_s42_change_item_table_if_needed(connection)
    from app.models.test_design import ChangeSetApproval, TestDesign

    for model in (TestDesign, ChangeSetApproval):
        table = cast(Table, model.__table__)
        await connection.execute(CreateTable(table, if_not_exists=True))


async def _ensure_s47_test_design_columns(connection: AsyncConnection) -> None:
    for column, definition in (
        ("scenarios", "JSON NOT NULL DEFAULT '[]'"),
        ("evidence_refs", "JSON NOT NULL DEFAULT '[]'"),
        ("warnings", "JSON NOT NULL DEFAULT '[]'"),
        ("confidence", "FLOAT NOT NULL DEFAULT 1"),
        ("review_requirements", "JSON NOT NULL DEFAULT '[]'"),
    ):
        await _add_column_if_missing(
            connection,
            table="test_designs",
            column=column,
            definition=definition,
        )


async def _ensure_s471_api_version_contracts(connection: AsyncConnection) -> None:
    columns = await connection.execute(text("PRAGMA table_info(api_versions)"))
    if not columns.fetchall():
        return
    await connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_api_versions_contract_fingerprint "
            "ON api_versions (contract_fingerprint)"
        )
    )
    rows = (
        await connection.execute(
            text(
                "SELECT id, version, method, path, query_parameters, headers, body, "
                "auth_kind, auth_config, canonical_contract FROM api_versions"
            )
        )
    ).mappings()
    for row in rows:
        if _json_value(row["canonical_contract"]):
            continue
        contract = _standalone_legacy_contract(dict(row))
        sanitized = sanitize_contract_payload(contract).payload
        await connection.execute(
            text(
                "UPDATE api_versions SET canonical_contract = :contract, "
                "contract_fingerprint = :fingerprint, "
                "contract_completeness = 'legacy_partial' WHERE id = :id"
            ),
            {
                "id": row["id"],
                "contract": json.dumps(
                    sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                "fingerprint": semantic_contract_fingerprint(sanitized),
            },
        )


async def _sanitize_s472_api_version_contracts(connection: AsyncConnection) -> None:
    columns = await connection.execute(text("PRAGMA table_info(api_versions)"))
    if not columns.fetchall():
        return
    rows = (
        await connection.execute(text("SELECT id, canonical_contract FROM api_versions"))
    ).mappings()
    for row in rows:
        raw = _json_value(row["canonical_contract"])
        if not isinstance(raw, dict) or not raw:
            continue
        sanitized = sanitize_contract_payload(raw).payload
        await connection.execute(
            text(
                "UPDATE api_versions SET canonical_contract = :contract, "
                "contract_fingerprint = :fingerprint, contract_completeness = :completeness "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "contract": json.dumps(
                    sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                "fingerprint": semantic_contract_fingerprint(sanitized),
                "completeness": sanitized["completeness"],
            },
        )


def _standalone_legacy_contract(row: dict[str, object]) -> dict[str, object]:
    path = str(row["path"]).split("?", 1)[0] or "/"
    body = _json_value(row.get("body"))
    body_schema = _standalone_inferred_schema(body) if body is not None else {}
    auth_kind = str(row.get("auth_kind") or "none")
    auth_config = _json_value(row.get("auth_config"))
    auth_config = auth_config if isinstance(auth_config, dict) else {}
    auth_location = auth_config.get("in")
    return {
        "operation": f"legacy_{str(row['id']).replace('-', '_')}",
        "method": str(row["method"]),
        "path": path,
        "service": None,
        "auth": {
            "required": auth_kind != "none",
            "kind": auth_kind,
            "location": (
                auth_location
                if auth_location in {"header", "query", "cookie"}
                else ("header" if auth_kind != "none" else None)
            ),
            "name": auth_config.get("name"),
            "source_ref": None,
        },
        "parameters": _standalone_legacy_parameters(row, path),
        "request_body": (
            {"required": False, "content_type": "application/json", "schema": body_schema}
            if body_schema
            else None
        ),
        "request": body_schema,
        "responses": {},
        "source_ref": f"api-version://{row['id']}",
        "revision": str(row["version"]),
        "completeness": "legacy_partial",
    }


def _standalone_legacy_parameters(row: dict[str, object], path: str) -> list[dict[str, object]]:
    parameters = [
        _standalone_parameter(name, "path", True)
        for name in re.findall(r"\{\{?([A-Za-z_][A-Za-z0-9_.-]*)\}\}?", path)
    ]
    query = _json_value(row.get("query_parameters"))
    if isinstance(query, list):
        parameters.extend(
            _standalone_parameter(str(item["name"]), "query", item.get("required") is True)
            for item in query
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
    headers = _json_value(row.get("headers"))
    if isinstance(headers, dict):
        parameters.extend(
            _standalone_parameter(str(name), "header", False) for name in sorted(headers)
        )
    return parameters


def _standalone_parameter(name: str, location: str, required: bool) -> dict[str, object]:
    return {
        "name": name,
        "location": location,
        "required": required,
        "schema": {"type": "string"},
        "example": None,
        "style": None,
        "explode": None,
        "source_ref": None,
    }


def _standalone_inferred_schema(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _standalone_inferred_schema(value[0]) if value else {},
        }
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                str(key): _standalone_inferred_schema(child) for key, child in value.items()
            },
        }
    if value is None:
        return {}
    return {"type": "string"}


def _json_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


async def _ensure_change_regression_tables(connection: AsyncConnection) -> None:
    """Create the S45 trace tables for existing standalone SQLite databases."""

    from app.models.change_regression import ChangeRegressionRun, ChangeRegressionStage

    for model in (ChangeRegressionRun, ChangeRegressionStage):
        table = cast(Table, model.__table__)
        await connection.execute(CreateTable(table, if_not_exists=True))


async def _rebuild_s42_change_item_table_if_needed(connection: AsyncConnection) -> None:
    result = await connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ai_change_items'")
    )
    row = result.first()
    table_sql = str(row[0]) if row and row[0] else ""
    if not table_sql or "test_design" in table_sql:
        return
    change_item_table = cast(Table, AIChangeItem.__table__)
    await _drop_table_indexes(connection, "ai_change_items")
    await connection.execute(
        text("ALTER TABLE ai_change_items RENAME TO ai_change_items_s42_legacy")
    )
    await connection.execute(CreateTable(change_item_table))
    await connection.execute(
        text(
            "INSERT INTO ai_change_items ("
            "change_set_id, suggestion_id, position, item_type, action, title, target_resource_id, "
            "target_snapshot_sha256, proposed_content, review_status, review_note, reviewed_by_id, "
            "reviewed_at, materialized_resource_type, materialized_resource_id, id, created_at, "
            "updated_at) SELECT change_set_id, suggestion_id, position, item_type, action, title, "
            "target_resource_id, target_snapshot_sha256, proposed_content, review_status, "
            "review_note, reviewed_by_id, reviewed_at, materialized_resource_type, "
            "materialized_resource_id, id, created_at, updated_at FROM ai_change_items_s42_legacy"
        )
    )
    await connection.execute(text("DROP TABLE ai_change_items_s42_legacy"))
    for index in change_item_table.indexes:
        await connection.execute(CreateIndex(index))


async def _ensure_organization_tables(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS organizations ("
            "id CHAR(32) PRIMARY KEY, name VARCHAR(160) NOT NULL, "
            "slug VARCHAR(80) NOT NULL UNIQUE, "
            "description VARCHAR(4000) NOT NULL DEFAULT '', enabled BOOLEAN NOT NULL DEFAULT 1, "
            "created_by_id CHAR(32), created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    await connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS organization_members ("
            "id CHAR(32) PRIMARY KEY, organization_id CHAR(32) NOT NULL, "
            "user_id CHAR(32) NOT NULL, "
            "role VARCHAR(16) NOT NULL DEFAULT 'member', "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE (organization_id, user_id))"
        )
    )
    await connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS service_accounts ("
            "id CHAR(32) PRIMARY KEY, organization_id CHAR(32) NOT NULL, "
            "name VARCHAR(160) NOT NULL, "
            "account_key VARCHAR(120) NOT NULL, token_prefix VARCHAR(24) NOT NULL UNIQUE, "
            "token_hash VARCHAR(64) NOT NULL UNIQUE, scopes JSON NOT NULL DEFAULT '[]', "
            "enabled BOOLEAN NOT NULL DEFAULT 1, created_by_id CHAR(32) NOT NULL, "
            "expires_at DATETIME, last_used_at DATETIME, revoked_at DATETIME, "
            "metadata_json JSON NOT NULL DEFAULT '{}', "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE (organization_id, name), UNIQUE (organization_id, account_key))"
        )
    )


async def _ensure_governance_tables(connection: AsyncConnection) -> None:
    from app.models.governance import OrganizationGovernance, OrganizationKeyVersion

    for model in (OrganizationGovernance, OrganizationKeyVersion):
        table = cast(Table, model.__table__)
        await connection.execute(CreateTable(table, if_not_exists=True))


async def _ensure_flow_spec_change_set_columns(connection: AsyncConnection) -> None:
    """Upgrade the change-set tables used by a pre-S40 standalone database.

    Fresh standalone databases get the complete model from metadata.  Existing
    SQLite tables need a rebuild because SQLite cannot alter a NOT NULL column in
    place; the rebuild preserves existing AI rows and adds the FlowSpec fields.
    """

    if await _flow_spec_tables_need_rebuild(connection):
        await _rebuild_flow_spec_change_set_tables(connection)
        return

    await _add_column_if_missing(
        connection,
        table="ai_change_sets",
        column="source_type",
        definition="VARCHAR(24) NOT NULL DEFAULT 'ai'",
    )
    await _add_column_if_missing(
        connection,
        table="ai_change_sets",
        column="source_ref",
        definition="VARCHAR(512)",
    )
    await _add_column_if_missing(
        connection,
        table="ai_change_sets",
        column="actor_type",
        definition="VARCHAR(32) NOT NULL DEFAULT 'user'",
    )
    await _add_column_if_missing(
        connection,
        table="ai_change_sets",
        column="actor_id",
        definition="CHAR(32)",
    )
    await _add_column_if_missing(
        connection,
        table="ai_change_sets",
        column="applied_at",
        definition="DATETIME",
    )


async def _flow_spec_tables_need_rebuild(connection: AsyncConnection) -> bool:
    table_result = await connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ai_change_sets'")
    )
    table_row = table_result.first()
    table_sql = str(table_row[0]) if table_row and table_row[0] else ""
    if table_sql and "change_regression" not in table_sql:
        return True
    change_sets = await connection.execute(text("PRAGMA table_info(ai_change_sets)"))
    change_items = await connection.execute(text("PRAGMA table_info(ai_change_items)"))
    set_info = {str(row[1]): bool(row[3]) for row in change_sets.fetchall()}
    item_info = {str(row[1]): bool(row[3]) for row in change_items.fetchall()}
    if not set_info or not item_info:
        return False
    required_set_columns = {
        "impact_run_id",
        "release_risk_id",
        "ai_job_id",
        "source_type",
        "source_ref",
        "actor_type",
        "actor_id",
        "applied_at",
    }
    if not required_set_columns.issubset(set_info) or "suggestion_id" not in item_info:
        return True
    return any(
        set_info[column] for column in ("impact_run_id", "release_risk_id", "ai_job_id")
    ) or bool(item_info["suggestion_id"])


async def _rebuild_flow_spec_change_set_tables(connection: AsyncConnection) -> None:
    change_set_table = cast(Table, AIChangeSet.__table__)
    change_item_table = cast(Table, AIChangeItem.__table__)
    await _drop_table_indexes(connection, "ai_change_sets")
    await _drop_table_indexes(connection, "ai_change_items")
    await connection.execute(
        text("ALTER TABLE ai_change_items RENAME TO ai_change_items_s40_legacy")
    )
    await connection.execute(text("ALTER TABLE ai_change_sets RENAME TO ai_change_sets_s40_legacy"))
    await connection.execute(CreateTable(change_set_table))
    await connection.execute(CreateTable(change_item_table))
    await connection.execute(
        text(
            "INSERT INTO ai_change_sets ("
            "project_id, impact_run_id, release_risk_id, ai_job_id, title, status, "
            "source_snapshot, source_fingerprint, source_type, source_ref, actor_type, actor_id, "
            "created_by_id, applied_at, id, created_at, updated_at) "
            "SELECT project_id, impact_run_id, release_risk_id, ai_job_id, title, status, "
            "source_snapshot, source_fingerprint, 'ai', NULL, 'user', NULL, created_by_id, NULL, "
            "id, created_at, updated_at FROM ai_change_sets_s40_legacy"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO ai_change_items ("
            "change_set_id, suggestion_id, position, item_type, action, title, target_resource_id, "
            "target_snapshot_sha256, proposed_content, review_status, review_note, reviewed_by_id, "
            "reviewed_at, materialized_resource_type, materialized_resource_id, id, created_at, "
            "updated_at) SELECT change_set_id, suggestion_id, position, item_type, action, title, "
            "target_resource_id, target_snapshot_sha256, proposed_content, review_status, "
            "review_note, reviewed_by_id, reviewed_at, materialized_resource_type, "
            "materialized_resource_id, id, created_at, updated_at FROM ai_change_items_s40_legacy"
        )
    )
    await connection.execute(text("DROP TABLE ai_change_items_s40_legacy"))
    await connection.execute(text("DROP TABLE ai_change_sets_s40_legacy"))
    for table in (change_set_table, change_item_table):
        for index in table.indexes:
            await connection.execute(CreateIndex(index))


async def _drop_table_indexes(connection: AsyncConnection, table: str) -> None:
    result = await connection.execute(text(f"PRAGMA index_list({table})"))
    for row in result.fetchall():
        index_name = str(row[1])
        if index_name.startswith("sqlite_autoindex_"):
            continue
        quoted_name = index_name.replace('"', '""')
        await connection.execute(text(f'DROP INDEX IF EXISTS "{quoted_name}"'))


async def _ensure_default_organization(connection: AsyncConnection) -> None:
    required_tables = {"users", "projects", "organizations", "organization_members"}
    existing_tables = {
        table
        for table in required_tables
        if (await connection.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    }
    if existing_tables != required_tables:
        return
    organization_id = await connection.scalar(
        text("SELECT id FROM organizations WHERE slug = 'default'")
    )
    if organization_id is None:
        creator = await connection.scalar(
            text("SELECT id FROM users ORDER BY created_at, id LIMIT 1")
        )
        if creator is None:
            return
        organization_id = uuid4().hex
        await connection.execute(
            text(
                "INSERT INTO organizations "
                "(id, name, slug, description, enabled, created_by_id) "
                "VALUES (:id, 'Default Organization', 'default', '迁移兼容的默认组织', 1, :creator)"
            ),
            {"id": organization_id, "creator": creator},
        )
    await connection.execute(
        text(
            "UPDATE projects SET organization_id = :organization_id WHERE organization_id IS NULL"
        ),
        {"organization_id": organization_id},
    )
    await connection.execute(
        text(
            "UPDATE runner_pools SET organization_id = :organization_id "
            "WHERE organization_id IS NULL"
        ),
        {"organization_id": organization_id},
    )
    await connection.execute(
        text(
            "UPDATE audit_logs SET organization_id = "
            "(SELECT projects.organization_id FROM projects "
            "WHERE projects.id = audit_logs.project_id) "
            "WHERE organization_id IS NULL AND project_id IS NOT NULL"
        )
    )
    await connection.execute(
        text(
            "UPDATE audit_logs SET organization_id = :organization_id WHERE organization_id IS NULL"
        ),
        {"organization_id": organization_id},
    )
    users = await connection.execute(text("SELECT id, is_system_admin FROM users"))
    for user_id, is_system_admin in users.fetchall():
        await connection.execute(
            text(
                "INSERT OR IGNORE INTO organization_members "
                "(id, organization_id, user_id, role) "
                "VALUES (:id, :organization_id, :user_id, :role)"
            ),
            {
                "id": uuid4().hex,
                "organization_id": organization_id,
                "user_id": user_id,
                "role": "owner" if is_system_admin else "member",
            },
        )


async def _add_column_if_missing(
    connection: AsyncConnection,
    *,
    table: str,
    column: str,
    definition: str,
) -> None:
    result = await connection.execute(text(f"PRAGMA table_info({table})"))
    rows = result.fetchall()
    if not rows:
        return
    columns = {str(row[1]) for row in rows}
    if column not in columns:
        await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


async def _ensure_default_targets(connection: AsyncConnection) -> None:
    required_tables = {
        "projects",
        "services",
        "environments",
        "api_definitions",
        "service_endpoints",
    }
    existing_tables = {
        table
        for table in required_tables
        if (await connection.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    }
    if existing_tables != required_tables:
        return
    projects = await connection.execute(text("SELECT id, created_by_id FROM projects"))
    for project_id, created_by_id in projects.fetchall():
        service = await connection.execute(
            text(
                "SELECT id FROM services WHERE project_id = :project_id AND service_key = 'default'"
            ),
            {"project_id": project_id},
        )
        service_id = service.scalar_one_or_none()
        if service_id is None:
            service_id = uuid4().hex
            await connection.execute(
                text(
                    "INSERT INTO services "
                    "(id, project_id, service_key, name, created_by_id) "
                    "VALUES (:id, :project_id, 'default', 'Default Service', :created_by_id)"
                ),
                {
                    "id": service_id,
                    "project_id": project_id,
                    "created_by_id": created_by_id,
                },
            )
        await connection.execute(
            text(
                "UPDATE environments SET default_service_id = :service_id "
                "WHERE project_id = :project_id AND default_service_id IS NULL"
            ),
            {"service_id": service_id, "project_id": project_id},
        )
        await connection.execute(
            text(
                "UPDATE api_definitions SET service_id = :service_id "
                "WHERE project_id = :project_id AND service_id IS NULL"
            ),
            {"service_id": service_id, "project_id": project_id},
        )
        environments = await connection.execute(
            text(
                "SELECT id, base_url, created_by_id FROM environments "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
        for environment_id, base_url, environment_created_by_id in environments.fetchall():
            existing = await connection.execute(
                text(
                    "SELECT id FROM service_endpoints WHERE environment_id = :environment_id "
                    "AND service_id = :service_id AND variant = 'default'"
                ),
                {"environment_id": environment_id, "service_id": service_id},
            )
            if existing.scalar_one_or_none() is None:
                await connection.execute(
                    text(
                        "INSERT INTO service_endpoints "
                        "(id, project_id, environment_id, service_id, variant, base_url, "
                        "created_by_id) "
                        "VALUES (:id, :project_id, :environment_id, :service_id, 'default', "
                        ":base_url, :created_by_id)"
                    ),
                    {
                        "id": uuid4().hex,
                        "project_id": project_id,
                        "environment_id": environment_id,
                        "service_id": service_id,
                        "base_url": base_url,
                        "created_by_id": environment_created_by_id,
                    },
                )
