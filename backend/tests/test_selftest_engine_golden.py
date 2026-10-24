"""New native golden pack uses public assets/Case/Suite/Plan/Run and independent O."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from test_selftest_fixed_baseline import RunningAPI, _dependencies, _fixture_apps
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import BatchEvidence, Builds  # noqa: E402
from scripts.selftest.engine_golden import (  # noqa: E402
    PACK_DIRECTORY,
    execute_engine_golden,
    load_engine_golden_pack,
)
from scripts.selftest.fixed_baseline import load_core_pack  # noqa: E402
from scripts.selftest.io import HarnessError, PublicAPI  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402


def test_golden_pack_freezes_exact_denominator_and_independent_constants(tmp_path: Path) -> None:
    pack = load_engine_golden_pack()
    assert len(pack.expectations) == 5
    assert sum(len(item.wire) for item in pack.fixtures) == 5
    assert pack.manifest.pack_id == "engine-golden-v1"
    assert (
        sum(int(item.definition["run_policy"]["request_budget"]) for item in pack.workflows) <= 500
    )
    file = pack.expectations[2].expected.binary_file
    assert file is not None
    assert file.size_bytes == len(b"flowtest-download") == 17
    assert file.sha256 == hashlib.sha256(b"flowtest-download").hexdigest()
    assert (
        load_core_pack().digest
        == "93d772af7216b661586dd0f4714b49b295846d192c383d8c4cc2fff21164b9bf"
    )
    changed = tmp_path / "changed"
    shutil.copytree(PACK_DIRECTORY, changed)
    document = json.loads((changed / "expectations.json").read_text())
    document["expectations"][2]["expected"]["binary_file"]["size_bytes"] = 18
    (changed / "expectations.json").write_text(json.dumps(document))
    with pytest.raises(HarnessError, match="PACK_DIGEST_MISMATCH"):
        load_core_pack(changed)


@pytest.mark.asyncio
async def test_golden_native_case_suite_plan_run_and_independent_file_oracle(
    tasking_context: TaskingTestContext, tmp_path: Path
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    project, environment, service = await _dependencies(api)
    token = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "黄金证据", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", str(token["token"]), transport=httpx.ASGITransport(app=app))
    business, admin = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=admin),
    )
    target = httpx.AsyncClient(
        base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
    )
    calls: list[str] = []

    async def forward(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
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
        with respx.mock as routes:
            routes.route(host="fixed-fixture.example").mock(side_effect=forward)
            result = await execute_engine_golden(
                api,
                reader,
                observer,
                project_id=project,
                environment_id=environment,
                service_id=service,
                batch_key="golden-native",
                nonce="golden-native-nonce-001",
                fixture_digest="a" * 64,
                builds=Builds(
                    runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
                ),
                output_dir=tmp_path / "golden",
                deadline=datetime.now(UTC) + timedelta(seconds=600),
            )
        assert result.report.batch_verdict == "passed", result.report.model_dump_json(indent=2)
        assert len(calls) == 5
        assert [scene.execution.status for scene in result.evidence.scenarios] == [
            "passed",
            "passed",
            "passed",
            "failed",
            "failed",
        ]
        assert all(scene.verification_status == "matched" for scene in result.report.scenarios)
        assert result.installation is not None and len(result.installation.assets) == 5
        plan = json.loads((tmp_path / "golden/plan-run.json").read_text())
        assert len(plan["items"]) == 5
        assert {item["target_id"] for item in plan["items"]} == {
            str(asset.case_id) for asset in result.installation.assets
        }
        assert all(
            item["target_type"] == "case" and item["target_version"] == 1 for item in plan["items"]
        )
        assert {item["execution_id"] for item in plan["items"]} == {
            str(scene.execution.id) for scene in result.evidence.scenarios
        }
        assert (tmp_path / "golden/execution.junit.xml").is_file()
        assert (tmp_path / "golden/verification.junit.xml").is_file()
        assert sum(len(scene.execution.nodes) for scene in result.evidence.scenarios) >= 20
        # Tamper only safe receipt metadata/constant evidence. No product comparator is O.
        for field, value in [("size_bytes", 18), ("sha256", "b" * 64)]:
            changed = result.evidence.model_dump(mode="json")
            changed["scenarios"][2]["journal"]["entries"][0]["binary_response"][field] = value
            report = verify_batch(result.manifest, BatchEvidence.model_validate(changed))
            assert report.batch_verdict == "failed"
            assert "FILE_CONTENT_MISMATCH" in {
                finding.code for finding in report.scenarios[2].findings
            }
        changed = copy.deepcopy(result.evidence.model_dump(mode="json"))
        entry = changed["scenarios"][2]["journal"]["entries"][0]
        entry["response_body"] = {"value": "flowtest-download"}
        report = verify_batch(result.manifest, BatchEvidence.model_validate(changed))
        assert report.batch_verdict == "failed"
        assert "FILE_RESPONSE_KIND_MISMATCH" in {
            finding.code for finding in report.scenarios[2].findings
        }
    finally:
        await target.aclose()
        await api.close()
        await reader.close()
        await observer.close()


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("golden", "FILE_GOLDEN_INVALID"),
        ("missing", "FILE_RECEIPT_MISSING"),
        ("json", "FILE_RESPONSE_KIND_MISMATCH"),
        ("no_binary", "FILE_RESPONSE_KIND_MISMATCH"),
        ("path", "FILE_CONTENT_MISMATCH"),
        ("method", "FILE_CONTENT_MISMATCH"),
        ("status", "FILE_CONTENT_MISMATCH"),
    ],
)
def test_independent_file_oracle_rejects_wrong_kind_and_unbound_download(
    mutation: str, code: str
) -> None:
    from scripts.selftest.contracts import ScenarioObservation
    from scripts.selftest.verify_engine_golden import verify_binary_file

    expected = load_engine_golden_pack().expectations[2].expected
    binary = {
        "size_bytes": 17,
        "sha256": hashlib.sha256(b"flowtest-download").hexdigest(),
        "content_type": "application/octet-stream",
        "filename": "flowtest.bin",
    }
    entry = {
        "sequence": 1,
        "method": "GET",
        "path": "/selftest/owned/ST-GOLDEN-file/download",
        "response_status": 200,
        "request_body": {},
        "response_body": None,
        "binary_response": binary,
    }
    if mutation == "golden":
        expected = expected.model_copy(
            update={"binary_file": expected.binary_file.model_copy(update={"sha256": "b" * 64})}
        )
    elif mutation == "json":
        entry["response_body"] = {"value": "flowtest-download"}
    elif mutation == "no_binary":
        entry["binary_response"] = None
    elif mutation == "path":
        entry["path"] = "/selftest/owned/ST-GOLDEN-file/request"
    elif mutation == "method":
        entry["method"] = "POST"
    elif mutation == "status":
        entry["response_status"] = 503
    observation = ScenarioObservation.model_validate(
        {
            "scenario_id": "ST-GOLDEN-file",
            "cleanup_status": "completed",
            "journal": None
            if mutation == "missing"
            else {
                "batch_key": "owned",
                "scenario_id": "ST-GOLDEN-file",
                "nonce": "owned-nonce",
                "fixture_epoch": "epoch",
                "fixture_digest": "a" * 64,
                "request_count": 1,
                "entries": [entry],
            },
        }
    )
    assert [finding.code for finding in verify_binary_file(expected, observation)] == [code]
