"""Fresh MCP generation and independent evidence connected to product task leases."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from scripts.selftest.bootstrap import BootstrapResult
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import collect_scenario, wait_plan
from scripts.selftest.collect_lifecycle_evidence import (
    collect_lifecycle_scenario,
    lifecycle_expectation,
)
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Builds,
    Contract,
    FixtureBudgetScope,
    ProposalEvidence,
    Sha256,
    canonical_digest,
)
from scripts.selftest.generation_lifecycle import LifecycleAsset, generate_lifecycle
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_generation_journey import GeneratedAsset, generate_canary
from scripts.selftest.product_agent_client import agent_root, lease_body, upload
from scripts.selftest.product_fixed import seal_verification
from scripts.selftest.request_bounds import native_request_bound
from scripts.selftest.review_driver import FixtureReviewDriver, HumanReviewDriver, PendingReview
from scripts.selftest.run import _configure, _expectation, _pack_digest, _protocol
from scripts.selftest.start_plan import PlanSelection, _frozen_case

from app.schemas.self_tests import (
    AgentTaskResponse,
    APISourceReference,
    ArtifactReference,
    BatchResponse,
    GenerationProgress,
    MaterializedReceipt,
    OracleReference,
    ProposalReference,
    PublishedAsset,
    SourceReference,
)


class ProductGeneration(Contract):
    assets: tuple[GeneratedAsset, ...]
    lifecycle: LifecycleAsset | None
    catalog_digest: str


def proposal_reference(value: ProposalEvidence | PendingReview) -> ProposalReference:
    return ProposalReference(
        change_set_id=value.proposal_id,
        item_id=value.item_id,
        route="flow_spec_visual" if value.route == "flow_spec" else "controlled_write",
        content_fingerprint=value.content_fingerprint,
        review_status="pending" if isinstance(value, PendingReview) else value.review_status,
        materialized_resource_id=None
        if isinstance(value, PendingReview)
        else value.materialized_resource_id,
    )


class _PendingReference(Contract):
    reference: ProposalReference
    source_digest: Sha256 | None = None


def _proposal_identity(project: UUID, reference: ProposalReference, change: JsonObject) -> None:
    if (
        change.get("id") != str(reference.change_set_id)
        or change.get("project_id") != str(project)
        or change.get("source_fingerprint") != reference.content_fingerprint
    ):
        raise HarnessError("SELFTEST_HUMAN_REVIEW_SOURCE_CHANGED")


async def _proposal_document(
    writer: PublicAPI, project: UUID, reference: ProposalReference
) -> tuple[JsonObject, JsonObject]:
    if reference.route == "flow_spec_visual":
        change = await writer.object(
            "GET", f"/projects/{project}/flow-specs/change-sets/{reference.change_set_id}"
        )
        _proposal_identity(project, reference, change)
        if reference.item_id is not None or change.get("source_type") != "flow_spec":
            raise HarnessError("SELFTEST_HUMAN_REVIEW_SOURCE_CHANGED")
        source = {
            key: change[key]
            for key in (
                "source_type",
                "source_ref",
                "spec",
                "target_workflow_id",
                "target_revision",
                "target_snapshot_sha256",
                "proposal_origin",
            )
        }
        return {
            "review_status": change["review_status"],
            "materialized_resource_id": change["materialized_workflow_id"],
        }, source
    change = object_value(
        (await writer.object("GET", f"/mcp/write/change-sets/{reference.change_set_id}"))["data"]
    )
    _proposal_identity(project, reference, change)
    cases = [item for item in objects_value(change["items"]) if item["item_type"] == "test_case"]
    if len(cases) != 1 or cases[0]["id"] != str(reference.item_id):
        raise HarnessError("SELFTEST_HUMAN_REVIEW_ITEM_AMBIGUOUS")
    item = cases[0]
    if (
        item.get("materialized_resource_id") is not None
        and item.get("materialized_resource_type") != "test_case"
    ):
        raise HarnessError("SELFTEST_HUMAN_REVIEW_SOURCE_CHANGED")
    return item, {
        "source_fingerprint": change["source_fingerprint"],
        "item": {
            key: item[key]
            for key in (
                "id",
                "item_type",
                "action",
                "target_resource_id",
                "proposed_content",
            )
        },
    }


async def _refresh_proposal(
    writer: PublicAPI, project: UUID, previous: _PendingReference
) -> _PendingReference:
    item, source = await _proposal_document(writer, project, previous.reference)
    digest = canonical_digest(source)
    if previous.source_digest is not None and previous.source_digest != digest:
        raise HarnessError("SELFTEST_HUMAN_REVIEW_SOURCE_CHANGED")
    status = item["review_status"]
    if status == "rejected":
        raise HarnessError("SELFTEST_HUMAN_REVIEW_REJECTED")
    if status not in {"pending", "accepted"}:
        raise HarnessError("SELFTEST_HUMAN_REVIEW_RECEIPT_INVALID")
    resource = item.get("materialized_resource_id")
    identifier = UUID(text_value(resource)) if resource is not None else None
    reference = previous.reference
    if (
        (reference.review_status == "accepted" and status != "accepted")
        or (
            reference.materialized_resource_id is not None
            and reference.materialized_resource_id != identifier
        )
        or (status == "pending" and identifier is not None)
    ):
        raise HarnessError("SELFTEST_HUMAN_REVIEW_SOURCE_CHANGED")
    current = reference.model_copy(
        update={"review_status": status, "materialized_resource_id": identifier}
    )
    return _PendingReference(reference=current, source_digest=digest)


def _append_pending(
    proposals: list[_PendingReference], project: UUID, value: PendingReview
) -> None:
    if (
        value.project_id != project
        or any(item.reference.change_set_id == value.proposal_id for item in proposals)
        or len(proposals) >= 100
    ):
        raise HarnessError("SELFTEST_HUMAN_REVIEW_ITEM_AMBIGUOUS")
    proposals.append(_PendingReference(reference=proposal_reference(value)))


async def _current_progress(
    machine: PublicAPI,
    writer: PublicAPI,
    task: AgentTaskResponse,
    proposals: list[_PendingReference],
    count: int,
) -> None:
    # Acceptance can race the GET. Only a strict, uncommitted status conflict
    # gets a bounded re-read; arbitrary progress failures are never retried.
    for attempt in range(3):
        if task.batch is None or datetime.now(UTC) >= task.batch.deadline:
            raise HarnessError("SELFTEST_HUMAN_REVIEW_DEADLINE_EXPIRED")
        proposals[:] = [
            await _refresh_proposal(writer, task.project_id, item) for item in proposals
        ]
        try:
            await _progress(machine, task, tuple(item.reference for item in proposals), count)
            return
        except HarnessError as error:
            if (
                not str(error).startswith("SELFTEST_HTTP_409:SELFTEST_PROPOSAL_REVIEW_MISMATCH:")
                or attempt == 2
            ):
                raise


async def _progress(
    machine: PublicAPI,
    task: AgentTaskResponse,
    proposals: tuple[ProposalReference, ...],
    count: int,
    *,
    blocked: bool = False,
) -> None:
    payload = GenerationProgress(
        **lease_body(task).model_dump(),
        stage="blocked" if blocked else "awaiting_review",
        readiness="blocked" if blocked else "needs_review",
        reason_codes=("WAITING_FOR_HOST",) if blocked else (),
        tool_call_count=count,
        proposals=proposals,
    )
    await machine.object(
        "POST",
        f"{agent_root(task.project_id)}/runs/{task.task_id}/generation",
        object_value(payload.model_dump(mode="json")),
    )


def _source(
    asset: GeneratedAsset | LifecycleAsset, reference: ArtifactReference
) -> SourceReference:
    workflow, case = asset.workflow, asset.case
    origins = (
        (asset.api_source,)
        if isinstance(asset, GeneratedAsset)
        else tuple(item.api_source for item in asset.operations)
    )
    apis = tuple(APISourceReference.model_validate(item.model_dump()) for item in origins)
    oracles = tuple(
        OracleReference.model_validate(item.model_dump()) for item in asset.oracle_bindings
    )
    return SourceReference(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        workflow=PublishedAsset(
            id=UUID(text_value(workflow.workflow["id"])),
            version=integer_value(workflow.version["version"]),
            fingerprint=text_value(workflow.version["fingerprint"]),
        ),
        case=PublishedAsset(
            id=UUID(text_value(case.case["id"])),
            version=integer_value(case.version["version"]),
            fingerprint=text_value(case.version["fingerprint"]),
        ),
        design_fingerprint=asset.design_fingerprint
        if isinstance(asset, GeneratedAsset)
        else asset.combined_design_fingerprint,
        compilation_fingerprint=asset.compilation_fingerprint,
        oracle_mapping_digest=canonical_digest([item.model_dump(mode="json") for item in oracles]),
        workflow_proposal=proposal_reference(workflow.proposal),
        case_proposal=proposal_reference(case.proposal),
        api_sources_digest=canonical_digest([item.model_dump(mode="json") for item in apis]),
        api_sources=apis,
        oracle_bindings=oracles,
        protocol_receipts_digest=canonical_digest(
            [item.model_dump(mode="json") for item in asset.calls]
        ),
        generation_manifest=reference,
    )


def _selection(
    batch: BatchResponse, generated: ProductGeneration, directory: Path
) -> PlanSelection:
    snapshot = batch.resource_snapshot
    if snapshot is None:
        raise HarnessError("SELFTEST_AGENT_RESOURCE_SNAPSHOT_MISSING")
    cases = tuple(asset.case for asset in generated.assets)
    if generated.lifecycle is not None:
        cases = (generated.lifecycle.case, *cases)
    frozen = tuple(
        _frozen_case(case, str(snapshot.suite.id), snapshot.suite.version) for case in cases
    )
    actual = {
        (item.case.id, item.case.version, item.target_snapshot_digest) for item in snapshot.cases
    }
    expected = {(item.case_id, item.version, item.target_snapshot_digest) for item in frozen}
    if actual != expected or len(snapshot.cases) != len(cases):
        raise HarnessError("SELFTEST_AGENT_PUBLISHED_CASE_SET_MISMATCH")
    result = PlanSelection(
        project_id=batch.project_id,
        suite_id=snapshot.suite.id,
        suite_version=snapshot.suite.version,
        suite_fingerprint=snapshot.suite.fingerprint,
        plan_id=snapshot.plan_id,
        cases=frozen,
        frozen_at=datetime.now(UTC),
    )
    write_json(directory / "selection.json", result)
    return result


def _validate_request_budget(
    assets: tuple[GeneratedAsset | LifecycleAsset, ...], maximum: int
) -> None:
    bound = sum(
        native_request_bound(object_value(asset.workflow.version["definition"])) for asset in assets
    )
    if bound > maximum:
        raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")


async def generate_task(
    machine: PublicAPI,
    writer: PublicAPI,
    observer: PublicAPI,
    *,
    task: AgentTaskResponse,
    stack: StackBinding,
    boot: BootstrapResult,
    directory: Path,
    review_mode: Literal["human", "ci_fixture", "ui_fixture"],
) -> None:
    batch, frozen = task.batch, task.frozen_manifest
    if (
        batch is None
        or frozen is None
        or canonical_digest(frozen.model_dump(mode="json")) != batch.manifest_digest
    ):
        raise HarnessError("SELFTEST_AGENT_FROZEN_MANIFEST_MISMATCH")
    if batch.generation_mode != "deterministic_mcp":
        await _progress(machine, task, (), 0, blocked=True)
        raise HarnessError("SELFTEST_MODEL_HOST_NOT_REGISTERED")
    if frozen.template.pack_digest != _pack_digest():
        raise HarnessError("SELFTEST_AGENT_GENERATION_PACK_MISMATCH")
    selected = {item.scenario_id for item in frozen.scenarios}
    proposals: list[_PendingReference] = []
    async with _protocol(
        stack, "stdio", boot.credentials.mcp_token, batch.batch_key, directory
    ) as client:
        client.max_tool_calls = task.budget.max_tool_calls

        async def pending(value: PendingReview) -> None:
            _append_pending(proposals, task.project_id, value)
            await _current_progress(machine, writer, task, proposals, len(client.receipts))

        review = (
            HumanReviewDriver(
                batch.deadline,
                pending,
                review_mode="ci_fixture" if review_mode == "ui_fixture" else "human",
            )
            if review_mode in {"human", "ui_fixture"}
            else FixtureReviewDriver()
        )
        await client.call(
            "flowtest.inspect_connection", {"request": {}}, scenario_id="batch", phase="connection"
        )
        assets = tuple(
            [
                await generate_canary(
                    client,
                    writer,
                    installation=boot.installation,
                    scenario_id=scenario,
                    expected_actual=expected,
                    output_dir=directory / scenario,
                    review_driver=review,
                )
                for scenario, expected in (("ST-MCP-025", 2), ("ST-MCP-026", 1))
                if scenario in selected
            ]
        )
        lifecycle = (
            await generate_lifecycle(
                client,
                writer,
                installation=boot.installation,
                binding=stack,
                batch_key=batch.batch_key,
                output_dir=directory / "ST-MCP-023",
                review_driver=review,
            )
            if "ST-MCP-023" in selected
            else None
        )
        generated = ProductGeneration(
            assets=assets, lifecycle=lifecycle, catalog_digest=client.catalog_digest
        )
    write_json(directory / "product-generation.json", generated)
    all_assets: tuple[GeneratedAsset | LifecycleAsset, ...] = (
        *((lifecycle,) if lifecycle else ()),
        *assets,
    )
    _validate_request_budget(all_assets, task.budget.max_requests)
    scope = FixtureBudgetScope(
        parent_batch_key=batch.batch_key,
        nonce=task.nonce,
        limit=500,
        expires_at=batch.deadline.timestamp(),
    )
    epochs: list[str] = []
    for scenario in ("ST-MCP-025", "ST-MCP-026"):
        if scenario in selected:
            epochs.append(
                await _configure(
                    observer,
                    batch.batch_key,
                    scenario,
                    task.nonce,
                    task.builds.fixture,
                    scope=scope,
                )
            )
    if len(set(epochs)) > 1:
        raise HarnessError("SELFTEST_FIXTURE_EPOCH_CHANGED")
    sources: list[SourceReference] = []
    for asset in all_assets:
        content = asset.model_dump_json().encode()
        reference = await upload(
            machine,
            task,
            kind="generation",
            filename=f"{asset.scenario_id}-generation.json",
            content=content,
        )
        sources.append(_source(asset, reference))
    write_json(
        directory / "generation-sources.json",
        {"sources": [item.model_dump(mode="json") for item in sources]},
    )
    reference = await upload(
        machine,
        task,
        kind="generation",
        filename="generation-sources.json",
        content=(directory / "generation-sources.json").read_bytes(),
    )
    payload = MaterializedReceipt(
        **lease_body(task).model_dump(), sources=tuple(sources), manifest=reference
    )
    ready = BatchResponse.model_validate(
        await machine.object(
            "POST",
            f"{agent_root(task.project_id)}/runs/{task.task_id}/materialized",
            object_value(payload.model_dump(mode="json")),
        )
    )
    selection = _selection(ready, generated, directory)
    expectations = tuple(_expectation(asset, epochs[0], selection) for asset in assets)
    if lifecycle is not None:
        expectations = (lifecycle_expectation(lifecycle, selection), *expectations)
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
        generation_mode="deterministic_mcp",
        verification_scope=batch.verification_scope,
        expected_scenario_set=tuple(item.scenario_id for item in frozen.scenarios),
        required_scenario_set=tuple(item.scenario_id for item in batch.required_scenario_set),
        scenarios=expectations,
        fixture_epoch=epochs[0] if epochs else None,
        created_at=batch.created_at,
        expires_at=batch.deadline,
    )
    write_json(directory / "manifest.json", manifest)


async def observe_task(
    machine: PublicAPI,
    writer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    task: AgentTaskResponse,
    stack: StackBinding,
    boot: BootstrapResult,
    directory: Path,
) -> None:
    batch = task.batch
    if batch is None or len(batch.plan_run_ids) != 1:
        raise HarnessError("SELFTEST_AGENT_RUN_SET_INVALID")
    manifest = BatchManifest.model_validate(read_json(directory / "manifest.json"))
    generated = ProductGeneration.model_validate(read_json(directory / "product-generation.json"))
    selection = PlanSelection.model_validate(read_json(directory / "selection.json"))
    run = await wait_plan(reader, str(task.project_id), str(batch.plan_run_ids[0]), batch.deadline)
    if run["test_plan_id"] != str(selection.plan_id):
        raise HarnessError("SELFTEST_AGENT_PLAN_CHANGED")
    items = objects_value(run["items"])
    if len(items) != len(selection.cases):
        raise HarnessError("SELFTEST_AGENT_PLAN_ITEM_SET_MISMATCH")
    cleanup = RoundCleanup(
        batch_key=batch.batch_key,
        project_id=task.project_id,
        output_dir=directory,
        writer=writer,
        reader=reader,
        observer=observer,
        nonce=task.nonce,
        fixture_digest=task.builds.fixture,
    )
    cleanup.arm_plan(selection.plan_id, tuple(item.case_id for item in selection.cases))
    cleanup.started_plan(batch.plan_run_ids[0])
    cleanup.plan.observe(run)
    observations = []
    for asset in generated.assets:
        cleanup.register_fixture(asset.scenario_id)
        observations.append(
            await collect_scenario(
                reader,
                observer,
                asset=asset,
                run=run,
                item=next(item for item in items if item["target_id"] == asset.case.case["id"]),
                batch_key=batch.batch_key,
                catalog_digest=generated.catalog_digest,
                expected_target_snapshot_digest=next(
                    item.target_snapshot_digest
                    for item in selection.cases
                    if str(item.case_id) == asset.case.case["id"]
                ),
                selection=selection,
                output_dir=directory / asset.scenario_id,
                deadline=manifest.expires_at,
            )
        )
    lifecycle = generated.lifecycle
    if lifecycle is not None:
        target_reader = PublicAPI(
            stack.target_url,
            boot.credentials.target_viewer_token,
            str(boot.installation.target_organization_id),
        )
        try:
            observed = await collect_lifecycle_scenario(
                reader,
                target_reader,
                capture_reader=reader,
                bounded_capture=True,
                asset=lifecycle,
                run=run,
                item=next(item for item in items if item["target_id"] == lifecycle.case.case["id"]),
                batch_key=batch.batch_key,
                catalog_digest=generated.catalog_digest,
                expected_target_snapshot_digest=next(
                    item.target_snapshot_digest
                    for item in selection.cases
                    if str(item.case_id) == lifecycle.case.case["id"]
                ),
                output_dir=directory / lifecycle.scenario_id,
                selection=selection,
            )
            observations.insert(0, observed)
        finally:
            await target_reader.close()
    cleaned = await cleanup.finish()
    observations = [
        item.model_copy(update={"cleanup_status": cleaned.status})
        if item.scenario_id != "ST-MCP-023"
        else item
        for item in observations
    ]
    status = (
        "completed"
        if all(item.cleanup_status == "completed" for item in observations)
        else "needs_review"
    )
    evidence = BatchEvidence(
        batch_key=batch.batch_key,
        nonce=task.nonce,
        pack_digest=manifest.pack_digest,
        policy_digest=manifest.policy_digest,
        builds=manifest.builds,
        collected_at=datetime.now(UTC),
        scenarios=tuple(observations),
        cleanup_status=status,
    )
    await seal_verification(machine, task, manifest, evidence, directory)
