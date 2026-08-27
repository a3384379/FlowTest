"""Persist canonical API operation contracts for S47.1."""

import json
import re
from collections.abc import Sequence
from hashlib import sha256
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0042"
down_revision: str | None = "20260823_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_versions") as batch:
        batch.add_column(
            sa.Column("canonical_contract", sa.JSON(), server_default="{}", nullable=False)
        )
        batch.add_column(sa.Column("contract_fingerprint", sa.String(length=64)))
        batch.add_column(
            sa.Column(
                "contract_completeness",
                sa.String(length=32),
                server_default="legacy_partial",
                nullable=False,
            )
        )
        batch.create_index(
            "ix_api_versions_contract_fingerprint", ["contract_fingerprint"], unique=False
        )
    _backfill_legacy_contracts()


def downgrade() -> None:
    with op.batch_alter_table("api_versions") as batch:
        batch.drop_index("ix_api_versions_contract_fingerprint")
        batch.drop_column("contract_completeness")
        batch.drop_column("contract_fingerprint")
        batch.drop_column("canonical_contract")


def _backfill_legacy_contracts() -> None:
    connection = op.get_bind()
    versions = sa.table(
        "api_versions",
        sa.column("id"),
        sa.column("version", sa.Integer()),
        sa.column("method", sa.String()),
        sa.column("path", sa.String()),
        sa.column("query_parameters", sa.JSON()),
        sa.column("headers", sa.JSON()),
        sa.column("body", sa.JSON()),
        sa.column("auth_kind", sa.String()),
        sa.column("auth_config", sa.JSON()),
        sa.column("canonical_contract", sa.JSON()),
        sa.column("contract_fingerprint", sa.String()),
        sa.column("contract_completeness", sa.String()),
    )
    rows = connection.execute(
        sa.select(
            versions.c.id,
            versions.c.version,
            versions.c.method,
            versions.c.path,
            versions.c.query_parameters,
            versions.c.headers,
            versions.c.body,
            versions.c.auth_kind,
            versions.c.auth_config,
        )
    ).mappings()
    for row in rows:
        contract = _legacy_contract(dict(row))
        canonical = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection.execute(
            versions.update()
            .where(versions.c.id == row["id"])
            .values(
                canonical_contract=contract,
                contract_fingerprint=sha256(canonical.encode()).hexdigest(),
                contract_completeness="legacy_partial",
            )
        )


def _legacy_contract(row: dict[str, Any]) -> dict[str, Any]:
    path = str(row["path"]).split("?", 1)[0] or "/"
    parameters = _legacy_parameters(row, path)
    body_schema = _inferred_schema(row.get("body")) if row.get("body") is not None else {}
    request_body = (
        {
            "required": False,
            "content_type": "application/json",
            "schema": body_schema,
        }
        if body_schema
        else None
    )
    auth_kind = str(row.get("auth_kind") or "none")
    auth_config = row.get("auth_config") if isinstance(row.get("auth_config"), dict) else {}
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
        "parameters": parameters,
        "request_body": request_body,
        "request": body_schema,
        "responses": {},
        "source_ref": f"api-version://{row['id']}",
        "revision": str(row["version"]),
        "completeness": "legacy_partial",
    }


def _legacy_parameters(row: dict[str, Any], path: str) -> list[dict[str, Any]]:
    parameters = [
        _parameter(name, "path", True)
        for name in re.findall(r"\{\{?([A-Za-z_][A-Za-z0-9_.-]*)\}\}?", path)
    ]
    query = row.get("query_parameters")
    if isinstance(query, list):
        parameters.extend(
            _parameter(str(item["name"]), "query", item.get("required") is True)
            for item in query
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
    headers = row.get("headers")
    if isinstance(headers, dict):
        parameters.extend(_parameter(str(name), "header", False) for name in sorted(headers))
    return parameters


def _parameter(name: str, location: str, required: bool) -> dict[str, Any]:
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


def _inferred_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _inferred_schema(value[0]) if value else {},
        }
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {str(key): _inferred_schema(child) for key, child in value.items()},
        }
    if value is None:
        return {}
    return {"type": "string"}
