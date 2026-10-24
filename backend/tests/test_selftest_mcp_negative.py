"""Real SDK 2.2 receipts are inputs; only pre-frozen pack literals supply expected behavior."""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.io import HarnessError, read_json
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_negative_contracts import ProtocolEvidence, ProtocolManifest
from scripts.selftest.mcp_negative_verify import (
    ProtocolReport,
    verify_protocol,
    write_reports,
)

FIXTURES = Path(__file__).parent / "fixtures/mcp_negative_actual_valid_write"
PACK = Path(__file__).resolve().parents[2] / "selftest/packs/mcp-negative-v1/pack.json"


@pytest.fixture
def original() -> tuple[ProtocolManifest, ProtocolEvidence]:
    return (
        ProtocolManifest.model_validate(read_json(FIXTURES / "manifest.json")),
        ProtocolEvidence.model_validate(read_json(FIXTURES / "evidence.json")),
    )


def report(manifest: ProtocolManifest, evidence: ProtocolEvidence) -> ProtocolReport:
    # Unit-only time injection isolates expiry behavior from the captured wire.
    return verify_protocol(manifest, evidence, now=manifest.created_at, pack_path=PACK)


def findings(value: ProtocolReport) -> set[str]:
    return {item.code for item in value.findings} | {
        item.code for row in value.scenarios for item in row.findings
    }


@pytest.mark.parametrize("mutation", ["nonce", "expiry", "cleanup"])
def test_global_verification_failure_is_a_failed_junit_case(
    original: tuple[ProtocolManifest, ProtocolEvidence], tmp_path: Path, mutation: str
) -> None:
    manifest, evidence = original
    changed = evidence
    now = manifest.created_at
    if mutation == "nonce":
        changed = evidence.model_copy(update={"nonce": "different-nonce"})
    elif mutation == "expiry":
        now = manifest.expires_at + timedelta(seconds=1)
    else:
        changed = evidence.model_copy(update={"cleanup_complete": False})
    checked = verify_protocol(manifest, changed, now=now, pack_path=PACK)
    assert checked.exit_code != 0 and checked.findings
    assert all(row.verification_status == "matched" for row in checked.scenarios)
    write_reports(checked, changed, tmp_path)
    root = parse(tmp_path / "verification.junit.xml").getroot()
    assert int(root.attrib["tests"]) == len(checked.scenarios) + 1
    assert root.find("./testcase[@name='batch-global']/failure") is not None


def test_frozen_34_actual_sdk_stdio_http_raw_errors_match_independent_expected(
    original: tuple[ProtocolManifest, ProtocolEvidence], tmp_path: Path
) -> None:
    manifest, evidence = original
    checked = report(manifest, evidence)
    assert checked.exit_code == 0 and len(checked.scenarios) == 34
    assert len(manifest.scenarios) == 34 and evidence.protocol_attempts == 28
    assert evidence.rejected_http_requests == evidence.rejected_tool_calls == 0
    assert evidence.http_requests <= 500
    write_reports(checked, evidence, tmp_path)
    assert "failure" in (tmp_path / "execution.junit.xml").read_text()
    assert "failure" not in (tmp_path / "verification.junit.xml").read_text()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("business_code", None, "PROTOCOL_RAW_RESULT_MISMATCH"),
        ("trace_present", False, "PROTOCOL_TRACE_MISSING"),
        ("is_error", True, "PROTOCOL_RAW_RESULT_MISMATCH"),
    ],
)
def test_http200_iserror_false_cannot_hide_business_error_or_trace(
    original: tuple[ProtocolManifest, ProtocolEvidence], field: str, value: object, code: str
) -> None:
    manifest, evidence = original
    row = next(
        item
        for item in evidence.scenarios
        if item.scenario_id.endswith("business_error_under_http200-streamable-http")
    )
    changed = row.model_copy(
        update={"results": (row.results[0].model_copy(update={field: value}),)}
    )
    changed_evidence = evidence.model_copy(
        update={"scenarios": tuple(changed if item == row else item for item in evidence.scenarios)}
    )
    assert code in findings(report(manifest, changed_evidence))


@pytest.mark.parametrize(
    ("mutation", "code", "exit_code"),
    [
        ("missing_scenario", "PROTOCOL_REQUIRED_SCENARIO_MISSING", 2),
        ("duplicate_scenario", "PROTOCOL_SCENARIO_SET_MISMATCH", 1),
        ("missing_wire", "PROTOCOL_WIRE_RESPONSE_MISSING", 2),
        ("duplicate_wire", "PROTOCOL_RPC_ID_DUPLICATE", 1),
        ("rpc_string", "PROTOCOL_REQUEST_BINDING_MISMATCH", 1),
        ("missing_principal", "PROTOCOL_PRINCIPAL_RESULT_MISSING", 2),
        ("principal_swap", "PROTOCOL_PRINCIPAL_ISOLATION_MISMATCH", 1),
        ("nonce", "PROTOCOL_BATCH_IDENTITY_MISMATCH", 1),
        ("cleanup", "PROTOCOL_FIXTURE_CLEANUP_INCOMPLETE", 2),
        ("budget", "PROTOCOL_HTTP_BUDGET_EXCEEDED", 1),
        ("tool_budget", "PROTOCOL_TOOL_BUDGET_EXCEEDED", 1),
    ],
)
def test_independent_verifier_rejects_missing_reused_swapped_or_unfinished_receipts(
    original: tuple[ProtocolManifest, ProtocolEvidence], mutation: str, code: str, exit_code: int
) -> None:
    manifest, evidence = original
    rows = list(evidence.scenarios)
    first, group = rows[0], rows[-1]
    if mutation == "missing_scenario":
        rows.pop()
    elif mutation == "duplicate_scenario":
        rows.append(first)
    elif mutation == "missing_wire":
        rows[0] = first.model_copy(update={"responses": first.responses[:-1]})
    elif mutation == "duplicate_wire":
        rows[0] = first.model_copy(update={"responses": (*first.responses, first.responses[0])})
    elif mutation == "rpc_string":
        rows[0] = first.model_copy(
            update={
                "results": (
                    first.results[0].model_copy(update={"rpc_id": str(first.results[0].rpc_id)}),
                )
            }
        )
    elif mutation == "missing_principal":
        rows[-1] = group.model_copy(update={"results": group.results[:-1]})
    elif mutation == "principal_swap":
        rows[-1] = group.model_copy(
            update={
                "results": (
                    group.results[0],
                    group.results[1].model_copy(
                        update={"project_ids": (manifest.fixture.project_a,)}
                    ),
                    group.results[2],
                )
            }
        )
    changed = evidence.model_copy(update={"scenarios": tuple(rows)})
    updates = {
        "nonce": {"nonce": "stale"},
        "cleanup": {"cleanup_complete": False},
        "budget": {"rejected_http_requests": 1},
        "tool_budget": {"rejected_tool_calls": 1},
    }
    changed = changed.model_copy(update=updates.get(mutation, {}))
    checked = report(manifest, changed)
    assert checked.exit_code == exit_code
    assert code in findings(checked)


def test_mutating_manifest_and_evidence_together_cannot_shrink_frozen_pack(
    original: tuple[ProtocolManifest, ProtocolEvidence],
) -> None:
    manifest, evidence = original
    manifest = manifest.model_copy(update={"scenarios": manifest.scenarios[:-1]})
    evidence = evidence.model_copy(update={"scenarios": evidence.scenarios[:-1]})
    assert "PROTOCOL_FROZEN_DENOMINATOR_MISMATCH" in findings(report(manifest, evidence))


def test_manifest_expected_tool_argument_and_principal_binding_are_not_mutable_goldens(
    original: tuple[ProtocolManifest, ProtocolEvidence],
) -> None:
    manifest, evidence = original
    first = manifest.scenarios[0]
    changed = first.model_copy(
        update={"expected": first.expected.model_copy(update={"arguments_digest": "0" * 64})}
    )
    manifest = manifest.model_copy(update={"scenarios": (changed, *manifest.scenarios[1:])})
    assert "PROTOCOL_GOLDEN_MUTATED" in findings(report(manifest, evidence))


def test_manifest_deadline_and_duplicate_scope_fail_closed(
    original: tuple[ProtocolManifest, ProtocolEvidence],
) -> None:
    manifest, _ = original
    for updates in (
        {"expires_at": manifest.created_at + timedelta(seconds=601)},
        {"created_at": manifest.created_at.replace(tzinfo=None)},
        {"scenarios": (manifest.scenarios[0], manifest.scenarios[0])},
    ):
        with pytest.raises(ValidationError):
            ProtocolManifest.model_validate(manifest.model_dump() | updates)


def test_http_budget_499_concurrent_admission_identity_and_reopen_do_not_reset(
    tmp_path: Path,
) -> None:
    import time

    deadline = time.time() + 600
    budget = ProtocolHttpBudget(tmp_path / "budget.sqlite3", "batch-nonce", deadline)
    for _ in range(499):
        assert budget.reserve()
    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = list(pool.map(lambda _: budget.reserve(), range(2)))
    assert sum(admitted) == 1 and budget.counts() == (500, 1)
    reopened = ProtocolHttpBudget(budget.path, "batch-nonce", deadline)
    assert not reopened.reserve() and reopened.counts() == (500, 2)
    with pytest.raises(HarnessError, match="IDENTITY_CHANGED"):
        ProtocolHttpBudget(budget.path, "different", deadline)
    with pytest.raises(HarnessError, match="IDENTITY_CHANGED"):
        ProtocolHttpBudget(budget.path, "batch-nonce", deadline + 1)


def test_tool_attempt_budget_includes_dispatch_failure_reservation(tmp_path: Path) -> None:
    import time

    budget = ProtocolHttpBudget(tmp_path / "tools.sqlite3", "nonce", time.time() + 600)
    for _ in range(100):
        assert budget.reserve_tool()
    assert not budget.reserve_tool()
    assert budget.tool_counts() == (100, 1)


def test_denied_write_uses_a_valid_controlled_proposal_contract(
    original: tuple[ProtocolManifest, ProtocolEvidence],
) -> None:
    from scripts.selftest.mcp_negative_verify import _golden_arguments

    from app.schemas.test_design import MCPControlledWriteCreate

    manifest, _ = original
    scenario = next(item for item in manifest.scenarios if item.operation == "propose_denied")
    tool, arguments = _golden_arguments(manifest, scenario)
    payload = MCPControlledWriteCreate.model_validate(arguments)
    assert tool == "flowtest.propose_test_design"
    assert payload.design.oracles[0].kind == "status"
    assert payload.design.oracles[0].expression == "$.status"
    assert payload.design.oracles[0].expected == 200
    assert not payload.dry_run


def test_prior_actual_receipts_are_retained_as_historical_inputs() -> None:
    old = Path(__file__).parent / "fixtures/mcp_negative_actual"
    assert len(ProtocolManifest.model_validate(read_json(old / "manifest.json")).scenarios) == 34
    assert len(ProtocolEvidence.model_validate(read_json(old / "evidence.json")).scenarios) == 34


@pytest.mark.parametrize("section", ["assets", "before_assets"])
def test_missing_observed_asset_counter_never_defaults_to_zero(
    original: tuple[ProtocolManifest, ProtocolEvidence], section: str
) -> None:
    manifest, evidence = original
    raw = evidence.model_dump(mode="json")
    del raw["scenarios"][0][section]["executions"]
    checked = report(manifest, ProtocolEvidence.model_validate(raw))
    assert checked.exit_code == 2
    assert "PROTOCOL_ASSET_COUNTER_MISSING" in findings(checked)


@pytest.mark.parametrize("field", ["rejected_http_requests", "rejected_tool_calls"])
def test_missing_observed_rejection_counter_is_incomplete(
    original: tuple[ProtocolManifest, ProtocolEvidence], field: str
) -> None:
    manifest, evidence = original
    raw = evidence.model_dump(mode="json")
    del raw[field]
    checked = report(manifest, ProtocolEvidence.model_validate(raw))
    assert checked.exit_code == 2
    assert "PROTOCOL_REJECTION_COUNTER_MISSING" in findings(checked)


def test_reported_tool_attempt_count_must_equal_actual_receipt_set(
    original: tuple[ProtocolManifest, ProtocolEvidence],
) -> None:
    manifest, evidence = original
    checked = report(manifest, evidence.model_copy(update={"protocol_attempts": 0}))
    assert checked.exit_code == 1
    assert "PROTOCOL_TOOL_ATTEMPT_COUNT_MISMATCH" in findings(checked)
    incomplete = report(manifest, evidence.model_copy(update={"protocol_attempts": 29}))
    assert incomplete.exit_code == 2
    assert "PROTOCOL_TOOL_ATTEMPT_RECEIPTS_MISSING" in findings(incomplete)


def test_rpc_journal_cannot_be_reused_for_two_distinct_principal_scenarios(
    original: tuple[ProtocolManifest, ProtocolEvidence],
) -> None:
    manifest, evidence = original
    source, target = evidence.scenarios[-2:]
    forged = target.model_copy(
        update={
            "requests": source.requests,
            "responses": source.responses,
            "results": source.results,
            "started_at": source.started_at,
            "completed_at": source.completed_at,
        }
    )
    checked = report(
        manifest, evidence.model_copy(update={"scenarios": (*evidence.scenarios[:-1], forged)})
    )
    assert checked.exit_code == 1
    assert "PROTOCOL_RPC_RECEIPT_REUSED" in findings(checked)


@pytest.mark.parametrize("field", ["business_code", "diagnostic_code"])
def test_positive_tool_result_requires_explicit_no_business_error_observation(
    original: tuple[ProtocolManifest, ProtocolEvidence], field: str
) -> None:
    manifest, evidence = original
    raw = evidence.model_dump(mode="json")
    row = next(item for item in raw["scenarios"] if "inspect_readonly-stdio" in item["scenario_id"])
    del row["results"][0][field]
    checked = report(manifest, ProtocolEvidence.model_validate(raw))
    assert checked.exit_code == 2
    assert "PROTOCOL_TOOL_RESULT_FIELD_MISSING" in findings(checked)
