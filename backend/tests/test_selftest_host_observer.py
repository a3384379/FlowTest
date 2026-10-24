"""Independent O host trail cannot hide failures, unknown calls or proposal mutations."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import (  # noqa: E402
    BatchEvidence,
    BatchManifest,
    HostEvidence,
    canonical_digest,
)
from scripts.selftest.host_contracts import HostModelSummary, HostToolReceipt  # noqa: E402
from scripts.selftest.host_events import EventReceipt  # noqa: E402
from scripts.selftest.host_launch import VerifiedGrant  # noqa: E402
from scripts.selftest.host_observer import HostFrozenTrail  # noqa: E402
from scripts.selftest.host_runner import ProcessReceipt  # noqa: E402
from scripts.selftest.host_verify import verify_host_batch  # noqa: E402
from test_selftest_host_adapter import authorization  # noqa: E402
from test_selftest_verification import (  # noqa: E402
    DEADLINE,
    FROZEN,
    GENERATED,
    SHA,
    START,
    add_provenance,
    evidence_payload,
    manifest_payload,
)


def fixture():
    manifest, evidence = manifest_payload(), evidence_payload()
    add_provenance(manifest, evidence)
    manifest["generation_mode"] = "host_llm_mcp"
    source = evidence["scenarios"][0]["provenance"]
    source["generation_mode"] = "host_llm_mcp"
    auth = authorization(
        project_id=UUID(manifest["project_id"]),
        batch_key=manifest["batch_key"],
        approved_at=datetime.fromisoformat(START),
        expires_at=datetime.fromisoformat(DEADLINE),
    )
    auth = auth.model_copy(
        update={
            "budget": auth.budget.model_copy(update={"maximum_tool_calls": 10, "wall_seconds": 600})
        }
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    host = HostEvidence(
        host=auth.host_id,
        model=auth.model,
        skill_digest=auth.skill_digest,
        prompt_digest=canonical_digest({"workflow": SHA, "case": SHA}),
        authorized_budget_digest=grant.digest,
        actual_tool_calls=3,
    )
    source["host"] = host.model_dump(mode="json")
    receipts = []
    attempt = uuid4()
    for index, call in enumerate(source["calls"], start=1):
        phase = "case" if call["tool_name"] == "flowtest.propose_test_design" else "workflow"
        call.update(call_id=f"host-{attempt}-{index}", phase=phase)
        receipts.append(
            HostToolReceipt(
                sequence=index,
                attempt_id=attempt,
                phase=phase,
                tool_name=call["tool_name"],
                request_digest=SHA,
                result_digest=SHA,
                catalog_digest=SHA,
                started_at=datetime.fromisoformat(GENERATED),
                completed_at=datetime.fromisoformat(GENERATED),
                outcome="completed",
                business_success=True,
            )
        )
    processes = []
    for phase, proposal in (
        ("workflow", source["workflow_proposal"]),
        ("case", source["case_proposal"]),
    ):
        events = tuple(
            EventReceipt(
                sequence=index,
                event_type="item.started",
                event_digest=SHA,
                item_id=str(index),
                item_type="mcp_tool_call",
                tool_name=receipt.tool_name,
                request_digest=receipt.request_digest,
            )
            for index, receipt in enumerate(
                (item for item in receipts if item.phase == phase), start=1
            )
        )
        processes.append(
            ProcessReceipt(
                prompt_digest=SHA,
                authorization_digest=grant.digest,
                exit_code=0,
                reason_code=None,
                started_at=datetime.fromisoformat(GENERATED),
                completed_at=datetime.fromisoformat(FROZEN),
                stderr_digest=SHA,
                stderr_bytes=0,
                events=events,
                summary=HostModelSummary(
                    phase=phase,
                    status="waiting_for_review",
                    proposal_ids=(UUID(proposal["proposal_id"]),),
                ),
            )
        )
    return (
        BatchManifest.model_validate(manifest),
        BatchEvidence.model_validate(evidence),
        HostFrozenTrail(
            authorization_digest=grant.digest,
            task_digest=auth.task_digest,
            host=host,
            catalog_digest=SHA,
            receipts=tuple(receipts),
            phases=tuple(processes),
        ),
        grant,
    )


def test_independent_host_report_preserves_expected_failed_canary_and_all_batch_blocks():
    manifest, evidence, trail, grant = fixture()
    report = verify_host_batch(
        manifest,
        evidence,
        trail=trail,
        grant=grant,
        now=datetime.fromisoformat(FROZEN) + timedelta(seconds=1),
    )
    assert report.batch_verdict == "passed" and report.scenarios[0].observed_status == "failed"
    blocked = verify_host_batch(
        manifest,
        evidence.model_copy(update={"observer_error": "SYNTHETIC_OBSERVER_ERROR"}),
        trail=trail,
        grant=grant,
        now=datetime.fromisoformat(FROZEN) + timedelta(seconds=1),
    )
    assert blocked.batch_verdict == "blocked" and blocked.exit_code == 2
    assert "OBSERVER_ERROR" in {item.code for item in blocked.findings}


@pytest.mark.parametrize("change", ["request", "outcome", "event", "summary", "budget"])
def test_host_trail_mutations_cannot_be_counted_as_matching(change):
    manifest, evidence, trail, grant = fixture()
    if change == "request":
        trail = trail.model_copy(
            update={
                "receipts": (
                    trail.receipts[0].model_copy(update={"request_digest": "f" * 64}),
                    *trail.receipts[1:],
                )
            }
        )
    elif change == "outcome":
        trail = trail.model_copy(
            update={
                "receipts": (
                    trail.receipts[0].model_copy(update={"outcome": "unknown"}),
                    *trail.receipts[1:],
                )
            }
        )
    elif change == "event":
        trail = trail.model_copy(
            update={"phases": (trail.phases[0].model_copy(update={"events": ()}), trail.phases[1])}
        )
    elif change == "summary":
        trail = trail.model_copy(
            update={
                "phases": (
                    trail.phases[0].model_copy(
                        update={
                            "summary": trail.phases[0].summary.model_copy(
                                update={"proposal_ids": (uuid4(),)}
                            )
                        }
                    ),
                    trail.phases[1],
                )
            }
        )
    else:
        trail = trail.model_copy(
            update={
                "phases": (
                    trail.phases[0],
                    trail.phases[1].model_copy(
                        update={"completed_at": trail.phases[0].started_at + timedelta(seconds=601)}
                    ),
                )
            }
        )
    report = verify_host_batch(
        manifest,
        evidence,
        trail=trail,
        grant=grant,
        now=datetime.fromisoformat(FROZEN) + timedelta(seconds=1),
    )
    assert report.batch_verdict != "passed" and report.exit_code != 0
