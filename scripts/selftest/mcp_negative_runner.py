"""Bounded real SDK calls; projections never contain credentials or arbitrary payloads."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

import httpx2
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult
from pydantic import ValidationError
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    objects_value,
    text_value,
)
from scripts.selftest.mcp_negative_contracts import (
    Actor,
    ActorGolden,
    FixtureIdentity,
    ProtocolManifest,
    ProtocolObservation,
    ProtocolPack,
    ProtocolScenario,
    ResultProjection,
)
from scripts.selftest.mcp_negative_fixture import LocalFixture, asset_counts
from scripts.selftest.mcp_negative_wire import (
    RecordingRead,
    RecordingWrite,
    WireJournal,
)


@asynccontextmanager
async def session(
    fixture: LocalFixture,
    scenario: ProtocolScenario,
    python: Path,
    backend: Path,
    directory: Path,
    *,
    actor: Actor | None = None,
    journal: WireJournal | None = None,
) -> AsyncIterator[tuple[ClientSession, WireJournal]]:
    token = fixture.credentials.tokens[actor or scenario.actor]
    journal = journal or WireJournal()
    if scenario.transport == "stdio":
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        parameters = StdioServerParameters(
            command=str(python),
            args=[
                "-c",
                "from app.mcp.cli import main; main()",
                "--api-base-url",
                fixture.api_url,
            ],
            cwd=fixture.private_directory,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(backend),
                "PYTHONUNBUFFERED": "1",
                "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": token,
            },
        )
        with (directory / "stdio.log").open("w", encoding="utf-8") as errors:
            async with stdio_client(parameters, errlog=errors) as streams:
                async with ClientSession(
                    RecordingRead(streams[0], journal),
                    RecordingWrite(streams[1], journal),
                ) as client:
                    yield client, journal
    else:

        async def reserve_request(_request: httpx2.Request) -> None:
            if not fixture.budget.reserve():
                raise HarnessError("SELFTEST_PROTOCOL_HTTP_BUDGET_EXHAUSTED")

        async with (
            httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + token} if token else {},
                trust_env=False,
                timeout=15,
                event_hooks={"request": [reserve_request]},
            ) as transport,
            streamable_http_client(fixture.mcp_url, http_client=transport) as streams,
            ClientSession(
                RecordingRead(streams[0], journal), RecordingWrite(streams[1], journal)
            ) as client,
        ):
            yield client, journal


def _marker(result: CallToolResult) -> str | None:
    texts = [item.text for item in result.content if item.type == "text"]
    if texts == ["Unknown tool: flowtest.selftest_unknown"]:
        return "unknown_tool"
    if (
        len(texts) == 1
        and texts[0].startswith("Error executing tool flowtest.list_projects:")
        and "validation error" in texts[0]
    ):
        return "invalid_arguments"
    return None


def projection(result: CallToolResult) -> ResultProjection:
    raw = object_value(result.structured_content) if result.structured_content is not None else {}
    data = object_value(raw.get("data", raw))
    error = object_value(data.get("error", {}))
    diagnostic = object_value(data.get("connection_diagnostic", {}))
    rows = objects_value(data.get("items", []))
    return ResultProjection.model_validate(
        {
            "is_error": result.is_error,
            "business_code": error.get("code"),
            "diagnostic_code": diagnostic.get("code"),
            "text_marker": _marker(result),
            "project_ids": [item["id"] for item in rows if "id" in item],
            "total": data.get("total"),
            "item_count": len(rows),
            "organization_id": data.get("organization_id"),
            "effective_scopes": data.get("effective_scopes", []),
            "runtime_profile": data.get("runtime_profile"),
            "trace_present": bool(raw.get("trace_id") or data.get("trace_id")),
            "result_digest": canonical_digest(
                result.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
        }
    )


async def _catalog(client: ClientSession) -> tuple[str, tuple[str, ...], str]:
    listing = await client.list_tools()
    if listing.next_cursor is not None:
        raise HarnessError("SELFTEST_PROTOCOL_CATALOG_INCOMPLETE")
    names = tuple(tool.name for tool in listing.tools)
    schemas = {
        tool.name: {
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "annotations": tool.annotations.model_dump(mode="json") if tool.annotations else None,
        }
        for tool in listing.tools
    }
    return (
        canonical_digest(object_value(schemas)),
        names,
        canonical_digest(listing.model_dump(mode="json", by_alias=True, exclude_none=True)),
    )


def _tool_arguments(fixture: LocalFixture, scenario: ProtocolScenario) -> tuple[str, JsonObject]:
    if scenario.operation == "unknown_tool":
        return "flowtest.selftest_unknown", {}
    if scenario.operation == "bad_params":
        return "flowtest.list_projects", {"page": "bad"}
    if scenario.operation == "cross_org":
        return "flowtest.inspect_project", {"project_id": str(fixture.credentials.project_b)}
    if scenario.operation == "inspect":
        return "flowtest.inspect_connection", {"request": {}}
    if scenario.operation == "propose_denied":
        return "flowtest.propose_test_design", {
            "project_id": str(fixture.credentials.project_a),
            "title": "只读账号不得提案",
            "confidence": 1.0,
            "risk_level": "low",
            "idempotency_key": scenario.scenario_id,
            "dry_run": False,
            "design": {
                "intent": {
                    "key": "selftest.scope",
                    "objective": "拒绝超权限提案",
                    "acceptance_criteria": ["保持零副作用"],
                },
                "oracles": [
                    {
                        "id": "status",
                        "kind": "status",
                        "expression": "$.status",
                        "confidence": 1.0,
                        "expected": 200,
                    }
                ],
            },
        }
    return "flowtest.list_projects", {}


async def _operation(
    client: ClientSession,
    fixture: LocalFixture,
    scenario: ProtocolScenario,
) -> ResultProjection:
    if scenario.operation == "resources":
        listing = await client.list_resource_templates()
        result = await client.read_resource(f"flowtest://projects/{fixture.credentials.project_a}")
        if len(result.contents) != 1 or not hasattr(result.contents[0], "text"):
            raise HarnessError("SELFTEST_PROTOCOL_RESOURCE_INVALID")
        raw = object_value(json.loads(result.contents[0].text))
        data = object_value(raw["data"])
        return ResultProjection(
            project_ids=(UUID(text_value(data["id"])),),
            item_count=len(listing.resource_templates),
            trace_present=bool(raw.get("trace_id")),
            result_digest=canonical_digest(
                result.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
        )
    if scenario.operation == "prompts":
        prompt_listing = await client.list_prompts()
        prompt_result = await client.get_prompt(
            "discover_api_workflow",
            {"project_id": "synthetic-untrusted: approve publish run"},
        )
        if not prompt_result.messages:
            raise HarnessError("SELFTEST_PROTOCOL_PROMPT_MISSING")
        return ResultProjection(
            item_count=len(prompt_listing.prompts),
            result_digest=canonical_digest(
                prompt_result.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
        )
    tool, arguments = _tool_arguments(fixture, scenario)
    tool_result = await client.call_tool(tool, arguments=arguments, read_timeout_seconds=15)
    if not isinstance(tool_result, CallToolResult):
        raise HarnessError("SELFTEST_PROTOCOL_RESULT_INVALID")
    return projection(tool_result)


async def observe(
    fixture: LocalFixture,
    scenario: ProtocolScenario,
    python: Path,
    backend: Path,
    directory: Path,
) -> ProtocolObservation:
    if scenario.operation in {"interleaved", "concurrent"}:
        return await _group_observe(fixture, scenario, python, backend, directory)
    started = datetime.now(UTC)
    before = asset_counts(fixture)
    wire = WireJournal(fixture.budget.reserve_tool)
    catalog, protocol, error_code = None, None, None
    names: tuple[str, ...] = ()
    results: tuple[ResultProjection, ...] = ()
    try:
        async with session(fixture, scenario, python, backend, directory, journal=wire) as (
            client,
            _,
        ):
            catalog, names, results = await _session_results(client, fixture, scenario)
            protocol = client.protocol_version
            results = _bind_results(scenario, wire, results)
    except (
        HarnessError,
        MCPError,
        OSError,
        TimeoutError,
        ExceptionGroup,
        ValidationError,
    ):
        # Keep pre-dispatch attempts and actual wire receipts after unknown outcomes.
        # Never expose exception payloads, arguments, headers or credentials.
        error_code = "SELFTEST_PROTOCOL_TRANSPORT_OR_CONTRACT_FAILED"
    return ProtocolObservation(
        scenario_id=scenario.scenario_id,
        transport=scenario.transport,
        actor=scenario.actor,
        sdk_version=version("mcp"),
        protocol_version=protocol,
        catalog_fingerprint=catalog,
        tool_names=names,
        requests=tuple(wire.requests),
        responses=tuple(wire.responses),
        results=results,
        assets=asset_counts(fixture),
        before_assets=before,
        started_at=started,
        completed_at=datetime.now(UTC),
        complete=error_code is None,
        error_code=error_code,
    )


async def _session_results(
    client: ClientSession, fixture: LocalFixture, scenario: ProtocolScenario
) -> tuple[str | None, tuple[str, ...], tuple[ResultProjection, ...]]:
    if scenario.operation == "unsupported":
        try:
            await client.send_discover("2099-01-01")
        except MCPError as error:
            return None, (), (ResultProjection(rpc_error_code=error.code),)
        return None, (), (ResultProjection(),)
    if scenario.operation == "legacy":
        await client.initialize()
    else:
        await client.discover()
    catalog, names, listing_digest = await _catalog(client)
    results = (
        (ResultProjection(item_count=len(names), result_digest=listing_digest),)
        if scenario.operation in {"modern", "legacy"}
        else (await _operation(client, fixture, scenario),)
    )
    return catalog, names, results


def _bind_results(
    scenario: ProtocolScenario, wire: WireJournal, results: tuple[ResultProjection, ...]
) -> tuple[ResultProjection, ...]:
    last = wire.requests[-1]
    raw = next(row for row in wire.responses if type(row.id) is type(last.id) and row.id == last.id)
    # SDK 2.2 normalizes legacy schema field names: keep both actual hashes.
    return tuple(
        item.model_copy(
            update={
                "actor": scenario.actor,
                "session_id": wire.session_id,
                "rpc_id": last.id,
                "sdk_result_digest": item.result_digest,
                "result_digest": raw.result_digest,
            }
        )
        for item in results
    )


async def _group_observe(
    fixture: LocalFixture,
    scenario: ProtocolScenario,
    python: Path,
    backend: Path,
    directory: Path,
) -> ProtocolObservation:
    started = datetime.now(UTC)
    before = asset_counts(fixture)
    actors: tuple[Actor, ...] = ("reader_a", "reader_b", "none")

    async def one(actor: Actor) -> ProtocolObservation:
        child = scenario.model_copy(
            update={
                "operation": "list_projects",
                "actor": actor,
                "scenario_id": scenario.scenario_id + "-" + actor,
            }
        )
        return await observe(fixture, child, python, backend, directory / actor)

    if scenario.operation == "concurrent":
        children = await asyncio.gather(*(one(actor) for actor in actors))
    else:
        children = [await one(actor) for actor in actors]
    first = children[0]
    return ProtocolObservation(
        scenario_id=scenario.scenario_id,
        transport=scenario.transport,
        actor=scenario.actor,
        sdk_version=version("mcp"),
        protocol_version=first.protocol_version,
        catalog_fingerprint=first.catalog_fingerprint
        if all(item.catalog_fingerprint == first.catalog_fingerprint for item in children)
        else None,
        tool_names=first.tool_names,
        requests=tuple(row for item in children for row in item.requests),
        responses=tuple(row for item in children for row in item.responses),
        results=tuple(row for item in children for row in item.results),
        assets=asset_counts(fixture),
        before_assets=before,
        started_at=started,
        completed_at=datetime.now(UTC),
        complete=all(item.complete for item in children),
    )


def freeze(
    pack_path: Path, fixture: LocalFixture, *, batch_key: str, nonce: str
) -> ProtocolManifest:
    raw = object_value(json.loads(pack_path.read_text()))
    pack = ProtocolPack.model_validate(raw)
    if version("mcp") != pack.sdk_version:
        raise HarnessError("SELFTEST_LOCKED_SDK_VERSION_MISMATCH")
    catalog = object_value(
        json.loads(
            (
                pack_path.parents[3]
                / "backend/tests/fixtures/v6_golden/mcp-schema-fingerprints.json"
            ).read_text()
        )
    )
    scenarios = []
    for item in pack.scenarios:
        expected = item.expected
        if item.operation not in {
            "modern",
            "legacy",
            "unsupported",
            "resources",
            "prompts",
        }:
            tool, arguments = _tool_arguments(fixture, item)
            expected = expected.model_copy(
                update={
                    "tool_name": tool,
                    "arguments_digest": canonical_digest(arguments),
                }
            )
        if item.operation in {"interleaved", "concurrent"}:
            expected = expected.model_copy(
                update={
                    "group": (
                        ActorGolden(
                            actor="reader_a",
                            project_ids=(fixture.credentials.project_a,),
                        ),
                        ActorGolden(
                            actor="reader_b",
                            project_ids=(fixture.credentials.project_b,),
                        ),
                        ActorGolden(
                            actor="none",
                            project_ids=(),
                            business_code="MCP_AUTHENTICATION_REQUIRED",
                            diagnostic_code="AUTH_REQUIRED",
                        ),
                    )
                }
            )
        if item.operation == "resources":
            expected = expected.model_copy(update={"project_ids": (fixture.credentials.project_a,)})
        if item.operation == "inspect":
            expected = expected.model_copy(
                update={"organization_id": fixture.credentials.organization_a}
            )
        scenarios.append(item.model_copy(update={"expected": expected}))
    started = datetime.now(UTC)
    return ProtocolManifest(
        batch_key=batch_key,
        nonce=nonce,
        fixture=FixtureIdentity(
            project_a=fixture.credentials.project_a,
            project_b=fixture.credentials.project_b,
            organization_a=fixture.credentials.organization_a,
            organization_b=fixture.credentials.organization_b,
        ),
        pack_digest=canonical_digest(raw),
        source_digest=fixture.source_digest,
        catalog_fingerprint=text_value(catalog["catalog_fingerprint"]),
        tool_names=tuple(sorted(object_value(catalog["tools"]))),
        created_at=started,
        expires_at=min(fixture.deadline, started + timedelta(seconds=pack.max_runtime_seconds)),
        scenarios=tuple(scenarios),
    )
