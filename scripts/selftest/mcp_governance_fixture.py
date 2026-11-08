"""Own local processes only; synthetic reviewer JWT and machine tokens remain in memory."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

import httpx
from mcp import ClientSession
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI, object_value, text_value
from scripts.selftest.mcp_governance_contracts import (
    Fixture,
    Inventory,
    MaterializedView,
    ProposalView,
    Scenario,
)
from scripts.selftest.mcp_negative_contracts import ProtocolGolden, ProtocolScenario
from scripts.selftest.mcp_negative_fixture import LocalFixture, asset_counts
from scripts.selftest.mcp_negative_runner import session
from scripts.selftest.mcp_negative_wire import WireJournal


@dataclass(repr=False, frozen=True)
class Actors:
    identity: Fixture
    machine_token: str
    reviewer_token: str


async def _login_reviewer(base: LocalFixture, password: str) -> str:
    public = PublicAPI(base.api_url)
    try:
        login = await public.object(
            "POST",
            "/auth/login",
            {"email": "governance-reviewer@example.com", "password": password},
        )
        token = text_value(login["access_token"])
        if object_value(login["user"])["requires_password_change"] is True:
            authenticated = PublicAPI(base.api_url, token)
            active = secrets.token_urlsafe(30)
            try:
                await authenticated.request(
                    "POST",
                    "/auth/change-password",
                    {"current_password": password, "new_password": active},
                )
            finally:
                await authenticated.close()
            login = await public.object(
                "POST",
                "/auth/login",
                {"email": "governance-reviewer@example.com", "password": active},
            )
        return text_value(login["access_token"])
    finally:
        await public.close()


async def provision(base: LocalFixture) -> Actors:
    org, project = str(base.credentials.organization_a), str(base.credentials.project_a)
    admin = PublicAPI(base.api_url, base.credentials.tokens["human"], org)
    try:
        owner = await admin.object("GET", "/auth/me")
        writer = await admin.object(
            "POST",
            f"/organizations/{org}/service-accounts",
            {
                "name": "隔离治理机器",
                "account_key": "governance-writer",
                "scopes": ["mcp:read", "mcp:write", "mcp:flow:propose"],
            },
        )
        password = secrets.token_urlsafe(30)
        user = await admin.object(
            "POST",
            "/users",
            {
                "email": "governance-reviewer@example.com",
                "password": password,
                "display_name": "独立fixture审核者",
            },
        )
        await admin.object(
            "PUT",
            f"/organizations/{org}/members/{user['id']}",
            {"user_id": user["id"], "role": "member"},
        )
        await admin.object(
            "PUT",
            f"/projects/{project}/members/{user['id']}",
            {"user_id": user["id"], "role": "owner"},
        )
        return Actors(
            Fixture(
                project_id=base.credentials.project_a,
                organization_id=base.credentials.organization_a,
                machine_id=UUID(text_value(writer["id"])),
                owner_user_id=UUID(text_value(owner["id"])),
                reviewer_user_id=UUID(text_value(user["id"])),
            ),
            text_value(writer["token"]),
            await _login_reviewer(base, password),
        )
    finally:
        await admin.close()


@asynccontextmanager
async def sdk(
    base: LocalFixture,
    actors: Actors,
    scenario: Scenario,
    python: Path,
    backend: Path,
    directory: Path,
) -> AsyncIterator[tuple[ClientSession, WireJournal]]:
    # Reuse only transport plumbing. This slot is populated with the independently
    # provisioned generation machine; public artifacts use its exact principal ID.
    fixture = replace(
        base,
        credentials=replace(
            base.credentials, tokens=base.credentials.tokens | {"reader_a": actors.machine_token}
        ),
    )
    descriptor = ProtocolScenario(
        scenario_id=scenario.scenario_id,
        acceptance_id=scenario.acceptance_id,
        variant_key=scenario.variant_key,
        title="治理协议连接",
        transport=scenario.transport,
        actor="reader_a",
        operation="list_projects",
        expected=ProtocolGolden(layer="success"),
    )
    wire = WireJournal(base.budget.reserve_tool)
    async with session(fixture, descriptor, python, backend, directory, journal=wire) as result:
        await result[0].discover()
        yield result


def inventory(base: LocalFixture) -> Inventory:
    counts = asset_counts(base).model_dump()
    with sqlite3.connect(f"file:{base.database}?mode=ro", uri=True) as connection:
        designs = int(connection.execute("SELECT count(*) FROM test_designs").fetchone()[0])
        approvals = int(
            connection.execute("SELECT count(*) FROM change_set_approvals").fetchone()[0]
        )
    return Inventory.model_validate(counts | {"designs": designs, "approvals": approvals})


async def read_materialized(
    base: LocalFixture, actors: Actors, change_id: UUID, item_id: str
) -> MaterializedView:
    observer = PublicAPI(base.api_url, actors.reviewer_token, str(actors.identity.organization_id))
    try:
        raw = await observer.object(
            "GET", f"/mcp/write/change-sets/{change_id}/items/{item_id}/materialized-design"
        )
    finally:
        await observer.close()
    return MaterializedView.model_validate(
        {
            "id": raw["id"],
            "project_id": raw["project_id"],
            "source_change_set_id": raw["source_change_set_id"],
            "fingerprint": raw["fingerprint"],
            "document_digest": canonical_digest(raw["design"]),
            "reviewed_by_id": raw["reviewed_by_id"],
            "status": raw["status"],
        }
    )


async def read_proposal(base: LocalFixture, actors: Actors, identifier: UUID) -> ProposalView:
    observer = PublicAPI(base.api_url, actors.reviewer_token, str(actors.identity.organization_id))
    try:
        raw = await observer.object("GET", f"/mcp/write/change-sets/{identifier}")
    finally:
        await observer.close()
    data = object_value(raw["data"])
    items = data["items"]
    if not isinstance(items, list) or len(items) != 1:
        raise HarnessError("SELFTEST_GOVERNANCE_ITEM_SET_MISMATCH")
    item = object_value(items[0])
    content = object_value(item["proposed_content"])
    intent = object_value(content["intent"])
    oracles = content["oracles"]
    if not isinstance(oracles, list):
        raise HarnessError("SELFTEST_GOVERNANCE_ORACLE_MISSING")
    approval = object_value(data["approval"]) if data["approval"] is not None else {}
    materialized = (
        await read_materialized(base, actors, identifier, text_value(item["id"]))
        if item["materialized_resource_id"] is not None
        else None
    )
    projected = [
        {
            "id": object_value(row)["id"],
            "kind": object_value(row)["kind"],
            "expression": object_value(row)["expression"],
            "operator": object_value(row)["operator"],
            "expected_digest": canonical_digest(object_value(row).get("expected")),
        }
        for row in oracles
    ]
    return ProposalView.model_validate(
        {
            "id": data["id"],
            "project_id": data["project_id"],
            "source_fingerprint": data["source_fingerprint"],
            "proposed_document_digest": canonical_digest(content),
            "actor_type": data["actor_type"],
            "created_by_id": data["created_by_id"],
            "status": data["status"],
            "item_id": item["id"],
            "item_type": item["item_type"],
            "item_review": item["review_status"],
            "materialized_type": item["materialized_resource_type"],
            "materialized_id": item["materialized_resource_id"],
            "approval_id": approval.get("id"),
            "approved_by_id": approval.get("approved_by_id"),
            "materialized": materialized.model_dump(mode="json") if materialized else None,
            "reviewed_by_id": item["reviewed_by_id"],
            "intent_key": intent["key"],
            "objective": intent["objective"],
            "oracles": projected,
        }
    )


async def rest(
    base: LocalFixture, actors: Actors, role: str, path: str, body: JsonObject
) -> tuple[int, object]:
    token = actors.machine_token if role == "generation_machine" else actors.reviewer_token
    async with httpx.AsyncClient(
        base_url=base.api_url + "/api/v1/",
        headers={
            "Authorization": "Bearer " + token,
            "X-Organization-Id": str(actors.identity.organization_id),
        },
        trust_env=False,
        timeout=15,
    ) as client:
        response = await client.post(path.lstrip("/"), json=body)
    return response.status_code, response.json()
