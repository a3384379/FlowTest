"""Freeze lifecycle status goldens and collect independent, bounded B postconditions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from scripts.selftest.collect_evidence import normalize_execution
from scripts.selftest.contracts import (
    AssertionExpectation,
    DesignSource,
    ExpectedOutcome,
    GenerationProvenance,
    PlanRunSnapshot,
    PublishedCase,
    PublishedSuite,
    PublishedWorkflow,
    ResourceAbsenceEvidence,
    ResourceAbsenceExpectation,
    ResponseFieldEvidence,
    ResponseFieldExpectation,
    ScenarioExpectation,
    ScenarioObservation,
    SuiteCaseVersion,
    SuiteReference,
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
from scripts.selftest.oracle_semantics import validate_published_oracles
from scripts.selftest.start_plan import PlanSelection

from app.schemas.self_test_evidence import SyntheticNameEvidence

if TYPE_CHECKING:
    from scripts.selftest.generation_lifecycle import LifecycleAsset


def _status_goldens(asset: LifecycleAsset) -> tuple[AssertionExpectation, ...]:
    statuses = {"login": 200, "create": 201, "list": 200, "patch": 200, "delete": 204}
    if {item.purpose for item in asset.operations} != set(statuses) or len(asset.operations) != 5:
        raise HarnessError("SELFTEST_LIFECYCLE_OPERATION_SET_CHANGED")
    purposes = {item.operation_ref: item.purpose for item in asset.operations}
    steps = {
        text_value(item["id"]): purposes[text_value(item["operation_ref"])]
        for item in objects_value(asset.integration_plan["steps"])
    }
    bindings = {item.oracle_id: item for item in asset.oracle_bindings}
    expected: list[AssertionExpectation] = []
    seen: set[str] = set()
    for oracle in objects_value(asset.integration_plan["oracles"]):
        if oracle["kind"] != "status":
            continue
        purpose = steps[text_value(oracle["step_id"])]
        status = statuses[purpose]
        binding = bindings[text_value(oracle["id"])]
        if (
            purpose in seen
            or oracle["operator"] != "equals"
            or canonical_digest(oracle["expected"]) != canonical_digest(status)
            or binding.expected_value_digest != canonical_digest(status)
        ):
            raise HarnessError("SELFTEST_LIFECYCLE_STATUS_GOLDEN_CHANGED")
        seen.add(purpose)
        expected.append(
            AssertionExpectation(
                node_id=binding.node_id,
                phase=binding.phase,
                name=binding.assertion_name,
                expected=status,
                actual=status,
                passed=True,
            )
        )
    if seen != set(statuses):
        raise HarnessError("SELFTEST_LIFECYCLE_STATUS_GOLDEN_MISSING")
    return tuple(expected)


def _suite(selection: PlanSelection) -> PublishedSuite:
    return PublishedSuite(
        project_id=selection.project_id,
        id=selection.suite_id,
        version=selection.suite_version,
        fingerprint=selection.suite_fingerprint,
        case_versions=tuple(
            SuiteCaseVersion(case_id=item.case_id, version=item.version) for item in selection.cases
        ),
    )


def _expected_digest(asset: LifecycleAsset, selection: PlanSelection) -> str:
    matches = [item for item in selection.cases if str(item.case_id) == asset.case.case["id"]]
    if (
        selection.project_id != asset.operations[0].api_source.project_id
        or len(matches) != 1
        or matches[0].version != asset.case.version["version"]
    ):
        raise HarnessError("SELFTEST_PLAN_EXPANSION_SNAPSHOT_CHANGED")
    return matches[0].target_snapshot_digest


def _response_goldens(asset: LifecycleAsset) -> tuple[ResponseFieldExpectation, ...]:
    definition = object_value(asset.workflow.version["definition"])
    api_nodes = [node for node in objects_value(definition["nodes"]) if node["type"] == "api"]
    purposes = {item.purpose: item for item in asset.operations}
    result: list[ResponseFieldExpectation] = []
    for purpose, name in (
        ("create", asset.created_resource_name),
        ("patch", asset.updated_resource_name),
    ):
        source = purposes[purpose].api_source
        matches = [
            node
            for node in api_nodes
            if (
                object_value(node["config"]).get("api_definition_id"),
                object_value(node["config"]).get("api_version"),
            )
            == (str(source.api_definition_id), source.api_version)
        ]
        if len(matches) != 1:
            raise HarnessError("SELFTEST_RESPONSE_FIELD_API_NODE_AMBIGUOUS")
        result.append(
            ResponseFieldExpectation(
                api_source=source,
                node_id=text_value(matches[0]["id"]),
                expected=name,
            )
        )
    return tuple(result)


def lifecycle_expectation(asset: LifecycleAsset, selection: PlanSelection) -> ScenarioExpectation:
    """Call before Plan execution; dynamic body/token/UUID values are never invented."""
    return ScenarioExpectation(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        expected=ExpectedOutcome(
            execution_status="passed",
            assertions=_status_goldens(asset),
            response_fields=_response_goldens(asset),
            resource_absence=ResourceAbsenceExpectation(
                project_id=asset.target_project_id,
                absent_names=(asset.created_resource_name, asset.updated_resource_name),
            ),
        ),
        required_evidence=(
            "execution",
            "assertions",
            "provenance",
            "postcondition",
            "response_fields",
        ),
        required_oracle_ids=tuple(item.oracle_id for item in asset.oracle_bindings),
        expected_oracle_bindings=asset.oracle_bindings,
        expected_mcp_calls=asset.calls,
        expected_combined_design_fingerprint=asset.combined_design_fingerprint,
        require_suite_provenance=True,
        expected_suite=_suite(selection),
        expected_target_snapshot_digest=_expected_digest(asset, selection),
        expected_api_sources=tuple(item.api_source for item in asset.operations),
        expected_design_sources=tuple(
            DesignSource(
                api_source=item.api_source,
                operation_ref=item.operation_ref,
                scenario_id=item.scenario_id,
                design_fingerprint=item.design_fingerprint,
            )
            for item in asset.operations
        ),
    )


def _published_workflow(asset: LifecycleAsset) -> PublishedWorkflow:
    definition = object_value(asset.workflow.version["definition"])
    nodes = {text_value(item["id"]): item for item in objects_value(definition["nodes"])}
    expected = {
        (str(item.api_source.api_definition_id), item.api_source.api_version)
        for item in asset.operations
    }
    actual = {
        (
            object_value(item["config"]).get("api_definition_id"),
            object_value(item["config"]).get("api_version"),
        )
        for item in nodes.values()
        if item["type"] == "api"
    }
    if actual != expected:
        raise HarnessError("SELFTEST_PUBLISHED_API_SOURCE_CHANGED")
    validate_published_oracles(
        definition, asset.integration_plan, asset.oracle_bindings, source_kind="integration_plan"
    )
    return PublishedWorkflow(
        project_id=asset.operations[0].api_source.project_id,
        id=UUID(text_value(asset.workflow.workflow["id"])),
        version_id=UUID(text_value(asset.workflow.version["id"])),
        version=integer_value(asset.workflow.version["version"]),
        fingerprint=text_value(asset.workflow.version["fingerprint"]),
        assertions=asset.oracle_bindings,
        api_sources=tuple(item.api_source for item in asset.operations),
    )


def _evidence_complete(raw: JsonObject) -> bool:
    return (
        raw["truncated"] is False
        and raw["bindings_complete"] is True
        and raw["node_total"] == len(objects_value(raw["nodes"]))
        and all(node["assertions_complete"] is True for node in objects_value(raw["nodes"]))
    )


def _response_field(
    detail: JsonObject,
    golden: ResponseFieldExpectation,
    execution: JsonObject,
    *,
    batch_key: str,
    scenario_id: str,
) -> ResponseFieldEvidence:
    snapshot = object_value(execution["snapshot"])
    api = object_value(object_value(snapshot["apis"])[golden.node_id])
    matches = [node for node in objects_value(detail["nodes"]) if node["node_id"] == golden.node_id]
    if (
        len(matches) != 1
        or api.get("definition_id") != str(golden.api_source.api_definition_id)
        or api.get("version") != golden.api_source.api_version
    ):
        raise HarnessError("SELFTEST_RESPONSE_FIELD_NODE_SOURCE_CHANGED")
    node = matches[0]
    if (
        node["node_type"] != "api"
        or node["status"] != "passed"
        or node["phase"] != "main"
        or node["attempts"] != 1
        or node["workflow_execution_id"] != execution["id"]
    ):
        raise HarnessError("SELFTEST_RESPONSE_FIELD_NODE_NOT_EXECUTED")
    # This authorized synthetic capture stays in memory. Only the bounded name is exported.
    value = object_value(object_value(node["output"])["body"]).get("name")
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise HarnessError("SELFTEST_RESPONSE_FIELD_NAME_MISSING")
    return ResponseFieldEvidence(
        batch_key=batch_key,
        scenario_id=scenario_id,
        project_id=UUID(text_value(execution["project_id"])),
        execution_id=UUID(text_value(execution["id"])),
        workflow_version_id=UUID(text_value(execution["workflow_version_id"])),
        api_source=golden.api_source,
        node_id=golden.node_id,
        actual=value,
        observed_at=datetime.now(UTC),
    )


async def _capture_fields(
    capture_reader: PublicAPI,
    asset: LifecycleAsset,
    raw: JsonObject,
    batch_key: str,
) -> tuple[ResponseFieldEvidence, ...]:
    detail = await capture_reader.object(
        "GET", f"/projects/{raw['project_id']}/workflow-executions/{raw['execution_id']}"
    )
    execution = object_value(detail["execution"])
    identity = ("project_id", "workflow_id", "workflow_version_id", "environment_id", "status")
    if (
        execution.get("id") != raw["execution_id"]
        or any(execution.get(key) != raw[key] for key in identity)
        or canonical_digest(execution.get("snapshot")) != raw["snapshot_digest"]
    ):
        raise HarnessError("SELFTEST_RESPONSE_FIELD_EXECUTION_CHANGED")
    return tuple(
        _response_field(
            detail, golden, execution, batch_key=batch_key, scenario_id=asset.scenario_id
        )
        for golden in _response_goldens(asset)
    )


async def _bounded_capture_fields(
    reader: PublicAPI,
    asset: LifecycleAsset,
    raw: JsonObject,
    batch_key: str,
) -> tuple[ResponseFieldEvidence, ...]:
    evidence = SyntheticNameEvidence.model_validate(
        await reader.object(
            "GET",
            f"/ci/projects/{raw['project_id']}/workflow-executions/{raw['execution_id']}/evidence/synthetic-names",
        )
    )
    expected = tuple(
        raw[key]
        for key in (
            "project_id",
            "execution_id",
            "workflow_id",
            "workflow_version_id",
            "environment_id",
            "status",
            "snapshot_digest",
        )
    )
    actual = (
        str(evidence.project_id),
        str(evidence.execution_id),
        str(evidence.workflow_id),
        str(evidence.workflow_version_id),
        str(evidence.environment_id),
        evidence.status,
        evidence.snapshot_digest,
    )
    if (
        actual != expected
        or evidence.batch_key != batch_key
        or evidence.scenario_id != asset.scenario_id
    ):
        raise HarnessError("SELFTEST_RESPONSE_FIELD_EXECUTION_CHANGED")
    indexed = {field.node_id: field for field in evidence.fields}
    goldens = _response_goldens(asset)
    if len(indexed) != 2 or set(indexed) != {golden.node_id for golden in goldens}:
        raise HarnessError("SELFTEST_RESPONSE_FIELD_NODE_SOURCE_CHANGED")
    fields = []
    for golden in goldens:
        field = indexed[golden.node_id]
        if field.api_source.model_dump(mode="json") != golden.api_source.model_dump(mode="json"):
            raise HarnessError("SELFTEST_RESPONSE_FIELD_NODE_SOURCE_CHANGED")
        fields.append(
            ResponseFieldEvidence(
                batch_key=batch_key,
                scenario_id=asset.scenario_id,
                project_id=evidence.project_id,
                execution_id=evidence.execution_id,
                workflow_version_id=evidence.workflow_version_id,
                api_source=golden.api_source,
                node_id=golden.node_id,
                actual=field.actual,
                observed_at=evidence.observed_at,
            )
        )
    return tuple(fields)


def _plan_snapshot(
    asset: LifecycleAsset,
    run: JsonObject,
    item: JsonObject,
    selection: PlanSelection,
    expected_digest: str,
) -> PlanRunSnapshot:
    matches = [value for value in selection.cases if str(value.case_id) == asset.case.case["id"]]
    if (
        selection.project_id != asset.operations[0].api_source.project_id
        or len(matches) != 1
        or matches[0].target_snapshot_digest != expected_digest
        or item["target_snapshot_digest"] != expected_digest
        or run["test_plan_id"] != str(selection.plan_id)
    ):
        raise HarnessError("SELFTEST_PLAN_EXPANSION_SNAPSHOT_CHANGED")
    return PlanRunSnapshot.model_validate(
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
                    "execution_id",
                )
            },
            "project_id": str(selection.project_id),
            "run_id": run["run_id"],
            "run_item_id": item["id"],
            "expected_target_snapshot_digest": expected_digest,
            "source_suite": SuiteReference(id=selection.suite_id, version=selection.suite_version),
        }
    )


def _provenance(
    asset: LifecycleAsset,
    run: PlanRunSnapshot,
    selection: PlanSelection,
    batch_key: str,
    catalog_digest: str,
) -> GenerationProvenance:
    definition = object_value(asset.case.version["definition"])
    return GenerationProvenance(
        batch_key=batch_key,
        scenario_id=asset.scenario_id,
        generation_mode="deterministic_mcp",
        api_source=asset.operations[0].api_source,
        design_sources=tuple(
            DesignSource(
                api_source=item.api_source,
                operation_ref=item.operation_ref,
                scenario_id=item.scenario_id,
                design_fingerprint=item.design_fingerprint,
            )
            for item in asset.operations
        ),
        design_fingerprint=asset.combined_design_fingerprint,
        combined_design_fingerprint=asset.combined_design_fingerprint,
        compilation_fingerprint=asset.compilation_fingerprint,
        catalog_digest=catalog_digest,
        oracle_bindings=asset.oracle_bindings,
        calls=asset.calls,
        workflow_proposal=asset.workflow.proposal,
        case_proposal=asset.case.proposal,
        workflow=_published_workflow(asset),
        case=PublishedCase(
            project_id=selection.project_id,
            id=UUID(text_value(asset.case.case["id"])),
            version=integer_value(asset.case.version["version"]),
            fingerprint=text_value(asset.case.version["fingerprint"]),
            workflow_id=UUID(text_value(definition["workflow_id"])),
            workflow_version=integer_value(definition["workflow_version"]),
            environment_id=UUID(text_value(definition["environment_id"])),
        ),
        suite=_suite(selection),
        run=run,
        generated_at=asset.generated_at,
        frozen_at=asset.frozen_at,
    )


async def collect_lifecycle_scenario(
    reader: PublicAPI,
    target_reader: PublicAPI,
    *,
    capture_reader: PublicAPI,
    asset: LifecycleAsset,
    run: JsonObject,
    item: JsonObject,
    batch_key: str,
    catalog_digest: str,
    expected_target_snapshot_digest: str,
    output_dir: Path,
    selection: PlanSelection,
    bounded_capture: bool = False,
) -> ScenarioObservation:
    snapshot = _plan_snapshot(asset, run, item, selection, expected_target_snapshot_digest)
    project_id = str(selection.project_id)
    base = f"/ci/projects/{project_id}/workflow-executions"
    ids = item["execution_ids"]
    if not isinstance(ids, list) or not ids or ids[-1] != item["execution_id"]:
        raise HarnessError("SELFTEST_ATTEMPT_IDS_INVALID")
    raw_attempts = [
        await reader.object("GET", f"{base}/{text_value(value)}/evidence") for value in ids
    ]
    if any(
        raw["source_plan_run_item_id"] != item["id"]
        or raw["source_case_id"] != asset.case.case["id"]
        or raw["source_case_version"] != asset.case.version["version"]
        for raw in raw_attempts
    ):
        raise HarnessError("SELFTEST_EXECUTION_CASE_SOURCE_MISMATCH")
    attempts = tuple(normalize_execution(raw) for raw in raw_attempts)
    fields = (
        await _bounded_capture_fields(capture_reader, asset, raw_attempts[-1], batch_key)
        if bounded_capture
        else await _capture_fields(capture_reader, asset, raw_attempts[-1], batch_key)
    )
    resources = await target_reader.request(
        "GET", f"/projects/{asset.target_project_id}/environments"
    )
    names = tuple(text_value(value["name"]) for value in objects_value(resources))
    result = ScenarioObservation(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        execution=attempts[-1],
        attempts=attempts,
        response_fields=fields,
        provenance=_provenance(asset, snapshot, selection, batch_key, catalog_digest),
        resource_absence=ResourceAbsenceEvidence(
            project_id=asset.target_project_id,
            returned_names=names,
            observed_at=datetime.now(UTC),
            complete=True,
        ),
        cleanup_status=(
            "failed"
            if {asset.created_resource_name, asset.updated_resource_name} & set(names)
            else "completed"
        ),
        evidence_complete=all(_evidence_complete(raw) for raw in raw_attempts)
        and item["attempts_complete"] is True,
    )
    write_json(output_dir / "observed.json", result)
    return result
