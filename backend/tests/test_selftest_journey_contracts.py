"""Runner boundary behavior; these checks do not replace real transport acceptance."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession
from mcp.types import CallToolResult
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import FixturePayload, FixtureRequest
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, PublicAPI
from scripts.selftest.mcp_generation_journey import import_operation
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.review_fixture_driver import ReviewedCase
from scripts.selftest.start_plan import launch_plan, prepare_plan


def test_real_default_fixture_response_retains_empty_synthetic_values() -> None:
    payload = FixturePayload(
        actual=1,
        code=0,
        marker="",
        branch="",
        iteration_key="",
        request_count=1,
        fixture_epoch="epoch-1",
    )
    request = FixtureRequest(
        sequence=1,
        method="GET",
        path="/selftest/batch/scenario/request",
        response_status=200,
        marker="",
        response_body=payload,
    )
    assert request.response_body is not None
    assert request.response_body.marker == ""
    assert request.response_body.value is None
    with pytest.raises(ValidationError):
        FixturePayload(marker="x" * 201)


def test_protocol_exception_group_preserves_code_without_payload_or_credential() -> None:
    error = ExceptionGroup(
        "task group may include private provider payload",
        [
            ExceptionGroup(
                "SDK error",
                [HarnessError("SELFTEST_MCP_TOOL_ERROR:trace=private-secret")],
            ),
            ValueError("malformed payload with private-secret"),
            HarnessError("SELFTEST_MCP_TOOL_ERROR:another private-secret"),
        ],
    )
    assert failure_codes(error) == ("SELFTEST_MCP_TOOL_ERROR", "SELFTEST_VALUEERROR")
    assert "private-secret" not in str(failure_codes(error))


async def test_protocol_failure_retains_safe_code_and_hashes_without_error_payload(
    tmp_path: Path,
) -> None:
    session = AsyncMock(spec=ClientSession)
    session.protocol_version = "2026-07-28"
    session.call_tool.return_value = CallToolResult(
        content=[],
        structuredContent={
            "data": {"error": {"code": "TEST_CONTEXT_NOT_FOUND", "message": "private-secret"}},
        },
    )
    client = ProtocolClient(session, "stdio", "batch-1", tmp_path)
    client.catalog_digest = "a" * 64
    client.tools = frozenset({"flowtest.compile_test_design"})
    client.tool_schemas = {"flowtest.compile_test_design": {"type": "object"}}
    with pytest.raises(HarnessError, match="SELFTEST_MCP_CALL_REJECTED_TEST_CONTEXT_NOT_FOUND"):
        await client.call(
            "flowtest.compile_test_design",
            {"request": {"secret": "private-secret"}},
            scenario_id="scenario-1",
            phase="compilation",
        )
    assert len(client.receipts) == 1
    assert client.receipts[0].success is False
    records = "".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert "private-secret" not in records
    assert "TEST_CONTEXT_NOT_FOUND" in records


async def test_live_catalog_required_argument_blocks_before_tool_call(tmp_path: Path) -> None:
    session = AsyncMock(spec=ClientSession)
    client = ProtocolClient(session, "stdio", "batch-1", tmp_path)
    client.tools = frozenset({"flowtest.inspect_connection"})
    client.tool_schemas = {
        "flowtest.inspect_connection": {
            "type": "object",
            "required": ["request"],
            "properties": {"request": {"type": "object"}},
        }
    }
    with pytest.raises(HarnessError, match="SELFTEST_MCP_ARGUMENTS_INVALID"):
        await client.call(
            "flowtest.inspect_connection", {}, scenario_id="batch", phase="connection"
        )
    session.call_tool.assert_not_awaited()


@pytest.mark.parametrize("failure", [TimeoutError, BrokenPipeError, asyncio.CancelledError])
async def test_protocol_transport_failure_retains_attempt_and_consumes_budget(
    tmp_path: Path, failure: type[BaseException]
) -> None:
    session = AsyncMock(spec=ClientSession)
    session.protocol_version = "2026-07-28"
    session.call_tool.side_effect = failure("private-secret")
    client = ProtocolClient(session, "stdio", "batch-1", tmp_path)
    client.catalog_digest = "a" * 64
    client.tools = frozenset({"flowtest.inspect_connection"})
    client.tool_schemas = {"flowtest.inspect_connection": {"type": "object"}}
    client.max_tool_calls = 1
    with pytest.raises(failure):
        await client.call(
            "flowtest.inspect_connection",
            {"request": {"secret": "private-secret"}},
            scenario_id="batch",
            phase="connection",
        )
    assert len(client.receipts) == 1 and client.receipts[0].success is False
    with pytest.raises(HarnessError, match="SELFTEST_MCP_CALL_BUDGET_EXCEEDED"):
        await client.call(
            "flowtest.inspect_connection", {"request": {}}, scenario_id="batch", phase="connection"
        )
    session.call_tool.assert_awaited_once()
    records = "".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert "private-secret" not in records


async def test_protocol_budget_admits_only_one_concurrent_tool_call(tmp_path: Path) -> None:
    started, release = asyncio.Event(), asyncio.Event()

    async def complete(*args: object, **kwargs: object) -> CallToolResult:
        started.set()
        await release.wait()
        return CallToolResult(content=[], structuredContent={"data": {}})

    session = AsyncMock(spec=ClientSession)
    session.protocol_version = "2026-07-28"
    session.call_tool.side_effect = complete
    client = ProtocolClient(session, "stdio", "batch-1", tmp_path)
    client.catalog_digest = "a" * 64
    client.tools = frozenset({"flowtest.inspect_connection"})
    client.tool_schemas = {"flowtest.inspect_connection": {"type": "object"}}
    client.max_tool_calls = 1
    first = asyncio.create_task(
        client.call(
            "flowtest.inspect_connection", {"request": {}}, scenario_id="batch", phase="connection"
        )
    )
    await started.wait()
    try:
        with pytest.raises(HarnessError, match="SELFTEST_MCP_CALL_BUDGET_EXCEEDED"):
            await asyncio.wait_for(
                client.call(
                    "flowtest.inspect_connection",
                    {"request": {}},
                    scenario_id="batch",
                    phase="connection",
                ),
                timeout=0.1,
            )
    finally:
        release.set()
        await first
    session.call_tool.assert_awaited_once()


@pytest.mark.parametrize("unexpected_applied_key", [False, True])
async def test_contract_import_selects_only_this_operation_from_full_diff(
    tmp_path: Path, unexpected_applied_key: bool
) -> None:
    installed = Installation(
        binding_nonce="nonce-1",
        organization_id=uuid4(),
        project_id=uuid4(),
        reviewer_id=uuid4(),
        reviewer_email="reviewer@example.com",
        mcp_account_id=uuid4(),
        target_project_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.com",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
    )
    path, definition_id = "/selftest/new-batch/scenario/request", str(uuid4())
    selected = {
        "method": "GET",
        "path": path,
        "import_key": "wanted",
        "change": "added",
        "definition_id": None,
        "version": 1,
    }
    unrelated = {
        "method": "GET",
        "path": "/selftest/previous-batch/scenario/request",
        "import_key": "old",
        "change": "deleted",
        "definition_id": str(uuid4()),
        "version": 1,
    }
    client = AsyncMock(spec=ProtocolClient)
    client.batch_key = "new-batch"
    client.call.side_effect = [
        {"items": [unrelated, selected], "preview_id": str(uuid4()), "source_sha256": "a" * 64},
        {
            "results": [unrelated, {**selected, "definition_id": definition_id}],
            "applied_keys": ["wanted", "old"] if unexpected_applied_key else ["wanted"],
        },
    ]
    arguments = {
        "installation": installed,
        "scenario_id": "scenario-1",
        "operation": {"method": "GET", "path": path},
        "service_id": str(installed.fixture_service_id),
        "environment_id": str(installed.fixture_environment_id),
        "output_dir": tmp_path,
    }
    if unexpected_applied_key:
        with pytest.raises(HarnessError, match="SELFTEST_CONTRACT_APPLIED_SET_MISMATCH"):
            await import_operation(client, **arguments)
    else:
        result = await import_operation(client, **arguments)
        assert result["definition_id"] == definition_id
    commit = client.call.call_args_list[1].args[1]
    assert commit["request"]["selected_operations"] == ["wanted"]


@pytest.mark.parametrize("change_published_version", [False, True])
async def test_suite_plan_freezes_real_case_version_before_trigger_without_secret_receipt(
    tmp_path: Path, change_published_version: bool
) -> None:
    project, case_id, workflow, environment, suite_id, plan_id, run_id = (
        str(uuid4()) for _ in range(7)
    )
    case = ReviewedCase.model_validate(
        {
            "case": {"id": case_id},
            "version": {
                "version": 3,
                "definition": {
                    "workflow_id": workflow,
                    "workflow_version": 2,
                    "environment_id": environment,
                    "runtime_variables": {},
                    "runtime_headers": {},
                },
            },
            "proposal": {
                "project_id": project,
                "proposal_id": str(uuid4()),
                "item_id": str(uuid4()),
                "route": "controlled_write",
                "review_status": "accepted",
                "materialized_resource_id": case_id,
                "content_fingerprint": "a" * 64,
                "review_mode": "ci_fixture",
                "reviewer_id": str(uuid4()),
            },
        }
    )
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content) if request.content else None
        if request.url.path.endswith("/test-suites"):
            assert body["definition"]["items"] == [
                {"test_case_id": case_id, "test_case_version": 3}
            ]
            return httpx.Response(201, json={"id": suite_id})
        if request.url.path.endswith("/versions"):
            return httpx.Response(
                201,
                json={
                    "version": 1,
                    "fingerprint": "b" * 64,
                    "definition": {
                        "items": [
                            {
                                "test_case_id": case_id,
                                "test_case_version": 4 if change_published_version else 3,
                            }
                        ]
                    },
                },
            )
        if request.url.path.endswith("/test-plans"):
            assert body["items"] == [
                {
                    "target_type": "suite",
                    "target_id": suite_id,
                    "target_version": 1,
                    "max_retries": 0,
                }
            ]
            return httpx.Response(201, json={"id": plan_id, "webhook_secret": "private-secret"})
        assert (tmp_path / "plan-selection.json").exists()
        assert request.headers["Idempotency-Key"] == "batch-1:run"
        return httpx.Response(201, json={"id": run_id})

    api = PublicAPI("http://isolated.example", transport=httpx.MockTransport(respond))
    try:
        if change_published_version:
            with pytest.raises(HarnessError, match="SELFTEST_SUITE_CASE_VERSION_CHANGED"):
                await prepare_plan(
                    api, project_id=project, cases=(case,), batch_key="batch-1", output_dir=tmp_path
                )
            assert len(requests) == 2
            assert not (tmp_path / "plan-selection.json").exists()
        else:
            selection = await prepare_plan(
                api, project_id=project, cases=(case,), batch_key="batch-1", output_dir=tmp_path
            )
            assert len(requests) == 3
            started = await launch_plan(api, selection=selection, batch_key="batch-1")
            assert str(started.run_id) == run_id
            assert started.selection.cases[0].version == 3
            assert "private-secret" not in (tmp_path / "plan-selection.json").read_text()
            assert len(requests) == 4
    finally:
        await api.close()
