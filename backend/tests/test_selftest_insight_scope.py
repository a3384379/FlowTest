"""Incomplete observer manifests cannot supply cross-scenario metrics before evidence arrives."""

import json
from uuid import UUID

from test_selftest_product_api import ProductContext
from test_selftest_product_api import product as product
from test_selftest_product_insights import generated
from test_tasking_api import tasking_context as tasking_context

from app.models.access import User
from app.models.self_tests import SelfTestBatch
from app.schemas.self_tests import ArtifactReference
from app.services.artifacts import ArtifactService


async def test_manifest_scope_is_checked_even_without_an_evidence_document(product: ProductContext):
    batch = await generated(product)
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert model
        actor = await session.get(User, model.created_by_id)
        assert actor
        content = {"batch_key": model.batch_key, "scenarios": [{"scenario_id": "ST-OTHER-001"}]}
        stored = await ArtifactService(session).upload(
            actor=actor,
            project_id=model.project_id,
            filename="manifest.json",
            content_type="application/json",
            content=json.dumps(content).encode(),
        )
        model.artifact_refs = [
            ArtifactReference(id=stored.id, kind="manifest", sha256=stored.sha256).model_dump(
                mode="json"
            )
        ]
        await session.commit()
    response = await product.native.client.get(
        product.root + f"/runs/{batch['id']}/insights", headers=product.headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELFTEST_INSIGHT_SCOPE_MISMATCH"
    assert response.json()["error"]["trace_id"]
