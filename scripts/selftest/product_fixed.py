"""Fixed-pack installation/preparation and independent observation for product batches."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import Installation
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import journal, wait_plan
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Builds,
    FixtureBudgetScope,
    canonical_digest,
)
from scripts.selftest.fixed_baseline import (
    CorePack,
    _collect_fixed,
    _execution_junit,
    install_fixed_baseline,
    load_core_pack,
)
from scripts.selftest.fixed_recovery import PreparedFixedAssets, recover_fixed_assets
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    object_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.product_agent_client import agent_root, lease_body, upload
from scripts.selftest.request_bounds import native_request_bound
from scripts.selftest.verify import verify_batch, write_report

from app.schemas.self_tests import (
    AgentTaskResponse,
    ArtifactKind,
    InstallationMapping,
    InstallationReceipt,
    PublishedAsset,
    ScenarioAssets,
    VerificationReceipt,
    VerificationScenario,
)


def fixed_pack(identifier: str) -> CorePack:
    if identifier == "core-v1":
        return load_core_pack()
    if identifier == "extended-v1":
        return load_core_pack(Path(__file__).resolve().parents[2] / "selftest/packs/extended-v1")
    raise HarnessError("SELFTEST_AGENT_FIXED_TEMPLATE_UNSUPPORTED")


async def install_task(
    machine: PublicAPI,
    writer: PublicAPI,
    *,
    task: AgentTaskResponse,
    installation: Installation,
    directory: Path,
) -> None:
    assets: tuple[ScenarioAssets, ...] = ()
    if task.installation.template_id != "mcp-core-v1":
        pack = fixed_pack(task.installation.template_id)
        if pack.digest != task.installation.pack_digest:
            raise HarnessError("SELFTEST_AGENT_FIXED_PACK_DIGEST_MISMATCH")
        fixed = await install_fixed_baseline(
            writer,
            project_id=str(task.project_id),
            environment_id=str(installation.fixture_environment_id),
            service_id=str(installation.fixture_service_id),
            batch_key=f"install-{task.task_id.hex}",
            nonce=task.nonce,
            output_dir=directory,
            pack=pack,
            dynamic_batch=True,
        )
        assets = tuple(
            ScenarioAssets(
                scenario_id=item.scenario_id,
                workflow=PublishedAsset(
                    id=item.workflow_id,
                    version=item.workflow_version,
                    fingerprint=item.workflow_fingerprint,
                ),
                case=PublishedAsset(
                    id=item.case_id, version=item.case_version, fingerprint=item.case_fingerprint
                ),
            )
            for item in fixed.assets
        )
    if installation.target_organization_id is None:
        raise HarnessError("SELFTEST_AGENT_TARGET_ORGANIZATION_MISSING")
    mapping = InstallationMapping(
        environment_id=installation.fixture_environment_id,
        target_environment_id=installation.target_environment_id,
        fixture_service_id=installation.fixture_service_id,
        target_service_id=installation.target_service_id,
        target_project_id=installation.target_project_id,
        target_organization_id=installation.target_organization_id,
        target_user_id=installation.target_user_id,
        target_instance_id=f"target-{installation.binding_nonce}",
        target_build_digest=task.builds.target,
        assets=assets,
    )
    receipt = InstallationReceipt(
        **lease_body(task).model_dump(),
        environment_fingerprint=task.environment_fingerprint,
        mapping=mapping,
    )
    await machine.object(
        "POST",
        f"{agent_root(task.project_id)}/installations/{task.task_id}/receipt",
        object_value(receipt.model_dump(mode="json")),
    )


def selected_pack(task: AgentTaskResponse) -> CorePack:
    frozen = task.frozen_manifest
    if frozen is None or task.batch is None:
        raise HarnessError("SELFTEST_AGENT_FROZEN_MANIFEST_MISSING")
    pack = fixed_pack(frozen.template.id)
    if (
        pack.digest != frozen.template.pack_digest
        or canonical_digest(frozen.model_dump(mode="json")) != task.batch.manifest_digest
    ):
        raise HarnessError("SELFTEST_AGENT_FROZEN_MANIFEST_MISMATCH")
    expected = tuple(item.scenario_id for item in frozen.scenarios)
    if (
        not expected
        or len(expected) != len(set(expected))
        or not set(expected) <= set(pack.manifest.scenario_ids)
    ):
        raise HarnessError("SELFTEST_AGENT_FROZEN_SCENARIOS_INVALID")
    bounds = sum(
        native_request_bound(item.definition)
        for item in pack.workflows
        if item.scenario_id in expected
    )
    if bounds > task.budget.max_requests:
        raise HarnessError("SELFTEST_REQUEST_BUDGET_UNSUPPORTED")
    return pack.model_copy(
        update={
            "apis": tuple(item for item in pack.apis if item.scenario_id in expected),
            "workflows": tuple(item for item in pack.workflows if item.scenario_id in expected),
            "fixtures": tuple(item for item in pack.fixtures if item.scenario_id in expected),
            "expectations": tuple(
                item for item in pack.expectations if item.scenario_id in expected
            ),
            "manifest": pack.manifest.model_copy(update={"scenario_ids": expected}),
        }
    )


async def prepare_task(
    machine: PublicAPI,
    observer: PublicAPI,
    task: AgentTaskResponse,
    *,
    directory: Path,
    installation_directory: Path,
    asset_reader: PublicAPI | None = None,
) -> None:
    pack = selected_pack(task)
    batch = task.batch
    if batch is None:
        raise HarnessError("SELFTEST_AGENT_BATCH_MISSING")
    if asset_reader is None:
        raise HarnessError("SELFTEST_FIXED_RECOVERY_READER_REQUIRED")
    installed = await recover_fixed_assets(
        asset_reader, task, fixed_pack(task.installation.template_id)
    )
    write_json(directory / "installation.json", installed)
    scope = FixtureBudgetScope(
        parent_batch_key=batch.batch_key,
        nonce=task.nonce,
        expires_at=batch.deadline.timestamp(),
    )
    for fixture in pack.fixtures:
        await observer.request(
            "PUT",
            f"/selftest/batches/{batch.batch_key}/scenarios/{fixture.scenario_id}",
            {
                "nonce": task.nonce,
                "fixture_digest": task.builds.fixture,
                "ttl_seconds": max(1, int((batch.deadline - datetime.now(UTC)).total_seconds())),
                "max_entries": 100,
                "max_bytes": 131072,
                "budget_scope": scope.model_dump(mode="json"),
                **fixture.fixture.model_dump(mode="json"),
            },
        )
    empty = await journal(observer, batch.batch_key, pack.fixtures[0].scenario_id)
    if empty.request_count or empty.expired or empty.truncated:
        raise HarnessError("SELFTEST_AGENT_FIXTURE_NOT_FRESH")
    manifest = BatchManifest(
        fixture_budget=scope,
        pack_id=pack.manifest.pack_id,
        pack_version=pack.manifest.pack_version,
        pack_digest=pack.digest,
        policy_digest=batch.policy_digest,
        project_id=task.project_id,
        batch_key=batch.batch_key,
        nonce=task.nonce,
        builds=Builds.model_validate(task.builds.model_dump()),
        batch_kind="fixed_baseline",
        verification_scope=batch.verification_scope,
        expected_scenario_set=pack.manifest.scenario_ids,
        required_scenario_set=tuple(item.scenario_id for item in batch.required_scenario_set),
        scenarios=pack.expectations,
        fixture_epoch=empty.fixture_epoch,
        created_at=batch.created_at,
        expires_at=batch.deadline,
    )
    write_json(directory / "manifest.json", manifest)
    await machine.object(
        "POST",
        f"{agent_root(task.project_id)}/runs/{task.task_id}/prepared",
        object_value(lease_body(task).model_dump(mode="json")),
    )


async def observe_fixed(
    machine: PublicAPI,
    writer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    task: AgentTaskResponse,
    directory: Path,
) -> None:
    batch = task.batch
    if batch is None or len(batch.plan_run_ids) != 1:
        raise HarnessError("SELFTEST_AGENT_RUN_SET_INVALID")
    manifest = BatchManifest.model_validate(read_json(directory / "manifest.json"))
    installed = PreparedFixedAssets.model_validate(read_json(directory / "installation.json"))
    run = await wait_plan(reader, str(task.project_id), str(batch.plan_run_ids[0]), batch.deadline)
    write_json(directory / "plan-run.json", run)
    observations = await _collect_fixed(
        reader, observer, installed, run, selected_pack(task), directory, deadline=batch.deadline
    )
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
    for fixture in selected_pack(task).fixtures:
        cleanup.register_fixture(fixture.scenario_id)
    cleanup.arm_plan(
        UUID(text_value(run["test_plan_id"])), tuple(asset.case_id for asset in installed.assets)
    )
    cleanup.started_plan(batch.plan_run_ids[0])
    cleanup.plan.observe(run)
    cleaned = await cleanup.finish()
    observations = [
        item.model_copy(update={"cleanup_status": cleaned.status}) for item in observations
    ]
    evidence = BatchEvidence(
        batch_key=manifest.batch_key,
        nonce=task.nonce,
        pack_digest=manifest.pack_digest,
        policy_digest=manifest.policy_digest,
        builds=manifest.builds,
        collected_at=datetime.now(UTC),
        scenarios=tuple(observations),
        cleanup_status=cleaned.status,
    )
    await seal_verification(machine, task, manifest, evidence, directory)


async def seal_verification(
    machine: PublicAPI,
    task: AgentTaskResponse,
    manifest: BatchManifest,
    evidence: BatchEvidence,
    directory: Path,
) -> None:
    batch = task.batch
    if batch is None:
        raise HarnessError("SELFTEST_AGENT_BATCH_MISSING")
    write_json(directory / "evidence.json", evidence)
    _execution_junit(list(evidence.scenarios), directory)
    report = verify_batch(manifest, evidence)
    write_report(report, directory)
    artifacts: tuple[tuple[ArtifactKind, str], ...] = (
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
            for kind, name in artifacts
        ]
    )
    scenarios = tuple(
        VerificationScenario(
            scenario_id=item.scenario_id,
            variant_key=item.variant_key,
            observed_status=item.observed_status,
            verification_status=item.verification_status,
            reason_codes=tuple(finding.code for finding in item.findings),
            evidence_refs=references[1:3],
        )
        for item in report.scenarios
    )
    if batch.resource_digest is None:
        raise HarnessError("SELFTEST_AGENT_RESOURCE_DIGEST_MISSING")
    receipt = VerificationReceipt(
        **lease_body(task).model_dump(),
        manifest_digest=batch.manifest_digest,
        resource_digest=batch.resource_digest,
        policy_digest=batch.policy_digest,
        builds=task.builds,
        batch_verdict=report.batch_verdict,
        evidence_integrity=report.evidence_integrity,
        batch_reason_codes=tuple(finding.code for finding in report.findings),
        cleanup_status=evidence.cleanup_status,
        scenarios=scenarios,
        artifacts=references,
    )
    await machine.object(
        "POST",
        f"/ci/projects/{task.project_id}/self-test-runs/{task.task_id}/verification",
        object_value(receipt.model_dump(mode="json")),
    )
