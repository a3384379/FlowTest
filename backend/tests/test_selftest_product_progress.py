"""Actual proposal reads and strict generation progress around human review transitions."""

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, MockTransport, Request, Response
from test_selftest_product_api import ProductContext, _ready
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.main import app
from app.schemas.self_tests import AgentTaskResponse, ProposalReference

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest import product_mcp
from scripts.selftest.io import HarnessError, PublicAPI
from scripts.selftest.review_driver import PendingReview


class StopAfterProgress(Exception):
    pass


async def _pending_flow(context: ProductContext) -> dict:
    root = f"/api/v1/projects/{context.project_id}"
    original = context.mapping.assets[0].workflow.id
    exported = await context.get(root + f"/flow-specs/workflows/{original}/export")
    workflow = await context.get(root + f"/workflows/{original}")
    node = next(item for item in workflow["draft_definition"]["nodes"] if item["type"] == "api")
    mappings = {
        item["ref"]: node["config"]["api_definition_id"] for item in exported["spec"]["operations"]
    }
    return await context.post(
        root + "/flow-specs/imports",
        {
            "spec": {**exported["spec"], "name": "审核进度状态刷新"},
            "operation_mappings": mappings,
            "operation_version_mappings": {key: 1 for key in mappings},
        },
        status=201,
    )


async def _pending_case(context: ProductContext, workflow: str) -> dict:
    project = await context.get(f"/api/v1/projects/{context.project_id}")
    account = await context.post(
        f"/api/v1/organizations/{project['organization_id']}/service-accounts",
        {
            "name": "审核进度测试",
            "account_key": "progress-proposal-regression",
            "scopes": ["project:read", "project:write", "mcp:read", "mcp:write"],
        },
        status=201,
    )
    response = await context.native.client.post(
        "/api/v1/mcp/write/change-sets",
        headers={
            "Authorization": "Bearer " + account["token"],
        },
        json={
            "project_id": str(context.project_id),
            "idempotency_key": "progress-case",
            "dry_run": False,
            "title": "下一条Case真实pending",
            "confidence": 1,
            "risk_level": "high",
            "design": {
                "intent": {
                    "key": "progress.review",
                    "objective": "审核进度刷新",
                    "acceptance_criteria": ["真实状态"],
                },
                "oracles": [
                    {
                        "id": "actual",
                        "kind": "json_path",
                        "confidence": 1,
                        "expression": "body.actual",
                        "expected": 1,
                    }
                ],
            },
            "test_cases": [
                {
                    "name": "下一条Case",
                    "definition": {
                        "workflow_id": workflow,
                        "workflow_version": 1,
                        "environment_id": str(context.mapping.environment_id),
                    },
                }
            ],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


async def test_next_pending_refreshes_first_workflow_after_real_human_apply(
    product: ProductContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = await _ready(product, "mcp-core-v1")
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/generation-batches",
        {
            "scenario_ids": ["ST-MCP-026"],
            "verification_scope": "diagnostic_subset",
            "generation_mode": "deterministic_mcp",
        },
        key="progress-review",
        status=202,
    )
    task = AgentTaskResponse.model_validate(
        await product.post(
            product.agent + f"/runs/{batch['id']}/claim",
            {
                "expected_revision": batch["revision"],
                "nonce": "progress-review-" + "7" * 32,
            },
            machine="h",
        )
    )
    flow = await _pending_flow(product)
    project = await product.get(f"/api/v1/projects/{product.project_id}")
    writer = PublicAPI(
        "http://testserver",
        product.headers["Authorization"].removeprefix("Bearer "),
        project["organization_id"],
        transport=ASGITransport(app=app),
    )
    machine = PublicAPI(
        "http://testserver",
        product.machine("h")["Authorization"].removeprefix("Bearer "),
        transport=ASGITransport(app=app),
    )

    class Client:
        receipts = ()

        async def call(self, *_args, **_kwargs):
            return {}

    @asynccontextmanager
    async def protocol(*_args, **_kwargs):
        yield Client()

    async def generation(_client, _writer, *, review_driver, **_kwargs):
        await review_driver.on_pending(
            PendingReview(
                project_id=product.project_id,
                proposal_id=UUID(flow["id"]),
                route="flow_spec",
                content_fingerprint=flow["source_fingerprint"],
            )
        )
        path = f"/api/v1/projects/{product.project_id}/flow-specs/change-sets/{flow['id']}"
        await product.post(path + "/review", {"accept": True})
        applied = await product.post(path + "/apply", {})
        await product.post(
            f"/api/v1/projects/{product.project_id}/workflows/{applied['workflow_id']}/versions", {}
        )
        case = await _pending_case(product, applied["workflow_id"])
        item = next(value for value in case["items"] if value["item_type"] == "test_case")
        await review_driver.on_pending(
            PendingReview(
                project_id=product.project_id,
                proposal_id=UUID(case["id"]),
                item_id=UUID(item["id"]),
                route="controlled_write",
                content_fingerprint=case["source_fingerprint"],
            )
        )
        latest = await product.get(product.root + f"/runs/{batch['id']}/generation")
        refs = latest["proposals"]
        assert refs[0]["review_status"] == "accepted"
        assert refs[0]["materialized_resource_id"] == applied["workflow_id"]
        assert refs[1]["review_status"] == "pending" and refs[1]["item_id"] == item["id"]
        case_path = "/api/v1/mcp/write/change-sets/" + case["id"]
        approval = (await product.post(case_path + "/approve", {}))["data"]["approval"]["id"]
        for pending_item in case["items"]:
            accepted = await product.post(
                case_path + f"/items/{pending_item['id']}/accept", {"approval_id": approval}
            )
        accepted_case = next(
            value for value in accepted["data"]["items"] if value["item_type"] == "test_case"
        )
        await product.post(
            f"/api/v1/projects/{product.project_id}/test-cases/{accepted_case['materialized_resource_id']}/versions",
            {},
        )
        following = await _pending_flow(product)
        await review_driver.on_pending(
            PendingReview(
                project_id=product.project_id,
                proposal_id=UUID(following["id"]),
                route="flow_spec",
                content_fingerprint=following["source_fingerprint"],
            )
        )
        latest = await product.get(product.root + f"/runs/{batch['id']}/generation")
        assert latest["proposals"][1]["review_status"] == "accepted"
        assert (
            latest["proposals"][1]["materialized_resource_id"]
            == accepted_case["materialized_resource_id"]
        )
        raise StopAfterProgress

    monkeypatch.setattr(product_mcp, "_protocol", protocol)
    monkeypatch.setattr(
        product_mcp, "_pack_digest", lambda: task.frozen_manifest.template.pack_digest
    )
    monkeypatch.setattr(product_mcp, "generate_canary", generation)
    try:
        with pytest.raises(StopAfterProgress):
            await product_mcp.generate_task(
                machine,
                writer,
                writer,
                task=task,
                stack=None,
                boot=SimpleNamespace(
                    credentials=SimpleNamespace(mcp_token="synthetic-only"), installation=None
                ),
                directory=tmp_path,
                review_mode="human",
            )
    finally:
        await writer.close()
        await machine.close()


def _flow_document(project, identifier):
    return {
        "id": str(identifier),
        "project_id": str(project),
        "source_fingerprint": "a" * 64,
        "source_type": "flow_spec",
        "source_ref": "mcp://selftest/batch/scenario",
        "spec": {"name": "frozen"},
        "target_workflow_id": None,
        "target_revision": None,
        "target_snapshot_sha256": None,
        "proposal_origin": "mcp",
        "review_status": "pending",
        "materialized_workflow_id": None,
    }


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("project_id", str(uuid4())),
        ("id", str(uuid4())),
        ("source_fingerprint", "b" * 64),
        ("source_type", "other"),
        ("source_ref", "mcp://other"),
        ("spec", {"name": "changed"}),
        ("target_revision", 99),
        ("review_status", "rejected"),
    ],
)
async def test_refresh_rejects_changed_or_rejected_flow_without_writing(field, replacement):
    project, identifier = uuid4(), uuid4()
    document = _flow_document(project, identifier)

    def respond(request):
        assert request.method == "GET"
        assert "/flow-specs/change-sets/" in request.url.path
        return Response(200, json=document)

    api = PublicAPI("http://test", transport=MockTransport(respond))
    pending = product_mcp._PendingReference(
        reference=ProposalReference(
            change_set_id=identifier,
            route="flow_spec_visual",
            content_fingerprint="a" * 64,
            review_status="pending",
        )
    )
    try:
        frozen = await product_mcp._refresh_proposal(api, project, pending)
        document[field] = replacement
        reason = (
            "HUMAN_REVIEW_REJECTED" if field == "review_status" else "HUMAN_REVIEW_SOURCE_CHANGED"
        )
        with pytest.raises(HarnessError, match=reason):
            await product_mcp._refresh_proposal(api, project, frozen)
    finally:
        await api.close()


@pytest.mark.parametrize("always_conflict", [False, True])
async def test_accept_race_refreshes_only_exact_status_conflicts_and_is_bounded(always_conflict):
    project, identifier, resource = uuid4(), uuid4(), uuid4()
    document = _flow_document(project, identifier)
    reads, posts = [], []

    def respond(request: Request):
        if request.method == "GET":
            reads.append(request.url.path)
            return Response(200, json=document)
        payload = __import__("json").loads(request.content)
        posts.append(payload["proposals"][0])
        if len(posts) == 1 or always_conflict:
            document.update(review_status="accepted", materialized_workflow_id=str(resource))
            return Response(
                409,
                json={
                    "error": {
                        "code": "SELFTEST_PROPOSAL_REVIEW_MISMATCH",
                        "trace_id": "synthetic-race",
                    }
                },
            )
        return Response(200, json={})

    api = PublicAPI("http://test", transport=MockTransport(respond))
    task = AgentTaskResponse.model_construct(
        project_id=project,
        task_id=uuid4(),
        lease_token="l" * 48,
        nonce="n" * 64,
        batch=SimpleNamespace(deadline=datetime.now(UTC) + timedelta(seconds=30)),
    )
    proposals = [
        product_mcp._PendingReference(
            reference=ProposalReference(
                change_set_id=identifier,
                route="flow_spec_visual",
                content_fingerprint="a" * 64,
                review_status="pending",
            )
        )
    ]
    try:
        if always_conflict:
            with pytest.raises(HarnessError, match="SELFTEST_PROPOSAL_REVIEW_MISMATCH"):
                await product_mcp._current_progress(api, api, task, proposals, 2)
        else:
            await product_mcp._current_progress(api, api, task, proposals, 2)
    finally:
        await api.close()
    assert len(reads) == len(posts) == (3 if always_conflict else 2)
    assert posts[0]["review_status"] == "pending" and posts[1]["review_status"] == "accepted"
    assert posts[1]["materialized_resource_id"] == str(resource)
