"""Offline adapter tests only; no model, network, real authentication or CLI exec."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.types import CallToolResult, Tool
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_contracts import (  # noqa: E402
    HostAuthorization,
    HostBudget,
    ReviewedWorkflowBinding,
)
from scripts.selftest.host_gateway import BoundedGateway  # noqa: E402
from scripts.selftest.host_launch import (  # noqa: E402
    CodexLaunchPlan,
    HostDeployment,
    HostReadiness,
    VerifiedGrant,
    launch_plan,
    readiness,
    verify_authorization,
)
from scripts.selftest.io import HarnessError  # noqa: E402


def authorization(**changes):
    now = datetime.now(UTC)
    value = {
        "authorization_id": uuid4(),
        "approved_by": "human-budget-owner",
        "host_id": "isolated-codex",
        "model": "explicitly-authorized-model",
        "provider": "openai",
        "cli_version": "codex-cli 0.163.0-alpha.11",
        "project_id": uuid4(),
        "batch_key": "host-synthetic-batch",
        "environment_ids": (uuid4(),),
        "task_digest": "a" * 64,
        "skill_digest": "b" * 64,
        "authorized_data_digest": "c" * 64,
        "policy_digest": "d" * 64,
        "allowed_tools": ("flowtest.inspect_contract",),
        "reviewer_ids": (uuid4(),),
        "budget": HostBudget(
            maximum_tool_calls=2,
            wall_seconds=10,
            maximum_prompt_bytes=1024,
            maximum_result_bytes=1024,
            maximum_total_result_bytes=2048,
        ),
        "approved_at": now,
        "expires_at": now + timedelta(minutes=10),
    }
    value.update(changes)
    return HostAuthorization.model_validate(value)


def deployment(value):
    return HostDeployment(
        value.host_id,
        Path("/trusted/codex"),
        value.cli_version,
        Path("/private/host-auth"),
        Path("/private/job"),
        Path("/trusted/relay"),
        Path("/private/job/proxy.sock"),
        value.skill_digest,
        value.authorized_data_digest,
        value.task_digest,
        "e" * 64,
        True,
        value.policy_digest,
    )


class Upstream:
    def __init__(self):
        self.calls = []
        self.result = CallToolResult(content=[], structured_content={"data": {"persisted": False}})

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def gateway(tmp_path, auth=None, upstream=None):
    value = auth or authorization()
    tool = Tool(
        name="flowtest.inspect_contract",
        description="frozen synthetic contract",
        input_schema={
            "type": "object",
            "required": ["project_id"],
            "properties": {"project_id": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    target = upstream or Upstream()
    return BoundedGateway(
        authorization=value,
        attempt_id=uuid4(),
        phase="workflow",
        catalog=(tool,),
        upstream=target,
        directory=tmp_path,
        deadline=datetime.now(UTC) + timedelta(seconds=60),
    ), target


def test_no_authorization_never_creates_launch_command():
    value = authorization()
    result = launch_plan(
        None,
        deployment(value),
        prompt="synthetic",
        schema=Path("/schema"),
        output=Path("/out"),
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert isinstance(result, HostReadiness)
    assert result.status == "NOT_RUN" and result.reason_codes == ("HOST_AUTHORIZATION_PENDING",)


def test_signed_grant_still_requires_deployment_digest_allowlist():
    value = authorization()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    token = jwt.encode(
        {
            "iss": "trusted-budget",
            "aud": "flowtest-host",
            "sub": value.approved_by,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "authorization": value.model_dump(mode="json"),
        },
        private,
        algorithm="RS256",
    )
    with pytest.raises(HarnessError, match="NOT_DEPLOYMENT_APPROVED"):
        verify_authorization(
            token,
            public_key=public,
            algorithm="RS256",
            issuer="trusted-budget",
            audience="flowtest-host",
            allowed_digests=frozenset(),
        )
    digest = canonical_digest(value.model_dump(mode="json"))
    grant = verify_authorization(
        token,
        public_key=public,
        algorithm="RS256",
        issuer="trusted-budget",
        audience="flowtest-host",
        allowed_digests=frozenset({digest}),
    )
    assert grant.authorization == value


@pytest.mark.parametrize(
    "field", ["skill_digest", "data_digest", "task_digest", "host_id", "cli_version"]
)
def test_frozen_source_or_host_drift_prevents_launch(field):
    value = authorization()
    env = replace(deployment(value), **{field: "changed"})
    assert readiness(VerifiedGrant(value, "e" * 64), env).status == "NOT_RUN"


def test_read_only_sandbox_is_not_accepted_as_secret_isolation_proof():
    value = authorization()
    env = replace(deployment(value), tool_isolation_attestation=None)
    assert (
        "HOST_TOOL_ISOLATION_UNVERIFIED"
        in readiness(VerifiedGrant(value, "e" * 64), env).reason_codes
    )


def test_hard_provider_cap_must_be_independently_proven():
    value = authorization(
        budget=HostBudget(
            maximum_tool_calls=2,
            wall_seconds=10,
            maximum_prompt_bytes=1024,
            maximum_result_bytes=1024,
            maximum_total_result_bytes=2048,
            require_hard_provider_cap=True,
            provider_cap_reference="approved-provider-quota",
        )
    )
    env = replace(deployment(value), provider_cap_verified=False)
    assert (
        "HOST_PROVIDER_CAP_UNVERIFIED"
        in readiness(VerifiedGrant(value, "e" * 64), env).reason_codes
    )


def test_command_is_review_only_explicit_model_and_contains_no_application_credentials():
    value = authorization()
    plan = launch_plan(
        VerifiedGrant(value, "e" * 64),
        deployment(value),
        prompt="synthetic",
        schema=Path("/schema"),
        output=Path("/out"),
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    assert isinstance(plan, CodexLaunchPlan)
    assert "--ignore-user-config" in plan.arguments and "--ephemeral" in plan.arguments
    assert plan.arguments[plan.arguments.index("--model") + 1] == value.model
    assert "features.shell_tool=false" in plan.arguments
    assert "project_doc_max_bytes=0" in plan.arguments
    assert "project_doc_fallback_filenames=[]" in plan.arguments
    assert 'web_search="disabled"' in plan.arguments
    assert "model_providers.openai.request_max_retries=0" in plan.arguments
    assert dict(plan.environment) == {"CODEX_HOME": "/private/host-auth", "LANG": "en_US.UTF-8"}
    assert plan.deadline <= datetime.now(UTC) + timedelta(seconds=10)


def test_naive_authorization_timestamp_and_boolean_budget_rejected():
    with pytest.raises(ValidationError):
        authorization(approved_at=datetime.now())
    with pytest.raises(ValidationError):
        HostBudget(
            maximum_tool_calls=True,
            wall_seconds=10,
            maximum_prompt_bytes=1024,
            maximum_result_bytes=1024,
            maximum_total_result_bytes=2048,
        )


@pytest.mark.asyncio
async def test_allowed_tool_calls_actual_upstream_and_saves_only_digests(tmp_path):
    proxy, target = gateway(tmp_path)
    args = {"project_id": str(proxy.authorization.project_id)}
    result = await proxy.call("flowtest.inspect_contract", args)
    assert result == target.result and len(target.calls) == 1
    receipt = proxy.receipts[0]
    assert receipt.outcome == "completed" and receipt.result_digest
    raw = (tmp_path / "tool-receipts" / "001.json").read_text()
    assert "frozen synthetic contract" not in raw and "Authorization" not in raw
    assert "structured_content" not in raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool",
    ["flowtest.preview_flow_proposal", "flowtest.publish", "flowtest.execute", "flowtest.approve"],
)
async def test_model_cannot_exceed_human_review_boundary(tmp_path, tool):
    proxy, target = gateway(tmp_path)
    result = await proxy.call(tool, {"project_id": str(proxy.authorization.project_id)})
    assert result.is_error and target.calls == []
    assert proxy.receipts[0].outcome == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [False, True])
async def test_cross_project_and_extra_schema_arguments_never_reach_upstream(tmp_path, extra):
    proxy, target = gateway(tmp_path)
    args = {"project_id": str(proxy.authorization.project_id) if extra else str(uuid4())}
    if extra:
        args["token"] = "synthetic-canary"
    await proxy.call("flowtest.inspect_contract", args)
    assert target.calls == [] and len(proxy.receipts) == 1 and proxy.stopped.is_set()
    assert proxy.receipts[0].reason_code == (
        "HOST_TOOL_ARGUMENTS_INVALID" if extra else "HOST_PROJECT_BINDING_CHANGED"
    )


@pytest.mark.asyncio
async def test_concurrent_calls_cannot_multiply_tool_budget(tmp_path):
    import asyncio

    proxy, target = gateway(tmp_path)
    args = {"project_id": str(proxy.authorization.project_id)}
    results = await asyncio.gather(
        *(proxy.call("flowtest.inspect_contract", args) for _ in range(5))
    )
    assert len(target.calls) == 2 and len(proxy.receipts) == 2
    assert sum(result.is_error is True for result in results) == 3


@pytest.mark.asyncio
async def test_deadline_rejects_before_call_without_mutating_native_results(tmp_path):
    proxy, target = gateway(tmp_path)
    proxy.deadline = datetime.now(UTC) - timedelta(seconds=1)
    result = await proxy.call(
        "flowtest.inspect_contract", {"project_id": str(proxy.authorization.project_id)}
    )
    assert result.is_error and target.calls == [] and proxy.receipts == []


@pytest.mark.asyncio
async def test_result_size_limit_rejects_without_exposing_full_value(tmp_path):
    proxy, target = gateway(tmp_path)
    target.result = CallToolResult(content=[], structured_content={"oversize": "x" * 2048})
    result = await proxy.call(
        "flowtest.inspect_contract", {"project_id": str(proxy.authorization.project_id)}
    )
    assert result.is_error and proxy.receipts[0].reason_code == "HOST_TOOL_RESULT_BUDGET_EXCEEDED"
    assert "oversize" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_pending_receipt_precedes_real_call_and_unknown_failure_is_not_replayed(tmp_path):
    from scripts.selftest.host_contracts import HostToolReceipt

    class BrokenUpstream:
        async def call_tool(self, name, arguments):
            saved = HostToolReceipt.model_validate_json(
                (tmp_path / "tool-receipts/001.json").read_bytes()
            )
            assert saved.outcome == "pending" and saved.completed_at is None
            raise ConnectionError("synthetic transport loss; no retry")

    proxy, _ = gateway(tmp_path, upstream=BrokenUpstream())
    result = await proxy.call(
        "flowtest.inspect_contract", {"project_id": str(proxy.authorization.project_id)}
    )
    assert result.is_error and proxy.receipts[0].outcome == "unknown"
    restored, _ = gateway(tmp_path, auth=proxy.authorization)
    restored.attempt_id = proxy.attempt_id
    with pytest.raises(HarnessError, match="CANNOT_RESUME"):
        restored.restore_receipts()


@pytest.mark.asyncio
async def test_business_error_is_preserved_separately_from_protocol_completion(tmp_path):
    proxy, target = gateway(tmp_path)
    target.result = CallToolResult(
        content=[], structured_content={"data": {"error": {"code": "BLOCKED"}}}
    )
    result = await proxy.call(
        "flowtest.inspect_contract", {"project_id": str(proxy.authorization.project_id)}
    )
    assert result == target.result
    assert proxy.receipts[0].outcome == "completed"
    assert proxy.receipts[0].business_success is False


@pytest.mark.asyncio
async def test_case_phase_requires_exact_human_published_bindings_and_keeps_shared_budget(tmp_path):

    value = authorization(
        allowed_tools=("flowtest.propose_test_design", "flowtest.propose_flow_draft")
    )
    tools = tuple(Tool(name=name, input_schema={"type": "object"}) for name in value.allowed_tools)
    target = Upstream()
    proxy = BoundedGateway(
        authorization=value,
        attempt_id=uuid4(),
        phase="workflow",
        catalog=tools,
        upstream=target,
        directory=tmp_path,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    early = await proxy.call(
        "flowtest.propose_test_design", {"project_id": str(value.project_id), "test_cases": []}
    )
    assert early.is_error and target.calls == []
    assert proxy.stopped.is_set()
    # A rejected phase cannot be resumed. The positive path owns a separate approved attempt.
    proxy = BoundedGateway(
        authorization=value,
        attempt_id=uuid4(),
        phase="workflow",
        catalog=tools,
        upstream=target,
        directory=tmp_path / "positive",
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    await proxy.call(
        "flowtest.propose_flow_draft",
        {
            "project_id": str(value.project_id),
            "idempotency_key": value.batch_key + ":read",
            "source_ref": "mcp://selftest/" + value.batch_key + "/read",
        },
    )
    binding = ReviewedWorkflowBinding(workflow_id=uuid4(), version=2, fingerprint="a" * 64)
    proxy.begin_case_phase((binding,))
    selected = {
        "project_id": str(value.project_id),
        "idempotency_key": value.batch_key + ":case",
        "source_ref": "mcp://selftest/" + value.batch_key + "/case",
        "test_cases": [
            {
                "definition": {
                    "workflow_id": str(binding.workflow_id),
                    "workflow_version": binding.version,
                    "environment_id": str(value.environment_ids[0]),
                }
            }
        ],
    }
    actual = await proxy.call("flowtest.propose_test_design", selected)
    exhausted = await proxy.call("flowtest.propose_test_design", selected)
    assert not actual.is_error and exhausted.is_error and len(target.calls) == 2
    assert [item.phase for item in proxy.receipts] == ["workflow", "case"]


def test_explicit_unknown_cost_authorization_needs_no_invented_provider_quota():
    value = authorization()
    assert not value.budget.require_hard_provider_cap
    assert (
        readiness(
            VerifiedGrant(value, "e" * 64), replace(deployment(value), provider_cap_verified=False)
        ).status
        == "ready"
    )


@pytest.mark.asyncio
async def test_real_sdk22_stdio_proxy_protocol_without_model_or_upstream_credentials(tmp_path):
    import asyncio
    import sys
    from tempfile import TemporaryDirectory

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from scripts.selftest.host_ipc import PrivateMCPRelay

    proxy, target = gateway(tmp_path)
    with TemporaryDirectory(prefix="fh-", dir="/tmp") as private:
        socket_path = Path(private) / "mcp.sock"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "scripts/selftest/host_proxy_stdio.py"), "--socket", str(socket_path)],
            env={"LANG": "en_US.UTF-8"},
        )
        async with (
            asyncio.timeout(10),
            PrivateMCPRelay(proxy, socket_path),
            stdio_client(parameters) as streams,
            ClientSession(*streams) as session,
        ):
            await session.discover()
            listing = await session.list_tools()
            assert [tool.name for tool in listing.tools] == ["flowtest.inspect_contract"]
            result = await session.call_tool(
                "flowtest.inspect_contract",
                arguments={"project_id": str(proxy.authorization.project_id)},
            )
            assert isinstance(result, CallToolResult)
            assert result.structured_content == target.result.structured_content
        assert not socket_path.exists()
    assert len(target.calls) == 1 and len(proxy.receipts) == 1


def test_unscoped_account_and_project_inventory_cannot_be_granted(tmp_path):
    from scripts.selftest.host_gateway import SAFE_TOOLS

    assert "flowtest.list_projects" not in SAFE_TOOLS
    assert "flowtest.inspect_connection" not in SAFE_TOOLS
    for name in ("flowtest.list_projects", "flowtest.inspect_connection"):
        with pytest.raises(HarnessError, match="TOOL_ALLOWLIST_INVALID"):
            gateway(tmp_path, auth=authorization(allowed_tools=(name,)))
