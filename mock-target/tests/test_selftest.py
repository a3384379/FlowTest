"""Behavior checks for the separate synthetic fixture business and observer apps."""
# Match the backend test policy for assertions and explicit synthetic credentials.
# ruff: noqa: S101, S105

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.selftest import (
    create_business_app,
    create_observer_app,
    install_business_routes,
    observer_app,
)
from app.selftest_contracts import FixtureConfiguration, SyntheticRequest
from app.selftest_journal import FixtureError, FixtureStore

TOKEN = "fixture-observer-synthetic-token-for-tests"
DIGEST = "a" * 64


def configuration(**updates: Any) -> dict[str, Any]:
    return {"nonce": "synthetic-nonce-001", "fixture_digest": DIGEST, **updates}


@pytest.fixture
def fixture_apps(tmp_path: Path) -> tuple[TestClient, TestClient, FixtureStore]:
    path = tmp_path / "private" / "journal.sqlite3"
    store = FixtureStore(path)
    store.start_epoch()
    business = FastAPI()
    business.mount("/selftest", create_business_app(store))
    with (
        TestClient(business) as public,
        TestClient(observer_app(FixtureStore(path), TOKEN)) as admin,
    ):
        admin.headers["Authorization"] = f"Bearer {TOKEN}"
        yield public, admin, store


def setup_fixture(
    admin: TestClient, batch: str = "batch-a", scenario: str = "ST-ENG-002", **changes: Any
) -> str:
    path = f"/selftest/batches/{batch}/scenarios/{scenario}"
    result = admin.put(path, json=configuration(**changes))
    assert result.status_code == 204, result.text
    return path


def test_management_routes_are_absent_from_business_listener_and_require_separate_auth(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin)
    assert (
        public.put(
            path, json=configuration(), headers={"Authorization": f"Bearer {TOKEN}"}
        ).status_code
        == 404
    )
    assert (
        public.get(f"{path}/journal", headers={"Authorization": f"Bearer {TOKEN}"}).status_code
        == 404
    )
    assert admin.get("/selftest/batch-a/ST-ENG-002/request").status_code == 404
    denied = admin.get(f"{path}/journal", headers={"Authorization": "Bearer wrong"})
    assert denied.status_code == 401
    assert denied.json()["error"]["trace_id"]
    assert TOKEN not in denied.text
    assert (
        admin.get(f"{path}/journal", headers={"Authorization": b"Bearer \xe9"}).status_code == 401
    )


@pytest.mark.parametrize("listener", ["business", "observer"])
def test_fixture_routing_errors_use_standard_envelope_and_trace(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore], listener: str
) -> None:
    public, admin, _store = fixture_apps
    client = public if listener == "business" else admin
    prefix = "/selftest" if listener == "business" else ""
    missing = client.get(prefix + "/missing-route")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "FIXTURE_ROUTE_NOT_FOUND"
    assert missing.json()["error"]["trace_id"]
    route = "/selftest/batch-a/ST-ENG-002/request" if listener == "business" else "/health"
    wrong_method = client.delete(route)
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "FIXTURE_METHOD_NOT_ALLOWED"
    assert wrong_method.json()["error"]["trace_id"] != missing.json()["error"]["trace_id"]


def test_configured_sequence_is_durable_paged_and_does_not_capture_credentials(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin, response_statuses=[503, 503, 200])
    for index, status in enumerate([503, 503, 200, 200], 1):
        response = public.get(
            "/selftest/batch-a/ST-ENG-002/sequence",
            params={"marker": f"marker-{index}"},
            headers={
                "Authorization": "Bearer must-not-be-recorded",
                "Cookie": "credential=private",
            },
        )
        assert response.status_code == status
        assert response.json()["request_count"] == index
    first = admin.get(f"{path}/journal?limit=2").json()
    second = admin.get(f"{path}/journal?after_sequence={first['next_sequence']}&limit=2").json()
    assert first["request_count"] == 4
    assert first["nonce"] == "synthetic-nonce-001"
    assert first["fixture_digest"] == DIGEST
    assert first["truncated"] is False
    assert [entry["sequence"] for entry in first["entries"] + second["entries"]] == [1, 2, 3, 4]
    assert second["next_sequence"] is None
    entry = first["entries"][0]
    assert entry["authorization_present"] and entry["cookie_present"]
    assert entry["response_body"]["actual"] == 1
    assert entry["path"] == "/selftest/batch-a/ST-ENG-002/sequence"
    assert "must-not-be-recorded" not in str(first)
    assert "credential=private" not in str(first)


@pytest.mark.parametrize("value", [0, False, "", None, "中文", {"nested": [0, False, None]}])
def test_synthetic_wire_values_preserve_types_and_null(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore], value: Any
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin, response_body={"actual": 1, "value": "default"})
    response = public.post(
        "/selftest/batch-a/ST-ENG-002/request", json={"value": value, "marker": "unique"}
    )
    assert response.status_code == 200
    assert response.json()["value"] == value
    assert type(response.json()["value"]) is type(value)
    journal = admin.get(f"{path}/journal").json()
    assert journal["entries"][0]["request_body"]["value"] == value
    assert journal["entries"][0]["response_body"]["value"] == value


def test_configure_is_idempotent_without_reset_and_conflicts_do_not_overwrite_receipts(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin)
    assert public.post("/selftest/batch-a/ST-ENG-002/request", json={}).json()["value"] is None
    assert admin.put(path, json=configuration()).status_code == 204
    assert admin.put(path, json=configuration(response_body={"actual": 2})).status_code == 409
    response = public.get("/selftest/batch-a/ST-ENG-002/request")
    assert response.json()["request_count"] == 2
    assert response.json()["actual"] == 1
    assert admin.get(f"{path}/journal").json()["request_count"] == 2


def test_expiry_and_restart_are_exposed_without_claiming_complete_evidence(tmp_path: Path) -> None:
    now = [1000.0]
    store = FixtureStore(tmp_path / "journal.sqlite3", clock=lambda: now[0])
    first_epoch = store.start_epoch()
    store.configure("batch-a", "ST-ENG-002", FixtureConfiguration(**configuration(ttl_seconds=1)))
    store.record(
        "batch-a",
        "ST-ENG-002",
        SyntheticRequest(),
        method="GET",
        authorization_present=False,
        cookie_present=False,
    )
    restarted = FixtureStore(store.path, clock=lambda: now[0])
    assert restarted.start_epoch() != first_epoch
    journal = restarted.journal("batch-a", "ST-ENG-002")
    assert journal.epoch_changed and journal.truncated
    assert journal.entries[0].fixture_epoch == first_epoch
    now[0] += 2
    assert restarted.journal("batch-a", "ST-ENG-002").expired
    with pytest.raises(FixtureError) as expired:
        restarted.record(
            "batch-a",
            "ST-ENG-002",
            SyntheticRequest(),
            method="GET",
            authorization_present=False,
            cookie_present=False,
        )
    assert expired.value.status_code == 410


@pytest.mark.parametrize(
    "limits,value", [({"max_entries": 1}, "short"), ({"max_bytes": 1024}, "x" * 2000)]
)
def test_journal_overflow_retains_total_count_and_marks_incomplete(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore], limits: dict[str, int], value: str
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin, **limits)
    for _index in range(2):
        assert (
            public.post("/selftest/batch-a/ST-ENG-002/request", json={"value": value}).status_code
            == 200
        )
    journal = admin.get(f"{path}/journal").json()
    assert journal["request_count"] == 2
    assert journal["truncated"]
    assert len(journal["entries"]) < 2


def test_concurrent_requests_and_cleanup_do_not_cross_batch_boundaries(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path / "journal.sqlite3")
    store.start_epoch()
    for batch in ("batch-a", "batch-b"):
        store.configure(batch, "same-scenario", FixtureConfiguration(**configuration()))

    def request(index: int) -> None:
        batch = "batch-a" if index % 2 else "batch-b"
        independent = FixtureStore(store.path)
        independent.record(
            batch,
            "same-scenario",
            SyntheticRequest(marker=batch),
            method="POST",
            authorization_present=False,
            cookie_present=False,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(request, range(40)))
    for batch in ("batch-a", "batch-b"):
        journal = store.journal(batch, "same-scenario")
        assert journal.request_count == 20
        assert [item.sequence for item in journal.entries] == list(range(1, 21))
        assert {item.marker for item in journal.entries} == {batch}
    store.remove("batch-a", "same-scenario")
    assert store.journal("batch-b", "same-scenario").request_count == 20
    with pytest.raises(FixtureError):
        store.journal("batch-a", "same-scenario")


def test_strict_input_and_byte_budgets_reject_before_recording(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin)
    for payload in (
        {"authorization": "forbidden-field"},
        {"value": "x" * 5000},
        {"value": [[[[[[[1]]]]]]]},
    ):
        assert public.post("/selftest/batch-a/ST-ENG-002/request", json=payload).status_code == 422
    oversized = public.post("/selftest/batch-a/ST-ENG-002/request", content=b"x" * 9000)
    assert oversized.status_code == 413
    assert oversized.json()["error"]["trace_id"]
    assert admin.put(path, json=configuration(response_statuses=[204])).status_code == 422
    assert admin.get(f"{path}/journal?limit=1001").status_code == 422
    assert admin.get(f"{path}/journal").json()["request_count"] == 0


def test_business_is_opt_in_and_observer_configuration_is_not_loaded_by_business(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FLOWTEST_SELFTEST_JOURNAL_PATH", raising=False)
    monkeypatch.delenv("FLOWTEST_SELFTEST_OBSERVER_TOKEN", raising=False)
    legacy = FastAPI()
    install_business_routes(legacy)
    assert TestClient(legacy).get("/selftest/batch-a/ST-ENG-002/request").status_code == 404
    enabled = FastAPI()
    install_business_routes(enabled, tmp_path / "journal.sqlite3")
    assert TestClient(enabled).get("/selftest/batch-a/ST-ENG-002/request").status_code == 404
    with pytest.raises(RuntimeError, match="observer token"):
        create_observer_app()


def test_existing_mock_routes_preserve_their_contract_without_selftest_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLOWTEST_SELFTEST_JOURNAL_PATH", raising=False)
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/control/cursor-pages").json()["items"] == ["first"]
        assert (
            client.post("/auth/login", json={"username": "demo", "password": "demo"}).status_code
            == 401
        )
        assert client.post(
            "/auth/login", json={"username": "tester", "password": "flowtest"}
        ).json() == {"code": 0, "data": {"token": "mock-token", "user_id": "user-001"}}
        assert client.get("/selftest/batch-a/ST-ENG-002/request").status_code == 404


def test_only_explicit_synthetic_header_is_projected_with_duplicate_count(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin)
    private = "synthetic-private-value-must-never-enter-journal"
    response = public.post(
        "/selftest/batch-a/ST-ENG-002/request",
        json={"marker": "header-proof"},
        headers=[
            ("X-Selftest-Precedence", "node"),
            ("Authorization", private),
            ("Cookie", private),
            ("X-Other-Header", private),
        ],
    )
    assert response.status_code == 200, response.text
    journal = admin.get(path + "/journal")
    assert journal.json()["entries"][0]["synthetic_precedence_header"] == {
        "value": "node",
        "count": 1,
    }
    assert private not in journal.text
    duplicate = public.post(
        "/selftest/batch-a/ST-ENG-002/request",
        json={"marker": "header-proof"},
        headers=[("X-Selftest-Precedence", "runtime"), ("x-selftest-precedence", "node")],
    )
    assert duplicate.status_code == 200
    entries = admin.get(path + "/journal").json()["entries"]
    assert entries[1]["synthetic_precedence_header"] == {"value": None, "count": 2}


def test_non_fixture_value_in_synthetic_header_is_never_persisted(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin)
    unexpected = "synthetic-nonfixture-value-never-persisted"
    assert (
        public.post(
            "/selftest/batch-a/ST-ENG-002/request",
            json={"marker": "header-proof"},
            headers={"X-Selftest-Precedence": unexpected},
        ).status_code
        == 200
    )
    journal = admin.get(path + "/journal")
    assert journal.json()["entries"][0]["synthetic_precedence_header"] == {
        "value": None,
        "count": 1,
    }
    assert unexpected not in journal.text


def test_management_projects_only_bounded_begin_end_and_per_namespace_peak(
    fixture_apps: tuple[TestClient, TestClient, FixtureStore],
) -> None:
    public, admin, _store = fixture_apps
    path = setup_fixture(admin, scenario="ST-PEAK", delay_ms=150)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(lambda _: public.get("/selftest/batch-a/ST-PEAK/request"), range(4))
        )
    assert all(response.status_code == 200 for response in responses)
    journal = admin.get(path + "/journal").json()
    metrics = journal["metrics"]
    assert metrics["complete"] and metrics["active_count"] == 0
    assert metrics["peak_concurrency"] == 4 and metrics["completed_count"] == 4
    assert metrics["failed_count"] == metrics["cancelled_count"] == 0
    assert {event["sequence"] for event in metrics["events"]} == {1, 2, 3, 4}
    assert len({event["request_id"] for event in metrics["events"]}) == 4
    assert all(event["started_at"] <= event["completed_at"] for event in metrics["events"])
    assert public.get(path + "/journal").status_code == 404


def test_late_finish_cannot_change_an_expired_reconfigured_namespace(tmp_path: Path) -> None:
    clock = [1.0]
    store = FixtureStore(tmp_path / "events.sqlite3", clock=lambda: clock[0])
    store.start_epoch()
    config = FixtureConfiguration.model_validate(configuration(ttl_seconds=1))
    store.configure("batch", "scenario", config)
    old = store.record(
        "batch",
        "scenario",
        SyntheticRequest(),
        method="GET",
        authorization_present=False,
        cookie_present=False,
    )
    clock[0] = 3.0
    store.configure(
        "batch", "scenario", config.model_copy(update={"nonce": "fresh-synthetic-nonce-0002"})
    )
    current = store.record(
        "batch",
        "scenario",
        SyntheticRequest(),
        method="GET",
        authorization_present=False,
        cookie_present=False,
    )
    assert store.finish(old.request_id, "completed") is False
    assert store.finish(current.request_id, "completed") is True
    assert store.finish(current.request_id, "cancelled") is False
    journal = store.journal("batch", "scenario")
    assert journal.nonce == "fresh-synthetic-nonce-0002" and journal.request_count == 1
    assert journal.metrics.complete and journal.metrics.peak_concurrency == 1
    assert journal.metrics.events[0].request_id == current.request_id
