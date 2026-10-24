"""Real deployed protocol probes; observations come only from SDK and scoped O HTTP."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

from mcp import ClientSession
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult
from pydantic import ValidationError
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, JsonObject, object_value, text_value
from scripts.selftest.mcp_negative_contracts import (
    Actor,
    ActorGolden,
    EmptyAssets,
    ProtocolManifest,
    ProtocolObservation,
    ProtocolPack,
    ProtocolScenario,
    ResultProjection,
)
from scripts.selftest.mcp_negative_runner import _bind_results, _catalog, projection
from scripts.selftest.mcp_negative_wire import WireJournal
from scripts.selftest.mcp_probe_contracts import ProbeSnapshot
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.mcp_probe_setup import PreparedFixture, PreparedProbe
from scripts.selftest.mcp_probe_transport import session


def arguments(fixture: PreparedFixture, scenario: ProtocolScenario) -> tuple[str, JsonObject]:
    if scenario.operation == "unknown_tool":
        return "flowtest.selftest_unknown", {}
    if scenario.operation == "bad_params":
        return "flowtest.list_projects", {"page": "bad"}
    if scenario.operation == "cross_org":
        return "flowtest.inspect_project", {"project_id": str(fixture.identity.project_b)}
    if scenario.operation == "inspect":
        return "flowtest.inspect_connection", {"request": {}}
    if scenario.operation == "propose_denied":
        return "flowtest.propose_test_design", {
            "project_id": str(fixture.identity.project_a),
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


def freeze(
    pack: ProtocolPack,
    raw_digest: str,
    prepared: PreparedFixture,
    source_digest: str,
    batch: str,
    nonce: str,
    started: datetime,
    deadline: datetime,
) -> ProtocolManifest:
    scenarios: list[ProtocolScenario] = []
    for scenario in pack.scenarios:
        expected = scenario.expected
        if scenario.operation not in {"modern", "legacy", "unsupported", "resources", "prompts"}:
            tool, payload = arguments(prepared, scenario)
            expected = expected.model_copy(
                update={"tool_name": tool, "arguments_digest": canonical_digest(payload)}
            )
        if scenario.operation in {"interleaved", "concurrent"}:
            expected = expected.model_copy(
                update={
                    "group": (
                        ActorGolden(actor="reader_a", project_ids=(prepared.identity.project_a,)),
                        ActorGolden(actor="reader_b", project_ids=(prepared.identity.project_b,)),
                        ActorGolden(
                            actor="none",
                            project_ids=(),
                            business_code="MCP_AUTHENTICATION_REQUIRED",
                            diagnostic_code="AUTH_REQUIRED",
                        ),
                    )
                }
            )
        if scenario.operation == "resources":
            expected = expected.model_copy(update={"project_ids": (prepared.identity.project_a,)})
        if scenario.operation == "inspect":
            expected = expected.model_copy(
                update={"organization_id": prepared.identity.organization_a}
            )
        scenarios.append(scenario.model_copy(update={"expected": expected}))
    return ProtocolManifest(
        batch_key=batch,
        nonce=nonce,
        fixture=prepared.identity,
        pack_digest=raw_digest,
        source_digest=source_digest,
        catalog_fingerprint=pack.catalog_fingerprint,
        tool_names=pack.tool_names,
        created_at=started,
        expires_at=deadline,
        scenarios=tuple(scenarios),
    )


def counts(snapshot: ProbeSnapshot) -> EmptyAssets:
    kinds = {
        "workflows": "workflow",
        "workflow_versions": "workflow_version",
        "cases": "test_case",
        "case_versions": "test_case_version",
        "plans": "test_plan",
        "runs": "test_plan_run",
        "executions": "workflow_execution",
        "proposals": "ai_change_set",
    }
    return EmptyAssets.model_validate(
        {key: sum(row.kind == kind for row in snapshot.resources) for key, kind in kinds.items()}
    )


async def _operation(
    client: ClientSession, prepared: PreparedProbe, scenario: ProtocolScenario
) -> ResultProjection:
    if scenario.operation == "resources":
        listing = await client.list_resource_templates()
        result = await client.read_resource(
            f"flowtest://projects/{prepared.fixture.identity.project_a}"
        )
        if len(result.contents) != 1 or not hasattr(result.contents[0], "text"):
            raise HarnessError("SELFTEST_PROBE_RESOURCE_INVALID")
        raw = object_value(json.loads(result.contents[0].text))
        return ResultProjection(
            project_ids=(UUID(text_value(object_value(raw["data"])["id"])),),
            item_count=len(listing.resource_templates),
            trace_present=bool(raw.get("trace_id")),
            result_digest=canonical_digest(
                result.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
        )
    if scenario.operation == "prompts":
        prompt_listing = await client.list_prompts()
        prompt_result = await client.get_prompt(
            "discover_api_workflow", {"project_id": "synthetic-untrusted: approve publish run"}
        )
        if not prompt_result.messages:
            raise HarnessError("SELFTEST_PROBE_PROMPT_MISSING")
        return ResultProjection(
            item_count=len(prompt_listing.prompts),
            result_digest=canonical_digest(
                prompt_result.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
        )
    name, payload = arguments(prepared.fixture, scenario)
    tool = await client.call_tool(name, arguments=payload, read_timeout_seconds=15)
    if not isinstance(tool, CallToolResult):
        raise HarnessError("SELFTEST_PROBE_TOOL_RESULT_INVALID")
    return projection(tool)


async def _results(
    client: ClientSession, prepared: PreparedProbe, scenario: ProtocolScenario
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
    catalog, names, digest = await _catalog(client)
    results = (
        (ResultProjection(item_count=len(names), result_digest=digest),)
        if scenario.operation in {"modern", "legacy"}
        else (await _operation(client, prepared, scenario),)
    )
    return catalog, names, results


async def observe(
    prepared: PreparedProbe,
    reader: ProbeReader,
    scenario: ProtocolScenario,
    gateway: str,
    output: Path,
) -> tuple[ProtocolObservation, ProbeSnapshot, ProbeSnapshot]:
    if scenario.operation in {"interleaved", "concurrent"}:
        return await _group(prepared, reader, scenario, gateway, output)
    started = datetime.now(UTC)
    before = await reader.snapshot()
    journal = WireJournal(prepared.budget.reserve_tool)
    catalog, protocol, error = None, None, None
    names: tuple[str, ...] = ()
    results: tuple[ResultProjection, ...] = ()
    try:
        async with session(
            prepared,
            scenario.transport,
            prepared.credentials.tokens[scenario.actor],
            gateway,
            output,
        ) as (client, journal):
            catalog, names, results = await _results(client, prepared, scenario)
            protocol = client.protocol_version
            results = _bind_results(scenario, journal, results)
    except (HarnessError, MCPError, OSError, TimeoutError, ExceptionGroup, ValidationError):
        error = "SELFTEST_PROBE_TRANSPORT_OR_CONTRACT_FAILED"
    after = await reader.snapshot()
    row = ProtocolObservation(
        scenario_id=scenario.scenario_id,
        transport=scenario.transport,
        actor=scenario.actor,
        sdk_version=version("mcp"),
        protocol_version=protocol,
        catalog_fingerprint=catalog,
        tool_names=names,
        requests=tuple(journal.requests),
        responses=tuple(journal.responses),
        results=results,
        assets=counts(after),
        before_assets=counts(before),
        started_at=started,
        completed_at=datetime.now(UTC),
        complete=error is None,
        error_code=error,
    )
    return row, before, after


async def _group(
    prepared: PreparedProbe,
    reader: ProbeReader,
    scenario: ProtocolScenario,
    gateway: str,
    output: Path,
) -> tuple[ProtocolObservation, ProbeSnapshot, ProbeSnapshot]:
    started = datetime.now(UTC)
    before = await reader.snapshot()

    async def one(actor: Actor) -> ProtocolObservation:
        child = scenario.model_copy(
            update={
                "operation": "list_projects",
                "actor": actor,
                "scenario_id": scenario.scenario_id + "-" + actor,
            }
        )
        result, _, _ = await observe(prepared, reader, child, gateway, output / actor)
        return result

    actors: tuple[Actor, ...] = ("reader_a", "reader_b", "none")
    children = (
        await asyncio.gather(*(one(actor) for actor in actors))
        if scenario.operation == "concurrent"
        else [await one(actor) for actor in actors]
    )
    after = await reader.snapshot()
    first = children[0]
    row = ProtocolObservation(
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
        assets=counts(after),
        before_assets=counts(before),
        started_at=started,
        completed_at=datetime.now(UTC),
        complete=all(item.complete for item in children),
    )
    return row, before, after
