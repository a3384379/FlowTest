"""Product read projections and recovery preserve scope and original installation identity."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from test_selftest_product_api import ProductContext, _claimed_installation, _ready
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.domain.self_tests import document_digest
from app.models.access import User
from app.models.self_tests import SelfTestBatch, SelfTestInstallation, SelfTestScenarioResult
from app.schemas.self_tests import ArtifactReference
from app.services.artifacts import ArtifactService


async def generated(product: ProductContext) -> dict:
    installed = await _ready(product, "mcp-core-v1")
    return await product.post(
        product.root + f"/installations/{installed['id']}/generation-batches",
        {},
        key="insight-batch",
        status=202,
    )


async def test_insights_use_entire_frozen_set_and_zero_means_unevaluated(product: ProductContext):
    batch = await generated(product)
    result = await product.get(product.root + f"/runs/{batch['id']}/insights")
    metrics = {item["key"]: item for item in result["metrics"]}
    assert len(metrics) == 11
    assert metrics["verification"]["denominator"] == batch["expected_count"]
    assert metrics["first"]["denominator"] == batch["expected_count"]
    assert metrics["verification"]["numerator"] == 0
    for key in ("protocol", "design", "assisted", "oracle"):
        assert metrics[key]["denominator"] == 0
        assert metrics[key]["exclusions"]
    assert result["manifest_digest"] == batch["manifest_digest"]
    assert result["task_set_digest"] and result["template_version"]
    assert result["comparisons"] == []
    page = await product.get(product.root + f"/runs/{batch['id']}/scenarios?page_size=1")
    assert len(page["items"]) == 1 < metrics["verification"]["denominator"]
    denied = await product.native.client.get(
        f"/api/v1/projects/{uuid4()}/self-tests/runs/{batch['id']}/insights",
        headers=product.headers,
    )
    assert denied.status_code == 404 and denied.json()["error"]["trace_id"]


async def test_observer_projection_has_actual_counts_and_does_not_expose_extra_payload(
    product: ProductContext,
):
    batch = await generated(product)
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert model
        rows = list(
            (
                await session.scalars(
                    select(SelfTestScenarioResult).where(
                        SelfTestScenarioResult.batch_id == model.id
                    )
                )
            ).all()
        )
        manifest = {
            "batch_key": model.batch_key,
            "scenarios": [
                {
                    "scenario_id": row.scenario_id,
                    "variant_key": row.variant_key,
                    "expected": {"execution_status": "failed", "request_count": 2},
                    "required_oracle_ids": ["status"],
                }
                for row in rows
            ],
        }
        evidence = {
            "batch_key": model.batch_key,
            "scenarios": [
                {
                    "scenario_id": row.scenario_id,
                    "variant_key": row.variant_key,
                    "execution": None,
                    "journal": {"request_count": 1},
                    "cleanup_status": "pending",
                    "raw_secret": "never-in-product-projection",
                }
                for row in rows
            ],
        }
        actor = await session.get(User, model.created_by_id)
        assert actor
        refs = []
        for kind, content in (("manifest", manifest), ("evidence", evidence)):
            stored = await ArtifactService(session).upload(
                actor=actor,
                project_id=model.project_id,
                filename=f"{kind}.json",
                content_type="application/json",
                content=json.dumps(content).encode(),
            )
            refs.append(
                ArtifactReference(id=stored.id, kind=kind, sha256=stored.sha256).model_dump(
                    mode="json"
                )
            )
        model.artifact_refs = refs
        await session.commit()
    result = await product.get(product.root + f"/runs/{batch['id']}/insights")
    item = next(item for item in result["comparisons"][0]["items"] if item["field"] == "请求次数")
    assert item["expected"] == "2" and item["observed"] == "1"
    assert item["verification_status"] == "pending"
    assert item["difference"] == "different"
    assert "never-in-product-projection" not in str(result)


async def test_resume_keeps_mapping_nonce_and_rejects_live_lease_stale_revision(
    product: ProductContext,
):
    installed, lease = await _claimed_installation(product)
    path = product.root + f"/installations/{installed['id']}/resume"
    current = await product.get(product.root + f"/installations/{installed['id']}")
    failed = await product.post(
        product.agent + f"/installations/{installed['id']}/failure",
        {
            "lease_token": lease["lease_token"],
            "nonce": lease["nonce"],
            "reason_codes": ["SELFTEST_INSTALLATION_PARTIAL"],
            "mapping": product.mapping.model_copy(
                update={"assets": product.mapping.assets[:1]}
            ).model_dump(mode="json"),
        },
        machine="h",
    )
    assert failed["status"] == "blocked" and len(failed["mapping"]["assets"]) == 1
    current = await product.get(product.root + f"/installations/{installed['id']}")
    payload = {
        "expected_revision": current["revision"],
        "environment_fingerprint": current["environment_fingerprint"],
        "confirmed": True,
    }
    response = await product.native.client.post(path, headers=product.headers, json=payload)
    assert response.status_code == 409
    async with product.native.session_maker() as session:
        row = await session.get(SelfTestInstallation, UUID(installed["id"]))
        assert row
        row.status = "blocked"
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        row.resource_mapping = product.mapping.model_dump(mode="json")
        original_nonce = row.nonce_hash
        await session.commit()
    resumed = await product.post(path, payload)
    assert resumed["id"] == installed["id"] and resumed["status"] == "needs_input"
    assert resumed["mapping"] == product.mapping.model_dump(mode="json")
    again = await product.native.client.post(path, headers=product.headers, json=payload)
    assert again.status_code == 409 and again.json()["error"]["trace_id"]
    async with product.native.session_maker() as session:
        row = await session.get(SelfTestInstallation, UUID(installed["id"]))
        assert row and row.nonce_hash == original_nonce and row.lease_hash is None
    await product.post(
        product.agent + "/register",
        {
            "binding_id": str(product.binding.id),
            "binding_fingerprint": document_digest(product.binding),
            "environment_fingerprint": product.binding.environment_fingerprint,
            "builds": product.binding.builds.model_dump(),
            "host_id": "test-host",
            "capabilities": ["install", "deterministic_mcp"],
        },
        machine="h",
    )

    current = await product.get(product.root + f"/installations/{installed['id']}")
    wrong_nonce = await product.native.client.post(
        product.agent + f"/installations/{installed['id']}/claim",
        headers=product.machine("h"),
        json={"expected_revision": current["revision"], "nonce": "x" * 32},
    )
    assert wrong_nonce.status_code == 409
    await product.post(
        product.agent + f"/installations/{installed['id']}/claim",
        {"expected_revision": current["revision"], "nonce": lease["nonce"]},
        machine="h",
    )


async def test_compiler_input_diagnostics_survive_the_authorized_progress_projection(
    product: ProductContext,
):
    batch = await generated(product)
    lease = await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {
            "expected_revision": batch["revision"],
            "nonce": "diagnostic-nonce-" + "3" * 32,
        },
        machine="h",
    )
    diagnostic = {
        "code": "REQUIRED_INPUT_MISSING",
        "severity": "input",
        "scenario_id": "ST-MCP-025",
        "oracle_id": "required-order",
        "field_path": "$.order_id",
        "repair_hint": "补充订单标识",
    }
    await product.post(
        product.agent + f"/runs/{batch['id']}/generation",
        {
            "lease_token": lease["lease_token"],
            "nonce": lease["nonce"],
            "stage": "blocked",
            "readiness": "needs_input",
            "tool_call_count": 0,
            "diagnostics": [diagnostic],
        },
        machine="h",
    )
    result = await product.get(product.root + f"/runs/{batch['id']}/insights")
    assert result["diagnostics"] == [diagnostic]
