"""Independent host O: task-bound A reads, synthetic M journal, read-only B postcondition."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from scripts.selftest.bootstrap import BootstrapResult
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import collect_scenario, wait_plan
from scripts.selftest.collect_lifecycle_evidence import collect_lifecycle_scenario
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    FixtureBudgetScope,
    ScenarioObservation,
    VerificationReport,
    canonical_digest,
)
from scripts.selftest.generation_lifecycle import LifecycleAsset
from scripts.selftest.host_assisted_verify import AssistedValidation, validate_assisted
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.host_materialized import HostMaterialization
from scripts.selftest.host_product_bridge import materialized_source
from scripts.selftest.host_product_prepare import freeze_product_expectations
from scripts.selftest.host_prompts import HostTask
from scripts.selftest.host_quality_evidence import materialized_quality
from scripts.selftest.host_quality_history import QualityHistory
from scripts.selftest.host_runtime_config import HostRuntimeConfig
from scripts.selftest.host_verify import evaluate_host_batch
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    read_json,
    write_json,
)
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.product_agent_client import AgentIdentity, lease_body, upload
from scripts.selftest.product_evidence import TaskEvidenceReader
from scripts.selftest.run import _execution_junit
from scripts.selftest.start_plan import PlanSelection
from scripts.selftest.verify import write_report

from app.schemas.self_tests import (
    AgentTaskResponse,
    ArtifactKind,
    VerificationReceipt,
    VerificationScenario,
)


async def observe_task(
    machine: PublicAPI,
    reader: TaskEvidenceReader,
    observer: PublicAPI,
    *,
    task: AgentTaskResponse,
    stack: StackBinding,
    boot: BootstrapResult,
    directory: Path,
    grant: VerifiedGrant,
    frozen_task: HostTask,
    quality_root: Path | None = None,
    quality_signer: AgentIdentity | None = None,
    host_config: HostRuntimeConfig | None = None,
) -> VerificationReport:
    if not isinstance(reader, TaskEvidenceReader):
        raise HarnessError("HOST_OBSERVER_REQUIRES_LEASE_BOUND_READER")
    if quality_root is None or quality_signer is None:
        raise HarnessError("HOST_QUALITY_HISTORY_CONFIGURATION_REQUIRED")
    history = QualityHistory.for_task(
        quality_root, grant, frozen_task.quality_taskset, quality_signer.principal
    )
    history.report(signer=quality_signer)
    batch = task.batch
    if batch is None or batch.generation_mode != "host_llm_mcp" or len(batch.plan_run_ids) != 1:
        raise HarnessError("HOST_OBSERVER_BATCH_INVALID")
    materialized = HostMaterialization.model_validate(
        read_json(directory / "host-materialized.json")
    )
    manifest = BatchManifest.model_validate(read_json(directory / "manifest.json"))
    selection = PlanSelection.model_validate(read_json(directory / "selection.json"))
    if (
        manifest.generation_mode != "host_llm_mcp"
        or materialized.authorization_digest != grant.digest
    ):
        raise HarnessError("HOST_OBSERVER_FROZEN_AUTHORIZATION_CHANGED")
    _independent_manifest(task, materialized, manifest, selection, frozen_task, grant, directory)
    validated, fixture_batch_key = _assisted_context(
        task, materialized, manifest, frozen_task, grant, host_config, directory
    )
    run = await wait_plan(reader, str(task.project_id), str(batch.plan_run_ids[0]), batch.deadline)
    if run["test_plan_id"] != str(selection.plan_id):
        raise HarnessError("HOST_OBSERVER_PLAN_CHANGED")
    # TaskEvidenceReader rejects mutations; H's separate watchdog owns cancellation.
    cleanup = RoundCleanup(
        batch_key=fixture_batch_key,
        project_id=task.project_id,
        output_dir=directory,
        writer=reader,
        reader=reader,
        observer=observer,
        nonce=task.nonce,
        fixture_digest=task.builds.fixture,
    )
    cleanup.arm_plan(selection.plan_id, tuple(item.case_id for item in selection.cases))
    cleanup.started_plan(batch.plan_run_ids[0])
    cleanup.plan.observe(run)
    observations = []
    for asset in materialized.assets:
        if isinstance(asset, GeneratedAsset):
            cleanup.register_fixture(asset.scenario_id)
        observed = await _collect(
            reader,
            observer,
            task,
            stack,
            boot,
            asset,
            run,
            selection,
            materialized.catalog_digest,
            directory,
        )
        source = observed.provenance
        if source is None:
            raise HarnessError("HOST_OBSERVER_PROVENANCE_MISSING")
        observations.append(
            observed.model_copy(
                update={
                    "provenance": source.model_copy(
                        update={
                            "generation_mode": "host_llm_mcp",
                            "host": materialized.host,
                            "batch_key": batch.batch_key,
                            "assisted": bool(materialized.revisions),
                        }
                    )
                }
            )
        )
    cleaned = await cleanup.finish()
    observations = [
        item.model_copy(
            update={"cleanup_status": "completed" if cleaned.status == "completed" else "pending"}
        )
        if isinstance(asset, GeneratedAsset)
        else item
        for asset, item in zip(materialized.assets, observations, strict=True)
    ]
    status: Literal["completed", "pending"] = (
        "completed"
        if all(item.cleanup_status == "completed" for item in observations)
        else "pending"
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
    if validated is not None:
        from scripts.selftest.host_assisted_verify import evaluate_assisted_batch

        verification = evaluate_assisted_batch(manifest, evidence, validated=validated)
    else:
        verification = evaluate_host_batch(
            manifest, evidence, trail=materialized.trail, grant=grant
        )
    report = verification.report
    current_quality = materialized_quality(
        frozen_task.quality_taskset, materialized, evidence, verification
    )
    quality = history.finish(
        grant, materialized.attempt_id, current_quality.attempts, signer=quality_signer
    )
    write_json(directory / "host-quality.json", quality)
    await _seal(machine, task, manifest, evidence, report, directory)
    return report


def _assisted_context(
    task: AgentTaskResponse,
    materialized: HostMaterialization,
    manifest: BatchManifest,
    frozen_task: HostTask,
    grant: VerifiedGrant,
    host_config: HostRuntimeConfig | None,
    directory: Path,
) -> tuple[AssistedValidation | None, str]:
    batch = task.batch
    if batch is None:
        raise HarnessError("HOST_OBSERVER_BATCH_INVALID")
    validated = None
    if materialized.revisions:
        if host_config is None:
            raise HarnessError("HOST_ASSISTED_ARCHIVE_CONFIGURATION_REQUIRED")
        validated = validate_assisted(
            task, materialized, frozen_task, grant, host_config, directory, manifest
        )
    fixture_keys = {
        item.fixture_batch_key
        for item in materialized.revisions
        if item.fixture_batch_key is not None
    }
    if len(fixture_keys) > 1:
        raise HarnessError("HOST_ASSISTED_MIXED_FIXTURE_NAMESPACES")
    return validated, next(iter(fixture_keys), batch.batch_key)


def _independent_manifest(
    task: AgentTaskResponse,
    materialized: HostMaterialization,
    manifest: BatchManifest,
    selection: PlanSelection,
    frozen_task: HostTask,
    grant: VerifiedGrant,
    directory: Path,
) -> None:
    batch = task.batch
    if (
        batch is None
        or canonical_digest(frozen_task.model_dump(mode="json")) != grant.authorization.task_digest
    ):
        raise HarnessError("HOST_OBSERVER_TASK_CHANGED")
    if bool(materialized.revisions) != (frozen_task.assisted is not None):
        raise HarnessError("HOST_ASSISTED_GENERATION_KIND_CHANGED")
    _frozen_sources(task, materialized)
    selected = {(item.scenario_id, item.variant_key): item for item in frozen_task.selections}
    actual = {(item.scenario_id, item.variant_key): item for item in materialized.assets}
    if set(selected) != set(actual):
        raise HarnessError("HOST_OBSERVER_REQUIRED_ASSET_SET_CHANGED")
    for key, asset in actual.items():
        wanted = selected[key]
        apis = (
            (asset.api_source,)
            if isinstance(asset, GeneratedAsset)
            else tuple(item.api_source for item in asset.operations)
        )
        if apis != (wanted.api_source, *wanted.additional_api_sources):
            raise HarnessError("HOST_OBSERVER_AUTHORIZED_API_SET_CHANGED")
        if not isinstance(asset, GeneratedAsset):
            frozen = wanted.lifecycle
            if frozen is None or any(
                getattr(asset, name) != value for name, value in frozen.model_dump().items()
            ):
                raise HarnessError("HOST_OBSERVER_LIFECYCLE_INPUT_CHANGED")
    scope = FixtureBudgetScope(
        parent_batch_key=batch.batch_key,
        nonce=task.nonce,
        limit=task.budget.max_requests,
        expires_at=batch.deadline.timestamp(),
    )
    rebuilt = freeze_product_expectations(
        task, batch, materialized, scope, manifest.fixture_epoch, directory / "observer-freeze"
    )
    if rebuilt != manifest:
        raise HarnessError("HOST_OBSERVER_INDEPENDENT_MANIFEST_CHANGED")
    independent = PlanSelection.model_validate(
        read_json(directory / "observer-freeze" / "selection.json")
    )
    if independent.model_dump(exclude={"frozen_at"}) != selection.model_dump(exclude={"frozen_at"}):
        raise HarnessError("HOST_OBSERVER_FROZEN_SELECTION_CHANGED")


def _frozen_sources(task: AgentTaskResponse, materialized: HostMaterialization) -> None:
    batch = task.batch
    if batch is None:
        raise HarnessError("HOST_OBSERVER_FROZEN_SOURCE_BATCH_MISSING")
    expected = {(item.scenario_id, item.variant_key): item for item in task.sources}
    actual = {(item.scenario_id, item.variant_key): item for item in materialized.assets}
    if (
        set(expected) != set(actual)
        or len(expected) != len(task.sources)
        or len(actual) != len(materialized.assets)
    ):
        raise HarnessError("HOST_OBSERVER_FROZEN_SOURCE_SET_CHANGED")
    for key, asset in actual.items():
        frozen = expected[key]
        reference = frozen.generation_manifest
        digest = canonical_digest(asset.model_dump(mode="json"))
        if reference.kind != "generation" or digest != reference.sha256:
            raise HarnessError("HOST_OBSERVER_FROZEN_SOURCE_ARTIFACT_CHANGED")
        source = materialized_source(materialized, asset, reference)
        if source != frozen:
            raise HarnessError("HOST_OBSERVER_FROZEN_SOURCE_CHANGED")


async def _collect(
    reader: TaskEvidenceReader,
    observer: PublicAPI,
    task: AgentTaskResponse,
    stack: StackBinding,
    boot: BootstrapResult,
    asset: GeneratedAsset | LifecycleAsset,
    run: JsonObject,
    selection: PlanSelection,
    catalog: str,
    directory: Path,
) -> ScenarioObservation:
    batch = task.batch
    if batch is None:
        raise HarnessError("HOST_OBSERVER_BATCH_REQUIRED")
    matches = [
        item for item in objects_value(run["items"]) if item["target_id"] == asset.case.case["id"]
    ]
    if len(matches) != 1:
        raise HarnessError("HOST_OBSERVER_CASE_ITEM_CHANGED")
    expected = next(
        item.target_snapshot_digest
        for item in selection.cases
        if str(item.case_id) == asset.case.case["id"]
    )
    if isinstance(asset, GeneratedAsset):
        return await collect_scenario(
            reader,
            observer,
            asset=asset,
            run=run,
            item=matches[0],
            batch_key=next(
                (
                    item.fixture_batch_key
                    for item in task.sources
                    if (item.scenario_id, item.variant_key)
                    == (asset.scenario_id, asset.variant_key)
                    and item.fixture_batch_key is not None
                ),
                batch.batch_key,
            ),
            catalog_digest=catalog,
            expected_target_snapshot_digest=expected,
            selection=selection,
            output_dir=directory / asset.scenario_id,
            deadline=batch.deadline,
        )
    target = PublicAPI(
        stack.target_url,
        boot.credentials.target_viewer_token,
        str(boot.installation.target_organization_id),
    )
    try:
        return await collect_lifecycle_scenario(
            reader,
            target,
            capture_reader=reader,
            bounded_capture=True,
            asset=asset,
            run=run,
            item=matches[0],
            batch_key=batch.batch_key,
            catalog_digest=catalog,
            expected_target_snapshot_digest=expected,
            selection=selection,
            output_dir=directory / asset.scenario_id,
        )
    finally:
        await target.close()


async def _seal(
    machine: PublicAPI,
    task: AgentTaskResponse,
    manifest: BatchManifest,
    evidence: BatchEvidence,
    report: VerificationReport,
    directory: Path,
) -> None:
    batch = task.batch
    if batch is None or batch.resource_digest is None:
        raise HarnessError("HOST_OBSERVER_RESOURCE_DIGEST_REQUIRED")
    write_json(directory / "evidence.json", evidence)
    _execution_junit(list(evidence.scenarios), directory)
    write_report(report, directory)
    files: tuple[tuple[ArtifactKind, str], ...] = (
        ("manifest", "manifest.json"),
        ("evidence", "evidence.json"),
        ("verification", "verification.json"),
        ("execution_junit", "execution.junit.xml"),
        ("verification_junit", "verification.junit.xml"),
    )
    references = tuple(
        [
            await upload(
                machine, task, kind=kind, filename=name, content=(directory / name).read_bytes()
            )
            for kind, name in files
        ]
    )
    quality_ref = await upload(
        machine,
        task,
        kind="generation",
        filename="host-quality.json",
        content=(directory / "host-quality.json").read_bytes(),
    )
    references = (*references, quality_ref)
    receipt = VerificationReceipt(
        **lease_body(task).model_dump(),
        manifest_digest=batch.manifest_digest,
        resource_digest=batch.resource_digest,
        policy_digest=batch.policy_digest,
        builds=task.builds,
        batch_verdict=report.batch_verdict,
        evidence_integrity=report.evidence_integrity,
        batch_reason_codes=tuple(item.code for item in report.findings),
        cleanup_status=evidence.cleanup_status,
        scenarios=tuple(
            VerificationScenario(
                scenario_id=item.scenario_id,
                variant_key=item.variant_key,
                observed_status=item.observed_status,
                verification_status=item.verification_status,
                reason_codes=tuple(f.code for f in item.findings),
                evidence_refs=references[1:3],
            )
            for item in report.scenarios
        ),
        artifacts=references,
    )
    await machine.object(
        "POST",
        f"/ci/projects/{task.project_id}/self-test-runs/{task.task_id}/verification",
        object_value(receipt.model_dump(mode="json")),
    )
