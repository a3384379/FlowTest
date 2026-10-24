"""Frozen read-only repair policies; unknown and mutation failures remain blocked."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from mcp.types import CallToolResult, Tool
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.host_contracts import HostBudget, ReadOnlyRepairPolicy  # noqa: E402
from scripts.selftest.host_gateway import BoundedGateway  # noqa: E402
from scripts.selftest.host_repairs import resolve_known_read_errors  # noqa: E402
from scripts.selftest.io import HarnessError  # noqa: E402
from test_selftest_host_adapter import authorization  # noqa: E402


class ReadRepairUpstream:
    async def call_tool(self, name, arguments):
        if arguments["version"] == 0:
            return CallToolResult(
                content=[], structured_content={"error": {"code": "API_VERSION_NOT_FOUND"}}
            )
        return CallToolResult(
            content=[], structured_content={"data": {"version": arguments["version"]}}
        )


def proxy(tmp_path, *, policies=()):
    auth = authorization(
        read_only_repairs=policies,
        budget=HostBudget(
            maximum_tool_calls=5,
            wall_seconds=10,
            maximum_prompt_bytes=1024,
            maximum_result_bytes=1024,
            maximum_total_result_bytes=8192,
        ),
    )
    tool = Tool(
        name="flowtest.inspect_contract",
        input_schema={
            "type": "object",
            "required": ["project_id", "version"],
            "properties": {"project_id": {"type": "string"}, "version": {"type": "integer"}},
        },
    )
    return BoundedGateway(
        authorization=auth,
        attempt_id=uuid4(),
        phase="workflow",
        catalog=(tool,),
        upstream=ReadRepairUpstream(),
        directory=tmp_path,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )


def policy():
    return ReadOnlyRepairPolicy(
        tool_name="flowtest.inspect_contract",
        error_codes=("API_VERSION_NOT_FOUND",),
        allowed_argument_fields=("version",),
    )


@pytest.mark.asyncio
async def test_only_preapproved_structured_read_error_and_actual_later_resolution_are_accepted(
    tmp_path,
):
    gateway = proxy(tmp_path, policies=(policy(),))
    original = {"project_id": str(gateway.authorization.project_id), "version": 0}
    await gateway.call("flowtest.inspect_contract", original)
    with pytest.raises(HarnessError, match="RESOLUTION_NOT_PROVEN"):
        resolve_known_read_errors(gateway)
    await gateway.call("flowtest.inspect_contract", {**original, "version": 1})
    (proof,) = resolve_known_read_errors(gateway)
    assert (
        proof.failed_sequence == 1
        and proof.resolved_sequence == 2
        and proof.changed_fields == ("version",)
    )
    assert gateway.receipts[0].business_success is False and gateway.receipts[0].resolved_by == 2
    assert gateway.receipts[0].result_digest and gateway.receipts[1].business_success is True


@pytest.mark.asyncio
async def test_saving_actual_failed_read_cannot_self_authorize_a_repair(tmp_path):
    gateway = proxy(tmp_path)
    args = {"project_id": str(gateway.authorization.project_id), "version": 0}
    await gateway.call("flowtest.inspect_contract", args)
    await gateway.call("flowtest.inspect_contract", {**args, "version": 1})
    with pytest.raises(HarnessError, match="UNRESOLVED_OR_UNKNOWN"):
        resolve_known_read_errors(gateway)


def test_mutation_tools_cannot_receive_read_repair_policy():
    with pytest.raises(ValidationError):
        ReadOnlyRepairPolicy(
            tool_name="flowtest.propose_test_design",
            error_codes=("CONFLICT",),
            allowed_argument_fields=("test_cases",),
        )


@pytest.mark.asyncio
async def test_unknown_response_is_never_resolved_by_later_success(tmp_path):
    gateway = proxy(tmp_path, policies=(policy(),))
    args = {"project_id": str(gateway.authorization.project_id), "version": 0}
    await gateway.call("flowtest.inspect_contract", args)
    await gateway.call("flowtest.inspect_contract", {**args, "version": 1})
    gateway.receipts[0] = gateway.receipts[0].model_copy(update={"outcome": "unknown"})
    with pytest.raises(HarnessError, match="UNRESOLVED_OR_UNKNOWN"):
        resolve_known_read_errors(gateway)
