"""Frozen synthetic native SDK/ASGI evidence, independently tested against tampering."""

import copy
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contract_delta_budget import DeltaBudget  # noqa: E402
from scripts.selftest.contracts import TargetDisposalReceipt, canonical_digest  # noqa: E402
from scripts.selftest.io import HarnessError, read_json  # noqa: E402
from scripts.selftest.native_control import NativeControlProtocol  # noqa: E402
from scripts.selftest.native_control_contracts import (  # noqa: E402
    NativeControlEvidence,
    NativeControlManifest,
)
from scripts.selftest.native_control_verify import load_pack, verify, write_reports  # noqa: E402


@pytest.fixture
def captured():
    base = ROOT / "backend/tests/fixtures/native_control_actual"
    frozen = NativeControlManifest.model_validate(read_json(base / "manifest.json"))
    evidence = NativeControlEvidence.model_validate(read_json(base / "evidence.json"))
    # Unit-only disposal assertion; deployment CLI must independently prove exact owned removal.
    disposal = TargetDisposalReceipt(
        **frozen.required_disposal.model_dump(),
        removed_at=evidence.collected_at,
        containers_absent=True,
        volumes_absent=True,
        networks_absent=True,
    )
    return (
        frozen,
        evidence.model_copy(update={"disposal": disposal}),
        load_pack(ROOT / "selftest/packs/native-control-mcp-v1/pack.json"),
    )


def codes(report):
    return set(report.findings) | {code for row in report.scenarios for code in row.findings}


def test_frozen_native_run_and_two_export_refusals_have_fixed_denominator(captured, tmp_path):
    frozen, evidence, pack = captured
    report = verify(frozen, pack, evidence, now=evidence.collected_at)
    assert report.exit_code == 0, report.model_dump_json(indent=2)
    assert all(row.status == "matched" for row in report.scenarios)
    assert len(report.scenarios) == 3
    write_reports(report, evidence, tmp_path)
    assert 'tests="1"' in (tmp_path / "execution.junit.xml").read_text()
    assert 'tests="3"' in (tmp_path / "verification.junit.xml").read_text()
    assert "<failure" not in (tmp_path / "verification.junit.xml").read_text()


# Each mutation changes actual evidence, never its frozen expected definition or outcome.
MUTATIONS = [
    ("manifest_digest", None, "f" * 64),
    ("calls.0.request_digest", None, "a" * 64),
    ("calls.1.result_digest", None, "a" * 64),
    ("calls.1.phase", None, "other"),
    ("calls.1.batch_key", None, "other"),
    ("calls.1.success", None, False),
    ("frozen.pending.actor_type", None, "user"),
    ("frozen.pending.created_by_id", None, str(uuid4())),
    ("frozen.accepted.items.0.reviewed_by_id", None, str(uuid4())),
    ("frozen.accepted.items.0.materialized_resource_type", None, "test_case"),
    ("frozen.accepted.items.0.proposed_content.description", None, "rewritten"),
    ("frozen.draft.current_version", None, 1),
    ("frozen.draft.draft_definition.regions", None, []),
    ("frozen.published.definition.schema_version", None, "3.0"),
    ("frozen.case.version.definition.workflow_version", None, 2),
    ("frozen.suite.definition.items", None, []),
    ("frozen.plan.items.0.max_retries", None, 1),
    ("frozen.selection.cases.0.target_snapshot_digest", None, "a" * 64),
    ("plan_run.test_plan_id", None, str(uuid4())),
    ("plan_run.items.0.target_version", None, 2),
    ("plan_run.items.0.attempts", None, 2),
    ("raw_execution.source_case_id", None, str(uuid4())),
    ("raw_execution.bindings_complete", None, False),
    ("raw_execution.truncated", None, True),
    ("raw_execution.node_total", None, 100),
    ("raw_execution.nodes.0.assertions_complete", None, False),
    ("execution.run_purpose", None, "preview"),
    ("execution.workflow_version_id", None, str(uuid4())),
    ("execution.nodes.0.node_type", None, "api"),
    ("execution.nested_nodes", None, []),
    ("control_page.truncated", None, True),
    ("control_page.items.1.ordinal", None, 2),
    ("control_details.0.payload.branch_id", None, "second"),
    ("control_details.0.payload.status", None, "failed"),
    ("control_details.1.payload.nodes.0.instance_id", None, "other"),
    ("exports.0.status", None, 200),
    ("exports.1.error_code", None, "WRONG"),
    ("exports.1.path", None, "/unrelated"),
    ("exports.1.after_definition_digest", None, "a" * 64),
    ("cleanup.status", None, "needs_review"),
    ("disposal.target_container_id", None, "foreign"),
    ("rejected_requests", None, 1),
    ("rejected_tool_calls", None, 1),
    ("admitted_tool_calls", None, 3),
]


@pytest.mark.parametrize(("path", "unused", "value"), MUTATIONS, ids=[row[0] for row in MUTATIONS])
def test_native_green_cannot_hide_mutated_source_control_export_or_budget(
    captured, path, unused, value
):
    frozen, evidence, pack = captured
    payload = evidence.model_dump(mode="json")
    parts = path.split(".")
    target = payload
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    key = int(parts[-1]) if isinstance(target, list) else parts[-1]
    target[key] = value
    changed = NativeControlEvidence.model_validate(payload)
    report = verify(frozen, pack, changed, now=evidence.collected_at)
    assert report.exit_code != 0
    assert report.verdict != "passed"
    assert len(report.scenarios) == 3


@pytest.mark.parametrize("field", ["frozen", "execution", "raw_execution", "control_page"])
def test_missing_native_evidence_never_reduces_denominator(captured, field):
    frozen, evidence, pack = captured
    changed = evidence.model_copy(update={field: None})
    report = verify(frozen, pack, changed, now=evidence.collected_at)
    assert report.exit_code != 0
    assert len(report.scenarios) == 3


def test_unknown_mutation_and_cleanup_never_become_raw_failure_matched(captured):
    frozen, evidence, pack = captured
    changed = evidence.model_copy(
        update={"failure_code": "MUTATION_RESULT_UNKNOWN", "cleanup": None}
    )
    report = verify(frozen, pack, changed, now=evidence.collected_at)
    assert report.verdict == "blocked" and report.exit_code == 2
    assert {"NATIVE_CONTROL_HARNESS_FAILED", "NATIVE_CONTROL_CLEANUP_INCOMPLETE"} <= codes(report)


def test_expired_or_changed_pack_cannot_reuse_green(captured):
    frozen, evidence, pack = captured
    assert (
        verify(frozen, pack, evidence, now=frozen.expires_at + timedelta(microseconds=1)).exit_code
        == 2
    )
    changed = copy.deepcopy(pack)
    changed.definition["regions"][0]["nodes"][0]["config"]["seconds"] = 1
    assert "NATIVE_CONTROL_FROZEN_PACK_CHANGED" in codes(
        verify(frozen, changed, evidence, now=evidence.collected_at)
    )


def test_shared_admission_stops_before_501st_request(captured, tmp_path):
    frozen, _, _ = captured
    budget = DeltaBudget(tmp_path, frozen.expires_at + timedelta(days=1000))
    budget.admit(500)
    with pytest.raises(HarnessError, match="ADMISSION_BUDGET_EXCEEDED"):
        budget.admit()
    assert budget.requests == 500 and budget.rejected_requests == 1


@pytest.mark.asyncio
async def test_native_tool_allowlist_does_not_dispatch_unapproved_tools(captured, tmp_path):
    from scripts.selftest.mcp_protocol_runner import ProtocolClient

    frozen, _, _ = captured

    class Session:
        calls = 0

        async def call_tool(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("must not dispatch")

    session = Session()
    client = ProtocolClient(session, "stdio", frozen.batch_key, tmp_path)
    client.catalog_digest = canonical_digest([])
    limited = NativeControlProtocol(
        client, DeltaBudget(tmp_path, frozen.expires_at + timedelta(days=1000))
    )
    with pytest.raises(HarnessError, match="TOOL_NOT_ALLOWED"):
        await limited.call("flowtest.propose_flow_draft", {}, scenario_id="ST-MCP-023", phase="bad")
    assert session.calls == 0
