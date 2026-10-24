"""Real SDK stdio and public native paired Runs; local integration, not deployment proof."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
import uvicorn
from test_selftest_fixed_baseline import RunningAPI, _dependencies, _fixture_apps
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.bad_targets import execute_bad_targets  # noqa: E402
from scripts.selftest.bad_targets_contracts import (  # noqa: E402
    BadTargetsResult,
    load_bad_targets_pack,
)
from scripts.selftest.bad_targets_verify import verify_bad_targets  # noqa: E402
from scripts.selftest.bootstrap import Installation  # noqa: E402
from scripts.selftest.contracts import Builds, canonical_digest  # noqa: E402
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json  # noqa: E402
from scripts.selftest.mcp_protocol_runner import stdio_protocol  # noqa: E402


@asynccontextmanager
async def _actual_loopback():
    server = uvicorn.Server(
        uvicorn.Config(app, lifespan="off", access_log=False, log_level="error")
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


async def _inputs(api):
    project, environment, service = await _dependencies(api)
    doc = await api.object("GET", f"/projects/{project}")
    me = await api.object("GET", "/auth/me")
    account = await api.object(
        "POST",
        f"/organizations/{doc['organization_id']}/service-accounts",
        {
            "name": "真实SDK坏目标生成",
            "account_key": "badtargets-sdk",
            "scopes": [
                "project:read",
                "project:write",
                "mcp:read",
                "mcp:write",
                "mcp:flow:propose",
                "mcp:evidence:write",
                "mcp:contract:import",
                "mcp:test-plan:propose",
            ],
        },
    )
    reader = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {
            "name": "坏目标独立证据",
            "scopes": ["read:execution"],
        },
    )
    installation = Installation.model_validate(
        {
            "binding_nonce": "synthetic-binding-nonce",
            "organization_id": doc["organization_id"],
            "project_id": project,
            "reviewer_id": me["id"],
            "reviewer_email": me["email"],
            "mcp_account_id": account["id"],
            "target_project_id": project,
            "target_user_id": me["id"],
            "target_email": me["email"],
            "fixture_environment_id": environment,
            "target_environment_id": environment,
            "fixture_service_id": service,
            "target_service_id": service,
        }
    )
    return installation, str(account["token"]), str(reader["token"])


@pytest.mark.parametrize(
    "target_fault", ["normal", "positive_bad", "fault_status", "configure_unknown"]
)
@pytest.mark.asyncio
async def test_sdk_generated_three_real_bad_targets_keep_same_assets_two_native_runs_and_dual_junit(
    tasking_context: TaskingTestContext,
    tmp_path: Path,
    target_fault: str,
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    installation, mcp_token, reader_token = await _inputs(api)
    reader = PublicAPI("http://test", reader_token, transport=httpx.ASGITransport(app=app))
    business, admin = _fixture_apps(tmp_path)
    observer = FaultObserver(
        target_fault,
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=admin),
    )
    target = httpx.AsyncClient(
        base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
    )
    calls = []

    async def forward(request):
        calls.append((request.method, request.url.path))
        response = await target.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    try:
        async with (
            _actual_loopback() as base,
            stdio_protocol(
                python=Path(sys.executable),
                backend=ROOT / "backend",
                api_url=base,
                token=mcp_token,
                batch_key="badtargets-sdk",
                output_dir=tmp_path / "sdk",
            ) as client,
        ):
            with respx.mock(assert_all_called=False, assert_all_mocked=False) as routes:
                routes.route(host="fixed-fixture.example").mock(side_effect=forward)

                async def perform():
                    return await execute_bad_targets(
                        client,
                        api,
                        reader,
                        observer,
                        installation=installation,
                        batch_key="badtargets-sdk",
                        nonce="badtargets-native-nonce-000001",
                        fixture_digest="a" * 64,
                        builds=Builds(
                            runner="candidate",
                            target="candidate",
                            fixture="a" * 64,
                            verifier="independent-o",
                        ),
                        output_dir=tmp_path / "round",
                        deadline=datetime.now(UTC) + timedelta(seconds=600),
                    )

                if target_fault == "configure_unknown":
                    with pytest.raises(HarnessError, match="UNKNOWN_CONFIGURATION_RESULT"):
                        await perform()
                    assert not calls
                    cleanup = read_json(tmp_path / "round/positive/cleanup.json")
                    assert cleanup["status"] == "completed"
                    assert cleanup["plan"]["launch_requested"] is False
                    return
                result = await perform()

        if target_fault == "positive_bad":
            assert result.exit_code == 2 and len(result.phases) == 1
            assert "BADTARGET_PAIRED_CONTROL_MISSING" in result.reason_codes
            assert not (tmp_path / "round/fault/plan-run.json").exists()
            return
        if target_fault == "fault_status":
            assert result.exit_code != 0 and len(result.phases) == 2
            auth = result.phases[1].evidence.scenarios[2]
            assert auth.execution.error_code == "HTTP_UNEXPECTED_STATUS"
            assert result.phases[1].report.scenarios[2].verification_status != "matched"
            assert len(calls) == 8
            return
        assert result.exit_code == 0, result.model_dump_json(indent=2)
        assert verify_bad_targets(result) == ()
        assert len(calls) == 8
        assert [
            [scene.execution.status for scene in phase.evidence.scenarios]
            for phase in result.phases
        ] == [
            ["passed"] * 3,
            ["failed"] * 3,
        ]
        assert all(
            scene.verification_status == "matched"
            for phase in result.phases
            for scene in phase.report.scenarios
        )
        assert (
            len(
                {
                    scene.provenance.run.run_id
                    for phase in result.phases
                    for scene in phase.evidence.scenarios
                }
            )
            == 2
        )
        assert all(
            (tmp_path / "round" / name / file).is_file()
            for name in ("positive", "fault")
            for file in (
                "manifest.json",
                "evidence.json",
                "execution.junit.xml",
                "verification.junit.xml",
            )
        )
        assert result.admission.direct_http_attempts + result.admission.tool_attempts + 8 <= 500
        _tamper_actual(result)
        _assert_identity_map(tmp_path / "round/generation/ST-BAD-dependency")
        _assert_cli(tmp_path / "round/badtargets-result.json", tmp_path / "cli")
    finally:
        await target.aclose()
        await reader.close()
        await observer.close()
        await api.close()


def _tamper_actual(result):
    baseline = result.model_dump(mode="json")
    for change in (
        "missing_positive",
        "zero_requests",
        "wrong_code",
        "missing_oracle",
        "source_drift",
        "http_status",
        "truncated",
        "missing_scenario",
        "registration_replay",
        "changed_manifest",
        "tool_count",
        "dependency_input",
        "deleted_read_receipt",
    ):
        value = copy.deepcopy(baseline)
        _tamper_records(value, change)
        assert verify_bad_targets(BadTargetsResult.model_validate(value)), change
    assert baseline == result.model_dump(mode="json")


def test_badtargets_pack_denominator_and_auth_scope_are_explicit() -> None:
    pack = load_bad_targets_pack()
    assert len(pack.scenarios) == 3
    assert sum(item.requests for item in pack.scenarios) * 2 == 8
    assert pack.auth_boundary == "403_synthetic_response_leak_not_cross_tenant_authorization"
    assert pack.scenarios[2].status == 403
    assert pack.scenarios[2].good_value is None
    assert pack.scenarios[2].bad_value == {"resource": "synthetic-protected", "allowed": True}


class FaultObserver(PublicAPI):
    def __init__(self, mode, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.counts = {}

    async def request(self, method, path, payload=None, **kwargs):
        if method == "PUT":
            self.counts[path] = self.counts.get(path, 0) + 1
            payload = copy.deepcopy(payload)
            if self.mode == "positive_bad" and path.endswith("ST-BAD-business"):
                payload["response_body"]["code"] = 7
            if (
                self.mode == "fault_status"
                and path.endswith("ST-BAD-auth")
                and self.counts[path] == 2
            ):
                payload["response_statuses"] = [401]
        result = await super().request(method, path, payload, **kwargs)
        if method == "PUT" and self.mode == "configure_unknown":
            raise HarnessError("SELFTEST_UNKNOWN_CONFIGURATION_RESULT")
        return result


def _assert_identity_map(directory):
    original = read_json(directory / "generated-integration-plan.json")
    final = read_json(directory / "integration-plan.json")
    receipt = read_json(directory / "oracle-identity-map.json")
    mapping = receipt["oracle_id_map"]
    assert receipt["original_plan_fingerprint"] == original["plan_fingerprint"]
    assert receipt["oracle_semantics_changed"] is False
    assert set(mapping) == {item["id"] for item in original["oracles"]}
    assert set(mapping.values()) == {item["id"] for item in final["oracles"]}
    before = {
        mapping[item["id"]]: {k: v for k, v in item.items() if k != "id"}
        for item in original["oracles"]
    }
    after = {item["id"]: {k: v for k, v in item.items() if k != "id"} for item in final["oracles"]}
    assert before == after
    for old, new in zip(original["coverage_targets"], final["coverage_targets"], strict=True):
        assert new["target_ref"] == mapping.get(old["target_ref"], old["target_ref"])
        assert new["covered_by"] == [mapping.get(value, value) for value in old["covered_by"]]


@pytest.mark.asyncio
async def test_badtarget_direct_admission_reserves_all_native_and_sdk_requests() -> None:
    from scripts.selftest.bad_targets_budget import BadTargetsBudget, BoundedBadTargetAPI

    calls = []

    async def transport(request):
        calls.append(request.method)
        return httpx.Response(200, json={"ok": True})

    api = PublicAPI("http://bounded", transport=httpx.MockTransport(transport))
    budget = BadTargetsBudget(datetime.now(UTC) + timedelta(seconds=10))
    bounded = BoundedBadTargetAPI(api, budget)
    try:
        for _ in range(392):
            await bounded.object("GET", "/safe")
        with pytest.raises(HarnessError, match="BUDGET_OR_DEADLINE"):
            await bounded.object("POST", "/never-dispatched", {})
        assert len(calls) == budget.attempts == 392
        assert 392 + 100 + 8 == 500
    finally:
        await api.close()


@pytest.mark.asyncio
async def test_badtarget_slow_public_response_is_bounded_by_same_frozen_deadline() -> None:
    from scripts.selftest.bad_targets_budget import BadTargetsBudget, BoundedBadTargetAPI

    completed = []

    async def transport(request):
        await asyncio.sleep(1)
        completed.append(True)
        return httpx.Response(200, json={"ok": True})

    api = PublicAPI("http://bounded", transport=httpx.MockTransport(transport))
    budget = BadTargetsBudget(datetime.now(UTC) + timedelta(milliseconds=25))
    try:
        with pytest.raises(TimeoutError):
            await BoundedBadTargetAPI(api, budget).object("GET", "/slow")
        assert not completed
        with pytest.raises(HarnessError, match="BUDGET_OR_DEADLINE"):
            budget.admit()
    finally:
        await api.close()


def _assert_cli(path, directory):
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    command = [
        sys.executable,
        "-m",
        "scripts.selftest.bad_targets_verify",
        str(path),
        "--output-dir",
        str(directory),
    ]
    good = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=10)
    assert good.returncode == 0, good.stderr.decode()
    assert read_json(directory / "badtargets-verification.json")["batch_verdict"] == "passed"
    changed = read_json(path)
    changed["phases"][1]["evidence"]["scenarios"][2]["execution"]["error_code"] = (
        "HTTP_UNEXPECTED_STATUS"
    )
    tampered = directory / "tampered.json"
    write_json(tampered, changed)
    bad = subprocess.run(
        [*command[:3], str(tampered), "--output-dir", str(directory / "counterexample")],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
    )
    assert bad.returncode == 1, bad.stderr.decode()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


def _tamper_records(value, change):
    bad = value["phases"][1]
    if change == "missing_scenario":
        bad["evidence"]["scenarios"].pop()
    elif change == "missing_positive":
        value["phases"] = [bad]
    elif change == "zero_requests":
        bad["evidence"]["scenarios"][0]["journal"]["request_count"] = 0
    elif change == "wrong_code":
        bad["evidence"]["scenarios"][0]["execution"]["error_code"] = "NETWORK_TIMEOUT"
    elif change == "missing_oracle":
        bad["evidence"]["scenarios"][2]["provenance"]["oracle_bindings"].pop()
    elif change == "source_drift":
        bad["evidence"]["scenarios"][0]["provenance"]["workflow"]["version"] = 2
    elif change == "http_status":
        bad["evidence"]["scenarios"][2]["execution"]["error_code"] = "HTTP_UNEXPECTED_STATUS"
    elif change == "truncated":
        bad["evidence"]["scenarios"][1]["journal"]["truncated"] = True
    else:
        _tamper_more(value, change)


def _tamper_more(value, change):
    bad = value["phases"][1]
    if change == "registration_replay":
        bad["registrations"] = copy.deepcopy(value["phases"][0]["registrations"])
    elif change == "changed_manifest":
        assertion = next(
            item
            for item in bad["manifest"]["scenarios"][0]["expected"]["assertions"]
            if isinstance(item["expected"], dict)
        )
        assertion["expected"]["properties"]["code"]["const"] = 7
        value["expectation_digests"][1] = canonical_digest(bad["manifest"])
    elif change == "tool_count":
        value["admission"]["tool_attempts"] = 0
    elif change == "dependency_input":
        bad["evidence"]["scenarios"][1]["journal"]["entries"][1]["response_body"][
            "iteration_key"
        ] = "dependency-other"
    elif change == "deleted_read_receipt":
        calls = bad["evidence"]["scenarios"][1]["provenance"]["calls"]
        calls.pop(
            next(
                index
                for index, item in enumerate(calls)
                if item["tool_name"] == "flowtest.inspect_contract"
            )
        )
    else:
        bad["evidence"]["scenarios"].pop()
