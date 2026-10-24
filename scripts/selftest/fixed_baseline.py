"""Install and execute the frozen core pack using public native and asset-package APIs.

This trusted fixed route is separate from MCP generation. Native import creates a draft
immediately; its local preview/readback receipts are not server ChangeSet approvals.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx
from pydantic import Field, JsonValue
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.collect_evidence import (
    collect_children,
    journal,
    normalize_execution,
    wait_plan,
)
from scripts.selftest.contracts import (
    ApiSource,
    BatchEvidence,
    BatchManifest,
    Builds,
    Contract,
    EvidencePage,
    FixtureBudgetScope,
    ScenarioExpectation,
    ScenarioObservation,
    VerificationReport,
    canonical_digest,
)
from scripts.selftest.failures import failure_codes
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
from scripts.selftest.verify import verify_batch, write_report

PACK_DIRECTORY = Path(__file__).resolve().parents[2] / "selftest" / "packs" / "core-v1"


class CoreManifest(Contract):
    schema_version: Literal["flowtest-fixed-pack-v1"]
    pack_id: Literal[
        "core-v1",
        "extended-v1",
        "native-api-v1",
        "supplemental-api-v1",
        "engine-golden-v1",
        "s5-native-v1",
        "s5-product-files-v1",
    ]
    pack_version: str
    request_budget: Literal[500]
    runtime_seconds: Literal[600]
    scenario_ids: tuple[str, ...] = Field(min_length=1, max_length=50)
    files: dict[str, str]


class CoreSource(Contract):
    source_id: UUID
    name: str
    request: JsonObject


class CoreAPI(CoreSource):
    scenario_id: str
    additional_sources: tuple[CoreSource, ...] = Field(default=(), max_length=40)


class CoreWorkflow(Contract):
    scenario_id: str
    definition: JsonObject
    published_definition: JsonObject
    case_runtime_headers: dict[str, str] = Field(default_factory=dict)
    plan_runtime_headers: dict[str, str] = Field(default_factory=dict)
    header_layer: Literal["project", "environment", "api", "case", "runtime", "node"] | None = None
    target_kind: Literal["fixture", "product"] = "fixture"
    version_drift: bool = False
    project_lifecycle: bool = False


class WireExpectation(Contract):
    value: JsonValue
    branch: str
    iteration_key: str
    response_status: int
    authorization_present: bool


class FixturePolicy(Contract):
    response_statuses: tuple[int, ...]
    response_body: JsonObject
    delay_ms: int


class ControlExpectation(Contract):
    node_id: str
    kind: Literal["iteration", "branch"]
    total: int


class CoreFixture(Contract):
    scenario_id: str
    fixture: FixturePolicy
    wire: tuple[WireExpectation, ...]
    control: ControlExpectation | None
    wire_order: Literal["ordered", "unordered"] = "ordered"


class CorePack(Contract):
    manifest: CoreManifest
    digest: str
    apis: tuple[CoreAPI, ...]
    workflows: tuple[CoreWorkflow, ...]
    expectations: tuple[ScenarioExpectation, ...]
    fixtures: tuple[CoreFixture, ...]


class FixedAsset(Contract):
    scenario_id: str
    api_id: UUID
    api_version: int
    api_fingerprint: str
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_version: int
    workflow_fingerprint: str
    case_id: UUID
    case_version: int
    case_fingerprint: str
    api_sources: tuple[ApiSource, ...] = Field(default=(), max_length=50)


class FixedInstallation(Contract):
    schema_version: Literal["flowtest-fixed-installation-v1"] = "flowtest-fixed-installation-v1"
    project_id: UUID
    environment_id: UUID
    service_id: UUID
    batch_key: str
    nonce: str
    pack_digest: str
    assets: tuple[FixedAsset, ...]
    suite_id: UUID
    suite_version: int
    plan_id: UUID


class FixedObservationInputs(Protocol):
    @property
    def project_id(self) -> UUID: ...

    @property
    def environment_id(self) -> UUID: ...

    @property
    def batch_key(self) -> str: ...

    @property
    def assets(self) -> tuple[FixedAsset, ...]: ...


class FixedResult(Contract):
    manifest: BatchManifest
    evidence: BatchEvidence
    report: VerificationReport
    installation: FixedInstallation | None


def load_core_pack(directory: Path = PACK_DIRECTORY) -> CorePack:
    manifest = CoreManifest.model_validate(read_json(directory / "manifest.json"))
    names = {"api-definitions.json", "workflows.json", "expectations.json"}
    scenario_count = len(manifest.scenario_ids)
    if (
        set(manifest.files) != names
        or len(set(manifest.scenario_ids)) != scenario_count
        or (manifest.pack_id == "core-v1" and scenario_count != 8)
    ):
        raise HarnessError("SELFTEST_FIXED_PACK_STRUCTURE_INVALID")
    documents = {name: read_json(directory / name) for name in sorted(names)}
    if any(canonical_digest(documents[name]) != manifest.files[name] for name in names):
        raise HarnessError("SELFTEST_FIXED_PACK_DIGEST_MISMATCH")
    pack = CorePack(
        manifest=manifest,
        digest=canonical_digest(manifest.model_dump(mode="json")),
        apis=tuple(
            CoreAPI.model_validate(item)
            for item in objects_value(documents["api-definitions.json"]["apis"])
        ),
        workflows=tuple(
            CoreWorkflow.model_validate(item)
            for item in objects_value(documents["workflows.json"]["workflows"])
        ),
        expectations=tuple(
            ScenarioExpectation.model_validate(item)
            for item in objects_value(documents["expectations.json"]["expectations"])
        ),
        fixtures=tuple(
            CoreFixture.model_validate(item)
            for item in objects_value(documents["expectations.json"]["fixtures"])
        ),
    )
    groups = (pack.apis, pack.workflows, pack.expectations, pack.fixtures)
    if any(tuple(item.scenario_id for item in group) != manifest.scenario_ids for group in groups):
        raise HarnessError("SELFTEST_FIXED_PACK_SCENARIOS_MISMATCH")
    graph_budget = sum(
        integer_value(object_value(item.definition["run_policy"])["request_budget"])
        for item in pack.workflows
    )
    if graph_budget > manifest.request_budget:
        raise HarnessError("SELFTEST_FIXED_REQUEST_BUDGET")
    if sum(len(item.wire) for item in pack.fixtures) > manifest.request_budget:
        raise HarnessError("SELFTEST_FIXED_REQUEST_BUDGET")
    return pack


async def _mutate(
    api: PublicAPI, directory: Path, phase: str, path: str, payload: JsonObject
) -> JsonObject:
    """Persist an intent before each non-idempotent mutation; unknown results stop."""
    receipt_path = directory / "mutation-receipts" / f"{phase}.json"
    digest = canonical_digest({"path": path, "payload": payload})
    if receipt_path.exists():
        previous = read_json(receipt_path)
        if previous.get("request_digest") != digest:
            raise HarnessError("SELFTEST_FIXED_MUTATION_CONFLICT")
        if previous.get("status") != "completed":
            raise HarnessError("SELFTEST_FIXED_MUTATION_UNKNOWN_RESULT_NEEDS_REVIEW")
        return object_value(previous["response"])
    write_json(receipt_path, {"request_digest": digest, "status": "pending"})
    result = await api.object("POST", path, payload)
    write_json(
        receipt_path,
        {"request_digest": digest, "status": "completed", "response": result},
    )
    return result


def _bind_definition(
    template: CoreWorkflow, source: CoreAPI, api: JsonObject, *, published: bool = False
) -> JsonObject:
    definition = deepcopy(template.published_definition if published else template.definition)
    references = object_value(api.get("references", {str(source.source_id): api}))
    groups = [object_value(definition), *objects_value(definition.get("regions", []))]
    for group in groups:
        for node in objects_value(group["nodes"]):
            if node["type"] != "api":
                continue
            config = object_value(node["config"])
            reference = references.get(text_value(config.get("api_definition_id")))
            if reference is None:
                raise HarnessError("SELFTEST_FIXED_API_REFERENCE_UNKNOWN")
            pinned = object_value(reference)
            config["api_definition_id"] = pinned["id"]
            config["api_version"] = pinned["version"]
    return definition


def _case_definition(workflow: JsonObject, environment_id: str) -> JsonObject:
    return {
        "workflow_id": workflow["workflow_id"],
        "workflow_version": workflow["version"],
        "environment_id": environment_id,
        "runtime_variables": {},
        "runtime_headers": workflow.get("case_runtime_headers", {}),
    }


def _source_id(batch_key: str, scenario_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"flowtest:fixed:{batch_key}:{scenario_id}"))


def _package(
    pack: CorePack,
    project_id: str,
    environment_id: str,
    batch_key: str,
    workflows: list[JsonObject],
) -> JsonObject:
    cases: list[JsonObject] = []
    workflow_refs: list[JsonObject] = []
    workflow_bindings: JsonObject = {}
    choices: list[JsonValue] = []
    for scenario, workflow in zip(pack.manifest.scenario_ids, workflows, strict=True):
        source_id = _source_id(batch_key, scenario)
        definition = _case_definition(workflow, environment_id)
        cases.append(
            {
                "id": source_id,
                "name": f"{batch_key} {scenario}",
                "description": "固定基准包",
                "folder_id": None,
                "tags": ["自测", "core-v1"],
                "is_template": False,
                "draft_definition": definition,
                "versions": [
                    {
                        "version": 1,
                        "definition": definition,
                        "fingerprint": canonical_digest(definition),
                        "change_note": "冻结基准",
                    }
                ],
            }
        )
        workflow_id, version = (
            text_value(workflow["workflow_id"]),
            integer_value(workflow["version"]),
        )
        workflow_refs.append(
            {
                "id": workflow_id,
                "name": scenario,
                "versions": [{"version": version, "fingerprint": workflow["fingerprint"]}],
            }
        )
        workflow_bindings[workflow_id] = {
            "target_id": workflow_id,
            "versions": {str(version): version},
        }
        choices.append({"kind": "case", "source_id": source_id, "action": "create"})
    suite_definition: JsonObject = {
        "items": [{"test_case_id": item["id"], "test_case_version": 1} for item in cases]
    }
    suite_id = _source_id(batch_key, "suite")
    suite: JsonObject = {
        "id": suite_id,
        "name": f"{batch_key} 固定基准套件",
        "description": "固定基准包",
        "folder_id": None,
        "tags": ["自测", "core-v1"],
        "draft_definition": suite_definition,
        "versions": [
            {
                "version": 1,
                "definition": suite_definition,
                "fingerprint": canonical_digest(suite_definition),
                "change_note": "冻结基准",
            }
        ],
    }
    choices.append({"kind": "suite", "source_id": suite_id, "action": "create"})
    return {
        "package": {
            "format": "flowtest-test-assets",
            "format_version": 1,
            "source_project_id": project_id,
            "folders": [],
            "environments": [{"id": environment_id, "name": "隔离合成目标"}],
            "workflows": [item for item in workflow_refs],
            "cases": [item for item in cases],
            "suites": [suite],
        },
        "choices": choices,
        "bindings": {
            "workflows": workflow_bindings,
            "environments": {environment_id: environment_id},
            "folders": {},
        },
    }


def _mapped_version(mapping: JsonObject) -> int:
    versions = objects_value(mapping["versions"])
    if len(versions) != 1 or versions[0]["source_version"] != 1:
        raise HarnessError("SELFTEST_FIXED_VERSION_MAPPING_INVALID")
    return integer_value(versions[0]["target_version"])


def _pinned_sources(project_id: str, source: JsonObject) -> tuple[ApiSource, ...]:
    references = object_value(source.get("references", {"primary": source}))
    return tuple(
        ApiSource(
            project_id=UUID(project_id),
            api_definition_id=UUID(text_value(item["id"])),
            api_version=integer_value(item["version"]),
            contract_fingerprint=text_value(item["fingerprint"]),
        )
        for value in references.values()
        for item in (object_value(value),)
    )


async def _install_workflows(
    api: PublicAPI,
    pack: CorePack,
    project_id: str,
    service_id: str,
    batch_key: str,
    directory: Path,
    *,
    dynamic_batch: bool = False,
) -> tuple[list[JsonObject], list[JsonObject]]:
    root = f"/projects/{project_id}"
    apis: list[JsonObject] = []
    workflows: list[JsonObject] = []
    for index, (source, template) in enumerate(zip(pack.apis, pack.workflows, strict=True)):
        request = deepcopy(source.request)
        request["path"] = text_value(request["path"]).replace(
            "{batch_key}", "{{selftest_batch_key}}" if dynamic_batch else batch_key
        )
        created = await _mutate(
            api,
            directory,
            f"api-{index}",
            root + "/apis",
            {
                "name": f"{batch_key} {source.name}",
                "service_id": service_id,
                "request": request,
            },
        )
        definition, version = (
            object_value(created["definition"]),
            object_value(created["version"]),
        )
        pinned: JsonObject = {
            "id": definition["id"],
            "version": version["version"],
            "fingerprint": version["contract_fingerprint"],
        }
        if version["api_definition_id"] != pinned["id"] or not pinned["fingerprint"]:
            raise HarnessError("SELFTEST_FIXED_API_IDENTITY_MISMATCH")
        if source.additional_sources:
            references: JsonObject = {str(source.source_id): deepcopy(pinned)}
            for extra_index, extra in enumerate(source.additional_sources):
                references[str(extra.source_id)] = await _install_additional_source(
                    api,
                    extra,
                    project_id,
                    service_id,
                    batch_key,
                    directory,
                    phase=f"api-{index}-extra-{extra_index}",
                    dynamic_batch=dynamic_batch,
                )
            pinned["references"] = references
        graph = _bind_definition(template, source, pinned)
        native: JsonObject = {
            "format_version": "flowtest-workflow-native-v1",
            "name": f"{batch_key} {source.scenario_id}",
            "description": "固定基准: 本地冻结预览后原生导入",
            "definition": graph,
        }
        write_json(
            directory / source.scenario_id / "native-local-preview.json",
            {
                "approval_kind": "trusted_fixed_pack_initialization",
                "server_review": False,
                "pack_digest": pack.digest,
                "document": native,
            },
        )
        draft = await _mutate(
            api,
            directory,
            f"workflow-{index}",
            root + "/workflows/native-import",
            native,
        )
        workflow_id = text_value(draft["id"])
        readback = await api.object("GET", root + f"/workflows/{workflow_id}/native-export")
        if canonical_digest(readback) != canonical_digest(native):
            raise HarnessError("SELFTEST_FIXED_NATIVE_READBACK_MISMATCH")
        published = await _mutate(
            api,
            directory,
            f"publish-{index}",
            root + f"/workflows/{workflow_id}/versions",
            {},
        )
        if (
            published["workflow_id"] != workflow_id
            or published["fingerprint"]
            != canonical_digest(_bind_definition(template, source, pinned, published=True))
            or canonical_digest(published["definition"]) != canonical_digest(graph)
        ):
            raise HarnessError("SELFTEST_FIXED_PUBLISHED_GRAPH_MISMATCH")
        apis.append(pinned)
        workflows.append(
            {
                **published,
                "case_runtime_headers": dict(template.case_runtime_headers),
                "plan_runtime_headers": dict(template.plan_runtime_headers),
            }
        )
    return apis, workflows


async def _install_additional_source(
    api: PublicAPI,
    source: CoreSource,
    project_id: str,
    service_id: str,
    batch_key: str,
    directory: Path,
    *,
    phase: str,
    dynamic_batch: bool,
) -> JsonObject:
    request = deepcopy(source.request)
    request["path"] = text_value(request["path"]).replace(
        "{batch_key}", "{{selftest_batch_key}}" if dynamic_batch else batch_key
    )
    created = await _mutate(
        api,
        directory,
        phase,
        f"/projects/{project_id}/apis",
        {
            "name": f"{batch_key} {source.name}",
            "service_id": service_id,
            "request": request,
        },
    )
    definition, version = (
        object_value(created["definition"]),
        object_value(created["version"]),
    )
    if version["api_definition_id"] != definition["id"] or not version["contract_fingerprint"]:
        raise HarnessError("SELFTEST_FIXED_API_IDENTITY_MISMATCH")
    return {
        "id": definition["id"],
        "version": version["version"],
        "fingerprint": version["contract_fingerprint"],
    }


async def _apply_package(
    api: PublicAPI, root: str, payload: JsonObject, output_dir: Path
) -> JsonObject:
    preview = await api.object("POST", root + "/test-assets/import/preview", payload)
    # A completed apply can be replayed from the local receipt, but never re-approved.
    apply_path = output_dir / "mutation-receipts" / "package.json"
    if apply_path.exists():
        stored_preview = read_json(output_dir / "package-preview.json")
        preview = stored_preview
    elif preview["can_apply"] is not True:
        raise HarnessError("SELFTEST_FIXED_PACKAGE_PREVIEW_BLOCKED")
    else:
        write_json(output_dir / "package-preview.json", preview)
    applied = await _mutate(
        api,
        output_dir,
        "package",
        root + "/test-assets/import/apply",
        {**payload, "expected_preview_fingerprint": preview["fingerprint"]},
    )
    return applied


async def install_fixed_baseline(
    api: PublicAPI,
    *,
    project_id: str,
    environment_id: str,
    service_id: str,
    batch_key: str,
    nonce: str,
    output_dir: Path,
    pack: CorePack | None = None,
    dynamic_batch: bool = False,
) -> FixedInstallation:
    frozen = pack or load_core_pack()
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", batch_key)
        or not 16 <= len(nonce) <= 160
    ):
        raise HarnessError("SELFTEST_FIXED_BATCH_ID_INVALID")
    root = f"/projects/{project_id}"
    identity: JsonObject = {
        "project_id": project_id,
        "environment_id": environment_id,
        "service_id": service_id,
        "batch_key": batch_key,
        "nonce": nonce,
        "pack_digest": frozen.digest,
        "dynamic_batch": dynamic_batch,
    }
    intent = output_dir / "installation-intent.json"
    if intent.exists() and read_json(intent) != identity:
        raise HarnessError("SELFTEST_FIXED_INSTALLATION_IDENTITY_MISMATCH")
    write_json(intent, identity)
    apis, workflows = await _install_workflows(
        api,
        frozen,
        project_id,
        service_id,
        batch_key,
        output_dir,
        dynamic_batch=dynamic_batch,
    )
    payload = _package(frozen, project_id, environment_id, batch_key, workflows)
    applied = await _apply_package(api, root, payload, output_dir)
    mappings = objects_value(applied["assets"])
    if len(mappings) != len(frozen.manifest.scenario_ids) + 1:
        raise HarnessError("SELFTEST_FIXED_PACKAGE_MAPPING_INCOMPLETE")
    assets: list[FixedAsset] = []
    for scenario, source, workflow in zip(
        frozen.manifest.scenario_ids, apis, workflows, strict=True
    ):
        matches = [
            item
            for item in mappings
            if item["kind"] == "case" and item["source_id"] == _source_id(batch_key, scenario)
        ]
        if len(matches) != 1:
            raise HarnessError("SELFTEST_FIXED_CASE_MAPPING_AMBIGUOUS")
        mapping = matches[0]
        case_id, case_version = (
            text_value(mapping["target_id"]),
            _mapped_version(mapping),
        )
        versions = objects_value(await api.request("GET", root + f"/test-cases/{case_id}/versions"))
        case = next((item for item in versions if item["version"] == case_version), None)
        if case is None or canonical_digest(case["definition"]) != canonical_digest(
            _case_definition(workflow, environment_id)
        ):
            raise HarnessError("SELFTEST_FIXED_CASE_READBACK_MISMATCH")
        assets.append(
            FixedAsset(
                scenario_id=scenario,
                api_id=UUID(text_value(source["id"])),
                api_version=integer_value(source["version"]),
                api_fingerprint=text_value(source["fingerprint"]),
                workflow_id=UUID(text_value(workflow["workflow_id"])),
                workflow_version_id=UUID(text_value(workflow["id"])),
                workflow_version=integer_value(workflow["version"]),
                workflow_fingerprint=text_value(workflow["fingerprint"]),
                case_id=UUID(case_id),
                case_version=case_version,
                case_fingerprint=text_value(case["fingerprint"]),
                api_sources=_pinned_sources(project_id, source),
            )
        )
    suites = [
        item
        for item in mappings
        if item["kind"] == "suite" and item["source_id"] == _source_id(batch_key, "suite")
    ]
    if len(suites) != 1:
        raise HarnessError("SELFTEST_FIXED_SUITE_MAPPING_AMBIGUOUS")
    suite_id, suite_version = (
        text_value(suites[0]["target_id"]),
        _mapped_version(suites[0]),
    )
    versions = objects_value(await api.request("GET", root + f"/test-suites/{suite_id}/versions"))
    suite = next((item for item in versions if item["version"] == suite_version), None)
    expected_items: JsonValue = [
        {"test_case_id": str(item.case_id), "test_case_version": item.case_version}
        for item in assets
    ]
    if suite is None or object_value(suite["definition"])["items"] != expected_items:
        raise HarnessError("SELFTEST_FIXED_SUITE_READBACK_MISMATCH")
    plan = await _mutate(
        api,
        output_dir,
        "plan",
        root + "/test-plans",
        {
            "name": f"{batch_key} 固定基准计划",
            "items": [
                {
                    "target_type": "suite",
                    "target_id": suite_id,
                    "target_version": suite_version,
                    "max_retries": 0,
                    **(
                        {"runtime_headers": dict(frozen.workflows[0].plan_runtime_headers)}
                        if frozen.workflows[0].plan_runtime_headers
                        else {}
                    ),
                }
            ],
        },
    )
    plan_items = objects_value(plan["items"])
    if len(plan_items) != 1 or (
        plan_items[0]["target_type"],
        plan_items[0]["target_id"],
        plan_items[0]["target_version"],
        plan_items[0]["max_retries"],
    ) != ("suite", suite_id, suite_version, 0):
        raise HarnessError("SELFTEST_FIXED_PLAN_READBACK_MISMATCH")
    installed = FixedInstallation(
        project_id=UUID(project_id),
        environment_id=UUID(environment_id),
        service_id=UUID(service_id),
        batch_key=batch_key,
        nonce=nonce,
        pack_digest=frozen.digest,
        assets=tuple(assets),
        suite_id=UUID(suite_id),
        suite_version=suite_version,
        plan_id=UUID(text_value(plan["id"])),
    )
    write_json(output_dir / "installation.json", installed)
    return installed


def _wire_matches(fixture: CoreFixture, observed: ScenarioObservation) -> bool:
    if observed.journal is None or len(observed.journal.entries) != len(fixture.wire):
        return False
    actual_entries = observed.journal.entries
    expected_entries = fixture.wire
    if fixture.wire_order == "unordered":
        actual_entries = tuple(
            sorted(
                actual_entries,
                key=lambda item: (item.request_body.branch or "") if item.request_body else "",
            )
        )
        expected_entries = tuple(sorted(expected_entries, key=lambda item: item.branch))
    for expected, actual in zip(expected_entries, actual_entries, strict=True):
        body = actual.request_body
        response = actual.response_body
        if body is None or (response is None and actual.binary_response is None):
            return False
        observed_wire = WireExpectation(
            value=body.value,
            branch=body.branch or "",
            iteration_key=body.iteration_key or "",
            response_status=actual.response_status,
            authorization_present=actual.authorization_present,
        )
        if canonical_digest(observed_wire.model_dump(mode="json")) != canonical_digest(
            expected.model_dump(mode="json")
        ) or (
            response is not None
            and canonical_digest(response.value) != canonical_digest(expected.value)
        ):
            return False
    return True


async def _control_page(
    reader: PublicAPI, base: str, fixture: CoreFixture
) -> tuple[tuple[EvidencePage, ...], bool]:
    if fixture.control is None:
        return (), True
    expected = fixture.control
    raw = await reader.object(
        "GET",
        base
        + f"/evidence/control-records?node_id={expected.node_id}&kind={expected.kind}"
        + "&page=1&page_size=100",
    )
    items = objects_value(raw["items"])
    page = EvidencePage(
        page=integer_value(raw["page"]),
        page_size=integer_value(raw["page_size"]),
        total=integer_value(raw["total"]),
        ordinals=tuple(integer_value(item["ordinal"]) for item in items),
        truncated=raw["truncated"] is not False,
    )
    matches = (
        raw["has_more"] is False
        and len(items) == expected.total == page.total
        and all(item["status"] == "passed" for item in items)
    )
    return (page,), matches


async def _collect_fixed(
    reader: PublicAPI,
    observer: PublicAPI,
    installed: FixedObservationInputs,
    run: JsonObject,
    pack: CorePack,
    output_dir: Path,
    deadline: datetime | None = None,
) -> list[ScenarioObservation]:
    items = objects_value(run["items"])
    if len(items) != len(installed.assets):
        raise HarnessError("SELFTEST_FIXED_PLAN_EXPANSION_MISMATCH")
    observations: list[ScenarioObservation] = []
    for asset, fixture in zip(installed.assets, pack.fixtures, strict=True):
        matches = [item for item in items if item["target_id"] == str(asset.case_id)]
        if len(matches) != 1:
            raise HarnessError("SELFTEST_FIXED_RUN_CASE_AMBIGUOUS")
        item = matches[0]
        execution_id = text_value(item["execution_id"])
        base = f"/ci/projects/{installed.project_id}/workflow-executions/{execution_id}"
        raw = await reader.object("GET", base + "/evidence")
        if (
            raw["source_case_id"],
            raw["source_case_version"],
            raw["source_plan_run_item_id"],
            raw["workflow_id"],
            raw["workflow_version_id"],
            raw["workflow_fingerprint"],
            raw["environment_id"],
        ) != (
            str(asset.case_id),
            asset.case_version,
            item["id"],
            str(asset.workflow_id),
            str(asset.workflow_version_id),
            asset.workflow_fingerprint,
            str(installed.environment_id),
        ):
            raise HarnessError("SELFTEST_FIXED_EXECUTION_SOURCE_MISMATCH")
        if (item["target_type"], item["target_version"], item["workflow_version"]) != (
            "case",
            asset.case_version,
            asset.workflow_version,
        ):
            raise HarnessError("SELFTEST_FIXED_RUN_VERSION_MISMATCH")
        execution = normalize_execution(raw)
        bindings = objects_value(raw["api_bindings"])
        expected_sources = {
            (
                str(source.api_definition_id),
                source.api_version,
                source.contract_fingerprint,
            )
            for source in asset.api_sources
        } or {(str(asset.api_id), asset.api_version, asset.api_fingerprint)}
        valid_bindings = (
            bool(bindings)
            and {
                (
                    binding["api_definition_id"],
                    binding["api_version"],
                    binding["contract_fingerprint"],
                )
                for binding in bindings
            }
            == expected_sources
        )
        ids = item["execution_ids"]
        if not isinstance(ids, list) or len(ids) > 4:
            raise HarnessError("SELFTEST_FIXED_ATTEMPTS_INVALID")
        attempts = tuple(
            [
                normalize_execution(
                    await reader.object(
                        "GET",
                        f"/ci/projects/{installed.project_id}/workflow-executions/{text_value(attempt)}/evidence",
                    )
                )
                for attempt in ids
            ]
        )
        receipt = await journal(observer, installed.batch_key, asset.scenario_id, deadline=deadline)
        pages, control_matches = await _control_page(reader, base, fixture)
        complete = (
            raw["truncated"] is False
            and raw["bindings_complete"] is True
            and item["attempts_complete"] is True
            and valid_bindings
            and raw["node_total"] == len(objects_value(raw["nodes"]))
            and all(node["assertions_complete"] is True for node in objects_value(raw["nodes"]))
        )
        golden = next(
            value for value in pack.expectations if value.scenario_id == asset.scenario_id
        )
        children, children_complete = (
            await collect_children(reader, str(installed.project_id), raw)
            if golden.expected.dataset is not None
            else ((), True)
        )
        observation = ScenarioObservation(
            children=children,
            children_complete=children_complete,
            scenario_id=asset.scenario_id,
            execution=execution,
            attempts=attempts,
            journal=receipt,
            control_pages=pages,
            cleanup_status="pending",
            evidence_complete=complete,
        )
        observation = observation.model_copy(
            update={
                "postcondition_matched": _wire_matches(fixture, observation) and control_matches
            }
        )
        write_json(output_dir / asset.scenario_id / "observed.json", observation)
        observations.append(observation)
    return observations


def _execution_junit(observations: list[ScenarioObservation], directory: Path) -> None:
    suite = Element("testsuite", name="FlowTest 固定基准原始执行", tests=str(len(observations)))
    failures = 0
    for observation in observations:
        case = SubElement(suite, "testcase", name=observation.scenario_id)
        execution = observation.execution
        if execution is None or execution.status not in {"passed", "failed"}:
            SubElement(case, "skipped", message="原始执行未完成")
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


async def execute_fixed_baseline(
    api: PublicAPI,
    reader: PublicAPI,
    observer: PublicAPI,
    *,
    project_id: str,
    environment_id: str,
    service_id: str,
    batch_key: str,
    nonce: str,
    fixture_digest: str,
    builds: Builds,
    output_dir: Path,
    pack: CorePack | None = None,
    deadline: datetime | None = None,
    before_launch: Callable[[FixedInstallation], Awaitable[None]] | None = None,
    enrich_observations: Callable[
        [FixedInstallation, list[ScenarioObservation]],
        Awaitable[list[ScenarioObservation]],
    ]
    | None = None,
    verification_scope: Literal["full_pack", "selected_suites", "diagnostic_subset"] = "full_pack",
    budget_scope: str | None = None,
) -> FixedResult:
    """Full fixed route after bootstrap. Register, import, run, observe, clean and verify."""
    frozen = pack or load_core_pack()
    started = datetime.now(UTC)
    expires = (
        min(deadline, started + timedelta(seconds=600))
        if deadline
        else started + timedelta(seconds=600)
    )
    if expires <= started:
        raise HarnessError("SELFTEST_FIXED_DEADLINE_EXPIRED")
    scope = FixtureBudgetScope(
        parent_batch_key=budget_scope or batch_key,
        nonce=nonce,
        expires_at=expires.timestamp(),
    )
    manifest = BatchManifest(
        fixture_budget=scope,
        pack_id=frozen.manifest.pack_id,
        pack_version=frozen.manifest.pack_version,
        pack_digest=frozen.digest,
        policy_digest=canonical_digest(
            {"request_budget": 500, "runtime_seconds": 600, "plan_retries": 0}
        ),
        project_id=UUID(project_id),
        batch_key=batch_key,
        nonce=nonce,
        builds=builds,
        batch_kind="fixed_baseline",
        verification_scope=verification_scope,
        expected_scenario_set=frozen.manifest.scenario_ids,
        required_scenario_set=frozen.manifest.scenario_ids,
        trusted_required_scenario_set=frozen.manifest.scenario_ids,
        scenarios=frozen.expectations,
        created_at=started,
        expires_at=expires,
    )
    write_json(output_dir / "manifest.json", manifest)
    if builds.fixture != fixture_digest:
        raise HarnessError("SELFTEST_FIXED_FIXTURE_BUILD_MISMATCH")
    cleanup = RoundCleanup(
        batch_key=batch_key,
        project_id=UUID(project_id),
        output_dir=output_dir,
        writer=api,
        reader=reader,
        observer=observer,
        nonce=nonce,
        fixture_digest=fixture_digest,
    )
    observations: list[ScenarioObservation] = []
    cleanup_ok = True
    installed: FixedInstallation | None = None
    observer_error: str | None = None
    try:
        async with asyncio.timeout((expires - started).total_seconds()):
            for fixture in frozen.fixtures:
                if datetime.now(UTC) >= expires:
                    raise HarnessError("SELFTEST_FIXED_DEADLINE_EXPIRED")
                cleanup.register_fixture(fixture.scenario_id)
                await observer.request(
                    "PUT",
                    f"/selftest/batches/{batch_key}/scenarios/{fixture.scenario_id}",
                    {
                        "nonce": nonce,
                        "fixture_digest": fixture_digest,
                        "budget_scope": scope.model_dump(mode="json"),
                        "ttl_seconds": max(1, int((expires - datetime.now(UTC)).total_seconds())),
                        "max_entries": 100,
                        "max_bytes": 131072,
                        **fixture.fixture.model_dump(mode="json"),
                    },
                )
            empty = await journal(observer, batch_key, frozen.fixtures[0].scenario_id)
            if empty.request_count != 0 or empty.fixture_digest != fixture_digest:
                raise HarnessError("SELFTEST_FIXED_FIXTURE_NOT_FRESH")
            manifest = manifest.model_copy(update={"fixture_epoch": empty.fixture_epoch})
            write_json(output_dir / "manifest.json", manifest)
            installed = await install_fixed_baseline(
                api,
                project_id=project_id,
                environment_id=environment_id,
                service_id=service_id,
                batch_key=batch_key,
                nonce=nonce,
                output_dir=output_dir,
                pack=frozen,
            )
            if datetime.now(UTC) >= expires:
                raise HarnessError("SELFTEST_FIXED_DEADLINE_EXPIRED")
            manifest = manifest.model_copy(
                update={
                    "scenarios": tuple(
                        expected.model_copy(update={"expected_api_sources": asset.api_sources})
                        for expected, asset in zip(
                            manifest.scenarios, installed.assets, strict=True
                        )
                    )
                }
            )
            write_json(output_dir / "manifest.json", manifest)
            if before_launch is not None:
                await before_launch(installed)
            cleanup.arm_plan(installed.plan_id, tuple(asset.case_id for asset in installed.assets))
            run = await _mutate(
                api,
                output_dir,
                "run",
                f"/projects/{project_id}/test-plans/{installed.plan_id}/runs",
                {},
            )
            cleanup.started_plan(UUID(text_value(run["id"])))
            run = await wait_plan(reader, project_id, text_value(run["id"]), expires)
            cleanup.plan.observe(run)
            write_json(output_dir / "plan-run.json", run)
            observations = await _collect_fixed(
                reader, observer, installed, run, frozen, output_dir, deadline=expires
            )
            if enrich_observations is not None:
                observations = await enrich_observations(installed, observations)
    except (HarnessError, httpx.HTTPError, OSError, ValueError, TimeoutError) as error:
        observer_error = failure_codes(error)[0]
    finally:
        cleanup_receipt = await cleanup.finish()
        cleanup_ok = cleanup_receipt.status == "completed"
    present = {item.scenario_id for item in observations}
    observations.extend(
        ScenarioObservation(
            scenario_id=scenario,
            cleanup_status="pending",
            evidence_complete=False,
            read_error=observer_error or "SELFTEST_FIXED_OBSERVATION_MISSING",
        )
        for scenario in frozen.manifest.scenario_ids
        if scenario not in present
    )
    observations = [
        item.model_copy(update={"cleanup_status": "completed" if cleanup_ok else "failed"})
        for item in observations
    ]
    evidence = BatchEvidence(
        batch_key=batch_key,
        nonce=nonce,
        pack_digest=manifest.pack_digest,
        policy_digest=manifest.policy_digest,
        builds=builds,
        collected_at=datetime.now(UTC),
        scenarios=tuple(observations),
        cleanup_status="completed" if cleanup_ok else "failed",
        observer_error=observer_error,
    )
    write_json(output_dir / "evidence.json", evidence)
    _execution_junit(observations, output_dir)
    report = verify_batch(manifest, evidence)
    write_report(report, output_dir)
    return FixedResult(manifest=manifest, evidence=evidence, report=report, installation=installed)
