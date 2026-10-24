"""Public proposal/review/publication contract tests, not live generation evidence."""

import base64
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, Request
from sqlalchemy import select
from test_selftest_product_api import ProductContext, _ready
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.domain.self_tests import document_digest, request_upper_bound
from app.domain.test_engineering import fingerprint_contract
from app.engine.contracts import WorkflowDefinition
from app.main import app
from app.models.ai import AIChangeItem
from app.repositories.workflows import WorkflowRepository
from app.services.test_engineering import TestEngineeringService as EngineeringService

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.io import PublicAPI, object_value
from scripts.selftest.review_driver import HumanReviewDriver, PendingReview


@pytest.mark.asyncio
async def test_real_flowspec_public_detail_tracks_materialization_and_keeps_project_boundary(
    product: ProductContext,
) -> None:
    project = await product.get(f"/api/v1/projects/{product.project_id}")
    api = PublicAPI(
        "http://testserver",
        product.headers["Authorization"].removeprefix("Bearer "),
        project["organization_id"],
        transport=ASGITransport(app=app),
    )
    root = f"/projects/{product.project_id}"
    try:
        original = product.mapping.assets[0].workflow.id
        exported = await api.object("GET", root + f"/flow-specs/workflows/{original}/export")
        original_workflow = await api.object("GET", root + f"/workflows/{original}")
        node = next(
            value
            for value in original_workflow["draft_definition"]["nodes"]
            if value["type"] == "api"
        )
        spec = {**exported["spec"], "name": "只读物化身份公开契约"}
        mappings = {
            operation["ref"]: node["config"]["api_definition_id"]
            for operation in spec["operations"]
        }
        proposal = await api.object(
            "POST",
            root + "/flow-specs/imports",
            {
                "spec": spec,
                "operation_mappings": mappings,
                "operation_version_mappings": {key: 1 for key in mappings},
            },
        )
        path = root + f"/flow-specs/change-sets/{proposal['id']}"
        pending = await api.object("GET", path)
        assert pending["target_workflow_id"] is None
        assert pending["materialized_workflow_id"] is None
        reviewed = await api.object("POST", path + "/review", {"accept": True})
        assert reviewed["materialized_workflow_id"] is None
        applied = await api.object("POST", path + "/apply")
        version = await api.object(
            "POST", root + f"/workflows/{applied['workflow_id']}/versions", {}
        )
        detail = await api.object("GET", path)
        assert detail["target_workflow_id"] is None
        assert (
            detail["materialized_workflow_id"] == applied["workflow_id"] == version["workflow_id"]
        )
        assert detail["reviewed_by_id"] == reviewed["reviewed_by_id"]
        assert detail["reviewed_by_id"] is not None
        assert detail["applied_at"] is not None
        other = await api.object("POST", "/projects", {"name": "无关提案项目"})
        wrong_project = object_value(
            await api.request(
                "GET",
                f"/projects/{other['id']}/flow-specs/change-sets/{proposal['id']}",
                allow_status=(404,),
            )
        )
        assert wrong_project["error"]["code"] == "FLOWSPEC_CHANGE_SET_NOT_FOUND"
        assert wrong_project["error"]["trace_id"]
        controlled = object_value(
            await api.request(
                "GET", f"/mcp/write/change-sets/{proposal['id']}", allow_status=(404,)
            )
        )
        assert controlled["error"]["trace_id"]
        async with product.native.session_maker() as session:
            item = await session.scalar(
                select(AIChangeItem).where(AIChangeItem.change_set_id == UUID(proposal["id"]))
            )
            assert item is not None
            item.materialized_resource_type = "test_case"
            await session.commit()
        unrelated_type = await api.object("GET", path)
        assert unrelated_type["materialized_workflow_id"] is None
    finally:
        await api.close()


async def _workflow_proposal(context: ProductContext) -> tuple[dict, dict, dict]:
    root = f"/api/v1/projects/{context.project_id}"
    original = context.mapping.assets[0].workflow.id
    exported = await context.get(root + f"/flow-specs/workflows/{original}/export")
    spec = {**exported["spec"], "name": "本批提案审核与固定版本"}
    original_workflow = await context.get(root + f"/workflows/{original}")
    api = next(
        node for node in original_workflow["draft_definition"]["nodes"] if node["type"] == "api"
    )
    mappings = {
        operation["ref"]: api["config"]["api_definition_id"] for operation in spec["operations"]
    }
    proposal = await context.post(
        root + "/flow-specs/imports",
        {
            "spec": spec,
            "operation_mappings": mappings,
            "operation_version_mappings": {key: 1 for key in mappings},
        },
        status=201,
    )
    path = root + f"/flow-specs/change-sets/{proposal['id']}"
    await context.post(path + "/review", {"accept": True, "note": "真实审核"})
    applied = await context.post(path + "/apply", {})
    version = await context.post(root + f"/workflows/{applied['workflow_id']}/versions", {})
    visual = await context.get(path + "/visual-proposal")
    assert visual["proposal"]["review_status"] == "accepted"
    workflow = await context.get(root + f"/workflows/{applied['workflow_id']}")
    assert any(value is None for value in visual["proposed_definition"]["run_policy"].values())
    async with context.native.session_maker() as session:
        published = await WorkflowRepository(session).find_version(UUID(workflow["id"]), 1)
        assert published is not None
        assert not any(value is None for value in published.definition["run_policy"].values())
    return proposal, version, workflow


async def _case_proposal(context: ProductContext, workflow_id: str) -> tuple[dict, dict, dict]:
    root = f"/api/v1/projects/{context.project_id}"
    project = await context.get(root)
    account = await context.post(
        f"/api/v1/organizations/{project['organization_id']}/service-accounts",
        {
            "name": "独立提案账号",
            "account_key": "source-proposal-regression",
            "scopes": ["project:read", "project:write", "mcp:read", "mcp:write"],
        },
        status=201,
    )
    payload = {
        "project_id": str(context.project_id),
        "idempotency_key": "source-regression-case",
        "dry_run": False,
        "title": "本批真实 Case 提案",
        "confidence": 1,
        "risk_level": "high",
        "design": {
            "intent": {
                "key": "source.normalization",
                "objective": "核对实际审核发布图",
                "acceptance_criteria": ["断言实际值"],
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
                "name": "本批审核 Case",
                "definition": {
                    "workflow_id": workflow_id,
                    "workflow_version": 1,
                    "environment_id": str(context.mapping.environment_id),
                },
            }
        ],
    }
    response = await context.native.client.post(
        "/api/v1/mcp/write/change-sets",
        headers={"Authorization": "Bearer " + account["token"]},
        json=payload,
    )
    assert response.status_code == 202, response.text
    proposed = response.json()["data"]
    path = "/api/v1/mcp/write/change-sets/" + proposed["id"]
    approval = (await context.post(path + "/approve", {"note": "人工确认真实提案"}))["data"][
        "approval"
    ]["id"]
    for item in proposed["items"]:
        reviewed = await context.post(
            path + f"/items/{item['id']}/accept", {"approval_id": approval, "note": "审核接受"}
        )
    case_item = next(item for item in reviewed["data"]["items"] if item["item_type"] == "test_case")
    case_id = case_item["materialized_resource_id"]
    version = await context.post(
        root + f"/test-cases/{case_id}/versions", {"change_note": "固定审核结果"}
    )
    case = await context.get(root + f"/test-cases/{case_id}")
    return proposed, case_item, {**version, "id": case["id"]}


@pytest.mark.asyncio
async def test_human_driver_reads_actual_flow_and_case_receipts_without_any_write(
    product: ProductContext, tmp_path: Path
) -> None:
    proposal, version, workflow = await _workflow_proposal(product)
    case, case_item, case_version = await _case_proposal(product, workflow["id"])
    root = f"/api/v1/projects/{product.project_id}"
    visual = await product.get(root + f"/flow-specs/change-sets/{proposal['id']}/visual-proposal")
    definition = visual["proposed_definition"]
    api_ids = tuple(
        node["config"]["api_definition_id"] for node in definition["nodes"] if node["type"] == "api"
    )
    actual_case = next(item for item in case["items"] if item["item_type"] == "test_case")
    project = await product.get(root)
    api = PublicAPI(
        "http://testserver",
        product.headers["Authorization"].removeprefix("Bearer "),
        project["organization_id"],
        transport=ASGITransport(app=app),
    )
    requests: list[str] = []
    pending: list[PendingReview] = []

    async def readonly(request: Request) -> None:
        assert request.method == "GET"
        requests.append(request.url.path)

    async def on_pending(value: PendingReview) -> None:
        pending.append(value)

    api._client.event_hooks["request"].append(readonly)
    driver = HumanReviewDriver(datetime.now(UTC) + timedelta(seconds=30), on_pending)
    try:
        flow = await driver.flow(
            api,
            project_id=str(product.project_id),
            reviewer_id=visual["proposal"]["reviewed_by_id"],
            proposal_id=proposal["id"],
            expected_definition=object_value(definition),
            expected_api_ids=api_ids,
            output_dir=tmp_path / "flow",
        )
        reviewed_case = await driver.case(
            api,
            project_id=str(product.project_id),
            reviewer_id=case_item["reviewed_by_id"],
            proposal_id=case["id"],
            expected_definition=object_value(actual_case["proposed_content"]["definition"]),
            output_dir=tmp_path / "case",
        )
    finally:
        await api.close()
    assert flow.version["fingerprint"] == version["fingerprint"]
    assert str(flow.proposal.materialized_resource_id) == workflow["id"]
    assert flow.proposal.item_id is None
    assert reviewed_case.version["fingerprint"] == case_version["fingerprint"]
    assert str(reviewed_case.proposal.item_id) == case_item["id"]
    assert [item.route for item in pending] == ["flow_spec", "controlled_write"]
    assert any(path.endswith(f"/flow-specs/change-sets/{proposal['id']}") for path in requests)
    assert not any(path.endswith(f"/mcp/write/change-sets/{proposal['id']}") for path in requests)


async def _materialized(
    context: ProductContext, *, mode: str = "deterministic_mcp"
) -> tuple[dict, dict]:
    installed = await _ready(context, "mcp-core-v1")
    if mode == "host_llm_mcp":
        await context.post(
            context.agent + "/register",
            {
                "binding_id": str(context.binding.id),
                "binding_fingerprint": document_digest(context.binding),
                "environment_fingerprint": context.binding.environment_fingerprint,
                "builds": context.binding.builds.model_dump(),
                "capabilities": ["install", "host_llm_mcp"],
                "host_id": "synthetic-host",
            },
            machine="h",
        )
    batch = await context.post(
        context.root + f"/installations/{installed['id']}/generation-batches",
        {
            "scenario_ids": ["ST-MCP-026"],
            "verification_scope": "diagnostic_subset",
            "generation_mode": mode,
        },
        key="source-regression",
        status=202,
    )
    task = await context.post(
        context.agent + f"/runs/{batch['id']}/claim",
        {
            "expected_revision": batch["revision"],
            "nonce": "source-regression-" + "7" * 32,
        },
        machine="h",
    )
    proposal, version, workflow = await _workflow_proposal(context)
    case_proposal, case_item, case = await _case_proposal(context, workflow["id"])
    lease = {"lease_token": task["lease_token"], "nonce": task["nonce"]}
    artifact = await context.post(
        context.agent + f"/runs/{batch['id']}/artifacts",
        {
            **lease,
            "kind": "generation",
            "filename": "generation.json",
            "content_base64": base64.b64encode(b'{"scope":"contract_regression"}').decode(),
        },
        machine="h",
        status=201,
    )
    definition = workflow["draft_definition"]
    node = next(node for node in definition["nodes"] if node["type"] == "assert")
    api_node = next(node for node in definition["nodes"] if node["type"] == "api")
    api_id = api_node["config"]["api_definition_id"]
    async with context.native.session_maker() as session:
        contract = await EngineeringService(session).contract_for_api(
            project_id=context.project_id, definition_id=UUID(api_id), version_number=1
        )
    origins = [
        {
            "project_id": str(context.project_id),
            "api_definition_id": api_id,
            "api_version": 1,
            "contract_fingerprint": fingerprint_contract(contract),
        }
    ]
    oracles = [
        {
            "oracle_id": "actual",
            "node_id": node["id"],
            "phase": "main",
            "expression": node["config"]["expression"],
            "expected_value_digest": document_digest(node["config"]["expected"]),
            "assertion_name": "workflow_assertion",
        }
    ]
    source = {
        "scenario_id": "ST-MCP-026",
        "variant_key": "positive_assertion_canary",
        "workflow": {"id": workflow["id"], "version": 1, "fingerprint": version["fingerprint"]},
        "case": {"id": case["id"], "version": 1, "fingerprint": case["fingerprint"]},
        "design_fingerprint": "3" * 64,
        "compilation_fingerprint": "4" * 64,
        "oracle_mapping_digest": document_digest(oracles),
        "api_sources_digest": document_digest(origins),
        "api_sources": origins,
        "oracle_bindings": oracles,
        "protocol_receipts_digest": "5" * 64,
        "workflow_proposal": {
            "change_set_id": proposal["id"],
            "route": "flow_spec_visual",
            "content_fingerprint": proposal["source_fingerprint"],
            "review_status": "accepted",
            "materialized_resource_id": workflow["id"],
        },
        "case_proposal": {
            "change_set_id": case_proposal["id"],
            "item_id": case_item["id"],
            "route": "controlled_write",
            "content_fingerprint": case_proposal["source_fingerprint"],
            "review_status": "accepted",
            "materialized_resource_id": case["id"],
        },
        "generation_manifest": artifact,
    }
    return batch, {**lease, "sources": [source], "manifest": artifact}


@pytest.mark.asyncio
async def test_materialized_preserves_semantics_across_real_visual_and_published_defaults(
    product: ProductContext,
) -> None:
    batch, payload = await _materialized(product)
    result = await product.post(
        product.agent + f"/runs/{batch['id']}/materialized", payload, machine="h"
    )
    assert result["readiness"] == "ready" and result["phase"] == "ready"
    assert (
        result["resource_snapshot"]["cases"][0]["case"]["id"] == payload["sources"][0]["case"]["id"]
    )
    assert product.native.queue.test_plan_run_ids == []


@pytest.mark.asyncio
async def test_host_mode_requires_actual_registered_capability_not_deterministic_host(
    product: ProductContext,
) -> None:
    installed = await _ready(product, "mcp-core-v1")
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/generation-batches",
        {
            "generation_mode": "host_llm_mcp",
        },
        key="host-waiting",
        status=202,
    )
    assert batch["readiness"] == "needs_input" and batch["reason_codes"] == ["WAITING_FOR_HOST"]
    summary = await product.get(product.root + f"/runs/{batch['id']}/generation")
    assert summary["host_status"] == "not_registered"
    response = await product.native.client.get(
        product.agent + "/tasks", headers=product.machine("h")
    )
    assert response.status_code == 200
    assert batch["id"] not in {row["id"] for row in response.json()["batches"]}


@pytest.mark.asyncio
async def test_host_materialized_cannot_claim_model_without_host_evidence(
    product: ProductContext,
) -> None:
    batch, payload = await _materialized(product, mode="host_llm_mcp")
    error = await product.post(
        product.agent + f"/runs/{batch['id']}/materialized", payload, machine="h", status=409
    )
    assert error["error"]["code"] == "SELFTEST_HOST_EVIDENCE_MISSING"
    assert product.native.queue.test_plan_run_ids == []


@pytest.mark.asyncio
async def test_host_budget_cannot_be_self_authorized_by_source_digest(
    product: ProductContext,
) -> None:
    batch, payload = await _materialized(product, mode="host_llm_mcp")
    payload["sources"][0]["host_evidence"] = {
        "host": "synthetic-host",
        "model": "unapproved-model",
        "skill_digest": "1" * 64,
        "prompt_digest": "2" * 64,
        "authorized_budget_digest": "3" * 64,
        "actual_tool_calls": 3,
    }
    error = await product.post(
        product.agent + f"/runs/{batch['id']}/materialized", payload, machine="h", status=403
    )
    assert error["error"]["code"] == "SELFTEST_HOST_EVIDENCE_UNAUTHORIZED"


def test_plain_dag_request_upper_bound_counts_retries_and_rejects_control_fallback() -> None:
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {
                "id": "api",
                "type": "api",
                "name": "请求",
                "position": {"x": 100, "y": 0},
                "config": {
                    "api_definition_id": "00000000-0000-0000-0000-000000000001",
                    "max_retries": 3,
                },
            },
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "api"},
            {"id": "b", "source": "api", "target": "end"},
        ],
    }
    assert request_upper_bound(WorkflowDefinition.model_validate(definition)) == 4
    definition["nodes"][1].update(type="delay", config={"seconds": 1})
    assert request_upper_bound(WorkflowDefinition.model_validate(definition)) is None
    definition["run_policy"] = {"request_budget": 5, "cleanup_request_budget": 2}
    assert request_upper_bound(WorkflowDefinition.model_validate(definition)) == 7


@pytest.mark.asyncio
async def test_host_shared_batch_tool_count_is_not_multiplied_by_source_count(
    product: ProductContext,
) -> None:
    from app.models.self_tests import SelfTestBatch
    from app.schemas.self_tests import HostEvidence, MaterializedReceipt
    from app.services.self_test_agents import SelfTestAgentService

    batch, body = await _materialized(product, mode="host_llm_mcp")
    host = HostEvidence(
        host="synthetic-host",
        model="synthetic-model",
        skill_digest="1" * 64,
        prompt_digest="2" * 64,
        authorized_budget_digest="3" * 64,
        actual_tool_calls=40,
    )
    original = MaterializedReceipt.model_validate(body).sources[0]
    sources = tuple(
        original.model_copy(update={"scenario_id": f"BATCH-SOURCE-{index}", "host_evidence": host})
        for index in range(3)
    )
    payload = MaterializedReceipt.model_validate({**body, "sources": sources})
    principal = product.config.principals[0].model_copy(
        update={"authorized_host_budget_digests": ("3" * 64,)}
    )
    async with product.native.session_maker() as session:
        frozen = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert frozen is not None
        service = SelfTestAgentService(session, product.config)
        service._host_sources(principal, frozen, payload)
        assert product.native.queue.test_plan_run_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["model", "skill_digest", "prompt_digest", "actual_tool_calls"])
async def test_host_sources_cannot_disagree_about_the_shared_batch_call_trail(
    product: ProductContext,
    changed: str,
) -> None:
    from app.core.errors import AppError
    from app.models.self_tests import SelfTestBatch
    from app.schemas.self_tests import HostEvidence, MaterializedReceipt
    from app.services.self_test_agents import SelfTestAgentService

    batch, body = await _materialized(product, mode="host_llm_mcp")
    host = HostEvidence(
        host="synthetic-host",
        model="synthetic-model",
        skill_digest="1" * 64,
        prompt_digest="2" * 64,
        authorized_budget_digest="3" * 64,
        actual_tool_calls=3,
    )
    other = host.model_copy(update={changed: 4 if changed == "actual_tool_calls" else "4" * 64})
    original = MaterializedReceipt.model_validate(body).sources[0]
    sources = tuple(
        original.model_copy(update={"scenario_id": f"BATCH-SOURCE-{index}", "host_evidence": value})
        for index, value in enumerate((host, other))
    )
    payload = MaterializedReceipt.model_validate({**body, "sources": sources})
    principal = product.config.principals[0].model_copy(
        update={"authorized_host_budget_digests": ("3" * 64,)}
    )
    async with product.native.session_maker() as session:
        frozen = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert frozen is not None
        with pytest.raises(AppError) as rejected:
            SelfTestAgentService(session, product.config)._host_sources(principal, frozen, payload)
        assert rejected.value.code == "SELFTEST_HOST_EVIDENCE_INCONSISTENT"
