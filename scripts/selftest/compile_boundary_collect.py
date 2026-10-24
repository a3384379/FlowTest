"""Actual locked SDK calls with ordinary compiler credentials and an independent viewer."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import bootstrap
from scripts.selftest.compile_boundary_contracts import KEYS, CompileBoundaryObservation
from scripts.selftest.initialization_contracts import InstallationInventory
from scripts.selftest.initialization_inventory import inventory
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    integer_value,
    object_value,
    objects_value,
    read_json,
    text_value,
)
from scripts.selftest.mcp_generation_journey import begin_context, import_operation
from scripts.selftest.mcp_probe_setup import ProbeAPI, _account, _project
from scripts.selftest.product_agent_client import AgentRuntime
from scripts.selftest.product_boundary_common import ProductWorld
from scripts.selftest.quality_protocol import QualityProtocol, reserve_protocol_setup
from scripts.selftest.quality_sessions import open_protocols


@dataclass(frozen=True, repr=False)
class CompilerActors:
    full: str
    restricted: tuple[str, str, str]
    foreign: UUID


async def actors(world: ProductWorld) -> CompilerActors:
    boot = await bootstrap(world.stack, world.directory, credential_role="observer")
    org = boot.installation.organization_id
    admin = ProbeAPI(world.stack.runner_url, world.budget, boot.credentials.admin_token, str(org))
    try:
        tokens = []
        for index, scopes in enumerate(([], ["mcp:read"], ["mcp:flow:propose"])):
            _, token = await _account(
                admin,
                org,
                f"compile-{world.stack.nonce[:12]}-{index}",
                scopes,
                expires=world.deadline,
            )
            tokens.append(token)
        foreign = await _project(admin, world.stack.nonce, "compiler-foreign")
    finally:
        await admin.close()
    runtime = AgentRuntime.model_validate(read_json(world.state / "harness-runtime.json"))
    return CompilerActors(runtime.mcp_token, (tokens[0], tokens[1], tokens[2]), foreign.project_id)


def operation(batch: str) -> JsonObject:
    return {
        "name": batch,
        "method": "POST",
        "path": "/compile-only/" + batch,
        "request_body": {
            "required": True,
            "schema": {
                "type": "object",
                "required": ["count", "flag", "text"],
                "properties": {
                    "count": {"type": "integer", "enum": [0]},
                    "flag": {"type": "boolean", "enum": [False]},
                    "text": {"type": "string", "enum": [""]},
                    "optional": {"type": ["string", "null"], "enum": [None]},
                },
            },
        },
        "responses": {
            "201": {"description": "固定成功", "schema": {"type": "object"}},
            "422": {"description": "缺少必填字段"},
        },
    }


async def request(client: QualityProtocol, world: ProductWorld, output: Path) -> JsonObject:
    installed = AgentRuntime.model_validate(
        read_json(world.state / "harness-runtime.json")
    ).installation
    imported = await import_operation(
        client,
        installation=installed,
        scenario_id="compile-only",
        operation=operation(client.batch_key),
        service_id=str(installed.fixture_service_id),
        environment_id=str(installed.fixture_environment_id),
        output_dir=output,
    )
    api_id, version = text_value(imported["definition_id"]), integer_value(imported["version"])
    generated = await client.call(
        "flowtest.generate_test_design",
        {
            "project_id": str(installed.project_id),
            "api_definition_id": api_id,
            "api_version": version,
            "generation_policy": {
                "include_negative": True,
                "include_auth": False,
                "include_state": False,
                "include_data_constraints": True,
                "pairwise_enabled": False,
                "max_scenarios": 50,
            },
        },
        scenario_id="compile-only",
        phase="generate",
    )
    origin, design = object_value(generated["origin"]), object_value(generated["design"])
    context = await begin_context(
        client,
        installation=installed,
        scenario_id="compile-only",
        environment_id=str(installed.fixture_environment_id),
        api_id=api_id,
        api_version=version,
        contract_fingerprint=text_value(origin["contract_fingerprint"]),
    )
    happy = next(row for row in objects_value(design["scenarios"]) if row["kind"] == "happy_path")
    return {
        "project_id": str(installed.project_id),
        "environment_id": str(installed.fixture_environment_id),
        "design": design,
        "design_fingerprint": generated["fingerprint"],
        "origin": origin,
        "scenario_ids": [happy["id"]],
        "context_binding": context,
    }


def arguments(base: JsonObject, key: str, foreign: UUID) -> JsonObject:
    value = copy.deepcopy(base)
    if key in {"negative", "null_field"}:
        value["scenario_ids"] = [
            next(
                row["id"]
                for row in objects_value(object_value(value["design"])["scenarios"])
                if row["kind"] == ("required_omitted" if key == "negative" else "required_null")
            )
        ]
    updates: dict[str, JsonObject] = {
        "missing_context": {"context_binding": None},
        "unsupported_route": {"route_preference": "quick"},
        "fixture_auth": {
            "fixture_bindings": [
                {"field_path": "body.count", "fixture_ref": "fixture://unresolved"}
            ]
        },
        "organization": {"project_id": str(foreign)},
        "version": {"origin": {**object_value(value["origin"]), "api_version": 999}},
        "extra_fields": {"unrecognized": True},
        "boolean_budget": {"budget": {"max_nodes": True}},
        "context_changed": {
            "context_binding": {
                **object_value(value["context_binding"]),
                "context_fingerprint": "0" * 64,
            }
        },
    }
    if key == "source_changed":
        objects_value(object_value(value["design"])["scenarios"])[0]["title"] = "修改冻结来源"
    return {**value, **updates.get(key, {})}


async def proposals(world: ProductWorld) -> tuple[UUID, ...]:
    identifiers: list[UUID] = []
    for path in (
        f"/ai/change-sets?project_id={world.config.project_id}&page=1&page_size=100",
        f"/projects/{world.config.project_id}/flow-specs/change-sets?page=1&page_size=100",
    ):
        page = await world.viewer.object("GET", path)
        rows = objects_value(page["items"])
        if page["total"] != len(rows) or len(rows) >= 100:
            raise HarnessError("COMPILE_BOUNDARY_PROPOSAL_INVENTORY_INCOMPLETE")
        identifiers.extend(UUID(text_value(row["id"])) for row in rows)
    if len(identifiers) != len(set(identifiers)):
        raise HarnessError("COMPILE_BOUNDARY_PROPOSAL_INVENTORY_DUPLICATED")
    return tuple(sorted(identifiers, key=str))


async def collect_row(
    world: ProductWorld,
    client: QualityProtocol,
    base: JsonObject,
    key: str,
    foreign: UUID,
    catalog: JsonObject,
    before: InstallationInventory,
    prior: tuple[UUID, ...],
) -> CompileBoundaryObservation:
    payload = arguments(base, key, foreign)
    offset = len(client.receipts)
    response = boundary = None
    if key in {
        "positive",
        "reproducible",
        "negative",
        "null_field",
        "missing_context",
        "unsupported_route",
        "fixture_auth",
    }:
        response = await client.call(
            "flowtest.compile_test_design", {"request": payload}, scenario_id=key, phase="compile"
        )
    elif key != "catalog":
        boundary = await client.boundary_call(
            "flowtest.compile_test_design", {"request": payload}, scenario_id=key
        )
    return CompileBoundaryObservation(
        key=key,
        transport=client.transport,
        before=before,
        after=before,
        proposal_ids_before=prior,
        proposal_ids_after=prior,
        request=payload,
        response=response,
        boundary=boundary,
        calls=tuple(client.receipts[offset:]),
        catalog_names=tuple(sorted(client._delegate.tools)) if key == "catalog" else (),
        sdk_version=text_value(catalog["sdk_version"]),
        protocol_version=text_value(catalog["protocol_version"]),
        completed_at=datetime.now(UTC),
    )


async def collect(
    world: ProductWorld, issued: CompilerActors, output: Path
) -> tuple[CompileBoundaryObservation, ...]:
    rows: list[CompileBoundaryObservation] = []
    for transport in ("stdio", "streamable-http"):
        reserve_protocol_setup(world.budget)
        path = output / transport
        async with open_protocols(
            world.stack,
            transport,
            issued.full,
            issued.restricted[0],
            "compile-" + world.stack.nonce[:8] + "-" + transport,
            path,
            world.directory,
            world.deadline,
        ) as (writer, _):
            client = QualityProtocol(writer, world.budget, world.deadline)
            base = await request(client, world, path)
            catalog = read_json(path / "writer/mcp-catalog.json")
            before = await inventory(world.viewer, world.config.project_id)
            prior = await proposals(world)
            offset = len(rows)
            for key in KEYS:
                if not key.startswith("scope_"):
                    rows.append(
                        await collect_row(
                            world, client, base, key, issued.foreign, catalog, before, prior
                        )
                    )
        for index, key in enumerate(("scope_none", "scope_read", "scope_flow")):
            from scripts.selftest.run import _protocol

            reserve_protocol_setup(world.budget)
            async with _protocol(
                world.stack,
                transport,
                issued.restricted[index],
                "scope-" + world.stack.nonce[:8] + key,
                path / key,
                stack_directory=world.directory,
                deadline=world.deadline,
            ) as restricted:
                rows.append(
                    await collect_row(
                        world,
                        QualityProtocol(restricted, world.budget, world.deadline),
                        base,
                        key,
                        issued.foreign,
                        read_json(path / key / "mcp-catalog.json"),
                        before,
                        prior,
                    )
                )
        after = await inventory(world.viewer, world.config.project_id)
        current = await proposals(world)
        rows[offset:] = [
            row.model_copy(update={"after": after, "proposal_ids_after": current})
            for row in rows[offset:]
        ]
    order = {
        (transport, key): index
        for index, (transport, key) in enumerate(
            (t, k) for t in ("stdio", "streamable-http") for k in KEYS
        )
    }
    return tuple(sorted(rows, key=lambda row: order[row.transport, row.key]))
