"""Credential-free model-facing MCP facade with a trusted H-owned upstream session."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Literal, Protocol
from uuid import UUID

import httpx
from jsonschema import Draft202012Validator
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.host_contracts import (
    HostAuthorization,
    HostStopReceipt,
    HostToolReceipt,
    ReviewedWorkflowBinding,
)
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    integer_value,
    object_value,
    text_value,
    write_json,
)

# Deliberately excludes preview, import commit, credential, review, publish, run and cancellation.
SAFE_TOOLS = frozenset(
    {
        "flowtest.inspect_project",
        "flowtest.inspect_project_readiness",
        "flowtest.find_assets",
        "flowtest.inspect_contract",
        "flowtest.discover_services",
        "flowtest.generate_test_design",
        "flowtest.analyze_test_coverage",
        "flowtest.begin_test_context",
        "flowtest.inspect_context_requirements",
        "flowtest.inspect_test_context",
        "flowtest.plan_integration_test",
        "flowtest.validate_integration_plan",
        "flowtest.compile_integration_flowspec",
        "flowtest.compile_test_design",
        "flowtest.validate_flowspec",
        "flowtest.explain_compiler_diagnostics",
        "flowtest.propose_flow_draft",
        "flowtest.propose_simple_flow",
        "flowtest.inspect_flow_proposal",
        "flowtest.propose_test_design",
    }
)


class ToolUpstream(Protocol):
    async def call_tool(self, name: str, arguments: JsonObject) -> CallToolResult: ...


@dataclass(frozen=True)
class ToolExchange:
    sequence: int
    name: str
    arguments: JsonObject
    result: CallToolResult


def _error(code: str) -> CallToolResult:
    return CallToolResult(
        is_error=True,
        content=[TextContent(type="text", text=code)],
        structured_content={"error": {"code": code}},
    )


class BoundedGateway:
    safe_tools: ClassVar[frozenset[str]] = SAFE_TOOLS

    def __init__(
        self,
        *,
        authorization: HostAuthorization,
        attempt_id: UUID,
        phase: Literal["workflow", "case", "diagnosis"],
        catalog: tuple[Tool, ...],
        upstream: ToolUpstream,
        directory: Path,
        deadline: datetime,
    ) -> None:
        granted = frozenset(authorization.allowed_tools)
        if not granted <= self.safe_tools or len(granted) != len(authorization.allowed_tools):
            raise HarnessError("HOST_TOOL_ALLOWLIST_INVALID")
        self.authorization, self.attempt_id, self.phase = authorization, attempt_id, phase
        self.upstream, self.directory = upstream, directory
        self.deadline = min(
            deadline,
            authorization.expires_at,
            datetime.now(UTC) + timedelta(seconds=authorization.budget.wall_seconds),
        )
        self.catalog = tuple(tool for tool in catalog if tool.name in granted)
        if {tool.name for tool in self.catalog} != granted:
            raise HarnessError("HOST_REQUIRED_TOOL_UNAVAILABLE")
        self.schemas = {tool.name: tool.input_schema for tool in self.catalog}
        self.catalog_digest = canonical_digest(
            [tool.model_dump(mode="json", by_alias=True) for tool in catalog]
        )
        self.receipts: list[HostToolReceipt] = []
        self.result_bytes = 0
        self.lock = asyncio.Lock()
        self.stopped = asyncio.Event()
        self.stop_receipt: HostStopReceipt | None = None
        # H consumes these exact typed tool results to validate proposals. No token enters a result.
        self.results: list[tuple[str, CallToolResult]] = []
        self.exchanges: list[ToolExchange] = []
        self.reviewed_workflows: tuple[ReviewedWorkflowBinding, ...] = ()

    def server(self) -> Server:
        # SDK 2.2 uses callbacks on the constructor, not legacy @list_tools decorators.
        async def listing(_context: object, _params: object) -> ListToolsResult:
            visible = [tool for tool in self.catalog if self._visible(tool.name)]
            return ListToolsResult(tools=visible)

        async def calling(_context: object, params: CallToolRequestParams) -> CallToolResult:
            return await self.call(params.name, object_value(params.arguments or {}))

        return Server(
            "flowtest-bounded-host-proxy",
            version="draft-v1",
            on_list_tools=listing,
            on_call_tool=calling,
        )

    def _visible(self, name: str) -> bool:
        if self.phase == "workflow":
            return name != "flowtest.propose_test_design"
        return name not in {"flowtest.propose_flow_draft", "flowtest.propose_simple_flow"}

    def begin_case_phase(self, workflows: tuple[ReviewedWorkflowBinding, ...]) -> None:
        if self.phase != "workflow" or not workflows or len(workflows) > 3:
            raise HarnessError("HOST_REVIEWED_WORKFLOW_BINDINGS_INVALID")
        if len({item.workflow_id for item in workflows}) != len(workflows):
            raise HarnessError("HOST_REVIEWED_WORKFLOW_BINDINGS_DUPLICATED")
        if "flowtest.propose_test_design" not in self.schemas:
            raise HarnessError("HOST_CASE_TOOL_UNAVAILABLE")
        self.reviewed_workflows = workflows
        self.phase = "case"

    def restore_receipts(self) -> None:
        if self.receipts:
            raise HarnessError("HOST_RECEIPTS_ALREADY_LOADED")
        if (self.directory / "host-stop.json").exists():
            raise HarnessError("HOST_STOPPED_ATTEMPT_CANNOT_RESUME")
        paths = sorted((self.directory / "tool-receipts").glob("*.json"))
        for index, path in enumerate(paths, start=1):
            receipt = HostToolReceipt.model_validate_json(path.read_bytes())
            if (
                receipt.sequence != index
                or receipt.attempt_id != self.attempt_id
                or receipt.catalog_digest != self.catalog_digest
                or receipt.outcome in {"pending", "unknown"}
            ):
                raise HarnessError("HOST_TOOL_RECEIPT_CANNOT_RESUME")
            self.receipts.append(receipt)
            self.result_bytes += receipt.result_bytes
        if len(self.receipts) > self.authorization.budget.maximum_tool_calls:
            raise HarnessError("HOST_TOOL_RECEIPT_BUDGET_CHANGED")

    def _authorize_phase(self, name: str, arguments: JsonObject) -> None:
        if name == "flowtest.propose_test_design":
            if self.phase != "case" or not self.reviewed_workflows:
                raise HarnessError("HOST_HUMAN_REVIEW_REQUIRED")
            values = arguments.get("test_cases")
            if not isinstance(values, list):
                raise HarnessError("HOST_CASE_BINDINGS_MISSING")
            selected = tuple(
                object_value(object_value(value).get("definition")) for value in values
            )
            expected = {(str(item.workflow_id), item.version) for item in self.reviewed_workflows}
            actual = tuple(
                (text_value(item.get("workflow_id")), integer_value(item.get("workflow_version")))
                for item in selected
            )
            if not actual or len(actual) != len(set(actual)) or not set(actual) <= expected:
                raise HarnessError("HOST_PUBLISHED_WORKFLOW_BINDING_CHANGED")
            if any(
                item.get("environment_id")
                not in {str(value) for value in self.authorization.environment_ids}
                for item in selected
            ):
                raise HarnessError("HOST_ENVIRONMENT_BINDING_CHANGED")
        elif self.phase == "case" and name in {
            "flowtest.propose_flow_draft",
            "flowtest.propose_simple_flow",
        }:
            raise HarnessError("HOST_REVIEWED_WORKFLOW_REWRITE_FORBIDDEN")

    def _authorize(self, name: str, arguments: JsonObject) -> None:
        if name not in self.schemas:
            raise HarnessError("HOST_TOOL_NOT_ALLOWED")
        if not Draft202012Validator(self.schemas[name]).is_valid(arguments):
            raise HarnessError("HOST_TOOL_ARGUMENTS_INVALID")
        self._authorize_project_scope(name, arguments)
        self._authorize_phase(name, arguments)
        if name in {
            "flowtest.propose_flow_draft",
            "flowtest.propose_simple_flow",
            "flowtest.propose_test_design",
        }:
            prefix = self.authorization.batch_key + ":"
            if not str(arguments.get("idempotency_key", "")).startswith(prefix):
                raise HarnessError("HOST_PROPOSAL_BATCH_KEY_CHANGED")
            if name != "flowtest.propose_simple_flow" and not str(
                arguments.get("source_ref", "")
            ).startswith("mcp://selftest/" + self.authorization.batch_key + "/"):
                raise HarnessError("HOST_PROPOSAL_SOURCE_REF_CHANGED")
        candidates = (arguments, object_value(arguments.get("request", {})))
        for scope in candidates:
            if "project_id" in scope and scope["project_id"] != str(self.authorization.project_id):
                raise HarnessError("HOST_PROJECT_BINDING_CHANGED")
            if "environment_id" in scope and scope["environment_id"] not in {
                str(value) for value in self.authorization.environment_ids
            }:
                raise HarnessError("HOST_ENVIRONMENT_BINDING_CHANGED")

    def _authorize_project_scope(self, name: str, arguments: JsonObject) -> None:
        pure = {
            "flowtest.compile_integration_flowspec",
            "flowtest.validate_integration_plan",
            "flowtest.explain_compiler_diagnostics",
        }
        if name in pure:
            plan = object_value(arguments.get("plan"))
            revisions = {
                object_value(object_value(item.result.structured_content).get("data", {})).get(
                    "context_revision_id"
                )
                for item in self.exchanges
                if item.name == "flowtest.plan_integration_test" and business_success(item.result)
            }
            if plan.get("context_revision_id") not in revisions:
                raise HarnessError("HOST_CONTEXT_NOT_OBSERVED_IN_AUTHORIZED_PROJECT")
        elif not any(
            "project_id" in scope
            for scope in (arguments, object_value(arguments.get("request", {})))
        ):
            raise HarnessError("HOST_PROJECT_SCOPE_REQUIRED")

    async def call(self, name: str, arguments: JsonObject) -> CallToolResult:
        async with self.lock:
            if self.stopped.is_set():
                return self._stop(
                    self.stop_receipt.reason_code if self.stop_receipt else "HOST_STOPPED",
                    name,
                    arguments,
                )
            if len(self.receipts) >= self.authorization.budget.maximum_tool_calls:
                return self._stop("HOST_TOOL_BUDGET_EXCEEDED", name, arguments)
            if self.result_bytes >= self.authorization.budget.maximum_total_result_bytes:
                return self._stop("HOST_TOOL_RESULT_BUDGET_EXCEEDED", name, arguments)
            if datetime.now(UTC) >= self.deadline:
                return self._stop("HOST_DEADLINE_EXCEEDED", name, arguments)
            started = datetime.now(UTC)
            receipt = HostToolReceipt(
                sequence=len(self.receipts) + 1,
                attempt_id=self.attempt_id,
                phase=self.phase,
                tool_name=name if name in self.schemas else "rejected_tool",
                request_digest=canonical_digest({"name": name, "arguments": arguments}),
                result_digest=None,
                catalog_digest=self.catalog_digest,
                started_at=started,
                completed_at=None,
                outcome="pending",
            )
            self.receipts.append(receipt)
            path = self.directory / "tool-receipts" / f"{receipt.sequence:03}.json"
            write_json(path, receipt)
            result = None
            outcome: Literal["completed", "rejected", "unknown"] = "unknown"
            reason: str | None = "HOST_TOOL_RESULT_UNKNOWN"
            try:
                self._authorize(name, arguments)
                timeout = max(0.001, (self.deadline - datetime.now(UTC)).total_seconds())
                result = await asyncio.wait_for(
                    self.upstream.call_tool(name, arguments), timeout=timeout
                )
                self._bound_result(result)
                outcome, reason = "completed", None
            except HarnessError as error:
                outcome, reason = "rejected", str(error)
            except (TimeoutError, ConnectionError, MCPError, httpx.HTTPError):
                outcome, reason = "unknown", "HOST_TOOL_RESULT_UNKNOWN"
            finally:
                receipt = receipt.model_copy(
                    update={
                        "result_digest": canonical_digest(
                            result.model_dump(mode="json", by_alias=True)
                        )
                        if result
                        else None,
                        "completed_at": datetime.now(UTC),
                        "outcome": outcome,
                        "reason_code": reason,
                        "business_success": business_success(result) if result else None,
                        "error_code": structured_error_code(result) if result else reason,
                        "result_bytes": len(result.model_dump_json(by_alias=True).encode())
                        if result
                        else 0,
                    }
                )
                self.receipts[-1] = receipt
                write_json(path, receipt)
            if reason:
                return self._stop(reason, name, arguments)
            if result is None:
                return _error("HOST_TOOL_RESULT_MISSING")
            self.results.append((name, result))
            self.exchanges.append(ToolExchange(receipt.sequence, name, arguments, result))
            if not business_success(result) and not any(
                policy.tool_name == name and structured_error_code(result) in policy.error_codes
                for policy in self.authorization.read_only_repairs
            ):
                self._stop("HOST_UNRESOLVED_OR_UNKNOWN_TOOL_FAILURE", name, arguments)
            return result

    def _stop(self, code: str, name: str, arguments: JsonObject) -> CallToolResult:
        now = datetime.now(UTC)
        current = self.stop_receipt
        if current is None:
            self.stop_receipt = HostStopReceipt(
                attempt_id=self.attempt_id,
                reason_code=code,
                first_rejected_at=now,
                last_rejected_at=now,
                admitted_calls=len(self.receipts),
                rejected_calls=1,
                first_tool_name=name[:160],
                first_request_digest=canonical_digest({"name": name, "arguments": arguments}),
            )
        else:
            self.stop_receipt = current.model_copy(
                update={
                    "last_rejected_at": now,
                    "rejected_calls": min(100, current.rejected_calls + 1),
                    "rejected_count_truncated": current.rejected_count_truncated
                    or current.rejected_calls >= 100,
                }
            )
        write_json(self.directory / "host-stop.json", self.stop_receipt)
        self.stopped.set()
        return _error(code)

    def _bound_result(self, result: CallToolResult) -> None:
        encoded = result.model_dump_json(by_alias=True).encode()
        limit = self.authorization.budget
        self.result_bytes += len(encoded)
        if (
            len(encoded) > limit.maximum_result_bytes
            or self.result_bytes > limit.maximum_total_result_bytes
        ):
            raise HarnessError("HOST_TOOL_RESULT_BUDGET_EXCEEDED")


def business_success(result: CallToolResult) -> bool:
    if result.is_error or result.structured_content is None:
        return False
    structured = object_value(result.structured_content)
    data = object_value(structured.get("data", structured))
    return "error" not in data


def structured_error_code(result: CallToolResult) -> str | None:
    if result.structured_content is None:
        return None
    structured = object_value(result.structured_content)
    error = object_value(object_value(structured.get("data", structured)).get("error", {}))
    code = error.get("code")
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code) else None
