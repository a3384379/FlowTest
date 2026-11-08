"""Recover a reused public installation in a fresh H directory without mutations."""

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.main import app
from app.schemas.self_tests import (
    AgentTaskResponse,
    BatchResponse,
    Budget,
    BuildIdentity,
    ExpectedResult,
    FrozenBatchManifest,
    InstallationMapping,
    InstallationResponse,
    PublishedAsset,
    ScenarioAssets,
    ScenarioKey,
    TemplateResponse,
    TemplateScenario,
)
from app.services.self_test_catalog import templates

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.fixed_baseline import (
    FixedInstallation,
    install_fixed_baseline,
    load_core_pack,
)
from scripts.selftest.fixed_recovery import recover_fixed_assets
from scripts.selftest.io import HarnessError, PublicAPI, read_json
from scripts.selftest.product_fixed import prepare_task


@dataclass
class RecoveryContext:
    api: PublicAPI
    task: AgentTaskResponse
    installed: FixedInstallation
    requests: list[tuple[str, str]]


class ReadOnlyVersions(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.delegate = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.url.path.endswith("/prepared"):
            return httpx.Response(200, json={"accepted": True})
        assert request.method == "GET", "Recovery must not create, edit, publish or run assets"
        return await self.delegate.handle_async_request(request)


@pytest.fixture
async def recovery(
    tasking_context: TaskingTestContext,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> RecoveryContext:
    headers = await _login_headers(tasking_context.client)
    token = headers["Authorization"].removeprefix("Bearer ")
    api = PublicAPI("http://test", token, transport=httpx.ASGITransport(app=app))
    identifier = getattr(request, "param", "core-v1")
    pack = load_core_pack(Path(__file__).parents[2] / "selftest" / "packs" / identifier)
    try:
        project = await api.object("POST", "/projects", {"name": "恢复隔离项目"})
        root = f"/projects/{project['id']}"
        environment = await api.object(
            "POST",
            root + "/environments",
            {"name": "固定目标", "base_url": "http://fixed.example", "classification": "test"},
        )
        service = await api.object(
            "POST", root + "/services", {"name": "固定目标", "service_key": "fixture"}
        )
        installed = await install_fixed_baseline(
            api,
            project_id=str(project["id"]),
            environment_id=str(environment["id"]),
            service_id=str(service["id"]),
            batch_key="old-installation",
            nonce="n" * 64,
            output_dir=tmp_path / "old-state",
            pack=pack,
            dynamic_batch=True,
        )
    finally:
        await api.close()
    template = next((item for item in templates() if item.id == identifier), None)
    if template is None:
        template = TemplateResponse(
            id=identifier,
            title="登记扩展固定包",
            batch_kind="fixed_baseline",
            pack_digest=pack.digest,
            task_set_digest=pack.digest,
            scenarios=tuple(
                TemplateScenario(
                    scenario_id=item.scenario_id,
                    title=item.scenario_id,
                    category="engine",
                    expected=ExpectedResult(
                        status=item.expected.execution_status,
                        error_code=item.expected.error_code,
                        phase=item.expected.phase,
                    ),
                )
                for item in pack.expectations
            ),
        )
    now = datetime.now(UTC)
    batch_id, installation_id, binding_id = uuid4(), uuid4(), uuid4()
    builds = BuildIdentity(runner="candidate", target="candidate", fixture="f" * 64, verifier="o")
    frozen = FrozenBatchManifest(
        batch_id=batch_id,
        installation_id=installation_id,
        project_id=installed.project_id,
        binding_id=binding_id,
        template=template,
        scenarios=template.scenarios,
        batch_kind="fixed_baseline",
        generation_mode=None,
        verification_scope="full_pack",
        budget=Budget(),
        binding_fingerprint="a" * 64,
        environment_fingerprint="b" * 64,
        builds=builds,
        created_at=now,
        deadline=now + timedelta(seconds=600),
    )
    mapping = InstallationMapping(
        environment_id=installed.environment_id,
        target_environment_id=uuid4(),
        fixture_service_id=installed.service_id,
        target_service_id=uuid4(),
        target_project_id=uuid4(),
        target_organization_id=uuid4(),
        target_user_id=uuid4(),
        target_instance_id="target-test",
        target_build_digest=builds.target,
        assets=tuple(
            ScenarioAssets(
                scenario_id=asset.scenario_id,
                workflow=PublishedAsset(
                    id=asset.workflow_id,
                    version=asset.workflow_version,
                    fingerprint=asset.workflow_fingerprint,
                ),
                case=PublishedAsset(
                    id=asset.case_id, version=asset.case_version, fingerprint=asset.case_fingerprint
                ),
            )
            for asset in installed.assets
        ),
    )
    installation = InstallationResponse.model_construct(
        id=installation_id,
        task_id=installation_id,
        project_id=installed.project_id,
        binding_id=binding_id,
        template_id=identifier,
        template_version=template.version,
        pack_digest=pack.digest,
        status="ready",
        revision=1,
        mapping=mapping,
        environment_fingerprint=frozen.environment_fingerprint,
    )
    batch = BatchResponse.model_construct(
        id=batch_id,
        installation_id=installation_id,
        project_id=installed.project_id,
        binding_id=binding_id,
        batch_key="fresh-batch",
        manifest_digest=canonical_digest(frozen.model_dump(mode="json")),
        policy_digest="c" * 64,
        verification_scope="full_pack",
        created_at=now,
        deadline=frozen.deadline,
        required_scenario_set=tuple(
            ScenarioKey(scenario_id=item.scenario_id) for item in template.scenarios
        ),
    )
    task = AgentTaskResponse.model_construct(
        task_kind="preparation",
        task_id=batch_id,
        project_id=installed.project_id,
        binding_id=binding_id,
        nonce="q" * 64,
        lease_token="l" * 64,
        binding_fingerprint=frozen.binding_fingerprint,
        environment_fingerprint=frozen.environment_fingerprint,
        builds=builds,
        installation=installation,
        batch=batch,
        frozen_manifest=frozen,
        budget=frozen.budget,
    )
    transport = ReadOnlyVersions()
    reader = PublicAPI("http://test", token, transport=transport)
    try:
        yield RecoveryContext(reader, task, installed, transport.requests)
    finally:
        await reader.close()


@pytest.mark.parametrize("recovery", ["core-v1", "extended-v1"], indirect=True)
async def test_ready_fixed_installation_prepares_in_fresh_state_without_old_local_receipt(
    recovery: RecoveryContext,
    tmp_path: Path,
) -> None:
    task = recovery.task
    assert task.batch is not None
    observer_requests: list[tuple[str, str]] = []

    def fixture(request: httpx.Request) -> httpx.Response:
        observer_requests.append((request.method, request.url.path))
        if request.method == "PUT":
            payload = json.loads(request.content)
            assert (
                payload["nonce"] == task.nonce and payload["fixture_digest"] == task.builds.fixture
            )
            return httpx.Response(200, json={"registered": True})
        return httpx.Response(
            200,
            json={
                "batch_key": task.batch.batch_key,
                "scenario_id": task.frozen_manifest.scenarios[0].scenario_id,
                "nonce": task.nonce,
                "fixture_epoch": "real-fresh-fixture-epoch",
                "fixture_digest": task.builds.fixture,
                "request_count": 0,
                "entries": [],
                "truncated": False,
                "expired": False,
                "epoch_changed": False,
                "next_sequence": None,
            },
        )

    observer = PublicAPI("http://observer", api_prefix="", transport=httpx.MockTransport(fixture))
    fresh = tmp_path / "fresh-state"
    assert not (fresh / str(task.installation.id) / "installation.json").exists()
    try:
        await prepare_task(
            recovery.api,
            observer,
            task,
            directory=fresh / str(task.task_id),
            installation_directory=fresh / str(task.installation.id),
            asset_reader=recovery.api,
        )
    finally:
        await observer.close()
    saved = read_json(fresh / str(task.task_id) / "installation.json")
    assert saved["project_id"] == str(task.project_id) and saved["nonce"] == task.nonce
    assert saved["assets"] == [asset.model_dump(mode="json") for asset in recovery.installed.assets]
    assert not {"suite_id", "suite_version", "plan_id"} & set(saved)
    assert len(observer_requests) == len(recovery.installed.assets) + 1
    assert recovery.requests[-1] == (
        "POST",
        f"/api/v1/agent/projects/{task.project_id}/self-tests/runs/{task.task_id}/prepared",
    )
    assert all(method == "GET" for method, _ in recovery.requests[:-1])


@pytest.mark.parametrize(
    ("change", "code", "read_count"),
    [
        ("missing", "ASSET_SET_MISMATCH", 0),
        ("extra", "ASSET_SET_MISMATCH", 0),
        ("duplicate", "ASSET_SET_MISMATCH", 0),
        ("workflow_fingerprint", "WORKFLOW_FINGERPRINT_MISMATCH", 1),
        ("case_fingerprint", "CASE_SOURCE_MISMATCH", 3),
        ("unknown_workflow", "WORKFLOW_NOT_FOUND", 1),
        ("unknown_case", "TEST_CASE_NOT_FOUND", 3),
        ("environment", "CASE_SOURCE_MISMATCH", 3),
        ("service", "API_SOURCE_MISMATCH", 2),
    ],
)
async def test_recovery_rejects_incomplete_extra_unknown_or_drifted_registered_sources(
    recovery: RecoveryContext,
    change: str,
    code: str,
    read_count: int,
) -> None:
    task = recovery.task
    mapping = task.installation.mapping
    assert mapping is not None
    assets = list(mapping.assets)
    first = assets[0]
    if change == "missing":
        assets = assets[1:]
    elif change == "extra":
        assets.append(first.model_copy(update={"scenario_id": "ST-UNKNOWN"}))
    elif change == "duplicate":
        assets.append(first)
    elif change in {"workflow_fingerprint", "unknown_workflow"}:
        field = {"fingerprint": "0" * 64} if change == "workflow_fingerprint" else {"id": uuid4()}
        assets[0] = first.model_copy(update={"workflow": first.workflow.model_copy(update=field)})
    elif change in {"case_fingerprint", "unknown_case"}:
        field = {"fingerprint": "0" * 64} if change == "case_fingerprint" else {"id": uuid4()}
        assets[0] = first.model_copy(update={"case": first.case.model_copy(update=field)})
    updates = {"assets": tuple(assets)}
    if change == "environment":
        updates["environment_id"] = uuid4()
    elif change == "service":
        updates["fixture_service_id"] = uuid4()
    changed = task.model_copy(
        update={
            "installation": task.installation.model_copy(
                update={"mapping": mapping.model_copy(update=updates)}
            )
        }
    )
    with pytest.raises(HarnessError, match=code):
        await recover_fixed_assets(recovery.api, changed, load_core_pack())
    assert len(recovery.requests) == read_count
    assert all(method == "GET" for method, _ in recovery.requests)


async def test_recovery_rejects_api_request_drift_from_a_real_publicly_published_workflow(
    recovery: RecoveryContext,
    tasking_context: TaskingTestContext,
) -> None:
    task = recovery.task
    mapping = task.installation.mapping
    assert mapping is not None
    headers = await _login_headers(tasking_context.client)
    client = tasking_context.client
    first = recovery.installed.assets[0]
    root = f"/api/v1/projects/{task.project_id}"
    request = dict(load_core_pack().apis[0].request)
    request["path"] = str(request["path"]).replace("{batch_key}", "{{selftest_batch_key}}")
    request.update(base_version=first.api_version, body={"changed_after_installation": True})
    version = await client.post(
        root + f"/apis/{first.api_id}/versions", headers=headers, json=request
    )
    assert version.status_code == 201, version.text
    workflow = await client.get(root + f"/workflows/{first.workflow_id}", headers=headers)
    assert workflow.status_code == 200
    graph = workflow.json()["draft_definition"]
    for node in graph["nodes"]:
        if node["type"] == "api":
            node["config"]["api_version"] = version.json()["version"]
    changed = await client.patch(
        root + f"/workflows/{first.workflow_id}",
        headers=headers,
        json={"expected_revision": workflow.json()["draft_revision"], "definition": graph},
    )
    assert changed.status_code == 200, changed.text
    published = await client.post(
        root + f"/workflows/{first.workflow_id}/versions", headers=headers
    )
    assert published.status_code == 200, published.text
    assets = list(mapping.assets)
    assets[0] = assets[0].model_copy(
        update={
            "workflow": PublishedAsset(
                id=first.workflow_id,
                version=published.json()["version"],
                fingerprint=published.json()["fingerprint"],
            )
        }
    )
    altered = task.model_copy(
        update={
            "installation": task.installation.model_copy(
                update={"mapping": mapping.model_copy(update={"assets": tuple(assets)})}
            )
        }
    )
    with pytest.raises(HarnessError, match="API_SOURCE_MISMATCH"):
        await recover_fixed_assets(recovery.api, altered, load_core_pack())
    assert len(recovery.requests) == 2
    assert all(method == "GET" for method, _ in recovery.requests)


async def test_selected_target_budget_does_not_count_readonly_metadata_as_business_requests(
    recovery: RecoveryContext,
) -> None:
    task = recovery.task
    assert task.frozen_manifest is not None and task.batch is not None
    frozen = task.frozen_manifest.model_copy(
        update={
            "scenarios": task.frozen_manifest.scenarios[:1],
            "budget": Budget(max_requests=10),
            "verification_scope": "diagnostic_subset",
        }
    )
    task = task.model_copy(
        update={
            "frozen_manifest": frozen,
            "budget": frozen.budget,
            "batch": task.batch.model_copy(
                update={"manifest_digest": canonical_digest(frozen.model_dump(mode="json"))}
            ),
        }
    )
    restored = await recover_fixed_assets(recovery.api, task, load_core_pack())
    assert tuple(item.scenario_id for item in restored.assets) == (frozen.scenarios[0].scenario_id,)
    assert len(recovery.requests) == 24


async def test_recovery_deadline_prevents_all_asset_and_mock_calls(
    recovery: RecoveryContext,
) -> None:
    assert recovery.task.batch is not None
    task = recovery.task.model_copy(
        update={
            "batch": recovery.task.batch.model_copy(
                update={"deadline": datetime.now(UTC) - timedelta(seconds=1)}
            )
        }
    )
    with pytest.raises(HarnessError, match="RECOVERY_BUDGET_EXHAUSTED"):
        await recover_fixed_assets(recovery.api, task, load_core_pack())
    assert recovery.requests == []
