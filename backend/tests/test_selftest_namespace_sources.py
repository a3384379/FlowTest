"""Namespace aliases must match the actual public frozen materialization digest."""

import sys
from pathlib import Path

import pytest
from test_selftest_product_api import ProductContext
from test_selftest_product_api import product as product
from test_selftest_product_sources import _materialized
from test_tasking_api import tasking_context as tasking_context

from app.schemas.self_tests import BatchResponse, GenerationSummary

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.io import HarnessError
from scripts.selftest.namespace_sources import frozen_namespace_keys


async def test_namespace_aliases_require_complete_actual_public_resource_digest(
    product: ProductContext,
) -> None:
    batch, payload = await _materialized(product)
    actual = BatchResponse.model_validate(
        await product.post(
            product.agent + f"/runs/{batch['id']}/materialized", payload, machine="h"
        )
    )
    generation = GenerationSummary.model_validate(
        await product.get(product.root + f"/runs/{actual.id}/generation")
    )
    source = generation.sources[0]
    assert frozen_namespace_keys(actual, generation, assisted=False) == {
        source.scenario_id: actual.batch_key
    }
    changed = source.model_copy(update={"fixture_batch_key": "unfrozen-other-namespace"})
    with pytest.raises(HarnessError, match="SOURCE_DIGEST_MISMATCH"):
        frozen_namespace_keys(
            actual, generation.model_copy(update={"sources": (changed,)}), assisted=False
        )
    for sources in ((), (source, source)):
        with pytest.raises(HarnessError, match="SOURCE_INCOMPLETE"):
            frozen_namespace_keys(
                actual, generation.model_copy(update={"sources": sources}), assisted=False
            )
    with pytest.raises(HarnessError, match="ASSISTED_SOURCE_MISSING"):
        frozen_namespace_keys(actual, generation, assisted=True)
    with pytest.raises(HarnessError, match="SOURCE_INCOMPLETE"):
        frozen_namespace_keys(
            actual.model_copy(update={"resource_digest": None}), generation, assisted=True
        )
    with pytest.raises(HarnessError, match="SOURCE_INCOMPLETE"):
        frozen_namespace_keys(
            actual,
            generation.model_copy(update={"batch_id": actual.installation_id}),
            assisted=False,
        )
    changed = source.model_copy(
        update={"workflow": source.workflow.model_copy(update={"version": 2})}
    )
    with pytest.raises(HarnessError, match="SOURCE_ASSETS_CHANGED"):
        frozen_namespace_keys(
            actual, generation.model_copy(update={"sources": (changed,)}), assisted=False
        )
