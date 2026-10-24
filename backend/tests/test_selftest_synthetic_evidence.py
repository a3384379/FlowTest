"""Real native requests retain two declared names without granting full report access."""

import base64
from dataclasses import replace
from itertools import pairwise
from uuid import UUID, uuid4

import pytest
import respx
from httpx import ASGITransport, Response
from test_selftest_product_api import ProductContext, _ready
from test_selftest_product_api import product as product
from test_selftest_product_sources import _case_proposal
from test_selftest_task_evidence import _claim, _error, _scope
from test_tasking_api import tasking_context as tasking_context

from app.domain.self_tests import document_digest
from app.domain.test_engineering import fingerprint_contract
from app.main import app
from app.schemas.self_tests import AgentTaskResponse
from app.services.test_engineering import TestEngineeringService as Engineering
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanCoordinator


def _node(identity: str, kind: str, config: dict | None = None) -> dict:
    return {
        "id": identity,
        "type": kind,
        "name": identity,
        "position": {"x": 0, "y": 0},
        "config": config or {},
    }


async def _generation(product: ProductContext) -> tuple[dict, dict]:
    installed = await _ready(product, "mcp-core-v1")
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/generation-batches",
        {"scenario_ids": ["ST-MCP-023"], "verification_scope": "diagnostic_subset"},
        key="synthetic-capture",
        status=202,
    )
    task = await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {"expected_revision": batch["revision"], "nonce": "capture-nonce-" + "c" * 32},
        machine="h",
    )
    return batch, {"lease_token": task["lease_token"], "nonce": task["nonce"]}


async def _definitions(
    product: ProductContext, batch: dict, *, declared: bool = True
) -> tuple[dict, list[dict]]:
    root = f"/api/v1/projects/{product.project_id}"
    target = f"/api/v1/projects/{product.binding.target_project_id}/environments"
    apis, origins = {}, []
    for purpose, method, path in (
        ("create", "POST", target),
        ("patch", "PATCH", target + "/{{environment_id}}"),
    ):
        api = await product.post(
            root + "/apis",
            {
                "name": purpose,
                "request": {
                    "method": method,
                    "path": path,
                    "body_kind": "json",
                    "body": {"name": "unselected-api-default"},
                },
            },
            status=201,
        )
        identity = api["definition"]["id"]
        apis[(method, path)] = identity
        async with product.native.session_maker() as session:
            contract = await Engineering(session).contract_for_api(
                project_id=product.project_id, definition_id=UUID(identity), version_number=1
            )
        origins.append(
            {
                "project_id": str(product.project_id),
                "api_definition_id": identity,
                "api_version": 1,
                "contract_fingerprint": fingerprint_contract(contract),
            }
        )
    configs = [
        {
            "api_definition_id": origin["api_definition_id"],
            "api_version": 1,
            "request_overrides": {
                "body": {"kind": "json", "value": {"name": batch["batch_key"] + suffix}}
            },
        }
        for origin, suffix in zip(origins, ("-created", "-updated"), strict=True)
    ]
    if not declared:
        configs[0]["request_overrides"]["body"]["value"]["name"] = "not-a-declared-synthetic-name"
    ids = ["start", "create", "extract", "patch", "assert", "end"]
    edges = [
        {"id": f"edge-{index}", "source": source, "target": target}
        for index, (source, target) in enumerate(pairwise(ids))
    ]
    edges[2]["mappings"] = [
        {
            "source": {"node_id": "extract", "path": "value"},
            "target": {"node_id": "patch", "location": "variable", "key": "environment_id"},
        }
    ]
    definition = {
        "run_policy": {"request_budget": 2},
        "nodes": [
            _node("start", "start"),
            _node("create", "api", configs[0]),
            _node(
                "extract",
                "extract",
                {"source_node_id": "create", "expression": "body.id", "variable": "environment_id"},
            ),
            _node("patch", "api", configs[1]),
            _node(
                "assert",
                "assert",
                {"source_node_id": "patch", "expression": "body.actual", "expected": 1},
            ),
            _node("end", "end"),
        ],
        "edges": edges,
    }
    original = await product.post(
        root + "/workflows", {"name": "已声明合成字段流程源", "definition": definition}, status=201
    )
    exported = await product.get(root + f"/flow-specs/workflows/{original['id']}/export")
    mappings = {
        operation["ref"]: apis[(operation["method"], operation["path"])]
        for operation in exported["spec"]["operations"]
    }
    proposal = await product.post(
        root + "/flow-specs/imports",
        {
            "spec": {**exported["spec"], "name": "字段投影审核结果"},
            "operation_mappings": mappings,
            "operation_version_mappings": {key: 1 for key in mappings},
        },
        status=201,
    )
    path = root + f"/flow-specs/change-sets/{proposal['id']}"
    await product.post(path + "/review", {"accept": True})
    applied = await product.post(path + "/apply", {})
    version = await product.post(root + f"/workflows/{applied['workflow_id']}/versions", {})
    return {
        "proposal": proposal,
        "version": version,
        "workflow_id": applied["workflow_id"],
    }, origins


async def _materialized(product: ProductContext, *, declared: bool = True) -> tuple[dict, str]:
    batch, lease = await _generation(product)
    flow, origins = await _definitions(product, batch, declared=declared)
    target_context = replace(
        product,
        mapping=product.mapping.model_copy(
            update={
                "environment_id": product.mapping.target_environment_id,
            }
        ),
    )
    proposal, item, case = await _case_proposal(target_context, flow["workflow_id"])
    artifact = await product.post(
        product.agent + f"/runs/{batch['id']}/artifacts",
        {
            **lease,
            "kind": "generation",
            "filename": "synthetic-capture.json",
            "content_base64": base64.b64encode(
                b'{"purpose":"synthetic-capture-contract-test"}'
            ).decode(),
        },
        machine="h",
        status=201,
    )
    oracle = {
        "oracle_id": "actual",
        "node_id": "assert",
        "phase": "main",
        "expression": "body.actual",
        "expected_value_digest": document_digest(1),
        "assertion_name": "workflow_assertion",
    }
    source = {
        "scenario_id": "ST-MCP-023",
        "variant_key": "environment_lifecycle",
        "workflow": {
            "id": flow["workflow_id"],
            "version": 1,
            "fingerprint": flow["version"]["fingerprint"],
        },
        "case": {"id": case["id"], "version": 1, "fingerprint": case["fingerprint"]},
        "design_fingerprint": "3" * 64,
        "compilation_fingerprint": "4" * 64,
        "oracle_mapping_digest": document_digest([oracle]),
        "api_sources_digest": document_digest(origins),
        "api_sources": origins,
        "oracle_bindings": [oracle],
        "protocol_receipts_digest": "5" * 64,
        "workflow_proposal": {
            "change_set_id": flow["proposal"]["id"],
            "route": "flow_spec_visual",
            "content_fingerprint": flow["proposal"]["source_fingerprint"],
            "review_status": "accepted",
            "materialized_resource_id": flow["workflow_id"],
        },
        "case_proposal": {
            "change_set_id": proposal["id"],
            "item_id": item["id"],
            "route": "controlled_write",
            "content_fingerprint": proposal["source_fingerprint"],
            "review_status": "accepted",
            "materialized_resource_id": case["id"],
        },
        "generation_manifest": artifact,
    }
    ready = await product.post(
        product.agent + f"/runs/{batch['id']}/materialized",
        {**lease, "sources": [source], "manifest": artifact},
        machine="h",
    )
    running = await product.post(
        product.root + f"/runs/{batch['id']}/execute-materialized",
        {
            "resource_digest": ready["resource_digest"],
            "environment_fingerprint": ready["environment_fingerprint"],
            "confirmed": True,
        },
        key="execute-synthetic-capture",
        status=202,
    )
    return running, lease["nonce"]


@respx.mock
async def test_public_synthetic_capture_exports_only_declared_names_and_native_identity(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, nonce = await _materialized(product)
    identity = str(uuid4())
    base = f"http://target.example/api/v1/projects/{product.binding.target_project_id}/environments"
    secret = "synthetic-extra-body-and-login-secret"
    respx.post(base).mock(
        return_value=Response(
            201, json={"id": identity, "name": batch["batch_key"] + "-created", "password": secret}
        )
    )
    respx.patch(base + "/" + identity).mock(
        return_value=Response(
            200,
            json={"actual": 1, "name": batch["batch_key"] + "-updated", "token": secret},
            headers={"Set-Cookie": secret},
        )
    )
    task = await _claim(product, batch, nonce)
    await PlanCoordinator(product.native.session_maker, product.native.events).run(
        UUID(batch["plan_run_ids"][0])
    )
    path, headers = _scope(product, batch, task)
    run = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers
    )
    assert run.status_code == 200, run.text
    execution = run.json()["items"][0]["execution_id"]

    async def forbid_full_report(*args, **kwargs):
        raise AssertionError("O must not construct or return a full execution report")

    monkeypatch.setattr("app.services.workflows.WorkflowService.get_execution", forbid_full_report)
    monkeypatch.setattr(
        "app.services.workflows.WorkflowService.get_execution_report", forbid_full_report
    )
    response = await product.native.client.get(
        path + f"/workflow-executions/{execution}/synthetic-names", headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["execution_id"] == execution and data["batch_id"] == batch["id"]
    assert data["status"] == "passed"
    assert [(field["purpose"], field["field"], field["actual"]) for field in data["fields"]] == [
        ("create", "body.name", batch["batch_key"] + "-created"),
        ("patch", "body.name", batch["batch_key"] + "-updated"),
    ]
    assert secret not in response.text
    assert not {"snapshot", "context", "output", "headers", "body", "login"}.intersection(data)
    other = await product.native.client.get(
        path + f"/workflow-executions/{uuid4()}/synthetic-names", headers=headers
    )
    _error(other, 404, "SELFTEST_EVIDENCE_NOT_IN_BATCH")

    from scripts.selftest.product_evidence import TaskEvidenceReader

    reader = TaskEvidenceReader(
        "http://test",
        product.machine("o")["Authorization"].removeprefix("Bearer "),
        AgentTaskResponse.model_validate(task),
        transport=ASGITransport(app=app),
    )
    try:
        bounded = await reader.object(
            "GET",
            f"/ci/projects/{product.project_id}/workflow-executions/{execution}/evidence/synthetic-names",
        )
    finally:
        await reader.close()
    assert bounded["fields"] == data["fields"]
    assert bounded["snapshot_digest"] == data["snapshot_digest"]


@respx.mock
async def test_published_owner_selected_name_is_not_a_declared_synthetic_capture(
    product: ProductContext,
) -> None:
    batch, nonce = await _materialized(product, declared=False)
    identity = str(uuid4())
    base = f"http://target.example/api/v1/projects/{product.binding.target_project_id}/environments"
    respx.post(base).mock(
        return_value=Response(201, json={"id": identity, "name": "not-exported-private-value"})
    )
    respx.patch(base + "/" + identity).mock(
        return_value=Response(200, json={"actual": 1, "name": "not-exported-private-value"})
    )
    task = await _claim(product, batch, nonce)
    await PlanCoordinator(product.native.session_maker, product.native.events).run(
        UUID(batch["plan_run_ids"][0])
    )
    path, headers = _scope(product, batch, task)
    run = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers
    )
    execution = run.json()["items"][0]["execution_id"]
    response = await product.native.client.get(
        path + f"/workflow-executions/{execution}/synthetic-names", headers=headers
    )
    _error(response, 404, "SELFTEST_SYNTHETIC_CAPTURE_NOT_DECLARED")
    assert "not-exported-private-value" not in response.text
