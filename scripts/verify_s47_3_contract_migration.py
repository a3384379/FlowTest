#!/usr/bin/env python3
"""Prepare and verify the irreversible S47.3 canonical-contract cleanup."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import settings
from app.migrations_support.canonical_contract_v2 import clean_historical_contract
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_IMPORT_KEY = "s47-2-contract-migration-golden"
_SENSITIVE_PATTERN = "Bearer migration-sensitive-pattern"


async def _prepare() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        version_id = await connection.scalar(
            text(
                "SELECT v.id FROM api_versions v "
                "JOIN api_definitions d ON d.id = v.api_definition_id "
                "WHERE d.import_key = :import_key"
            ),
            {"import_key": _IMPORT_KEY},
        )
        if version_id is None:
            raise RuntimeError("prepare the S47.2 migration fixture before S47.3")
        await connection.execute(
            text(
                "UPDATE api_versions SET canonical_contract = CAST(:contract AS json), "
                "contract_fingerprint = :fingerprint, contract_completeness = 'complete' "
                "WHERE id = :version_id"
            ),
            {
                "contract": json.dumps(_unsafe_history_fixture()),
                "fingerprint": "f" * 64,
                "version_id": version_id,
            },
        )
    await engine.dispose()
    print(json.dumps({"status": "prepared", "revision": "20260823_0043"}))


async def _verify() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT v.canonical_contract, v.contract_fingerprint, "
                        "v.contract_completeness FROM api_versions v "
                        "JOIN api_definitions d ON d.id = v.api_definition_id "
                        "WHERE d.import_key = :import_key"
                    ),
                    {"import_key": _IMPORT_KEY},
                )
            )
            .mappings()
            .one()
        )
    await engine.dispose()
    contract = row["canonical_contract"]
    if isinstance(contract, str):
        contract = json.loads(contract)
    if not isinstance(contract, dict):
        raise TypeError("S47.3 migration contract is missing")
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    if "value_hashes" in encoded or _SENSITIVE_PATTERN in encoded:
        raise RuntimeError(
            "S47.3 migration retained a sensitive enum digest or pattern"
        )
    if (
        '"minimum": "invalid-number"' in encoded
        or '"type": "Bearer invalid-type"' in encoded
    ):
        raise RuntimeError("S47.3 migration retained an invalid keyword value")
    redacted = contract["request"]["properties"]["status"]["x-flowtest-redacted-enum"]
    if redacted != {"value_count": 2, "values_redacted": True}:
        raise RuntimeError("S47.3 migration did not reduce the enum to its count")
    cleaned = clean_historical_contract(contract)
    if row["contract_fingerprint"] != cleaned.fingerprint:
        raise RuntimeError("S47.3 migration fingerprint is not stable")
    if row["contract_completeness"] not in {
        "redacted_partial",
        "invalid_history_cleaned",
    }:
        raise RuntimeError("S47.3 migration completeness was not adjusted")
    print(
        json.dumps(
            {
                "status": "verified",
                "sensitive_hash_present": False,
                "fingerprint": cleaned.fingerprint,
            }
        )
    )


def _unsafe_history_fixture() -> dict[str, object]:
    return {
        "operation": "migration.contract",
        "method": "POST",
        "path": "/migration-contract",
        "service": "migration",
        "auth": {"required": False, "kind": "none"},
        "parameters": [],
        "request_body": None,
        "request": {
            "type": "object",
            "required": "not-a-list",
            "properties": {
                "status": {
                    "type": "string",
                    "x-flowtest-redacted-enum": {
                        "value_count": 2,
                        "values_redacted": True,
                        "value_hashes": ["a" * 64, "b" * 64],
                    },
                },
                "quantity": {"type": "integer", "minimum": "invalid-number"},
                "invalid_type": {"type": "Bearer invalid-type"},
                "pattern": {"type": "string", "pattern": _SENSITIVE_PATTERN},
            },
        },
        "responses": {},
        "source_ref": "migration://s47.3/source-metadata",
        "revision": "0043",
        "completeness": "complete",
        "warnings": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "verify"))
    args = parser.parse_args()
    asyncio.run(_prepare() if args.mode == "prepare" else _verify())


if __name__ == "__main__":
    main()
