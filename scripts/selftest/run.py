"""Run freshly generated MCP canaries; raw execution and independent results stay separate."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, tostring

from scripts.selftest.bootstrap import Installation, bootstrap
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import collect_scenario, wait_plan
from scripts.selftest.collect_lifecycle_evidence import (
    collect_lifecycle_scenario,
    lifecycle_expectation,
)
from scripts.selftest.contracts import (
    AssertionExpectation,
    BatchEvidence,
    BatchManifest,
    Builds,
    ExpectedOutcome,
    FixtureBudgetScope,
    FixtureResponseExpectation,
    PublishedSuite,
    ScenarioExpectation,
    ScenarioObservation,
    SuiteCaseVersion,
    canonical_digest,
)
from scripts.selftest.failures import failure_codes
from scripts.selftest.fixed_baseline import (
    CorePack,
    FixedInstallation,
    execute_fixed_baseline,
    load_core_pack,
)
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import ROOT, StackBinding, private_environment
from scripts.selftest.mcp_container_http import container_http_gateway
from scripts.selftest.mcp_generation_journey import GeneratedAsset, generate_canary
from scripts.selftest.mcp_protocol_runner import (
    ProtocolClient,
    container_stdio_protocol,
    http_protocol,
)
from scripts.selftest.start_plan import PlanSelection, launch_plan, prepare_plan
from scripts.selftest.verify import verify_batch, write_report

if TYPE_CHECKING:
    from scripts.selftest.generation_lifecycle import LifecycleAsset


def _verifier_digest(runtime_profile: str = "standalone") -> str:
    return canonical_digest(
        {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "scripts/selftest").glob("*.py"))
            if runtime_profile != "standalone" or path.name != "profile_stack.py"
        }
    )


def _pack_digest() -> str:
    pack = ROOT / "selftest/packs/mcp-core-v1"
    return canonical_digest(
        {
            path.relative_to(pack).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(pack.rglob("*.json"))
        }
    )


async def _configure(
    observer: PublicAPI,
    batch: str,
    scenario: str,
    nonce: str,
    fixture_digest: str,
    *,
    scope: FixtureBudgetScope | None = None,
) -> str:
    policy = scope or FixtureBudgetScope(
        parent_batch_key=batch,
        nonce=nonce,
        expires_at=(datetime.now(UTC) + timedelta(seconds=600)).timestamp(),
    )
    remaining = int(policy.expires_at - datetime.now(UTC).timestamp())
    if remaining <= 0 or policy.nonce != nonce or remaining > 600:
        raise HarnessError("SELFTEST_FIXTURE_BUDGET_INVALID")
    await observer.request(
        "PUT",
        f"/selftest/batches/{batch}/scenarios/{scenario}",
        {
            "nonce": nonce,
            "fixture_digest": fixture_digest,
            "ttl_seconds": remaining,
            "budget_scope": policy.model_dump(mode="json"),
            "max_entries": 100,
            "response_statuses": [200],
            "response_body": {"actual": 1, "code": 0, "value": None},
        },
    )
    empty = await observer.object("GET", f"/selftest/batches/{batch}/scenarios/{scenario}/journal")
    if (
        empty["request_count"] != 0
        or empty["truncated"] is not False
        or empty["expired"] is not False
    ):
        raise HarnessError("SELFTEST_FIXTURE_NOT_EMPTY")
    return text_value(empty["fixture_epoch"])


def _expectation(
    asset: GeneratedAsset, epoch: str, selection: PlanSelection
) -> ScenarioExpectation:
    negative = asset.scenario_id == "ST-MCP-025"
    actual: JsonObject = {
        "actual": 1,
        "code": 0,
        "value": None,
        "marker": "",
        "branch": "",
        "iteration_key": "",
        "request_count": 1,
        "fixture_epoch": epoch,
    }
    golden = object_value(
        object_value(
            read_json(ROOT / "selftest/packs/mcp-core-v1/golden-contracts/canaries.json")[
                "scenarios"
            ]
        )[asset.scenario_id]
    )
    oracle_ids = golden["oracle_ids"]
    if not isinstance(oracle_ids, list):
        raise HarnessError("SELFTEST_GOLDEN_ORACLE_SET_INVALID")
    required_oracles = tuple(text_value(item) for item in oracle_ids)
    if {item.oracle_id for item in asset.oracle_bindings} != set(required_oracles):
        raise HarnessError("SELFTEST_REQUIRED_GOLDEN_ORACLE_MISSING")
    assertions = []
    for binding in asset.oracle_bindings:
        assertions.append(
            AssertionExpectation(
                node_id=binding.node_id,
                name="workflow_assertion",
                passed=not negative or binding.node_id == "assert_status",
                expected=golden["status"]
                if binding.node_id == "assert_status"
                else golden["schema"],
                actual=200 if binding.node_id == "assert_status" else actual,
            )
        )
    return ScenarioExpectation(
        scenario_id=asset.scenario_id,
        variant_key=asset.variant_key,
        expected=ExpectedOutcome(
            execution_status="failed" if negative else "passed",
            error_code="WORKFLOW_ASSERTION_FAILED" if negative else None,
            node_id="assert_schema_1" if negative else None,
            phase="main" if negative else None,
            request_count=1,
            assertions=tuple(assertions),
            fixture_responses=(FixtureResponseExpectation(response_status=200, actual=1, code=0),),
        ),
        required_evidence=("execution", "assertions", "fixture_journal", "provenance"),
        required_oracle_ids=tuple(required_oracles),
        expected_oracle_bindings=asset.oracle_bindings,
        expected_mcp_calls=asset.calls,
        require_suite_provenance=True,
        expected_api_sources=(asset.api_source,),
        expected_suite=PublishedSuite(
            project_id=selection.project_id,
            id=selection.suite_id,
            version=selection.suite_version,
            fingerprint=selection.suite_fingerprint,
            case_versions=tuple(
                SuiteCaseVersion(case_id=case.case_id, version=case.version)
                for case in selection.cases
            ),
        ),
        expected_target_snapshot_digest=next(
            case.target_snapshot_digest
            for case in selection.cases
            if str(case.case_id) == asset.case.case["id"]
        ),
    )


def _execution_junit(observations: list[ScenarioObservation], directory: Path) -> None:
    suite = Element("testsuite", name="FlowTest 原始执行", tests=str(len(observations)))
    failures = 0
    for observed in observations:
        case = SubElement(suite, "testcase", name=observed.scenario_id)
        execution = observed.execution
        if execution is None or execution.status in {"queued", "running", "cancelled"}:
            SubElement(case, "skipped", message="原始执行未完成或已取消")
        elif execution.status == "failed":
            failures += 1
            SubElement(case, "failure", message=execution.error_code or "failed").text = str(
                execution.id
            )
        else:
            SubElement(case, "system-out").text = str(execution.id)
    suite.set("failures", str(failures))
    (directory / "execution.junit.xml").write_bytes(
        tostring(suite, encoding="utf-8", xml_declaration=True)
    )


def _confirm_lifecycle_cleanup(cleanup: RoundCleanup, observed: ScenarioObservation) -> None:
    if observed.cleanup_status != "completed":
        return
    if observed.resource_absence is None:
        raise HarnessError("SELFTEST_CLEANUP_ABSENCE_NOT_CONFIRMED")
    cleanup.observe_absence(observed.resource_absence)


async def _close_round(cleanup: RoundCleanup, suite: str, *apis: PublicAPI) -> None:
    try:
        if suite not in {
            "fixed-core",
            "extended-core",
            "engine-additional",
            "native-api",
            "supplemental-api",
            "engine-golden",
            "s5-native",
            "s5-product-files",
        }:
            await cleanup.finish()
    finally:
        for api in apis:
            await api.close()


@asynccontextmanager
async def _protocol(
    binding: StackBinding,
    transport: str,
    token: str,
    batch_key: str,
    output_dir: Path,
    *,
    stack_directory: Path | None = None,
    deadline: datetime | None = None,
) -> AsyncIterator[ProtocolClient]:
    if transport == "stdio":
        async with container_stdio_protocol(
            container_id=binding.runner_container_id,
            token=token,
            batch_key=batch_key,
            output_dir=output_dir,
        ) as client:
            yield client
        return
    if transport != "streamable-http" or stack_directory is None:
        raise HarnessError("SELFTEST_CANDIDATE_HTTP_BINDING_REQUIRED")
    async with (
        container_http_gateway(
            binding,
            stack_directory,
            output_dir,
            deadline=deadline or datetime.now(UTC) + timedelta(seconds=600),
        ) as endpoint,
        http_protocol(
            url=endpoint.url, token=token, batch_key=batch_key, output_dir=output_dir
        ) as client,
    ):
        yield client


def _fixed_pack(suite: str) -> CorePack:
    directory = ROOT / "selftest/packs" / ("extended-v1" if suite == "extended-core" else "core-v1")
    return load_core_pack(directory)


def _batch_key(suite: str) -> str:
    prefix = {
        "fixed-core": "core",
        "extended-core": "extended",
        "engine-additional": "engine",
        "native-api": "native-api",
        "supplemental-api": "supplemental-api",
        "engine-golden": "engine-golden",
        "s5-native": "s5-native",
        "s5-product-files": "s5-product-files",
    }.get(suite, "mcp")
    return prefix + "-" + secrets.token_hex(10)


async def _configure_canaries(
    observer: PublicAPI,
    cleanup: RoundCleanup,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    scope: FixtureBudgetScope,
) -> str:
    epochs = []
    for scenario in ("ST-MCP-025", "ST-MCP-026"):
        cleanup.register_fixture(scenario)
        epochs.append(
            await _configure(observer, batch_key, scenario, nonce, fixture_digest, scope=scope)
        )
    if len(set(epochs)) != 1:
        raise HarnessError("SELFTEST_FIXTURE_EPOCH_CHANGED")
    return epochs[0]


async def _run_fixed_suite(
    suite: str,
    binding: StackBinding,
    installation: Installation,
    reviewer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    started: datetime,
    output_dir: Path,
    capture_reader: PublicAPI,
) -> int:
    if suite == "engine-golden":
        from scripts.selftest.engine_golden import execute_engine_golden

        result = await execute_engine_golden(
            reviewer,
            reader,
            observer,
            project_id=str(installation.project_id),
            environment_id=str(installation.fixture_environment_id),
            service_id=str(installation.fixture_service_id),
            batch_key=batch_key,
            nonce=nonce,
            fixture_digest=fixture_digest,
            builds=Builds(
                runner=binding.candidate_image_digest,
                target=binding.candidate_image_digest,
                fixture=fixture_digest,
                verifier=_verifier_digest(binding.runtime_profile),
            ),
            output_dir=output_dir,
            deadline=started + timedelta(seconds=600),
        )
        print(
            json.dumps(
                {
                    "batch_key": batch_key,
                    "suite": suite,
                    "verdict": result.report.batch_verdict,
                    "exit_code": result.report.exit_code,
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return result.report.exit_code
    if suite == "s5-native":
        from scripts.selftest.s5_native import prepare_s5_native_pack

        pack = await prepare_s5_native_pack(
            reviewer, str(installation.project_id), output_dir / "dependencies", binding
        )
    elif suite == "engine-additional":
        from scripts.selftest.engine_additional import prepare_engine_additional_pack

        pack = await prepare_engine_additional_pack(
            reviewer,
            project_id=str(installation.project_id),
            service_id=str(installation.fixture_service_id),
            batch_key=batch_key,
            output_dir=output_dir / "dependencies",
            deadline=started + timedelta(seconds=600),
            binding=binding,
        )
    else:
        pack = _fixed_pack(suite)
    fixed = await execute_fixed_baseline(
        reviewer,
        reader,
        observer,
        project_id=str(installation.project_id),
        environment_id=str(installation.fixture_environment_id),
        service_id=str(installation.fixture_service_id),
        batch_key=batch_key,
        nonce=nonce,
        fixture_digest=fixture_digest,
        builds=Builds(
            runner=binding.candidate_image_digest,
            target=binding.candidate_image_digest,
            fixture=fixture_digest,
            verifier=_verifier_digest(binding.runtime_profile),
        ),
        output_dir=output_dir,
        pack=pack,
        deadline=started + timedelta(seconds=600),
        enrich_observations=(_s5_enricher(capture_reader, pack) if suite == "s5-native" else None),
    )
    print(
        json.dumps(
            {
                "batch_key": batch_key,
                "suite": suite,
                "verdict": fixed.report.batch_verdict,
                "exit_code": fixed.report.exit_code,
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return fixed.report.exit_code


def _s5_enricher(
    reader: PublicAPI, pack: CorePack
) -> Callable[[FixedInstallation, list[ScenarioObservation]], Awaitable[list[ScenarioObservation]]]:
    from scripts.selftest.s5_native import observe_s5_artifact

    async def collect(
        installed: FixedInstallation, observations: list[ScenarioObservation]
    ) -> list[ScenarioObservation]:
        return await observe_s5_artifact(reader, pack, installed, observations)

    return collect


async def _run_badtargets_suite(
    binding: StackBinding,
    stack_directory: Path,
    installation: Installation,
    reviewer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    mcp_token: str,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    started: datetime,
    output_dir: Path,
    transport: str,
) -> int:
    from scripts.selftest.bad_targets import execute_bad_targets

    deadline = started + timedelta(seconds=600)
    async with _protocol(
        binding,
        transport,
        mcp_token,
        batch_key,
        output_dir / "sdk",
        stack_directory=stack_directory,
        deadline=deadline,
    ) as client:
        result = await execute_bad_targets(
            client,
            reviewer,
            reader,
            observer,
            installation=installation,
            batch_key=batch_key,
            nonce=nonce,
            fixture_digest=fixture_digest,
            builds=Builds(
                runner=binding.candidate_image_digest,
                target=binding.candidate_image_digest,
                fixture=fixture_digest,
                verifier=_verifier_digest(binding.runtime_profile),
            ),
            output_dir=output_dir,
            deadline=deadline,
        )
    print(
        json.dumps(
            {
                "batch_key": batch_key,
                "suite": "mcp-badtargets",
                "verdict": result.batch_verdict,
                "exit_code": result.exit_code,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return result.exit_code


async def _run_preselected_suite(
    suite: str,
    binding: StackBinding,
    stack_directory: Path,
    installation: Installation,
    reviewer: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    mcp_token: str,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    started: datetime,
    output_dir: Path,
    transport: str,
    capture_reader: PublicAPI,
) -> int | None:
    if suite == "mcp-badtargets":
        return await _run_badtargets_suite(
            binding,
            stack_directory,
            installation,
            reviewer,
            reader,
            observer,
            mcp_token,
            batch_key,
            nonce,
            fixture_digest,
            started,
            output_dir,
            transport,
        )
    if suite in {"fixed-core", "extended-core", "engine-additional", "engine-golden", "s5-native"}:
        return await _run_fixed_suite(
            suite,
            binding,
            installation,
            reviewer,
            reader,
            observer,
            batch_key,
            nonce,
            fixture_digest,
            started,
            output_dir,
            capture_reader,
        )
    return None


async def run_round(
    binding: StackBinding,
    stack_directory: Path,
    output_dir: Path,
    *,
    transport: str = "stdio",
    suite: str = "mcp-core",
) -> int:
    boot = await bootstrap(binding, stack_directory)
    installation = boot.installation
    private = private_environment(stack_directory)
    reviewer = PublicAPI(
        binding.runner_url, boot.credentials.reviewer_token, str(installation.organization_id)
    )
    reader = PublicAPI(binding.runner_url, boot.credentials.observer_token)
    observer = PublicAPI(
        binding.observer_url, private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"], api_prefix=""
    )
    target_reader = PublicAPI(
        binding.target_url,
        boot.credentials.target_viewer_token,
        str(installation.target_organization_id),
    )
    target_writer = PublicAPI(
        binding.target_url,
        boot.credentials.target_admin_token,
        str(installation.target_organization_id),
    )
    capture_reader = PublicAPI(
        binding.runner_url,
        boot.credentials.capture_viewer_token,
        str(installation.organization_id),
    )
    batch_key = _batch_key(suite)
    nonce = secrets.token_hex(24)
    started, pack_digest = datetime.now(UTC), _pack_digest()
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "installation-binding.json", installation)
    fixture_digest = binding.fixture_image_digest.removeprefix("sha256:")
    cleanup = RoundCleanup(
        batch_key=batch_key,
        project_id=installation.project_id,
        output_dir=output_dir,
        writer=reviewer,
        reader=reader,
        observer=observer,
        nonce=nonce,
        fixture_digest=fixture_digest,
        target_reader=target_reader,
        target_writer=target_writer,
    )
    try:
        preselected = await _run_preselected_suite(
            suite,
            binding,
            stack_directory,
            installation,
            reviewer,
            reader,
            observer,
            boot.credentials.mcp_token,
            batch_key,
            nonce,
            fixture_digest,
            started,
            output_dir,
            transport,
            capture_reader,
        )
        if preselected is not None:
            return preselected
        if suite in {"native-api", "supplemental-api", "s5-product-files"}:
            from scripts.selftest.native_api_pack import execute_native_api_pack

            if suite == "supplemental-api":
                from scripts.selftest.supplemental_api_pack import execute_supplemental_api_pack

                result = await execute_supplemental_api_pack(
                    reviewer,
                    reader,
                    observer,
                    capture_reader=capture_reader,
                    target_reader=target_reader,
                    target_provisioner=target_writer,
                    installation=installation,
                    batch_key=batch_key,
                    nonce=nonce,
                    fixture_digest=fixture_digest,
                    builds=Builds(
                        runner=binding.candidate_image_digest,
                        target=binding.candidate_image_digest,
                        fixture=fixture_digest,
                        verifier=_verifier_digest(binding.runtime_profile),
                    ),
                    output_dir=output_dir,
                    deadline=started + timedelta(seconds=600),
                    binding=binding,
                )
            else:
                from scripts.selftest.s5_product_files import prepare_pack as prepare_files

                native_pack = (
                    await prepare_files(
                        reviewer,
                        target_reader,
                        installation,
                        binding,
                        batch_key,
                        output_dir / "dependencies",
                    )
                    if suite == "s5-product-files"
                    else None
                )
                result = await execute_native_api_pack(
                    reviewer,
                    reader,
                    observer,
                    capture_reader=capture_reader,
                    target_reader=target_reader,
                    installation=installation,
                    batch_key=batch_key,
                    nonce=nonce,
                    fixture_digest=fixture_digest,
                    builds=Builds(
                        runner=binding.candidate_image_digest,
                        target=binding.candidate_image_digest,
                        fixture=fixture_digest,
                        verifier=_verifier_digest(binding.runtime_profile),
                    ),
                    output_dir=output_dir,
                    binding=binding,
                    pack=native_pack,
                )
            print(
                json.dumps(
                    {
                        "batch_key": batch_key,
                        "suite": suite,
                        "verdict": result.report.batch_verdict,
                        "exit_code": result.report.exit_code,
                        "disposable_cleanup_pending": True,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return result.report.exit_code
        scope = FixtureBudgetScope(
            parent_batch_key=batch_key,
            nonce=nonce,
            expires_at=(started + timedelta(seconds=600)).timestamp(),
        )
        epoch = await _configure_canaries(
            observer, cleanup, batch_key, nonce, fixture_digest, scope
        )
        async with _protocol(
            binding,
            transport,
            boot.credentials.mcp_token,
            batch_key,
            output_dir,
            stack_directory=stack_directory,
            deadline=started + timedelta(seconds=600),
        ) as client:
            await client.call(
                "flowtest.inspect_connection",
                {"request": {}},
                scenario_id="batch",
                phase="connection",
            )
            assets = [
                await generate_canary(
                    client,
                    reviewer,
                    installation=installation,
                    scenario_id=scenario,
                    expected_actual=expected,
                    output_dir=output_dir / scenario,
                )
                for scenario, expected in (("ST-MCP-025", 2), ("ST-MCP-026", 1))
            ]
            lifecycle: LifecycleAsset | None = None
            if suite == "mcp-core":
                from scripts.selftest.generation_lifecycle import generate_lifecycle

                lifecycle = await generate_lifecycle(
                    client,
                    reviewer,
                    installation=installation,
                    binding=binding,
                    batch_key=batch_key,
                    output_dir=output_dir / "ST-MCP-023",
                )
            catalog_digest = client.catalog_digest
        cases = tuple(asset.case for asset in assets)
        if lifecycle is not None:
            cases = (lifecycle.case, *cases)
        selection = await prepare_plan(
            reviewer,
            project_id=str(installation.project_id),
            cases=cases,
            batch_key=batch_key,
            output_dir=output_dir,
        )
        expectations = tuple(_expectation(asset, epoch, selection) for asset in assets)
        if lifecycle is not None:
            expectations = (lifecycle_expectation(lifecycle, selection), *expectations)
        scenario_ids = tuple(item.scenario_id for item in expectations)
        verification_scope = "selected_suites" if lifecycle is not None else "diagnostic_subset"
        manifest = BatchManifest(
            fixture_budget=scope,
            pack_id="flowtest-mcp-core",
            pack_version="1.0.0",
            pack_digest=pack_digest,
            policy_digest=canonical_digest(
                {
                    "scenario_ids": list(scenario_ids),
                    "default_plan_retries": 0,
                    "verification_scope": verification_scope,
                }
            ),
            project_id=installation.project_id,
            batch_key=batch_key,
            nonce=nonce,
            builds=Builds(
                runner=binding.candidate_image_digest,
                target=binding.candidate_image_digest,
                fixture=fixture_digest,
                verifier=_verifier_digest(binding.runtime_profile),
            ),
            batch_kind="mcp_generated",
            generation_mode="deterministic_mcp",
            verification_scope=verification_scope,
            expected_scenario_set=scenario_ids,
            required_scenario_set=scenario_ids,
            scenarios=expectations,
            fixture_epoch=epoch,
            created_at=started,
            expires_at=started + timedelta(seconds=600),
        )
        write_json(output_dir / "manifest.json", manifest)
        if lifecycle is not None:
            await cleanup.arm_lifecycle(
                project_id=lifecycle.target_project_id,
                creator_id=installation.target_user_id,
                names=(lifecycle.created_resource_name, lifecycle.updated_resource_name),
            )
        cleanup.arm_plan(selection.plan_id, tuple(case.case_id for case in selection.cases))
        started_plan = await launch_plan(reviewer, selection=selection, batch_key=batch_key)
        cleanup.started_plan(started_plan.run_id)
        run_id = str(started_plan.run_id)
        run = await wait_plan(reader, str(installation.project_id), run_id, manifest.expires_at)
        cleanup.plan.observe(run)
        write_json(output_dir / "plan-run.json", run)
        items = objects_value(run["items"])
        if len(items) != len(cases):
            raise HarnessError("SELFTEST_PLAN_ITEM_SET_MISMATCH")
        observations = [
            await collect_scenario(
                reader,
                observer,
                asset=asset,
                run=run,
                item=next(item for item in items if item["target_id"] == asset.case.case["id"]),
                batch_key=batch_key,
                catalog_digest=catalog_digest,
                expected_target_snapshot_digest=next(
                    case.target_snapshot_digest
                    for case in started_plan.selection.cases
                    if str(case.case_id) == asset.case.case["id"]
                ),
                selection=started_plan.selection,
                output_dir=output_dir / asset.scenario_id,
            )
            for asset in assets
        ]
        if lifecycle is not None:
            lifecycle_observation = await collect_lifecycle_scenario(
                reader,
                target_reader,
                capture_reader=capture_reader,
                asset=lifecycle,
                run=run,
                item=next(item for item in items if item["target_id"] == lifecycle.case.case["id"]),
                batch_key=batch_key,
                catalog_digest=catalog_digest,
                expected_target_snapshot_digest=next(
                    case.target_snapshot_digest
                    for case in selection.cases
                    if str(case.case_id) == lifecycle.case.case["id"]
                ),
                output_dir=output_dir / lifecycle.scenario_id,
                selection=selection,
            )
            observations.insert(0, lifecycle_observation)
            _confirm_lifecycle_cleanup(cleanup, lifecycle_observation)
        cleanup_receipt = await cleanup.finish()
        observations = [
            item.model_copy(
                update={
                    "cleanup_status": "completed"
                    if cleanup_receipt.status == "completed"
                    else "failed"
                }
            )
            if item.scenario_id in {asset.scenario_id for asset in assets}
            else item
            for item in observations
        ]
        evidence = BatchEvidence(
            batch_key=batch_key,
            nonce=nonce,
            pack_digest=pack_digest,
            policy_digest=manifest.policy_digest,
            builds=manifest.builds,
            collected_at=datetime.now(UTC),
            scenarios=tuple(observations),
            cleanup_status="completed"
            if all(item.cleanup_status == "completed" for item in observations)
            else "failed",
        )
        write_json(output_dir / "evidence.json", evidence)
        _execution_junit(observations, output_dir)
        report = verify_batch(manifest, evidence)
        write_report(report, output_dir)
        print(
            json.dumps(
                {
                    "batch_key": batch_key,
                    "verification_scope": report.verification_scope,
                    "verdict": report.batch_verdict,
                    "exit_code": report.exit_code,
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return report.exit_code
    finally:
        await _close_round(
            cleanup, suite, reviewer, reader, observer, target_reader, target_writer, capture_reader
        )


def finalize_native(arguments: argparse.Namespace) -> int:
    from scripts.selftest.contracts import VerificationReport
    from scripts.selftest.fixed_baseline import FixedResult
    from scripts.selftest.native_api_pack import NativeAPIResult, finalize_disposable_cleanup

    if (
        arguments.suite
        not in {
            "native-api",
            "supplemental-api",
            "engine-additional",
            "s5-native",
            "s5-product-files",
        }
        or arguments.rounds != 1
    ):
        raise HarnessError("SELFTEST_DISPOSAL_FINALIZE_SCOPE_INVALID")
    binding = StackBinding.model_validate(read_json(arguments.directory / "stack.json"))
    directory = arguments.output_dir / "round-1"
    result = NativeAPIResult(
        manifest=BatchManifest.model_validate(read_json(directory / "manifest.json")),
        evidence=BatchEvidence.model_validate(read_json(directory / "evidence.json")),
        report=VerificationReport.model_validate(read_json(directory / "verification.json")),
        phases=(),
    )
    sealed: FixedResult | NativeAPIResult
    if arguments.suite == "s5-product-files":
        from scripts.selftest.s5_product_files import finalize as finalize_files

        sealed = finalize_files(binding, arguments.directory, directory)
    elif arguments.suite in {"engine-additional", "s5-native"}:
        from scripts.selftest.engine_additional import finalize_engine_additional_cleanup
        from scripts.selftest.fixed_baseline import FixedInstallation, FixedResult

        fixed = FixedResult(
            manifest=result.manifest,
            evidence=result.evidence,
            report=result.report,
            installation=FixedInstallation.model_validate(
                read_json(directory / "installation.json")
            ),
        )
        sealed = finalize_engine_additional_cleanup(
            fixed, binding=binding, stack_directory=arguments.directory, output_dir=directory
        )
    elif arguments.suite == "supplemental-api":
        from scripts.selftest.supplemental_api_pack import finalize_supplemental_cleanup

        sealed = finalize_supplemental_cleanup(
            result, binding=binding, stack_directory=arguments.directory, output_dir=directory
        )
    else:
        sealed = finalize_disposable_cleanup(
            result, binding=binding, stack_directory=arguments.directory, output_dir=directory
        )
    print(
        json.dumps(
            {
                "batch_key": sealed.manifest.batch_key,
                "suite": arguments.suite,
                "verdict": sealed.report.batch_verdict,
                "exit_code": sealed.report.exit_code,
            },
            ensure_ascii=False,
        )
    )
    return sealed.report.exit_code


async def _main(arguments: argparse.Namespace) -> int:
    if arguments.finalize_disposable:
        return finalize_native(arguments)
    if arguments.generation_mode == "host_llm_mcp":
        write_json(
            arguments.output_dir / "host-acceptance.json",
            {
                "generation_mode": "host_llm_mcp",
                "status": "NOT_RUN",
                "reason": "WAITING_FOR_HOST",
                "missing": [
                    "registered_host",
                    "installed_skill",
                    "provider_authorization",
                    "explicit_model_budget",
                ],
            },
        )
        return 2
    binding = StackBinding.model_validate(read_json(arguments.directory / "stack.json"))
    for index in range(arguments.rounds):
        async with asyncio.timeout(600):
            result = await run_round(
                binding,
                arguments.directory,
                arguments.output_dir / f"round-{index + 1}",
                transport=arguments.transport,
                suite=arguments.suite,
            )
        if result:
            return result
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="真实 MCP 生成并执行自测用例")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--finalize-disposable", action="store_true")
    parser.add_argument("--rounds", type=int, choices=(1, 2), default=2)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument(
        "--suite",
        choices=(
            "mcp-core",
            "mcp-badtargets",
            "mcp-canaries",
            "fixed-core",
            "extended-core",
            "engine-additional",
            "native-api",
            "supplemental-api",
            "engine-golden",
            "s5-native",
            "s5-product-files",
        ),
        default="mcp-core",
    )
    parser.add_argument(
        "--generation-mode",
        choices=("deterministic_mcp", "host_llm_mcp"),
        default="deterministic_mcp",
    )
    arguments = parser.parse_args()
    try:
        code = asyncio.run(_main(arguments))
    except Exception as error:
        # CLI failures stay nonzero; receipts exclude exception payloads and credentials.
        failure: JsonObject = {"status": "error", "reason_codes": list(failure_codes(error))}
        write_json(arguments.output_dir / "failure.json", failure)
        print(
            json.dumps(failure, ensure_ascii=False),
            flush=True,
        )
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
