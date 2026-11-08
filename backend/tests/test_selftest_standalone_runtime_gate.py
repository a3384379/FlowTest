"""Incomplete slot occupancy cannot prove Standalone queued cancellation or drift."""

import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.contracts import (
    FixtureJournal,
    FixtureMetrics,
    FixtureRequest,
    FixtureRequestEvent,
)
from scripts.selftest.runtime_faults import Operation, Snapshot, StandaloneGateWitness
from scripts.selftest.standalone_runtime_gate import gate_findings
from test_selftest_runtime_faults import budget_batch


def witnesses(frozen):
    values = []
    for index in range(1, 5):
        key = f"standalone-gate-{index}"
        events = tuple(
            FixtureRequestEvent(
                request_id=uuid4(),
                sequence=n,
                started_at=1.0,
                active_at_begin=n,
            )
            for n in range(1, 5)
        )
        metrics = FixtureMetrics(
            events=events,
            complete=True,
            active_count=4,
            peak_concurrency=4,
            completed_count=0,
            cancelled_count=0,
            failed_count=0,
        )
        active = FixtureJournal(
            batch_key=frozen.batch_key,
            scenario_id=key,
            nonce=frozen.nonce,
            fixture_epoch="synthetic-epoch",
            fixture_digest=frozen.pack_digest,
            request_count=4,
            metrics=metrics,
        )
        settled = active.model_copy(
            update={
                "request_count": 12,
                "entries": tuple(
                    FixtureRequest(
                        sequence=n,
                        method="POST",
                        path="/synthetic",
                        response_status=200,
                        marker=marker,
                    )
                    for n, marker in enumerate(["first"] * 4 + ["follow"] * 4 + ["cleanup"] * 4, 1)
                ),
                "metrics": metrics.model_copy(update={"active_count": 0, "completed_count": 12}),
            }
        )
        executions = tuple(
            Snapshot(
                run=Operation(id=uuid4(), status="passed"),
                execution_ids=(uuid4(),),
                item_statuses=("passed",),
                api_versions=(1, 1, 1),
                snapshot_digests=("a" * 64,),
            )
            for _ in range(4)
        )
        values.append(
            StandaloneGateWitness(
                scenario_key=key,
                project_id=uuid4(),
                workflow_id=uuid4(),
                held_at=frozen.created_at + timedelta(seconds=1),
                completed_at=frozen.created_at + timedelta(seconds=20),
                at_hold=active,
                settled=settled,
                executions=executions,
            )
        )
    return tuple(values)


def test_standalone_gate_requires_all_four_real_occupancy_windows():
    frozen = budget_batch().model_copy(update={"profile": "standalone"})
    values = witnesses(frozen)
    assert gate_findings(frozen, values) == ()
    assert gate_findings(frozen, values[:-1]) == ("RUNTIME_FAULT_STANDALONE_GATE_SET_INCOMPLETE",)
    assert gate_findings(frozen.model_copy(update={"profile": "compact"}), values)


@pytest.mark.parametrize("mutation", ["active", "counter", "markers", "foreign", "failed", "late"])
def test_slot_gate_cannot_hide_missing_effects_foreign_journal_or_failed_native_occupant(mutation):
    frozen = budget_batch().model_copy(update={"profile": "standalone"})
    values = witnesses(frozen)
    selected = values[0]
    if mutation == "active":
        active = selected.at_hold.model_copy(update={"request_count": 3})
        selected = selected.model_copy(update={"at_hold": active})
    elif mutation == "counter":
        settled = selected.settled.model_copy(update={"request_count": 11})
        selected = selected.model_copy(update={"settled": settled})
    elif mutation == "markers":
        settled = selected.settled.model_copy(update={"entries": selected.settled.entries[:-1]})
        selected = selected.model_copy(update={"settled": settled})
    elif mutation == "foreign":
        settled = selected.settled.model_copy(update={"nonce": "foreign-nonce"})
        selected = selected.model_copy(update={"settled": settled})
    elif mutation == "failed":
        executions = list(selected.executions)
        executions[0] = executions[0].model_copy(update={"item_statuses": ("failed",)})
        selected = selected.model_copy(update={"executions": tuple(executions)})
    else:
        selected = selected.model_copy(
            update={"completed_at": frozen.deadline + timedelta(seconds=1)}
        )
    assert gate_findings(frozen, (selected, *values[1:])) == (
        "RUNTIME_FAULT_STANDALONE_GATE_MISMATCH",
    )
