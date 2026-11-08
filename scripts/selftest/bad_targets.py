"""Real SDK generation and two formal Runs of identical published bad-target assets."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, SubElement, tostring

from scripts.selftest.bad_targets_budget import (
    BadTargetsBudget,
    BoundedBadTargetAPI,
    BoundedBadTargetProtocol,
)
from scripts.selftest.bad_targets_contracts import (
    SCENARIOS,
    BadTargetAsset,
    BadTargetGolden,
    BadTargetPhase,
    BadTargetsAdmission,
    BadTargetsPack,
    BadTargetsResult,
    NamespaceRegistration,
    load_bad_targets_pack,
)
from scripts.selftest.bad_targets_evidence import collect_bad_target, expectation
from scripts.selftest.bad_targets_generation import generate_bad_target
from scripts.selftest.bad_targets_verify import verify_bad_targets
from scripts.selftest.bootstrap import Installation
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import wait_plan
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Builds,
    FixtureBudgetScope,
    ScenarioObservation,
    canonical_digest,
)
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.review_driver import ReviewDriver
from scripts.selftest.start_plan import PlanSelection, launch_plan, prepare_plan
from scripts.selftest.verify import verify_batch, write_report


async def _configure(
    observer: PublicAPI,
    golden: BadTargetGolden,
    *,
    batch: str,
    nonce: str,
    digest: str,
    scope: FixtureBudgetScope,
    fault: bool,
) -> NamespaceRegistration:
    remaining = int(scope.expires_at - datetime.now(UTC).timestamp())
    if not 0 < remaining <= 600:
        raise HarnessError("SELFTEST_BADTARGET_FIXTURE_DEADLINE")
    path = f"/selftest/batches/{batch}/scenarios/{golden.scenario_id}"
    await observer.request(
        "PUT",
        path,
        {
            "nonce": nonce,
            "fixture_digest": digest,
            "ttl_seconds": remaining,
            "budget_scope": scope.model_dump(mode="json"),
            "max_entries": 20,
            "response_statuses": [golden.status],
            "response_body": {
                "actual": golden.actual,
                "code": golden.bad_code if fault else golden.good_code,
                "value": golden.bad_value if fault else golden.good_value,
            },
        },
    )
    empty = await observer.object("GET", path + "/journal")
    if (
        empty["request_count"] != 0
        or empty["entries"] != []
        or empty["truncated"] is not False
        or empty["expired"] is not False
        or empty["nonce"] != nonce
        or empty["fixture_digest"] != digest
    ):
        raise HarnessError("SELFTEST_BADTARGET_FIXTURE_NOT_EMPTY")
    return NamespaceRegistration(
        scenario_id=golden.scenario_id,
        fixture_epoch=text_value(empty["fixture_epoch"]),
        registration_epoch=text_value(empty["registration_epoch"]),
    )


def _manifest(
    pack: BadTargetsPack,
    assets: tuple[BadTargetAsset, ...],
    selection: PlanSelection,
    registrations: tuple[NamespaceRegistration, ...],
    *,
    batch: str,
    nonce: str,
    builds: Builds,
    created: datetime,
    deadline: datetime,
    fault: bool,
    scope: FixtureBudgetScope,
) -> BatchManifest:
    epochs = {item.fixture_epoch for item in registrations}
    if len(epochs) != 1:
        raise HarnessError("SELFTEST_BADTARGET_FIXTURE_EPOCH_CHANGED")
    epoch = next(iter(epochs))
    return BatchManifest(
        pack_id=pack.pack_id,
        pack_version=pack.version,
        pack_digest=pack.digest,
        policy_digest=canonical_digest(
            {"pack": pack.digest, "phase": "fault" if fault else "positive"}
        ),
        project_id=selection.project_id,
        batch_key=batch,
        nonce=nonce,
        builds=builds,
        fixture_epoch=epoch,
        batch_kind="mcp_generated",
        generation_mode="deterministic_mcp",
        verification_scope="full_pack",
        expected_scenario_set=SCENARIOS,
        required_scenario_set=SCENARIOS,
        trusted_required_scenario_set=SCENARIOS,
        scenarios=tuple(
            expectation(asset, golden, epoch, selection, fault=fault)
            for asset, golden in zip(assets, pack.scenarios, strict=True)
        ),
        created_at=created,
        expires_at=deadline,
        fixture_budget=None,
    )


async def _phase(
    reviewer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    cleanup: RoundCleanup,
    *,
    manifest: BatchManifest,
    assets: tuple[BadTargetAsset, ...],
    selection: PlanSelection,
    registrations: tuple[NamespaceRegistration, ...],
    catalog: str,
    phase: Literal["positive", "fault"],
    directory: Path,
) -> BadTargetPhase:
    observed: list[ScenarioObservation] = []
    error: str | None = None
    try:
        cleanup.arm_plan(selection.plan_id, tuple(item.case_id for item in selection.cases))
        started = await launch_plan(
            reviewer, selection=selection, batch_key=f"{manifest.batch_key}:{phase}"
        )
        cleanup.started_plan(started.run_id)
        run = await wait_plan(
            reader, str(selection.project_id), str(started.run_id), manifest.expires_at
        )
        cleanup.plan.observe(run)
        write_json(directory / "plan-run.json", run)
        items = objects_value(run["items"])
        by_case = {text_value(item["target_id"]): item for item in items}
        if len(items) != len(assets) or len(by_case) != len(items):
            raise HarnessError("SELFTEST_BADTARGET_FORMAL_RUN_SET_MISMATCH")
        for asset in assets:
            observed.append(
                await collect_bad_target(
                    reader,
                    observer,
                    asset=asset,
                    run=run,
                    item=by_case[text_value(asset.case.case["id"])],
                    selection=selection,
                    batch=manifest.batch_key,
                    catalog_digest=catalog,
                    output_dir=directory / asset.scenario_id,
                    deadline=manifest.expires_at,
                )
            )
    except (HarnessError, KeyError, ValueError) as failure:
        from scripts.selftest.failures import failure_codes

        error = failure_codes(failure)[0]
    finally:
        receipt = await cleanup.finish()
    status = "completed" if receipt.status == "completed" else "failed"
    evidence = BatchEvidence(
        batch_key=manifest.batch_key,
        nonce=manifest.nonce,
        pack_digest=manifest.pack_digest,
        policy_digest=manifest.policy_digest,
        builds=manifest.builds,
        collected_at=datetime.now(UTC),
        scenarios=tuple(item.model_copy(update={"cleanup_status": status}) for item in observed),
        cleanup_status=status,
        observer_error=error,
    )
    report = verify_batch(manifest, evidence)
    write_json(directory / "evidence.json", evidence)
    write_report(report, directory)
    _execution_junit(evidence, directory)
    return BadTargetPhase(
        phase=phase,
        registrations=registrations,
        manifest=manifest,
        evidence=evidence,
        report=report,
    )


def _execution_junit(evidence: BatchEvidence, directory: Path) -> None:
    suite = Element("testsuite", name="坏目标原始执行", tests=str(len(evidence.scenarios)))
    failures = 0
    for scene in evidence.scenarios:
        case = SubElement(suite, "testcase", name=scene.scenario_id)
        raw = scene.execution
        if raw is None or raw.status not in {"passed", "failed"}:
            SubElement(case, "skipped", message="执行未完成")
        elif raw.status == "failed":
            failures += 1
            SubElement(case, "failure", message=raw.error_code or "failed").text = str(raw.id)
    suite.set("failures", str(failures))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "execution.junit.xml").write_bytes(
        tostring(suite, encoding="utf-8", xml_declaration=True)
    )


async def execute_bad_targets(
    client: ProtocolClient,
    reviewer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    installation: Installation,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    builds: Builds,
    output_dir: Path,
    deadline: datetime,
    review_driver: ReviewDriver | None = None,
) -> BadTargetsResult:
    if client.batch_key != batch_key or fixture_digest != builds.fixture.removeprefix("sha256:"):
        raise HarnessError("SELFTEST_BADTARGET_BINDING_MISMATCH")
    budget = BadTargetsBudget(deadline)
    reviewer, reader, observer = (
        BoundedBadTargetAPI(api, budget) for api in (reviewer, reader, observer)
    )
    client = BoundedBadTargetProtocol(client, budget)
    created = datetime.now(UTC)
    pack = load_bad_targets_pack()
    assets = tuple(
        [
            await generate_bad_target(
                client,
                reviewer,
                installation=installation,
                golden=item,
                output_dir=output_dir / "generation" / item.scenario_id,
                review_driver=review_driver,
            )
            for item in pack.scenarios
        ]
    )
    selection = await prepare_plan(
        reviewer,
        project_id=str(installation.project_id),
        cases=tuple(item.case for item in assets),
        batch_key=batch_key,
        output_dir=output_dir,
    )
    scope = FixtureBudgetScope(
        parent_batch_key=batch_key, nonce=nonce, expires_at=deadline.timestamp()
    )
    phases: list[BadTargetPhase] = []
    manifests: tuple[BatchManifest, ...] = ()
    expectations_frozen_at = created
    for phase in ("positive", "fault"):
        if phases and phases[0].report.exit_code != 0:
            break
        directory = output_dir / phase
        cleanup = RoundCleanup(
            batch_key=batch_key,
            project_id=installation.project_id,
            output_dir=directory,
            writer=reviewer,
            reader=reader,
            observer=observer,
            nonce=nonce,
            fixture_digest=fixture_digest,
        )
        try:
            registrations = []
            for golden in pack.scenarios:
                cleanup.register_fixture(golden.scenario_id)
                registrations.append(
                    await _configure(
                        observer,
                        golden,
                        batch=batch_key,
                        nonce=nonce,
                        digest=fixture_digest,
                        scope=scope,
                        fault=phase == "fault",
                    )
                )
            registered = tuple(registrations)
            if phase == "positive":
                manifests = tuple(
                    _manifest(
                        pack,
                        assets,
                        selection,
                        registered,
                        batch=batch_key,
                        nonce=nonce,
                        builds=builds,
                        created=created,
                        deadline=deadline,
                        fault=fault,
                        scope=scope,
                    )
                    for fault in (False, True)
                )
                # Both independent expected results are durable before the first native Run.
                for name, manifest in zip(("positive", "fault"), manifests, strict=True):
                    write_json(output_dir / name / "manifest.json", manifest)
                expectations_frozen_at = datetime.now(UTC)
                write_json(
                    output_dir / "paired-expectations.json",
                    {
                        "frozen_at": expectations_frozen_at.isoformat(),
                        "manifest_digests": [
                            canonical_digest(item.model_dump(mode="json")) for item in manifests
                        ],
                    },
                )
            manifest = manifests[0 if phase == "positive" else 1]
            if any(item.fixture_epoch != manifest.fixture_epoch for item in registered):
                raise HarnessError("SELFTEST_BADTARGET_FIXTURE_EPOCH_CHANGED")
            phases.append(
                await _phase(
                    reviewer,
                    reader,
                    observer,
                    cleanup,
                    manifest=manifest,
                    assets=assets,
                    selection=selection,
                    registrations=registered,
                    catalog=client.catalog_digest,
                    phase=phase,
                    directory=directory,
                )
            )
        finally:
            await cleanup.finish()
    target_count = sum(
        scene.journal.request_count
        for phase in phases
        for scene in phase.evidence.scenarios
        if scene.journal is not None
    )
    provisional = BadTargetsResult(
        pack_digest=pack.digest,
        batch_key=batch_key,
        nonce=nonce,
        builds=builds,
        frozen_at=created,
        fixture_budget=scope,
        expectations_frozen_at=expectations_frozen_at,
        expectation_digests=(
            canonical_digest(manifests[0].model_dump(mode="json")),
            canonical_digest(manifests[1].model_dump(mode="json")),
        ),
        phases=tuple(phases),
        admission=BadTargetsAdmission(
            direct_http_attempts=budget.attempts,
            tool_attempts=client.attempt_count,
            target_requests=target_count,
            deadline=deadline,
        ),
        batch_verdict="blocked",
        exit_code=2,
    )
    reasons = verify_bad_targets(provisional)
    result = provisional.model_copy(
        update={
            "batch_verdict": "passed" if not reasons else "blocked",
            "exit_code": 0 if not reasons else 2,
            "reason_codes": reasons,
        }
    )
    write_json(output_dir / "badtargets-result.json", result)
    return result
