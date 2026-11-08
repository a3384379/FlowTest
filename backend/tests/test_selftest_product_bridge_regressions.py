"""The bridge preserves independent failures and rejects over-budget work."""

import base64
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import product_fixed  # noqa: E402
from scripts.selftest.contracts import BatchEvidence, BatchManifest, canonical_digest  # noqa: E402
from scripts.selftest.io import HarnessError, PublicAPI, write_json  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402
from test_selftest_verification import COLLECTED, evidence_payload, manifest_payload  # noqa: E402

from app.schemas.self_tests import (  # noqa: E402
    AgentTaskResponse,
    Budget,
    BuildIdentity,
    FrozenBatchManifest,
    VerificationReceipt,
)
from app.services.self_test_catalog import templates  # noqa: E402


async def test_batch_observer_error_cannot_be_transport_projected_into_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = BatchManifest.model_validate(manifest_payload())
    evidence = BatchEvidence.model_validate(
        {**evidence_payload(), "observer_error": "SELFTEST_OBSERVER_FAILED"}
    )
    verification = partial(verify_batch, now=datetime.fromisoformat(COLLECTED))
    expected = verification(manifest, evidence)
    assert expected.exit_code != 0
    assert {item.verification_status for item in expected.scenarios} == {"matched"}
    assert {item.code for item in expected.findings} == {"OBSERVER_ERROR"}
    monkeypatch.setattr(product_fixed, "verify_batch", verification)
    write_json(tmp_path / "manifest.json", manifest)
    task = cast(
        AgentTaskResponse,
        SimpleNamespace(
            batch=SimpleNamespace(
                resource_digest="b" * 64,
                manifest_digest="a" * 64,
                policy_digest=manifest.policy_digest,
            ),
            nonce="n" * 64,
            lease_token="l" * 64,
            builds=BuildIdentity.model_validate(manifest.builds.model_dump()),
            project_id=manifest.project_id,
            task_id=uuid4(),
        ),
    )
    receipts: list[VerificationReceipt] = []
    uploads: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        payload = json.loads(request.content)
        if request.url.path.endswith("/artifacts"):
            content = base64.b64decode(payload["content_base64"], validate=True)
            uploads.append(payload["kind"])
            return httpx.Response(
                200,
                json={
                    "id": str(uuid4()),
                    "kind": payload["kind"],
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
            )
        assert request.url.path.endswith(f"/{task.task_id}/verification")
        receipts.append(VerificationReceipt.model_validate(payload))
        return httpx.Response(200, json={"accepted": True})

    api = PublicAPI("http://runner.invalid", transport=httpx.MockTransport(respond))
    try:
        await product_fixed.seal_verification(api, task, manifest, evidence, tmp_path)
    finally:
        await api.close()
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.batch_verdict == "blocked"
    assert receipt.evidence_integrity == "missing"
    assert receipt.batch_reason_codes == ("OBSERVER_ERROR",)
    assert receipt.scenarios[0].verification_status == "matched"
    assert receipt.scenarios[0].observed_status == "failed"
    assert {"execution_junit", "verification_junit"} <= set(uploads)
    assert json.loads((tmp_path / "verification.json").read_text())["exit_code"] != 0


async def test_frozen_request_budget_rejects_before_mock_or_native_calls(tmp_path: Path) -> None:
    template = templates()[0]
    now = datetime.now(UTC)
    frozen = FrozenBatchManifest(
        batch_id=uuid4(),
        installation_id=uuid4(),
        project_id=uuid4(),
        binding_id=uuid4(),
        template=template,
        scenarios=template.scenarios,
        batch_kind="fixed_baseline",
        generation_mode=None,
        verification_scope="full_pack",
        budget=Budget(max_requests=1),
        binding_fingerprint="a" * 64,
        environment_fingerprint="b" * 64,
        builds=BuildIdentity(runner="r", target="t", fixture="f", verifier="o"),
        created_at=now,
        deadline=now + timedelta(seconds=600),
    )
    task = cast(
        AgentTaskResponse,
        SimpleNamespace(
            frozen_manifest=frozen,
            budget=frozen.budget,
            batch=SimpleNamespace(manifest_digest=canonical_digest(frozen.model_dump(mode="json"))),
        ),
    )
    requests: list[httpx.Request] = []

    def reject_external_work(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("Low-budget preparation must not contact Mock or native APIs")

    machine = PublicAPI(
        "http://runner.invalid", transport=httpx.MockTransport(reject_external_work)
    )
    observer = PublicAPI(
        "http://observer.invalid", transport=httpx.MockTransport(reject_external_work)
    )
    try:
        with pytest.raises(HarnessError, match="SELFTEST_REQUEST_BUDGET_UNSUPPORTED"):
            await product_fixed.prepare_task(
                machine,
                observer,
                task,
                directory=tmp_path / "batch",
                installation_directory=tmp_path / "unread-installation",
            )
    finally:
        await machine.close()
        await observer.close()
    assert requests == []
    assert not (tmp_path / "batch").exists()
