"""Collect the restricted CI projection and independent synthetic target journal."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from scripts.selftest.contracts import (
    ApiSource,
    DigestAssertionEvidence,
    ExecutionEvidence,
    FixtureJournal,
    FixtureRequest,
    GenerationProvenance,
    NodeEvidence,
    PlanRunSnapshot,
    PublishedCase,
    PublishedSuite,
    PublishedWorkflow,
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
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.oracle_semantics import validate_published_oracles
from scripts.selftest.start_plan import PlanSelection


async def wait_plan(
    reader: PublicAPI, project_id: str, run_id: str, deadline: datetime
) -> JsonObject:
    last: JsonObject = {}
    for _ in range(600):
        last = await reader.object(
            "GET",
            f"/ci/projects/{project_id}/test-plan-runs/{run_id}?page=1&page_size=100",
        )
        items = objects_value(last["items"])
        terminal = {"passed", "failed", "cancelled", "quarantined"}
        if last["status"] in terminal and all(item["status"] in terminal for item in items):
            break
        if datetime.now(UTC) >= deadline:
            break
        await asyncio.sleep(0.5)
    if (
        last.get("truncated") is not False
        or last.get("has_more") is not False
        or last.get("total") != len(objects_value(last.get("items", [])))
    ):
        raise HarnessError("SELFTEST_PLAN_EVIDENCE_INCOMPLETE")
    return last


def _normalize_nodes(nodes: list[JsonObject]) -> tuple[NodeEvidence, ...]:
    return tuple(
        NodeEvidence.model_validate(
            {
                **{
                    key: node[key]
                    for key in (
                        "node_id",
                        "node_type",
                        "phase",
                        "status",
                        "attempts",
                        "error_code",
                    )
                },
                "assertions": [
                    DigestAssertionEvidence.model_validate(
                        {"mode": "digest", **assertion}
                    ).model_dump(mode="json")
                    for assertion in objects_value(node["assertions"])
                ],
            }
        )
        for node in nodes
    )


def normalize_execution(raw: JsonObject) -> ExecutionEvidence:
    nodes = _normalize_nodes(objects_value(raw["nodes"]))
    nested = _normalize_nodes(objects_value(raw.get("nested_nodes", [])))
    sources = tuple(
        ApiSource(
            project_id=UUID(text_value(raw["project_id"])),
            api_definition_id=UUID(text_value(item["api_definition_id"])),
            api_version=integer_value(item["api_version"]),
            contract_fingerprint=text_value(item["contract_fingerprint"]),
        )
        for item in objects_value(raw["api_bindings"])
    )
    return ExecutionEvidence.model_validate(
        {
            **{
                key: raw[key]
                for key in (
                    "project_id",
                    "workflow_id",
                    "workflow_version_id",
                    "environment_id",
                    "status",
                    "error_code",
                    "run_purpose",
                    "main_status",
                    "cleanup_status",
                    "started_at",
                    "completed_at",
                    "snapshot_digest",
                    "workflow_fingerprint",
                )
            },
            "id": raw["execution_id"],
            "parent_execution_id": raw.get("parent_execution_id"),
            "dataset_row_index": raw.get("dataset_row_index"),
            "dataset": raw.get("dataset"),
            "children": raw.get("children", []),
            "children_complete": raw.get("children_complete", True) is True
            and raw.get("children_total", 0) == len(objects_value(raw.get("children", []))),
            "subflows": _subflow_bindings(raw),
            "subflows_complete": raw.get("subflows_complete", True),
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "nested_nodes": [node.model_dump(mode="json") for node in nested],
            "nested_nodes_complete": raw.get("nested_nodes_complete", True) is True
            and raw.get("nested_node_total", len(nested)) == len(nested),
            "api_sources": [item.model_dump(mode="json") for item in sources],
        }
    )


def _subflow_bindings(raw: JsonObject) -> list[JsonObject]:
    result: list[JsonObject] = []
    for item in objects_value(raw.get("subflows", [])):
        sources = tuple(
            ApiSource(
                project_id=UUID(text_value(raw["project_id"])),
                api_definition_id=UUID(text_value(api["api_definition_id"])),
                api_version=integer_value(api["api_version"]),
                contract_fingerprint=text_value(api["contract_fingerprint"]),
            )
            for api in objects_value(item["api_bindings"])
        )
        result.append(
            {
                **{
                    key: item[key]
                    for key in (
                        "path",
                        "workflow_id",
                        "workflow_version_id",
                        "workflow_version",
                        "workflow_fingerprint",
                        "complete",
                    )
                },
                "project_id": raw["project_id"],
                "api_sources": [
                    source.model_dump(mode="json")
                    for source in sorted(
                        set(sources), key=lambda source: str(source.api_definition_id)
                    )
                ],
            }
        )
    return result


async def collect_children(
    reader: PublicAPI, project: str, raw: JsonObject
) -> tuple[tuple[ExecutionEvidence, ...], bool]:
    refs = objects_value(raw.get("children", []))
    if (
        len(refs) > 500
        or raw.get("children_complete", True) is not True
        or raw.get("children_total", 0) != len(refs)
    ):
        return (), False
    children: list[ExecutionEvidence] = []
    complete = True
    for reference in refs:
        payload = await reader.object(
            "GET",
            f"/ci/projects/{project}/workflow-executions/{text_value(reference['execution_id'])}/evidence",
        )
        children.append(normalize_execution(payload))
        complete = (
            complete
            and payload["truncated"] is False
            and payload["bindings_complete"] is True
            and payload["node_total"] == len(objects_value(payload["nodes"]))
            and all(node["assertions_complete"] is True for node in objects_value(payload["nodes"]))
        )
    return tuple(children), complete


async def journal(
    observer: PublicAPI,
    batch_key: str,
    scenario_id: str,
    *,
    deadline: datetime | None = None,
) -> FixtureJournal:
    """Wait only for observed request UUIDs; never manufacture target completion."""
    stop = datetime.now(UTC) + timedelta(seconds=5.5)
    if deadline is not None:
        stop = min(stop, deadline)
    for _ in range(56):
        snapshot = await _journal_snapshot(observer, batch_key, scenario_id)
        remaining = (stop - datetime.now(UTC)).total_seconds()
        if snapshot.metrics is None or snapshot.metrics.active_count == 0 or remaining <= 0:
            return snapshot
        await asyncio.sleep(min(0.1, remaining))
    return snapshot


async def _journal_snapshot(
    observer: PublicAPI, batch_key: str, scenario_id: str
) -> FixtureJournal:
    entries: list[FixtureRequest] = []
    cursor, latest = 0, {}
    for _ in range(10):
        latest = await observer.object(
            "GET",
            f"/selftest/batches/{batch_key}/scenarios/{scenario_id}/journal?after_sequence={cursor}&limit=100",
        )
        for item in objects_value(latest["entries"]):
            entries.append(
                FixtureRequest.model_validate(
                    {
                        "synthetic_precedence_header": item.get("synthetic_precedence_header"),
                        "binary_response": item.get("binary_response"),
                        "binary_request": item.get("binary_request"),
                        "synthetic_cookie": item.get("synthetic_cookie"),
                        "received_at": item.get("received_at"),
                        **{
                            key: item[key]
                            for key in (
                                "sequence",
                                "method",
                                "path",
                                "response_status",
                                "marker",
                                "request_body",
                                "response_body",
                                "authorization_present",
                                "cookie_present",
                                "fixture_epoch",
                            )
                        },
                    }
                )
            )
        following = latest.get("next_sequence")
        if following is None:
            break
        next_cursor = integer_value(following)
        if next_cursor <= cursor:
            raise HarnessError("SELFTEST_JOURNAL_CURSOR_INVALID")
        cursor = next_cursor
    else:
        raise HarnessError("SELFTEST_JOURNAL_PAGE_BUDGET")
    return FixtureJournal.model_validate(
        {
            **{
                key: latest[key]
                for key in (
                    "batch_key",
                    "scenario_id",
                    "nonce",
                    "fixture_epoch",
                    "fixture_digest",
                    "request_count",
                    "truncated",
                    "expired",
                )
            },
            "truncated": latest["truncated"] is True or latest["epoch_changed"] is True,
            "entries": [item.model_dump(mode="json") for item in entries],
            "metrics": latest.get("metrics"),
            "budget": latest.get("budget"),
        }
    )


def _published_workflow(asset: GeneratedAsset) -> PublishedWorkflow:
    definition = object_value(asset.workflow.version["definition"])
    nodes = {text_value(node["id"]): node for node in objects_value(definition["nodes"])}
    api_nodes = [object_value(node["config"]) for node in nodes.values() if node["type"] == "api"]
    references = {(item.get("api_definition_id"), item.get("api_version")) for item in api_nodes}
    if references != {(str(asset.api_source.api_definition_id), asset.api_source.api_version)}:
        raise HarnessError("SELFTEST_PUBLISHED_API_SOURCE_CHANGED")
    validate_published_oracles(
        definition, asset.design, asset.oracle_bindings, source_kind="design"
    )
    return PublishedWorkflow(
        project_id=asset.api_source.project_id,
        id=UUID(text_value(asset.workflow.workflow["id"])),
        version_id=UUID(text_value(asset.workflow.version["id"])),
        version=integer_value(asset.workflow.version["version"]),
        fingerprint=text_value(asset.workflow.version["fingerprint"]),
        assertions=asset.oracle_bindings,
        api_sources=(asset.api_source,),
    )


async def collect_scenario(
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    asset: GeneratedAsset,
    run: JsonObject,
    item: JsonObject,
    batch_key: str,
    catalog_digest: str,
    expected_target_snapshot_digest: str,
    selection: PlanSelection,
    output_dir: Path,
    deadline: datetime | None = None,
) -> ScenarioObservation:
    if item["target_snapshot_digest"] != expected_target_snapshot_digest:
        raise HarnessError("SELFTEST_PLAN_EXPANSION_SNAPSHOT_CHANGED")
    project_id, execution_id = (
        str(asset.api_source.project_id),
        text_value(item["execution_id"]),
    )
    base = f"/ci/projects/{project_id}/workflow-executions"
    raw = await reader.object("GET", f"{base}/{execution_id}/evidence")
    complete = (
        raw["truncated"] is False
        and raw["bindings_complete"] is True
        and raw["node_total"] == len(objects_value(raw["nodes"]))
        and all(node["assertions_complete"] is True for node in objects_value(raw["nodes"]))
    )
    if (
        raw["source_plan_run_item_id"] != item["id"]
        or raw["source_case_id"] != asset.case.case["id"]
    ):
        raise HarnessError("SELFTEST_EXECUTION_CASE_SOURCE_MISMATCH")
    execution = normalize_execution(raw)
    attempt_ids = item["execution_ids"]
    if not isinstance(attempt_ids, list):
        raise HarnessError("SELFTEST_ATTEMPT_IDS_INVALID")
    attempts = tuple(
        [
            normalize_execution(await reader.object("GET", f"{base}/{attempt_id}/evidence"))
            for attempt_id in attempt_ids
        ]
    )
    fixture = await journal(observer, batch_key, asset.scenario_id, deadline=deadline)
    definition = object_value(asset.case.version["definition"])
    provenance = GenerationProvenance(
        batch_key=batch_key,
        scenario_id=asset.scenario_id,
        generation_mode="deterministic_mcp",
        api_source=asset.api_source,
        design_fingerprint=asset.design_fingerprint,
        compilation_fingerprint=asset.compilation_fingerprint,
        catalog_digest=catalog_digest,
        oracle_bindings=asset.oracle_bindings,
        calls=asset.calls,
        workflow_proposal=asset.workflow.proposal,
        case_proposal=asset.case.proposal,
        workflow=_published_workflow(asset),
        case=PublishedCase(
            project_id=asset.api_source.project_id,
            id=UUID(text_value(asset.case.case["id"])),
            version=integer_value(asset.case.version["version"]),
            fingerprint=text_value(asset.case.version["fingerprint"]),
            workflow_id=UUID(text_value(definition["workflow_id"])),
            workflow_version=integer_value(definition["workflow_version"]),
            environment_id=UUID(text_value(definition["environment_id"])),
        ),
        suite=PublishedSuite(
            project_id=selection.project_id,
            id=selection.suite_id,
            version=selection.suite_version,
            fingerprint=selection.suite_fingerprint,
            case_versions=tuple(
                SuiteCaseVersion(case_id=case.case_id, version=case.version)
                for case in selection.cases
            ),
        ),
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
                "project_id": project_id,
                "run_id": run["run_id"],
                "run_item_id": item["id"],
                "execution_id": execution_id,
                "expected_target_snapshot_digest": expected_target_snapshot_digest,
                "source_suite": SuiteReference(
                    id=selection.suite_id, version=selection.suite_version
                ).model_dump(mode="json"),
            }
        ),
        generated_at=asset.generated_at,
        frozen_at=asset.frozen_at,
    )
    result = ScenarioObservation(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        execution=execution,
        attempts=attempts,
        journal=fixture,
        provenance=provenance,
        cleanup_status="pending",
        evidence_complete=complete and item["attempts_complete"] is True,
    )
    write_json(output_dir / "observed.json", result)
    return result
