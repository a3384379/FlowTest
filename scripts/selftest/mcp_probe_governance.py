"""Deployed governance calls and reviewer actions with digest-only O snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

import httpx
from mcp import ClientSession
from mcp.types import CallToolResult
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, JsonObject
from scripts.selftest.mcp_governance_contracts import (
    Inventory,
    Manifest,
    Observation,
    Reference,
    Result,
    Scenario,
)
from scripts.selftest.mcp_governance_runner import payload, rest_projection, tool_projection
from scripts.selftest.mcp_negative_wire import WireJournal
from scripts.selftest.mcp_probe_contracts import ProbeSnapshot
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.mcp_probe_setup import PreparedProbe


@dataclass(frozen=True)
class ProposalReference:
    id: UUID
    item_id: UUID
    approval_id: UUID | None


@dataclass(frozen=True)
class References:
    low: ProposalReference | None = None
    high: ProposalReference | None = None
    other: ProposalReference | None = None

    def require(self, target: Reference) -> ProposalReference:
        selected = {"low": self.low, "high": self.high, "other": self.other}[target]
        if selected is None:
            raise HarnessError("SELFTEST_PROBE_PRIOR_PROPOSAL_MISSING")
        return selected


def counts(snapshot: ProbeSnapshot) -> Inventory:
    kinds = {
        "workflows": "workflow",
        "workflow_versions": "workflow_version",
        "cases": "test_case",
        "case_versions": "test_case_version",
        "plans": "test_plan",
        "runs": "test_plan_run",
        "executions": "workflow_execution",
        "proposals": "ai_change_set",
        "designs": "test_design",
        "approvals": "change_set_approval",
    }
    return Inventory.model_validate(
        {key: sum(row.kind == kind for row in snapshot.resources) for key, kind in kinds.items()}
    )


def _reference(snapshot: ProbeSnapshot, identifier: UUID) -> ProposalReference:
    proposals = [
        row for row in snapshot.resources if row.kind == "ai_change_set" and row.id == identifier
    ]
    if len(proposals) != 1 or len(proposals[0].items) != 1:
        raise HarnessError("SELFTEST_PROBE_PROPOSAL_ITEM_SET_MISMATCH")
    approvals = [
        row
        for row in snapshot.resources
        if row.kind == "change_set_approval" and row.parent_id == identifier
    ]
    if len(approvals) > 1:
        raise HarnessError("SELFTEST_PROBE_APPROVAL_SET_MISMATCH")
    return ProposalReference(
        identifier, proposals[0].items[0].id, approvals[0].id if approvals else None
    )


def _request(scenario: Scenario, references: References) -> tuple[str, JsonObject]:
    target = scenario.expected.target
    if target is None:
        raise HarnessError("SELFTEST_PROBE_ACTION_TARGET_MISSING")
    selected = references.require(target)
    root = f"/mcp/write/change-sets/{selected.id}"
    if scenario.action.endswith("approve"):
        return root + "/approve", {}
    body: JsonObject = {}
    if scenario.action in {"high_accept", "wrong_approval"}:
        approval = references.require("high").approval_id
        if approval is None:
            raise HarnessError("SELFTEST_PROBE_APPROVAL_REFERENCE_MISSING")
        body = {"approval_id": str(approval)}
    return root + f"/items/{selected.item_id}/" + (
        "reject" if scenario.action == "low_reject" else "accept"
    ), body


async def _rest(prepared: PreparedProbe, scenario: Scenario, path: str, body: JsonObject) -> Result:
    if not prepared.budget.reserve():
        raise HarnessError("SELFTEST_PROBE_HTTP_BUDGET_EXHAUSTED")
    token = (
        prepared.credentials.writer_token
        if scenario.expected.actor == "generation_machine"
        else prepared.credentials.reviewer_token
    )
    async with httpx.AsyncClient(
        base_url=prepared.binding.runner_url + "/api/v1/",
        headers={
            "Authorization": "Bearer " + token,
            "X-Organization-Id": str(prepared.fixture.identity.organization_a),
        },
        trust_env=False,
        timeout=15,
    ) as client:
        response = await client.post(path.lstrip("/"), json=body)
    if len(response.content) > 262144:
        raise HarnessError("SELFTEST_PROBE_REVIEW_RESPONSE_OVERSIZED")
    return rest_projection(response.status_code, response.json())


async def observe(
    prepared: PreparedProbe,
    reader: ProbeReader,
    manifest: Manifest,
    scenario: Scenario,
    client: ClientSession,
    wire: WireJournal,
    references: References,
) -> tuple[Observation, ProbeSnapshot, ProbeSnapshot, References]:
    started = datetime.now(UTC)
    before = await reader.snapshot()
    request, response = None, None
    if scenario.expected.channel == "mcp":
        name = scenario.expected.tool_name
        if name is None:
            raise HarnessError("SELFTEST_PROBE_TOOL_NAME_MISSING")
        arguments = {} if scenario.action.startswith("unknown_") else payload(manifest, scenario)
        index = len(wire.requests)
        returned = await client.call_tool(name, arguments=arguments, read_timeout_seconds=15)
        if not isinstance(returned, CallToolResult):
            raise HarnessError("SELFTEST_PROBE_GOVERNANCE_TOOL_INVALID")
        raw = tool_projection(returned, name)
        calls = [row for row in wire.requests[index:] if row.method == "tools/call"]
        if len(calls) != 1:
            raise HarnessError("SELFTEST_PROBE_GOVERNANCE_RPC_SET_MISMATCH")
        request = calls[0]
        response = next(
            row
            for row in wire.responses
            if row.session_id == request.session_id
            and canonical_digest(row.id) == canonical_digest(request.id)
        )
        path, digest = name, canonical_digest(arguments)
    else:
        path, body = _request(scenario, references)
        raw = await _rest(prepared, scenario, path, body)
        digest = canonical_digest(body)
    after = await reader.snapshot()
    target = scenario.expected.target
    if target is not None:
        identifier = (
            raw.proposal_id
            if scenario.action.startswith("persist_")
            else references.require(target).id
        )
        if identifier is None:
            raise HarnessError("SELFTEST_PROBE_GOVERNANCE_PROPOSAL_MISSING")
        references = replace(references, **{target: _reference(after, identifier)})
    observed = Observation(
        scenario_id=scenario.scenario_id,
        actor=scenario.expected.actor,
        transport=scenario.transport,
        started_at=started,
        completed_at=datetime.now(UTC),
        request_method="POST",
        request_path=path,
        request_digest=digest,
        wire_request=request,
        wire_response=response,
        result=raw,
        before=counts(before),
        after=counts(after),
        state=None,
        complete=True,
    )
    return observed, before, after, references
