import asyncio
import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import Response
from sqlalchemy import select
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.core.self_tests import (
    SelfTestBinding,
    SelfTestPrincipal,
    SelfTestSettings,
    get_self_test_settings,
)
from app.domain.self_tests import document_digest
from app.main import app
from app.models.self_tests import SelfTestBatch, SelfTestInstallation
from app.models.tasking import TestPlanRun as PlanRun
from app.schemas.self_tests import (
    BuildIdentity,
    ExpectedResult,
    InstallationMapping,
    PublishedAsset,
    ScenarioAssets,
    TemplateResponse,
    TemplateScenario,
)
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator


@dataclass(repr=False)
class ProductContext:
    native: TaskingTestContext
    headers: dict[str, str]
    project_id: UUID
    config: SelfTestSettings
    binding: SelfTestBinding
    mapping: InstallationMapping
    private_keys: dict[str, bytes]

    @property
    def root(self) -> str:
        return f"/api/v1/projects/{self.project_id}/self-tests"

    @property
    def agent(self) -> str:
        return f"/api/v1/agent/projects/{self.project_id}/self-tests"

    def machine(self, identifier: str) -> dict[str, str]:
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "iss": "https://selftest.example",
                "sub": identifier,
                "aud": "flowtest-selftest",
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(minutes=10),
            },
            self.private_keys[identifier],
            algorithm="RS256",
        )
        return {"Authorization": f"Bearer {token}"}

    async def post(
        self,
        path: str,
        payload: dict,
        *,
        machine: str | None = None,
        key: str | None = None,
        status: int = 200,
    ) -> dict:
        headers = self.headers if machine is None else self.machine(machine)
        if key is not None:
            headers = {**headers, "Idempotency-Key": key}
        response = await self.native.client.post(path, headers=headers, json=payload)
        assert response.status_code == status, response.text
        return response.json()

    async def get(self, path: str) -> dict:
        response = await self.native.client.get(path, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()


def _keys() -> tuple[bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )


@pytest.fixture
async def product(tasking_context: TaskingTestContext) -> ProductContext:
    headers = await _login_headers(tasking_context.client)
    response = await tasking_context.client.post(
        "/api/v1/projects", headers=headers, json={"name": "自测产品隔离项目"}
    )
    assert response.status_code == 201, response.text
    project_id = UUID(response.json()["id"])
    root = f"/api/v1/projects/{project_id}"
    environments, services = [], []
    for name in ("fixture", "target"):
        response = await tasking_context.client.post(
            root + "/environments",
            headers=headers,
            json={"name": name, "base_url": f"http://{name}.example", "classification": "test"},
        )
        assert response.status_code == 201, response.text
        environments.append(UUID(response.json()["id"]))
        response = await tasking_context.client.post(
            root + "/services", headers=headers, json={"name": name, "service_key": name}
        )
        assert response.status_code == 201, response.text
        services.append(UUID(response.json()["id"]))
    binding = SelfTestBinding(
        id=uuid4(),
        name="部署绑定",
        allowed_project_ids=(project_id,),
        runner_instance_id="candidate-a",
        target_instance_id="candidate-b",
        target_display="隔离 B",
        fixture_display="隔离 Mock",
        target_base_url="http://target.example",
        fixture_base_url="http://fixture.example",
        target_project_id=uuid4(),
        target_organization_id=uuid4(),
        target_user_id=uuid4(),
        builds=BuildIdentity(
            runner="runner-sha", target="target-sha", fixture="fixture-sha", verifier="observer-sha"
        ),
        environment_fingerprint="1" * 64,
        isolation_fingerprint="2" * 64,
        non_production=True,
        isolated=True,
        outbound_authorized=True,
        agent_id="h",
        observer_id="o",
    )
    principals, private_keys = [], {}
    for identifier, capabilities in (
        ("h", ("install", "deterministic_mcp", "host_llm_mcp", "observe")),
        ("o", ("verify",)),
    ):
        private, public = _keys()
        private_keys[identifier] = private
        principals.append(
            SelfTestPrincipal(
                id=identifier,
                issuer="https://selftest.example",
                subject=identifier,
                audience="flowtest-selftest",
                public_key=public,
                allowed_project_ids=(project_id,),
                allowed_binding_ids=(binding.id,),
                capabilities=capabilities,
            )
        )
    template = TemplateResponse(
        id="product-test-v1",
        title="公开 API 测试包",
        batch_kind="fixed_baseline",
        pack_digest="f" * 64,
        task_set_digest="e" * 64,
        scenarios=tuple(
            TemplateScenario(
                scenario_id=f"ST-PRODUCT-{name}",
                title=name,
                category="engine",
                expected=ExpectedResult(
                    status="passed" if name == "PASS" else "failed",
                    error_code=None if name == "PASS" else "WORKFLOW_ASSERTION_FAILED",
                    phase=None if name == "PASS" else "main",
                ),
            )
            for name in ("PASS", "FAIL")
        ),
    )
    config = SelfTestSettings(
        bindings=(binding,), principals=tuple(principals), extra_templates=(template,)
    )
    app.dependency_overrides[get_self_test_settings] = lambda: config
    context = ProductContext(
        tasking_context,
        headers,
        project_id,
        config,
        binding,
        InstallationMapping(
            environment_id=environments[0],
            target_environment_id=environments[1],
            fixture_service_id=services[0],
            target_service_id=services[1],
            target_project_id=binding.target_project_id,
            target_organization_id=binding.target_organization_id,
            target_user_id=binding.target_user_id,
            target_instance_id=binding.target_instance_id,
            target_build_digest=binding.builds.target,
        ),
        private_keys,
    )
    assets = tuple([await _asset(context, scenario) for scenario in template.scenarios])
    context.mapping = context.mapping.model_copy(update={"assets": assets})
    return context


async def _asset(context: ProductContext, scenario: TemplateScenario) -> ScenarioAssets:
    root = f"/api/v1/projects/{context.project_id}"
    api = await context.post(
        root + "/apis",
        {
            "name": scenario.title,
            "request": {"method": "GET", "path": "/value", "body_kind": "none"},
        },
        status=201,
    )
    nodes = [
        {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
        {
            "id": "request",
            "type": "api",
            "name": "请求",
            "position": {"x": 100, "y": 0},
            "config": {"api_definition_id": api["definition"]["id"], "api_version": 1},
        },
        {
            "id": "assert",
            "type": "assert",
            "name": "断言",
            "position": {"x": 200, "y": 0},
            "config": {
                "source_node_id": "request",
                "expression": "body.actual",
                "expected": 1 if scenario.expected.status == "passed" else 2,
                "operator": "equals",
            },
        },
        {"id": "end", "type": "end", "name": "结束", "position": {"x": 300, "y": 0}},
    ]
    definition = {
        "run_policy": {"request_budget": 1},
        "nodes": nodes,
        "edges": [
            {"id": str(index), "source": source, "target": target}
            for index, (source, target) in enumerate(
                zip(("start", "request", "assert"), ("request", "assert", "end"), strict=True)
            )
        ],
    }
    workflow = await context.post(
        root + "/workflows", {"name": scenario.scenario_id, "definition": definition}, status=201
    )
    version = await context.post(root + f"/workflows/{workflow['id']}/versions", {})
    case = await context.post(
        root + "/test-cases",
        {
            "name": scenario.scenario_id,
            "definition": {
                "workflow_id": workflow["id"],
                "workflow_version": 1,
                "environment_id": str(context.mapping.environment_id),
            },
        },
        status=201,
    )
    case_version = await context.post(
        root + f"/test-cases/{case['id']}/versions", {"change_note": "测试冻结"}
    )
    return ScenarioAssets(
        scenario_id=scenario.scenario_id,
        workflow=PublishedAsset(
            id=UUID(workflow["id"]), version=1, fingerprint=version["fingerprint"]
        ),
        case=PublishedAsset(
            id=UUID(case["id"]), version=1, fingerprint=case_version["fingerprint"]
        ),
    )


async def _install(context: ProductContext, template: str = "product-test-v1") -> dict:
    request = {"template_id": template, "binding_id": str(context.binding.id)}
    preview = await context.post(context.root + "/installations/preview", request)
    assert preview["can_apply"]
    return await context.post(
        context.root + "/installations",
        {
            **request,
            "preview_fingerprint": preview["fingerprint"],
            "preview_expires_at": preview["expires_at"],
        },
        key=f"installation:{template}",
        status=202,
    )


async def _ready(context: ProductContext, template: str = "product-test-v1") -> dict:
    installed, lease = await _claimed_installation(context, template)
    mapping = (
        context.mapping.model_copy(update={"assets": ()})
        if template == "mcp-core-v1"
        else context.mapping
    )
    return await context.post(
        context.agent + f"/installations/{installed['id']}/receipt",
        {
            "lease_token": lease["lease_token"],
            "nonce": lease["nonce"],
            "environment_fingerprint": context.binding.environment_fingerprint,
            "mapping": mapping.model_dump(mode="json"),
        },
        machine="h",
    )


async def test_fixture_instance_cannot_start_selftest_recursively_even_with_valid_binding_and_actor(
    product: ProductContext,
) -> None:
    installed = await _ready(product)
    depth_one = product.config.model_copy(update={"fixture_run_depth": 1})
    app.dependency_overrides[get_self_test_settings] = lambda: depth_one
    catalog = await product.get(product.root + "/bindings")
    binding = catalog["items"][0]
    assert binding["readiness"] == "blocked"
    assert not any(
        binding["actions"][name] for name in ("can_initialize", "can_generate", "can_execute")
    )
    request = {"template_id": "product-test-v1", "binding_id": str(product.binding.id)}
    preview = await product.post(product.root + "/installations/preview", request)
    assert preview["can_apply"] is False
    assert "SELFTEST_RECURSION_LIMIT_REACHED" in preview["conflicts"]
    response = await product.native.client.post(
        product.root + f"/installations/{installed['id']}/runs",
        headers={**product.headers, "Idempotency-Key": "forbidden-nested-selftest"},
        json={},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELFTEST_RECURSION_LIMIT_REACHED"
    assert response.json()["error"]["trace_id"]
    result = await product.get(product.root + f"/installations/{installed['id']}/runs")
    assert result["total"] == 0 and result["items"] == []


async def _claimed_installation(
    context: ProductContext, template: str = "product-test-v1"
) -> tuple[dict, dict]:
    installed = await _install(context, template)
    await context.post(
        context.agent + "/register",
        {
            "binding_id": str(context.binding.id),
            "binding_fingerprint": document_digest(context.binding),
            "environment_fingerprint": context.binding.environment_fingerprint,
            "builds": context.binding.builds.model_dump(),
            "capabilities": ["install", "deterministic_mcp"],
            "host_id": "synthetic-host",
        },
        machine="h",
    )
    current = await context.get(context.root + f"/installations/{installed['id']}")
    lease = await context.post(
        context.agent + f"/installations/{installed['id']}/claim",
        {
            "expected_revision": current["revision"],
            "nonce": "installation-nonce-" + "1" * 32,
        },
        machine="h",
    )
    return installed, lease


@pytest.mark.asyncio
async def test_public_installation_lease_and_renewal_keep_utc_timezone(
    product: ProductContext,
) -> None:
    installed, lease = await _claimed_installation(product)
    expiry = datetime.fromisoformat(lease["lease_expires_at"])
    assert expiry.tzinfo is not None
    assert (expiry - datetime.now(UTC)).total_seconds() > 0
    renewed = await product.post(
        product.agent + f"/installations/{installed['id']}/lease",
        {"lease_token": lease["lease_token"], "nonce": lease["nonce"]},
        machine="h",
    )
    assert datetime.fromisoformat(renewed["lease_expires_at"]).tzinfo is not None


async def _fixed(context: ProductContext) -> tuple[dict, str]:
    installed = await _ready(context)
    batch = await context.post(
        context.root + f"/installations/{installed['id']}/runs", {}, key="fixed-run", status=202
    )
    nonce = "batch-nonce-" + "2" * 32
    lease = await context.post(
        context.agent + f"/runs/{batch['id']}/claim",
        {
            "expected_revision": batch["revision"],
            "nonce": nonce,
        },
        machine="h",
    )
    assert lease["task_kind"] == "preparation"
    batch = await context.post(
        context.agent + f"/runs/{batch['id']}/prepared",
        {
            "lease_token": lease["lease_token"],
            "nonce": nonce,
        },
        machine="h",
        status=202,
    )
    return batch, nonce


@pytest.mark.asyncio
async def test_installation_is_durable_waiting_intent_without_native_work(
    product: ProductContext,
) -> None:
    installed = await _install(product)
    assert installed["status"] == "needs_input"
    assert installed["reason_codes"] == ["WAITING_FOR_HOST"]
    assert product.native.queue.test_plan_run_ids == []
    bindings = await product.get(product.root + "/bindings")
    assert bindings["items"][0]["installations"][0]["id"] == installed["id"]
    assert "public_key" not in str(bindings)
    async with product.native.session_maker() as session:
        assert len((await session.scalars(select(SelfTestInstallation))).all()) == 1


@pytest.mark.asyncio
async def test_ready_installation_and_binding_offer_the_authorized_run_action(
    product: ProductContext,
) -> None:
    installed = await _ready(product)
    installed = await product.get(product.root + f"/installations/{installed['id']}")
    binding = (await product.get(product.root + "/bindings"))["items"][0]
    assert installed["actions"]["can_execute"] is True
    assert binding["actions"]["can_initialize"] is True
    assert binding["actions"]["can_execute"] is True
    assert binding["actions"]["can_generate"] is True


@respx.mock
@pytest.mark.asyncio
async def test_real_suite_plan_preserves_expected_failure_and_independent_seal(
    product: ProductContext,
) -> None:
    target = respx.get("http://fixture.example/value").mock(
        return_value=Response(200, json={"actual": 1})
    )
    batch, nonce = await _fixed(product)
    assert batch["resource_snapshot"]["plan_id"] == batch["plan_id"]
    assert len(batch["resource_snapshot"]["cases"]) == 2
    assert batch["resource_snapshot"]["suite"]["version"] == 1
    before = await product.get(product.root + f"/runs/{batch['id']}/scenarios")
    assert [row["verification_status"] for row in before["items"]] == ["pending", "pending"]
    await PlanRunCoordinator(product.native.session_maker, product.native.events).run(
        UUID(batch["plan_run_ids"][0])
    )
    rows = (await product.get(product.root + f"/runs/{batch['id']}/scenarios"))["items"]
    assert [row["observed_status"] for row in rows] == ["passed", "failed"]
    assert len(target.calls) == 2
    current = await product.get(product.root + f"/runs/{batch['id']}")
    observer = await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {
            "expected_revision": current["revision"],
            "nonce": nonce,
        },
        machine="o",
    )
    lease = {"lease_token": observer["lease_token"], "nonce": nonce}
    artifact = await product.post(
        product.agent + f"/runs/{batch['id']}/artifacts",
        {
            **lease,
            "kind": "verification",
            "filename": "verification.json",
            "content_base64": base64.b64encode(b'{"synthetic":true}').decode(),
        },
        machine="o",
        status=201,
    )
    receipt = {
        **lease,
        "manifest_digest": batch["manifest_digest"],
        "resource_digest": batch["resource_digest"],
        "policy_digest": batch["policy_digest"],
        "builds": batch["builds"],
        "cleanup_status": "completed",
        "batch_verdict": "passed",
        "evidence_integrity": "complete",
        "batch_reason_codes": [],
        "scenarios": [
            {
                "scenario_id": row["scenario_id"],
                "variant_key": row["variant_key"],
                "observed_status": row["observed_status"],
                "verification_status": "matched",
                "evidence_refs": [artifact],
            }
            for row in rows
        ],
        "artifacts": [artifact],
    }
    path = f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification"
    sealed = await product.post(path, receipt, machine="o")
    assert (sealed["verdict"], sealed["provenance"], sealed["evidence_integrity"]) == (
        "passed",
        "local_untrusted",
        "complete",
    )
    replay = await product.post(path, receipt, machine="o")
    assert replay["sealed_at"] == sealed["sealed_at"]
    await product.post(path, {**receipt, "cleanup_status": "failed"}, machine="o", status=409)
    await product.post(product.root + f"/runs/{batch['id']}/cancel", {}, status=409)
    row = rows[0]
    execution_id = row["executions"][0]["execution_id"]
    relation = await product.get(
        product.root
        + f"/runs/{batch['id']}/scenarios/{row['scenario_id']}/executions/{execution_id}"
    )
    assert relation["scenario"]["id"] == row["id"]
    downloaded = await product.native.client.get(
        product.root + f"/runs/{batch['id']}/artifacts/{artifact['id']}", headers=product.headers
    )
    assert downloaded.content == b'{"synthetic":true}'
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert model is not None and model.sealed_at is not None


@pytest.fixture
async def observation(product: ProductContext) -> AsyncIterator[tuple[dict, dict]]:
    with respx.mock:
        respx.get("http://fixture.example/value").mock(
            return_value=Response(200, json={"actual": 1})
        )
        batch, nonce = await _fixed(product)
        await PlanRunCoordinator(product.native.session_maker, product.native.events).run(
            UUID(batch["plan_run_ids"][0])
        )
        current = await product.get(product.root + f"/runs/{batch['id']}")
        rows = (await product.get(product.root + f"/runs/{batch['id']}/scenarios"))["items"]
        observer = await product.post(
            product.agent + f"/runs/{batch['id']}/claim",
            {
                "expected_revision": current["revision"],
                "nonce": nonce,
            },
            machine="o",
        )
        lease = {"lease_token": observer["lease_token"], "nonce": nonce}
        artifact = await product.post(
            product.agent + f"/runs/{batch['id']}/artifacts",
            {
                **lease,
                "kind": "verification",
                "filename": "verification.json",
                "content_base64": base64.b64encode(b'{"synthetic":true}').decode(),
            },
            machine="o",
            status=201,
        )
        yield (
            batch,
            {
                **lease,
                "manifest_digest": batch["manifest_digest"],
                "resource_digest": batch["resource_digest"],
                "policy_digest": batch["policy_digest"],
                "builds": batch["builds"],
                "batch_verdict": "passed",
                "evidence_integrity": "complete",
                "batch_reason_codes": [],
                "cleanup_status": "completed",
                "scenarios": [
                    {
                        "scenario_id": row["scenario_id"],
                        "variant_key": row["variant_key"],
                        "observed_status": row["observed_status"],
                        "verification_status": "matched",
                        "evidence_refs": [artifact],
                    }
                    for row in rows
                ],
                "artifacts": [artifact],
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("manifest_digest", "0" * 64),
        ("resource_digest", "0" * 64),
        ("policy_digest", "0" * 64),
        ("nonce", "wrong-nonce-" + "0" * 32),
        ("lease_token", "wrong-token-" + "0" * 32),
        ("ci_run_id", "unfrozen-ci"),
        ("ci_attempt", 2),
    ],
)
async def test_observer_rejects_wrong_batch_identity_without_sealing(
    product: ProductContext,
    observation: tuple[dict, dict],
    field: str,
    value: object,
) -> None:
    batch, receipt = observation
    receipt[field] = value
    response = await product.native.client.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        headers=product.machine("o"),
        json=receipt,
    )
    assert response.status_code in {403, 409, 422}, response.text
    assert response.json()["error"]["trace_id"]
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert current["sealed_at"] is None and current["verdict"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant", ["missing", "duplicate", "wrong_raw", "wrong_artifact", "no_evidence"]
)
async def test_observer_rejects_denominator_raw_result_and_evidence_tampering(
    product: ProductContext,
    observation: tuple[dict, dict],
    variant: str,
) -> None:
    batch, receipt = observation
    if variant == "missing":
        receipt["scenarios"].pop()
    elif variant == "duplicate":
        receipt["scenarios"][1] = receipt["scenarios"][0]
    elif variant == "wrong_raw":
        receipt["scenarios"][1]["observed_status"] = "passed"
    elif variant == "wrong_artifact":
        receipt["artifacts"][0]["id"] = str(uuid4())
    else:
        receipt["scenarios"][1]["evidence_refs"] = []
    await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
        status=409,
    )
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert current["sealed_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verdict,integrity,cleanup",
    [
        ("blocked", "complete", "completed"),
        ("failed", "complete", "completed"),
        ("passed", "missing", "completed"),
        ("passed", "complete", "failed"),
    ],
)
async def test_global_observer_failure_cannot_be_promoted_by_matched_rows(
    product: ProductContext,
    observation: tuple[dict, dict],
    verdict: str,
    integrity: str,
    cleanup: str,
) -> None:
    batch, receipt = observation
    receipt.update(
        batch_verdict=verdict,
        evidence_integrity=integrity,
        cleanup_status=cleanup,
        batch_reason_codes=["SELFTEST_OBSERVER_GLOBAL_FINDING"],
    )
    sealed = await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
    )
    assert sealed["verdict"] == ("failed" if verdict == "failed" else "blocked")
    assert sealed["sealed_verdict"] == sealed["verdict"]
    assert "SELFTEST_OBSERVER_GLOBAL_FINDING" in sealed["reason_codes"]
    assert sealed["evidence_integrity"] == integrity
    rows = await product.get(product.root + f"/runs/{batch['id']}/scenarios")
    assert all(row["verification_status"] == "matched" for row in rows["items"])


@pytest.mark.asyncio
async def test_machine_identity_is_separate_from_owner_and_harness(
    product: ProductContext, observation: tuple[dict, dict]
) -> None:
    batch, receipt = observation
    path = f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification"
    await product.post(path, receipt, status=401)
    await product.post(path, receipt, machine="h", status=403)
    wrong_project = f"/api/v1/agent/projects/{uuid4()}/self-tests/tasks"
    response = await product.native.client.get(wrong_project, headers=product.machine("h"))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_retained_history_cannot_display_current_pass_after_artifact_metadata_expires(
    product: ProductContext,
    observation: tuple[dict, dict],
) -> None:
    from app.models.artifacts import Artifact

    batch, receipt = observation
    path = f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification"
    sealed = await product.post(path, receipt, machine="o")
    assert sealed["verdict"] == "passed"
    assert sealed["sealed_verdict"] == "passed"
    async with product.native.session_maker() as session:
        artifact = await session.get(Artifact, UUID(receipt["artifacts"][0]["id"]))
        assert artifact is not None
        await session.delete(artifact)
        await session.commit()
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert (current["verdict"], current["readiness"], current["evidence_integrity"]) == (
        "blocked",
        "blocked",
        "expired",
    )
    assert "SELFTEST_EVIDENCE_EXPIRED" in current["reason_codes"]
    assert current["sealed_verdict"] == "passed"
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert model is not None and model.verdict == "passed" and model.sealed_at is not None
    rows = await product.get(product.root + f"/runs/{batch['id']}/scenarios")
    assert [row["observed_status"] for row in rows["items"]] == ["passed", "failed"]


@pytest.mark.asyncio
async def test_retention_set_null_keeps_archived_identity_but_expires_live_execution_relation(
    product: ProductContext,
    observation: tuple[dict, dict],
) -> None:
    from app.models.self_tests import SelfTestScenarioResult
    from app.models.tasking import TestPlanRunItem as RunItem
    from app.models.workflows import WorkflowExecution

    batch, receipt = observation
    await product.post(
        f"/api/v1/ci/projects/{product.project_id}/self-test-runs/{batch['id']}/verification",
        receipt,
        machine="o",
    )
    before = (await product.get(product.root + f"/runs/{batch['id']}/scenarios"))["items"][0]
    reference = before["executions"][0]
    async with product.native.session_maker() as session:
        item = await session.get(RunItem, UUID(reference["run_item_id"]))
        execution = await session.get(WorkflowExecution, UUID(reference["execution_id"]))
        row = await session.get(SelfTestScenarioResult, UUID(before["id"]))
        assert item is not None and execution is not None and row is not None
        # This SQLite fixture disables FKs; reproduce PostgreSQL's post-retention SET NULL state.
        item.workflow_execution_id, row.execution_id = None, None
        await session.delete(execution)
        await session.commit()
    after = (await product.get(product.root + f"/runs/{batch['id']}/scenarios"))["items"][0]
    assert after["attempts_complete"] is False
    assert after["executions"][0]["execution_id"] == reference["execution_id"]
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert current["sealed_verdict"] == "passed"
    assert (current["evidence_integrity"], current["verdict"], current["readiness"]) == (
        "expired",
        "blocked",
        "blocked",
    )
    relation = (
        product.root
        + f"/runs/{batch['id']}/scenarios/{before['scenario_id']}"
        + f"/executions/{reference['execution_id']}"
    )
    response = await product.native.client.get(relation, headers=product.headers)
    assert response.status_code == 404
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestBatch, UUID(batch["id"]))
        assert model is not None and model.verdict == "passed"


@pytest.mark.asyncio
async def test_mcp_denominator_is_created_before_host_generation_and_cannot_shrink(
    product: ProductContext,
) -> None:
    installed = await _ready(product, "mcp-core-v1")
    path = product.root + f"/installations/{installed['id']}/generation-batches"
    await product.post(path, {"scenario_ids": ["ST-MCP-025"]}, key="bad-full", status=422)
    batch = await product.post(path, {}, key="generation", status=202)
    rows = await product.get(product.root + f"/runs/{batch['id']}/scenarios")
    assert rows["total"] == batch["expected_count"] == 3
    assert all(
        row["verification_status"] == "pending" and row["observed_status"] is None
        for row in rows["items"]
    )
    assert batch["phase"] == "pending" and batch["provenance"] == "local_untrusted"
    assert batch["sealed_verdict"] is None
    assert not batch["actions"]["can_execute"] and product.native.queue.test_plan_run_ids == []
    filtered = await product.get(
        product.root + f"/runs/{batch['id']}/scenarios?scenario_id=ST-MCP-023&page_size=1"
    )
    assert filtered["total"] == 1 and filtered["items"][0]["scenario_id"] == "ST-MCP-023"
    replay = await product.post(path, {}, key="generation", status=202)
    assert replay["id"] == batch["id"]
    await product.post(path, {"budget": {"max_requests": 400}}, key="generation", status=409)


@pytest.mark.asyncio
async def test_low_fixed_budget_rejected_before_batch_or_native_run(
    product: ProductContext,
) -> None:
    installed = await _ready(product)
    error = await product.post(
        product.root + f"/installations/{installed['id']}/runs",
        {
            "budget": {"max_requests": 1},
        },
        key="low-budget",
        status=409,
    )
    assert error["error"]["code"] == "SELFTEST_REQUEST_BUDGET_UNSUPPORTED"
    async with product.native.session_maker() as session:
        assert (await session.scalars(select(SelfTestBatch))).all() == []
        assert (await session.scalars(select(PlanRun))).all() == []
    assert product.native.queue.test_plan_run_ids == []


@pytest.mark.asyncio
async def test_installation_idempotency_and_preview_are_bound_to_intent(
    product: ProductContext,
) -> None:
    installed = await _install(product)
    request = {"template_id": "product-test-v1", "binding_id": str(product.binding.id)}
    preview = await product.post(product.root + "/installations/preview", request)
    # The completed intent remains replayable even after its old preview expired.
    replay = await product.post(
        product.root + "/installations",
        {
            **request,
            "preview_fingerprint": "0" * 64,
            "preview_expires_at": "2020-01-01T00:00:00Z",
        },
        key="installation:product-test-v1",
        status=202,
    )
    assert replay["id"] == installed["id"]
    await product.post(
        product.root + "/installations",
        {
            **request,
            "template_id": "core-v1",
            "preview_fingerprint": preview["fingerprint"],
            "preview_expires_at": preview["expires_at"],
        },
        key="installation:product-test-v1",
        status=409,
    )
    await product.post(
        product.root + "/installations",
        {
            **request,
            "preview_fingerprint": "0" * 64,
            "preview_expires_at": preview["expires_at"],
        },
        key="tampered-preview",
        status=409,
    )
    await product.post(
        product.root + "/installations/preview",
        {**request, "target_url": "http://arbitrary.example"},
        status=422,
    )


@pytest.mark.asyncio
async def test_generation_claim_nonce_stage_and_cancel_never_resurrect(
    product: ProductContext,
) -> None:
    installed = await _ready(product, "mcp-core-v1")
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/generation-batches",
        {},
        key="generation",
        status=202,
    )
    claim = {"expected_revision": batch["revision"], "nonce": "generation-nonce-" + "3" * 32}
    lease = await product.post(product.agent + f"/runs/{batch['id']}/claim", claim, machine="h")
    await product.post(product.agent + f"/runs/{batch['id']}/claim", claim, machine="h", status=409)
    request = {"lease_token": lease["lease_token"], "nonce": lease["nonce"]}
    renewed = await product.post(product.agent + f"/runs/{batch['id']}/lease", request, machine="h")
    assert renewed["revision"] > lease["revision"]
    path = product.agent + f"/runs/{batch['id']}/generation"
    await product.post(
        path,
        {**request, "stage": "designing", "readiness": "needs_input", "tool_call_count": 5},
        machine="h",
    )
    await product.post(
        path,
        {**request, "stage": "discovering", "readiness": "needs_input", "tool_call_count": 6},
        machine="h",
        status=409,
    )

    await product.post(
        path,
        {**request, "stage": "compiling", "readiness": "ready", "tool_call_count": 6},
        machine="h",
        status=409,
    )
    await product.post(
        path,
        {**request, "stage": "compiling", "readiness": "needs_input", "tool_call_count": 4},
        machine="h",
        status=409,
    )
    cancelled = await product.post(product.root + f"/runs/{batch['id']}/cancel", {})
    assert cancelled["phase"] == "cancelled"
    await product.post(
        path,
        {**request, "stage": "proposing", "readiness": "needs_review", "tool_call_count": 6},
        machine="h",
        status=409,
    )


@pytest.mark.asyncio
async def test_installation_renew_receipt_replay_and_mismatch(product: ProductContext) -> None:
    installed, task = await _claimed_installation(product)
    lease = {"lease_token": task["lease_token"], "nonce": task["nonce"]}
    path = product.agent + f"/installations/{installed['id']}"
    renewed = await product.post(path + "/lease", lease, machine="h")
    assert renewed["revision"] > task["revision"]
    assert renewed["lease_token"] == task["lease_token"]
    await product.post(
        path + "/lease", {**lease, "nonce": "wrong-nonce-" + "3" * 32}, machine="h", status=403
    )
    await product.post(path + "/lease", lease, machine="o", status=403)
    payload = {
        **lease,
        "environment_fingerprint": product.binding.environment_fingerprint,
        "mapping": product.mapping.model_dump(mode="json"),
    }
    wrong = {**payload, "mapping": {**payload["mapping"], "target_project_id": str(uuid4())}}
    await product.post(path + "/receipt", wrong, machine="h", status=409)
    receipt = await product.post(path + "/receipt", payload, machine="h")
    replay = await product.post(path + "/receipt", payload, machine="h")
    assert receipt["revision"] == replay["revision"] and replay["status"] == "ready"
    await product.post(path + "/receipt", wrong, machine="h", status=409)
    await product.post(path + "/lease", lease, machine="h", status=409)


@pytest.mark.asyncio
async def test_expired_lease_is_unknown_and_cannot_be_automatically_reclaimed(
    product: ProductContext,
) -> None:
    installed, task = await _claimed_installation(product)
    async with product.native.session_maker() as session:
        model = await session.get(SelfTestInstallation, UUID(installed["id"]))
        assert model is not None
        model.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    await product.post(
        product.agent + f"/installations/{installed['id']}/lease",
        {
            "lease_token": task["lease_token"],
            "nonce": task["nonce"],
        },
        machine="h",
        status=409,
    )
    await product.post(
        product.agent + f"/installations/{installed['id']}/claim",
        {
            "expected_revision": task["revision"],
            "nonce": task["nonce"],
        },
        machine="h",
        status=409,
    )
    current = await product.get(product.root + f"/installations/{installed['id']}")
    assert current["status"] == "installing" and current["readiness"] == "needs_review"
    assert "SELFTEST_LEASE_EXPIRED" in current["reason_codes"]


@pytest.mark.asyncio
async def test_two_harness_workers_claim_batch_only_once(product: ProductContext) -> None:
    installed = await _ready(product, "mcp-core-v1")
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/generation-batches",
        {},
        key="concurrent",
        status=202,
    )
    responses = await asyncio.gather(
        *[
            product.native.client.post(
                product.agent + f"/runs/{batch['id']}/claim",
                headers=product.machine("h"),
                json={
                    "expected_revision": batch["revision"],
                    "nonce": f"worker-{index}-" + "4" * 32,
                },
            )
            for index in range(2)
        ]
    )
    assert sorted(response.status_code for response in responses) == [200, 409]


@pytest.mark.asyncio
async def test_dispatch_retry_reuses_one_durable_native_run(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = product.native.queue.start_test_plan

    def unavailable(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic unavailable queue")

    monkeypatch.setattr(product.native.queue, "start_test_plan", unavailable)
    batch, _ = await _fixed(product)
    assert batch["reason_codes"] == ["SELFTEST_DISPATCH_UNCONFIRMED"]
    assert batch["actions"]["can_execute"]
    assert len(batch["plan_run_ids"]) == 1
    monkeypatch.setattr(product.native.queue, "start_test_plan", original)
    payload = {
        "resource_digest": batch["resource_digest"],
        "environment_fingerprint": batch["environment_fingerprint"],
        "confirmed": True,
    }
    path = product.root + f"/runs/{batch['id']}/execute-materialized"
    resumed = await product.post(path, payload, key="dispatch-recovery", status=202)
    assert resumed["plan_run_ids"] == batch["plan_run_ids"] and not resumed["reason_codes"]
    replay = await product.post(path, payload, key="dispatch-recovery", status=202)
    assert replay["plan_run_ids"] == batch["plan_run_ids"]
    assert len(product.native.queue.test_plan_run_ids) == 1
    async with product.native.session_maker() as session:
        assert len((await session.scalars(select(PlanRun))).all()) == 1


@pytest.mark.asyncio
async def test_native_queue_transaction_failure_can_retry_frozen_plan_without_second_suite(
    product: ProductContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.errors import AppError
    from app.models.test_assets import TestSuite as Suite
    from app.services.tasking import TestPlanService as Plans

    original = Plans.queue_run

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise AppError(code="SYNTHETIC_QUEUE_REJECTED", message="合成队列拒绝", status_code=503)

    installed = await _ready(product)
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/runs", {}, key="transaction", status=202
    )
    task = await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {
            "expected_revision": batch["revision"],
            "nonce": "queue-nonce-" + "5" * 32,
        },
        machine="h",
    )
    monkeypatch.setattr(Plans, "queue_run", unavailable)
    await product.post(
        product.agent + f"/runs/{batch['id']}/prepared",
        {
            "lease_token": task["lease_token"],
            "nonce": task["nonce"],
        },
        machine="h",
        status=503,
    )
    current = await product.get(product.root + f"/runs/{batch['id']}")
    assert current["phase"] == "ready" and current["plan_run_ids"] == []
    monkeypatch.setattr(Plans, "queue_run", original)
    executed = await product.post(
        product.root + f"/runs/{batch['id']}/execute-materialized",
        {
            "resource_digest": current["resource_digest"],
            "environment_fingerprint": current["environment_fingerprint"],
            "confirmed": True,
        },
        key="after-rollback",
        status=202,
    )
    assert executed["plan_id"] == current["plan_id"]
    async with product.native.session_maker() as session:
        assert len((await session.scalars(select(PlanRun))).all()) == 1
        assert len((await session.scalars(select(Suite))).all()) == 1
