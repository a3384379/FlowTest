"""Owned cleanup behavior without bootstrap, containers, or external network requests."""

import asyncio
import inspect
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest import run
from scripts.selftest.bootstrap import BootstrapResult, Credentials, Installation
from scripts.selftest.cleanup import CleanupReceipt, RoundCleanup
from scripts.selftest.contracts import ResourceAbsenceEvidence
from scripts.selftest.io import HarnessError, PublicAPI


def installation() -> Installation:
    return Installation(
        binding_nonce="binding-nonce",
        organization_id=uuid4(),
        project_id=uuid4(),
        reviewer_id=uuid4(),
        reviewer_email="reviewer@example.com",
        mcp_account_id=uuid4(),
        target_project_id=uuid4(),
        target_organization_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.com",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
    )


async def test_mcp_configuration_failure_cleans_only_registered_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = installation()
    credentials = Credentials(*("private-test-token" for _ in range(7)))
    monkeypatch.setattr(
        run, "bootstrap", AsyncMock(return_value=BootstrapResult(installed, credentials))
    )
    monkeypatch.setattr(
        run,
        "private_environment",
        lambda directory: {"FLOWTEST_SELFTEST_OBSERVER_TOKEN": "private-observer"},
    )
    calls: list[tuple[str, str]] = []
    configuration: dict = {}
    removed = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal removed
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            configuration.update(json.loads(request.content))
        if "after_sequence" in request.url.query.decode():
            if removed:
                return httpx.Response(404, json={"error": {"code": "FIXTURE_NOT_FOUND"}})
            parts = request.url.path.split("/")
            return httpx.Response(
                200,
                json={
                    "batch_key": parts[3],
                    "scenario_id": parts[5],
                    "nonce": configuration["nonce"],
                    "fixture_digest": configuration["fixture_digest"],
                    "fixture_epoch": "epoch",
                    "registration_epoch": "epoch",
                    "entries": [],
                    "metrics": {"complete": True, "active_count": 0},
                },
            )
        if request.method == "DELETE":
            removed = True
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"request_count": 1, "truncated": False, "expired": False},
            )
        return httpx.Response(204)

    def api(base_url: str, *arguments: str, **keywords: str) -> PublicAPI:
        return PublicAPI(base_url, *arguments, **keywords, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(run, "PublicAPI", api)
    binding = SimpleNamespace(
        runner_url="http://runner",
        target_url="http://target",
        observer_url="http://observer",
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image_digest="sha256:" + "b" * 64,
    )
    with pytest.raises(HarnessError, match="SELFTEST_FIXTURE_NOT_EMPTY"):
        await run.run_round(binding, tmp_path, tmp_path / "round")
    registered = [path for method, path in calls if method == "PUT"]
    deleted = [path for method, path in calls if method == "DELETE"]
    assert deleted == registered
    assert len(deleted) == 1


@dataclass(frozen=True)
class Identities:
    project: UUID
    plan: UUID
    run: UUID
    case: UUID
    item: UUID
    execution: UUID
    target_project: UUID
    target_user: UUID


@pytest.fixture
def ids() -> Identities:
    return Identities(*(uuid4() for _ in range(8)))


def plan(ids: Identities, status: str = "passed", item_status: str | None = None) -> dict:
    return {
        "run_id": str(ids.run),
        "project_id": str(ids.project),
        "test_plan_id": str(ids.plan),
        "status": status,
        "truncated": False,
        "has_more": False,
        "total": 1,
        "items": [
            {
                "id": str(ids.item),
                "target_id": str(ids.case),
                "status": item_status or status,
                "attempts": 1,
                "execution_id": str(ids.execution),
                "execution_ids": [str(ids.execution)],
                "attempts_complete": True,
            }
        ],
    }


def execution(ids: Identities, status: str = "passed") -> dict:
    return {
        "execution_id": str(ids.execution),
        "project_id": str(ids.project),
        "source_plan_run_item_id": str(ids.item),
        "status": status,
    }


def environment(ids: Identities, **updates: object) -> dict:
    return {
        "id": str(uuid4()),
        "project_id": str(ids.target_project),
        "name": "batch-created",
        "created_by_id": str(ids.target_user),
        "created_at": datetime.now(UTC).isoformat(),
        **updates,
    }


def cleanup(tmp_path: Path, ids: Identities, respond) -> RoundCleanup:
    removed = False

    async def fixture_transport(request: httpx.Request) -> httpx.Response:
        nonlocal removed
        if request.url.host == "observer" and request.method == "GET":
            if removed:
                return httpx.Response(404, json={"error": {"code": "FIXTURE_NOT_FOUND"}})
            return httpx.Response(
                200,
                json={
                    "batch_key": "batch",
                    "scenario_id": "scenario",
                    "nonce": "synthetic-cleanup-nonce-001",
                    "fixture_digest": "a" * 64,
                    "fixture_epoch": "epoch",
                    "registration_epoch": "epoch",
                    "entries": [],
                    "metrics": {"complete": True, "active_count": 0},
                },
            )
        result = respond(request)
        response = await result if inspect.isawaitable(result) else result
        if (
            request.url.host == "observer"
            and request.method == "DELETE"
            and response.status_code == 204
        ):
            condition = json.loads(request.content)
            assert condition == {
                "expected_nonce": "synthetic-cleanup-nonce-001",
                "expected_fixture_epoch": "epoch",
                "expected_registration_epoch": "epoch",
            }
            removed = True
        return response

    transport = httpx.MockTransport(fixture_transport)
    return RoundCleanup(
        batch_key="batch",
        nonce="synthetic-cleanup-nonce-001",
        fixture_digest="a" * 64,
        project_id=ids.project,
        output_dir=tmp_path,
        writer=PublicAPI("http://writer", "writer-private", transport=transport),
        reader=PublicAPI("http://reader", "reader-private", transport=transport),
        observer=PublicAPI(
            "http://observer", "observer-private", api_prefix="", transport=transport
        ),
        target_reader=PublicAPI(
            "http://target-reader", "target-viewer-private", transport=transport
        ),
        target_writer=PublicAPI(
            "http://target-writer", "target-admin-private", transport=transport
        ),
    )


def started(subject: RoundCleanup, ids: Identities, observed: dict | None = None) -> None:
    subject.register_fixture("scenario")
    subject.arm_plan(ids.plan, (ids.case,))
    subject.started_plan(ids.run)
    if observed is not None:
        subject.plan.observe(observed)


async def test_cancel_waits_for_parent_item_and_actual_execution_before_deleting(
    tmp_path: Path, ids: Identities, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        calls.append((request.method, request.url.path))
        if "test-plan-runs" in request.url.path and request.method == "GET":
            reads += 1
            return httpx.Response(
                200,
                json=plan(
                    ids,
                    "running" if reads == 1 else "cancelled",
                    "running" if reads < 3 else "cancelled",
                ),
            )
        if "workflow-executions" in request.url.path:
            return httpx.Response(200, json=execution(ids, "cancelled"))
        return httpx.Response(204)

    monkeypatch.setattr("scripts.selftest.cleanup.asyncio.sleep", AsyncMock())
    subject = cleanup(tmp_path, ids, respond)
    started(subject, ids)
    receipt = await subject.finish()
    assert receipt.status == "completed"
    assert receipt.plan.cancel_requested
    assert [method for method, path in calls if path.endswith("/cancel")] == ["POST"]
    assert calls[-2][1].endswith(f"/{ids.execution}/evidence")
    assert calls[-1] == ("DELETE", "/selftest/batches/batch/scenarios/scenario")
    assert await subject.finish() == receipt
    assert len([method for method, path in calls if method == "DELETE"]) == 1


@pytest.mark.parametrize("mode", ["unknown_launch", "running", "parent_only", "wrong_identity"])
async def test_unconfirmed_stop_never_removes_fixture(
    tmp_path: Path, ids: Identities, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        value = plan(ids, "passed" if mode == "parent_only" else "running", "running")
        if mode == "wrong_identity":
            value["run_id"] = str(uuid4())
        return httpx.Response(200, json=value)

    monkeypatch.setattr("scripts.selftest.cleanup.asyncio.sleep", AsyncMock())
    subject = cleanup(tmp_path, ids, respond)
    subject.register_fixture("scenario")
    subject.arm_plan(ids.plan, (ids.case,))
    if mode != "unknown_launch":
        subject.started_plan(ids.run)
    receipt = await subject.finish()
    assert receipt.status == "needs_review"
    assert receipt.fixtures[0].status == "pending"
    assert not any(method == "DELETE" for method, path in calls)
    if mode == "unknown_launch":
        assert calls == []
        assert receipt.plan.reason_codes == ("SELFTEST_CLEANUP_LAUNCH_RESULT_UNKNOWN",)


async def test_lost_cancel_response_uses_reads_without_second_mutation(
    tmp_path: Path, ids: Identities
) -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("private unknown cancel response", request=request)
        if "test-plan-runs" in request.url.path:
            return httpx.Response(200, json=plan(ids, "cancelled"))
        if "workflow-executions" in request.url.path:
            return httpx.Response(200, json=execution(ids, "cancelled"))
        return httpx.Response(204)

    subject = cleanup(tmp_path, ids, respond)
    started(subject, ids, plan(ids, "running"))
    assert (await subject.finish()).status == "completed"
    assert calls.count("POST") == 1


async def test_fixture_delete_unknown_is_failed_and_never_repeated(
    tmp_path: Path, ids: Identities
) -> None:
    deletes = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal deletes
        deletes += 1
        raise httpx.ReadTimeout("private observer token or response", request=request)

    subject = cleanup(tmp_path, ids, respond)
    subject.register_fixture("scenario")
    receipt = await subject.finish()
    assert receipt.status == "failed"
    assert receipt.fixtures[0].status == "failed"
    assert receipt.fixtures[0].delete_requested
    assert await subject.finish() == receipt
    assert deletes == 1
    assert "private" not in (tmp_path / "cleanup.json").read_text()


async def test_resource_recovery_registers_exact_id_and_rechecks_before_admin_delete(
    tmp_path: Path, ids: Identities
) -> None:
    rows: list[dict] = []
    calls: list[tuple[str, str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.host, request.url.path))
        if request.url.host == "target-reader":
            assert request.headers["Authorization"] == "Bearer target-viewer-private"
            return httpx.Response(200, json=rows)
        if request.url.host == "target-writer":
            assert request.headers["Authorization"] == "Bearer target-admin-private"
            frozen = CleanupReceipt.model_validate_json((tmp_path / "cleanup.json").read_text())
            assert frozen.resource is not None and frozen.resource.delete_requested
            assert frozen.resource.registered_resource.id == UUID(rows[0]["id"])
            rows.clear()
            return httpx.Response(204)
        if request.url.host == "reader":
            return httpx.Response(200, json=execution(ids))
        return httpx.Response(204)

    subject = cleanup(tmp_path, ids, respond)
    await subject.arm_lifecycle(
        project_id=ids.target_project,
        creator_id=ids.target_user,
        names=("batch-created", "batch-updated"),
    )
    owned = environment(ids)
    rows.append(owned)
    started(subject, ids, plan(ids))
    receipt = await subject.finish()
    assert receipt.status == "completed"
    assert receipt.resource.registered_resource.id == UUID(owned["id"])
    assert [path for method, host, path in calls if host == "target-writer"] == [
        f"/api/v1/projects/{ids.target_project}/environments/{owned['id']}"
    ]
    assert calls[-1] == ("DELETE", "observer", "/selftest/batches/batch/scenarios/scenario")


@pytest.mark.parametrize(
    "mutation", ["creator", "old", "naive", "duplicate", "changed", "delete_unknown"]
)
async def test_unproven_resource_or_unknown_delete_stays_needs_review(
    tmp_path: Path, ids: Identities, mutation: str
) -> None:
    rows: list[dict] = []
    deletes: list[str] = []
    target_reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal target_reads
        if request.url.host == "target-reader":
            target_reads += 1
            if mutation == "changed" and target_reads == 3:
                rows[0]["name"] = "unrelated-renamed-resource"
            return httpx.Response(200, json=rows)
        if request.url.host == "target-writer":
            deletes.append(request.url.path)
            raise httpx.ReadTimeout("private target admin payload", request=request)
        if request.url.host == "reader":
            return httpx.Response(200, json=execution(ids))
        return httpx.Response(204)

    subject = cleanup(tmp_path, ids, respond)
    await subject.arm_lifecycle(
        project_id=ids.target_project,
        creator_id=ids.target_user,
        names=("batch-created", "batch-updated"),
    )
    updates = {}
    if mutation == "creator":
        updates["created_by_id"] = str(uuid4())
    if mutation == "old":
        updates["created_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    if mutation == "naive":
        updates["created_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
    rows.append(environment(ids, **updates))
    if mutation == "duplicate":
        rows.append(environment(ids, name="batch-updated"))
    started(subject, ids, plan(ids))
    receipt = await subject.finish()
    assert receipt.status == "needs_review"
    assert receipt.resource.status == "needs_review"
    assert receipt.fixtures[0].status == "completed"
    assert await subject.finish() == receipt
    assert len(deletes) == (1 if mutation == "delete_unknown" else 0)
    assert "private" not in (tmp_path / "cleanup.json").read_text()


async def test_confirmed_native_resource_absence_does_not_repeat_cleanup(
    tmp_path: Path, ids: Identities
) -> None:
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.host))
        if request.url.host == "target-reader":
            return httpx.Response(200, json=[])
        if request.url.host == "reader":
            return httpx.Response(200, json=execution(ids))
        return httpx.Response(204)

    subject = cleanup(tmp_path, ids, respond)
    await subject.arm_lifecycle(
        project_id=ids.target_project,
        creator_id=ids.target_user,
        names=("batch-created", "batch-updated"),
    )
    started(subject, ids, plan(ids))
    subject.observe_absence(
        ResourceAbsenceEvidence(
            project_id=ids.target_project,
            returned_names=(),
            observed_at=datetime.now(UTC),
            complete=True,
        )
    )
    assert (await subject.finish()).status == "completed"
    assert calls == [("GET", "target-reader"), ("GET", "reader"), ("DELETE", "observer")]


async def test_interrupted_fixture_delete_is_recorded_and_not_replayed(
    tmp_path: Path, ids: Identities
) -> None:
    calls = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    subject = cleanup(tmp_path, ids, respond)
    subject.register_fixture("scenario")
    with pytest.raises(asyncio.CancelledError):
        await subject.finish()
    receipt = await subject.finish()
    assert receipt.status == "needs_review"
    assert receipt.fixtures[0].status == "failed"
    assert calls == 1
