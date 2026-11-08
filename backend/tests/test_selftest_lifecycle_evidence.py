"""Lifecycle goldens retain real compiled schemas without inventing dynamic body values."""

from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.collect_lifecycle_evidence import (  # noqa: E402
    _capture_fields,
    _published_workflow,
    _response_goldens,
    collect_lifecycle_scenario,
    lifecycle_expectation,
)
from scripts.selftest.contracts import (  # noqa: E402
    BatchEvidence,
    BatchManifest,
    Builds,
    McpCallReceipt,
    ProposalEvidence,
    canonical_digest,
)
from scripts.selftest.generation_lifecycle import (  # noqa: E402
    LifecycleAsset,
    _oracle_bindings,
    bind_lifecycle_plan,
    combine_generated_designs,
)
from scripts.selftest.io import HarnessError, PublicAPI  # noqa: E402
from scripts.selftest.review_fixture_driver import ReviewedCase, ReviewedWorkflow  # noqa: E402
from scripts.selftest.start_plan import FrozenPlanCase, PlanSelection  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402
from test_selftest_generation_lifecycle import _generated_inputs, _installation  # noqa: E402

from app.domain.flow_spec import flow_spec_to_workflow_definition  # noqa: E402
from app.domain.integration_plans import (  # noqa: E402
    IntegrationPlannerRequest,
    PlanActor,
    PlanTargetEnvironment,
    build_integration_plan,
    compile_integration_plan,
)
from app.domain.test_design import fingerprint_design  # noqa: E402


def lifecycle_fixture() -> tuple[
    LifecycleAsset, PlanSelection, dict[str, Any], dict[str, Any], dict[str, Any]
]:
    installed = _installation()
    _, _, selected, operations = _generated_inputs(installed)
    plan = build_integration_plan(
        IntegrationPlannerRequest(
            context_revision_id=uuid4(),
            context_fingerprint="a" * 64,
            objective="Lifecycle evidence",
            actors=[PlanActor(id="fixture", role="owner")],
            target_environment=PlanTargetEnvironment(
                key="target", source_ref=f"environment://{installed.target_environment_id}"
            ),
            selected_operations=selected,
        )
    )
    plan = bind_lifecycle_plan(plan, installed, "batch-one")
    compiled = compile_integration_plan(plan)
    assert compiled.importable
    native = flow_spec_to_workflow_definition(
        compiled.flow_spec,
        operation_mappings={
            item.operation_ref: item.api_source.api_definition_id for item in operations
        },
        operation_versions={item.operation_ref: 1 for item in operations},
        service_keys={item.service_ref: "selftest_target" for item in plan.operations},
    ).model_dump(mode="json")
    now = datetime.now(UTC)
    flow_id, version_id, case_id, execution_id = uuid4(), uuid4(), uuid4(), uuid4()
    proposal = ProposalEvidence(
        project_id=installed.project_id,
        proposal_id=uuid4(),
        route="flow_spec",
        review_status="accepted",
        materialized_resource_id=flow_id,
        content_fingerprint="a" * 64,
        review_mode="ci_fixture",
        reviewer_id=installed.reviewer_id,
    )
    definition = {
        "workflow_id": str(flow_id),
        "workflow_version": 1,
        "environment_id": str(installed.target_environment_id),
    }
    combined, composition = combine_generated_designs(operations)
    calls = tuple(
        McpCallReceipt(
            call_id=f"call-{index}",
            batch_key="batch-one",
            scenario_id="ST-MCP-023",
            phase="generation",
            tool_name=name,
            transport="stdio",
            sdk_version="1",
            protocol_version="1",
            request_digest="a" * 64,
            result_digest="a" * 64,
            catalog_digest="a" * 64,
            completed_at=now - timedelta(seconds=3),
            success=True,
        )
        for index, name in enumerate(
            (
                "flowtest.generate_test_design",
                "flowtest.propose_test_design",
                "flowtest.propose_flow_draft",
            )
        )
    )
    asset = LifecycleAsset(
        target_project_id=installed.target_project_id,
        operations=operations,
        source_document_digest="a" * 64,
        bound_document_digest="a" * 64,
        source_reused=False,
        context={},
        integration_plan=plan.model_dump(mode="json"),
        combined_design=combined.model_dump(mode="json"),
        combined_design_fingerprint=fingerprint_design(combined),
        design_composition=composition,
        compilation_fingerprint=compiled.flow_spec_fingerprint,
        oracle_bindings=_oracle_bindings(compiled.model_dump(mode="json")),
        workflow=ReviewedWorkflow(
            workflow={"id": str(flow_id)},
            version={
                "id": str(version_id),
                "version": 1,
                "definition": native,
                "fingerprint": "a" * 64,
            },
            proposal=proposal,
        ),
        case=ReviewedCase(
            case={"id": str(case_id)},
            version={"version": 1, "fingerprint": "a" * 64, "definition": definition},
            proposal=proposal.model_copy(
                update={
                    "route": "controlled_write",
                    "item_id": uuid4(),
                    "materialized_resource_id": case_id,
                }
            ),
        ),
        calls=calls,
        created_resource_name="batch-one-created",
        updated_resource_name="batch-one-updated",
        generated_at=now - timedelta(seconds=4),
        frozen_at=now - timedelta(seconds=2),
    )
    selection = PlanSelection(
        project_id=installed.project_id,
        suite_id=uuid4(),
        suite_version=1,
        suite_fingerprint="a" * 64,
        plan_id=uuid4(),
        frozen_at=now - timedelta(seconds=2),
        cases=(FrozenPlanCase(case_id=case_id, version=1, target_snapshot_digest="b" * 64),),
    )
    item = {
        "id": str(uuid4()),
        "target_type": "case",
        "target_id": str(case_id),
        "target_version": 1,
        "workflow_id": str(flow_id),
        "workflow_version": 1,
        "environment_id": str(installed.target_environment_id),
        "attempts": 1,
        "attempts_complete": True,
        "status": "passed",
        "execution_id": str(execution_id),
        "execution_ids": [str(execution_id)],
        "target_snapshot_digest": "b" * 64,
    }
    run = {"run_id": str(uuid4()), "test_plan_id": str(selection.plan_id)}
    configs = {node["id"]: node["config"] for node in native["nodes"]}
    raw = {
        "execution_id": str(execution_id),
        "project_id": str(installed.project_id),
        "workflow_id": str(flow_id),
        "workflow_version_id": str(version_id),
        "environment_id": str(installed.target_environment_id),
        "status": "passed",
        "error_code": None,
        "run_purpose": "standard",
        "main_status": "passed",
        "cleanup_status": None,
        "started_at": (now - timedelta(seconds=1)).isoformat(),
        "completed_at": now.isoformat(),
        "snapshot_digest": "a" * 64,
        "workflow_fingerprint": "a" * 64,
        "bindings_complete": True,
        "api_bindings": [
            {**operation.api_source.model_dump(mode="json"), "node_id": f"api-{index}"}
            for index, operation in enumerate(operations)
        ],
        "nodes": [
            {
                "node_id": binding.node_id,
                "node_type": "assert",
                "phase": "main",
                "status": "passed",
                "attempts": 1,
                "error_code": None,
                "assertions_complete": True,
                "assertions": [
                    {
                        "name": "workflow_assertion",
                        "passed": True,
                        "expected_digest": binding.expected_value_digest,
                        "actual_digest": canonical_digest(
                            configs[binding.node_id]["expected"]
                            if binding.expression == "status_code"
                            else {"dynamic": "body"}
                        ),
                    }
                ],
            }
            for binding in asset.oracle_bindings
        ],
        "node_total": len(asset.oracle_bindings),
        "truncated": False,
        "source_plan_run_item_id": item["id"],
        "source_case_id": str(case_id),
        "source_case_version": 1,
    }
    raw["nodes"].extend(
        {
            "node_id": node["id"],
            "node_type": "api",
            "phase": "main",
            "status": "passed",
            "attempts": 1,
            "error_code": None,
            "assertions_complete": True,
            "assertions": [],
        }
        for node in native["nodes"]
        if node["type"] == "api"
    )
    raw["node_total"] = len(raw["nodes"])
    return asset, selection, run, item, raw


def test_real_plan_freezes_five_statuses_and_all_schema_mappings_without_body_goldens() -> None:
    asset, selection, *_ = lifecycle_fixture()
    expected = lifecycle_expectation(asset, selection)
    assert sorted(item.actual for item in expected.expected.assertions) == [200, 200, 200, 201, 204]
    assert all(type(item.actual) is int for item in expected.expected.assertions)
    assert len(expected.required_oracle_ids) >= 9
    assert len(expected.expected_api_sources) == len(expected.expected_design_sources) == 5
    assert expected.require_suite_provenance
    assert expected.expected_suite is not None
    assert expected.expected_target_snapshot_digest == "b" * 64
    assert expected.expected.resource_absence is not None
    assert expected.expected.resource_absence.project_id == asset.target_project_id
    assert [(item.field, item.expected) for item in expected.expected.response_fields] == [
        ("name", asset.created_resource_name),
        ("name", asset.updated_resource_name),
    ]


def test_lifecycle_published_workflow_rejects_missing_nonprimary_api() -> None:
    asset, *_ = lifecycle_fixture()
    version = copy.deepcopy(asset.workflow.version)
    definition = version["definition"]
    index = next(index for index, node in enumerate(definition["nodes"]) if node["type"] == "api")
    definition["nodes"].pop(index)
    asset = asset.model_copy(
        update={"workflow": asset.workflow.model_copy(update={"version": version})}
    )
    with pytest.raises(HarnessError, match="PUBLISHED_API_SOURCE_CHANGED"):
        _published_workflow(asset)


@pytest.mark.parametrize("mutation", ["operator", "source", "expected_source", "extra_assertion"])
def test_lifecycle_published_assertion_semantics_cannot_drift(mutation: str) -> None:
    asset, _, _, _, _ = lifecycle_fixture()
    version = copy.deepcopy(asset.workflow.version)
    nodes = version["definition"]["nodes"]
    node = next(item for item in nodes if item["type"] == "assert")
    if mutation == "operator":
        node["config"]["operator"] = "not_equals"
    elif mutation == "source":
        node["config"]["source_node_id"] = "start"
    elif mutation == "expected_source":
        node["config"]["expected_source_node_id"] = node["config"]["source_node_id"]
        node["config"]["expected_expression"] = node["config"]["expression"]
    else:
        extra = copy.deepcopy(node)
        extra["id"] = "unexpected_assertion"
        nodes.append(extra)
    changed = asset.model_copy(
        update={"workflow": asset.workflow.model_copy(update={"version": version})}
    )
    with pytest.raises(HarnessError, match="PUBLISHED_ORACLE"):
        _published_workflow(changed)


@pytest.mark.parametrize("incomplete", [False, True])
@pytest.mark.parametrize("resource_present", [False, True])
async def test_lifecycle_collector_reads_all_attempts_and_separate_real_postcondition(
    tmp_path: Path, incomplete: bool, resource_present: bool
) -> None:
    asset, selection, run, item, raw = lifecycle_fixture()
    raw["nodes"][0]["assertions_complete"] = not incomplete
    calls: list[str] = []
    snapshot = {
        "apis": {
            item.node_id: {
                "definition_id": str(item.api_source.api_definition_id),
                "version": item.api_source.api_version,
            }
            for item in _response_goldens(asset)
        }
    }
    raw["snapshot_digest"] = canonical_digest(snapshot)
    detail = {
        "execution": {
            "id": raw["execution_id"],
            "snapshot": snapshot,
            **{
                key: raw[key]
                for key in (
                    "project_id",
                    "workflow_id",
                    "workflow_version_id",
                    "environment_id",
                    "status",
                )
            },
        },
        "nodes": [
            {
                "node_id": item.node_id,
                "node_type": "api",
                "phase": "main",
                "status": "passed",
                "attempts": 1,
                "workflow_execution_id": raw["execution_id"],
                "output": {
                    "headers": {"Authorization": "sensitive-in-memory"},
                    "body": {"name": item.expected, "private": "never-persist-this"},
                },
            }
            for item in _response_goldens(asset)
        ],
    }

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "runner":
            return httpx.Response(200, json=raw)
        if request.url.host == "capture":
            assert (
                request.url.path
                == f"/api/v1/projects/{raw['project_id']}/workflow-executions/{raw['execution_id']}"
            )
            return httpx.Response(200, json=detail)
        assert request.url.path == f"/api/v1/projects/{asset.target_project_id}/environments"
        return httpx.Response(
            200,
            json=[
                {
                    "name": asset.updated_resource_name if resource_present else "base",
                    "private": "never-persist-this",
                }
            ],
        )

    transport = httpx.MockTransport(respond)
    reader, target, capture = (
        PublicAPI("http://runner", transport=transport),
        PublicAPI("http://target", transport=transport),
        PublicAPI("http://capture", transport=transport),
    )
    try:
        observed = await collect_lifecycle_scenario(
            reader,
            target,
            capture_reader=capture,
            asset=asset,
            selection=selection,
            run=run,
            item=item,
            batch_key="batch-one",
            catalog_digest="a" * 64,
            expected_target_snapshot_digest="b" * 64,
            output_dir=tmp_path,
        )
    finally:
        await reader.close()
        await target.close()
        await capture.close()
    assert observed.evidence_complete is not incomplete
    assert observed.provenance is not None
    assert len(observed.provenance.design_sources) == 5
    assert len(observed.provenance.workflow.api_sources) == 5
    assert observed.resource_absence is not None
    assert observed.resource_absence.returned_names == (
        asset.updated_resource_name if resource_present else "base",
    )
    assert observed.cleanup_status == ("failed" if resource_present else "completed")
    assert observed.resource_absence.observed_at >= observed.execution.completed_at
    assert len(calls) == 3
    assert len(observed.response_fields) == 2
    assert [field.actual for field in observed.response_fields] == [
        asset.created_resource_name,
        asset.updated_resource_name,
    ]
    assert "sensitive-in-memory" not in (tmp_path / "observed.json").read_text()
    assert "never-persist-this" not in (tmp_path / "observed.json").read_text()
    assert (
        json.loads((tmp_path / "observed.json").read_text())["provenance"]["run"][
            "expected_target_snapshot_digest"
        ]
        == "b" * 64
    )
    expected = lifecycle_expectation(asset, selection)
    builds = Builds(runner="runner", target="target", fixture="fixture", verifier="observer")
    manifest = BatchManifest(
        pack_id="mcp-core-v1",
        pack_version="1",
        pack_digest="a" * 64,
        policy_digest="a" * 64,
        project_id=selection.project_id,
        batch_key="batch-one",
        nonce="nonce",
        builds=builds,
        batch_kind="mcp_generated",
        generation_mode="deterministic_mcp",
        verification_scope="selected_suites",
        expected_scenario_set=(asset.scenario_id,),
        required_scenario_set=(asset.scenario_id,),
        scenarios=(expected,),
        created_at=asset.generated_at - timedelta(seconds=1),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    evidence = BatchEvidence(
        batch_key="batch-one",
        nonce="nonce",
        pack_digest="a" * 64,
        policy_digest="a" * 64,
        builds=builds,
        collected_at=datetime.now(UTC),
        scenarios=(observed,),
        cleanup_status="failed" if resource_present else "completed",
    )
    report = verify_batch(manifest, evidence)
    assert (report.exit_code == 0) is (not incomplete and not resource_present), report.model_dump(
        mode="json"
    )


@pytest.mark.parametrize(
    "change",
    [
        "old_execution",
        "wrong_snapshot",
        "wrong_api",
        "missing_name",
        "numeric_name",
        "skipped",
        "duplicate",
        "wrong_node_execution",
    ],
)
async def test_capture_extraction_rejects_missing_changed_or_unexecuted_sources(
    change: str,
) -> None:
    asset, _, _, _, raw = lifecycle_fixture()
    fields = _response_goldens(asset)
    snapshot = {
        "apis": {
            field.node_id: {
                "definition_id": str(field.api_source.api_definition_id),
                "version": field.api_source.api_version,
            }
            for field in fields
        }
    }
    raw["snapshot_digest"] = canonical_digest(snapshot)
    execution = {
        "id": raw["execution_id"],
        "snapshot": snapshot,
        **{
            key: raw[key]
            for key in (
                "project_id",
                "workflow_id",
                "workflow_version_id",
                "environment_id",
                "status",
            )
        },
    }
    nodes = [
        {
            "node_id": field.node_id,
            "node_type": "api",
            "phase": "main",
            "status": "passed",
            "attempts": 1,
            "workflow_execution_id": raw["execution_id"],
            "output": {"body": {"name": field.expected}},
        }
        for field in fields
    ]
    if change == "old_execution":
        execution["id"] = str(uuid4())
    elif change == "wrong_snapshot":
        raw["snapshot_digest"] = "a" * 64
    elif change == "wrong_api":
        snapshot["apis"][fields[0].node_id]["definition_id"] = str(uuid4())
        raw["snapshot_digest"] = canonical_digest(snapshot)
    elif change == "missing_name":
        nodes[0]["output"]["body"] = {}
    elif change == "numeric_name":
        nodes[0]["output"]["body"]["name"] = 1
    elif change == "skipped":
        nodes[0]["status"] = "skipped"
    elif change == "duplicate":
        nodes.append(copy.deepcopy(nodes[0]))
    else:
        nodes[0]["workflow_execution_id"] = str(uuid4())
    reader = PublicAPI(
        "http://capture",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"execution": execution, "nodes": nodes})
        ),
    )
    try:
        with pytest.raises(HarnessError):
            await _capture_fields(reader, asset, raw, "batch-one")
    finally:
        await reader.close()
