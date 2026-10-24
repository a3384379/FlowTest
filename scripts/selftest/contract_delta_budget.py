"""Conservative admission, not a claim of an external network hard limit."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import JsonValue
from scripts.selftest.io import HarnessError, JsonObject, PublicAPI, object_value, write_json
from scripts.selftest.mcp_protocol_runner import ProtocolClient


class DeltaBudget:
    def __init__(self, directory: Path, deadline: datetime) -> None:
        self.path = directory / "request-admission.json"
        self.deadline = deadline
        self.requests = self.tools = self.rejected_requests = self.rejected_tools = 0

    def admit(self, count: int = 1, *, tool: bool = False, cleanup: bool = False) -> None:
        end = self.deadline + timedelta(seconds=15) if cleanup else self.deadline
        expired = datetime.now(UTC) > end
        rejected = expired or self.requests + count > 500 or (tool and self.tools >= 100)
        if rejected:
            self.rejected_requests += count
            self.rejected_tools += int(tool)
        else:
            self.requests += count
            self.tools += int(tool)
        write_json(
            self.path,
            {
                "conservative_request_upper_bound": self.requests,
                "tool_calls": self.tools,
                "rejected_requests": self.rejected_requests,
                "rejected_tool_calls": self.rejected_tools,
                "deadline": self.deadline.isoformat(),
            },
        )
        if rejected:
            raise HarnessError("DELTA_ADMISSION_BUDGET_EXCEEDED")


class DeltaAPI(PublicAPI):
    def __init__(self, api: PublicAPI, budget: DeltaBudget, *, cleanup: bool = False) -> None:
        self.api, self.budget, self.cleanup = api, budget, cleanup

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> JsonValue:
        self.budget.admit(cleanup=self.cleanup)
        return await self.api.request(
            method, path, payload, idempotency_key=idempotency_key, allow_status=allow_status
        )

    async def object(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        self.budget.admit(cleanup=self.cleanup)
        return await self.api.object(method, path, payload, idempotency_key=idempotency_key)

    async def response(
        self, method: str, path: str, payload: JsonObject, idempotency_key: str | None = None
    ) -> tuple[int, JsonObject]:
        self.budget.admit(cleanup=self.cleanup)
        response = await self.api._client.request(
            method, path.lstrip("/"), json=payload, headers=self.api._headers(idempotency_key)
        )
        if len(response.content) > 1048576:
            raise HarnessError("DELTA_BOUNDARY_RESPONSE_TOO_LARGE")
        return response.status_code, object_value(response.json())


class DeltaProtocol(ProtocolClient):
    def __init__(self, discovered: ProtocolClient, budget: DeltaBudget) -> None:
        if discovered.receipts or not discovered.catalog_digest:
            raise HarnessError("DELTA_PROTOCOL_MUST_BE_FRESH_DISCOVERED_SESSION")
        super().__init__(
            discovered.session, discovered.transport, discovered.batch_key, discovered.output_dir
        )
        self.tools, self.tool_schemas = discovered.tools, discovered.tool_schemas
        self.catalog_digest, self.budget = discovered.catalog_digest, budget

    async def call(
        self, tool_name: str, arguments: JsonObject, *, scenario_id: str, phase: str
    ) -> JsonObject:
        # This frozen allowlist uses at most four product HTTP operations per tool
        # in the locked SDK adapters; the upper bound is reserved before dispatch.
        allowed = {
            "flowtest.preview_contract_import",
            "flowtest.commit_contract_import",
            "flowtest.inspect_contract",
            "flowtest.generate_test_design",
            "flowtest.analyze_test_coverage",
            "flowtest.begin_test_context",
            "flowtest.compile_test_design",
            "flowtest.propose_flow_draft",
            "flowtest.propose_test_design",
        }
        if tool_name not in allowed:
            raise HarnessError("DELTA_TOOL_NOT_ALLOWED")
        self.budget.admit(4, tool=True)
        return await super().call(tool_name, arguments, scenario_id=scenario_id, phase=phase)
