"""Run frozen native API variants without replacing native business requests in H.

Header stages share a deadline and are serialized because they exercise project and
Environment configuration. The parent manifest is frozen before the first stage.
Project creation deliberately remains incomplete until the exact disposable target
has been removed: FlowTest does not expose a project DELETE API.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import JsonValue
from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    Builds,
    DisposableTargetIdentity,
    ErrorEnvelopeEvidence,
    FixtureBudgetScope,
    ProjectStateEvidence,
    ResourceAbsenceEvidence,
    ScenarioExpectation,
    ScenarioObservation,
    TargetDisposalReceipt,
    VerificationReport,
    canonical_digest,
)
from scripts.selftest.failures import failure_codes
from scripts.selftest.fixed_baseline import (
    CorePack,
    FixedInstallation,
    FixedResult,
    _execution_junit,
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
from scripts.selftest.local_stack import StackBinding, _verify_removed
from scripts.selftest.verify import verify_batch, write_report

NATIVE_API_DIRECTORY = Path(__file__).resolve().parents[2] / "selftest" / "packs" / "native-api-v1"
HEADER_NAME = "x-selftest-precedence"


@dataclass(frozen=True)
class NativeAPIResult:
    manifest: BatchManifest
    evidence: BatchEvidence
    report: VerificationReport
    phases: tuple[FixedResult, ...]


def load_native_api_pack(
    installed: Installation,
    batch_key: str,
    directory: Path = NATIVE_API_DIRECTORY,
    *,
    binding: StackBinding | None = None,
) -> CorePack:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,70}", batch_key) is None:
        raise HarnessError("SELFTEST_NATIVE_API_BATCH_KEY_INVALID")
    pack = load_core_pack(directory)
    if pack.manifest.pack_id != "native-api-v1":
        raise HarnessError("SELFTEST_NATIVE_API_PACK_ID_MISMATCH")
    required = (
        installed.target_organization_id,
        installed.target_viewer_id,
        installed.denied_email,
    )
    if any(value is None for value in required):
        raise HarnessError("SELFTEST_NATIVE_API_IDENTITIES_MISSING")
    bindings = {
        "00000000-0000-4000-8000-000000000001": str(installed.target_project_id),
        "00000000-0000-4000-8000-000000000002": str(installed.target_organization_id),
        "00000000-0000-4000-8000-000000000003": str(installed.target_user_id),
        "00000000-0000-4000-8000-000000000004": str(installed.target_viewer_id),
        "$BATCH": batch_key,
        "$B_EMAIL": installed.target_email,
        "$DENIED_EMAIL": installed.denied_email or "",
        "$BINDING_NONCE": installed.binding_nonce,
    }
    bound = CorePack.model_validate(_bind(pack.model_dump(mode="json"), bindings))
    expectations = tuple(
        item.model_copy(update={"fixture_batch_key": f"{batch_key}-phase-{index + 1}"})
        for index, item in enumerate(bound.expectations)
    )
    if binding is not None:
        expectations = tuple(_bind_disposal(item, installed, binding) for item in expectations)
    return bound.model_copy(update={"expectations": expectations})


def _bind_disposal(
    scenario: ScenarioExpectation, installed: Installation, binding: StackBinding
) -> ScenarioExpectation:
    if installed.binding_nonce != binding.nonce:
        raise HarnessError("SELFTEST_NATIVE_API_DISPOSAL_BINDING_MISMATCH")
    state = scenario.expected.project_state
    if state is None:
        return scenario
    identity = DisposableTargetIdentity(
        project_name=binding.project_name,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
    )
    return scenario.model_copy(
        update={
            "expected": scenario.expected.model_copy(
                update={
                    "project_state": state.model_copy(update={"disposable_target": identity}),
                }
            )
        }
    )


def _bind(value: JsonValue, bindings: dict[str, str]) -> JsonValue:
    if isinstance(value, str):
        for key, replacement in bindings.items():
            value = value.replace(key, replacement)
        return value
    if isinstance(value, list):
        return [_bind(item, bindings) for item in value]
    if isinstance(value, dict):
        return {key: _bind(item, bindings) for key, item in value.items()}
    return value


def _phase_pack(pack: CorePack, index: int) -> CorePack:
    sid = pack.manifest.scenario_ids[index]
    return pack.model_copy(
        update={
            "manifest": pack.manifest.model_copy(update={"scenario_ids": (sid,)}),
            "apis": (pack.apis[index],),
            "workflows": (pack.workflows[index],),
            "expectations": (pack.expectations[index],),
            "fixtures": (pack.fixtures[index],),
        }
    )


def _without_synthetic_header(headers: JsonObject) -> JsonObject:
    return {name: value for name, value in headers.items() if name.lower() != HEADER_NAME}


@asynccontextmanager
async def _header_setup(
    api: PublicAPI, installed: Installation, layer: str | None, directory: Path
) -> AsyncIterator[None]:
    if layer is None:
        yield
        return
    root = f"/projects/{installed.project_id}"
    configuration = await api.object("GET", root + "/configuration")
    environment_path = root + f"/environments/{installed.fixture_environment_id}"
    environment = await _environment(api, root, installed.fixture_environment_id)
    before_project, before_environment = (
        object_value(configuration["headers"]),
        object_value(environment["headers"]),
    )
    project_headers = {
        **_without_synthetic_header(before_project),
        "X-Selftest-Precedence": "project",
    }
    environment_headers = _without_synthetic_header(before_environment)
    if layer != "project":
        environment_headers["x-SELFTEST-precedence"] = "environment"
    project_payload: JsonObject = {
        "variables": configuration["variables"],
        "headers": project_headers,
    }
    write_json(
        directory / "header-setup.json",
        {
            "project_id": str(installed.project_id),
            "environment_id": str(installed.fixture_environment_id),
            "before_digest": canonical_digest([before_project, before_environment]),
            "after_digest": canonical_digest([project_headers, environment_headers]),
            "status": "pending",
        },
    )
    await api.object("PUT", root + "/configuration", project_payload)
    try:
        await api.object("PATCH", environment_path, {"headers": environment_headers})
        yield
    finally:
        current_project = await api.object("GET", root + "/configuration")
        current_environment = await _environment(api, root, installed.fixture_environment_id)
        if (
            current_project["headers"] != project_headers
            or current_environment["headers"] != environment_headers
        ):
            raise HarnessError("SELFTEST_HEADER_CONFIGURATION_CONCURRENT_CHANGE")
        await api.object(
            "PUT",
            root + "/configuration",
            {"variables": current_project["variables"], "headers": before_project},
        )
        await api.object("PATCH", environment_path, {"headers": before_environment})
        write_json(
            directory / "header-restored.json",
            {
                "project_id": str(installed.project_id),
                "environment_id": str(installed.fixture_environment_id),
                "restored_digest": canonical_digest([before_project, before_environment]),
                "status": "completed",
            },
        )


async def _environment(api: PublicAPI, root: str, identity: UUID) -> JsonObject:
    matches = [
        item
        for item in objects_value(await api.request("GET", root + "/environments"))
        if item["id"] == str(identity)
    ]
    if len(matches) != 1:
        raise HarnessError("SELFTEST_HEADER_ENVIRONMENT_MISMATCH")
    return matches[0]


async def _advance_api_version(
    api: PublicAPI, asset: FixedInstallation, phase: CorePack, directory: Path
) -> None:
    if not phase.workflows[0].version_drift:
        return
    source = asset.assets[0]
    request = deepcopy(phase.apis[0].request)
    request["path"] = (
        text_value(request["path"]).replace("{batch_key}", asset.batch_key) + "/must-not-run"
    )
    request["base_version"] = source.api_version
    version = await api.object(
        "POST", f"/projects/{asset.project_id}/apis/{source.api_id}/versions", request
    )
    if version["version"] != source.api_version + 1:
        raise HarnessError("SELFTEST_NATIVE_API_VERSION_NOT_ADVANCED")
    write_json(
        directory / "api-version-drift.json",
        {
            "api_id": str(source.api_id),
            "frozen_version": source.api_version,
            "current_version": version["version"],
            "frozen_fingerprint": source.api_fingerprint,
            "current_fingerprint": version["contract_fingerprint"],
        },
    )


def _response(detail: JsonObject, node_id: str) -> JsonObject:
    nodes = [item for item in objects_value(detail["nodes"]) if item["node_id"] == node_id]
    if len(nodes) != 1 or nodes[0]["status"] != "passed" or nodes[0]["phase"] != "main":
        raise HarnessError("SELFTEST_NATIVE_API_CAPTURE_NODE_MISSING")
    observations = objects_value(object_value(nodes[0]["result"])["observations"])
    if len(observations) != 1:
        raise HarnessError("SELFTEST_NATIVE_API_CAPTURE_ATTEMPTS_MISMATCH")
    return object_value(observations[0]["response"])


def _error_envelope(
    response: JsonObject, node_id: str, observation: ScenarioObservation
) -> ErrorEnvelopeEvidence:
    execution = observation.execution
    if execution is None:
        raise HarnessError("SELFTEST_NATIVE_API_EXECUTION_MISSING")
    body = object_value(response["body"])
    error = object_value(body.get("error"))
    if (
        set(body) != {"error"}
        or set(error) != {"code", "message", "details", "trace_id"}
        or not isinstance(error["message"], str)
    ):
        raise HarnessError("SELFTEST_NATIVE_API_ERROR_ENVELOPE_INVALID")
    headers = object_value(response["headers"])
    traces = [value for key, value in headers.items() if key.lower() == "x-trace-id"]
    if len(traces) != 1:
        raise HarnessError("SELFTEST_NATIVE_API_TRACE_HEADER_MISSING")
    return ErrorEnvelopeEvidence.model_validate(
        {
            "node_id": node_id,
            "project_id": str(execution.project_id),
            "execution_id": str(execution.id),
            "status_code": response["status_code"],
            "error_code": error["code"],
            "trace_id": error["trace_id"],
            "response_trace_id": traces[0],
        }
    )


def _utc_timestamp(value: JsonValue) -> datetime:
    parsed = datetime.fromisoformat(text_value(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


async def _enrich(
    capture_reader: PublicAPI,
    target_reader: PublicAPI,
    phase: CorePack,
    _assets: FixedInstallation,
    observations: list[ScenarioObservation],
) -> list[ScenarioObservation]:
    if len(observations) != 1 or observations[0].execution is None:
        raise HarnessError("SELFTEST_NATIVE_API_SCENARIO_MISSING")
    observation = observations[0]
    execution = observation.execution
    if execution is None:
        raise HarnessError("SELFTEST_NATIVE_API_EXECUTION_MISSING")
    expected = phase.expectations[0].expected
    detail: JsonObject = {}
    if (
        expected.error_envelopes
        or expected.project_state is not None
        or expected.created_file is not None
    ):
        detail = await capture_reader.object(
            "GET",
            f"/projects/{execution.project_id}/workflow-executions/{execution.id}",
        )
        captured_execution = object_value(detail["execution"])
        if (
            (
                captured_execution["id"],
                captured_execution["project_id"],
                captured_execution["workflow_id"],
                captured_execution["workflow_version_id"],
            )
            != (
                str(execution.id),
                str(execution.project_id),
                str(execution.workflow_id),
                str(execution.workflow_version_id),
            )
            or captured_execution["environment_id"] != str(execution.environment_id)
            or canonical_digest(captured_execution["snapshot"]) != execution.snapshot_digest
        ):
            raise HarnessError("SELFTEST_NATIVE_API_CAPTURE_BINDING_MISMATCH")
    errors = tuple(
        _error_envelope(_response(detail, item.node_id), item.node_id, observation)
        for item in expected.error_envelopes
    )
    absences: list[ResourceAbsenceEvidence] = []
    for golden in expected.resource_absences:
        values = objects_value(
            await target_reader.request(
                "GET", f"/projects/{golden.project_id}/{golden.resource_kind}"
            )
        )
        if len(values) > 1000 or any(
            item["project_id"] != str(golden.project_id) for item in values
        ):
            raise HarnessError("SELFTEST_NATIVE_API_POSTCONDITION_SCOPE_INVALID")
        absences.append(
            ResourceAbsenceEvidence(
                project_id=golden.project_id,
                resource_kind=golden.resource_kind,
                returned_names=tuple(text_value(item["name"]) for item in values),
                observed_at=datetime.now(UTC),
                complete=True,
            )
        )
    project_state: ProjectStateEvidence | None = None
    if expected.project_state is not None:
        created = object_value(_response(detail, "create_project")["body"])
        identity = UUID(text_value(created["id"]))
        queried = await target_reader.object("GET", f"/projects/{identity}")
        project_state = ProjectStateEvidence.model_validate(
            {
                "project_id": queried["id"],
                "organization_id": queried["organization_id"],
                "created_by_id": queried["created_by_id"],
                "name": queried["name"],
                "created_at": _utc_timestamp(queried["created_at"]),
                "observed_at": datetime.now(UTC),
                "disposal_binding_nonce": expected.project_state.disposal_binding_nonce,
                "disposal_status": "pending",
                "disposable_target": expected.project_state.disposable_target,
            }
        )
    from scripts.selftest.file_observation import observe_created_file

    created_file = (
        await observe_created_file(detail, target_reader, expected.created_file)
        if expected.created_file is not None
        else None
    )
    return [
        observation.model_copy(
            update={
                "error_envelopes": errors,
                "resource_absences": tuple(absences),
                "project_state": project_state,
                "created_file": created_file,
            }
        )
    ]


async def execute_native_api_pack(
    api: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    capture_reader: PublicAPI,
    target_reader: PublicAPI,
    installation: Installation,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    builds: Builds,
    output_dir: Path,
    deadline: datetime | None = None,
    binding: StackBinding | None = None,
    pack: CorePack | None = None,
) -> NativeAPIResult:
    pack = pack or load_native_api_pack(installation, batch_key, binding=binding)
    started = datetime.now(UTC)
    expires = (
        min(deadline, started + timedelta(seconds=600))
        if deadline
        else started + timedelta(seconds=600)
    )
    manifest = BatchManifest(
        fixture_budget=FixtureBudgetScope(
            parent_batch_key=batch_key, nonce=nonce, expires_at=expires.timestamp()
        ),
        pack_id=pack.manifest.pack_id,
        pack_version=pack.manifest.pack_version,
        pack_digest=pack.digest,
        policy_digest=canonical_digest(
            {
                "max_requests": 500,
                "max_runtime_seconds": 600,
                "phases": "serialized",
                "project_cleanup": "exact_disposable_target",
            }
        ),
        project_id=installation.project_id,
        batch_key=batch_key,
        nonce=nonce,
        builds=builds,
        batch_kind="fixed_baseline",
        verification_scope="full_pack",
        expected_scenario_set=pack.manifest.scenario_ids,
        required_scenario_set=pack.manifest.scenario_ids,
        trusted_required_scenario_set=pack.manifest.scenario_ids,
        scenarios=pack.expectations,
        created_at=started,
        expires_at=expires,
    )
    write_json(output_dir / "manifest.json", manifest)
    results: list[FixedResult] = []
    observations: list[ScenarioObservation] = []
    observer_error: str | None = None
    for index, template in enumerate(pack.workflows):
        phase = _phase_pack(pack, index)
        directory = output_dir / "phases" / template.scenario_id
        target = template.target_kind == "product"

        async def before(
            assets: FixedInstallation,
            selected: CorePack = phase,
            selected_dir: Path = directory,
        ) -> None:
            await _advance_api_version(api, assets, selected, selected_dir)

        async def enrich(
            assets: FixedInstallation,
            items: list[ScenarioObservation],
            selected: CorePack = phase,
        ) -> list[ScenarioObservation]:
            return await _enrich(capture_reader, target_reader, selected, assets, items)

        try:
            async with _header_setup(api, installation, template.header_layer, directory):
                result = await execute_fixed_baseline(
                    api,
                    reader,
                    observer,
                    project_id=str(installation.project_id),
                    environment_id=str(
                        installation.target_environment_id
                        if target
                        else installation.fixture_environment_id
                    ),
                    service_id=str(
                        installation.target_service_id
                        if target
                        else installation.fixture_service_id
                    ),
                    batch_key=f"{batch_key}-phase-{index + 1}",
                    nonce=nonce,
                    fixture_digest=fixture_digest,
                    builds=builds,
                    output_dir=directory,
                    pack=phase,
                    deadline=expires,
                    before_launch=before,
                    enrich_observations=enrich,
                    verification_scope="selected_suites",
                    budget_scope=batch_key,
                )
        except (
            HarnessError,
            httpx.HTTPError,
            OSError,
            ValueError,
            TimeoutError,
        ) as error:
            observer_error = failure_codes(error)[0]
            break
        results.append(result)
        observations.extend(result.evidence.scenarios)
        if result.evidence.observer_error or datetime.now(UTC) >= expires:
            break
    epochs = {result.manifest.fixture_epoch for result in results}
    if len(epochs) == 1:
        manifest = manifest.model_copy(update={"fixture_epoch": next(iter(epochs))})
    evidence = BatchEvidence(
        batch_key=batch_key,
        nonce=nonce,
        pack_digest=pack.digest,
        policy_digest=manifest.policy_digest,
        builds=builds,
        collected_at=datetime.now(UTC),
        scenarios=tuple(observations),
        cleanup_status="completed"
        if len(results) == len(pack.expectations)
        and all(result.evidence.cleanup_status == "completed" for result in results)
        else "failed",
        observer_error=observer_error,
    )
    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "evidence.json", evidence)
    _execution_junit(observations, output_dir)
    report = verify_batch(manifest, evidence)
    write_report(report, output_dir)
    return NativeAPIResult(manifest, evidence, report, tuple(results))


def finalize_disposable_cleanup(
    result: NativeAPIResult,
    *,
    binding: StackBinding,
    stack_directory: Path,
    output_dir: Path,
) -> NativeAPIResult:
    """Seal only after the owned launcher's cleanup and independent Docker absence read.

    This host-only read does not stop containers. Pending pre-disposal evidence is
    preserved, and native execution/attempt statuses are never changed.
    """
    ownership = read_json(stack_directory / "ownership.json")
    cleanup = read_json(stack_directory / "cleanup.json")
    stored = StackBinding.model_validate(read_json(stack_directory / "stack.json"))
    if (
        stored != binding
        or ownership != {"project_name": binding.project_name, "nonce": binding.nonce}
        or cleanup != {"project_name": binding.project_name, "status": "completed"}
    ):
        raise HarnessError("SELFTEST_NATIVE_API_DISPOSAL_RECEIPT_MISMATCH")
    _verify_removed(binding.project_name)
    removed_at = datetime.now(UTC)
    observations: list[ScenarioObservation] = []
    changed = False
    for observation, expected in zip(
        result.evidence.scenarios, result.manifest.scenarios, strict=True
    ):
        if observation.scenario_id != expected.scenario_id:
            raise HarnessError("SELFTEST_NATIVE_API_DISPOSAL_SCENARIO_MISMATCH")
        state = observation.project_state
        if state is None:
            observations.append(observation)
            continue
        identity = DisposableTargetIdentity(
            project_name=binding.project_name,
            target_container_id=binding.target_container_id,
            target_volume=binding.target_volume,
            target_image=binding.candidate_image_digest,
        )
        if (
            expected.expected.project_state is None
            or state.disposable_target != identity
            or expected.expected.project_state.disposable_target != identity
            or state.disposal_binding_nonce != binding.nonce
        ):
            raise HarnessError("SELFTEST_NATIVE_API_DISPOSAL_IDENTITY_MISMATCH")
        if state.disposal_status == "completed":
            observations.append(observation)
            continue
        changed = True
        receipt = TargetDisposalReceipt(
            **identity.model_dump(),
            binding_nonce=binding.nonce,
            removed_at=removed_at,
            containers_absent=True,
            volumes_absent=True,
            networks_absent=True,
        )
        observations.append(
            observation.model_copy(
                update={
                    "project_state": state.model_copy(
                        update={
                            "disposal_status": "completed",
                            "disposal_receipt": receipt,
                        }
                    )
                }
            )
        )
    prior_path = output_dir / "evidence.pre-disposal.json"
    if not prior_path.exists():
        write_json(prior_path, result.evidence)
    evidence = result.evidence.model_copy(
        update={
            "scenarios": tuple(observations),
            "collected_at": removed_at if changed else result.evidence.collected_at,
        }
    )
    report = verify_batch(result.manifest, evidence)
    write_json(output_dir / "evidence.json", evidence)
    write_report(report, output_dir)
    return NativeAPIResult(result.manifest, evidence, report, result.phases)
