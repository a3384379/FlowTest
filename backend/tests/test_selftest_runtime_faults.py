"""Driver/oracle behavior tests; these never count as deployed runtime acceptance."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest import runtime_faults as subject
from scripts.selftest.io import HarnessError, PublicAPI, read_json
from scripts.selftest.run_runtime_faults import Progress
from scripts.selftest.runtime_faults import (
    Assets,
    DropCompletedResponse,
    Observation,
    ObserverResult,
    Operation,
    RuntimeClients,
    Snapshot,
    VariantRuntime,
    launch_same_key,
    load_pack,
    verify,
)

PACK_PATH = (
    Path(__file__).resolve().parents[2] / "selftest/packs/runtime-faults-v1/expectations.json"
)


def golden(variant):
    pack, _ = load_pack(PACK_PATH)
    return next(item for item in pack.variants if item.variant == variant)


def observed(variant):
    expected = golden(variant)
    operation = Operation(id=uuid4(), status=expected.native_status, trigger=expected.trigger)
    child = (
        ObserverResult(
            status=expected.observer_status,
            exit_code=expected.observer_exit_code,
            reason_code=expected.required_reason,
            observed_native_status="running",
        )
        if expected.observer_status
        else None
    )
    return Observation(
        scenario_id=expected.scenario_id,
        variant=variant,
        operations=(operation,),
        final=Snapshot(
            run=operation,
            execution_ids=() if variant == "queued" else (uuid4(),),
            item_statuses=(expected.native_status,),
            api_versions=(1,),
            snapshot_digests=("a" * 64,),
        ),
        conflicts=(expected.required_conflict,) if expected.required_conflict else (),
        markers=expected.markers,
        cancellation_stage=expected.stage,
        observer=child,
        independent_status=expected.expected_independent_status or "complete",
        reason_codes=(expected.required_reason,) if expected.required_reason else (),
        cleanup_status="completed",
        pending_observed=variant == "concurrent",
        lost_response_after_send=variant == "lost-response",
        request_count=len(expected.markers),
        first_wire_value=expected.actual_environment_value,
    )


def test_pack_freezes_all_fifteen_variants_and_bounded_budget():
    pack, digest = load_pack(PACK_PATH)
    assert len(pack.variants) == 15 and len(digest) == 64
    assert pack.max_requests == 100 and pack.max_runtime_seconds == 600
    assert {item.scenario_id for item in pack.variants} == {
        "ST-RUN-001",
        "ST-RUN-002",
        "ST-RUN-003",
        "ST-RUN-005",
        "ST-RUN-006",
    }


@pytest.mark.parametrize("variant", [item.variant for item in load_pack(PACK_PATH)[0].variants])
def test_independently_declared_golden_can_match_expected_failure_states(variant):
    report = verify(golden(variant), observed(variant))
    assert report.status == "matched", report
    assert report.native_status == golden(variant).native_status


def test_extra_wire_request_cannot_hide_duplicate_nonidempotent_side_effect():
    value = observed("same-key").model_copy(
        update={"markers": ("first", "follow", "cleanup", "first")}
    )
    report = verify(golden("same-key"), value)
    assert "RUNTIME_FAULT_WIRE_SEQUENCE_MISMATCH" in {item.code for item in report.findings}


def test_two_native_operation_ids_never_pass_same_key():
    value = observed("same-key")
    value = value.model_copy(
        update={"operations": (*value.operations, Operation(id=uuid4(), status="passed"))}
    )
    assert "RUNTIME_FAULT_DUPLICATE_OPERATION" in {
        item.code for item in verify(golden("same-key"), value).findings
    }


def test_terminal_parent_does_not_hide_nonterminal_child():
    value = observed("manual")
    value = value.model_copy(
        update={"final": value.final.model_copy(update={"item_statuses": ("running",)})}
    )
    assert verify(golden("manual"), value).status == "mismatched"


def test_concurrent_replay_without_actual_pending_is_incomplete():
    value = observed("concurrent").model_copy(update={"pending_observed": False})
    assert verify(golden("concurrent"), value).status == "incomplete"


def test_changed_payload_requires_exact_conflict_code():
    value = observed("changed-payload").model_copy(
        update={"conflicts": ("IDEMPOTENCY_IN_PROGRESS",)}
    )
    report = verify(golden("changed-payload"), value)
    assert report.status != "matched"
    assert "RUNTIME_FAULT_UNEXPECTED_CONFLICT" in {item.code for item in report.findings}


def test_observer_deadline_cannot_rewrite_native_cancelled_to_passed():
    value = observed("deadline")
    value = value.model_copy(
        update={
            "final": value.final.model_copy(
                update={"run": value.final.run.model_copy(update={"status": "passed"})}
            )
        }
    )
    assert verify(golden("deadline"), value).status == "mismatched"


def test_observer_error_requires_actual_running_snapshot():
    value = observed("crash-watchdog")
    value = value.model_copy(
        update={"observer": value.observer.model_copy(update={"observed_native_status": "passed"})}
    )
    assert verify(golden("crash-watchdog"), value).status == "mismatched"


def test_force_policy_must_match_exact_cleanup_wire_sequence():
    value = observed("force-skip-cleanup").model_copy(update={"markers": ("first", "cleanup")})
    assert verify(golden("force-skip-cleanup"), value).status == "mismatched"


def test_configuration_drift_claim_without_actual_wire_value_is_incomplete():
    value = observed("environment-drift").model_copy(update={"first_wire_value": None})
    assert verify(golden("environment-drift"), value).status == "incomplete"


@pytest.mark.asyncio
async def test_drop_completed_response_sends_once_and_has_explicit_witness():
    calls = []

    async def upstream(request):
        calls.append(request)
        return httpx.Response(202, json={"id": str(uuid4()), "status": "queued"})

    fault = DropCompletedResponse(httpx.MockTransport(upstream))
    api = PublicAPI("http://fixture.invalid", transport=fault)
    try:
        with pytest.raises(httpx.ReadTimeout):
            await api.object("POST", "/projects/x/test-plans/y/runs", idempotency_key="same-key")
    finally:
        await api.close()
    assert len(calls) == 1 and fault.completed_and_dropped


@pytest.mark.asyncio
async def test_real_upstream_timeout_is_not_misreported_as_injected_response_loss():
    async def upstream(request):
        raise httpx.ReadTimeout("upstream did not respond", request=request)

    fault = DropCompletedResponse(httpx.MockTransport(upstream))
    api = PublicAPI("http://fixture.invalid", transport=fault)
    try:
        with pytest.raises(httpx.ReadTimeout):
            await api.object("POST", "/runs", idempotency_key="same-key")
    finally:
        await api.close()
    assert not fault.completed_and_dropped


@pytest.mark.asyncio
async def test_launch_does_not_treat_arbitrary_409_as_pending():
    api = PublicAPI(
        "http://fixture.invalid",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(409, json={"error": {"code": "UNRELATED_CONFLICT"}}),
        ),
    )
    try:
        with pytest.raises(HarnessError, match="UNEXPECTED_ERROR"):
            await launch_same_key(api, "/runs", "same-key")
    finally:
        await api.close()


def assets():
    return Assets(
        project_id=uuid4(),
        environment_id=uuid4(),
        api_id=uuid4(),
        workflow_id=uuid4(),
        workflow_version=1,
        workflow_fingerprint="a" * 64,
        case_id=uuid4(),
        case_version=1,
        suite_id=uuid4(),
        suite_version=1,
        plan_id=uuid4(),
        batch_key="owned-batch",
        scenario_key="owned-scenario",
        skip_cleanup=False,
        pinned=True,
        frozen_environment_digest="b" * 64,
    )


@pytest.mark.asyncio
async def test_unknown_launch_never_deletes_fixture_and_persists_needs_review(tmp_path):
    calls = []
    api = PublicAPI(
        "http://fixture.invalid",
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(204),
        ),
    )
    try:
        clients = RuntimeClients(
            api, api, api, api, "http://fixture.invalid", "synthetic-read-token"
        )
        runtime = VariantRuntime(golden("same-key"), assets(), clients, None, tmp_path)
        await runtime.cleanup()
        assert calls == []
        assert read_json(tmp_path / "cleanup.json")["status"] == "needs_review"
    finally:
        await api.close()


@pytest.mark.asyncio
async def test_failed_fixture_delete_is_never_cleanup_completed(tmp_path):
    api = PublicAPI(
        "http://fixture.invalid",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(500, json={"error": {"code": "INTERNAL_ERROR"}}),
        ),
    )
    try:
        clients = RuntimeClients(
            api, api, api, api, "http://fixture.invalid", "synthetic-read-token"
        )
        runtime = VariantRuntime(
            golden("same-key"),
            assets(),
            clients,
            None,
            tmp_path,
            fixture_nonce="a" * 32,
            fixture_digest="b" * 64,
        )
        runtime.final = observed("same-key").final
        with pytest.raises(HarnessError):
            await runtime.cleanup()
        assert read_json(tmp_path / "cleanup.json")["status"] == "failed"
    finally:
        await api.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["foreign", "active", "wrong_digest"])
async def test_terminal_runtime_cannot_delete_unowned_or_active_mock_namespace(tmp_path, mutation):
    chosen = assets()
    calls = []

    def serve(request):
        calls.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(
            200,
            json={
                "batch_key": chosen.batch_key,
                "scenario_id": chosen.scenario_key,
                "nonce": "f" * 32 if mutation == "foreign" else "a" * 32,
                "fixture_digest": "e" * 64 if mutation == "wrong_digest" else "b" * 64,
                "fixture_epoch": "epoch",
                "registration_epoch": "registration",
                "entries": [],
                "metrics": {"complete": True, "active_count": 1 if mutation == "active" else 0},
            },
        )

    api = PublicAPI("http://fixture.invalid", transport=httpx.MockTransport(serve))
    try:
        runtime = VariantRuntime(
            golden("same-key"),
            chosen,
            RuntimeClients(api, api, api, api, "http://fixture.invalid", "read-token"),
            None,
            tmp_path,
            fixture_nonce="a" * 32,
            fixture_digest="b" * 64,
        )
        runtime.final = observed("same-key").final
        await runtime.cleanup()
        assert not any(request.method == "DELETE" for request in calls)
        assert read_json(tmp_path / "cleanup.json")["status"] == "needs_review"
    finally:
        await api.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "unknown"])
async def test_runtime_mock_delete_is_epoch_conditioned_and_unknown_is_never_replayed(
    tmp_path, outcome
):
    chosen = assets()
    calls = []

    def serve(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "batch_key": chosen.batch_key,
                    "scenario_id": chosen.scenario_key,
                    "nonce": "a" * 32,
                    "fixture_digest": "b" * 64,
                    "fixture_epoch": "fixture-epoch",
                    "registration_epoch": "registration-epoch",
                    "entries": [],
                    "metrics": {"complete": True, "active_count": 0},
                },
            )
        assert json.loads(request.content) == {
            "expected_nonce": "a" * 32,
            "expected_fixture_epoch": "fixture-epoch",
            "expected_registration_epoch": "registration-epoch",
        }
        if outcome == "unknown":
            raise httpx.ReadTimeout("synthetic unknown DELETE result", request=request)
        return httpx.Response(204)

    api = PublicAPI("http://fixture.invalid", transport=httpx.MockTransport(serve))
    try:
        runtime = VariantRuntime(
            golden("same-key"),
            chosen,
            RuntimeClients(api, api, api, api, "http://fixture.invalid", "read-token"),
            None,
            tmp_path,
            fixture_nonce="a" * 32,
            fixture_digest="b" * 64,
        )
        runtime.final = observed("same-key").final
        await runtime.cleanup()
        assert read_json(tmp_path / "cleanup.json")["status"] == (
            "completed" if outcome == "completed" else "needs_review"
        )
        await runtime.cleanup()
        assert [request.method for request in calls] == ["GET", "DELETE"]
    finally:
        await api.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_runtime_waits_for_owned_active_request_and_never_deletes_reregistered_namespace(
    tmp_path, changed
):
    chosen = assets()
    calls = []

    def serve(request):
        calls.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        reads = sum(row.method == "GET" for row in calls)
        return httpx.Response(
            200,
            json={
                "batch_key": chosen.batch_key,
                "scenario_id": chosen.scenario_key,
                "nonce": "a" * 32,
                "fixture_digest": "b" * 64,
                "fixture_epoch": "epoch",
                "registration_epoch": "new-registration" if changed and reads > 1 else "first",
                "entries": [],
                "metrics": {"complete": True, "active_count": 1 if reads == 1 else 0},
            },
        )

    api = PublicAPI("http://fixture.invalid", transport=httpx.MockTransport(serve))
    try:
        runtime = VariantRuntime(
            golden("same-key"),
            chosen,
            RuntimeClients(api, api, api, api, "http://fixture.invalid", "read-token"),
            None,
            tmp_path,
            fixture_nonce="a" * 32,
            fixture_digest="b" * 64,
            fixture_deadline=datetime.now(UTC) + timedelta(seconds=10),
        )
        runtime.final = observed("same-key").final
        await runtime.cleanup()
        assert [r.method for r in calls] == (
            ["GET", "GET"] if changed else ["GET", "GET", "DELETE"]
        )
        receipt = read_json(tmp_path / "cleanup.json")
        assert receipt["management_read_admitted"] == 2
        assert receipt["status"] == ("needs_review" if changed else "completed")
    finally:
        await api.close()


def test_runtime_cleanup_management_admission_has_finite_cap_and_frozen_deadline(tmp_path):
    runtime = VariantRuntime(golden("same-key"), assets(), None, None, tmp_path)
    for _ in range(12):
        runtime._reserve_management_read()
    with pytest.raises(HarnessError, match="CLEANUP_READ_BUDGET"):
        runtime._reserve_management_read()
    runtime.management_read_admitted = 0
    runtime.fixture_deadline = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(HarnessError, match="CLEANUP_READ_BUDGET"):
        runtime._reserve_management_read()
    assert runtime.management_read_admitted == 0


@pytest.mark.asyncio
async def test_driver_requires_completed_response_witness_not_arbitrary_timeout(
    tmp_path, monkeypatch
):
    async def upstream(request):
        raise httpx.ReadTimeout("upstream did not reply", request=request)

    witness = DropCompletedResponse(httpx.MockTransport(upstream))
    lossy = PublicAPI("http://fixture.invalid", transport=witness)
    ordinary = PublicAPI(
        "http://fixture.invalid", transport=httpx.MockTransport(lambda _: httpx.Response(204))
    )

    async def recover(*args, **kwargs):
        return Operation(id=uuid4(), status="queued")

    monkeypatch.setattr(subject, "recover_same_key", recover)
    try:
        clients = RuntimeClients(
            ordinary,
            ordinary,
            ordinary,
            ordinary,
            "http://fixture.invalid",
            "read-token",
            lambda: subject.LossClient(lossy, witness),
        )
        runtime = VariantRuntime(golden("lost-response"), assets(), clients, None, tmp_path)
        await runtime.response_loss()
        assert runtime.dropped is False
        assert runtime.run_id is not None
    finally:
        await ordinary.close()


def test_expected_denominator_is_precreated_even_before_any_action():
    pack, _ = load_pack(PACK_PATH)
    rows = subject.initial_reports(pack)
    assert len(rows) == 15
    assert all(row.status == "incomplete" and row.findings[0].code == "NOT_RUN" for row in rows)


def test_manual_ci_relation_requires_same_snapshot_distinct_ids_and_triggers():
    manual, ci = observed("manual"), observed("ci")
    manual = manual.model_copy(
        update={
            "final": manual.final.model_copy(
                update={"run": manual.final.run.model_copy(update={"target_digest": "a" * 64})}
            )
        }
    )
    ci = ci.model_copy(
        update={
            "final": ci.final.model_copy(
                update={"run": ci.final.run.model_copy(update={"target_digest": "a" * 64})}
            )
        }
    )
    assert subject.run001_relation((manual, ci))
    ci = ci.model_copy(
        update={
            "final": ci.final.model_copy(
                update={"run": ci.final.run.model_copy(update={"id": manual.final.run.id})}
            )
        }
    )
    assert not subject.run001_relation((manual, ci))


def test_worker_fault_refuses_foreign_nonce_before_docker_pause(monkeypatch):
    from types import SimpleNamespace

    from scripts.selftest.profile_stack import ProfileContainer

    calls = []
    expected = ProfileContainer(
        role="runner-worker", container_id="a" * 64, image_digest="sha256:" + "b" * 64
    )
    controller = object.__new__(subject.OwnedWorkers)
    controller.binding = SimpleNamespace(project_name="owned-project", nonce="owned-nonce")
    controller.identities = (expected,)
    controller.paused = False

    def docker(arguments):
        calls.append(arguments)
        return json.dumps(
            [
                {
                    "Id": expected.container_id,
                    "Image": expected.image_digest,
                    "Config": {
                        "Labels": {
                            "com.docker.compose.project": "owned-project",
                            "dev.flowtest.selftest.nonce": "foreign",
                        }
                    },
                }
            ]
        )

    monkeypatch.setattr(subject, "_docker", docker)
    with pytest.raises(HarnessError, match="OWNERSHIP_MISMATCH"):
        controller.pause()
    assert len(calls) == 1 and calls[0][0] == "inspect"


def test_empty_child_denominator_cannot_pass_positive_parent():
    value = observed("manual")
    value = value.model_copy(update={"final": value.final.model_copy(update={"item_statuses": ()})})
    assert verify(golden("manual"), value).status == "incomplete"


def test_two_execution_attempts_cannot_hide_behind_one_run_id():
    value = observed("same-key")
    value = value.model_copy(
        update={"final": value.final.model_copy(update={"execution_ids": (uuid4(), uuid4())})}
    )
    assert verify(golden("same-key"), value).status == "mismatched"


def test_packaged_dual_junit_keeps_raw_failure_and_independent_match_separate(tmp_path):
    from xml.etree.ElementTree import parse

    from scripts.selftest.run_runtime_faults import write_junit
    from scripts.selftest.runtime_faults import RuntimePackReport, initial_reports

    pack, digest = load_pack(PACK_PATH)
    rows = initial_reports(pack)
    rows = (
        rows[0].model_copy(update={"native_status": "failed", "status": "matched", "findings": ()}),
        *rows[1:],
    )
    report = RuntimePackReport(
        pack_digest=digest,
        completed_count=1,
        verdict="blocked",
        exit_code=2,
        run001_same_frozen_plan_distinct_runs=False,
        request_count=0,
        runtime_profile="compact",
        scenarios=rows,
    )
    write_junit(tmp_path, report)
    execution = parse(tmp_path / "execution.junit.xml").getroot()
    verification = parse(tmp_path / "verification.junit.xml").getroot()
    assert len(execution.findall("testcase")) == len(verification.findall("testcase")) == 15
    assert execution.find("testcase/failure") is not None
    assert verification.findall("testcase")[0].find("failure") is None
    assert len(verification.findall("testcase/failure")) == 14


def test_packaged_manifest_and_report_schemas_match_strict_contracts():
    from scripts.selftest.runtime_faults import FrozenRuntimeBatch, RuntimePackReport

    for model, name in (
        (FrozenRuntimeBatch, "batch-manifest.schema.json"),
        (RuntimePackReport, "verification-report.schema.json"),
    ):
        exported = json.loads(PACK_PATH.with_name(name).read_text())
        assert exported == model.model_json_schema()
        assert exported["additionalProperties"] is False


def budget_batch():
    from datetime import UTC, datetime, timedelta

    from scripts.selftest.runtime_faults import FrozenRuntimeBatch

    pack, digest = load_pack(PACK_PATH)
    return FrozenRuntimeBatch.model_validate(
        {
            "batch_key": "runtime-" + "a" * 20,
            "pack_digest": digest,
            "driver_digest": "b" * 64,
            "expected_variants": pack.variants,
            "builds": {"candidate": "sha256:" + "c" * 64, "fixture": "sha256:" + "d" * 64},
            "source_digest": "e" * 64,
            "profile": "compact",
            "nonce": "f" * 32,
            "created_at": datetime.now(UTC),
            "deadline": datetime.now(UTC) + timedelta(seconds=500),
        }
    )


def scoped_observation(frozen, variant, admitted, **changes):
    from scripts.selftest.contracts import FixtureBudgetReceipt

    value = observed(variant)
    budget = FixtureBudgetReceipt(
        parent_batch_key=frozen.batch_key,
        nonce=frozen.nonce,
        limit=100,
        expires_at=frozen.deadline.timestamp(),
        admitted_count=admitted,
        rejected_count=0,
        fixture_digest=frozen.pack_digest,
        registration_epoch="same-epoch",
    ).model_copy(update=changes)
    return value.model_copy(update={"budget": budget})


def test_runtime_batch_budget_requires_exact_final_independent_admission_count():
    from scripts.selftest.run_runtime_faults import budget_findings

    frozen = budget_batch()
    first = scoped_observation(frozen, "manual", 3)
    second = scoped_observation(frozen, "ci", 6)
    assert budget_findings(frozen, (first, second)) == ()
    assert budget_findings(frozen, (first, second.model_copy(update={"request_count": 2}))) == (
        "RUNTIME_FAULT_FIXTURE_BUDGET_COUNT_MISMATCH",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"nonce": "different"},
        {"limit": 101},
        {"expires_at": 1.0},
        {"parent_batch_key": "different"},
        {"rejected_count": 1},
        {"fixture_digest": "different"},
        {"admitted_count": 2},
    ],
)
def test_runtime_batch_budget_drift_or_rejection_cannot_pass(changes):
    from scripts.selftest.run_runtime_faults import budget_findings

    frozen = budget_batch()
    assert budget_findings(frozen, (scoped_observation(frozen, "manual", 3, **changes),))


@pytest.mark.asyncio
async def test_configure_reuses_absolute_batch_scope_in_every_namespace():
    from scripts.selftest.contracts import FixtureBudgetScope
    from scripts.selftest.runtime_faults import configure

    frozen = budget_batch()
    captured = []

    async def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {}})

    api = PublicAPI(
        "http://observer.test", "synthetic-management", transport=httpx.MockTransport(handle)
    )
    scope = FixtureBudgetScope(
        parent_batch_key=frozen.batch_key,
        nonce=frozen.nonce,
        limit=100,
        expires_at=frozen.deadline.timestamp(),
    )
    assets = Assets(
        project_id=uuid4(),
        environment_id=uuid4(),
        api_id=uuid4(),
        workflow_id=uuid4(),
        workflow_version=1,
        case_id=uuid4(),
        case_version=1,
        suite_id=uuid4(),
        suite_version=1,
        plan_id=uuid4(),
        batch_key=frozen.batch_key,
        scenario_key="ST-RUN-001-manual",
        workflow_fingerprint="a" * 64,
        skip_cleanup=False,
        pinned=True,
        frozen_environment_digest="b" * 64,
    )
    try:
        await configure(api, assets, frozen.pack_digest, slow=False, scope=scope)
        await configure(
            api,
            assets.model_copy(update={"scenario_key": "ST-RUN-002-same-key"}),
            frozen.pack_digest,
            slow=True,
            scope=scope,
        )
    finally:
        await api.close()
    assert len(captured) == 2
    assert (
        captured[0]["budget_scope"] == captured[1]["budget_scope"] == scope.model_dump(mode="json")
    )
    assert all(
        item["nonce"] == frozen.nonce and 1 <= item["ttl_seconds"] <= 500 for item in captured
    )


def test_all_matched_rows_cannot_hide_a_late_final_variant() -> None:
    frozen = budget_batch().model_copy(
        update={"deadline": datetime.now(UTC) - timedelta(seconds=1)}
    )
    observations: list[Observation] = []
    total = 0
    for expected in load_pack(PACK_PATH)[0].variants:
        sample = scoped_observation(frozen, expected.variant, 0)
        total += sample.request_count
        sample = sample.model_copy(
            update={"budget": sample.budget.model_copy(update={"admitted_count": total})}
        )
        if expected.scenario_id == "ST-RUN-001":
            sample = sample.model_copy(
                update={
                    "final": sample.final.model_copy(
                        update={
                            "run": sample.final.run.model_copy(update={"target_digest": "a" * 64})
                        }
                    )
                }
            )
        observations.append(sample)
    progress = Progress(
        tuple(verify(golden(item.variant), item) for item in observations), tuple(observations)
    )
    report = progress.result(frozen)
    assert report.verdict == "blocked" and report.exit_code == 2
    assert report.completed_count == len(report.scenarios) == 15
    assert all(item.status == "matched" for item in report.scenarios)
    assert "RUNTIME_FAULT_BATCH_DEADLINE" in report.reason_codes
