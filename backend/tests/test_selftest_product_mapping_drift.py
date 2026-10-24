"""A ready installation cannot authorize a later changed environment or service endpoint."""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_selftest_product_api import ProductContext, _ready
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.models.tasking import TestPlanRun as PlanRun


async def drift(context: ProductContext, kind: str) -> None:
    root = f"/api/v1/projects/{context.project_id}"
    environment = context.mapping.environment_id
    if kind == "environment":
        response = await context.native.client.patch(
            root + f"/environments/{environment}",
            headers=context.headers,
            json={"base_url": "http://wrong-target.example"},
        )
    else:
        endpoint = await context.post(
            root + f"/environments/{environment}/service-endpoints",
            {
                "service_id": str(context.mapping.fixture_service_id),
                "variant": "default",
                "base_url": "http://wrong-target.example",
            },
            status=201,
        )
        assert UUID(endpoint["service_id"]) == context.mapping.fixture_service_id
        response = await context.native.client.patch(
            root + f"/environments/{environment}",
            headers=context.headers,
            json={"default_service_id": str(context.mapping.fixture_service_id)},
        )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("kind", ["environment", "endpoint"])
async def test_preflight_blocks_changed_ready_mapping_before_confirmation(
    product: ProductContext, kind: str
):
    installed = await _ready(product)
    await drift(product, kind)
    response = await product.post(
        product.root + "/installations/preview",
        {"template_id": installed["template_id"], "binding_id": str(product.binding.id)},
    )
    assert response["can_apply"] is False
    assert "SELFTEST_ENVIRONMENT_MAPPING_INVALID" in response["conflicts"]
    assert any(
        check["code"] == "SELFTEST_ENVIRONMENT_MAPPING_INVALID" and check["status"] == "blocked"
        for check in response["checks"]
    )
    assert not product.native.queue.test_plan_run_ids


@pytest.mark.parametrize("kind", ["environment", "endpoint"])
async def test_ready_installation_drift_is_rejected_before_new_batch_or_native_run(
    product: ProductContext, kind: str
):
    installed = await _ready(product)
    await drift(product, kind)
    response = await product.native.client.post(
        product.root + f"/installations/{installed['id']}/runs",
        headers={**product.headers, "Idempotency-Key": "drift-run"},
        json={},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "SELFTEST_ENVIRONMENT_MAPPING_INVALID"
    assert response.json()["error"]["trace_id"]
    async with product.native.session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(PlanRun)) == 0
    assert not product.native.queue.test_plan_run_ids


@pytest.mark.parametrize("kind", ["environment", "endpoint"])
async def test_drift_after_batch_creation_is_rejected_before_prepared_dispatch(
    product: ProductContext, kind: str
):
    installed = await _ready(product)
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/runs", {}, key="before-drift", status=202
    )
    lease = await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {
            "expected_revision": batch["revision"],
            "nonce": "drift-nonce-" + "a" * 32,
        },
        machine="h",
    )
    await drift(product, kind)
    result = await product.post(
        product.agent + f"/runs/{batch['id']}/prepared",
        {
            "lease_token": lease["lease_token"],
            "nonce": lease["nonce"],
        },
        machine="h",
        status=409,
    )
    assert result["error"]["code"] == "SELFTEST_ENVIRONMENT_MAPPING_INVALID"
    assert not product.native.queue.test_plan_run_ids
    async with product.native.session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(PlanRun)) == 0
