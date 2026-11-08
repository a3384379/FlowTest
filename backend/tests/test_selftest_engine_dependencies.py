"""Native dependency behavior via public APIs; supplemental O projections remain explicit."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from test_selftest_fixed_baseline import RunningAPI, _dependencies, _fixture_apps
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.engine.contracts import WorkflowDefinition
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import Builds, canonical_digest  # noqa: E402
from scripts.selftest.fixed_baseline import (  # noqa: E402
    CorePack,
    CoreSource,
    _install_additional_source,
    _mutate,
    execute_fixed_baseline,
    load_core_pack,
)
from scripts.selftest.io import PublicAPI  # noqa: E402

PACK = ROOT / "selftest/packs/engine-additional-v1"


@dataclass(repr=False)
class DependencyContext:
    api: RunningAPI
    reader: PublicAPI
    observer: PublicAPI
    target: httpx.AsyncClient
    project: str
    environment: str
    service: str
    headers: dict[str, str]


@pytest.fixture
async def dependency_context(tasking_context: TaskingTestContext, tmp_path: Path):
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    project, environment, service = await _dependencies(api)
    token = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "依赖证据", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", str(token["token"]), transport=httpx.ASGITransport(app=app))
    business, management = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=management),
    )
    target = httpx.AsyncClient(
        base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
    )
    try:
        yield DependencyContext(
            api, reader, observer, target, project, environment, service, headers
        )
    finally:
        await target.aclose()
        await observer.close()
        await reader.close()
        await api.close()


def _replace(value: Any, bindings: dict[str, str]) -> Any:
    if isinstance(value, str):
        return bindings.get(value, value)
    if isinstance(value, list):
        return [_replace(item, bindings) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, bindings) for key, item in value.items()}
    return value


def _bound_pack(scenario: str, bindings: dict[str, str], directory: Path) -> CorePack:
    original = load_core_pack(PACK)
    index = original.manifest.scenario_ids.index(scenario)
    workflow = _replace(original.workflows[index].model_dump(mode="json"), bindings)
    documents = {
        "api-definitions.json": {"apis": [original.apis[index].model_dump(mode="json")]},
        "workflows.json": {"workflows": [workflow]},
        "expectations.json": {
            "expectations": [
                _replace(original.expectations[index].model_dump(mode="json"), bindings)
            ],
            "fixtures": [original.fixtures[index].model_dump(mode="json")],
        },
    }
    directory.mkdir()
    manifest = original.manifest.model_dump(mode="json")
    manifest.update(
        scenario_ids=[scenario],
        files={key: canonical_digest(value) for key, value in documents.items()},
    )
    for filename, content in {**documents, "manifest.json": manifest}.items():
        (directory / filename).write_text(json.dumps(content, ensure_ascii=False, indent=2))
    # Reopen the exact pre-run bytes; expectations are never derived from a run.
    return load_core_pack(directory)


def _specification(kind: str) -> dict[str, Any]:
    specification = json.loads((PACK / "dependencies.json").read_text())
    requirements = json.loads((PACK / "acceptance-requirements.json").read_text())
    assert canonical_digest(specification) == requirements["dependencies_digest"]
    return specification[kind]


async def _subflow(
    context: DependencyContext, batch: str, directory: Path
) -> tuple[dict[str, str], dict[str, Any]]:
    specification = _specification("subflow")
    pinned = await _install_additional_source(
        context.api,
        CoreSource(
            source_id=specification["api_placeholder"],
            name="Return固定API",
            request=specification["api_request"],
        ),
        context.project,
        context.service,
        batch,
        directory,
        phase="child-api",
        dynamic_batch=False,
    )
    bindings = {specification["api_placeholder"]: pinned["id"]}
    graph = _replace(specification["versions"][0]["definition"], bindings)
    native = {
        "format_version": "flowtest-workflow-native-v1",
        "name": batch + " Return子流程",
        "description": "冻结Return+Finally",
        "definition": graph,
    }
    root = f"/projects/{context.project}/workflows"
    child = await _mutate(context.api, directory, "child-workflow", root + "/native-import", native)
    assert await context.api.object("GET", root + f"/{child['id']}/native-export") == native
    version = await _mutate(
        context.api, directory, "child-publish-v1", root + f"/{child['id']}/versions", {}
    )
    expected_fingerprint = canonical_digest(
        WorkflowDefinition.model_validate(graph).model_dump(mode="json", exclude_none=True)
    )
    assert version["fingerprint"] == expected_fingerprint
    newer = _replace(specification["versions"][1]["definition"], bindings)
    changed = await context.api.object(
        "PATCH",
        root + f"/{child['id']}",
        {"expected_revision": child["draft_revision"], "definition": newer},
    )
    assert changed["draft_revision"] > child["draft_revision"]
    current = await _mutate(
        context.api, directory, "child-publish-v2", root + f"/{child['id']}/versions", {}
    )
    assert current["version"] == 2 and current["fingerprint"] != expected_fingerprint
    return {specification["workflow_placeholder"]: child["id"]}, {
        "workflow_id": child["id"],
        "version": 1,
        "fingerprint": expected_fingerprint,
        "api_id": pinned["id"],
        "api_version": pinned["version"],
        "api_fingerprint": pinned["fingerprint"],
    }


async def _dataset(
    context: DependencyContext, tasking_context: TaskingTestContext
) -> tuple[dict[str, str], dict[str, Any]]:
    specification = _specification("dataset")
    content = json.dumps(specification["rows"], ensure_ascii=False, separators=(",", ":")).encode()
    uploaded = await tasking_context.client.post(
        f"/api/v1/projects/{context.project}/files",
        headers=context.headers,
        files={"file": (specification["filename"], content, "application/json")},
    )
    assert uploaded.status_code == 201, uploaded.text
    artifact = uploaded.json()
    digest = hashlib.sha256(content).hexdigest()
    assert artifact["sha256"] == digest
    downloaded = await tasking_context.client.get(
        f"/api/v1/projects/{context.project}/files/{artifact['id']}", headers=context.headers
    )
    assert downloaded.content == content
    return {specification["artifact_placeholder"]: artifact["id"]}, {
        "artifact_id": artifact["id"],
        "sha256": digest,
        "row_count": 2,
    }


async def _subflow_proof(
    context: DependencyContext, detail: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    snapshot = detail["execution"]["snapshot"]["subflows"]["call_child"]
    assert (
        snapshot["workflow"]["id"],
        snapshot["workflow"]["version"],
        snapshot["workflow"]["fingerprint"],
    ) == (expected["workflow_id"], 1, expected["fingerprint"])
    api = snapshot["apis"]["finally_request"]
    assert (api["definition_id"], api["version"]) == (expected["api_id"], 1)
    versions = await context.api.request(
        "GET", f"/projects/{context.project}/apis/{expected['api_id']}/versions"
    )
    version = next(item for item in versions if item["version"] == 1)
    assert version["contract_fingerprint"] == expected["api_fingerprint"]
    call = next(node for node in detail["nodes"] if node["node_id"] == "call_child")
    assert call["output"]["return"] == {"result": 42}
    return {"source": expected, "return": {"result": 42}, "child_source_exact": True}


async def _rows_proof(
    context: DependencyContext, detail: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    children = detail["children"]
    assert len(children) == 2
    assert {child["dataset_row_index"] for child in children} == {0, 1}
    assert len({child["id"] for child in children}) == 2
    actual = []
    for child in sorted(children, key=lambda child: child["dataset_row_index"]):
        assert child["status"] == "passed"
        row = await context.api.object(
            "GET", f"/projects/{context.project}/workflow-executions/{child['id']}"
        )
        assert row["execution"]["parent_execution_id"] == detail["execution"]["id"]
        assert row["execution"]["status"] == "passed"
        node = next(item for item in row["nodes"] if item["node_id"] == "row_request")
        actual.append(node["output"]["body"]["value"])
        assertion = next(item for item in row["nodes"] if item["node_id"] == "assert_row_status")
        assert assertion["status"] == "passed"
    assert canonical_digest(actual) == canonical_digest([0, False])
    return {
        "source": expected,
        "indices": [0, 1],
        "statuses": ["passed", "passed"],
        "actual_value_digests": [canonical_digest(value) for value in actual],
    }


@pytest.mark.parametrize("kind", ["subflow", "dataset"])
async def test_pinned_native_subflow_return_and_dataset_rows_reach_case_suite_plan(
    dependency_context: DependencyContext,
    tasking_context: TaskingTestContext,
    tmp_path: Path,
    kind: str,
) -> None:
    context = dependency_context
    scenario = "ST-ADD-subflow-return" if kind == "subflow" else "ST-ADD-dataset-rows"
    batch = "additional-dependency-" + kind
    bindings, frozen = (
        await _subflow(context, batch, tmp_path)
        if kind == "subflow"
        else await _dataset(context, tasking_context)
    )
    pack = _bound_pack(scenario, bindings, tmp_path / "bound")

    async def forward(request: httpx.Request) -> httpx.Response:
        response = await context.target.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    with respx.mock as routes:
        routes.route(host="fixed-fixture.example").mock(side_effect=forward)
        result = await execute_fixed_baseline(
            context.api,
            context.reader,
            context.observer,
            project_id=context.project,
            environment_id=context.environment,
            service_id=context.service,
            batch_key=batch,
            nonce="dependency-nonce-001",
            fixture_digest="a" * 64,
            builds=Builds(
                runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
            ),
            output_dir=tmp_path / "result",
            pack=pack,
            verification_scope="selected_suites",
        )
    expected_findings = {"OWNED_ASSET_DISPOSAL_REQUIREMENT_MISSING"} if kind == "dataset" else set()
    assert {
        finding.code for item in result.report.scenarios for finding in item.findings
    } == expected_findings, result.report.model_dump_json(indent=2)
    assert result.report.exit_code == (2 if kind == "dataset" else 0)
    observation = result.evidence.scenarios[0]
    detail = await context.api.object(
        "GET", f"/projects/{context.project}/workflow-executions/{observation.execution.id}"
    )
    proof = (
        await _subflow_proof(context, detail, frozen)
        if kind == "subflow"
        else await _rows_proof(context, detail, frozen)
    )
    (tmp_path / "result/dependency-proof-asgi-only.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2)
    )
    assert observation.cleanup_status == "completed"
