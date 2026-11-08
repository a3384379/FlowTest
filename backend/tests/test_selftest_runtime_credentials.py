"""Real A CI-reader and M observer API contracts, using distinct synthetic role tokens."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.bootstrap import BootstrapResult, Credentials, Installation
from scripts.selftest.io import PublicAPI
from scripts.selftest.local_stack import ROOT, StackBinding
from scripts.selftest.run_runtime_faults import observer_clients
from test_selftest_product_api import ProductContext, _fixed
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.main import app


class ScopedASGITransport(httpx.AsyncBaseTransport):
    def __init__(self, fixture):
        self.runner = httpx.ASGITransport(app=app)
        self.fixture = httpx.ASGITransport(app=fixture)

    async def handle_async_request(self, request):
        selected = self.runner if request.url.host == "runner.test" else self.fixture
        return await selected.handle_async_request(request)


def mock_observer(tmp_path):
    root = ROOT
    package = "runtime_fault_mock_app"
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            package,
            root / "mock-target/app/__init__.py",
            submodule_search_locations=[str(root / "mock-target/app")],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        spec.loader.exec_module(module)
    fixture = importlib.import_module(package + ".selftest")
    journal = importlib.import_module(package + ".selftest_journal")
    store = journal.FixtureStore(tmp_path / "journal.sqlite")
    store.start_epoch()
    return fixture.observer_app(store, "m-management-" + "1" * 32)


def binding():
    return StackBinding(
        project_name="flowtest-selftest-" + "1" * 12,
        nonce="2" * 32,
        runner_url="http://runner.test",
        target_url="http://target.test",
        observer_url="http://observer.test",
        private_subnet="172.18.0.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image="fixture",
        fixture_image_digest="sha256:" + "b" * 64,
        source_digest="c" * 64,
        dependency_digest="d" * 64,
        runner_container_id="e" * 64,
        target_container_id="f" * 64,
        observer_container_id="0" * 64,
        runner_volume="owned-runner",
        target_volume="owned-target",
    )


@pytest.mark.asyncio
async def test_real_ci_read_execution_scope_is_distinct_from_mock_management_role(
    product: ProductContext, tmp_path
):
    batch, _ = await _fixed(product)
    created = await product.post(
        f"/api/v1/projects/{product.project_id}/service-tokens",
        {"name": "bounded O reader", "scopes": ["read:execution"]},
        status=201,
    )
    writer_token = product.headers["Authorization"].removeprefix("Bearer ")
    credentials = Credentials(
        "bootstrap-admin",
        writer_token,
        "b-admin",
        "mcp-generation",
        created["token"],
        writer_token,
        "b-viewer",
    )
    installation = Installation(
        binding_nonce="2" * 32,
        organization_id=uuid4(),
        project_id=product.project_id,
        reviewer_id=uuid4(),
        reviewer_email="reviewer@example.test",
        mcp_account_id=uuid4(),
        target_project_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.test",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
    )
    boot = BootstrapResult(installation, credentials)
    fixture = mock_observer(tmp_path)
    transport = ScopedASGITransport(fixture)
    reader, observer = observer_clients(
        binding(), boot, "m-management-" + "1" * 32, transport=transport
    )
    wrong_a = PublicAPI("http://runner.test", credentials.capture_viewer_token, transport=transport)
    wrong_m = PublicAPI(
        "http://observer.test", credentials.observer_token, api_prefix="", transport=transport
    )
    try:
        path = f"/ci/projects/{product.project_id}/test-plan-runs/{batch['plan_run_ids'][0]}"
        exact = await reader.object("GET", path)
        assert exact["run_id"] == batch["plan_run_ids"][0]
        rejected = await wrong_a.request("GET", path, allow_status=(401, 403))
        assert rejected["error"]["trace_id"]
        policy = {
            "nonce": "3" * 32,
            "fixture_digest": "a" * 64,
            "ttl_seconds": 60,
            "max_entries": 10,
            "max_bytes": 4096,
            "response_statuses": [200],
            "response_body": {"actual": 1, "code": 0, "value": None},
            "delay_ms": 0,
        }
        await observer.request("PUT", "/selftest/batches/owned/scenarios/role", policy)
        journal = await observer.object("GET", "/selftest/batches/owned/scenarios/role/journal")
        assert journal["request_count"] == 0
        denied = await wrong_m.request(
            "GET", "/selftest/batches/owned/scenarios/role/journal", allow_status=(401,)
        )
        assert denied["error"]["code"] == "FIXTURE_OBSERVER_AUTH_REQUIRED"
    finally:
        await reader.close()
        await observer.close()
        await wrong_a.close()
        await wrong_m.close()


@pytest.mark.asyncio
async def test_real_public_publish_pins_unspecified_api_before_case_suite_plan(
    product: ProductContext, tmp_path
):
    from scripts.selftest.runtime_faults import install

    api = PublicAPI(
        "http://runner.test",
        product.headers["Authorization"].removeprefix("Bearer "),
        transport=httpx.ASGITransport(app=app),
    )
    try:
        assets = await install(
            api,
            project=product.project_id,
            service=product.mapping.fixture_service_id,
            fixture_url="http://mock-target:8080",
            batch="runtime-publish-contract",
            scenario="ST-RUN-006-unpinned-control",
            directory=tmp_path / "install",
            pinned=False,
        )
        workflow = await api.object(
            "GET", f"/projects/{product.project_id}/workflows/{assets.workflow_id}"
        )
        assert all(
            "api_version" not in item["config"]
            for item in workflow["draft_definition"]["nodes"]
            if item["type"] == "api"
        )
        versions = await api.request(
            "GET", f"/projects/{product.project_id}/workflows/{assets.workflow_id}/versions"
        )
        published = versions[0]["definition"]
        assert all(
            item["config"]["api_version"] == 1
            for item in published["nodes"]
            if item["type"] == "api"
        )
        assert assets.pinned is False
        assert assets.workflow_version == 1 and assets.plan_id
    finally:
        await api.close()
