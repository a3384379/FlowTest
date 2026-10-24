"""Freeze known synthetic responses before launch and collect the restricted CI projection."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bad_targets_contracts import BadTargetAsset, BadTargetGolden
from scripts.selftest.collect_evidence import journal, normalize_execution
from scripts.selftest.contracts import (
    AssertionExpectation,
    ExpectedOutcome,
    FixtureResponseExpectation,
    GenerationProvenance,
    PlanRunSnapshot,
    PublishedCase,
    PublishedSuite,
    PublishedWorkflow,
    ScenarioExpectation,
    ScenarioObservation,
    SuiteCaseVersion,
    SuiteReference,
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
from scripts.selftest.oracle_semantics import validate_published_oracles
from scripts.selftest.start_plan import PlanSelection


def frozen_suite(selection: PlanSelection) -> PublishedSuite:
    return PublishedSuite(
        project_id=selection.project_id,
        id=selection.suite_id,
        version=selection.suite_version,
        fingerprint=selection.suite_fingerprint,
        case_versions=tuple(
            SuiteCaseVersion(case_id=item.case_id, version=item.version) for item in selection.cases
        ),
    )


def snapshot(asset: BadTargetAsset, selection: PlanSelection) -> str:
    matches = [item for item in selection.cases if str(item.case_id) == asset.case.case["id"]]
    if len(matches) != 1 or matches[0].version != asset.case.version["version"]:
        raise HarnessError("SELFTEST_BADTARGET_CASE_SELECTION_CHANGED")
    return matches[0].target_snapshot_digest


def response_golden(
    golden: BadTargetGolden,
    epoch: str,
    *,
    fault: bool,
    purpose: str,
) -> JsonObject:
    seed = purpose == "seed"
    return {
        "actual": golden.actual,
        "code": golden.bad_code if fault else golden.good_code,
        "value": golden.bad_value if fault and not seed else golden.good_value,
        "marker": "",
        "branch": "",
        "iteration_key": "dependency-good" if golden.requests == 2 and not seed else "",
        "request_count": 1 if seed else golden.requests,
        "fixture_epoch": epoch,
    }


def expectation(
    asset: BadTargetAsset,
    golden: BadTargetGolden,
    epoch: str,
    selection: PlanSelection,
    *,
    fault: bool,
) -> ScenarioExpectation:
    assertions = tuple(
        AssertionExpectation(
            node_id=item.binding.node_id,
            phase=item.binding.phase,
            name=item.binding.assertion_name,
            expected=item.expected,
            actual=golden.status
            if item.kind == "status"
            else response_golden(golden, epoch, fault=fault, purpose=item.purpose),
            passed=not (fault and item.kind == "schema" and item.purpose != "seed"),
        )
        for item in asset.assertions
    )
    failures = [item for item in assertions if not item.passed]
    if len(failures) != int(fault):
        raise HarnessError("SELFTEST_BADTARGET_FAILURE_POSITION_NOT_UNIQUE")
    sources = tuple(item.api_source for item in asset.operations)
    return ScenarioExpectation(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        expected=ExpectedOutcome(
            execution_status="failed" if fault else "passed",
            error_code="WORKFLOW_ASSERTION_FAILED" if fault else None,
            node_id=failures[0].node_id if fault else None,
            phase="main" if fault else None,
            request_count=golden.requests,
            assertions=assertions,
            fixture_responses=tuple(
                FixtureResponseExpectation(
                    response_status=golden.status,
                    actual=golden.actual,
                    code=golden.bad_code if fault else golden.good_code,
                )
                for _ in range(golden.requests)
            ),
        ),
        required_evidence=("execution", "assertions", "fixture_journal", "provenance"),
        required_oracle_ids=tuple(item.oracle_id for item in asset.oracle_bindings),
        expected_oracle_bindings=asset.oracle_bindings,
        expected_mcp_calls=asset.calls,
        expected_api_sources=sources,
        expected_design_sources=tuple(item.source for item in asset.operations)
        if len(asset.operations) > 1
        else (),
        expected_combined_design_fingerprint=asset.combined_design_fingerprint,
        require_suite_provenance=True,
        expected_suite=frozen_suite(selection),
        expected_target_snapshot_digest=snapshot(asset, selection),
    )


def _workflow(asset: BadTargetAsset) -> PublishedWorkflow:
    definition = object_value(asset.workflow.version["definition"])
    validate_published_oracles(
        definition, asset.oracle_source, asset.oracle_bindings, source_kind=asset.oracle_source_kind
    )
    nodes = objects_value(definition["nodes"])
    actual = {
        (
            object_value(n["config"]).get("api_definition_id"),
            object_value(n["config"]).get("api_version"),
        )
        for n in nodes
        if n["type"] == "api"
    }
    sources = tuple(item.api_source for item in asset.operations)
    if actual != {(str(item.api_definition_id), item.api_version) for item in sources}:
        raise HarnessError("SELFTEST_BADTARGET_PUBLISHED_API_SOURCE_CHANGED")
    return PublishedWorkflow(
        project_id=sources[0].project_id,
        id=UUID(text_value(asset.workflow.workflow["id"])),
        version_id=UUID(text_value(asset.workflow.version["id"])),
        version=integer_value(asset.workflow.version["version"]),
        fingerprint=text_value(asset.workflow.version["fingerprint"]),
        assertions=asset.oracle_bindings,
        api_sources=sources,
    )


def _provenance(
    asset: BadTargetAsset,
    run: JsonObject,
    item: JsonObject,
    selection: PlanSelection,
    batch: str,
    catalog_digest: str,
) -> GenerationProvenance:
    definition = object_value(asset.case.version["definition"])
    source = asset.operations[0]
    return GenerationProvenance(
        batch_key=batch,
        scenario_id=asset.scenario_id,
        generation_mode="deterministic_mcp",
        api_source=source.api_source,
        design_sources=tuple(item.source for item in asset.operations)
        if len(asset.operations) > 1
        else (),
        design_fingerprint=asset.combined_design_fingerprint or source.design_fingerprint,
        combined_design_fingerprint=asset.combined_design_fingerprint,
        compilation_fingerprint=asset.compilation_fingerprint,
        catalog_digest=catalog_digest,
        oracle_bindings=asset.oracle_bindings,
        calls=asset.calls,
        workflow_proposal=asset.workflow.proposal,
        case_proposal=asset.case.proposal,
        workflow=_workflow(asset),
        case=PublishedCase(
            project_id=source.api_source.project_id,
            id=UUID(text_value(asset.case.case["id"])),
            version=integer_value(asset.case.version["version"]),
            fingerprint=text_value(asset.case.version["fingerprint"]),
            workflow_id=UUID(text_value(definition["workflow_id"])),
            workflow_version=integer_value(definition["workflow_version"]),
            environment_id=UUID(text_value(definition["environment_id"])),
        ),
        suite=frozen_suite(selection),
        run=PlanRunSnapshot.model_validate(
            {
                **{
                    key: item[key]
                    for key in (
                        "target_type",
                        "target_id",
                        "target_version",
                        "workflow_id",
                        "workflow_version",
                        "environment_id",
                        "attempts",
                        "status",
                        "target_snapshot_digest",
                    )
                },
                "project_id": str(selection.project_id),
                "run_id": run["run_id"],
                "run_item_id": item["id"],
                "execution_id": item["execution_id"],
                "expected_target_snapshot_digest": snapshot(asset, selection),
                "source_suite": SuiteReference(
                    id=selection.suite_id, version=selection.suite_version
                ).model_dump(mode="json"),
            }
        ),
        generated_at=asset.generated_at,
        frozen_at=asset.frozen_at,
    )


async def collect_bad_target(
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    asset: BadTargetAsset,
    run: JsonObject,
    item: JsonObject,
    selection: PlanSelection,
    batch: str,
    catalog_digest: str,
    output_dir: Path,
    deadline: datetime,
) -> ScenarioObservation:
    if (
        item["target_snapshot_digest"] != snapshot(asset, selection)
        or item["target_id"] != asset.case.case["id"]
        or item["attempts_complete"] is not True
    ):
        raise HarnessError("SELFTEST_BADTARGET_RUN_SELECTION_MISMATCH")
    base = f"/ci/projects/{selection.project_id}/workflow-executions"
    raw = await reader.object("GET", f"{base}/{text_value(item['execution_id'])}/evidence")
    if raw["source_plan_run_item_id"] != item["id"] or raw["source_case_id"] != item["target_id"]:
        raise HarnessError("SELFTEST_BADTARGET_EXECUTION_MEMBERSHIP_MISMATCH")
    execution = normalize_execution(raw)
    complete = (
        raw["truncated"] is False
        and raw["bindings_complete"] is True
        and raw["node_total"] == len(objects_value(raw["nodes"]))
        and all(node["assertions_complete"] is True for node in objects_value(raw["nodes"]))
    )
    # Retry zero is frozen by prepare_plan. Unknown or additional attempts are never accepted.
    if item["attempts"] != 1 or item["execution_ids"] != [str(execution.id)]:
        raise HarnessError("SELFTEST_BADTARGET_ATTEMPT_SET_MISMATCH")
    observed = ScenarioObservation(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        execution=execution,
        attempts=(execution,),
        journal=await journal(observer, batch, asset.scenario_id, deadline=deadline),
        provenance=_provenance(asset, run, item, selection, batch, catalog_digest),
        cleanup_status="pending",
        evidence_complete=complete,
    )
    write_json(output_dir / "observed.json", observed)
    return observed
