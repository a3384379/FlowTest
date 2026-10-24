"""Real public after-review/native execution; the before seal is a synthetic fixture."""

import sys
from pathlib import Path
from uuid import UUID

import httpx
import respx
from httpx import Response
from test_selftest_assisted import assisted_contract
from test_selftest_product_api import ProductContext
from test_selftest_product_api import product as product
from test_selftest_retention import owned_storage as owned_storage
from test_tasking_api import tasking_context as tasking_context

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_assisted import _case, _flow  # noqa: E402
from scripts.selftest.host_launch import VerifiedGrant  # noqa: E402
from scripts.selftest.host_revisions import AssistedSelection  # noqa: E402
from scripts.selftest.io import PublicAPI  # noqa: E402
from test_selftest_host_adapter import authorization  # noqa: E402

from app.main import app  # noqa: E402
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator  # noqa: E402


class ReadbackTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.asgi = httpx.ASGITransport(app=app)
        self.calls = []

    async def handle_async_request(self, request):
        self.calls.append((request.method, request.url.path))
        return await self.asgi.handle_async_request(request)

    async def aclose(self):
        await self.asgi.aclose()


@respx.mock
async def test_reviewed_assisted_assets_readback_then_real_new_suite_plan_run(
    product: ProductContext, owned_storage: object
):
    task, before, payload = await assisted_contract(product)
    source = payload["sources"][0]
    lineage = source["assisted"]
    selected = AssistedSelection(
        scenario_id=source["scenario_id"],
        variant_key=source["variant_key"],
        workflow_proposal_id=source["workflow_proposal"]["change_set_id"],
        case_proposal_id=source["case_proposal"]["change_set_id"],
        case_item_id=source["case_proposal"]["item_id"],
        editor_id=lineage["editor_id"],
        reason="隔离公开 API 回归,原批次 seal 为合成 fixture",
    )
    auth = authorization(
        project_id=product.project_id,
        reviewer_ids=(UUID(lineage["workflow_reviewer_id"]),),
        review_mode="ci_fixture",
    )
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    transport = ReadbackTransport()
    api = PublicAPI(
        "http://test",
        product.headers["Authorization"].removeprefix("Bearer "),
        transport=transport,
    )
    try:
        workflow = await _flow(api, product.project_id, selected, grant)
        case = await _case(api, product.project_id, selected, grant)
    finally:
        await api.close()
    assert workflow.workflow["id"] == source["workflow"]["id"]
    assert workflow.version["fingerprint"] == source["workflow"]["fingerprint"]
    assert case.case["id"] == source["case"]["id"]
    assert case.version["fingerprint"] == source["case"]["fingerprint"]
    assert workflow.proposal.reviewer_id == case.proposal.reviewer_id == selected.editor_id
    assert all(method == "GET" for method, _ in transport.calls)
    assert not any(
        path.endswith(f"/mcp/write/change-sets/{selected.workflow_proposal_id}")
        for _, path in transport.calls
    )
    ready = await product.post(
        product.agent + f"/runs/{task['task_id']}/materialized", payload, machine="h"
    )
    assert ready["plan_run_ids"] == []
    target = respx.get("http://fixture.example/value").mock(
        return_value=Response(200, json={"actual": 1})
    )
    run = await product.post(
        product.root + f"/runs/{task['task_id']}/execute-materialized",
        {
            "resource_digest": ready["resource_digest"],
            "environment_fingerprint": ready["environment_fingerprint"],
            "confirmed": True,
        },
        key="reviewed-assisted-native-execute",
        status=202,
    )
    assert run["resource_snapshot"]["suite"]["version"] == 1
    assert len(run["resource_snapshot"]["cases"]) == 1
    await PlanRunCoordinator(product.native.session_maker, product.native.events).run(
        UUID(run["plan_run_ids"][0])
    )
    rows = (await product.get(product.root + f"/runs/{run['id']}/scenarios"))["items"]
    assert len(rows) == 1 and rows[0]["observed_status"] == "passed"
    assert len(target.calls) == 1
    origin = await product.get(product.root + f"/runs/{before['id']}")
    assert origin["sealed_verdict"] == "failed" and origin["plan_run_ids"] == []
