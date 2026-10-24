"""Freeze independent golden checks before the product's native execution confirmation."""

from __future__ import annotations

from pathlib import Path

from scripts.selftest.collect_lifecycle_evidence import lifecycle_expectation
from scripts.selftest.contracts import BatchManifest, Builds, FixtureBudgetScope, canonical_digest
from scripts.selftest.generation_lifecycle import LifecycleAsset
from scripts.selftest.host_materialized import HostMaterialization
from scripts.selftest.io import HarnessError, PublicAPI, text_value, write_json
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.product_mcp import ProductGeneration, _selection, _validate_request_budget
from scripts.selftest.run import _configure, _expectation

from app.schemas.self_tests import AgentTaskResponse, BatchResponse


async def configure_fixtures(
    observer: PublicAPI, task: AgentTaskResponse, materialized: HostMaterialization
) -> tuple[FixtureBudgetScope, str | None]:
    batch = task.batch
    if batch is None:
        raise HarnessError("HOST_PRODUCT_BATCH_MISSING")
    _validate_request_budget(materialized.assets, task.budget.max_requests)
    scope = FixtureBudgetScope(
        parent_batch_key=batch.batch_key,
        nonce=task.nonce,
        limit=task.budget.max_requests,
        expires_at=batch.deadline.timestamp(),
    )
    revisions = {(item.scenario_id, item.variant_key): item for item in materialized.revisions}
    epochs = []
    for asset in materialized.assets:
        if isinstance(asset, GeneratedAsset):
            if asset.scenario_id not in {"ST-MCP-025", "ST-MCP-026"}:
                raise HarnessError("HOST_SCENARIO_GOLDEN_UNSUPPORTED")
            epochs.append(
                await _configure(
                    observer,
                    text_value(revisions[(asset.scenario_id, asset.variant_key)].fixture_batch_key)
                    if revisions
                    else batch.batch_key,
                    asset.scenario_id,
                    task.nonce,
                    task.builds.fixture,
                    scope=scope,
                )
            )
    if len(set(epochs)) > 1:
        raise HarnessError("HOST_FIXTURE_EPOCH_CHANGED")
    return scope, epochs[0] if epochs else None


def freeze_product_expectations(
    task: AgentTaskResponse,
    ready: BatchResponse,
    materialized: HostMaterialization,
    scope: FixtureBudgetScope,
    epoch: str | None,
    directory: Path,
) -> BatchManifest:
    batch, frozen = task.batch, task.frozen_manifest
    if (
        batch is None
        or frozen is None
        or canonical_digest(frozen.model_dump(mode="json")) != batch.manifest_digest
    ):
        raise HarnessError("HOST_PRODUCT_FROZEN_MANIFEST_CHANGED")
    assets = tuple(item for item in materialized.assets if isinstance(item, GeneratedAsset))
    lifecycle = tuple(item for item in materialized.assets if isinstance(item, LifecycleAsset))
    if len(lifecycle) > 1:
        raise HarnessError("HOST_MULTIPLE_LIFECYCLE_ASSETS_UNSUPPORTED")
    generated = ProductGeneration(
        assets=assets,
        lifecycle=lifecycle[0] if lifecycle else None,
        catalog_digest=materialized.catalog_digest,
    )
    selection = _selection(ready, generated, directory)
    expectations = tuple(_expectation(asset, epoch or "", selection) for asset in assets)
    if lifecycle:
        expectations = (lifecycle_expectation(lifecycle[0], selection), *expectations)
    revisions = {(item.scenario_id, item.variant_key): item for item in materialized.revisions}
    expectations = tuple(
        item.model_copy(
            update={
                "fixture_batch_key": revisions[
                    (item.scenario_id, item.variant_key)
                ].fixture_batch_key
            }
        )
        if revisions
        and revisions[(item.scenario_id, item.variant_key)].fixture_batch_key is not None
        else item
        for item in expectations
    )
    manifest = BatchManifest(
        fixture_budget=scope,
        pack_id="flowtest-mcp-core",
        pack_version="1.0.0",
        pack_digest=frozen.template.pack_digest,
        policy_digest=batch.policy_digest,
        project_id=task.project_id,
        batch_key=batch.batch_key,
        nonce=task.nonce,
        builds=Builds.model_validate(task.builds.model_dump()),
        batch_kind="mcp_generated",
        generation_mode="host_llm_mcp",
        verification_scope=batch.verification_scope,
        expected_scenario_set=tuple(item.scenario_id for item in frozen.scenarios),
        required_scenario_set=tuple(item.scenario_id for item in batch.required_scenario_set),
        scenarios=expectations,
        fixture_epoch=epoch,
        created_at=batch.created_at,
        expires_at=batch.deadline,
    )
    write_json(directory / "product-generation.json", generated)
    write_json(directory / "manifest.json", manifest)
    return manifest
