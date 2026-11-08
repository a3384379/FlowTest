"""Synthetic CLI -> actual SDK/ASGI diagnosis; no real model or native-run claim."""

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from httpx import ASGITransport
from mcp.types import CallToolResult, Tool
from sqlalchemy import select
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api
from test_s60_continuous_mcp import _account, _counts

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_contracts import HostBudget  # noqa: E402
from scripts.selftest.host_diagnosis import (  # noqa: E402
    DiagnosisConfig,
    DiagnosisGateway,
    _postcheck,
    check_conclusion,
    execute_diagnosis,
    frozen_failure,
    retained_failure,
)
from scripts.selftest.host_diagnosis_contracts import DiagnosisTask  # noqa: E402
from scripts.selftest.host_gateway import BoundedGateway  # noqa: E402
from scripts.selftest.host_launch import CodexLaunchPlan, VerifiedGrant  # noqa: E402
from scripts.selftest.host_product_bridge import materialized_source  # noqa: E402
from scripts.selftest.host_runner import run_process  # noqa: E402
from scripts.selftest.host_verify import verify_host_batch  # noqa: E402
from scripts.selftest.io import HarnessError, write_json  # noqa: E402
from scripts.selftest.run_host_diagnosis import run as diagnosis_cli  # noqa: E402
from test_selftest_host_adapter import authorization  # noqa: E402
from test_selftest_host_observer import fixture  # noqa: E402
from test_selftest_host_quality_boundaries import materialization  # noqa: E402

from app.main import app  # noqa: E402
from app.mcp.client import MCPReadGatewayClient  # noqa: E402
from app.mcp.server import create_mcp_server  # noqa: E402
from app.models.workflows import WorkflowExecution, WorkflowNodeExecution  # noqa: E402
from app.schemas.self_tests import (  # noqa: E402
    ArtifactReference,
    BatchResponse,
    ScenarioResultResponse,
)


def archived(tmp_path):
    manifest, evidence, trail, grant = fixture()
    report = verify_host_batch(
        manifest, evidence, trail=trail, grant=grant, now=evidence.collected_at
    )
    assert report.exit_code == 0
    paths = {}
    digests = {}
    for name, value in (("manifest", manifest), ("evidence", evidence), ("verification", report)):
        path = tmp_path / (name + ".json")
        write_json(path, value)
        paths[name] = path
        digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    actual = evidence.scenarios[0]
    source, execution = actual.provenance, actual.execution
    task = DiagnosisTask(
        project_id=manifest.project_id,
        batch_key="explicit-new-diagnosis",
        origin_batch_id=uuid4(),
        origin_batch_key=manifest.batch_key,
        scenario_id=actual.scenario_id,
        variant_key=actual.variant_key,
        execution_id=execution.id,
        workflow_id=source.workflow.id,
        workflow_version_id=source.workflow.version_id,
        workflow_version=source.workflow.version,
        workflow_fingerprint=source.workflow.fingerprint,
        environment_id=source.case.environment_id,
        error_code=execution.error_code,
        node_id=manifest.scenarios[0].expected.node_id,
        phase="main",
        required_oracles=source.oracle_bindings,
        manifest_sha256=digests["manifest"],
        evidence_sha256=digests["evidence"],
        verification_sha256=digests["verification"],
        expected_digest=canonical_digest(manifest.scenarios[0].expected.model_dump(mode="json")),
        authorized_data_digest=canonical_digest(digests),
    )
    config = DiagnosisConfig.model_construct(
        manifest_file=paths["manifest"],
        evidence_file=paths["evidence"],
        verification_file=paths["verification"],
        attempt_directory=tmp_path / "attempts",
    )
    return config, task


def test_frozen_known_failure_and_required_oracles_are_preserved(tmp_path):
    config, task = archived(tmp_path)
    frozen_failure(config, task)
    for update in (
        {"execution_id": uuid4()},
        {"workflow_fingerprint": "f" * 64},
        {"error_code": "CHANGED"},
        {"phase": "cleanup"},
        {
            "required_oracles": (
                task.required_oracles[0].model_copy(update={"expression": "other"}),
            )
        },
        {"expected_digest": "f" * 64},
    ):
        with pytest.raises(HarnessError):
            frozen_failure(config, task.model_copy(update=update))
    config.evidence_file.write_text("{}")
    with pytest.raises(HarnessError, match="FROZEN_ARTIFACT_CHANGED"):
        frozen_failure(config, task)


FAKE_DIAGNOSIS_CLI = r"""
import asyncio,json,sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client
def event(v): print(json.dumps(v),flush=True)
async def main():
    socket,proxy,source,output=sys.argv[1:5]
    task=json.loads(Path(source).read_text())
    event({"type":"thread.started","thread_id":"synthetic-diagnosis"})
    event({"type":"turn.started"})
    params=StdioServerParameters(command=sys.executable,args=[proxy,"--socket",socket],env={"LANG":"en_US.UTF-8"})
    async with stdio_client(params) as streams:
      async with ClientSession(*streams) as session:
        await session.discover()
        for index,(name,args) in enumerate([
          ("flowtest.inspect_run_evidence",{"execution_id":task["execution_id"]}),
          ("flowtest.diagnose_failure",{"request":{"project_id":task["project_id"],"execution_id":task["execution_id"]}})
        ],1):
          item={"id":"read-"+str(index),"type":"mcp_tool_call","server":"flowtest","tool":name,"arguments":args,"status":"in_progress"}
          event({"type":"item.started","item":item})
          result=await session.call_tool(name,arguments=args)
          item["status"]="completed"
          event({"type":"item.completed","item":item})
        classification=result.structured_content["data"]["diagnosis"]["triage"]["primary_classification"]
    event({"type":"turn.completed","usage":{"input_tokens":13,"output_tokens":8}})
    Path(output).write_text(json.dumps({"phase":"diagnosis","status":"diagnosed","diagnosis":{
      "execution_id":task["execution_id"],"classification":classification,"error_code":task["error_code"],
      "node_id":task["node_id"],"phase":task["phase"],"explanation":"合成CLI对真实工具证据的解释,保留原始产品失败和全部Oracle",
      "supporting_sequences":[1,2]}}))
asyncio.run(main())
"""


@pytest.mark.asyncio
async def test_synthetic_process_uses_actual_sdk_asgi_diagnosis_and_keeps_product_failure(
    failure_repair_api, tmp_path
):
    context = failure_repair_api
    _, token = await _account(context, ["mcp:read"])
    async with context["sessions"]() as session:
        execution = await session.get(WorkflowExecution, context["execution_id"])
        execution.error_code = "WORKFLOW_ASSERTION_FAILED"
        node = await session.scalar(
            select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_execution_id == execution.id,
                WorkflowNodeExecution.node_id == "start",
            )
        )
        node.error_code = execution.error_code
        await session.commit()
        version_id = execution.workflow_version_id
    _, seed = archived(tmp_path)
    task = seed.model_copy(
        update={
            "project_id": context["project_id"],
            "execution_id": context["execution_id"],
            "workflow_id": context["workflow_id"],
            "workflow_version_id": version_id,
            "environment_id": context["environment_id"],
            "node_id": "start",
        }
    )
    auth = authorization(
        project_id=task.project_id,
        batch_key=task.batch_key,
        task_digest=canonical_digest(task.model_dump(mode="json")),
        authorized_data_digest=task.authorized_data_digest,
        environment_ids=(task.environment_id,),
        allowed_tools=("flowtest.inspect_run_evidence", "flowtest.diagnose_failure"),
        budget=HostBudget(
            maximum_tool_calls=2,
            wall_seconds=8,
            maximum_prompt_bytes=131072,
            maximum_result_bytes=65536,
            maximum_total_result_bytes=131072,
        ),
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    before = await _counts(context)
    with TemporaryDirectory(prefix="hd-", dir="/tmp") as location:
        directory = Path(location)
        write_json(directory / "task.json", task)
        fake = directory / "synthetic.py"
        fake.write_text(FAKE_DIAGNOSIS_CLI)
        summary = directory / "summary.json"
        socket = directory / "relay.sock"
        plan = CodexLaunchPlan(
            (
                sys.executable,
                str(fake),
                str(socket),
                str(ROOT / "scripts/selftest/host_proxy_stdio.py"),
                str(directory / "task.json"),
                str(summary),
                "--output-last-message",
                str(summary),
            ),
            directory,
            (("LANG", "en_US.UTF-8"),),
            canonical_digest("synthetic post-run"),
            grant.digest,
            datetime.now(UTC) + timedelta(seconds=8),
        )
        async with MCPReadGatewayClient(
            base_url="http://test", token=token, transport=ASGITransport(app=app)
        ) as client:
            server = create_mcp_server(client=client)

            class ActualSDK:
                async def call_tool(self, name, arguments):
                    return await server.call_tool(name, arguments)

            gateway = DiagnosisGateway(
                task=task,
                grant=grant,
                attempt_id=uuid4(),
                catalog=tuple(await server.list_tools()),
                upstream=ActualSDK(),
                directory=directory,
                deadline=plan.deadline,
            )
            result = await run_process(
                plan,
                prompt="synthetic post-run",
                gateway=gateway,
                socket_path=socket,
                output_dir=directory / "process",
            )
            assert result.receipt.reason_code is None
            check_conclusion(task, gateway, result.receipt)
            assert [item.tool_name for item in gateway.receipts] == list(auth.allowed_tools)
            assert all(item.phase == "diagnosis" for item in gateway.receipts)
            assert result.receipt.summary.diagnosis.classification == "PRODUCT_DEFECT"
            assert result.receipt.summary.diagnosis.changes_applied is False
            changed = result.receipt.summary.diagnosis.model_copy(
                update={"classification": "BAD_TEST"}
            )
            summary_changed = result.receipt.summary.model_copy(update={"diagnosis": changed})
            with pytest.raises(HarnessError, match="CLASSIFICATION_CHANGED"):
                check_conclusion(
                    task, gateway, result.receipt.model_copy(update={"summary": summary_changed})
                )
            foreign = task.model_copy(update={"execution_id": uuid4()})
            with pytest.raises(HarnessError, match="CONCLUSION_FAILURE_CHANGED"):
                check_conclusion(foreign, gateway, result.receipt)
            denied = await gateway.call(
                "flowtest.inspect_run_evidence", {"execution_id": str(task.execution_id)}
            )
            assert (
                denied.is_error and gateway.stop_receipt.reason_code == "HOST_TOOL_BUDGET_EXCEEDED"
            )
            assert len(gateway.receipts) == gateway.stop_receipt.admitted_calls == 2
            assert gateway.stop_receipt.rejected_calls == 1
    assert await _counts(context) == before
    async with context["sessions"]() as session:
        execution = await session.get(WorkflowExecution, task.execution_id)
        assert execution.status == "failed" and execution.error_code == "WORKFLOW_ASSERTION_FAILED"


async def test_diagnosis_cli_without_authorization_is_not_run_and_never_launches(
    tmp_path, monkeypatch
):
    import asyncio

    async def forbidden(*args, **kwargs):
        pytest.fail("default diagnosis must not start any model or subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    result = await diagnosis_cli(argparse.Namespace(host_config=None, output_dir=tmp_path))
    assert result == 2
    saved = json.loads((tmp_path / "diagnosis.json").read_text())
    assert saved["status"] == "NOT_RUN" and saved["actual_model_calls"] == 0


@pytest.mark.parametrize("change", ["execution", "project", "write", "extra"])
async def test_diagnosis_cannot_leave_exact_failed_execution_or_dispatch_writes(tmp_path, change):
    _, task = archived(tmp_path)
    auth = authorization(
        allowed_tools=("flowtest.inspect_run_evidence", "flowtest.diagnose_failure")
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    tools = tuple(Tool(name=name, input_schema={"type": "object"}) for name in auth.allowed_tools)

    class ForbiddenUpstream:
        async def call_tool(self, name, arguments):
            pytest.fail("foreign execution, project, extra fields or writes must not dispatch")

    values = dict(
        task=task,
        grant=grant,
        attempt_id=uuid4(),
        catalog=tools,
        upstream=ForbiddenUpstream(),
        directory=tmp_path,
        deadline=datetime.now(UTC) + timedelta(seconds=5),
    )
    gateway = DiagnosisGateway(**values)
    name = "flowtest.diagnose_failure"
    args = {"request": {"project_id": str(task.project_id), "execution_id": str(task.execution_id)}}
    if change == "execution":
        args["request"]["execution_id"] = str(uuid4())
    elif change == "project":
        args["request"]["project_id"] = str(uuid4())
    elif change == "write":
        name = "flowtest.propose_repair"
    else:
        args["request"]["ignored"] = True
    result = await gateway.call(name, args)
    assert result.is_error and gateway.stop_receipt is not None
    assert len(gateway.receipts) == 1 and gateway.receipts[0].outcome == "rejected"
    with pytest.raises(HarnessError, match="ALLOWLIST_INVALID"):
        BoundedGateway(
            authorization=auth,
            attempt_id=uuid4(),
            phase="workflow",
            catalog=tools,
            upstream=ForbiddenUpstream(),
            directory=tmp_path,
            deadline=values["deadline"],
        )


async def test_reserved_diagnosis_grant_is_never_replayed_from_new_output_directory(tmp_path):
    config, task = archived(tmp_path)
    auth = authorization(
        allowed_tools=("flowtest.inspect_run_evidence", "flowtest.diagnose_failure")
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    tools = tuple(Tool(name=name, input_schema={"type": "object"}) for name in auth.allowed_tools)

    class ForbiddenUpstream:
        async def call_tool(self, name, arguments):
            pytest.fail("an already reserved grant cannot start a new model")

    config.attempt_directory.mkdir(mode=0o700)
    write_json(
        config.attempt_directory / (str(auth.authorization_id) + ".json"), {"status": "pending"}
    )
    output = tmp_path / "different-output"
    gateway = DiagnosisGateway(
        task=task,
        grant=grant,
        attempt_id=uuid4(),
        catalog=tools,
        upstream=ForbiddenUpstream(),
        directory=output,
        deadline=datetime.now(UTC) + timedelta(seconds=5),
    )
    plan = CodexLaunchPlan(
        (), tmp_path, (), canonical_digest("not launched"), grant.digest, gateway.deadline
    )
    with pytest.raises(HarnessError, match="AUTHORIZATION_ALREADY_RESERVED"):
        await execute_diagnosis(
            plan,
            prompt="not launched",
            gateway=gateway,
            config=config,
            directory=output,
            reader=None,
        )
    assert not output.exists()


async def test_diagnosis_final_deadline_guard_never_reads_more_evidence_or_reports_success(
    tmp_path,
):
    config, task = archived(tmp_path)

    class Expired:
        deadline = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(HarnessError, match="DIAGNOSIS_DEADLINE_EXCEEDED"):
        await _postcheck(config, task, Expired(), None)


def retained_wire(task):
    _, _, materialized, _ = materialization()
    source = materialized_source(
        materialized,
        materialized.assets[0],
        ArtifactReference(id=uuid4(), sha256="a" * 64, kind="generation"),
    )
    references = tuple(
        ArtifactReference(id=uuid4(), kind=kind, sha256=value)
        for kind, value in (
            ("manifest", task.manifest_sha256),
            ("evidence", task.evidence_sha256),
            ("verification", task.verification_sha256),
        )
    )
    key = {"scenario_id": task.scenario_id, "variant_key": task.variant_key}
    now = datetime.now(UTC)
    batch = BatchResponse(
        id=task.origin_batch_id,
        installation_id=uuid4(),
        project_id=task.project_id,
        binding_id=uuid4(),
        batch_key=task.origin_batch_key,
        batch_kind="mcp_generated",
        generation_mode="host_llm_mcp",
        generation_stage="ready",
        readiness="ready",
        phase="completed",
        revision=1,
        verdict="passed",
        sealed_verdict="passed",
        verification_scope="diagnostic_subset",
        provenance="local_untrusted",
        evidence_integrity="complete",
        cleanup_status="completed",
        expected_count=1,
        expected_scenario_set=(key,),
        required_scenario_set=(key,),
        manifest_digest="a" * 64,
        policy_digest="b" * 64,
        binding_fingerprint="c" * 64,
        environment_fingerprint="d" * 64,
        builds={name: "synthetic" for name in ("runner", "target", "fixture", "verifier")},
        deadline=now + timedelta(seconds=60),
        created_at=now,
        updated_at=now,
        sealed_at=now,
        artifacts=references,
        actions={},
    )
    scenario = ScenarioResultResponse(
        **key,
        id=uuid4(),
        batch_id=task.origin_batch_id,
        title="合成只读DTO",
        category="mcp",
        expected={"status": "failed", "error_code": task.error_code, "phase": task.phase},
        observed_status="failed",
        verification_status="matched",
        generation_attempt=1,
        source=source,
        evidence_refs=references[1:],
        attempts_complete=True,
    )
    return batch.model_dump(mode="json"), {
        "batch": batch.model_dump(mode="json"),
        "scenario": scenario.model_dump(mode="json"),
        "execution_id": str(task.execution_id),
    }


@pytest.mark.parametrize(
    "change", ["none", "duplicate", "observer_ref", "workflow", "variant", "unsealed"]
)
async def test_retained_binding_requires_exact_sealed_artifacts_and_observer_refs(tmp_path, change):
    _, task = archived(tmp_path)
    batch, relation = retained_wire(task)
    if change == "duplicate":
        batch["artifacts"].append(deepcopy(batch["artifacts"][0]))
    elif change == "observer_ref":
        relation["scenario"]["evidence_refs"][0]["sha256"] = "e" * 64
    elif change == "workflow":
        relation["scenario"]["source"]["workflow"]["fingerprint"] = "e" * 64
    elif change == "variant":
        relation["scenario"]["variant_key"] = "foreign"
    elif change == "unsealed":
        batch["sealed_at"] = None

    class FrozenReadAPI:
        async def object(self, method, path):
            assert method == "GET"
            return relation if "/executions/" in path else batch

    if change == "none":
        await retained_failure(FrozenReadAPI(), task)
    else:
        with pytest.raises(HarnessError):
            await retained_failure(FrozenReadAPI(), task)


@pytest.mark.parametrize("name", ["flowtest.inspect_run_evidence", "flowtest.diagnose_failure"])
async def test_malformed_candidate_evidence_is_blocked_before_reaching_model(tmp_path, name):
    _, task = archived(tmp_path)
    auth = authorization(
        allowed_tools=("flowtest.inspect_run_evidence", "flowtest.diagnose_failure")
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    tools = tuple(Tool(name=tool, input_schema={"type": "object"}) for tool in auth.allowed_tools)

    class MalformedCandidate:
        async def call_tool(self, name, arguments):
            return CallToolResult(
                content=[],
                structured_content={
                    "data": {
                        "execution_id": str(task.execution_id),
                        "workflow_id": str(task.workflow_id),
                    }
                },
            )

    gateway = DiagnosisGateway(
        task=task,
        grant=grant,
        attempt_id=uuid4(),
        catalog=tools,
        upstream=MalformedCandidate(),
        directory=tmp_path,
        deadline=datetime.now(UTC) + timedelta(seconds=5),
    )
    args = {"execution_id": str(task.execution_id)}
    if name.endswith("diagnose_failure"):
        args = {"request": {"project_id": str(task.project_id), **args}}
    result = await gateway.call(name, args)
    assert result.is_error and gateway.stopped.is_set()
    assert gateway.receipts[0].outcome == "rejected" and gateway.exchanges == []
