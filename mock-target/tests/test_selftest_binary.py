"""Fixed binary bytes obey the same namespace journal, expiry and request budget."""
# ruff: noqa: S101, S105

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.selftest import create_business_app, observer_app
from app.selftest_journal import FixtureStore


def test_binary_download_is_exact_and_never_masquerades_as_json(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path / "journal.sqlite3")
    store.start_epoch()
    token = "binary-fixture-observer-token-0001"
    path = "/selftest/batches/binary-batch/scenarios/file"
    with (
        TestClient(observer_app(store, token)) as observer,
        TestClient(create_business_app(store)) as target,
    ):
        observer.headers["Authorization"] = f"Bearer {token}"
        assert (
            observer.put(
                path, json={"nonce": "binary-fixture-nonce", "fixture_digest": "a" * 64}
            ).status_code
            == 204
        )
        response = target.get("/binary-batch/file/download?marker=engine-golden")
        assert response.status_code == 200
        assert response.content == b"flowtest-download"
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"] == 'attachment; filename="flowtest.bin"'
        journal = observer.get(path + "/journal").json()
        assert journal["request_count"] == 1
        assert journal["metrics"]["completed_count"] == 1
        entry = journal["entries"][0]
        assert entry["response_body"] is None
        assert entry["binary_response"] == {
            "size_bytes": 17,
            "sha256": hashlib.sha256(b"flowtest-download").hexdigest(),
            "content_type": "application/octet-stream",
            "filename": "flowtest.bin",
        }
        assert target.post("/binary-batch/file/request", json={"value": False}).status_code == 200
        json_entry = observer.get(path + "/journal").json()["entries"][1]
        assert json_entry["response_body"]["value"] is False
        assert "binary_response" not in json_entry


def test_binary_download_cannot_bypass_namespace_budget_or_expiry(
    tmp_path: Path,
) -> None:
    now = [1000.0]
    store = FixtureStore(tmp_path / "journal.sqlite3", clock=lambda: now[0])
    store.start_epoch()
    token = "binary-fixture-observer-token-0001"
    with (
        TestClient(observer_app(store, token)) as observer,
        TestClient(create_business_app(store)) as target,
    ):
        observer.headers["Authorization"] = f"Bearer {token}"
        path = "/selftest/batches/binary-batch/scenarios/file"
        config = {
            "nonce": "binary-fixture-nonce",
            "fixture_digest": "a" * 64,
            "ttl_seconds": 1,
            "budget_scope": {
                "parent_batch_key": "binary-batch",
                "nonce": "binary-fixture-nonce",
                "limit": 1,
                "expires_at": 1001.0,
            },
        }
        assert observer.put(path, json=config).status_code == 204
        assert target.get("/binary-batch/file/download").status_code == 200
        exhausted = target.get("/binary-batch/file/download")
        assert exhausted.status_code == 429
        assert exhausted.json()["error"]["trace_id"]
        now[0] += 2
        expired = target.get("/binary-batch/file/download")
        assert expired.status_code in {410, 429}
        assert expired.json()["error"]["trace_id"]
