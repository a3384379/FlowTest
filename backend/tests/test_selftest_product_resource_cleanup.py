"""Public native cancellation and B environment recovery share the exact owned batch."""

import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from test_selftest_fixed_baseline import _fixture_apps
from test_selftest_host_assisted import fixture as assisted_fixture
from test_selftest_product_api import ProductContext, _ready
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.core.self_tests import get_self_test_settings
from app.main import app
from app.schemas.self_tests import AgentTaskResponse, BatchResponse, PublishedAsset

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    objects_value,
    read_json,
    write_json,
)
from scripts.selftest.product_resource_cleanup import arm_owned_lifecycle, lifecycle_identity
from scripts.selftest.product_watchdog import run_expired_watchdogs


@dataclass
class ResourceWorld:
    product: ProductContext
    task: AgentTaskResponse
    directory: Path
    api: PublicAPI
    observer: PublicAPI
    machine: PublicAPI

    @property
    def target_root(self) -> str:
        return f"/projects/{self.task.installation.mapping.target_project_id}/environments"

    async def create(self, name: str) -> dict:
        return await self.api.object(
            "POST",
            self.target_root,
            {"name": name, "base_url": "http://synthetic.example", "classification": "test"},
        )

    async def cancel(self) -> BatchResponse:
        return BatchResponse.model_validate(
            await self.product.post(self.product.root + f"/runs/{self.task.batch.id}/cancel", {})
        )

    async def prepare(self) -> None:
        await self.product.post(
            self.product.agent + f"/runs/{self.task.batch.id}/prepared",
            {"lease_token": self.task.lease_token, "nonce": self.task.nonce},
            machine="h",
            status=202,
        )

    async def cleanup(self, batch: BatchResponse, target: PublicAPI | None = None) -> dict:
        await run_expired_watchdogs(
            self.machine,
            (batch,),
            self.directory.parent,
            writer=self.api,
            observer=self.observer,
            target_cleanup=target or self.api,
        )
        return read_json(self.directory / "namespace-cleanup.json")


@pytest.fixture
async def resource_world(product: ProductContext, tmp_path: Path) -> AsyncIterator[ResourceWorld]:
    target = await product.post("/api/v1/projects", {"name": "真实独立回收项目"}, status=201)
    user = await product.get("/api/v1/auth/me")
    product.binding = product.binding.model_copy(
        update={
            "target_project_id": UUID(target["id"]),
            "target_organization_id": UUID(target["organization_id"]),
            "target_user_id": UUID(user["id"]),
            "builds": product.binding.builds.model_copy(update={"fixture": "f" * 64}),
        }
    )
    base = product.config.extra_templates[0]
    scenario = base.scenarios[0].model_copy(
        update={"scenario_id": "ST-MCP-023", "variant_key": "owned_resource"}
    )
    template = base.model_copy(update={"id": "resource-test-v1", "scenarios": (scenario,)})
    product.config = product.config.model_copy(
        update={
            "bindings": (product.binding,),
            "extra_templates": (*product.config.extra_templates, template),
        }
    )
    app.dependency_overrides[get_self_test_settings] = lambda: product.config
    asset = product.mapping.assets[0]
    case_root = f"/api/v1/projects/{product.project_id}/test-cases"
    case = await product.post(
        case_root,
        {
            "name": "真实回收测试固定用例",
            "definition": {
                "workflow_id": str(asset.workflow.id),
                "workflow_version": asset.workflow.version,
                "environment_id": str(product.mapping.target_environment_id),
            },
        },
        status=201,
    )
    version = await product.post(case_root + f"/{case['id']}/versions", {})
    product.mapping = product.mapping.model_copy(
        update={
            "target_project_id": product.binding.target_project_id,
            "target_organization_id": product.binding.target_organization_id,
            "target_user_id": product.binding.target_user_id,
            "target_build_digest": product.binding.builds.target,
            "assets": (
                asset.model_copy(
                    update={
                        "scenario_id": "ST-MCP-023",
                        "variant_key": "owned_resource",
                        "case": PublishedAsset(
                            id=UUID(case["id"]), version=1, fingerprint=version["fingerprint"]
                        ),
                    }
                ),
            ),
        }
    )
    installed = await _ready(product, template.id)
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/runs",
        {},
        key="owned-resource",
        status=202,
    )
    task = AgentTaskResponse.model_validate(
        await product.post(
            product.agent + f"/runs/{batch['id']}/claim",
            {"expected_revision": batch["revision"], "nonce": "resource-owned-" + "1" * 32},
            machine="h",
        )
    )
    directory = tmp_path / str(task.batch.id)
    write_json(directory / "private-lease.json", task)
    _, observer_app = _fixture_apps(tmp_path)
    api = PublicAPI(
        "http://test",
        product.headers["Authorization"].removeprefix("Bearer "),
        transport=httpx.ASGITransport(app=app),
    )
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=observer_app),
    )
    machine = PublicAPI(
        "http://test",
        product.machine("h")["Authorization"].removeprefix("Bearer "),
        transport=httpx.ASGITransport(app=app),
    )
    try:
        yield ResourceWorld(product, task, directory, api, observer, machine)
    finally:
        await api.close()
        await observer.close()
        await machine.close()


async def test_cancelled_native_run_recovers_prearmed_b_resource_and_keeps_product_blocked(
    resource_world: ResourceWorld,
) -> None:
    world = resource_world
    await arm_owned_lifecycle(world.task, world.api, world.directory)
    before = (world.directory / "lifecycle-arm.json").read_bytes()
    await arm_owned_lifecycle(world.task, world.api, world.directory)
    assert (world.directory / "lifecycle-arm.json").read_bytes() == before
    await world.prepare()
    key = world.task.batch.batch_key
    created = await world.create(key + "-created")
    foreign = await world.create("another-unrelated-environment")
    cancelled = await world.cancel()
    assert cancelled.plan_run_ids
    receipt = await world.cleanup(cancelled)
    assert receipt["status"] == "completed" and receipt["admitted_requests"] <= 100
    remaining = await world.api.request("GET", world.target_root)
    assert created["id"] not in {item["id"] for item in remaining}
    assert foreign["id"] in {item["id"] for item in remaining}
    state = read_json(world.directory / "lifecycle-cleanup.json")
    assert state["registered_resource"]["id"] == created["id"] and state["status"] == "completed"
    current = await world.product.get(world.product.root + f"/runs/{cancelled.id}")
    assert (
        current["phase"] == "cancelled"
        and current["verdict"] == "blocked"
        and current["sealed_at"] is None
        and current["cleanup_status"] != "completed"
    )


@pytest.mark.parametrize("sent", [True, False])
async def test_unknown_b_delete_is_not_replayed_and_old_failure_receipt_is_immutable(
    resource_world: ResourceWorld, sent: bool
) -> None:
    world = resource_world
    await arm_owned_lifecycle(world.task, world.api, world.directory)
    await world.prepare()
    created = await world.create(world.task.batch.batch_key + "-updated")
    cancelled = await world.cancel()
    deletes = 0

    class LostDelete(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal deletes
            transport = httpx.ASGITransport(app=app)
            if request.method == "DELETE":
                deletes += 1
                if sent:
                    await transport.handle_async_request(request)
                raise httpx.ReadTimeout("unknown owned B deletion", request=request)
            return await transport.handle_async_request(request)

    target = PublicAPI(
        "http://test",
        world.product.headers["Authorization"].removeprefix("Bearer "),
        transport=LostDelete(),
    )
    try:
        first = await world.cleanup(cancelled, target)
        assert first["status"] == "needs_review" and deletes == 1
        immutable = (world.directory / "lifecycle-cleanup-attempt-1.json").read_bytes()
        for _ in range(4):
            last = await world.cleanup(cancelled, target)
        assert (
            deletes == 1
            and (world.directory / "lifecycle-cleanup-attempt-1.json").read_bytes() == immutable
        )
        assert last["status"] == ("completed" if sent else "needs_review")
        if not sent:
            assert (
                last["attempts"] == 3
                and "SELFTEST_NAMESPACE_RECOVERY_LIMIT" in last["reason_codes"]
            )
        remaining = await world.api.request("GET", world.target_root)
        assert (created["id"] in {item["id"] for item in remaining}) is not sent
    finally:
        await target.close()


async def test_existing_names_missing_authority_and_missing_arm_never_delete(
    resource_world: ResourceWorld,
) -> None:
    world = resource_world
    with pytest.raises(HarnessError, match="CLEANUP_IDENTITY_REQUIRED"):
        await arm_owned_lifecycle(world.task, None, world.directory)
    await world.create(world.task.batch.batch_key + "-created")
    with pytest.raises(HarnessError, match="NAMESPACE_ALREADY_EXISTS"):
        await arm_owned_lifecycle(world.task, world.api, world.directory)
    assert not (world.directory / "lifecycle-arm.json").exists()
    await world.prepare()
    cancelled = await world.cancel()
    receipt = await world.cleanup(cancelled)
    assert receipt["status"] == "needs_review"
    assert "SELFTEST_RESOURCE_ARM_PRIVATE_STATE_MISSING" in receipt["reason_codes"]
    assert len(await world.api.request("GET", world.target_root)) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "creator",
        "old_time",
        "naive_time",
        "project",
        "duplicate",
        "truncated",
        "renamed",
        "replaced",
    ],
)
async def test_changed_or_incomplete_b_metadata_never_authorizes_deletion(
    resource_world: ResourceWorld, mutation: str
) -> None:
    world = resource_world
    await arm_owned_lifecycle(world.task, world.api, world.directory)
    await world.prepare()
    name = world.task.batch.batch_key + "-created"
    created = await world.create(name)
    cancelled = await world.cancel()
    reads = deletes = 0

    class MutatingMetadata(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal reads, deletes
            if request.method == "DELETE":
                deletes += 1
                pytest.fail("changed metadata must not permit a cleanup DELETE")
            if request.method == "GET" and request.url.path.endswith("/environments"):
                reads += 1
                if reads == 2 and mutation == "renamed":
                    await world.api.request(
                        "PATCH",
                        world.target_root + f"/{created['id']}",
                        {"name": "changed-by-another-operation"},
                    )
                if reads == 2 and mutation == "replaced":
                    await world.api.request("DELETE", world.target_root + f"/{created['id']}")
                    await world.create(world.task.batch.batch_key + "-updated")
                result = objects_value(await world.api.request("GET", world.target_root))
                return httpx.Response(200, json=_metadata_counterexample(result, mutation))
            return await httpx.ASGITransport(app=app).handle_async_request(request)

    target = PublicAPI(
        "http://test",
        world.product.headers["Authorization"].removeprefix("Bearer "),
        transport=MutatingMetadata(),
    )
    try:
        receipt = await world.cleanup(cancelled, target)
        assert receipt["status"] == "needs_review" and deletes == 0
        assert receipt["reason_codes"]
        remaining = await world.api.request("GET", world.target_root)
        assert len(remaining) == 1
    finally:
        await target.close()


def _metadata_counterexample(rows: list[JsonObject], mutation: str) -> dict | list[JsonObject]:
    replacements = {
        "creator": ("created_by_id", str(uuid4())),
        "old_time": ("created_at", (datetime.now(UTC) - timedelta(days=1)).isoformat()),
        "naive_time": ("created_at", "2026-10-23T10:00:00"),
        "project": ("project_id", str(uuid4())),
    }
    if mutation in replacements:
        field, value = replacements[mutation]
        rows[0][field] = value
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "truncated":
        return {"items": rows, "has_more": True, "truncated": True}
    return rows


async def test_assisted_lifecycle_names_use_exact_origin_projection_not_optional_mock_key(
    resource_world: ResourceWorld, tmp_path: Path
) -> None:
    """Typed synthetic sealed metadata tests naming only; no deployed seal acceptance."""
    world = resource_world
    frozen_fixture, materialized, *_ = assisted_fixture(tmp_path)
    original = frozen_fixture.before_sources[0]
    source = original.source.model_copy(
        update={
            "scenario_id": "ST-MCP-023",
            "variant_key": "owned_resource",
            "fixture_batch_key": None,
        }
    )
    origin = original.model_copy(
        update={
            "scenario_id": source.scenario_id,
            "variant_key": source.variant_key,
            "batch_key": "original-known-batch",
            "source": source,
            "source_digest": canonical_digest(source.model_dump(mode="json")),
        }
    )
    current = world.task
    before = origin
    for revision in (None, materialized.revisions[0].lineage):
        projections = (origin,)
        if revision is not None:
            amended = source.model_copy(
                update={
                    "assisted": revision.model_copy(update={"origin_batch_id": origin.batch_id})
                }
            )
            before = origin.model_copy(
                update={
                    "batch_id": uuid4(),
                    "batch_key": "intermediate-known-batch",
                    "source": amended,
                    "source_digest": canonical_digest(amended.model_dump(mode="json")),
                }
            )
            projections = (before, origin)
        frozen = current.frozen_manifest.model_copy(
            update={"assisted_before_batch_id": before.batch_id}
        )
        batch = current.batch.model_copy(
            update={"manifest_digest": canonical_digest(frozen.model_dump(mode="json"))}
        )
        task = current.model_copy(
            update={"batch": batch, "frozen_manifest": frozen, "before_sources": projections}
        )
        identity = lifecycle_identity(task)
        assert identity.naming_batch_key == origin.batch_key
        assert identity.names == ("original-known-batch-created", "original-known-batch-updated")
        with pytest.raises(HarnessError, match="BEFORE_SOURCE_MISSING"):
            lifecycle_identity(task.model_copy(update={"before_sources": ()}))
        changed = before.model_copy(update={"source_digest": "f" * 64})
        broken = (changed,) if before.batch_id == origin.batch_id else (changed, origin)
        with pytest.raises(HarnessError, match="BEFORE_SOURCE_UNPROVEN"):
            lifecycle_identity(task.model_copy(update={"before_sources": broken}))
