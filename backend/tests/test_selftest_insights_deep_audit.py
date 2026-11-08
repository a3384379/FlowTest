"""Real product execution and producer-shaped receipts preserve insight evidence boundaries."""

import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from selftest_materialization_helpers import finalize_fixture_materialization
from test_selftest_host_integration import fixture as integration_fixture
from test_selftest_product_api import ProductContext
from test_selftest_product_api import observation as observation
from test_selftest_product_api import product as product
from test_selftest_product_sources import _materialized
from test_tasking_api import tasking_context as tasking_context

from app.core.errors import AppError
from app.core.self_tests import get_self_test_settings
from app.core.storage import StoredObject
from app.domain.self_tests import document_digest
from app.domain.test_design import TestDesignDocument as DesignDocument
from app.domain.test_design import fingerprint_design
from app.main import app
from app.services import artifacts as artifact_module
from app.services.self_test_insight_documents import InsightGeneration
from app.services.self_test_insights import SelfTestInsightService
from app.services.workflows import WorkflowService

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.collect_evidence import normalize_execution
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Builds,
    ExpectedOutcome,
    McpCallReceipt,
    ScenarioExpectation,
    ScenarioObservation,
)
from scripts.selftest.generation_lifecycle import LifecycleAsset
from scripts.selftest.host_integration_sources import integration_source
from scripts.selftest.mcp_generation_journey import GeneratedAsset


async def _upload(
    context: ProductContext,
    batch_id: str,
    lease: dict[str, Any],
    kind: str,
    document: dict[str, Any],
    *,
    machine: str = "o",
) -> dict[str, Any]:
    return await context.post(
        context.agent + f"/runs/{batch_id}/artifacts",
        {
            "lease_token": lease["lease_token"],
            "nonce": lease["nonce"],
            "kind": kind,
            "filename": f"{kind}-deep-audit.json",
            "content_base64": base64.b64encode(json.dumps(document).encode()).decode(),
        },
        machine=machine,
        status=201,
    )


async def _observations(
    context: ProductContext,
    batch: dict[str, Any],
    receipt: dict[str, Any],
    *,
    omit_phase_status: bool = False,
) -> None:
    rows = (await context.get(context.root + f"/runs/{batch['id']}/scenarios"))["items"]
    observations = []
    expectations = []
    for row in rows:
        execution_id = row["executions"][0]["execution_id"]
        response = await context.native.client.get(
            context.agent + f"/runs/{batch['id']}/evidence/workflow-executions/{execution_id}",
            headers={
                **context.machine("o"),
                "X-SelfTest-Lease-Token": receipt["lease_token"],
                "X-SelfTest-Nonce": receipt["nonce"],
            },
        )
        assert response.status_code == 200, response.text
        execution = normalize_execution(response.json())
        if omit_phase_status and row["expected"]["status"] == "passed":
            execution = execution.model_copy(update={"main_status": None})
        observations.append(
            ScenarioObservation(
                scenario_id=row["scenario_id"],
                variant_key=row["variant_key"],
                execution=execution,
                attempts=(execution,),
                cleanup_status="completed",
            )
        )
        expectations.append(
            ScenarioExpectation(
                scenario_id=row["scenario_id"],
                variant_key=row["variant_key"],
                expected=ExpectedOutcome(
                    execution_status=row["expected"]["status"],
                    main_status=row["expected"]["status"],
                    error_code=row["expected"]["error_code"],
                    phase=row["expected"]["phase"],
                    node_id="assert" if row["expected"]["status"] == "failed" else None,
                ),
                required_evidence=("execution",),
            )
        )
    manifest = BatchManifest(
        pack_id="product-test-v1",
        pack_version="1.0.0",
        pack_digest="f" * 64,
        policy_digest=batch["policy_digest"],
        project_id=context.project_id,
        batch_key=batch["batch_key"],
        nonce=receipt["nonce"],
        builds=Builds.model_validate(batch["builds"]),
        batch_kind="fixed_baseline",
        verification_scope=batch["verification_scope"],
        expected_scenario_set=tuple(row["scenario_id"] for row in rows),
        required_scenario_set=tuple(row["scenario_id"] for row in rows),
        scenarios=tuple(expectations),
        created_at=datetime.fromisoformat(batch["created_at"]),
        expires_at=datetime.fromisoformat(batch["deadline"]),
    )
    evidence = BatchEvidence(
        batch_key=batch["batch_key"],
        nonce=receipt["nonce"],
        pack_digest=manifest.pack_digest,
        policy_digest=manifest.policy_digest,
        builds=manifest.builds,
        collected_at=datetime.now(UTC),
        scenarios=tuple(observations),
        cleanup_status="completed",
    )
    for kind, document in (("manifest", manifest), ("evidence", evidence)):
        receipt["artifacts"].append(
            await _upload(context, batch["id"], receipt, kind, document.model_dump(mode="json"))
        )


@pytest.mark.parametrize(
    "verdict,cleanup,reasons",
    [
        ("blocked", "completed", ["BATCH_IDENTITY_MISMATCH"]),
        ("failed", "completed", ["BATCH_IDENTITY_MISMATCH"]),
        ("passed", "failed", []),
        ("blocked", "completed", []),
        ("failed", "completed", []),
    ],
)
async def test_global_failure_keeps_the_frozen_denominator_without_success_numerators(
    product: ProductContext,
    observation: tuple[dict, dict],
    verdict: str,
    cleanup: str,
    reasons: list[str],
) -> None:
    batch, receipt = observation
    receipt.update(batch_verdict=verdict, cleanup_status=cleanup, batch_reason_codes=reasons)
    sealed = await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
    )
    assert sealed["verdict"] in {"failed", "blocked"}
    result = await product.get(product.root + f"/runs/{batch['id']}/insights")
    metrics = {item["key"]: item for item in result["metrics"]}
    for key in ("engine", "verification"):
        assert metrics[key]["denominator"] == batch["expected_count"] == 2
        assert metrics[key]["numerator"] == 0
        assert "SELFTEST_BATCH_OBSERVATION_NOT_CONFIRMED" in metrics[key]["exclusions"]
    rows = (await product.get(product.root + f"/runs/{batch['id']}/scenarios"))["items"]
    assert all(row["verification_status"] == "matched" for row in rows)


@pytest.mark.parametrize("failure", ["none", "runtime", "different_node_error"])
async def test_execution_error_is_compared_exactly_including_the_absence_of_an_error(
    product: ProductContext,
    observation: tuple[dict, dict],
    failure: str,
) -> None:
    batch, receipt = observation
    rows = (await product.get(product.root + f"/runs/{batch['id']}/scenarios"))["items"]
    selected = next(
        row
        for row in rows
        if row["expected"]["status"]
        == ("failed" if failure == "different_node_error" else "passed")
    )
    if failure != "none":
        async with product.native.session_maker() as session:
            await WorkflowService(session).stage_runtime_failed(
                UUID(selected["executions"][0]["execution_id"]),
                error_code="WORKFLOW_RUNTIME_ERROR",
                error_message="合成运行时故障, 保留原节点事实",
            )
            await session.commit()
        receipt["batch_verdict"] = "failed"
        result = next(
            item for item in receipt["scenarios"] if item["scenario_id"] == selected["scenario_id"]
        )
        result.update(
            observed_status="failed",
            verification_status="mismatched",
            reason_codes=["EXECUTION_ERROR_MISMATCH"],
        )
    await _observations(product, batch, receipt)
    await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
    )
    insights = await product.get(product.root + f"/runs/{batch['id']}/insights")
    scenario = next(
        item for item in insights["comparisons"] if item["scenario_id"] == selected["scenario_id"]
    )
    error = next(item for item in scenario["items"] if item["field"] == "错误码")
    assert json.loads(error["expected"]) == selected["expected"]["error_code"]
    assert json.loads(error["observed"]) == (
        None if failure == "none" else "WORKFLOW_RUNTIME_ERROR"
    )
    assert error["difference"] == ("equal" if failure == "none" else "different")
    metrics = {item["key"]: item for item in insights["metrics"]}
    assert metrics["verification"]["numerator"] == (2 if failure == "none" else 1)


def _design() -> DesignDocument:
    return DesignDocument.model_validate(
        {
            "intent": {
                "key": "insights.receipt",
                "objective": "核对真实发布来源与生成回执",
                "acceptance_criteria": ["读取实际断言值"],
            },
            "oracles": [
                {
                    "id": "actual",
                    "kind": "json_path",
                    "expression": "body.actual",
                    "expected": 1,
                    "confidence": 1,
                }
            ],
            "scenarios": [
                {
                    "id": "happy",
                    "kind": "happy_path",
                    "title": "正向",
                    "expected_category": "success",
                }
            ],
        }
    )


async def _generation(
    context: ProductContext, monkeypatch: pytest.MonkeyPatch, *, mode: str = "deterministic_mcp"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if mode == "host_llm_mcp":
        context.config = context.config.model_copy(
            update={
                "principals": tuple(
                    principal.model_copy(update={"authorized_host_budget_digests": ("3" * 64,)})
                    if principal.id == "h"
                    else principal
                    for principal in context.config.principals
                )
            }
        )
        monkeypatch.setitem(
            app.dependency_overrides, get_self_test_settings, lambda: context.config
        )
    batch, payload = await _materialized(context, mode=mode)
    source = payload["sources"][0]
    root = f"/api/v1/projects/{context.project_id}"
    workflow = await context.get(root + f"/workflows/{source['workflow']['id']}")
    workflow_versions = await context.get(root + f"/workflows/{source['workflow']['id']}/versions")
    case = await context.get(root + f"/test-cases/{source['case']['id']}")
    case_versions = await context.get(root + f"/test-cases/{source['case']['id']}/versions")
    reviewed = await context.get(
        root + f"/flow-specs/change-sets/{source['workflow_proposal']['change_set_id']}"
    )
    actor = reviewed["reviewed_by_id"]
    now = datetime.now(UTC)
    calls = tuple(
        McpCallReceipt(
            call_id=f"host-attempt-{index}",
            batch_key=batch["batch_key"],
            scenario_id=source["scenario_id"],
            phase="workflow" if mode == "host_llm_mcp" else phase,
            tool_name=tool,
            transport="stdio",
            sdk_version="2.2.0",
            protocol_version="2025-11-25",
            request_digest="a" * 64,
            result_digest="b" * 64,
            catalog_digest="c" * 64,
            completed_at=now,
            success=success,
        )
        for index, (phase, tool, success) in enumerate(
            (
                ("design", "flowtest.generate_test_design", True),
                ("compilation", "flowtest.compile_test_design", True),
                ("contract_read", "flowtest.read_api_contract", False),
            )
        )
    )

    def review(reference: dict[str, Any]) -> dict[str, Any]:
        return {
            "project_id": str(context.project_id),
            "proposal_id": reference["change_set_id"],
            "item_id": reference.get("item_id"),
            "route": "flow_spec"
            if reference["route"] == "flow_spec_visual"
            else "controlled_write",
            "review_status": "accepted",
            "materialized_resource_id": reference["materialized_resource_id"],
            "content_fingerprint": reference["content_fingerprint"],
            "review_mode": "ci_fixture",
            "reviewer_id": actor,
        }

    design = _design()
    asset = GeneratedAsset.model_validate(
        {
            "scenario_id": source["scenario_id"],
            "variant_key": source["variant_key"],
            "api_source": source["api_sources"][0],
            "design": design.model_dump(mode="json"),
            "design_fingerprint": fingerprint_design(design),
            "compilation_fingerprint": source["compilation_fingerprint"],
            "oracle_bindings": source["oracle_bindings"],
            "workflow": {
                "workflow": workflow,
                "version": workflow_versions[0],
                "proposal": review(source["workflow_proposal"]),
            },
            "case": {
                "case": case,
                "version": case_versions[0],
                "proposal": review(source["case_proposal"]),
            },
            "calls": calls,
            "generated_at": now,
            "frozen_at": now,
        }
    ).model_dump(mode="json")
    source.update(
        design_fingerprint=asset["design_fingerprint"],
        protocol_receipts_digest=document_digest(asset["calls"]),
    )
    if mode == "host_llm_mcp":
        source["host_evidence"] = {
            "host": "synthetic-host",
            "model": "synthetic-model",
            "skill_digest": "1" * 64,
            "prompt_digest": "2" * 64,
            "authorized_budget_digest": "3" * 64,
            "actual_tool_calls": len(calls),
        }
    return batch, payload, asset


async def _publish_generation(
    context: ProductContext, batch: dict[str, Any], payload: dict[str, Any], asset: dict[str, Any]
) -> None:
    reference = await _upload(context, batch["id"], payload, "generation", asset, machine="h")
    payload["sources"][0]["generation_manifest"] = reference
    payload["manifest"] = reference
    await finalize_fixture_materialization(
        context, context.agent + f"/runs/{batch['id']}/materialized", payload, machine="h"
    )


@pytest.mark.parametrize("mode", ["deterministic_mcp", "host_llm_mcp"])
async def test_design_calls_use_the_producer_tool_identity_in_both_generation_modes(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    batch, payload, asset = await _generation(product, monkeypatch, mode=mode)
    await _publish_generation(product, batch, payload, asset)
    insights = await product.get(product.root + f"/runs/{batch['id']}/insights")
    metrics = {item["key"]: item for item in insights["metrics"]}
    assert (metrics["design"]["numerator"], metrics["design"]["denominator"]) == (1, 1)
    assert (metrics["protocol"]["numerator"], metrics["protocol"]["denominator"]) == (2, 3)
    assert insights["case_slots"][0]["workflow_slot"] == "scenario:happy"
    assert "request_digest" not in str(insights)


@pytest.mark.parametrize(
    "changed", ["success", "batch", "scenario", "duplicate", "design_fingerprint", "design_content"]
)
async def test_generation_receipts_cannot_disagree_with_the_frozen_source(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    batch, payload, asset = await _generation(product, monkeypatch)
    if changed == "success":
        asset["calls"][2]["success"] = True
    elif changed in {"batch", "scenario"}:
        asset["calls"][0][f"{changed}_id" if changed == "scenario" else "batch_key"] = "other-scope"
        payload["sources"][0]["protocol_receipts_digest"] = document_digest(asset["calls"])
    elif changed == "duplicate":
        asset["calls"][1]["call_id"] = asset["calls"][0]["call_id"]
        payload["sources"][0]["protocol_receipts_digest"] = document_digest(asset["calls"])
    elif changed == "design_fingerprint":
        asset["design_fingerprint"] = "f" * 64
    else:
        asset["design"]["intent"]["objective"] = "已漂移但仍为合法文档的设计"
    await _publish_generation(product, batch, payload, asset)
    response = await product.native.client.get(
        product.root + f"/runs/{batch['id']}/insights", headers=product.headers
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "SELFTEST_INSIGHT_SOURCE_MISMATCH"
    assert response.json()["error"]["trace_id"]


@pytest.mark.parametrize("failure", ["local_missing", "s3_missing", "connection"])
async def test_missing_or_unavailable_observer_objects_return_the_evidence_error_contract(
    product: ProductContext,
    observation: tuple[dict, dict],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    batch, receipt = observation
    await _observations(product, batch, receipt)
    await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
    )
    original = artifact_module.object_storage.get

    async def unavailable(*, key: str) -> StoredObject:
        if key.endswith(receipt["artifacts"][-2]["id"]):
            if failure == "local_missing":
                raise FileNotFoundError(key)
            if failure == "s3_missing":
                raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            raise EndpointConnectionError(endpoint_url="http://unavailable.invalid")
        return await original(key=key)

    monkeypatch.setattr(artifact_module.object_storage, "get", unavailable)
    response = await product.native.client.get(
        product.root + f"/runs/{batch['id']}/insights", headers=product.headers
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "SELFTEST_INSIGHT_EVIDENCE_UNAVAILABLE"
    assert response.json()["error"]["trace_id"]
    retained = await product.get(product.root + f"/runs/{batch['id']}")
    assert retained["sealed_verdict"] == "passed"


async def test_missing_generation_object_uses_the_same_bounded_error_boundary(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, payload, asset = await _generation(product, monkeypatch)
    await _publish_generation(product, batch, payload, asset)
    original = artifact_module.object_storage.get

    async def missing(*, key: str) -> StoredObject:
        if key.endswith(payload["sources"][0]["generation_manifest"]["id"]):
            raise FileNotFoundError(key)
        return await original(key=key)

    monkeypatch.setattr(artifact_module.object_storage, "get", missing)
    response = await product.native.client.get(
        product.root + f"/runs/{batch['id']}/insights", headers=product.headers
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "SELFTEST_INSIGHT_GENERATION_UNAVAILABLE"
    assert response.json()["error"]["trace_id"]


async def test_real_lifecycle_format_and_repeated_host_calls_remain_compatible(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, body = await _generation(product, monkeypatch, mode="host_llm_mcp")
    single = GeneratedAsset.model_validate(body)
    gateway, visual, _ = integration_fixture()
    integration, oracles = integration_source(gateway, visual)
    lifecycle = LifecycleAsset(
        scenario_id="ST-MCP-023",
        variant_key="environment_lifecycle",
        target_project_id=integration.plan.target_environment.source_ref.removeprefix(
            "environment://"
        ),
        operations=integration.operations,
        source_document_digest="d" * 64,
        bound_document_digest="e" * 64,
        source_reused=False,
        context=integration.context,
        integration_plan=integration.plan.model_dump(mode="json"),
        combined_design=integration.combined_design.model_dump(mode="json"),
        combined_design_fingerprint=integration.combined_design_fingerprint,
        design_composition=integration.design_composition,
        compilation_fingerprint=integration.compilation.flow_spec_fingerprint,
        oracle_bindings=oracles,
        workflow=single.workflow,
        case=single.case,
        calls=tuple(call.model_copy(update={"scenario_id": "ST-MCP-023"}) for call in single.calls),
        created_resource_name="flowtest-lifecycle-before",
        updated_resource_name="flowtest-lifecycle-after",
        generated_at=single.generated_at,
        frozen_at=single.frozen_at,
    )
    assert len(lifecycle.operations) == 5
    first = InsightGeneration.model_validate(single.model_dump(mode="json"))
    second = InsightGeneration.model_validate(lifecycle.model_dump(mode="json"))
    assert second.design is None
    assert fingerprint_design(second.combined_design) == lifecycle.combined_design_fingerprint
    assert document_digest(
        [call.model_dump(mode="json") for call in second.calls]
    ) == document_digest([call.model_dump(mode="json") for call in lifecycle.calls])
    assert len(SelfTestInsightService._calls([first, second])) == len(single.calls) == 3
    changed = second.calls[0].model_copy(update={"success": False})
    conflict = second.model_copy(update={"calls": (changed, *second.calls[1:])})
    with pytest.raises(AppError) as rejected:
        SelfTestInsightService._calls([first, conflict])
    assert rejected.value.code == "SELFTEST_INSIGHT_SOURCE_MISMATCH"


async def test_missing_phase_status_keeps_the_unrecorded_evidence_boundary(
    product: ProductContext, observation: tuple[dict, dict]
) -> None:
    batch, receipt = observation
    selected = next(item for item in receipt["scenarios"] if item["observed_status"] == "passed")
    selected.update(
        verification_status="mismatched", reason_codes=["EXECUTION_PHASE_STATUS_MISMATCH"]
    )
    receipt["batch_verdict"] = "failed"
    await _observations(product, batch, receipt, omit_phase_status=True)
    await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
    )
    insights = await product.get(product.root + f"/runs/{batch['id']}/insights")
    scenario = next(
        item for item in insights["comparisons"] if item["scenario_id"] == selected["scenario_id"]
    )
    phase = next(item for item in scenario["items"] if item["field"] == "主阶段状态")
    assert phase["expected"] == '"passed"' and phase["observed"] == "null"
    assert phase["difference"] == "not_recorded"
    assert phase["verification_status"] == "mismatched"
