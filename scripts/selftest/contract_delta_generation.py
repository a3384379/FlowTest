"""Real MCP generation; v2 updates remain an explicitly reviewed public import."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import Installation
from scripts.selftest.contract_delta_contracts import (
    DeltaManifest,
    DeltaPack,
    DeltaPhaseFreeze,
    DeltaPhaseGolden,
    DeltaPreview,
    DeltaRejection,
)
from scripts.selftest.contract_delta_slots import execution_ids
from scripts.selftest.contracts import (
    ApiSource,
    AssertionExpectation,
    BatchManifest,
    ExpectedOutcome,
    OracleBinding,
    PublishedSuite,
    ScenarioExpectation,
    SuiteCaseVersion,
    canonical_digest,
)
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.review_fixture_driver import (
    ReviewedCase,
    ReviewedWorkflow,
    review_case,
    review_flow,
)
from scripts.selftest.start_plan import PlanSelection, prepare_plan

SCENARIO = "ST-MCP-012"


def operation(batch_key: str, golden: DeltaPhaseGolden) -> JsonObject:
    return {
        "name": batch_key + "_contract_delta",
        "method": "POST",
        "path": f"/selftest/{batch_key}/{SCENARIO}/request",
        "request_body": {
            "required": True,
            "content_type": "application/json",
            "schema": golden.request_schema,
        },
        "responses": {
            "200": {
                "description": "独立冻结响应契约",
                "content_type": "application/json",
                "schema": golden.response_schema,
            },
            "422": {"description": "输入无效"},
        },
    }


def _selected(preview: JsonObject, expected: JsonObject) -> JsonObject:
    items = [
        item
        for item in objects_value(preview["items"])
        if (item["method"], item["path"]) == (expected["method"], expected["path"])
    ]
    if len(items) != 1:
        raise HarnessError("DELTA_IMPORT_SELECTION_AMBIGUOUS")
    return items[0]


async def preview(
    client: ProtocolClient,
    installation: Installation,
    golden: DeltaPhaseGolden,
    directory: Path,
    fixture_batch_key: str,
) -> tuple[JsonObject, JsonObject]:
    expected = operation(fixture_batch_key, golden)
    result = await client.call(
        "flowtest.preview_contract_import",
        {
            "request": {
                "project_id": str(installation.project_id),
                "source_kind": "operations",
                "operations": [expected],
                "service_id": str(installation.fixture_service_id),
                "environment_id": str(installation.fixture_environment_id),
                "persist": True,
            }
        },
        scenario_id=SCENARIO,
        phase=golden.phase + ":preview",
    )
    write_json(directory / "contract-preview.json", result)
    selected = _selected(result, expected)
    change = "added" if golden.phase == "v1" else "changed"
    if selected["change"] != change:
        raise HarnessError("DELTA_IMPORT_NOT_EXPECTED_CHANGE")
    return result, selected


def commit_request(
    installation: Installation, snapshot: JsonObject, selected: JsonObject
) -> JsonObject:
    expected: JsonObject = {}
    if selected["change"] == "changed":
        expected[text_value(selected["definition_id"])] = selected["version"]
    return {
        "project_id": str(installation.project_id),
        "preview_id": snapshot["preview_id"],
        "preview_sha256": snapshot["source_sha256"],
        "selected_operations": [selected["import_key"]],
        "expected_current_versions": expected,
        "service_id": str(installation.fixture_service_id),
        "environment_id": str(installation.fixture_environment_id),
    }


async def apply_version(
    client: ProtocolClient,
    reviewer: PublicAPI,
    installation: Installation,
    golden: DeltaPhaseGolden,
    snapshot: JsonObject,
    selected: JsonObject,
    directory: Path,
    viewer: PublicAPI,
) -> tuple[DeltaPreview, str, int]:
    request = commit_request(installation, snapshot, selected)
    rejection = None
    if golden.phase == "v1":
        committed = await client.call(
            "flowtest.commit_contract_import",
            {
                "request": request,
                "idempotency_key": client.batch_key + ":v1:import",
            },
            scenario_id=SCENARIO,
            phase="v1:commit",
        )
        merged = None
        results = objects_value(committed["results"])
    else:
        rejection = await _expect_mcp_rejection(
            client, request, "IMPORT_REVIEW_REQUIRED", "v2:commit_review", viewer
        )
        committed = None
        merged = await reviewer.object(
            "POST",
            f"/projects/{installation.project_id}/imports/{snapshot['preview_id']}/merge",
            {
                "selected_keys": [selected["import_key"]],
                "service_id": str(installation.fixture_service_id),
                "environment_id": str(installation.fixture_environment_id),
                "endpoint_variant": "default",
            },
        )
        results = objects_value(merged["results"])
    applied = committed if committed is not None else object_value(merged)
    if applied["applied_keys"] != [selected["import_key"]]:
        raise HarnessError("DELTA_IMPORT_APPLIED_SET_CHANGED")
    matches = [item for item in results if item["import_key"] == selected["import_key"]]
    if len(matches) != 1:
        raise HarnessError("DELTA_IMPORT_MAPPING_MISSING")
    record = DeltaPreview(
        phase=golden.phase,
        preview=snapshot,
        commit=committed,
        merge=merged,
        frozen_at=datetime.now(UTC),
        rejection=rejection,
    )
    write_json(directory / "applied-preview.json", record)
    return record, text_value(matches[0]["definition_id"]), integer_value(matches[0]["version"])


async def _expect_mcp_rejection(
    client: ProtocolClient, request: JsonObject, code: str, phase: str, viewer: PublicAPI
) -> DeltaRejection:
    arguments: JsonObject = {"request": request, "idempotency_key": client.batch_key + ":" + phase}
    before = await execution_ids(viewer, text_value(request["project_id"]))
    try:
        await client.call(
            "flowtest.commit_contract_import", arguments, scenario_id=SCENARIO, phase=phase
        )
    except HarnessError as error:
        if str(error) == "SELFTEST_MCP_CALL_REJECTED_" + code:
            after = await execution_ids(viewer, text_value(request["project_id"]))
            return DeltaRejection(
                call_id=client.receipts[-1].call_id,
                request=arguments,
                code=code,
                before_execution_ids=before,
                after_execution_ids=after,
            )
        raise
    raise HarnessError("DELTA_EXPECTED_MCP_REJECTION_MISSING")


async def stale_preview_control(
    client: ProtocolClient,
    installation: Installation,
    snapshot: JsonObject,
    selected: JsonObject,
    viewer: PublicAPI,
) -> DeltaRejection:
    request = commit_request(installation, snapshot, selected)
    request["preview_sha256"] = "0" * 64
    return await _expect_mcp_rejection(
        client, request, "IMPORT_PREVIEW_STALE", "v1:stale_preview", viewer
    )


async def generate(
    client: ProtocolClient,
    reviewer: PublicAPI,
    installation: Installation,
    golden: DeltaPhaseGolden,
    api_id: str,
    api_version: int,
    directory: Path,
) -> tuple[GeneratedAsset, JsonObject, JsonObject, JsonObject, JsonObject, str]:
    start, generated_at = len(client.receipts), datetime.now(UTC)
    inspection = await client.call(
        "flowtest.inspect_contract",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "version": api_version,
        },
        scenario_id=SCENARIO,
        phase=golden.phase + ":inspect",
    )
    generated = await client.call(
        "flowtest.generate_test_design",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "api_version": api_version,
            "generation_policy": {
                "max_scenarios": 50,
                "include_negative": True,
                "include_auth": False,
                "include_state": False,
                "include_data_constraints": True,
                "pairwise_enabled": False,
            },
        },
        scenario_id=SCENARIO,
        phase=golden.phase + ":generate",
    )
    design, origin = object_value(generated["design"]), object_value(generated["origin"])
    coverage = await client.call(
        "flowtest.analyze_test_coverage",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "api_version": api_version,
            "generation_policy": origin["generation_policy"],
        },
        scenario_id=SCENARIO,
        phase=golden.phase + ":coverage",
    )
    begun = await client.call(
        "flowtest.begin_test_context",
        {
            "project_id": str(installation.project_id),
            "name": client.batch_key + ":" + golden.phase,
            "objective": "契约真实变更前后重新生成, 保持旧版固定来源与结果",
            "target_environment_id": str(installation.fixture_environment_id),
            "required_evidence": ["contract"],
            "contract_revisions": [
                {
                    "source_ref": f"api-definition://{api_id}/version/{api_version}",
                    "revision": origin["contract_fingerprint"],
                }
            ],
        },
        scenario_id=SCENARIO,
        phase=golden.phase + ":context",
    )
    revision = object_value(begun["revision"])
    context = {
        "context_id": begun["id"],
        "context_revision_id": revision["id"],
        "context_fingerprint": revision["fingerprint"],
    }
    happy = [item for item in objects_value(design["scenarios"]) if item["kind"] == "happy_path"]
    if generated["persisted"] is not False or len(happy) != 1:
        raise HarnessError("DELTA_DESIGN_NOT_READY")
    compiled = await client.call(
        "flowtest.compile_test_design",
        {
            "request": {
                "project_id": str(installation.project_id),
                "design": design,
                "design_fingerprint": generated["fingerprint"],
                "origin": origin,
                "scenario_ids": [happy[0]["id"]],
                "environment_id": str(installation.fixture_environment_id),
                "context_binding": context,
            }
        },
        scenario_id=SCENARIO,
        phase=golden.phase + ":compile",
    )
    asset, slot = await _materialize(
        client,
        reviewer,
        installation,
        golden,
        generated,
        compiled,
        context,
        start,
        generated_at,
        directory,
    )
    return asset, origin, inspection, coverage, compiled, slot


async def _materialize(
    client: ProtocolClient,
    reviewer: PublicAPI,
    installation: Installation,
    golden: DeltaPhaseGolden,
    generated: JsonObject,
    compiled: JsonObject,
    context: JsonObject,
    start: int,
    generated_at: datetime,
    directory: Path,
) -> tuple[GeneratedAsset, str]:
    if (compiled["readiness"], compiled["persisted"], compiled["execution_status"]) != (
        "ready",
        False,
        "not_run",
    ):
        raise HarnessError("DELTA_COMPILATION_NOT_READY")
    row = objects_value(compiled["scenarios"])[0]
    executable = object_value(row["executable_payload"])
    template = object_value(row["case_template"])
    if "workflow_id" in template or "workflow_version" in template:
        raise HarnessError("DELTA_SLOT_ALREADY_RUNNABLE")
    spec = object_value(executable["spec"])
    write_json(
        directory / "metadata-bindings.json",
        {
            "kind": "batch_namespace",
            "original_workflow_name": spec["name"],
            "workflow_name": client.batch_key + ":" + golden.phase,
            "native_definition_changed": False,
        },
    )
    proposal = await client.call(
        "flowtest.propose_flow_draft",
        {
            "project_id": str(installation.project_id),
            "context_id": context["context_id"],
            "context_revision_id": context["context_revision_id"],
            "spec": {**spec, "name": client.batch_key + ":" + golden.phase},
            "operation_mappings": executable["operation_mappings"],
            "operation_version_mappings": executable["operation_version_mappings"],
            "service_mappings": executable["service_mappings"],
            "source_ref": f"mcp://selftest/{client.batch_key}/{golden.phase}",
            "idempotency_key": client.batch_key + ":" + golden.phase + ":workflow",
            "dry_run": False,
        },
        scenario_id=SCENARIO,
        phase=golden.phase + ":workflow_proposal",
    )
    origin = object_value(generated["origin"])
    api_id = text_value(origin["api_definition_id"])
    flow = await review_flow(
        reviewer,
        project_id=str(installation.project_id),
        reviewer_id=str(installation.reviewer_id),
        proposal_id=text_value(proposal["change_set_id"]),
        expected_definition=object_value(executable["native_definition"]),
        expected_api_ids=(api_id,),
        output_dir=directory,
    )
    case = await _case(
        client,
        reviewer,
        installation,
        golden.phase,
        object_value(generated["design"]),
        flow,
        directory,
    )
    calls = tuple(client.receipts[start:])
    asset = GeneratedAsset(
        scenario_id=SCENARIO,
        variant_key=golden.phase,
        api_source=ApiSource(
            project_id=installation.project_id,
            api_definition_id=UUID(api_id),
            api_version=integer_value(origin["api_version"]),
            contract_fingerprint=text_value(origin["contract_fingerprint"]),
        ),
        design=object_value(generated["design"]),
        design_fingerprint=text_value(generated["fingerprint"]),
        compilation_fingerprint=text_value(compiled["compilation_fingerprint"]),
        oracle_bindings=tuple(
            OracleBinding(
                oracle_id=text_value(item["oracle_id"]),
                node_id=text_value(item["node_id"]),
                assertion_name="workflow_assertion",
                expression=text_value(item["normalized_expression"]),
                expected_value_digest=text_value(item["expected_value_fingerprint"]),
            )
            for item in objects_value(row["oracle_bindings"])
        ),
        workflow=flow,
        case=case,
        calls=calls,
        generated_at=generated_at,
        frozen_at=datetime.now(UTC),
    )
    write_json(directory / "asset.json", asset)
    return asset, text_value(template["workflow_slot"])


async def _case(
    client: ProtocolClient,
    reviewer: PublicAPI,
    installation: Installation,
    phase: str,
    design: JsonObject,
    workflow: ReviewedWorkflow,
    directory: Path,
) -> ReviewedCase:
    definition: JsonObject = {
        "workflow_id": workflow.workflow["id"],
        "workflow_version": workflow.version["version"],
        "environment_id": str(installation.fixture_environment_id),
        "runtime_variables": {},
        "runtime_headers": {},
    }
    result = await client.call(
        "flowtest.propose_test_design",
        {
            "project_id": str(installation.project_id),
            "title": client.batch_key + ":" + phase,
            "confidence": 1.0,
            "risk_level": "low",
            "design": design,
            "test_cases": [{"name": client.batch_key + ":" + phase, "definition": definition}],
            "idempotency_key": client.batch_key + ":" + phase + ":case",
            "dry_run": False,
            "source_ref": f"mcp://selftest/{client.batch_key}/{phase}",
        },
        scenario_id=SCENARIO,
        phase=phase + ":case_proposal",
    )
    return await review_case(
        reviewer,
        project_id=str(installation.project_id),
        reviewer_id=str(installation.reviewer_id),
        proposal_id=text_value(result["id"]),
        expected_definition=definition,
        output_dir=directory,
    )


def phase_manifest(
    frozen: DeltaManifest,
    pack: DeltaPack,
    golden: DeltaPhaseGolden,
    asset: GeneratedAsset,
    selection: PlanSelection,
    epoch: str,
) -> BatchManifest:
    expected_values = {
        "oracle_success_status": 200,
        "oracle_response_schema_200": golden.response_schema,
    }
    if {binding.oracle_id for binding in asset.oracle_bindings} != set(expected_values):
        raise HarnessError("DELTA_REQUIRED_ORACLE_SET_CHANGED")
    assertions = tuple(
        AssertionExpectation(
            node_id=binding.node_id,
            name=binding.assertion_name,
            expected=expected_values[binding.oracle_id],
            actual=200
            if binding.oracle_id.endswith("status")
            else {
                "actual": 1,
                "code": 0,
                "value": 0,
                "marker": golden.marker,
                "branch": "",
                "iteration_key": "",
                "request_count": golden.api_version,
                "fixture_epoch": epoch,
            },
            passed=True,
        )
        for binding in asset.oracle_bindings
    )
    suite = PublishedSuite(
        project_id=selection.project_id,
        id=selection.suite_id,
        version=selection.suite_version,
        fingerprint=selection.suite_fingerprint,
        case_versions=tuple(
            SuiteCaseVersion(case_id=item.case_id, version=item.version) for item in selection.cases
        ),
    )
    expected = ScenarioExpectation(
        scenario_id=SCENARIO,
        variant_key=golden.phase,
        expected=ExpectedOutcome(execution_status="passed", assertions=assertions),
        required_evidence=("execution", "assertions", "provenance"),
        required_oracle_ids=tuple(expected_values),
        expected_oracle_bindings=asset.oracle_bindings,
        expected_mcp_calls=asset.calls,
        expected_api_sources=(asset.api_source,),
        require_suite_provenance=True,
        expected_suite=suite,
        expected_target_snapshot_digest=selection.cases[0].target_snapshot_digest,
    )
    return BatchManifest(
        pack_id=pack.pack_id,
        pack_version=pack.version,
        pack_digest=frozen.pack_digest,
        policy_digest=canonical_digest({"phase": golden.phase}),
        project_id=frozen.installation.project_id,
        batch_key=asset.calls[0].batch_key,
        nonce=frozen.nonce,
        builds=frozen.builds,
        fixture_epoch=epoch,
        batch_kind="mcp_generated",
        generation_mode="deterministic_mcp",
        verification_scope="diagnostic_subset",
        expected_scenario_set=(SCENARIO,),
        required_scenario_set=(SCENARIO,),
        scenarios=(expected,),
        created_at=frozen.created_at,
        expires_at=frozen.expires_at,
    )


async def freeze_phase(
    client: ProtocolClient,
    reviewer: PublicAPI,
    frozen: DeltaManifest,
    pack: DeltaPack,
    golden: DeltaPhaseGolden,
    api_id: str,
    api_version: int,
    epoch: str,
    directory: Path,
) -> DeltaPhaseFreeze:
    asset, origin, inspection, coverage, compiled, slot = await generate(
        client, reviewer, frozen.installation, golden, api_id, api_version, directory
    )
    selection = await prepare_plan(
        reviewer,
        project_id=str(frozen.installation.project_id),
        cases=(asset.case,),
        batch_key=frozen.batch_key + ":" + golden.phase,
        output_dir=directory,
    )
    result = DeltaPhaseFreeze(
        phase=golden.phase,
        asset=asset,
        origin=origin,
        inspection=inspection,
        coverage=coverage,
        compilation=compiled,
        slot=slot,
        selection=selection,
        manifest=phase_manifest(frozen, pack, golden, asset, selection, epoch),
        frozen_at=datetime.now(UTC),
    )
    write_json(directory / "frozen-before-run.json", result)
    return result
