#!/usr/bin/env python3
"""Prepare and verify the irreversible S47.2 canonical-contract migration fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
from hashlib import sha256
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.domain.canonical_contracts import semantic_contract_fingerprint
from app.models import APIDefinition, APIVersion, Project, User

_IMPORT_KEY: Final = "s47-2-contract-migration-golden"
_USER_EMAIL: Final = "s47-2-migration@example.test"
_SENSITIVE_VALUES: Final = (
    "migration-password-sentinel",
    "migration-token-sentinel",
    "migration-person@example.test",
    "4111111111111111",
    "eyJhbGciOiJIUzI1NiJ9.c2Vuc2l0aXZl.c2lnbmF0dXJl",
)


async def _prepare() -> None:
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        existing = await session.scalar(
            select(APIDefinition).where(APIDefinition.import_key == _IMPORT_KEY)
        )
        if existing is not None:
            project = await session.get(Project, existing.project_id)
            if project is not None:
                await session.delete(project)
                await session.flush()
        user = await session.scalar(select(User).where(User.email == _USER_EMAIL))
        if user is None:
            user = User(
                email=_USER_EMAIL,
                display_name="S47.2 migration verifier",
                password_hash=sha256(b"disabled migration account").hexdigest(),
                is_active=False,
                is_system_admin=False,
                requires_password_change=True,
            )
            session.add(user)
            await session.flush()
        project = Project(
            name="S47.2 migration verifier",
            description="Ephemeral migration acceptance fixture",
            created_by_id=user.id,
        )
        session.add(project)
        await session.flush()
        definition = APIDefinition(
            project_id=project.id,
            name="S47.2 sensitive contract fixture",
            description="",
            current_version=1,
            is_active=True,
            import_key=_IMPORT_KEY,
            created_by_id=user.id,
        )
        session.add(definition)
        await session.flush()
        session.add(
            APIVersion(
                api_definition_id=definition.id,
                version=1,
                method="POST",
                path="/migration-contract",
                query_parameters=[],
                headers={},
                variables={},
                body_kind="json",
                body={},
                auth_kind="none",
                auth_config={},
                extraction_rules=[],
                assertions=[],
                canonical_contract=_unsafe_contract_fixture(),
                contract_fingerprint="0" * 64,
                contract_completeness="complete",
                created_by_id=user.id,
            )
        )
        await session.commit()
    await engine.dispose()
    print(json.dumps({"status": "prepared", "revision": "20260823_0042"}))


async def _verify() -> None:
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        version = await session.scalar(
            select(APIVersion)
            .join(APIDefinition, APIDefinition.id == APIVersion.api_definition_id)
            .where(APIDefinition.import_key == _IMPORT_KEY)
        )
        if version is None:
            raise RuntimeError("S47.2 migration fixture is missing")
        encoded = json.dumps(version.canonical_contract, ensure_ascii=False, sort_keys=True)
        if any(value in encoded for value in _SENSITIVE_VALUES):
            raise RuntimeError("S47.2 migration retained a sensitive canonical value")
        if version.contract_completeness != "redacted_partial":
            raise RuntimeError("S47.2 migration did not mark redacted_partial")
        expected = semantic_contract_fingerprint(version.canonical_contract)
        if version.contract_fingerprint != expected or expected == "0" * 64:
            raise RuntimeError("S47.2 migration did not recalculate the semantic fingerprint")
    await engine.dispose()
    print(json.dumps({"status": "verified", "sensitive_values_present": False}))


def _unsafe_contract_fixture() -> dict[str, object]:
    return {
        "operation": "migration.contract",
        "method": "POST",
        "path": "/migration-contract",
        "service": "migration",
        "auth": {"required": False, "kind": "none"},
        "parameters": [
            {
                "name": "email",
                "location": "query",
                "required": False,
                "schema": {"type": "string", "example": _SENSITIVE_VALUES[2]},
            }
        ],
        "request_body": {
            "required": True,
            "content_type": "application/json",
            "schema": {
                "type": "object",
                "properties": {
                    "password": {"type": "string", "example": _SENSITIVE_VALUES[0]},
                    "token": {"type": "string", "default": _SENSITIVE_VALUES[1]},
                    "card": {"type": "string", "const": _SENSITIVE_VALUES[3]},
                    "mode": {"type": "string", "enum": ["NORMAL", _SENSITIVE_VALUES[4]]},
                },
            },
        },
        "request": {},
        "responses": {},
        "source_ref": "migration://s47.2",
        "revision": "0042",
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
