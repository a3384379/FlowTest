"""Atomic processing budget checks; request 501 can arrive but must not be processed."""
# ruff: noqa: S101

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from test_selftest import (
    configuration,
    setup_fixture,
)
from test_selftest import (
    fixture_apps as fixture_apps,
)

from app.selftest_contracts import BudgetScope, FixtureConfiguration, SyntheticRequest
from app.selftest_journal import FixtureError, FixtureStore

NONCE = "synthetic-parent-nonce-001"


def configured_scope(
    *, nonce: str = NONCE, limit: int = 500, expires: float = 1600.0
) -> BudgetScope:
    return BudgetScope(
        parent_batch_key="parent-batch", nonce=nonce, limit=limit, expires_at=expires
    )


def configure_phase(store: FixtureStore, phase: str, scope: BudgetScope) -> None:
    store.configure(
        phase,
        "scenario",
        FixtureConfiguration.model_validate(
            configuration(nonce=scope.nonce, budget_scope=scope.model_dump())
        ),
    )


def record(store: FixtureStore, phase: str):
    return store.record(
        phase,
        "scenario",
        SyntheticRequest(),
        method="GET",
        authorization_present=False,
        cookie_present=False,
    )


def test_only_one_of_two_concurrent_requests_at_499_is_processed(
    tmp_path: Path,
) -> None:
    store = FixtureStore(tmp_path / "atomic.sqlite3", clock=lambda: 1000.0)
    store.start_epoch()
    configure_phase(store, "phase-main", configured_scope())
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE selftest_budget_scopes SET admitted_count=499")
    ready = Barrier(2)

    def attempt(_index: int) -> str:
        independent = FixtureStore(store.path, clock=lambda: 1000.0)
        ready.wait(timeout=5)
        try:
            record(independent, "phase-main")
        except FixtureError as error:
            assert error.status_code == 429
            return error.code
        return "processed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ["FIXTURE_SIDE_EFFECT_BUDGET_EXHAUSTED", "processed"]
    journal = store.journal("phase-main", "scenario")
    assert journal.request_count == 1 and len(journal.entries) == 1
    assert journal.budget.admitted_count == 500 and journal.budget.rejected_count == 1


def test_shared_parent_budget_survives_namespace_deletion_and_all_phases(
    tmp_path: Path,
) -> None:
    store = FixtureStore(tmp_path / "shared.sqlite3", clock=lambda: 1000.0)
    store.start_epoch()
    scope = configured_scope(limit=3)
    for phase in ("phase-main", "phase-cleanup", "phase-next"):
        configure_phase(store, phase, scope)
    record(store, "phase-main")
    store.remove("phase-main", "scenario")
    configure_phase(store, "phase-main", scope)
    assert store.journal("phase-main", "scenario").request_count == 0
    record(store, "phase-cleanup")
    record(store, "phase-next")
    with pytest.raises(FixtureError, match="预算已耗尽"):
        record(store, "phase-main")
    journal = store.journal("phase-main", "scenario")
    assert journal.request_count == 0
    assert journal.budget.admitted_count == 3 and journal.budget.rejected_count == 1
    assert journal.budget.parent_batch_key == "parent-batch"
    assert journal.budget.expires_at == 1600.0


def test_expired_scope_cannot_be_renewed_and_fresh_nonce_is_isolated(
    tmp_path: Path,
) -> None:
    now = [1000.0]
    store = FixtureStore(tmp_path / "expiry.sqlite3", clock=lambda: now[0])
    store.start_epoch()
    scope = configured_scope(limit=1, expires=1001.0)
    configure_phase(store, "phase", scope)
    previous = record(store, "phase")
    now[0] = 1002.0
    with pytest.raises(FixtureError) as expired:
        record(store, "phase")
    assert expired.value.code == "FIXTURE_BUDGET_EXPIRED"
    store.remove("phase", "scenario")
    with pytest.raises(FixtureError) as renewal:
        configure_phase(store, "phase", scope)
    assert renewal.value.code == "FIXTURE_BUDGET_EXPIRED"
    fresh = configured_scope(nonce="fresh-synthetic-nonce-002", limit=1, expires=1600.0)
    configure_phase(store, "phase", fresh)
    current = record(store, "phase")
    assert store.finish(previous.request_id, "completed") is False
    assert store.finish(current.request_id, "completed") is True
    journal = store.journal("phase", "scenario")
    assert journal.budget.nonce == fresh.nonce and journal.budget.admitted_count == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT count(*) FROM selftest_budget_scopes").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["limit", "digest", "nonce", "deadline"])
def test_bound_budget_identity_cannot_be_changed(tmp_path: Path, change: str) -> None:
    store = FixtureStore(tmp_path / "identity.sqlite3", clock=lambda: 1000.0)
    store.start_epoch()
    scope = configured_scope()
    configure_phase(store, "phase", scope)
    changes = {
        "limit": {"budget_scope": scope.model_copy(update={"limit": 499}).model_dump()},
        "digest": {"fixture_digest": "b" * 64},
        "nonce": {"nonce": "other-synthetic-nonce-001"},
        "deadline": {"budget_scope": scope.model_copy(update={"expires_at": 1700.0}).model_dump()},
    }
    payload = configuration(nonce=scope.nonce, budget_scope=scope.model_dump())
    payload.update(changes[change])
    with pytest.raises(FixtureError) as refused:
        store.configure("other-phase", "scenario", FixtureConfiguration.model_validate(payload))
    assert refused.value.status_code == 409
    assert store.journal("phase", "scenario").budget.admitted_count == 0


def test_501st_arrival_has_standard_429_and_no_processing_receipt(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin, max_bytes=1_048_576)
    for _index in range(500):
        assert public.get("/selftest/batch-a/ST-ENG-002/request").status_code == 200
    refused = public.get("/selftest/batch-a/ST-ENG-002/request")
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "FIXTURE_SIDE_EFFECT_BUDGET_EXHAUSTED"
    assert refused.json()["error"]["trace_id"]
    journal = admin.get(path + "/journal?limit=1000").json()
    assert journal["request_count"] == 500 and len(journal["entries"]) == 500
    assert journal["budget"]["admitted_count"] == 500 and journal["budget"]["rejected_count"] == 1
    assert journal["metrics"]["completed_count"] == 500
    invalid = configuration(budget_scope={"parent_batch_key": "b", "nonce": NONCE, "limit": 501})
    assert admin.put(path + "-other", json=invalid).status_code == 422


def test_reserved_old_generation_cannot_process_a_recreated_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FixtureStore(tmp_path / "generation.sqlite3", clock=lambda: 1000.0)
    store.start_epoch()
    scope = configured_scope(limit=2)
    configure_phase(store, "phase", scope)
    reserve = store._reserve

    def recreate_after_reserving(batch: str, scenario: str) -> str:
        previous = reserve(batch, scenario)
        store.remove(batch, scenario)
        configure_phase(store, batch, scope)
        return previous

    monkeypatch.setattr(store, "_reserve", recreate_after_reserving)
    with pytest.raises(FixtureError) as refused:
        record(store, "phase")
    assert refused.value.code == "FIXTURE_RESERVATION_CHANGED"
    journal = store.journal("phase", "scenario")
    assert journal.request_count == 0 and journal.budget.admitted_count == 1
    assert journal.metrics.events == []
    monkeypatch.setattr(store, "_reserve", reserve)
    record(store, "phase")
    assert store.journal("phase", "scenario").budget.admitted_count == 2


def test_expired_budget_cleanup_keeps_storage_bounded(tmp_path: Path) -> None:
    now = [1000.0]
    store = FixtureStore(tmp_path / "capacity.sqlite3", clock=lambda: now[0])
    epoch = store.start_epoch()
    with sqlite3.connect(store.path) as connection:
        connection.executemany(
            "INSERT INTO selftest_budget_scopes(parent_batch_key,nonce,budget_limit,"
            "fixture_digest,registration_epoch,expires_at) VALUES (?,?,500,?,?,1001.0)",
            [(f"scope-{index}", NONCE, "a" * 64, epoch) for index in range(128)],
        )
    with pytest.raises(FixtureError) as full:
        configure_phase(store, "phase", configured_scope())
    assert full.value.code == "FIXTURE_BUDGET_CAPACITY_EXCEEDED"
    now[0] = 1002.0
    configure_phase(store, "phase", configured_scope())
    assert store.journal("phase", "scenario").budget.admitted_count == 0
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT count(*) FROM selftest_budget_scopes").fetchone()[0] == 1
