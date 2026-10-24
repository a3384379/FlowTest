"""Bounded synthetic file and cookie capture never includes arbitrary user values."""
# ruff: noqa: S101, S105

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.selftest import create_business_app, observer_app
from app.selftest_journal import FixtureStore


def test_multipart_records_only_the_frozen_synthetic_file_identity(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path / "journal.sqlite3")
    store.start_epoch()
    token = "s5-observer-synthetic-token-0001"
    with (
        TestClient(observer_app(store, token)) as observer,
        TestClient(create_business_app(store)) as target,
    ):
        observer.headers["Authorization"] = f"Bearer {token}"
        path = "/selftest/batches/s5/scenarios/file"
        assert (
            observer.put(
                path, json={"nonce": "s5-synthetic-nonce", "fixture_digest": "a" * 64}
            ).status_code
            == 204
        )
        response = target.post(
            "/s5/file/upload?marker=s5-file",
            files={"file": ("flowtest.bin", b"flowtest-download", "application/octet-stream")},
        )
        assert response.status_code == 200, response.text
        journal = observer.get(path + "/journal").json()
        assert journal["request_count"] == 1
        entry = journal["entries"][0]
        assert entry["binary_request"]["sha256"] == hashlib.sha256(b"flowtest-download").hexdigest()
        assert entry["binary_request"]["size_bytes"] == 17
        denied = target.post(
            "/s5/file/upload", files={"file": ("private.txt", b"do-not-record-this", "text/plain")}
        )
        assert denied.status_code == 422
        assert observer.get(path + "/journal").json()["request_count"] == 1


def test_cookie_barrier_requires_both_branches_and_journals_only_synthetic_cookie(
    tmp_path: Path,
) -> None:
    store = FixtureStore(tmp_path / "journal.sqlite3")
    store.start_epoch()
    token = "s5-observer-synthetic-token-0001"
    application = create_business_app(store)
    with (
        TestClient(observer_app(store, token)) as observer,
        TestClient(application) as left,
        TestClient(application) as right,
    ):
        observer.headers["Authorization"] = f"Bearer {token}"
        path = "/selftest/batches/s5/scenarios/cookies"
        assert (
            observer.put(
                path, json={"nonce": "s5-synthetic-nonce", "fixture_digest": "a" * 64}
            ).status_code
            == 204
        )
        for client, branch in [(left, "left"), (right, "right")]:
            response = client.get(f"/s5/cookies/cookie/set?branch={branch}")
            assert response.status_code == 200
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [
                workers.submit(client.get, f"/s5/cookies/cookie/barrier?branch={branch}")
                for client, branch in [(left, "left"), (right, "right")]
            ]
            assert [future.result().status_code for future in futures] == [200, 200]
        for client, branch in [(left, "left"), (right, "right")]:
            assert client.get(f"/s5/cookies/cookie/check?branch={branch}").json()["value"] == branch
        journal = observer.get(path + "/journal").json()
        assert journal["request_count"] == 6
        assert journal["metrics"]["peak_concurrency"] == 2
        checks = [
            entry for entry in journal["entries"] if entry["synthetic_cookie"]["stage"] == "check"
        ]
        assert {e["request_body"]["branch"]: e["synthetic_cookie"]["value"] for e in checks} == {
            "left": "left",
            "right": "right",
        }
        assert "flowtest_synthetic_branch" not in str(journal)
