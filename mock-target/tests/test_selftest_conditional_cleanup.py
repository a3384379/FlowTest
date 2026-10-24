"""Conditional DELETE cannot remove another nonce after a real namespace replacement."""
# ruff: noqa: S101, S105

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.selftest import observer_app
from app.selftest_contracts import SyntheticRequest
from app.selftest_journal import FixtureStore

TOKEN = "owned-conditional-management-token"


@pytest.mark.parametrize("same_nonce", [False, True])
def test_real_expiry_recreation_between_metadata_get_and_delete_preserves_foreign_namespace(
    tmp_path: Path,
    same_nonce: bool,
) -> None:
    clock = [1000.0]
    store = FixtureStore(tmp_path / "journal.sqlite3", clock=lambda: clock[0])
    store.start_epoch()
    with TestClient(observer_app(store, TOKEN)) as admin:
        admin.headers["Authorization"] = f"Bearer {TOKEN}"
        path = "/selftest/batches/batch-owned/scenarios/scenario"
        original = {
            "nonce": "original-owned-nonce-001",
            "fixture_digest": "a" * 64,
            "ttl_seconds": 1,
        }
        assert admin.put(path, json=original).status_code == 204
        before = admin.get(path + "/journal").json()
        clock[0] += 2
        replacement = {
            **original,
            "nonce": original["nonce"] if same_nonce else "foreign-recreated-nonce-001",
        }
        assert admin.put(path, json=replacement).status_code == 204
        response = admin.request(
            "DELETE",
            path,
            json={
                "expected_nonce": before["nonce"],
                "expected_fixture_epoch": before["fixture_epoch"],
                "expected_registration_epoch": before["registration_epoch"],
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "FIXTURE_DELETE_PRECONDITION_MISMATCH"
        assert response.json()["error"]["trace_id"]
        assert admin.get(path + "/journal").json()["nonce"] == replacement["nonce"]


@pytest.mark.parametrize("mutation", ["fixture_epoch", "registration_epoch", "partial", "active"])
def test_delete_conditions_are_complete_atomic_and_quiescent(tmp_path: Path, mutation: str) -> None:
    store = FixtureStore(tmp_path / "journal.sqlite3")
    store.start_epoch()
    with TestClient(observer_app(store, TOKEN)) as admin:
        admin.headers["Authorization"] = f"Bearer {TOKEN}"
        path = "/selftest/batches/batch-owned/scenarios/scenario"
        assert (
            admin.put(
                path, json={"nonce": "original-owned-nonce-001", "fixture_digest": "a" * 64}
            ).status_code
            == 204
        )
        before = admin.get(path + "/journal").json()
        conditions = {
            "expected_nonce": before["nonce"],
            "expected_fixture_epoch": before["fixture_epoch"],
            "expected_registration_epoch": before["registration_epoch"],
        }
        reply = None
        if mutation == "partial":
            conditions.pop("expected_registration_epoch")
        elif mutation == "active":
            reply = store.record(
                "batch-owned",
                "scenario",
                SyntheticRequest(),
                method="POST",
                operation="request",
                authorization_present=False,
                cookie_present=False,
            )
        else:
            conditions["expected_" + mutation] = "changed"
        response = admin.request("DELETE", path, json=conditions)
        assert response.status_code == (422 if mutation == "partial" else 409), response.text
        assert response.json()["error"]["trace_id"]
        assert admin.get(path + "/journal").status_code == 200
        if reply is not None:
            store.finish(reply.request_id, "completed")
        assert (
            admin.request(
                "DELETE",
                path,
                json={
                    "expected_nonce": before["nonce"],
                    "expected_fixture_epoch": before["fixture_epoch"],
                    "expected_registration_epoch": before["registration_epoch"],
                },
            ).status_code
            == 204
        )
        assert admin.get(path + "/journal").status_code == 404
