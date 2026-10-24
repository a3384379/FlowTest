"""A claimed O task receives only its batch's typed frozen source projection."""

from uuid import UUID

from sqlalchemy import select
from test_selftest_product_api import ProductContext
from test_selftest_product_api import product as product
from test_selftest_product_sources import _materialized
from test_tasking_api import tasking_context as tasking_context

from app.models.self_tests import SelfTestScenarioResult
from app.schemas.self_tests import SourceReference


async def test_observation_claim_and_renew_return_exact_frozen_sources_without_project_read(
    product: ProductContext,
) -> None:
    batch, payload = await _materialized(product)
    ready = await product.post(
        product.agent + f"/runs/{batch['id']}/materialized", payload, machine="h"
    )
    other = await product.post(
        product.root + f"/installations/{batch['installation_id']}/generation-batches",
        {"scenario_ids": ["ST-MCP-026"], "verification_scope": "diagnostic_subset"},
        key="other-source-scope",
        status=202,
    )
    async with product.native.session_maker() as session:
        row = await session.scalar(
            select(SelfTestScenarioResult).where(
                SelfTestScenarioResult.batch_id == UUID(other["id"])
            )
        )
        assert row is not None
        row.source = {**payload["sources"][0], "compilation_fingerprint": "f" * 64}
        await session.commit()
    running = await product.post(
        product.root + f"/runs/{batch['id']}/execute-materialized",
        {
            "resource_digest": ready["resource_digest"],
            "environment_fingerprint": ready["environment_fingerprint"],
            "confirmed": True,
        },
        key="frozen-source-execute",
        status=202,
    )
    claimed = await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {"expected_revision": running["revision"], "nonce": payload["nonce"]},
        machine="o",
    )
    expected = SourceReference.model_validate(payload["sources"][0]).model_dump(mode="json")
    assert claimed["sources"] == [expected]
    assert claimed["task_id"] == batch["id"] and claimed["project_id"] == str(product.project_id)
    assert not {"definition", "design", "request", "response", "headers", "secret"}.intersection(
        claimed["sources"][0]
    )
    renewed = await product.post(
        product.agent + f"/runs/{batch['id']}/lease",
        {"lease_token": claimed["lease_token"], "nonce": claimed["nonce"]},
        machine="o",
    )
    assert renewed["sources"] == claimed["sources"]
    denied = await product.native.client.get(
        product.root + f"/runs/{batch['id']}/generation", headers=product.machine("o")
    )
    assert denied.status_code == 401
