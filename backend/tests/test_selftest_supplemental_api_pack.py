"""Real dual-ASGI native graphs; these are not deployed profile acceptance."""

import json
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from test_selftest_fixed_baseline import RunningAPI, _dependencies, _fixture_apps
from test_selftest_mcp_probe_setup import binding as synthetic_binding
from test_selftest_native_api_pack import identity, isolated_target, target_environment
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.core.config import settings
from app.domain.runtime_profiles import RuntimeProfile
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.bootstrap import Installation  # noqa: E402
from scripts.selftest.contracts import BatchEvidence, Builds, canonical_digest  # noqa: E402
from scripts.selftest.fixed_baseline import load_core_pack  # noqa: E402
from scripts.selftest.io import PublicAPI, read_json  # noqa: E402
from scripts.selftest.supplemental_api_pack import execute_supplemental_api_pack  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402


def test_fifteen_frozen_supplemental_variants_keep_old_pack_digests_and_expiry_exclusion():
    original = load_core_pack(ROOT / "selftest/packs/native-api-v1")
    extended = load_core_pack(ROOT / "selftest/packs/extended-v1")
    pack = load_core_pack(ROOT / "selftest/packs/supplemental-api-v1")
    assert len(original.expectations) == 12 and len(extended.expectations) == 19
    assert len(pack.expectations) == 15 and pack.manifest.pack_version == "1.0.0"
    assert sum(int(w.definition["run_policy"]["request_budget"]) for w in pack.workflows) <= 500
    assert len({w.scenario_id for w in pack.workflows}) == 15
    exclusion = read_json(ROOT / "selftest/packs/supplemental-api-v1/exclusions.json")["items"][0]
    assert exclusion["variant_key"] == "expired"
    assert exclusion["status"] == "unsupported_in_current_profile_budget"
    values = {v.scenario_id: v.expected.expected_request_value_presence for v in pack.expectations}
    assert values["ST-P0-API007-omitted"] == (False,)
    assert values["ST-P0-API007-explicit-null"] == (True,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile", [RuntimeProfile.STANDALONE, RuntimeProfile.FULL, RuntimeProfile.COMPACT]
)
async def test_fifteen_native_api_supplemental_variants_public_case_suite_plan_and_safe_oracle(
    tasking_context: TaskingTestContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: RuntimeProfile,
):
    from scripts.selftest import supplemental_api_pack

    monkeypatch.setattr(settings, "runtime_profile", profile)

    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    project, fixture_env, fixture_service = await _dependencies(api)
    a_project = await api.object("GET", f"/projects/{project}")
    capture, capture_token, _ = await identity(
        api,
        tasking_context.client,
        email="p0-capture@example.com",
        project=project,
        organization=str(a_project["organization_id"]),
    )
    ci = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "P0只读证据", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", str(ci["token"]), transport=httpx.ASGITransport(app=app))
    capture_reader = PublicAPI(
        "http://test",
        capture_token,
        str(a_project["organization_id"]),
        transport=httpx.ASGITransport(app=app),
    )
    business, management = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=management),
    )
    mock = httpx.AsyncClient(
        base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
    )
    async with isolated_target(tmp_path) as (b_app, b_client, b):
        target_project = await b.object("POST", "/projects", {"name": "P0独立B项目"})
        bp, bo = str(target_project["id"]), str(target_project["organization_id"])
        b.set_organization(bo)
        actor, _, password = await identity(
            b,
            b_client,
            email="p0-native-owner@example.com",
            project=bp,
            organization=bo,
            role="owner",
        )
        viewer, viewer_token, _ = await identity(
            b, b_client, email="p0-native-viewer@example.com", project=bp, organization=bo
        )
        await api.object(
            "PUT",
            f"/projects/{project}/secrets",
            {"name": "SELFTEST_B_PASSWORD", "value": password},
        )
        target_env, target_service = await target_environment(api, project)
        binding = synthetic_binding().model_copy(
            update={
                "runner_url": "http://test",
                "target_url": "http://native-b.example",
                "runtime_profile": profile.value,
            }
        )
        installed = Installation(
            binding_nonce=binding.nonce,
            organization_id=UUID(str(a_project["organization_id"])),
            project_id=UUID(project),
            reviewer_id=UUID(capture["id"]),
            reviewer_email=capture["email"],
            mcp_account_id=UUID(capture["id"]),
            target_project_id=UUID(bp),
            target_organization_id=UUID(bo),
            target_user_id=UUID(actor["id"]),
            target_email=actor["email"],
            fixture_environment_id=UUID(fixture_env),
            target_environment_id=UUID(target_env["id"]),
            fixture_service_id=UUID(fixture_service),
            target_service_id=UUID(target_service["id"]),
            target_viewer_id=UUID(viewer["id"]),
            target_viewer_email=viewer["email"],
        )
        target_reader = PublicAPI(
            "http://native-b.example", viewer_token, bo, transport=httpx.ASGITransport(app=b_app)
        )
        original_api = PublicAPI

        class TargetAPI(original_api):
            def __init__(self, url, token="", organization_id=None):
                super().__init__(
                    url, token, organization_id, transport=httpx.ASGITransport(app=b_app)
                )

        monkeypatch.setattr(supplemental_api_pack, "PublicAPI", TargetAPI)

        async def forward_mock(request):
            response = await mock.request(
                request.method,
                request.url.raw_path.decode(),
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(
                response.status_code, content=response.content, headers=dict(response.headers)
            )

        async def forward_target(request):
            # A fresh forwarding client must not invent browser cookie state.
            async with httpx.AsyncClient(
                base_url="http://native-b.example", transport=httpx.ASGITransport(app=b_app)
            ) as client:
                response = await client.request(
                    request.method,
                    request.url.raw_path.decode(),
                    content=request.content,
                    headers=dict(request.headers),
                )
            return httpx.Response(
                response.status_code, content=response.content, headers=dict(response.headers)
            )

        try:
            with respx.mock as routes:
                routes.route(host="fixed-fixture.example").mock(side_effect=forward_mock)
                routes.route(host="native-b.example").mock(side_effect=forward_target)
                result = await execute_supplemental_api_pack(
                    api,
                    reader,
                    observer,
                    capture_reader=capture_reader,
                    target_reader=target_reader,
                    target_provisioner=b,
                    installation=installed,
                    batch_key="supplemental-asgi",
                    nonce="supplemental-asgi-owned-nonce",
                    fixture_digest="a" * 64,
                    builds=Builds(
                        runner="candidate",
                        target="candidate",
                        fixture="a" * 64,
                        verifier="observer",
                    ),
                    output_dir=tmp_path / "p0",
                    binding=binding,
                )
            if len(result.evidence.scenarios) != 15:
                failed_preparation = []
                for phase in result.phases:
                    if any(row.execution is None for row in phase.evidence.scenarios):
                        run = read_json(
                            tmp_path
                            / "p0/phases"
                            / phase.manifest.scenarios[0].scenario_id
                            / "plan-run.json"
                        )
                        detail = await api.object(
                            "GET", f"/projects/{project}/test-plan-runs/{run['run_id']}"
                        )
                        failed_preparation.extend(item["error_message"] for item in detail["items"])
                pytest.fail("native preparation: " + repr(failed_preparation))
            findings = {
                finding.code for row in result.report.scenarios for finding in row.findings
            } | {finding.code for finding in result.report.findings}
            assert findings == {"OWNED_ASSET_DISPOSAL_PENDING"}, result.report.model_dump_json(
                indent=2
            )
            assert result.report.exit_code == 2
            assert all(
                row.execution and row.execution.status == "passed"
                for row in result.evidence.scenarios
            )
            assert all(row.cleanup_status == "completed" for row in result.evidence.scenarios)
            assert len(result.phases) == 15 and all(
                phase.installation and phase.installation.suite_id and phase.installation.plan_id
                for phase in result.phases
            )
            _reject_real_evidence_mutations(result)
            for path in (tmp_path / "p0").rglob("*.json"):
                encoded = path.read_text()
                assert (
                    password not in encoded
                    and capture_token not in encoded
                    and viewer_token not in encoded
                )
            (tmp_path / "p0" / "test-boundary.json").write_text(
                json.dumps(
                    {
                        "scope": "dual_asgi_only",
                        "deployment": "NOT_RUN",
                        "disposal": "not_simulated",
                    }
                )
            )
        finally:
            await target_reader.close()
            await mock.aclose()
            await observer.close()
            await capture_reader.close()
            await reader.close()
            await api.close()


def _reject_real_evidence_mutations(result):
    original = result.evidence.model_dump(mode="json")
    mutations = (
        ("ST-P0-API006-auth-disabled", "authorization_present", True, "FIXTURE_RESPONSE_MISMATCH"),
        ("ST-P0-API006-cookie-suppressed", "cookie_present", True, "FIXTURE_RESPONSE_MISMATCH"),
        ("ST-P0-API007-omitted", "request_value_present", True, "REQUEST_VALUE_PRESENCE_MISMATCH"),
    )
    for scenario, field, replacement, finding in mutations:
        payload = result.evidence.model_dump(mode="json")
        row = next(row for row in payload["scenarios"] if row["scenario_id"] == scenario)
        row["journal"]["entries"][0][field] = replacement
        report = verify_batch(result.manifest, BatchEvidence.model_validate(payload))
        assert report.exit_code == 1
        assert finding in {item.code for row in report.scenarios for item in row.findings}
    payload = result.evidence.model_dump(mode="json")
    row = next(row for row in payload["scenarios"] if row["scenario_id"] == "ST-P0-API009-history")
    for execution in [row["execution"], *row["attempts"]]:
        assertion = next(
            node for node in execution["nodes"] if node["node_id"] == "historical_name"
        )
        assertion["assertions"][0]["actual_digest"] = canonical_digest("current-v2")
    report = verify_batch(result.manifest, BatchEvidence.model_validate(payload))
    assert report.exit_code == 1
    assert "ASSERTION_VALUE_MISMATCH" in {
        item.code for row in report.scenarios for item in row.findings
    }
    payload = result.evidence.model_dump(mode="json")
    payload["scenarios"].pop()
    report = verify_batch(result.manifest, BatchEvidence.model_validate(payload))
    assert report.exit_code == 2
    assert "REQUIRED_SCENARIO_MISSING" in {
        item.code for row in report.scenarios for item in row.findings
    }
    assert result.evidence.model_dump(mode="json") == original


def _disposal_result(binding):
    from datetime import UTC, datetime, timedelta

    from scripts.selftest.contracts import BatchManifest, RequiredDisposal
    from scripts.selftest.native_api_pack import NativeAPIResult
    from test_selftest_verification import evidence_payload, manifest_payload

    now = datetime.now(UTC)
    manifest, evidence = manifest_payload(), evidence_payload()
    manifest["builds"]["target"] = binding.candidate_image_digest
    evidence["builds"]["target"] = binding.candidate_image_digest
    manifest["created_at"] = (now - timedelta(seconds=10)).isoformat()
    manifest["expires_at"] = (now + timedelta(seconds=600)).isoformat()
    manifest["scenarios"][0]["expected"]["required_disposal"] = RequiredDisposal(
        project_name=binding.project_name,
        target_container_id=binding.target_container_id,
        target_volume=binding.target_volume,
        target_image=binding.candidate_image_digest,
        binding_nonce=binding.nonce,
    ).model_dump(mode="json")
    evidence["collected_at"] = (now - timedelta(seconds=1)).isoformat()
    for execution in [evidence["scenarios"][0]["execution"], *evidence["scenarios"][0]["attempts"]]:
        execution["started_at"] = (now - timedelta(seconds=5)).isoformat()
        execution["completed_at"] = (now - timedelta(seconds=2)).isoformat()
    frozen, observed = (
        BatchManifest.model_validate(manifest),
        BatchEvidence.model_validate(evidence),
    )
    return NativeAPIResult(frozen, observed, verify_batch(frozen, observed), ())


def _owned_disposal_files(path, binding):
    from scripts.selftest.io import write_json

    write_json(path / "stack.json", binding)
    write_json(
        path / "ownership.json", {"project_name": binding.project_name, "nonce": binding.nonce}
    )
    write_json(path / "cleanup.json", {"project_name": binding.project_name, "status": "completed"})


def test_supplemental_finalizer_preserves_raw_status_and_is_idempotent_only_after_exact_absence(
    tmp_path, monkeypatch
):
    from scripts.selftest import supplemental_api_pack

    binding = synthetic_binding()
    result = _disposal_result(binding)
    assert result.report.exit_code == 2
    stack, output = tmp_path / "stack", tmp_path / "output"
    _owned_disposal_files(stack, binding)
    absence_reads = []
    monkeypatch.setattr(supplemental_api_pack, "_verify_removed", absence_reads.append)
    finalized = supplemental_api_pack.finalize_supplemental_cleanup(
        result, binding=binding, stack_directory=stack, output_dir=output
    )
    repeated = supplemental_api_pack.finalize_supplemental_cleanup(
        finalized, binding=binding, stack_directory=stack, output_dir=output
    )
    assert repeated.evidence == finalized.evidence and finalized.report.exit_code == 0
    assert absence_reads == [binding.project_name, binding.project_name]
    assert finalized.evidence.scenarios[0].execution.status == "failed"
    assert read_json(output / "evidence.pre-disposal.json") == result.evidence.model_dump(
        mode="json"
    )


@pytest.mark.parametrize("change", ["ownership", "binding", "missing_cleanup", "docker_present"])
def test_supplemental_finalizer_rejects_foreign_or_unremoved_target(tmp_path, monkeypatch, change):
    from scripts.selftest import supplemental_api_pack
    from scripts.selftest.io import HarnessError, write_json

    binding = synthetic_binding()
    result = _disposal_result(binding)
    stack, output = tmp_path / "stack", tmp_path / "output"
    _owned_disposal_files(stack, binding)
    if change == "ownership":
        write_json(
            stack / "ownership.json", {"project_name": binding.project_name, "nonce": "foreign"}
        )
    elif change == "binding":
        write_json(stack / "stack.json", binding.model_copy(update={"target_volume": "foreign"}))
    elif change == "missing_cleanup":
        write_json(
            stack / "cleanup.json", {"project_name": binding.project_name, "status": "pending"}
        )

    def absence(_project):
        if change == "docker_present":
            raise HarnessError("SELFTEST_OWNED_ASSETS_STILL_PRESENT")
        pytest.fail("foreign identity reached Docker read")

    monkeypatch.setattr(supplemental_api_pack, "_verify_removed", absence)
    with pytest.raises(HarnessError):
        supplemental_api_pack.finalize_supplemental_cleanup(
            result, binding=binding, stack_directory=stack, output_dir=output
        )
    assert not (output / "evidence.json").exists()
    assert result.evidence.scenarios[0].target_disposal is None
