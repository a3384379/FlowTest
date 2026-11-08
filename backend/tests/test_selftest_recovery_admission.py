"""Recovery regressions use real product admission; model calls remain absent."""

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

# The trusted scripts are repository modules, outside the backend pytest root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest import product_agent_client
from scripts.selftest.io import HarnessError, PublicAPI, read_json
from scripts.selftest.product_agent_client import keep_lease
from sqlalchemy import func, select
from test_selftest_product_api import ProductContext, _ready
from test_selftest_product_api import observation as observation
from test_selftest_product_api import product as product
from test_selftest_product_sources import _materialized
from test_selftest_retention import owned_storage as owned_storage
from test_tasking_api import tasking_context as tasking_context

from app.core.errors import AppError
from app.main import app
from app.models.self_tests import SelfTestBatch, SelfTestScenarioResult
from app.models.tasking import TestPlan as Plan
from app.models.test_assets import TestSuite as Suite
from app.schemas.self_tests import AgentTaskResponse
from app.services.self_test_assisted import SelfTestAssistedSources


def test_shared_nonce_initialization_publishes_only_one_complete_identity(tmp_path, monkeypatch):
    barrier = Barrier(2)
    original = product_agent_client.secrets.token_hex

    def simultaneous(size):
        value = original(size)
        barrier.wait(timeout=5)
        return value

    monkeypatch.setattr(product_agent_client.secrets, "token_hex", simultaneous)
    identifier = uuid4()
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(product_agent_client.task_nonce, tmp_path, identifier) for _ in range(2)
        ]
        nonces = [item.result(timeout=10) for item in futures]
    persisted = read_json(tmp_path / str(identifier) / "nonce.json")["nonce"]
    assert nonces == [persisted, persisted]
    assert (tmp_path / str(identifier) / "nonce.json").stat().st_mode & 0o077 == 0


def test_existing_incomplete_nonce_is_not_replaced_or_claimed(tmp_path):
    identifier = uuid4()
    path = tmp_path / str(identifier) / "nonce.json"
    path.parent.mkdir()
    path.write_text('{"nonce":')
    with pytest.raises(HarnessError, match="SELFTEST_AGENT_NONCE_INVALID"):
        product_agent_client.task_nonce(tmp_path, identifier)
    assert path.read_text() == '{"nonce":'


def _node(identifier, kind, config=None):
    return {
        "id": identifier,
        "type": kind,
        "name": identifier,
        "position": {"x": 0, "y": 0},
        "config": config or {},
    }


def _assertion_graph():
    return {
        "nodes": [
            _node("start", "start"),
            _node("api", "api", {"api_definition_id": str(uuid4()), "api_version": 1}),
            _node(
                "assert",
                "assert",
                {"source_node_id": "api", "expression": "body.actual", "expected": 1},
            ),
            _node("end", "end"),
        ],
        "edges": [
            {"id": "first", "source": "start", "target": "api"},
            {"id": "second", "source": "api", "target": "assert"},
            {"id": "last", "source": "assert", "target": "end"},
        ],
    }


def test_required_assertion_cannot_be_bypassed_by_new_control_path():
    before = _assertion_graph()
    after = deepcopy(before)
    after["nodes"].insert(
        2,
        _node(
            "guard",
            "condition",
            {"source_node_id": "api", "expression": "body.actual", "expected": 999},
        ),
    )
    after["edges"] = [
        before["edges"][0],
        {"id": "second", "source": "api", "target": "guard"},
        {"id": "true", "source": "guard", "target": "assert", "condition": "true"},
        {"id": "false", "source": "guard", "target": "end", "condition": "false"},
        before["edges"][-1],
    ]
    source = SimpleNamespace(oracle_bindings=(SimpleNamespace(node_id="assert"),))
    with pytest.raises(AppError) as caught:
        SelfTestAssistedSources._required_assertions(source, before, after)
    assert caught.value.code == "SELFTEST_ASSISTED_REQUIRED_ORACLE_CHANGED"


def test_required_assertion_allows_rename_position_and_edge_identity_changes():
    before = _assertion_graph()
    after = deepcopy(before)
    for node in after["nodes"]:
        node["name"] = "名称调整"
        node["position"] = {"x": 200, "y": 400}
    for edge in after["edges"]:
        edge["id"] += "-renamed"
    source = SimpleNamespace(oracle_bindings=(SimpleNamespace(node_id="assert"),))
    SelfTestAssistedSources._required_assertions(source, before, after)


async def test_staged_materialization_waits_for_manifest_ack_and_reuses_assets(
    product: ProductContext, owned_storage
):
    batch, payload = await _materialized(product)
    path = product.agent + f"/runs/{batch['id']}/materialized"
    staged = await product.post(path, payload, machine="h")
    assert staged["phase"] == "awaiting_review" and staged["generation_stage"] == "publishing"
    assert not staged["actions"]["can_execute"]
    assert staged["resource_snapshot"] and staged["plan_run_ids"] == []
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert model and model.lease_hash
        initial = (
            await session.scalar(select(func.count()).select_from(Suite)),
            await session.scalar(select(func.count()).select_from(Plan)),
        )
        attempt = await session.scalar(
            select(SelfTestScenarioResult.generation_attempt).where(
                SelfTestScenarioResult.batch_id == model.id
            )
        )
    replay = await product.post(path, payload, machine="h")
    assert replay["resource_snapshot"] == staged["resource_snapshot"]
    assert replay["resource_digest"] == staged["resource_digest"]
    finalized = await product.post(
        path,
        {
            **payload,
            "stage": "finalize",
            "observer_manifest_digest": "a" * 64,
            "observer_selection_digest": "b" * 64,
        },
        machine="h",
    )
    assert finalized["phase"] == "ready"
    user_view = await product.get(product.root + f"/runs/{batch['id']}")
    assert user_view["actions"]["can_execute"]
    replay = await product.post(
        path,
        {
            **payload,
            "stage": "finalize",
            "observer_manifest_digest": "a" * 64,
            "observer_selection_digest": "b" * 64,
        },
        machine="h",
    )
    assert replay["resource_snapshot"] == staged["resource_snapshot"]
    async with product.native.session_maker() as session:
        assert initial == (
            await session.scalar(select(func.count()).select_from(Suite)),
            await session.scalar(select(func.count()).select_from(Plan)),
        )
        assert attempt == await session.scalar(
            select(SelfTestScenarioResult.generation_attempt).where(
                SelfTestScenarioResult.batch_id == UUID(batch["id"])
            )
        )
    conflict = await product.post(
        path,
        {
            **payload,
            "stage": "finalize",
            "observer_manifest_digest": "c" * 64,
            "observer_selection_digest": "b" * 64,
        },
        machine="h",
        status=409,
    )
    assert conflict["error"]["code"] == "SELFTEST_MATERIALIZED_RECEIPT_CONFLICT"


async def test_actual_h_reports_acknowledged_assets_when_late_plan_creation_fails(
    product: ProductContext, tmp_path
):
    import httpx
    from scripts.selftest.fixed_baseline import load_core_pack
    from scripts.selftest.io import PublicAPI
    from scripts.selftest.product_fixed import install_task

    from app.main import app

    class LatePlanFailure(httpx.AsyncBaseTransport):
        def __init__(self):
            self.asgi = httpx.ASGITransport(app=app)

        async def handle_async_request(self, request):
            if request.method == "POST" and request.url.path.endswith("/test-plans"):
                return httpx.Response(503, json={"error": {"code": "SYNTHETIC_PLAN_UNAVAILABLE"}})
            return await self.asgi.handle_async_request(request)

        async def aclose(self):
            await self.asgi.aclose()

    captured = []

    def failure(request):
        import json

        assert request.url.path.endswith("/failure")
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "blocked"})

    pack = load_core_pack()
    task = SimpleNamespace(
        task_id=uuid4(),
        project_id=product.project_id,
        nonce="n" * 64,
        lease_token="l" * 64,
        environment_fingerprint="e" * 64,
        builds=product.binding.builds,
        installation=SimpleNamespace(template_id="core-v1", pack_digest=pack.digest),
    )
    mapping = product.mapping
    installation = SimpleNamespace(
        fixture_environment_id=mapping.environment_id,
        fixture_service_id=mapping.fixture_service_id,
        target_environment_id=mapping.target_environment_id,
        target_service_id=mapping.target_service_id,
        target_project_id=mapping.target_project_id,
        target_organization_id=mapping.target_organization_id,
        target_user_id=mapping.target_user_id,
        binding_nonce="owned-test-binding",
    )
    machine = PublicAPI("http://machine", transport=httpx.MockTransport(failure))
    writer = PublicAPI(
        "http://test",
        product.headers["Authorization"].removeprefix("Bearer "),
        transport=LatePlanFailure(),
    )
    try:
        with pytest.raises(HarnessError, match="SYNTHETIC_PLAN_UNAVAILABLE"):
            await install_task(
                machine, writer, task=task, installation=installation, directory=tmp_path
            )
    finally:
        await machine.close()
        await writer.close()
    assert len(captured) == 1
    assert len(captured[0]["mapping"]["assets"]) == len(pack.manifest.scenario_ids)
    assert {item["scenario_id"] for item in captured[0]["mapping"]["assets"]} == set(
        pack.manifest.scenario_ids
    )


async def test_lost_stage_and_final_responses_replay_exact_receipts(
    product: ProductContext, owned_storage, tmp_path
):
    from scripts.selftest.io import PublicAPI, write_json
    from scripts.selftest.product_agent_client import (
        finalize_materialization,
        keep_lease,
        stage_materialization,
    )

    from app.main import app
    from app.schemas.self_tests import AgentTaskResponse, BatchResponse, MaterializedReceipt

    batch, payload = await _materialized(product)
    tmp_path = tmp_path / str(batch["id"])
    path = product.agent + f"/runs/{batch['id']}"
    task = AgentTaskResponse.model_validate(
        await product.post(
            path + "/lease", {key: payload[key] for key in ("lease_token", "nonce")}, machine="h"
        )
    )

    class LostCommittedResponse(httpx.AsyncBaseTransport):
        def __init__(self):
            self.asgi = httpx.ASGITransport(app=app)
            self.lost = set()

        async def handle_async_request(self, request):
            response = await self.asgi.handle_async_request(request)
            if request.url.path.endswith("/materialized"):
                stage = json.loads(request.content).get("stage", "stage")
                if stage not in self.lost:
                    self.lost.add(stage)
                    assert response.status_code == 200
                    raise httpx.ReadTimeout("lost committed receipt response", request=request)
            return response

        async def aclose(self):
            await self.asgi.aclose()

    transport = LostCommittedResponse()
    machine = PublicAPI(
        "http://test",
        product.machine("h")["Authorization"].removeprefix("Bearer "),
        transport=transport,
    )
    receipt = MaterializedReceipt.model_validate(payload)
    try:
        with pytest.raises(httpx.ReadTimeout):
            await stage_materialization(machine, task, receipt, tmp_path)
        current = await product.get(product.root + f"/runs/{batch['id']}")
        assert current["phase"] == "awaiting_review" and not current["actions"]["can_execute"]
        staged = await stage_materialization(machine, task, receipt, tmp_path)
        assert staged.resource_snapshot.model_dump(mode="json") == current["resource_snapshot"]
        write_json(tmp_path / "manifest.json", {"synthetic_observer_manifest": str(batch["id"])})
        write_json(tmp_path / "selection.json", current["resource_snapshot"])
        with pytest.raises(httpx.ReadTimeout):
            await finalize_materialization(machine, task, tmp_path)
        current = await product.get(product.root + f"/runs/{batch['id']}")
        assert current["phase"] == "ready" and current["actions"]["can_execute"]
        from scripts.selftest.product_agent import _reconcile_ready

        write_json(tmp_path / "private-lease.json", task)
        assert await _reconcile_ready(
            machine, BatchResponse.model_validate(current), tmp_path.parent
        )
        assert (tmp_path / "materialized-acknowledged.json").is_file()
        assert not await _reconcile_ready(
            machine, BatchResponse.model_validate(current), tmp_path.parent
        )
        ready = await finalize_materialization(machine, task, tmp_path)
        assert ready.resource_snapshot == staged.resource_snapshot
        assert ready.plan_run_ids == () and product.native.queue.test_plan_run_ids == []
        # An already-issued renewal recognizes this exact finalized task and stops.
        soon = task.model_copy(
            update={"lease_expires_at": datetime.now(UTC) + timedelta(seconds=0.1)}
        )
        async with keep_lease(machine, soon):
            await asyncio.sleep(0.2)
    finally:
        await machine.close()
    async with product.native.session_maker() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(Plan).where(Plan.name == f"selftest:{batch['id']}")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Suite)
                .where(Suite.name == f"selftest:{batch['id']}")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(SelfTestScenarioResult.generation_attempt).where(
                    SelfTestScenarioResult.batch_id == UUID(batch["id"])
                )
            )
            == 1
        )


async def test_staged_receipt_cannot_finalize_or_renew_an_expired_lease(
    product: ProductContext, owned_storage
):
    batch, payload = await _materialized(product)
    path = product.agent + f"/runs/{batch['id']}"
    await product.post(path + "/materialized", payload, machine="h")
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(batch["id"]))
        model.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    for suffix, body in (
        ("/materialized", payload),
        ("/lease", {key: payload[key] for key in ("lease_token", "nonce")}),
        (
            "/materialized",
            {
                **payload,
                "stage": "finalize",
                "observer_manifest_digest": "a" * 64,
                "observer_selection_digest": "b" * 64,
            },
        ),
    ):
        error = await product.post(path + suffix, body, machine="h", status=409)
        assert error["error"]["code"] == "SELFTEST_LEASE_EXPIRED"
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert not current["actions"]["can_execute"] and not current["plan_run_ids"]


async def test_assisted_origin_namespace_is_reserved_before_second_task_creation(
    product: ProductContext, owned_storage
):
    from test_selftest_assisted import assisted_contract

    task, before, _ = await assisted_contract(product)
    conflict = await product.post(
        product.root + f"/installations/{before['installation_id']}/generation-batches",
        {
            "scenario_ids": ["ST-MCP-026"],
            "verification_scope": "diagnostic_subset",
            "generation_mode": "host_llm_mcp",
            "assisted_before_batch_id": before["id"],
        },
        key="conflicting-assisted-origin",
        status=409,
    )
    assert conflict["error"]["code"] == "SELFTEST_ASSISTED_NAMESPACE_BUSY"
    active = await product.get(product.root + f"/runs/{task['task_id']}")
    assert active["phase"] in {"generating", "awaiting_review"}
    assert product.native.queue.test_plan_run_ids == []


@pytest.mark.asyncio
async def test_successful_observer_seal_tolerates_its_terminal_renewal(
    product: ProductContext, observation: tuple[dict, dict]
) -> None:
    batch, receipt = observation
    task = AgentTaskResponse.model_validate(
        await product.post(
            product.agent + f"/runs/{batch['id']}/lease",
            {key: receipt[key] for key in ("lease_token", "nonce")},
            machine="o",
        )
    ).model_copy(update={"lease_expires_at": datetime.now(UTC) + timedelta(seconds=0.3)})
    machine = PublicAPI(
        "http://test",
        product.machine("o")["Authorization"].removeprefix("Bearer "),
        transport=httpx.ASGITransport(app=app),
    )
    try:
        async with keep_lease(machine, task):
            sealed = await product.post(
                f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
                receipt,
                machine="o",
            )
            assert sealed["verdict"] == "passed"
            await asyncio.sleep(0.3)
    finally:
        await machine.close()


@pytest.mark.asyncio
async def test_successful_fixed_preparation_tolerates_its_terminal_renewal(
    product: ProductContext,
) -> None:
    installed = await _ready(product)
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/runs",
        {},
        key="fixed-release-crosscheck",
        status=202,
    )
    task = AgentTaskResponse.model_validate(
        await product.post(
            product.agent + f"/runs/{batch['id']}/claim",
            {"expected_revision": batch["revision"], "nonce": "fixed-crosscheck-" + "4" * 32},
            machine="h",
        )
    ).model_copy(update={"lease_expires_at": datetime.now(UTC) + timedelta(seconds=0.3)})
    machine = PublicAPI(
        "http://test",
        product.machine("h")["Authorization"].removeprefix("Bearer "),
        transport=httpx.ASGITransport(app=app),
    )
    try:
        async with keep_lease(machine, task):
            running = await product.post(
                product.agent + f"/runs/{batch['id']}/prepared",
                {"lease_token": task.lease_token, "nonce": task.nonce},
                machine="h",
                status=202,
            )
            assert running["plan_run_ids"]
            await asyncio.sleep(0.3)
    finally:
        await machine.close()


async def test_cancelled_assisted_task_holds_namespace_until_its_deadline(
    product: ProductContext, owned_storage
):
    from test_selftest_assisted import assisted_contract

    task, before, _ = await assisted_contract(product)
    cancelled = await product.post(product.root + f"/runs/{task['task_id']}/cancel", {})
    assert cancelled["phase"] == "cancelled"
    body = {
        "scenario_ids": ["ST-MCP-026"],
        "verification_scope": "diagnostic_subset",
        "generation_mode": "host_llm_mcp",
        "assisted_before_batch_id": before["id"],
    }
    conflict = await product.post(
        product.root + f"/installations/{before['installation_id']}/generation-batches",
        body,
        key="cancelled-namespace-still-reserved",
        status=409,
    )
    assert conflict["error"]["code"] == "SELFTEST_ASSISTED_NAMESPACE_BUSY"
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(task["task_id"]))
        model.deadline = datetime.now(UTC) - timedelta(seconds=1)
        model.plan_run_ids = [str(uuid4())]
        await session.commit()
    unknown = await product.post(
        product.root + f"/installations/{before['installation_id']}/generation-batches",
        body,
        key="expired-native-unknown-reservation",
        status=409,
    )
    assert unknown["error"]["code"] == "SELFTEST_ASSISTED_NAMESPACE_BUSY"
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(task["task_id"]))
        model.plan_run_ids = []
        await session.commit()
    resumed = await product.post(
        product.root + f"/installations/{before['installation_id']}/generation-batches",
        body,
        key="expired-namespace-no-active-native",
        status=202,
    )
    assert resumed["phase"] == "pending" and resumed["id"] != task["task_id"]
