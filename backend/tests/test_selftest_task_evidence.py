"""Deployment O reads only the native attempts owned by its currently claimed batch."""

import asyncio
import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
import respx
from httpx import Response
from test_selftest_product_api import ProductContext, _fixed
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.core.self_tests import get_self_test_settings
from app.main import app
from app.schemas.self_tests import PublishedAsset
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanCoordinator


def _scope(product: ProductContext, batch: dict, lease: dict) -> tuple[str, dict[str, str]]:
    path = product.agent + f"/runs/{batch['id']}/evidence"
    headers = {
        **product.machine("o"),
        "X-SelfTest-Lease-Token": lease["lease_token"],
        "X-SelfTest-Nonce": lease["nonce"],
    }
    return path, headers


async def _claim(product: ProductContext, batch: dict, nonce: str) -> dict:
    current = await product.get(product.root + f"/runs/{batch['id']}")
    return await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {"expected_revision": current["revision"], "nonce": nonce},
        machine="o",
    )


def _error(response: Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["trace_id"]


async def test_observer_claims_before_terminal_and_scope_reads_real_run_pages(
    product: ProductContext,
) -> None:
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    assert lease["task_kind"] == "observation"
    assert lease["batch"]["phase"] == "collecting"
    path, headers = _scope(product, batch, lease)
    response = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}",
        headers=headers,
        params={"page_size": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert response.json()["total"] == 2 and response.json()["has_more"] is True
    assert len(response.json()["items"]) == 1
    assert "snapshot" not in response.json()["items"][0]
    invalid = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}",
        headers=headers,
        params={"page_size": 101},
    )
    _error(invalid, 422, "VALIDATION_ERROR")


@respx.mock
async def test_claimed_scope_reads_native_attempt_and_denies_other_run_execution_or_project(
    product: ProductContext,
) -> None:
    respx.get("http://fixture.example/value").mock(return_value=Response(200, json={"actual": 1}))
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    await PlanCoordinator(product.native.session_maker, product.native.events).run(
        UUID(batch["plan_run_ids"][0])
    )
    path, headers = _scope(product, batch, lease)
    run = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers
    )
    assert run.status_code == 200, run.text
    execution = run.json()["items"][0]["execution_ids"][0]
    evidence = await product.native.client.get(
        path + f"/workflow-executions/{execution}", headers=headers
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["source_plan_run_item_id"] == run.json()["items"][0]["id"]
    assert not {"context", "snapshot", "output", "headers", "body"}.intersection(evidence.json())
    control = await product.native.client.get(
        path + f"/workflow-executions/{execution}/control-records",
        headers=headers,
        params={"node_id": "request", "page_size": 1},
    )
    assert control.status_code == 200 and control.json()["items"] == []

    asset = product.mapping.assets[0]
    other_plan = await product.post(
        f"/api/v1/projects/{product.project_id}/test-plans",
        {
            "name": "不属于此自测批次",
            "items": [
                {
                    "workflow_id": str(asset.workflow.id),
                    "environment_id": str(product.mapping.environment_id),
                }
            ],
        },
        status=201,
    )
    other_run = await product.post(
        f"/api/v1/projects/{product.project_id}/test-plans/{other_plan['id']}/runs", {}, status=202
    )
    await PlanCoordinator(product.native.session_maker, product.native.events).run(
        UUID(other_run["id"])
    )
    detail = await product.get(
        f"/api/v1/projects/{product.project_id}/test-plan-runs/{other_run['id']}"
    )
    other_execution = detail["items"][0]["workflow_execution_id"]
    for suffix in (
        f"/test-plan-runs/{other_run['id']}",
        f"/workflow-executions/{other_execution}",
        f"/workflow-executions/{other_execution}/control-records?node_id=request",
    ):
        _error(
            await product.native.client.get(path + suffix, headers=headers),
            404,
            "SELFTEST_EVIDENCE_NOT_IN_BATCH",
        )
    foreign = path.replace(str(product.project_id), str(uuid4()))
    _error(
        await product.native.client.get(
            foreign + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers
        ),
        404,
        "SELFTEST_BATCH_NOT_FOUND",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "wrong_nonce",
        "wrong_lease",
        "harness",
        "owner",
        "revoked_principal",
        "expired_lease",
        "cancelled",
    ],
)
async def test_task_scope_rejects_invalid_or_ended_authority(
    product: ProductContext, mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    path, headers = _scope(product, batch, lease)
    status, code = 403, "SELFTEST_LEASE_INVALID"
    if mutation == "missing":
        headers.pop("X-SelfTest-Lease-Token")
    elif mutation == "wrong_nonce":
        headers["X-SelfTest-Nonce"] = "wrong-nonce-" + "1" * 32
    elif mutation == "wrong_lease":
        headers["X-SelfTest-Lease-Token"] = "wrong-lease-" + "1" * 32
    elif mutation == "harness":
        headers.update(product.machine("h"))
        code = "SELFTEST_AGENT_FORBIDDEN"
    elif mutation == "owner":
        headers.update(product.headers)
        status, code = 401, "SELFTEST_AGENT_UNAUTHORIZED"
    elif mutation == "revoked_principal":
        config = product.config.model_copy(update={"principals": (product.config.principals[0],)})
        app.dependency_overrides[get_self_test_settings] = lambda: config
        status, code = 401, "SELFTEST_AGENT_UNAUTHORIZED"
    elif mutation == "expired_lease":
        # Advance the lease verifier's clock; no database entity/outcome fabrication.
        class LeaseClock:
            @staticmethod
            def now(tz=None):
                return datetime.now(UTC) + timedelta(seconds=product.config.lease_seconds + 1)

        monkeypatch.setattr("app.services.self_test_access.datetime", LeaseClock)
        status, code = 409, "SELFTEST_LEASE_EXPIRED"
    elif mutation == "cancelled":
        await product.post(product.root + f"/runs/{batch['id']}/cancel", {})
        status, code = 409, "SELFTEST_BATCH_FINISHED"
    response = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers
    )
    _error(response, status, code)


@pytest.mark.parametrize("mutation", ["expired_principal", "expired_batch", "disabled_binding"])
async def test_task_scope_rejects_ended_deployment_or_batch(
    product: ProductContext, mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    path, headers = _scope(product, batch, lease)
    status, code = 401, "SELFTEST_AGENT_UNAUTHORIZED"
    if mutation == "expired_principal":
        now = datetime.now(UTC)
        expired = jwt.encode(
            {
                "iss": "https://selftest.example",
                "sub": "o",
                "aud": "flowtest-selftest",
                "iat": now - timedelta(minutes=5),
                "nbf": now - timedelta(minutes=5),
                "exp": now - timedelta(seconds=1),
            },
            product.private_keys["o"],
            algorithm="RS256",
        )
        headers["Authorization"] = "Bearer " + expired
        status, code = 401, "SELFTEST_AGENT_UNAUTHORIZED"
    elif mutation == "expired_batch":

        class BatchClock:
            @staticmethod
            def now(tz=None):
                return datetime.now(UTC) + timedelta(seconds=601)

        monkeypatch.setattr("app.services.self_test_access.datetime", BatchClock)
        status, code = 409, "SELFTEST_BATCH_EXPIRED"
    elif mutation == "disabled_binding":
        binding = product.binding.model_copy(update={"enabled": False})
        config = product.config.model_copy(update={"bindings": (binding,)})
        app.dependency_overrides[get_self_test_settings] = lambda: config
        status, code = 403, "SELFTEST_BINDING_UNSAFE"
    response = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers
    )
    _error(response, status, code)


async def test_projectwide_ci_token_is_not_a_task_credential(product: ProductContext) -> None:
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    token = await product.post(
        f"/api/v1/projects/{product.project_id}/service-tokens",
        {"name": "既有项目范围只读", "scopes": ["read:execution"]},
        status=201,
    )

    headers = {"Authorization": "Bearer " + token["token"]}
    # Preserve existing native project-token semantics; do not relabel it task scoped.
    generic = f"/api/v1/ci/projects/{product.project_id}/test-plan-runs/{batch['plan_run_ids'][0]}"
    assert (await product.native.client.get(generic, headers=headers)).status_code == 200
    path, scoped = _scope(product, batch, lease)
    scoped.update(headers)
    _error(
        await product.native.client.get(
            path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=scoped
        ),
        401,
        "SELFTEST_AGENT_UNAUTHORIZED",
    )


async def test_observation_lease_is_not_valid_for_another_batch_or_mutation(
    product: ProductContext,
) -> None:
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    path, headers = _scope(product, batch, lease)
    other = await product.post(
        product.root + f"/installations/{batch['installation_id']}/runs",
        {},
        key="different-frozen-batch",
        status=202,
    )
    _error(
        await product.native.client.get(
            path.replace(batch["id"], other["id"]) + f"/test-plan-runs/{batch['plan_run_ids'][0]}",
            headers=headers,
        ),
        403,
        "SELFTEST_LEASE_INVALID",
    )
    _error(
        await product.native.client.post(
            path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers, json={}
        ),
        405,
        "METHOD_NOT_ALLOWED",
    )


async def test_observer_cannot_seal_nonterminal_native_runs_after_preterminal_claim(
    product: ProductContext,
) -> None:
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    authority = {"lease_token": lease["lease_token"], "nonce": lease["nonce"]}
    artifact = await product.post(
        product.agent + f"/runs/{batch['id']}/artifacts",
        {
            **authority,
            "kind": "verification",
            "filename": "nonterminal-contract-test.json",
            "content_base64": base64.b64encode(b'{"purpose":"reject-nonterminal"}').decode(),
        },
        machine="o",
        status=201,
    )
    receipt = {
        **authority,
        "manifest_digest": batch["manifest_digest"],
        "resource_digest": batch["resource_digest"],
        "policy_digest": batch["policy_digest"],
        "builds": batch["builds"],
        "batch_verdict": "blocked",
        "evidence_integrity": "missing",
        "batch_reason_codes": ["NOT_RUN"],
        "cleanup_status": "pending",
        "scenarios": [
            {
                "scenario_id": value["scenario_id"],
                "variant_key": value["variant_key"],
                "observed_status": None,
                "verification_status": "incomplete",
            }
            for value in batch["required_scenario_set"]
        ],
        "artifacts": [artifact],
    }
    response = await product.native.client.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        headers=product.machine("o"),
        json=receipt,
    )
    _error(response, 409, "SELFTEST_NATIVE_RUN_NOT_TERMINAL")
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert current["sealed_at"] is None and current["sealed_verdict"] is None


async def _dataset_asset(product: ProductContext) -> None:
    asset = product.mapping.assets[0]
    root = f"/api/v1/projects/{product.project_id}"
    uploaded = await product.native.client.post(
        root + "/files",
        headers=product.headers,
        files={"file": ("owned-rows.json", b'[{"row":0},{"row":1}]', "application/json")},
    )
    assert uploaded.status_code == 201, uploaded.text
    workflow_path = root + f"/workflows/{asset.workflow.id}"
    current = await product.get(workflow_path)
    definition = deepcopy(current["draft_definition"])
    definition["nodes"].insert(
        1,
        {
            "id": "dataset",
            "type": "dataset",
            "name": "实际数据行",
            "position": {"x": 50, "y": 0},
            "config": {"artifact_id": uploaded.json()["id"], "format": "json"},
        },
    )
    definition["edges"][0]["source"] = "dataset"
    definition["edges"].append({"id": "dataset-entry", "source": "start", "target": "dataset"})
    definition["run_policy"]["request_budget"] = 2
    changed = await product.native.client.patch(
        workflow_path,
        headers=product.headers,
        json={
            "expected_revision": current["draft_revision"],
            "definition": definition,
        },
    )
    assert changed.status_code == 200, changed.text
    workflow_version = await product.post(workflow_path + "/versions", {})
    case_path = root + f"/test-cases/{asset.case.id}"
    changed_case = await product.native.client.patch(
        case_path,
        headers=product.headers,
        json={
            "definition": {
                "workflow_id": str(asset.workflow.id),
                "workflow_version": 2,
                "environment_id": str(product.mapping.environment_id),
            },
        },
    )
    assert changed_case.status_code == 200, changed_case.text
    case_version = await product.post(case_path + "/versions", {})
    updated = asset.model_copy(
        update={
            "workflow": PublishedAsset(
                id=asset.workflow.id, version=2, fingerprint=workflow_version["fingerprint"]
            ),
            "case": PublishedAsset(
                id=asset.case.id, version=2, fingerprint=case_version["fingerprint"]
            ),
        }
    )
    product.mapping = product.mapping.model_copy(
        update={"assets": (updated, *product.mapping.assets[1:])}
    )


@respx.mock
async def test_task_scope_follows_real_dataset_children_but_rejects_unbound_parent_lineage(
    product: ProductContext,
) -> None:
    respx.get("http://fixture.example/value").mock(return_value=Response(200, json={"actual": 1}))
    await _dataset_asset(product)
    batch, nonce = await _fixed(product)
    lease = await _claim(product, batch, nonce)
    await PlanCoordinator(product.native.session_maker, product.native.events).run(
        UUID(batch["plan_run_ids"][0])
    )
    path, headers = _scope(product, batch, lease)
    run = await product.native.client.get(
        path + f"/test-plan-runs/{batch['plan_run_ids'][0]}", headers=headers
    )
    parent = run.json()["items"][0]["execution_id"]
    evidence = await product.native.client.get(
        path + f"/workflow-executions/{parent}", headers=headers
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["children_total"] == 2 and evidence.json()["children_complete"]
    for child in evidence.json()["children"]:
        response = await product.native.client.get(
            path + f"/workflow-executions/{child['execution_id']}", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["parent_execution_id"] == parent

    asset = product.mapping.assets[0]
    root = f"/api/v1/projects/{product.project_id}"
    started = await product.post(
        root + f"/workflows/{asset.workflow.id}/executions",
        {"environment_id": str(product.mapping.environment_id), "version": 2},
        status=202,
    )
    for _ in range(100):
        detail = await product.get(root + f"/workflow-executions/{started['id']}")
        if detail["execution"]["status"] in {"passed", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.02)
    assert len(detail["children"]) == 2
    for child in detail["children"]:
        _error(
            await product.native.client.get(
                path + f"/workflow-executions/{child['id']}", headers=headers
            ),
            404,
            "SELFTEST_EVIDENCE_NOT_IN_BATCH",
        )
