"""Deployment-only negative probe inventory uses real public API assets."""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import Response
from pydantic import ValidationError
from test_selftest_native_api_security import (
    SecurityWorld,
    assert_error,
    assets,
    execute,
    login,
    payload,
)
from test_selftest_native_api_security import world as world

from app.core.config import settings
from app.core.self_test_probes import NegativeProbeGrant, ProbeFixture
from app.core.self_tests import SelfTestPrincipal, SelfTestSettings, get_self_test_settings
from app.domain.self_tests import document_digest
from app.domain.test_design import TestDesignDocument as DesignDocument
from app.domain.test_design import fingerprint_design
from app.main import app
from app.schemas.self_test_probes import ProbeKind
from app.schemas.self_tests import BuildIdentity
from app.services.self_test_access import token_digest
from app.services.self_test_probes import NegativeProbeService


@dataclass(repr=False)
class ProbeContext:
    world: SecurityWorld
    config: SelfTestSettings
    grant: NegativeProbeGrant
    headers: dict[str, str]
    machine_headers: dict[str, str]
    admin: dict[str, str]

    @property
    def path(self) -> str:
        return f"/api/v1/agent/self-test-probes/{self.grant.id}/inventory"

    def configure(self, config: SelfTestSettings) -> None:
        app.dependency_overrides[get_self_test_settings] = lambda: config


@pytest.fixture
async def probe(world: SecurityWorld) -> ProbeContext:
    client = world.client
    admin = await login(client, settings.bootstrap_admin_email)
    admin["X-Organization-ID"] = world.organization
    machine = payload(
        await client.post(
            f"/api/v1/organizations/{world.organization}/service-accounts",
            headers=admin,
            json={
                "name": "负向探针机器",
                "account_key": "negative-probe",
                "scopes": ["mcp:write"],
            },
        ),
        201,
    )
    owner = payload(await client.get("/api/v1/auth/me", headers=world.owner), 200)
    reviewer = payload(await client.get("/api/v1/auth/me", headers=world.viewer), 200)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    now = datetime.now(UTC)
    grant = NegativeProbeGrant(
        id=uuid4(),
        principal_id="negative-o",
        binding_id=uuid4(),
        binding_fingerprint="a" * 64,
        fixtures=(
            ProbeFixture(project_id=world.project, organization_id=world.organization),
            ProbeFixture(
                project_id=world.foreign_project, organization_id=world.foreign_organization
            ),
        ),
        owner_user_id=owner["id"],
        reviewer_user_id=reviewer["id"],
        machine_account_ids=(machine["id"],),
        nonce_hash=token_digest("n" * 48),
        manifest_digest="b" * 64,
        source_digest="c" * 64,
        runtime_profile="standalone",
        builds=BuildIdentity(runner="a", target="b", fixture="m", verifier="o"),
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=599),
    )
    principal = SelfTestPrincipal(
        id="negative-o",
        issuer="https://negative.example",
        subject="negative-o",
        audience="negative-probe",
        public_key=public,
        allowed_project_ids=tuple(item.project_id for item in grant.fixtures),
        allowed_binding_ids=(grant.binding_id,),
        capabilities=("verify",),
    )
    config = SelfTestSettings(principals=(principal,), probe_grants=(grant,))
    token = jwt.encode(
        {
            "iss": principal.issuer,
            "sub": principal.subject,
            "aud": principal.audience,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=600),
        },
        private,
        algorithm="RS256",
    )
    result = ProbeContext(
        world,
        config,
        grant,
        {
            "Authorization": "Bearer " + token,
            "X-SelfTest-Probe-Nonce": "n" * 48,
            "X-SelfTest-Manifest-Digest": grant.manifest_digest,
        },
        {"Authorization": "Bearer " + machine["token"]},
        admin,
    )
    result.configure(config)
    return result


async def proposal(
    probe: ProbeContext,
    *,
    oracles: int = 1,
    expression: str = "$.status",
    case_definition: dict | None = None,
) -> dict:
    design = {
        "intent": {
            "key": "negative.synthetic",
            "objective": "预批准合成治理反证",
            "acceptance_criteria": ["零原生运行"],
        },
        "oracles": [
            {
                "id": f"status_{i}",
                "kind": "status",
                "expression": expression,
                "expected": 200,
                "confidence": 1.0,
            }
            for i in range(oracles)
        ],
    }
    body = {
        "project_id": probe.world.project,
        "idempotency_key": uuid4().hex,
        "title": "合成治理设计",
        "confidence": 1.0,
        "risk_level": "high",
        "dry_run": False,
        "design": design,
    }
    if case_definition is not None:
        body["test_cases"] = [
            {
                "name": "附加实际提案项",
                "description": "不物化",
                "definition": case_definition,
            }
        ]
    return payload(
        await probe.world.client.post(
            "/api/v1/mcp/write/change-sets", headers=probe.machine_headers, json=body
        ),
        202,
    )["data"]


async def workflow(probe: ProbeContext, name: str = "实际工作流") -> dict:
    return payload(
        await probe.world.client.post(
            f"/api/v1/projects/{probe.world.project}/workflows",
            headers=probe.world.owner,
            json={
                "name": name,
                "definition": {
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "name": "开始",
                            "position": {"x": 0, "y": 0},
                        },
                        {
                            "id": "end",
                            "type": "end",
                            "name": "结束",
                            "position": {"x": 100, "y": 0},
                        },
                    ],
                    "edges": [{"id": "edge", "source": "start", "target": "end"}],
                },
            },
        ),
        201,
    )


async def test_negative_probe_empty_inventory_is_complete_but_never_native_run_success(
    probe: ProbeContext,
) -> None:
    response = await probe.world.client.get(probe.path, headers=probe.headers)
    body = payload(response, 200)
    assert body["complete"] is True and body["total"] == 0 and body["items"] == []
    assert body["execution_scope"] == "governance_negative_only"
    assert body["provenance"] == "local_untrusted"
    assert len(body["covered_projects"]) == 2 and len(body["covered_kinds"]) == 10
    assert "verdict" not in body and "verification_status" not in body
    assert "nonce" not in response.text and "public_key" not in response.text
    assert set(body["covered_kinds"]) == set(ProbeKind.__args__)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "nonce",
        "manifest",
        "principal",
        "project",
        "binding",
        "capability",
        "expired",
        "future",
        "revoked",
        "fixture_org",
        "machine",
        "user",
    ],
)
async def test_negative_probe_denies_missing_wrong_expired_or_drifted_authority(
    probe: ProbeContext,
    mutation: str,
) -> None:
    headers = dict(probe.headers)
    grant, principal = probe.grant, probe.config.principals[0]
    status, code = 403, "SELFTEST_PROBE_IDENTITY_MISMATCH"
    if mutation == "missing":
        headers.pop("X-SelfTest-Probe-Nonce")
        code = "SELFTEST_PROBE_IDENTITY_MISSING"
    elif mutation == "nonce":
        headers["X-SelfTest-Probe-Nonce"] = "x" * 48
    elif mutation == "manifest":
        headers["X-SelfTest-Manifest-Digest"] = "d" * 64
    elif mutation in {"principal", "project", "binding", "capability"}:
        field, value = {
            "principal": ("id", "wrong-o"),
            "project": ("allowed_project_ids", (uuid4(),)),
            "binding": ("allowed_binding_ids", (uuid4(),)),
            "capability": ("capabilities", ("install",)),
        }[mutation]
        principal = principal.model_copy(update={field: value})
        code = "SELFTEST_PROBE_FORBIDDEN"
    elif mutation in {"expired", "future"}:
        now = datetime.now(UTC)
        grant = grant.model_copy(
            update={
                "issued_at": now + timedelta(seconds=10)
                if mutation == "future"
                else now - timedelta(seconds=20),
                "expires_at": now + timedelta(seconds=30)
                if mutation == "future"
                else now - timedelta(seconds=1),
            }
        )
        code = "SELFTEST_PROBE_EXPIRED"
    elif mutation == "revoked":
        grant = grant.model_copy(update={"enabled": False})
        status, code = 404, "SELFTEST_PROBE_NOT_FOUND"
    else:
        if mutation == "fixture_org":
            grant = grant.model_copy(
                update={
                    "fixtures": (
                        grant.fixtures[0].model_copy(update={"organization_id": uuid4()}),
                        grant.fixtures[1],
                    )
                }
            )
        else:
            field = "machine_account_ids" if mutation == "machine" else "owner_user_id"
            grant = grant.model_copy(
                update={field: (uuid4(),) if mutation == "machine" else uuid4()}
            )
        code = "SELFTEST_PROBE_FIXTURE_MISMATCH"
    probe.configure(
        probe.config.model_copy(update={"probe_grants": (grant,), "principals": (principal,)})
    )
    assert_error(await probe.world.client.get(probe.path, headers=headers), status, code)


async def test_negative_probe_real_proposal_approval_design_digests_and_machine_revocation(
    probe: ProbeContext,
) -> None:
    proposed = await proposal(probe)
    root = f"/api/v1/mcp/write/change-sets/{proposed['id']}"
    approval = payload(
        await probe.world.client.post(root + "/approve", headers=probe.admin, json={}), 200
    )["data"]["approval"]
    accepted = payload(
        await probe.world.client.post(
            root + f"/items/{proposed['items'][0]['id']}/accept",
            headers=probe.admin,
            json={"approval_id": approval["id"]},
        ),
        200,
    )["data"]
    materialized = accepted["items"][0]["materialized_resource_id"]
    read = payload(await probe.world.client.get(probe.path, headers=probe.headers), 200)
    assert read["complete"] and read["total"] == 3
    rows = {row["kind"]: row for row in read["items"]}
    assert rows["change_set_approval"]["status"] == "approved"
    assert rows["change_set_approval"]["parent_id"] == proposed["id"]
    design, change = rows["test_design"], rows["ai_change_set"]
    assert design["id"] == materialized and design["status"] == "approved"
    assert design["source_change_set_id"] == proposed["id"]
    assert change["actor_type"] == "service_account"
    assert len(change["items"]) == 1
    item = change["items"][0]
    assert item["item_type"] == "test_design" and item["action"] == "create"
    normalized = DesignDocument.model_validate(proposed["items"][0]["proposed_content"])
    assert item["proposed_document_digest"] == fingerprint_design(normalized)
    assert item["design"]["document_digest"] == design["design"]["document_digest"]
    assert item["design"]["oracles"][0]["expected_digest"] == document_digest(200)
    assert "预批准合成治理反证" not in str(read) and "$.status" not in str(read)
    payload(
        await probe.world.client.post(
            f"/api/v1/organizations/{probe.world.organization}/service-accounts/{probe.grant.machine_account_ids[0]}/revoke",
            headers=probe.admin,
        ),
        200,
    )
    assert payload(await probe.world.client.get(probe.path, headers=probe.headers), 200)["complete"]


async def test_negative_probe_pagination_is_stable_exact_and_changes_fail_closed(
    probe: ProbeContext,
) -> None:
    for i in range(3):
        await workflow(probe, f"分页流程{i}")
    pages, cursor = [], None
    for _ in range(3):
        params = {"page_size": 1}
        if cursor:
            params["cursor"] = cursor
        body = payload(
            await probe.world.client.get(probe.path, headers=probe.headers, params=params), 200
        )
        pages.append(body)
        cursor = body["next_cursor"]
    assert cursor is None and len({page["snapshot_digest"] for page in pages}) == 1
    assert len({page["items"][0]["id"] for page in pages}) == 3
    assert all(page["total"] == 3 and page["complete"] for page in pages)
    await workflow(probe, "快照新增")
    assert_error(
        await probe.world.client.get(
            probe.path, headers=probe.headers, params={"cursor": pages[0]["next_cursor"]}
        ),
        409,
        "SELFTEST_PROBE_SNAPSHOT_CHANGED",
    )
    assert_error(
        await probe.world.client.get(probe.path, headers=probe.headers, params={"page_size": 101}),
        422,
        "VALIDATION_ERROR",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "unbounded",
        "naive",
        "duplicate_projects",
        "duplicate_machine",
        "same_reviewer",
        "same_org",
    ],
)
async def test_negative_probe_grant_rejects_unbounded_naive_and_duplicate_configuration(
    probe: ProbeContext,
    mutation: str,
) -> None:
    now = datetime.now(UTC)
    data = probe.grant.model_dump()
    if mutation == "unbounded":
        data.update(issued_at=now, expires_at=now + timedelta(seconds=601))
    elif mutation == "naive":
        data["issued_at"] = now.replace(tzinfo=None)
    elif mutation == "duplicate_projects":
        data["fixtures"] = (probe.grant.fixtures[0], probe.grant.fixtures[0])
    elif mutation == "same_reviewer":
        data["reviewer_user_id"] = probe.grant.owner_user_id
    elif mutation == "same_org":
        data["fixtures"] = (
            probe.grant.fixtures[0],
            probe.grant.fixtures[1].model_copy(
                update={"organization_id": probe.grant.fixtures[0].organization_id}
            ),
        )
    else:
        data["machine_account_ids"] = (probe.grant.machine_account_ids[0],) * 2
    with pytest.raises(ValidationError):
        NegativeProbeGrant.model_validate(data)


async def test_negative_probe_inventory_requires_deployment_identity(world: SecurityWorld) -> None:
    response = await world.client.get(
        f"/api/v1/agent/self-test-probes/{uuid4()}/inventory", headers=world.owner
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "SELFTEST_AGENT_UNAUTHORIZED"
    assert response.json()["error"]["trace_id"]


@respx.mock
async def test_negative_inventory_all_ten_kinds_have_real_public_native_and_governance_rows(
    probe: ProbeContext,
) -> None:
    respx.get("https://fixture.example.com/value").mock(
        return_value=Response(200, json={"ok": True})
    )
    world = probe.world
    env, _, flow = await assets(world, {"method": "GET", "path": "/value", "body_kind": "none"})
    root = f"/api/v1/projects/{world.project}"
    definition = {"workflow_id": flow, "workflow_version": 1, "environment_id": env}
    case = payload(
        await world.client.post(
            root + "/test-cases",
            headers=world.owner,
            json={"name": "实际固定用例", "definition": definition},
        ),
        201,
    )
    payload(
        await world.client.post(
            root + f"/test-cases/{case['id']}/versions",
            headers=world.owner,
            json={"change_note": "冻结"},
        ),
        200,
    )
    plan = payload(
        await world.client.post(
            root + "/test-plans",
            headers=world.owner,
            json={"name": "实际计划", "items": [{"workflow_id": flow, "environment_id": env}]},
        ),
        201,
    )
    run = payload(
        await world.client.post(
            root + f"/test-plans/{plan['id']}/runs", headers=world.owner, json={}
        ),
        202,
    )
    await execute(world, flow, env)
    proposed = await proposal(probe, case_definition=definition)
    change_root = f"/api/v1/mcp/write/change-sets/{proposed['id']}"
    approval = payload(
        await world.client.post(change_root + "/approve", headers=probe.admin, json={}), 200
    )["data"]["approval"]
    payload(
        await world.client.post(
            change_root + f"/items/{proposed['items'][0]['id']}/accept",
            headers=probe.admin,
            json={"approval_id": approval["id"]},
        ),
        200,
    )
    read = payload(await world.client.get(probe.path, headers=probe.headers), 200)
    assert read["complete"] and read["total"] == 10
    assert {row["kind"] for row in read["items"]} == set(ProbeKind.__args__)
    by_kind = {row["kind"]: row for row in read["items"]}
    assert by_kind["test_plan_run"]["id"] == run["id"]
    assert by_kind["test_plan_run"]["parent_id"] == plan["id"]
    assert by_kind["workflow_version"]["parent_id"] == flow
    assert by_kind["test_case_version"]["parent_id"] == case["id"]
    assert len(by_kind["ai_change_set"]["items"]) == 2
    assert by_kind["ai_change_set"]["items"][1]["item_type"] == "test_case"
    assert by_kind["ai_change_set"]["items"][1]["proposed_document_digest"]
    assert "definition" not in str(read) and "body_kind" not in str(read)


async def test_negative_inventory_total_resource_limit_never_truncates_into_complete(
    probe: ProbeContext,
) -> None:
    for i in range(501):
        await workflow(probe, f"总量边界{i}")
    body = payload(await probe.world.client.get(probe.path, headers=probe.headers), 200)
    assert body["total"] == 501 and not body["complete"] and body["items"] == []
    assert body["reason_codes"] == ["SELFTEST_PROBE_RESOURCE_LIMIT"]
    assert body["next_cursor"] is None and not body["has_more"]


@pytest.mark.parametrize("boundary", ["response", "source"])
async def test_negative_inventory_response_and_source_content_are_bounded(
    probe: ProbeContext,
    boundary: str,
) -> None:
    for _ in range(6 if boundary == "response" else 3):
        await proposal(
            probe, oracles=200, expression="x" * 1000 if boundary == "source" else "$.status"
        )
    body = payload(await probe.world.client.get(probe.path, headers=probe.headers), 200)
    assert not body["complete"] and body["items"] == [] and body["next_cursor"] is None
    expected = (
        "SELFTEST_PROBE_RESPONSE_LIMIT"
        if boundary == "response"
        else "SELFTEST_PROBE_CONTENT_LIMIT"
    )
    assert body["reason_codes"] == [expected]


async def test_negative_inventory_total_query_timeout_cannot_be_empty_success(
    probe: ProbeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(*args: object) -> None:
        raise TimeoutError

    monkeypatch.setattr("app.services.self_test_probes.probe_rows", unavailable)
    body = payload(await probe.world.client.get(probe.path, headers=probe.headers), 200)
    assert not body["complete"] and body["items"] == []
    assert body["reason_codes"] == ["SELFTEST_PROBE_QUERY_UNAVAILABLE"]


async def test_negative_inventory_fixture_authorization_reads_share_the_total_five_second_deadline(
    probe: ProbeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = NegativeProbeService._fixtures

    async def delayed(service: NegativeProbeService, grant: NegativeProbeGrant) -> None:
        await original(service, grant)
        await asyncio.sleep(10)

    async def snapshot_must_not_start(*args: object) -> None:
        raise AssertionError("authorization was not completed before its deadline")

    monkeypatch.setattr(NegativeProbeService, "_fixtures", delayed)
    monkeypatch.setattr("app.services.self_test_probes.probe_rows", snapshot_must_not_start)
    started = time.monotonic()
    body = payload(await probe.world.client.get(probe.path, headers=probe.headers), 200)
    assert time.monotonic() - started < 8
    assert not body["complete"] and body["items"] == [] and body["next_cursor"] is None
    assert body["reason_codes"] == ["SELFTEST_PROBE_QUERY_UNAVAILABLE"]
