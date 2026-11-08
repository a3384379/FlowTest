"""One shared admission counter covers both SDK principals and candidate API calls."""

import asyncio
from datetime import UTC, datetime

from mcp.types import CallToolResult
from scripts.selftest.io import HarnessError, JsonObject
from scripts.selftest.mcp_governance_contracts import Result
from scripts.selftest.mcp_governance_runner import tool_projection
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_protocol_runner import ProtocolClient


class QualityProtocol(ProtocolClient):
    def __init__(
        self, delegate: ProtocolClient, budget: ProtocolHttpBudget, deadline: datetime
    ) -> None:
        self._delegate, self._budget, self.deadline = delegate, budget, deadline
        self.batch_key, self.transport = delegate.batch_key, delegate.transport
        self.receipts, self.catalog_digest = delegate.receipts, delegate.catalog_digest
        self.last_structured_result = None

    def _admit(self) -> None:
        if not self._budget.reserve_tool():
            raise HarnessError("SELFTEST_QUALITY_SHARED_TOOL_BUDGET_EXCEEDED")
        count = 2 if self.transport == "streamable-http" else 1
        if not all(self._budget.reserve() for _ in range(count)):
            raise HarnessError("SELFTEST_QUALITY_SHARED_HTTP_BUDGET_EXCEEDED")

    def _remaining(self) -> float:
        seconds = (self.deadline - datetime.now(UTC)).total_seconds()
        if seconds <= 0:
            raise HarnessError("SELFTEST_QUALITY_DEADLINE_EXCEEDED")
        return seconds

    async def call(
        self,
        tool_name: str,
        arguments: JsonObject,
        *,
        scenario_id: str,
        phase: str,
    ) -> JsonObject:
        self._admit()
        async with asyncio.timeout(self._remaining()):
            result = await self._delegate.call(
                tool_name, arguments, scenario_id=scenario_id, phase=phase
            )
            self.last_structured_result = self._delegate.last_structured_result
            return result

    async def boundary_call(
        self,
        name: str,
        arguments: JsonObject,
        *,
        scenario_id: str,
    ) -> Result:
        self._admit()
        self._delegate.attempt_count += 1
        async with asyncio.timeout(self._remaining()):
            returned = await self._delegate.session.call_tool(name, arguments=arguments)
        if not isinstance(returned, CallToolResult):
            raise HarnessError("SELFTEST_QUALITY_RAW_TOOL_RESULT_MISSING")
        result = tool_projection(returned, name)
        self._delegate._record(
            name,
            arguments,
            scenario_id=scenario_id,
            phase="opaque_material_boundary",
            result_digest=result.result_digest,
            success=not returned.is_error and result.business_code is None,
        )
        return result


def reserve_protocol_setup(budget: ProtocolHttpBudget) -> None:
    # Reserve discovery and owned gateway health requests conservatively for each
    # finite session, in addition to actual H API reads and per-tool dispatch.
    if not all(budget.reserve() for _ in range(10)):
        raise HarnessError("SELFTEST_QUALITY_PROTOCOL_SETUP_BUDGET_EXCEEDED")
