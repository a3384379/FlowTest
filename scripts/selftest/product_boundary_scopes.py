"""Actual read:execution and task-lease refusals with real HTTP and short-lived tokens."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from scripts.selftest.io import HarnessError, JsonObject, objects_value, text_value
from scripts.selftest.product_agent_client import claim, register
from scripts.selftest.product_boundary_actions import response_receipt
from scripts.selftest.product_boundary_common import ProductWorld
from scripts.selftest.product_boundary_contracts import ProductBoundaryObservation
from scripts.selftest.security_boundary_http import BoundaryAPI

from app.schemas.self_tests import AgentTaskResponse, BatchResponse


class LeaseProbe(BoundaryAPI):
    def __init__(self, world: ProductWorld, task: AgentTaskResponse) -> None:
        super().__init__(
            world.stack.runner_url, world.budget, world.deadline, world.config.observer.token()
        )
        self.task = task

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        return {
            **super()._headers(idempotency_key),
            "X-SelfTest-Lease-Token": self.task.lease_token,
            "X-SelfTest-Nonce": self.task.nonce,
        }


async def claim_and_check_scope(
    world: ProductWorld,
    batch: BatchResponse,
    other: BatchResponse,
) -> tuple[AgentTaskResponse, ProductBoundaryObservation]:
    await register(world.machine, world.config, observer=True)
    current = await world.user.object("GET", world.root + f"/runs/{batch.id}")
    if not isinstance(current["revision"], int):
        raise HarnessError("PRODUCT_BOUNDARY_REVISION_INVALID")
    task = await claim(
        world.machine, world.config.project_id, batch.id, current["revision"], world.state / "tasks"
    )
    if task.batch is None or not task.batch.plan_run_ids or not other.plan_run_ids:
        raise HarnessError("PRODUCT_BOUNDARY_NATIVE_RUNS_MISSING")
    root = f"/agent/projects/{batch.project_id}/self-tests/runs/{batch.id}/evidence/test-plan-runs/"
    probe = LeaseProbe(world, task)
    try:
        own = await probe.probe("GET", root + str(task.batch.plan_run_ids[0]))
        foreign = await probe.probe("GET", root + str(other.plan_run_ids[0]))
    finally:
        await probe.close()
    return task, ProductBoundaryObservation(
        key="cross_run",
        requests=(response_receipt("own_run", own), response_receipt("foreign_run", foreign)),
        listed_ids=(task.batch.plan_run_ids[0], other.plan_run_ids[0]),
        observed_at=datetime.now(UTC),
    )


async def _token(world: ProductWorld, name: str, *, expires: datetime | None = None) -> JsonObject:
    return await world.user.object(
        "POST",
        f"/projects/{world.config.project_id}/service-tokens",
        {
            "name": name,
            "scopes": ["read:execution"],
            "expires_at": (expires or world.deadline).isoformat(),
        },
    )


async def _pages(world: ProductWorld, api: BoundaryAPI, path: str) -> ProductBoundaryObservation:
    identifiers: list[UUID] = []
    receipts = []
    total = -1
    for page in range(1, 20):
        response = await api.probe("GET", path + f"?page={page}&page_size=1")
        receipts.append(response_receipt("page_" + str(page), response))
        if response.status_code != 200:
            break
        raw = response.json()
        if raw["truncated"] is not False or raw["page"] != page or raw["page_size"] != 1:
            raise HarnessError("PRODUCT_BOUNDARY_SCOPE_PAGE_INCOMPLETE")
        if total not in (-1, raw["total"]):
            raise HarnessError("PRODUCT_BOUNDARY_SCOPE_PAGE_TOTAL_CHANGED")
        total = raw["total"]
        identifiers.extend(UUID(text_value(row["id"])) for row in objects_value(raw["items"]))
        if raw["has_more"] is False:
            break
    return ProductBoundaryObservation(
        key="pagination",
        requests=tuple(receipts),
        listed_ids=tuple(identifiers),
        listed_total=total,
        observed_at=datetime.now(UTC),
    )


async def read_scope_checks(
    world: ProductWorld, batch: BatchResponse
) -> tuple[ProductBoundaryObservation, ...]:
    if len(batch.plan_run_ids) != 1 or batch.plan_id is None:
        raise HarnessError("PRODUCT_BOUNDARY_PLAN_MISSING")
    root = f"/ci/projects/{batch.project_id}"
    path = root + f"/test-plan-runs/{batch.plan_run_ids[0]}"
    issued = await _token(world, "只读边界验证")
    api = BoundaryAPI(
        world.stack.runner_url, world.budget, world.deadline, text_value(issued["token"])
    )
    rows = []
    try:
        response = await api.probe("GET", path)
        payload = response.json()
        rows.append(
            ProductBoundaryObservation(
                key="readonly_scope",
                requests=(response_receipt("read_run", response),),
                safe_fields=tuple(sorted(payload)),
                observed_at=datetime.now(UTC),
            )
        )
        foreign = await api.probe("GET", path.replace(str(batch.project_id), str(uuid4())))
        rows.append(
            ProductBoundaryObservation(
                key="cross_project",
                requests=(response_receipt("foreign_project", foreign),),
                observed_at=datetime.now(UTC),
            )
        )
        denied = await api.probe("POST", root + f"/test-plans/{batch.plan_id}/runs")
        rows.append(
            ProductBoundaryObservation(
                key="denied_mutations",
                requests=(response_receipt("start_plan", denied),),
                observed_at=datetime.now(UTC),
            )
        )
        rows.append(await _pages(world, api, path))
        await world.user.request(
            "DELETE", f"/projects/{batch.project_id}/service-tokens/{issued['id']}"
        )
        revoked = await api.probe("GET", path)
        rows.append(
            ProductBoundaryObservation(
                key="revoked_token",
                requests=(response_receipt("revoked", revoked),),
                observed_at=datetime.now(UTC),
            )
        )
    finally:
        await api.close()
    rows.append(await _expired(world, path))
    return tuple(rows)


async def _expired(world: ProductWorld, path: str) -> ProductBoundaryObservation:
    expiry = datetime.now(UTC) + timedelta(seconds=2)
    issued = await _token(world, "真实到期边界", expires=expiry)
    api = BoundaryAPI(
        world.stack.runner_url, world.budget, world.deadline, text_value(issued["token"])
    )
    try:
        valid = await api.probe("GET", path)
        await asyncio.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.05)
        expired = await api.probe("GET", path)
    finally:
        await api.close()
    return ProductBoundaryObservation(
        key="expired_token",
        requests=(
            response_receipt("before_expiry", valid),
            response_receipt("after_expiry", expired),
        ),
        observed_at=datetime.now(UTC),
    )
