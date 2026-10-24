"""Use the existing leased machine protocol; browser requests never spawn a host."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.generation_lifecycle import LifecycleAsset
from scripts.selftest.host_materialized import HostMaterialization
from scripts.selftest.host_sources import FrozenHostCase, FrozenHostSource
from scripts.selftest.io import HarnessError, PublicAPI, object_value, write_json
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.product_agent_client import agent_root, lease_body, upload
from scripts.selftest.product_mcp import _PendingReference, _refresh_proposal, _source

from app.schemas.self_tests import (
    AgentTaskResponse,
    ArtifactReference,
    BatchResponse,
    GenerationProgress,
    HostEvidence,
    MaterializedReceipt,
    ProposalReference,
    SourceReference,
)


def verify_task(task: AgentTaskResponse, materialized: HostMaterialization) -> None:
    batch = task.batch
    if batch is None or batch.generation_mode != "host_llm_mcp":
        raise HarnessError("HOST_PRODUCT_GENERATION_MODE_CHANGED")
    selected = {(item.scenario_id, item.variant_key) for item in materialized.assets}
    required = {(item.scenario_id, item.variant_key) for item in batch.required_scenario_set}
    if selected != required or len(selected) != len(materialized.assets):
        raise HarnessError("HOST_PRODUCT_REQUIRED_SET_CHANGED")
    revisions = {(item.scenario_id, item.variant_key): item for item in materialized.revisions}
    if any(
        (
            asset.api_source.project_id
            if isinstance(asset, GeneratedAsset)
            else asset.operations[0].api_source.project_id
        )
        != task.project_id
        or any(
            call.batch_key
            != (
                revisions[(asset.scenario_id, asset.variant_key)].origin_batch_key
                if revisions
                else batch.batch_key
            )
            for call in asset.calls
        )
        for asset in materialized.assets
    ):
        raise HarnessError("HOST_PRODUCT_TASK_BINDING_CHANGED")


async def publish_pending(
    machine: PublicAPI,
    reader: PublicAPI,
    task: AgentTaskResponse,
    *,
    tool_count: int,
    workflows: tuple[FrozenHostSource, ...],
    cases: tuple[FrozenHostCase, ...] = (),
) -> None:
    references = tuple(
        ProposalReference(
            change_set_id=item.proposal_id,
            item_id=None,
            route="flow_spec_visual",
            content_fingerprint=item.proposal_fingerprint,
            review_status="pending",
        )
        for item in workflows
    )
    if cases:
        references = (
            *references,
            *tuple(
                ProposalReference(
                    change_set_id=item.proposal_id,
                    item_id=item.item_id,
                    route="controlled_write",
                    content_fingerprint=item.proposal_fingerprint,
                    review_status="pending",
                )
                for item in cases
            ),
        )
    current = tuple(
        [
            (
                await _refresh_proposal(
                    reader, task.project_id, _PendingReference(reference=reference)
                )
            ).reference
            for reference in references
        ]
    )
    payload = GenerationProgress(
        **lease_body(task).model_dump(),
        stage="awaiting_review",
        readiness="needs_input",
        reason_codes=("SELFTEST_HUMAN_REVIEW_REQUIRED",),
        tool_call_count=tool_count,
        proposals=current,
    )
    await machine.object(
        "POST",
        f"{agent_root(task.project_id)}/runs/{task.task_id}/generation",
        object_value(payload.model_dump(mode="json")),
    )


async def publish_materialized(
    machine: PublicAPI,
    task: AgentTaskResponse,
    *,
    materialized: HostMaterialization,
    directory: Path,
) -> BatchResponse:
    verify_task(task, materialized)
    sources = []
    for asset in materialized.assets:
        content = json.dumps(
            asset.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        reference = await upload(
            machine,
            task,
            kind="generation",
            filename=asset.scenario_id + "-host-generation.json",
            content=content,
        )
        sources.append(materialized_source(materialized, asset, reference))
    trail_ref = await upload(
        machine,
        task,
        kind="generation",
        filename="host-trail.json",
        content=materialized.trail.model_dump_json().encode(),
    )
    write_json(
        directory / "host-materialized-index.json",
        {
            "attempt_id": str(materialized.attempt_id),
            "authorization_digest": materialized.authorization_digest,
            "task_digest": materialized.task_digest,
            "host": materialized.host.model_dump(mode="json"),
            "sources": [item.model_dump(mode="json") for item in sources],
            "host_trail": trail_ref.model_dump(mode="json"),
            "assets_digest": canonical_digest(
                [item.model_dump(mode="json") for item in materialized.assets]
            ),
        },
    )
    reference = await upload(
        machine,
        task,
        kind="generation",
        filename="host-materialized-index.json",
        content=(directory / "host-materialized-index.json").read_bytes(),
    )
    receipt = MaterializedReceipt(
        **lease_body(task).model_dump(), sources=tuple(sources), manifest=reference
    )
    return BatchResponse.model_validate(
        await machine.object(
            "POST",
            f"{agent_root(task.project_id)}/runs/{task.task_id}/materialized",
            object_value(receipt.model_dump(mode="json")),
        )
    )


def materialized_source(
    materialized: HostMaterialization,
    asset: GeneratedAsset | LifecycleAsset,
    reference: ArtifactReference,
) -> SourceReference:
    source = _source(asset, reference).model_copy(
        update={"host_evidence": HostEvidence.model_validate(materialized.host.model_dump())}
    )
    revisions = [
        item
        for item in materialized.revisions
        if (item.scenario_id, item.variant_key) == (asset.scenario_id, asset.variant_key)
    ]
    if revisions:
        if len(revisions) != 1:
            raise HarnessError("HOST_ASSISTED_SOURCE_DUPLICATE")
        source = source.model_copy(
            update={
                "assisted": revisions[0].lineage,
                "fixture_batch_key": revisions[0].fixture_batch_key,
            }
        )
    return source
