"""Real owned maintenance with a controlled retention clock; never update rows to fake expiry."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from scripts.selftest.initialization_inventory import inventory
from scripts.selftest.io import HarnessError, integer_value, object_value, read_json
from scripts.selftest.local_stack import _docker, verify_binding
from scripts.selftest.product_agent_client import AgentRuntime
from scripts.selftest.product_boundary_actions import batch_snapshot
from scripts.selftest.product_boundary_common import ProductWorld
from scripts.selftest.product_boundary_contracts import (
    MaintenanceReceipt,
    ProductBoundaryObservation,
)
from scripts.selftest.security_boundary_http import BoundaryAPI

from app.schemas.self_tests import BatchResponse

MAINTENANCE = """
import asyncio, json, sys
from dataclasses import asdict
from datetime import datetime
from app.core.database import session_factory, close_database
from app.services.retention import RetentionCleanupService
async def main():
    try:
        async with session_factory() as session:
            clock = datetime.fromisoformat(sys.argv[1])
            value = await RetentionCleanupService(session).cleanup(clock)
            print(json.dumps(asdict(value)))
    finally:
        await close_database()
asyncio.run(main())
"""


def maintain(world: ProductWorld, clock: datetime, *, repeat: bool) -> MaintenanceReceipt:
    verify_binding(world.stack, world.directory)
    raw = object_value(
        json.loads(
            _docker(
                [
                    "exec",
                    world.stack.runner_container_id,
                    "python",
                    "-c",
                    MAINTENANCE,
                    clock.isoformat(),
                ],
                timeout=60,
            )
        )
    )
    return MaintenanceReceipt(
        container_id=world.stack.runner_container_id,
        ownership_nonce=world.stack.nonce,
        clock=clock,
        repeat=repeat,
        projects_scanned=integer_value(raw["projects_scanned"]),
        workflow_executions_deleted=integer_value(raw["workflow_executions_deleted"]),
        test_plan_runs_deleted=integer_value(raw["test_plan_runs_deleted"]),
        artifacts_deleted=integer_value(raw["artifacts_deleted"]),
        storage_failures=integer_value(raw["storage_failures"]),
    )


async def namespace_statuses(world: ProductWorld, batch: BatchResponse) -> tuple[int, ...]:
    runtime = AgentRuntime.model_validate(read_json(world.state / "harness-runtime.json"))
    api = BoundaryAPI(
        world.stack.observer_url, world.budget, world.deadline, runtime.fixture_management_token
    )
    # The Mock API has its own prefix; make the base transport explicit and preserve its token.
    from scripts.selftest.io import PublicAPI

    client = PublicAPI(world.stack.observer_url, runtime.fixture_management_token, api_prefix="")
    statuses = []
    try:
        for row in batch.expected_scenario_set:
            async with asyncio.timeout(api._reserve()):
                response = await client._client.get(
                    f"selftest/batches/{batch.batch_key}/scenarios/{row.scenario_id}/journal",
                    headers=client._headers(),
                )
            statuses.append(response.status_code)
    finally:
        await asyncio.gather(api.close(), client.close())
    return tuple(statuses)


async def cleanup_proof(world: ProductWorld, batch: BatchResponse) -> ProductBoundaryObservation:
    return ProductBoundaryObservation(
        key="success_failure_cleanup",
        batches=(await batch_snapshot(world, batch.id),),
        namespace_statuses=await namespace_statuses(world, batch),
        observed_at=datetime.now(UTC),
    )


async def retention_checks(
    world: ProductWorld, batch: BatchResponse
) -> tuple[ProductBoundaryObservation, ...]:
    before = await inventory(world.viewer, world.config.project_id)
    original = await batch_snapshot(world, batch.id)
    await world.user.object(
        "PUT", f"/projects/{batch.project_id}/retention-policy", {"retention_days": 1}
    )
    clock = datetime.now(UTC) + timedelta(days=2)
    first = await asyncio.to_thread(maintain, world, clock, repeat=False)
    current = await batch_snapshot(world, batch.id)
    after = await inventory(world.viewer, world.config.project_id)
    responses = [
        await world.viewer.probe("GET", f"/projects/{batch.project_id}/files/{artifact}")
        for artifact in original.artifact_ids
    ]
    second = await asyncio.to_thread(maintain, world, clock, repeat=True)
    if not responses:
        raise HarnessError("PRODUCT_BOUNDARY_RETENTION_NO_REAL_ARTIFACTS")
    return tuple(
        ProductBoundaryObservation(
            key=key,
            before=before,
            after=after,
            batches=(original, current),
            object_statuses=tuple(response.status_code for response in responses),
            maintenance=(first, second),
            observed_at=datetime.now(UTC),
        )
        for key in ("retention", "expiry", "foreign_key")
    )
