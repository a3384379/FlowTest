"""Observer behavior against hostile or incomplete candidate evidence."""

from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import BatchEvidence, BatchManifest, canonical_digest  # noqa: E402
from scripts.selftest.verify import main, verify_batch, write_report  # noqa: E402

SHA = "a" * 64
PROJECT = str(uuid4())
FLOW = str(uuid4())
FLOW_VERSION = str(uuid4())
ENV = str(uuid4())
EXECUTION = str(uuid4())
CASE = str(uuid4())
API = str(uuid4())
START = "2026-10-23T00:00:00+00:00"
GENERATED = "2026-10-23T00:00:01+00:00"
FROZEN = "2026-10-23T00:00:02+00:00"
EXECUTED = "2026-10-23T00:00:03+00:00"
COLLECTED = "2026-10-23T00:00:05+00:00"
DEADLINE = "2026-10-23T00:10:00+00:00"


def manifest_payload() -> dict[str, Any]:
    return {
        "pack_id": "mcp-core",
        "pack_version": "1.0.0",
        "pack_digest": SHA,
        "policy_digest": SHA,
        "project_id": PROJECT,
        "batch_key": "batch-1",
        "nonce": "nonce-1",
        "builds": {
            "runner": "runner-1",
            "target": "target-1",
            "fixture": "fixture-1",
            "verifier": "verifier-1",
        },
        "fixture_epoch": "epoch-1",
        "batch_kind": "fixed_baseline",
        "verification_scope": "full_pack",
        "expected_scenario_set": ["ST-ENG-002"],
        "required_scenario_set": ["ST-ENG-002"],
        "ci_run_id": "ci-1",
        "ci_attempt": 1,
        "created_at": START,
        "expires_at": DEADLINE,
        "scenarios": [
            {
                "scenario_id": "ST-ENG-002",
                "required_evidence": ["execution", "assertions", "fixture_journal"],
                "expected": {
                    "execution_status": "failed",
                    "error_code": "WORKFLOW_ASSERTION_FAILED",
                    "node_id": "assert_canary",
                    "phase": "main",
                    "request_count": 1,
                    "fixture_responses": [{"response_status": 200, "actual": 1, "code": 0}],
                    "assertions": [
                        {
                            "node_id": "assert_canary",
                            "name": "workflow_assertion",
                            "passed": False,
                            "expected": 2,
                            "actual": 1,
                        }
                    ],
                },
            }
        ],
    }


def evidence_payload() -> dict[str, Any]:
    execution = {
        "id": EXECUTION,
        "project_id": PROJECT,
        "workflow_id": FLOW,
        "workflow_version_id": FLOW_VERSION,
        "environment_id": ENV,
        "status": "failed",
        "error_code": "WORKFLOW_ASSERTION_FAILED",
        "main_status": "failed",
        "cleanup_status": "passed",
        "snapshot_digest": SHA,
        "workflow_fingerprint": SHA,
        "started_at": EXECUTED,
        "completed_at": COLLECTED,
        "nodes": [
            {
                "node_id": "assert_canary",
                "node_type": "assert",
                "phase": "main",
                "status": "failed",
                "attempts": 1,
                "error_code": "WORKFLOW_ASSERTION_FAILED",
                "assertions": [
                    {"name": "workflow_assertion", "passed": False, "expected": 2, "actual": 1}
                ],
            }
        ],
    }
    return {
        "batch_key": "batch-1",
        "nonce": "nonce-1",
        "pack_digest": SHA,
        "policy_digest": SHA,
        "builds": {
            "runner": "runner-1",
            "target": "target-1",
            "fixture": "fixture-1",
            "verifier": "verifier-1",
        },
        "ci_run_id": "ci-1",
        "ci_attempt": 1,
        "collected_at": COLLECTED,
        "cleanup_status": "completed",
        "scenarios": [
            {
                "scenario_id": "ST-ENG-002",
                "execution": execution,
                "attempts": [copy.deepcopy(execution)],
                "cleanup_status": "completed",
                "journal": {
                    "batch_key": "batch-1",
                    "scenario_id": "ST-ENG-002",
                    "nonce": "nonce-1",
                    "fixture_epoch": "epoch-1",
                    "fixture_digest": "fixture-1",
                    "request_count": 1,
                    "entries": [
                        {
                            "sequence": 1,
                            "method": "GET",
                            "path": "/selftest/request",
                            "response_status": 200,
                            "response_body": {"actual": 1, "code": 0},
                        }
                    ],
                },
            }
        ],
    }


def verify(manifest: dict[str, Any], evidence: dict[str, Any]) -> Any:
    return verify_batch(
        BatchManifest.model_validate(manifest),
        BatchEvidence.model_validate(evidence),
        now=datetime.fromisoformat(COLLECTED),
    )


def finding_codes(report: Any) -> set[str]:
    return {item.code for item in report.findings} | {
        item.code for result in report.scenarios for item in result.findings
    }


def test_exact_negative_canary_matches_and_keeps_failed_execution() -> None:
    report = verify(manifest_payload(), evidence_payload())
    assert report.exit_code == 0
    assert report.batch_verdict == "passed"
    assert report.scenarios[0].observed_status == "failed"
    assert report.scenarios[0].verification_status == "matched"
    assert report.provenance == "local_untrusted"


@pytest.mark.parametrize("present", [False, True])
def test_synthetic_request_value_presence_survives_serialization_and_cannot_be_swapped(present):
    manifest, evidence = manifest_payload(), evidence_payload()
    manifest["scenarios"][0]["expected"]["expected_request_value_presence"] = [present]
    entry = evidence["scenarios"][0]["journal"]["entries"][0]
    entry["request_body"] = {"value": None} if present else {}
    parsed = BatchEvidence.model_validate(evidence)
    saved = parsed.model_dump(mode="json")
    assert saved["scenarios"][0]["journal"]["entries"][0]["request_value_present"] is present
    assert verify(manifest, saved).exit_code == 0
    saved["scenarios"][0]["journal"]["entries"][0]["request_value_present"] = not present
    report = verify(manifest, saved)
    assert report.exit_code == 1
    assert "REQUEST_VALUE_PRESENCE_MISMATCH" in finding_codes(report)


def test_omitted_request_presence_cannot_be_reconstructed_from_default_null_after_flag_deleted():
    manifest, evidence = manifest_payload(), evidence_payload()
    manifest["scenarios"][0]["expected"]["expected_request_value_presence"] = [False]
    evidence["scenarios"][0]["journal"]["entries"][0]["request_body"] = {}
    saved = BatchEvidence.model_validate(evidence).model_dump(mode="json")
    del saved["scenarios"][0]["journal"]["entries"][0]["request_value_present"]
    report = verify(manifest, saved)
    assert report.exit_code != 0
    assert "REQUEST_VALUE_PRESENCE_MISMATCH" in finding_codes(report)


@pytest.mark.parametrize("actual", [1, True])
def test_hash_only_assertion_evidence_compares_to_independent_golden_values(actual: Any) -> None:
    evidence = evidence_payload()
    assertion = {
        "mode": "digest",
        "name": "workflow_assertion",
        "passed": False,
        "expected_digest": canonical_digest(2),
        "actual_digest": canonical_digest(actual),
    }
    evidence["scenarios"][0]["execution"]["nodes"][0]["assertions"] = [assertion]
    evidence["scenarios"][0]["attempts"][0]["nodes"][0]["assertions"] = [copy.deepcopy(assertion)]
    report = verify(manifest_payload(), evidence)
    assert (report.exit_code == 0) is (type(actual) is int)


def test_digest_mode_rejects_missing_digest_and_plaintext_extras() -> None:
    evidence = evidence_payload()
    evidence["scenarios"][0]["execution"]["nodes"][0]["assertions"] = [
        {
            "mode": "digest",
            "name": "workflow_assertion",
            "passed": False,
            "expected_digest": canonical_digest(2),
            "expected": 2,
        }
    ]
    with pytest.raises(ValidationError):
        BatchEvidence.model_validate(evidence)


def test_expired_batch_cannot_be_replayed_with_old_collection_time() -> None:
    report = verify_batch(
        BatchManifest.model_validate(manifest_payload()),
        BatchEvidence.model_validate(evidence_payload()),
        now=datetime.fromisoformat(DEADLINE) + timedelta(seconds=1),
    )
    assert report.exit_code != 0
    assert report.evidence_integrity == "expired"


@pytest.mark.parametrize(
    "change", ["passed", "timeout", "node", "phase", "skipped", "assertion", "value_type"]
)
def test_canary_rejects_wrong_failure_or_missing_assertion(change: str) -> None:
    evidence = evidence_payload()
    execution = evidence["scenarios"][0]["execution"]
    node = execution["nodes"][0]
    if change == "passed":
        execution["status"] = "passed"
    elif change == "timeout":
        execution["error_code"] = node["error_code"] = "NODE_TIMEOUT"
    elif change == "node":
        node["node_id"] = "other_assert"
    elif change == "phase":
        node["phase"] = "cleanup"
    elif change == "skipped":
        node["status"] = "skipped"
    elif change == "assertion":
        node["assertions"] = []
    else:
        node["assertions"][0]["actual"] = True
    report = verify(manifest_payload(), evidence)
    assert report.exit_code != 0
    assert report.scenarios[0].verification_status != "matched"


@pytest.mark.parametrize("change", ["empty", "missing", "duplicate", "unexpected"])
def test_actual_set_is_exact_nonempty(change: str) -> None:
    evidence = evidence_payload()
    if change in {"empty", "missing"}:
        evidence["scenarios"] = []
    elif change == "duplicate":
        evidence["scenarios"].append(copy.deepcopy(evidence["scenarios"][0]))
    else:
        extra = copy.deepcopy(evidence["scenarios"][0])
        extra["scenario_id"] = "ST-EXTRA-001"
        evidence["scenarios"].append(extra)
    assert verify(manifest_payload(), evidence).exit_code != 0


@pytest.mark.parametrize("field", ["expected_scenario_set", "required_scenario_set"])
def test_empty_manifest_denominator_is_invalid(field: str) -> None:
    manifest = manifest_payload()
    manifest[field] = []
    with pytest.raises(ValidationError):
        BatchManifest.model_validate(manifest)


def test_selected_optional_failure_still_blocks_batch() -> None:
    manifest = manifest_payload()
    manifest["expected_scenario_set"].append("ST-OPTIONAL-001")
    optional = copy.deepcopy(manifest["scenarios"][0])
    optional["scenario_id"] = "ST-OPTIONAL-001"
    manifest["scenarios"].append(optional)
    report = verify(manifest, evidence_payload())
    assert report.exit_code != 0
    assert "REQUIRED_SCENARIO_MISSING" in finding_codes(report)


def test_subset_cannot_reduce_trusted_required_policy() -> None:
    manifest = manifest_payload()
    manifest["verification_scope"] = "diagnostic_subset"
    manifest["trusted_required_scenario_set"] = ["ST-ENG-002", "ST-MCP-025"]
    with pytest.raises(ValidationError):
        BatchManifest.model_validate(manifest)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("scenarios", 0, "journal"), None),
        (("scenarios", 0, "journal", "truncated"), True),
        (("scenarios", 0, "journal", "entries", 0, "sequence"), 2),
        (("scenarios", 0, "journal", "fixture_epoch"), "epoch-2"),
        (("scenarios", 0, "journal", "entries", 0, "response_body", "actual"), 2),
        (("scenarios", 0, "journal", "entries", 0, "authorization_present"), True),
        (("scenarios", 0, "attempts"), []),
        (("cleanup_status",), "failed"),
        (("scenarios", 0, "execution", "status"), "queued"),
        (("observer_error",), "synthetic_crash"),
        (("builds", "runner"), "old-runner"),
        (("ci_attempt",), 2),
        (("nonce",), "old-nonce"),
        (("collected_at",), "2026-10-23T00:11:00+00:00"),
    ],
)
def test_missing_or_contradictory_evidence_cannot_pass(
    path: tuple[str | int, ...], value: Any
) -> None:
    evidence = evidence_payload()
    cursor: Any = evidence
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    assert verify(manifest_payload(), evidence).exit_code != 0


def test_control_pages_require_all_rows_and_pages() -> None:
    manifest = manifest_payload()
    manifest["scenarios"][0]["required_evidence"].append("control_records")
    evidence = evidence_payload()
    scenario = evidence["scenarios"][0]
    scenario["control_pages"] = [{"page": 1, "page_size": 1, "total": 2, "ordinals": [0]}]
    assert verify(manifest, evidence).exit_code != 0
    scenario["control_pages"].append({"page": 2, "page_size": 1, "total": 2, "ordinals": [1]})
    assert verify(manifest, evidence).exit_code == 0


def add_provenance(manifest: dict[str, Any], evidence: dict[str, Any]) -> None:
    manifest["batch_kind"] = "mcp_generated"
    manifest["generation_mode"] = "deterministic_mcp"
    manifest["scenarios"][0]["required_oracle_ids"] = ["oracle-canary"]
    scenario = evidence["scenarios"][0]
    source = {
        "project_id": PROJECT,
        "api_definition_id": API,
        "api_version": 1,
        "contract_fingerprint": SHA,
    }
    scenario["execution"]["api_sources"] = [source]
    scenario["attempts"][0]["api_sources"] = [copy.deepcopy(source)]
    oracle = {
        "oracle_id": "oracle-canary",
        "node_id": "assert_canary",
        "phase": "main",
        "assertion_name": "workflow_assertion",
        "expression": "body.actual",
        "expected_value_digest": canonical_digest(2),
    }
    proposal = {
        "project_id": PROJECT,
        "proposal_id": str(uuid4()),
        "review_status": "accepted",
        "content_fingerprint": SHA,
        "review_mode": "ci_fixture",
        "reviewer_id": str(uuid4()),
    }
    scenario["provenance"] = {
        "batch_key": "batch-1",
        "scenario_id": "ST-ENG-002",
        "generation_mode": "deterministic_mcp",
        "api_source": source,
        "design_fingerprint": SHA,
        "compilation_fingerprint": SHA,
        "catalog_digest": SHA,
        "oracle_bindings": [oracle],
        "calls": [
            {
                "call_id": f"call-{index}",
                "batch_key": "batch-1",
                "scenario_id": "ST-ENG-002",
                "phase": "generation",
                "tool_name": tool,
                "transport": "stdio",
                "sdk_version": "2.2.0",
                "protocol_version": "2025-11-25",
                "request_digest": SHA,
                "result_digest": SHA,
                "catalog_digest": SHA,
                "completed_at": GENERATED,
                "success": True,
            }
            for index, tool in enumerate(
                [
                    "flowtest.generate_test_design",
                    "flowtest.propose_test_design",
                    "flowtest.propose_simple_flow",
                ]
            )
        ],
        "workflow_proposal": {**proposal, "route": "flow_spec", "materialized_resource_id": FLOW},
        "case_proposal": {
            **proposal,
            "route": "controlled_write",
            "item_id": str(uuid4()),
            "materialized_resource_id": CASE,
        },
        "workflow": {
            "project_id": PROJECT,
            "id": FLOW,
            "version_id": FLOW_VERSION,
            "version": 1,
            "fingerprint": SHA,
            "api_sources": [source],
            "assertions": [oracle],
        },
        "case": {
            "project_id": PROJECT,
            "id": CASE,
            "version": 1,
            "fingerprint": SHA,
            "workflow_id": FLOW,
            "workflow_version": 1,
            "environment_id": ENV,
        },
        "run": {
            "project_id": PROJECT,
            "run_id": str(uuid4()),
            "run_item_id": str(uuid4()),
            "target_id": CASE,
            "target_version": 1,
            "workflow_id": FLOW,
            "workflow_version": 1,
            "environment_id": ENV,
            "execution_id": EXECUTION,
            "attempts": 1,
            "status": "failed",
            "target_snapshot_digest": SHA,
        },
        "generated_at": GENERATED,
        "frozen_at": FROZEN,
    }

    scenario["provenance"] = copy.deepcopy(scenario["provenance"])


def test_real_typed_provenance_relationships_match() -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_provenance(manifest, evidence)
    assert verify(manifest, evidence).exit_code == 0


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("case_proposal", "materialized_resource_id"), str(uuid4())),
        (("workflow_proposal", "review_status"), "pending"),
        (("case", "workflow_version"), 2),
        (("workflow", "project_id"), str(uuid4())),
        (("api_source", "api_version"), 2),
        (("oracle_bindings", 0, "oracle_id"), "different-oracle"),
        (("calls", 0, "tool_name"), "flowtest.inspect_connection"),
        (("calls", 0, "batch_key"), "old-batch"),
        (("frozen_at",), COLLECTED),
        (("assisted",), True),
    ],
)
def test_generated_provenance_rejects_forged_or_partial_chain(
    path: tuple[str | int, ...], value: Any
) -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_provenance(manifest, evidence)
    cursor = evidence["scenarios"][0]["provenance"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    assert verify(manifest, evidence).exit_code != 0


def test_host_evidence_cannot_be_filled_by_deterministic_result() -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_provenance(manifest, evidence)
    evidence["scenarios"][0]["provenance"]["generation_mode"] = "host_llm_mcp"
    manifest["generation_mode"] = "host_llm_mcp"
    assert verify(manifest, evidence).exit_code != 0


def add_frozen_multi_source(manifest: dict[str, Any], evidence: dict[str, Any]) -> None:
    add_provenance(manifest, evidence)
    scenario = evidence["scenarios"][0]
    provenance = scenario["provenance"]
    sources = [
        provenance["api_source"],
        {**provenance["api_source"], "api_definition_id": str(uuid4())},
    ]
    designs = [
        {
            "api_source": source,
            "operation_ref": f"op-{index}",
            "scenario_id": "happy",
            "design_fingerprint": SHA,
        }
        for index, source in enumerate(sources)
    ]
    provenance.update(design_sources=designs, combined_design_fingerprint=SHA)
    provenance["workflow"]["api_sources"] = copy.deepcopy(sources)
    scenario["execution"]["api_sources"] = copy.deepcopy(sources)
    scenario["attempts"][0]["api_sources"] = copy.deepcopy(sources)
    manifest["scenarios"][0].update(
        expected_api_sources=copy.deepcopy(sources), expected_design_sources=copy.deepcopy(designs)
    )


def test_multiple_frozen_api_designs_require_exact_full_set() -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_frozen_multi_source(manifest, evidence)
    assert verify(manifest, evidence).exit_code == 0
    evidence["scenarios"][0]["provenance"]["design_sources"][1]["design_fingerprint"] = "b" * 64
    assert verify(manifest, evidence).exit_code != 0


def test_deleting_multi_source_chain_and_relabeling_single_api_cannot_pass() -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_frozen_multi_source(manifest, evidence)
    scenario = evidence["scenarios"][0]
    scenario["provenance"]["design_sources"] = []
    scenario["provenance"]["workflow"]["api_sources"] = [scenario["provenance"]["api_source"]]
    scenario["execution"]["api_sources"] = [scenario["provenance"]["api_source"]]
    scenario["attempts"][0]["api_sources"] = [scenario["provenance"]["api_source"]]
    assert verify(manifest, evidence).exit_code != 0


def test_coordinated_oracle_mapping_replacement_cannot_override_frozen_manifest() -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_provenance(manifest, evidence)
    provenance = evidence["scenarios"][0]["provenance"]
    manifest["scenarios"][0]["expected_oracle_bindings"] = copy.deepcopy(
        provenance["oracle_bindings"]
    )
    assert verify(manifest, evidence).exit_code == 0
    provenance["oracle_bindings"][0]["expression"] = "body.other"
    provenance["workflow"]["assertions"][0]["expression"] = "body.other"
    assert verify(manifest, evidence).exit_code != 0


@pytest.mark.parametrize(
    "change", ["missing_coverage", "duplicate", "request", "result", "catalog"]
)
def test_complete_frozen_mcp_receipt_sequence_cannot_lose_optional_tool_receipts(
    change: str,
) -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_provenance(manifest, evidence)
    calls = evidence["scenarios"][0]["provenance"]["calls"]
    calls.append(
        {
            **copy.deepcopy(calls[0]),
            "call_id": "coverage-call",
            "tool_name": "flowtest.analyze_test_coverage",
        }
    )
    manifest["scenarios"][0]["expected_mcp_calls"] = copy.deepcopy(calls)
    assert verify(manifest, evidence).exit_code == 0
    if change == "missing_coverage":
        calls.pop()
    elif change == "duplicate":
        calls.append(copy.deepcopy(calls[-1]))
    else:
        calls[-1][change + "_digest"] = "b" * 64
    assert verify(manifest, evidence).exit_code != 0


def test_suite_deletion_and_coordinated_target_digest_replacement_cannot_pass() -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    add_provenance(manifest, evidence)
    provenance = evidence["scenarios"][0]["provenance"]
    suite = {
        "project_id": PROJECT,
        "id": str(uuid4()),
        "version": 1,
        "fingerprint": SHA,
        "case_versions": [{"case_id": CASE, "version": 1}],
    }
    manifest["scenarios"][0].update(
        require_suite_provenance=True, expected_suite=suite, expected_target_snapshot_digest=SHA
    )
    assert verify(manifest, evidence).exit_code != 0
    provenance["suite"] = suite
    provenance["run"].update(
        source_suite={"id": suite["id"], "version": 1}, expected_target_snapshot_digest=SHA
    )
    assert verify(manifest, evidence).exit_code == 0
    provenance["run"].update(
        expected_target_snapshot_digest="b" * 64, target_snapshot_digest="b" * 64
    )
    assert verify(manifest, evidence).exit_code != 0


@pytest.mark.parametrize("mutation", ["none", "project", "present", "old", "incomplete"])
def test_resource_postcondition_uses_independent_complete_scoped_after_run_query(
    mutation: str,
) -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    expected = manifest["scenarios"][0]
    expected["required_evidence"].append("postcondition")
    expected["expected"]["resource_absence"] = {
        "project_id": PROJECT,
        "absent_names": ["batch-1-created", "batch-1-updated"],
    }
    actual = {
        "project_id": PROJECT,
        "returned_names": ["base-environment"],
        "observed_at": COLLECTED,
        "complete": True,
    }
    evidence["scenarios"][0]["resource_absence"] = actual
    assert verify(manifest, evidence).exit_code == 0
    if mutation == "none":
        evidence["scenarios"][0].update(resource_absence=None, postcondition_matched=True)
    elif mutation == "project":
        actual["project_id"] = str(uuid4())
    elif mutation == "present":
        actual["returned_names"].append("batch-1-updated")
    elif mutation == "old":
        actual["observed_at"] = GENERATED
    else:
        actual["complete"] = False
    assert verify(manifest, evidence).exit_code != 0


def test_skipped_assertion_node_with_fabricated_outputs_cannot_count_as_evidence() -> None:
    manifest, evidence = manifest_payload(), evidence_payload()
    evidence["scenarios"][0]["execution"]["nodes"][0]["status"] = "skipped"
    evidence["scenarios"][0]["attempts"][0]["nodes"][0]["status"] = "skipped"
    assert verify(manifest, evidence).exit_code != 0


def response_field_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, evidence = manifest_payload(), evidence_payload()
    api = {
        "project_id": PROJECT,
        "api_definition_id": API,
        "api_version": 1,
        "contract_fingerprint": SHA,
    }
    golden = {
        "api_source": api,
        "node_id": "patch_environment",
        "field": "name",
        "expected": "batch-1-updated",
    }
    manifest["scenarios"][0]["required_evidence"].append("response_fields")
    manifest["scenarios"][0]["expected"]["response_fields"] = [golden]
    scenario = evidence["scenarios"][0]
    node = {
        "node_id": "patch_environment",
        "node_type": "api",
        "phase": "main",
        "status": "passed",
        "attempts": 1,
        "assertions": [],
    }
    scenario["execution"]["nodes"].append(copy.deepcopy(node))
    scenario["attempts"][0]["nodes"].append(copy.deepcopy(node))
    scenario["response_fields"] = [
        {
            "batch_key": "batch-1",
            "scenario_id": "ST-ENG-002",
            "project_id": PROJECT,
            "execution_id": EXECUTION,
            "workflow_version_id": FLOW_VERSION,
            "api_source": api,
            "node_id": "patch_environment",
            "field": "name",
            "actual": "batch-1-updated",
            "observed_at": COLLECTED,
        }
    ]
    return manifest, evidence


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "ignored_patch",
        "batch",
        "execution",
        "api_version",
        "node",
        "time",
        "skipped",
    ],
)
def test_response_field_requires_exact_actual_batch_execution_api_node_and_value(
    mutation: str,
) -> None:
    manifest, evidence = response_field_fixture()
    assert verify(manifest, evidence).exit_code == 0
    scenario = evidence["scenarios"][0]
    field = scenario["response_fields"][0]
    if mutation == "missing":
        scenario["response_fields"] = []
    elif mutation == "duplicate":
        scenario["response_fields"].append(copy.deepcopy(field))
    elif mutation == "ignored_patch":
        field["actual"] = "batch-1-created"
    elif mutation == "batch":
        field["batch_key"] = "old-batch"
    elif mutation == "execution":
        field["execution_id"] = str(uuid4())
    elif mutation == "api_version":
        field["api_source"] = {**field["api_source"], "api_version": 2}
    elif mutation == "node":
        field["node_id"] = "create_environment"
    elif mutation == "time":
        field["observed_at"] = GENERATED
    else:
        scenario["execution"]["nodes"][-1]["status"] = "skipped"
        scenario["attempts"][0]["nodes"][-1]["status"] = "skipped"
    assert verify(manifest, evidence).exit_code != 0


@pytest.mark.parametrize(
    "field,value", [("field", "access_token"), ("actual", "x" * 201), ("actual", 1)]
)
def test_response_field_export_contract_allows_only_bounded_name(field: str, value: Any) -> None:
    _, evidence = response_field_fixture()
    evidence["scenarios"][0]["response_fields"][0][field] = value
    with pytest.raises(ValidationError):
        BatchEvidence.model_validate(evidence)


def test_verification_junit_does_not_modify_raw_junit(tmp_path: Path) -> None:
    raw = tmp_path / "execution.junit.xml"
    raw.write_text('<testsuite tests="1" failures="1"/>', encoding="utf-8")
    write_report(verify(manifest_payload(), evidence_payload()), tmp_path)
    assert 'failures="1"' in raw.read_text(encoding="utf-8")
    result = ElementTree.parse(tmp_path / "verification.junit.xml").getroot()
    assert result.attrib["tests"] == "1"
    assert result.attrib["failures"] == "0"


def test_cli_nonzero_for_incomplete_and_invalid_input_replaces_old_pass(tmp_path: Path) -> None:
    manifest_path, evidence_path = tmp_path / "manifest.json", tmp_path / "evidence.json"
    manifest = manifest_payload()
    wall_time = datetime.now(UTC)
    times = {
        START: wall_time - timedelta(seconds=10),
        GENERATED: wall_time - timedelta(seconds=9),
        FROZEN: wall_time - timedelta(seconds=8),
        EXECUTED: wall_time - timedelta(seconds=7),
        COLLECTED: wall_time - timedelta(seconds=5),
        DEADLINE: wall_time + timedelta(minutes=5),
    }
    manifest_json, evidence_json = json.dumps(manifest), json.dumps(evidence_payload())
    for old, new in times.items():
        manifest_json = manifest_json.replace(old, new.isoformat())
        evidence_json = evidence_json.replace(old, new.isoformat())
    manifest_path.write_text(manifest_json, encoding="utf-8")
    evidence_path.write_text(evidence_json, encoding="utf-8")
    argv = [
        "--manifest",
        str(manifest_path),
        "--evidence",
        str(evidence_path),
        "--output-dir",
        str(tmp_path),
    ]
    assert main(argv) == 0
    evidence_path.write_text("{}", encoding="utf-8")
    assert main(argv) == 2
    result = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert result["batch_verdict"] == "blocked"
    assert result["exit_code"] == 2
    assert (
        ElementTree.parse(tmp_path / "verification.junit.xml").getroot().attrib["failures"] == "1"
    )


def test_independent_observer_modules_do_not_import_candidate_product() -> None:
    import ast

    for name in ("contracts.py", "verify.py", "verify_generation_provenance.py"):
        tree = ast.parse((ROOT / "scripts/selftest" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.")


def test_expected_native_cleanup_failure_keeps_external_cleanup_mandatory() -> None:
    manifest = manifest_payload()
    manifest["scenarios"][0]["expected"].update(main_status="failed", cleanup_status="failed")
    evidence = evidence_payload()
    observation = evidence["scenarios"][0]
    observation["execution"]["cleanup_status"] = "failed"
    observation["attempts"][0]["cleanup_status"] = "failed"
    assert verify(manifest, evidence).exit_code == 0
    manifest["scenarios"][0]["expected"].pop("cleanup_status")
    assert verify(manifest, evidence).exit_code != 0
    manifest["scenarios"][0]["expected"]["cleanup_status"] = "failed"
    observation["cleanup_status"] = "failed"
    assert verify(manifest, evidence).exit_code != 0


@pytest.mark.parametrize("tamper", ["missing", "wrong_error", "wrong_phase", "truncated"])
def test_nested_try_failure_has_exact_frozen_nodes_and_cannot_be_omitted(tamper: str) -> None:
    manifest = manifest_payload()
    nested = {
        "node_id": "__nested_request__:" + "a" * 64,
        "phase": "main",
        "status": "failed",
        "error_code": "WORKFLOW_ASSERTION_FAILED",
        "attempts": 1,
    }
    manifest["scenarios"][0]["expected"]["nested_nodes"] = [nested]
    evidence = evidence_payload()
    execution = evidence["scenarios"][0]["execution"]
    execution["nested_nodes"] = [{**nested, "node_type": "assert", "assertions": []}]
    evidence["scenarios"][0]["attempts"][0] = copy.deepcopy(execution)
    assert verify(manifest, evidence).exit_code == 0
    if tamper == "missing":
        execution["nested_nodes"] = []
    elif tamper == "truncated":
        execution["nested_nodes_complete"] = False
    elif tamper == "wrong_error":
        execution["nested_nodes"][0]["error_code"] = "NODE_TIMEOUT"
    else:
        execution["nested_nodes"][0]["phase"] = "cleanup"
    evidence["scenarios"][0]["attempts"][0] = copy.deepcopy(execution)
    report = verify(manifest, evidence)
    assert report.exit_code != 0
    assert any(finding.code.startswith("NESTED_") for finding in report.scenarios[0].findings)


@pytest.mark.parametrize("tamper", ["missing", "trace_header", "code", "node_missing"])
def test_normal_negative_envelope_needs_exact_code_trace_and_actual_api_node(tamper: str) -> None:
    manifest = manifest_payload()
    error = {
        "node_id": "negative_request",
        "status_code": 401,
        "error_code": "AUTHENTICATION_REQUIRED",
        "trace_id": "batch-1-error-401",
    }
    manifest["scenarios"][0]["expected"]["error_envelopes"] = [error]
    evidence = evidence_payload()
    observation = evidence["scenarios"][0]
    execution = observation["execution"]
    execution["nodes"].append(
        {
            "node_id": "negative_request",
            "node_type": "api",
            "phase": "main",
            "status": "passed",
            "attempts": 1,
            "error_code": None,
            "assertions": [],
        }
    )
    observation["attempts"][0] = copy.deepcopy(execution)
    observation["error_envelopes"] = [
        {
            **error,
            "project_id": PROJECT,
            "execution_id": EXECUTION,
            "response_trace_id": error["trace_id"],
        }
    ]
    assert verify(manifest, evidence).exit_code == 0
    if tamper == "missing":
        observation["error_envelopes"] = []
    elif tamper == "trace_header":
        observation["error_envelopes"][0]["response_trace_id"] = "old-batch-error-401"
    elif tamper == "code":
        observation["error_envelopes"][0]["error_code"] = "INVALID_ACCESS_TOKEN"
    else:
        execution["nodes"].pop()
        observation["attempts"][0] = copy.deepcopy(execution)
    report = verify(manifest, evidence)
    assert report.exit_code != 0
    assert any(
        finding.code.startswith("ERROR_ENVELOPE_") for finding in report.scenarios[0].findings
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "pending",
        "no_receipt",
        "wrong_volume",
        "wrong_nonce",
        "old_created",
        "foreign_org",
        "resources_still_present",
    ],
)
def test_project_disposal_needs_frozen_ownership_and_real_absence_receipt(tamper: str) -> None:
    manifest = manifest_payload()
    identity = {
        "project_name": "flowtest-selftest-aaaaaaaaaaaa",
        "target_container_id": "target-container",
        "target_volume": "owned-target-data",
        "target_image": "target-1",
    }
    golden = {
        "organization_id": PROJECT,
        "created_by_id": API,
        "name": "batch-1-project-updated",
        "disposal_binding_nonce": "binding-nonce-1",
        "disposable_target": identity,
    }
    manifest["scenarios"][0]["expected"]["project_state"] = golden
    evidence = evidence_payload()
    state = {
        **golden,
        "project_id": str(uuid4()),
        "created_at": EXECUTED,
        "observed_at": COLLECTED,
        "disposal_status": "completed",
        "disposal_receipt": {
            **identity,
            "binding_nonce": "binding-nonce-1",
            "removed_at": COLLECTED,
            "containers_absent": True,
            "volumes_absent": True,
            "networks_absent": True,
        },
    }
    evidence["scenarios"][0]["project_state"] = state
    assert verify(manifest, evidence).exit_code == 0
    if tamper == "pending":
        state["disposal_status"] = "pending"
    elif tamper == "no_receipt":
        state["disposal_receipt"] = None
    elif tamper == "wrong_volume":
        state["disposal_receipt"]["target_volume"] = "someone-elses-volume"
    elif tamper == "wrong_nonce":
        state["disposal_receipt"]["binding_nonce"] = "old-binding"
    elif tamper == "old_created":
        state["created_at"] = "2025-01-01T00:00:00+00:00"
    elif tamper == "foreign_org":
        state["organization_id"] = str(uuid4())
    else:
        state["disposal_receipt"]["volumes_absent"] = False
    assert verify(manifest, evidence).exit_code != 0
