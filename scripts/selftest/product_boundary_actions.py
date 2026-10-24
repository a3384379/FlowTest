"""Public product installation, overlapping batches and exact seal replay observations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.initialization_inventory import inventory
from scripts.selftest.io import HarnessError, JsonObject, object_value, objects_value, text_value
from scripts.selftest.product_boundary_common import (
    ProductWorld,
    agent,
    install,
    verification_receipt,
)
from scripts.selftest.product_boundary_contracts import (
    ProductBatchSnapshot,
    ProductBoundaryObservation,
)
from scripts.selftest.security_boundary_contracts import DenialObservation

from app.schemas.self_tests import BatchResponse, InstallationResponse


def response_receipt(operation: str, response: httpx.Response) -> DenialObservation:
    raw = object_value(response.json()) if response.content else {}
    error = object_value(raw.get("error", {}))
    code, trace = error.get("code"), error.get("trace_id")
    return DenialObservation(
        operation=operation,
        status=response.status_code,
        code=code if isinstance(code, str) else None,
        trace_id=trace if isinstance(trace, str) else None,
        response_digest=canonical_digest(raw),
    )


async def batch_snapshot(world: ProductWorld, identifier: UUID) -> ProductBatchSnapshot:
    batch = BatchResponse.model_validate(
        await world.viewer.object("GET", world.root + f"/runs/{identifier}")
    )
    if batch.provenance != "local_untrusted":
        raise HarnessError("PRODUCT_BOUNDARY_UNEXPECTED_TRUST_PROMOTION")
    page = await world.viewer.object(
        "GET", world.root + f"/runs/{identifier}/scenarios?page_size=100"
    )
    rows = objects_value(page["items"])
    if page.get("next_cursor") is not None or len(rows) != batch.expected_count:
        raise HarnessError("PRODUCT_BOUNDARY_SCENARIO_PAGE_INCOMPLETE")
    execution_ids = tuple(
        UUID(text_value(reference["execution_id"]))
        for row in rows
        for reference in objects_value(row["executions"])
    )
    return ProductBatchSnapshot(
        id=batch.id,
        project_id=batch.project_id,
        installation_id=batch.installation_id,
        plan_run_ids=batch.plan_run_ids,
        execution_ids=execution_ids,
        phase=batch.phase,
        verdict=batch.verdict,
        sealed_verdict=batch.sealed_verdict,
        evidence_integrity=batch.evidence_integrity,
        cleanup_status=batch.cleanup_status,
        manifest_digest=batch.manifest_digest,
        resource_digest=batch.resource_digest,
        sealed_at=batch.sealed_at,
        expected_scenario_ids=tuple(row.scenario_id for row in batch.expected_scenario_set),
        actual_scenario_ids=tuple(text_value(row["scenario_id"]) for row in rows),
        observed_statuses=tuple(
            row["observed_status"] if isinstance(row["observed_status"], str) else None
            for row in rows
        ),
        verification_statuses=tuple(text_value(row["verification_status"]) for row in rows),
        artifact_ids=tuple(row.id for row in batch.artifacts),
        provenance=batch.provenance,
    )


async def begin_batch(
    world: ProductWorld, installation: InstallationResponse, key: str, *, seconds: int = 600
) -> BatchResponse:
    return BatchResponse.model_validate(
        await world.user.object(
            "POST",
            world.root + f"/installations/{installation.id}/runs",
            {"budget": {"timeout_seconds": seconds, "max_requests": 500, "max_tool_calls": 100}},
            idempotency_key=key,
        )
    )


async def installation_checks(
    world: ProductWorld,
) -> tuple[InstallationResponse, tuple[ProductBoundaryObservation, ...]]:
    before = await inventory(world.viewer, world.config.project_id)
    installed, payload = await install(world, "core-v1", "product-boundary-install-core")
    after = await inventory(world.viewer, world.config.project_id)
    first = ProductBoundaryObservation(
        key="clean_install",
        before=before,
        after=after,
        installation_ids=(installed.id,),
        mapping_digests=(canonical_digest(installed.mapping.model_dump(mode="json")),)
        if installed.mapping
        else (),
        observed_at=datetime.now(UTC),
    )
    repeated = InstallationResponse.model_validate(
        await world.user.object(
            "POST",
            world.root + "/installations",
            payload,
            idempotency_key="product-boundary-install-core",
        )
    )
    repeated_inventory = await inventory(world.viewer, world.config.project_id)
    second = ProductBoundaryObservation(
        key="same_key_reinstall",
        before=after,
        after=repeated_inventory,
        installation_ids=(installed.id, repeated.id),
        mapping_digests=tuple(
            canonical_digest(row.mapping.model_dump(mode="json"))
            for row in (installed, repeated)
            if row.mapping is not None
        ),
        observed_at=datetime.now(UTC),
    )
    return installed, (first, second)


async def overlapping_batches(
    world: ProductWorld, installation: InstallationResponse
) -> tuple[BatchResponse, BatchResponse]:
    first = await begin_batch(world, installation, "product-boundary-batch-first")
    second = await begin_batch(world, installation, "product-boundary-batch-second")
    preparing = asyncio.create_task(agent(world, "harness"))
    try:
        for _ in range(100):
            states = [
                await world.user.object("GET", world.root + f"/runs/{row.id}")
                for row in (first, second)
            ]
            if any(row["phase"] != "pending" for row in states):
                break
            await asyncio.sleep(0.05)
        else:
            raise HarnessError("PRODUCT_BOUNDARY_FIRST_CLAIM_NOT_OBSERVED")
        await agent(world, "harness")
        await preparing
    finally:
        if not preparing.done():
            preparing.cancel()
            await asyncio.gather(preparing, return_exceptions=True)
    return first, second


async def seal_checks(
    world: ProductWorld, batch: BatchResponse
) -> tuple[ProductBoundaryObservation, ...]:
    before = await batch_snapshot(world, batch.id)
    receipt = verification_receipt(world, batch)
    path = f"/ci/projects/{batch.project_id}/self-test-runs/{batch.id}/verification"
    replay = await world.machine.probe("POST", path, object_value(receipt.model_dump(mode="json")))
    after = await batch_snapshot(world, batch.id)
    result = [
        ProductBoundaryObservation(
            key="seal_idempotent",
            requests=(response_receipt("same_receipt", replay),),
            batches=(before, after),
            observed_at=datetime.now(UTC),
        )
    ]
    changes: tuple[tuple[str, JsonObject], ...] = (
        ("seal_conflict", {"cleanup_status": "failed"}),
        (
            "seal_build",
            {"builds": {**receipt.builds.model_dump(mode="json"), "target": "sha256:" + "0" * 64}},
        ),
        ("seal_manifest", {"manifest_digest": "0" * 64}),
        ("seal_attempt", {"ci_attempt": 999}),
    )
    for key, change in changes:
        response = await world.machine.probe(
            "POST", path, {**object_value(receipt.model_dump(mode="json")), **change}
        )
        current = await batch_snapshot(world, batch.id)
        result.append(
            ProductBoundaryObservation(
                key=key,
                requests=(response_receipt("changed_receipt", response),),
                batches=(before, current),
                observed_at=datetime.now(UTC),
            )
        )
    return tuple(result)
