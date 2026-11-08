"""Freeze supplemental dependencies before running the complete additional engine pack."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import Field, JsonValue
from scripts.selftest.contracts import (
    ApiSource,
    Contract,
    DatasetExpectation,
    SubflowBinding,
    TargetDisposalReceipt,
    canonical_digest,
)
from scripts.selftest.fixed_baseline import (
    CorePack,
    CoreSource,
    FixedResult,
    _install_additional_source,
    _mutate,
    load_core_pack,
)
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import StackBinding, _verify_removed
from scripts.selftest.verify import verify_batch, write_report

PACK = Path(__file__).resolve().parents[2] / "selftest/packs/engine-additional-v1"


class DependencyVersion(Contract):
    version: int = Field(ge=1, le=2)
    definition: JsonObject
    published_definition: JsonObject


class SubflowDependency(Contract):
    scenario_id: str
    workflow_placeholder: UUID
    api_placeholder: UUID
    api_request: JsonObject
    versions: tuple[DependencyVersion, ...] = Field(min_length=2, max_length=2)


class DatasetDependency(Contract):
    scenario_id: str
    artifact_placeholder: UUID
    filename: str
    rows: tuple[JsonObject, ...] = Field(min_length=1, max_length=500)


class Dependencies(Contract):
    schema_version: str
    subflow: SubflowDependency
    dataset: DatasetDependency


def _replace(value: JsonValue, bindings: dict[str, str]) -> JsonValue:
    if isinstance(value, str):
        return bindings.get(value, value)
    if isinstance(value, dict):
        return {key: _replace(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, bindings) for item in value]
    return value


async def _child(
    api: PublicAPI, project: str, service: str, batch: str, directory: Path, spec: SubflowDependency
) -> tuple[dict[str, str], SubflowBinding]:
    source = await _install_additional_source(
        api,
        CoreSource(source_id=spec.api_placeholder, name="固定Return依赖", request=spec.api_request),
        project,
        service,
        batch,
        directory,
        phase="dependency-api",
        dynamic_batch=False,
    )
    bindings = {str(spec.api_placeholder): text_value(source["id"])}
    first = spec.versions[0]
    if tuple(item.version for item in spec.versions) != (1, 2):
        raise HarnessError("SELFTEST_ENGINE_DEPENDENCY_VERSION_INVALID")
    graph = object_value(_replace(first.definition, bindings))
    published_graph = object_value(_replace(first.published_definition, bindings))
    expected_fingerprint = canonical_digest(published_graph)
    native: JsonObject = {
        "format_version": "flowtest-workflow-native-v1",
        "name": batch + " Return依赖",
        "description": "固定v1后发布v2验证不会漂移",
        "definition": graph,
    }
    root = f"/projects/{project}/workflows"
    draft = await _mutate(api, directory, "dependency-workflow", root + "/native-import", native)
    identity = text_value(draft["id"])
    expected_draft = dict(native)
    if (directory / "dependency-patch.json").exists():
        receipt = read_json(directory / "dependency-patch.json")
        if receipt.get("status") == "completed":
            expected_draft["definition"] = _replace(spec.versions[1].definition, bindings)
    if await api.object("GET", root + f"/{identity}/native-export") != expected_draft:
        raise HarnessError("SELFTEST_ENGINE_DEPENDENCY_READBACK_MISMATCH")
    first_version = await _mutate(
        api, directory, "dependency-v1", root + f"/{identity}/versions", {}
    )
    if first_version["fingerprint"] != expected_fingerprint or first_version["definition"] != graph:
        raise HarnessError("SELFTEST_ENGINE_DEPENDENCY_VERSION_MISMATCH")
    await _newer_child(api, root, identity, draft, spec.versions[1], bindings, directory)
    frozen = SubflowBinding(
        path=("call_child",),
        project_id=UUID(project),
        workflow_id=UUID(identity),
        workflow_version_id=UUID(text_value(first_version["id"])),
        workflow_version=1,
        workflow_fingerprint=expected_fingerprint,
        api_sources=(
            ApiSource(
                project_id=UUID(project),
                api_definition_id=UUID(text_value(source["id"])),
                api_version=1,
                contract_fingerprint=text_value(source["fingerprint"]),
            ),
        ),
    )
    return {str(spec.workflow_placeholder): identity}, frozen


async def _newer_child(
    api: PublicAPI,
    root: str,
    identity: str,
    draft: JsonObject,
    spec: DependencyVersion,
    bindings: dict[str, str],
    directory: Path,
) -> None:
    payload: JsonObject = {
        "expected_revision": draft["draft_revision"],
        "definition": _replace(spec.definition, bindings),
    }
    receipt = directory / "dependency-patch.json"
    digest = canonical_digest(payload)
    if receipt.exists():
        value = read_json(receipt)
        if value.get("request_digest") != digest or value.get("status") != "completed":
            raise HarnessError("SELFTEST_ENGINE_DEPENDENCY_UNKNOWN_PATCH")
    else:
        write_json(receipt, {"request_digest": digest, "status": "pending"})
        await api.object("PATCH", root + f"/{identity}", payload)
        write_json(receipt, {"request_digest": digest, "status": "completed"})
    newer = await _mutate(api, directory, "dependency-v2", root + f"/{identity}/versions", {})
    expected = canonical_digest(_replace(spec.published_definition, bindings))
    if newer["version"] != 2 or newer["fingerprint"] != expected:
        raise HarnessError("SELFTEST_ENGINE_NEWER_DEPENDENCY_MISMATCH")


async def _rows(
    api: PublicAPI, project: str, directory: Path, spec: DatasetDependency
) -> tuple[dict[str, str], DatasetExpectation]:
    content = json.dumps(
        [row for row in spec.rows], ensure_ascii=False, separators=(",", ":")
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    path = f"/projects/{project}/files"
    receipt_path = directory / "dataset-upload.json"
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("sha256") != digest or receipt.get("status") != "completed":
            raise HarnessError("SELFTEST_ENGINE_DATASET_UPLOAD_UNKNOWN")
        identity = text_value(receipt["artifact_id"])
    else:
        write_json(receipt_path, {"sha256": digest, "status": "pending"})
        artifact = await api.upload_synthetic(path, spec.filename, content)
        if artifact["sha256"] != digest:
            raise HarnessError("SELFTEST_ENGINE_DATASET_UPLOAD_MISMATCH")
        identity = text_value(artifact["id"])
        write_json(
            receipt_path,
            {
                "sha256": digest,
                "status": "completed",
                "artifact_id": identity,
                "retention": "owned_fixture_asset_requires_stack_disposal",
            },
        )
    if hashlib.sha256(await api.read_synthetic(path + f"/{identity}")).hexdigest() != digest:
        raise HarnessError("SELFTEST_ENGINE_DATASET_READBACK_MISMATCH")
    return {str(spec.artifact_placeholder): identity}, DatasetExpectation(
        artifact_id=UUID(identity),
        sha256=digest,
        row_count=len(spec.rows),
        row_indices=tuple(range(len(spec.rows))),
    )


def _write_bound(
    pack: CorePack,
    bindings: dict[str, str],
    subflow: SubflowBinding,
    rows: DatasetExpectation,
    directory: Path,
    binding: StackBinding,
) -> CorePack:
    workflows: list[JsonValue] = [
        _replace(workflow.model_dump(mode="json"), bindings) for workflow in pack.workflows
    ]
    expectations: list[JsonValue] = [item.model_dump(mode="json") for item in pack.expectations]
    for value in expectations:
        expectation = object_value(value)
        outcome = object_value(expectation["expected"])
        if expectation["scenario_id"] == "ST-ADD-subflow-return":
            outcome["subflows"] = [subflow.model_dump(mode="json")]
        if expectation["scenario_id"] == "ST-ADD-dataset-rows":
            source = outcome.get("dataset")
            if not isinstance(source, dict):
                raise HarnessError("SELFTEST_ENGINE_DATASET_EXPECTATION_MISSING")
            outcome["dataset"] = {
                **source,
                **rows.model_dump(mode="json", exclude={"nodes", "assertions"}),
            }
            outcome["required_disposal"] = {
                "project_name": binding.project_name,
                "target_container_id": binding.runner_container_id,
                "target_volume": binding.runner_volume,
                "target_image": binding.candidate_image_digest,
                "binding_nonce": binding.nonce,
            }
    documents: dict[str, JsonObject] = {
        "api-definitions.json": {"apis": [item.model_dump(mode="json") for item in pack.apis]},
        "workflows.json": {"workflows": workflows},
        "expectations.json": {
            "expectations": expectations,
            "fixtures": [item.model_dump(mode="json") for item in pack.fixtures],
        },
    }
    manifest = pack.manifest.model_copy(
        update={"files": {name: canonical_digest(document) for name, document in documents.items()}}
    )
    for name, document in documents.items():
        write_json(directory / name, document)
    write_json(directory / "manifest.json", manifest)
    return load_core_pack(directory)


async def prepare_engine_additional_pack(
    api: PublicAPI,
    *,
    project_id: str,
    service_id: str,
    batch_key: str,
    output_dir: Path,
    deadline: datetime,
    binding: StackBinding,
    directory: Path = PACK,
) -> CorePack:
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if not 0 < remaining <= 600:
        raise HarnessError("SELFTEST_ENGINE_DEADLINE_INVALID")
    pack = load_core_pack(directory)
    raw = read_json(directory / "dependencies.json")
    requirements = read_json(directory / "acceptance-requirements.json")
    if requirements.get("pack_digest") != pack.digest or requirements.get(
        "dependencies_digest"
    ) != canonical_digest(raw):
        raise HarnessError("SELFTEST_ENGINE_DEPENDENCIES_DIGEST_MISMATCH")
    spec = Dependencies.model_validate(raw)
    if spec.schema_version != "flowtest-engine-dependencies-v1":
        raise HarnessError("SELFTEST_ENGINE_DEPENDENCIES_SCHEMA_INVALID")
    budget = sum(
        integer_value(object_value(item.definition["run_policy"])["request_budget"])
        + integer_value(object_value(item.definition["run_policy"])["cleanup_request_budget"])
        for item in pack.workflows
    )
    dataset_workflow = next(
        item for item in pack.workflows if item.scenario_id == spec.dataset.scenario_id
    )
    dataset_policy = object_value(dataset_workflow.definition["run_policy"])
    dataset_budget = integer_value(dataset_policy["request_budget"]) + integer_value(
        dataset_policy["cleanup_request_budget"]
    )
    expected_rows = next(
        item.expected.dataset
        for item in pack.expectations
        if item.scenario_id == spec.dataset.scenario_id
    )
    row_content = json.dumps(
        list(spec.dataset.rows), ensure_ascii=False, separators=(",", ":")
    ).encode()
    if (
        expected_rows is None
        or expected_rows.row_count != len(spec.dataset.rows)
        or expected_rows.sha256 != hashlib.sha256(row_content).hexdigest()
    ):
        raise HarnessError("SELFTEST_ENGINE_FROZEN_DATASET_MISMATCH")
    child_policy = object_value(spec.subflow.versions[0].definition["run_policy"])
    child_budget = integer_value(child_policy["request_budget"]) + integer_value(
        child_policy["cleanup_request_budget"]
    )
    if budget + dataset_budget * (len(spec.dataset.rows) - 1) + child_budget > 500:
        raise HarnessError("SELFTEST_ENGINE_REQUEST_BUDGET_EXCEEDED")
    write_json(output_dir / "source-manifest.json", pack.manifest)
    write_json(
        output_dir / "dependency-source.json",
        {
            "pack_digest": pack.digest,
            "dependencies_digest": canonical_digest(raw),
            "expected_scenario_set": list(pack.manifest.scenario_ids),
        },
    )
    async with asyncio.timeout(remaining):
        child_bindings, subflow = await _child(
            api, project_id, service_id, batch_key, output_dir, spec.subflow
        )
        row_bindings, dataset = await _rows(api, project_id, output_dir, spec.dataset)
        return _write_bound(
            pack,
            {**child_bindings, **row_bindings},
            subflow,
            dataset,
            output_dir / "bound-pack",
            binding,
        )


def finalize_engine_additional_cleanup(
    result: FixedResult, *, binding: StackBinding, stack_directory: Path, output_dir: Path
) -> FixedResult:
    if (
        StackBinding.model_validate(read_json(stack_directory / "stack.json")) != binding
        or read_json(stack_directory / "ownership.json")
        != {"project_name": binding.project_name, "nonce": binding.nonce}
        or read_json(stack_directory / "cleanup.json")
        != {"project_name": binding.project_name, "status": "completed"}
    ):
        raise HarnessError("SELFTEST_ENGINE_DISPOSAL_OWNERSHIP_MISMATCH")
    _verify_removed(binding.project_name)
    removed_at = datetime.now(UTC)
    observations = []
    changed = False
    for expected, actual in zip(result.manifest.scenarios, result.evidence.scenarios, strict=True):
        if expected.scenario_id != actual.scenario_id:
            raise HarnessError("SELFTEST_ENGINE_DISPOSAL_SCENARIO_MISMATCH")
        if expected.expected.required_disposal is None or actual.target_disposal is not None:
            observations.append(actual)
            continue
        identity = expected.expected.required_disposal
        if (
            identity.project_name != binding.project_name
            or identity.target_container_id != binding.runner_container_id
            or identity.target_volume != binding.runner_volume
            or identity.target_image != binding.candidate_image_digest
            or identity.binding_nonce != binding.nonce
        ):
            raise HarnessError("SELFTEST_ENGINE_DISPOSAL_BINDING_MISMATCH")
        changed = True
        receipt = TargetDisposalReceipt(
            **identity.model_dump(),
            removed_at=removed_at,
            containers_absent=True,
            volumes_absent=True,
            networks_absent=True,
        )
        observations.append(actual.model_copy(update={"target_disposal": receipt}))
    if not (output_dir / "evidence.pre-disposal.json").exists():
        write_json(output_dir / "evidence.pre-disposal.json", result.evidence)
    evidence = result.evidence.model_copy(
        update={
            "scenarios": tuple(observations),
            "collected_at": removed_at if changed else result.evidence.collected_at,
        }
    )
    report = verify_batch(result.manifest, evidence)
    write_json(output_dir / "evidence.json", evidence)
    write_report(report, output_dir)
    return FixedResult(
        manifest=result.manifest, evidence=evidence, report=report, installation=result.installation
    )
