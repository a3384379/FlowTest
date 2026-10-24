"""Real SDK quality failures, scoped observer and independent tamper checks."""

import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from test_selftest_bad_targets import _actual_loopback
from test_selftest_mcp_probe_setup import binding
from test_tasking_api import ADMIN_EMAIL, ADMIN_PASSWORD
from test_tasking_api import tasking_context as tasking_context

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.selftest import mcp_probe_setup, quality_setup
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import read_json, write_json
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_probe_evidence import StackSnapshot
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.mcp_probe_setup import _observer, authority, provision
from scripts.selftest.mcp_protocol_runner import isolated_http_protocol, stdio_protocol
from scripts.selftest.quality_boundaries import boundary_requests
from scripts.selftest.quality_contracts import (
    QualityCall,
    QualityEvidence,
    QualityManifest,
    QualityPack,
)
from scripts.selftest.quality_observer import observe
from scripts.selftest.quality_run import collect_transport
from scripts.selftest.quality_verify import PACK_PATH, verify

from app.core.self_test_probes import NegativeProbeGrant
from app.core.self_tests import SelfTestSettings, get_self_test_settings
from app.main import app

ROOT = Path(__file__).parents[2]


@pytest.mark.asyncio
async def test_sdk_quality_18_rows_and_independent_tamper_rejection(
    tasking_context, monkeypatch, tmp_path
):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    original_api, original_login = mcp_probe_setup.ProbeAPI, mcp_probe_setup._login

    class API(original_api):
        def __init__(self, url, budget, token="", organization=None):
            super().__init__(url, budget, token, organization, transport=transport)

    async def login(url, budget, email, password, *, new_actor=False):
        if email == "selftest-a@example.com":
            email, password = ADMIN_EMAIL, ADMIN_PASSWORD
        return await original_login(url, budget, email, password, new_actor=new_actor)

    monkeypatch.setattr(mcp_probe_setup, "ProbeAPI", API)
    monkeypatch.setattr(quality_setup, "ProbeAPI", API)
    monkeypatch.setattr(mcp_probe_setup, "_login", login)
    monkeypatch.setattr(
        mcp_probe_setup,
        "private_environment",
        lambda _: {"FLOWTEST_SELFTEST_RUNNER_PASSWORD": ADMIN_PASSWORD},
    )
    started, nonce = datetime.now(UTC), uuid4().hex
    deadline = started + timedelta(seconds=600)
    budget = ProtocolHttpBudget(tmp_path / "budget.sqlite3", nonce, deadline.timestamp())
    batch = "quality-actual"
    async with _actual_loopback() as base:
        stack = binding().model_copy(update={"runner_url": base})
        issued = await provision(stack, tmp_path, tmp_path, nonce, budget)
        issued, scope, sentinel = await quality_setup._scope(stack, issued, nonce, budget)
        raw = read_json(PACK_PATH)
        pack = QualityPack.model_validate(raw)
        calls = []
        for row in pack.scenarios:
            if row.expected_readiness is None:
                for name, arguments in boundary_requests(
                    scope, batch + "-" + row.transport, row.action
                ):
                    calls.append(
                        QualityCall(
                            scenario_id=row.scenario_id,
                            tool_name=name,
                            arguments_digest=canonical_digest(arguments),
                        )
                    )
        manifest = QualityManifest(
            batch_key=batch,
            nonce=nonce,
            pack_digest=canonical_digest(raw),
            source_digest=stack.source_digest,
            scope=scope,
            writer_machine_id=issued.fixture.governance.machine_id,
            reader_machine_id=issued.fixture.machine_ids[0],
            created_at=started,
            expires_at=deadline,
            scenarios=pack.scenarios,
            calls=tuple(calls),
        )
        frozen = authority(
            stack,
            issued.fixture,
            canonical_digest(manifest.model_dump(mode="json")),
            nonce,
            started,
            deadline,
        )
        identity = _observer(tmp_path, frozen)
        grant = NegativeProbeGrant.model_validate(
            {
                **frozen.model_dump(mode="json", exclude={"probe_id", "fixtures"}),
                "id": nonce,
                "fixtures": [f.model_dump(mode="json") for f in frozen.fixtures],
                "principal_id": identity.principal.id,
                "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
            }
        )
        config = SelfTestSettings(principals=(identity.principal,), probe_grants=(grant,))
        app.dependency_overrides[get_self_test_settings] = lambda: config
        observer = ProbeReader(
            base, identity.token(), nonce, frozen, budget.reserve, transport=transport
        )
        rows = ()
        try:
            for name, connection in (
                ("stdio", stdio_protocol),
                ("streamable-http", isolated_http_protocol),
            ):
                args = {
                    "python": Path(sys.executable),
                    "backend": ROOT / "backend",
                    "api_url": base,
                    "batch_key": batch + "-" + name,
                }
                async with (
                    connection(
                        **args, token=issued.writer_token, output_dir=tmp_path / name / "writer"
                    ) as writer,
                    connection(
                        **args,
                        token=issued.tokens["reader_a"],
                        output_dir=tmp_path / name / "reader",
                    ) as reader,
                ):
                    rows += await collect_transport(
                        manifest,
                        name,
                        writer,
                        reader,
                        observer,
                        budget,
                        sentinel,
                        tmp_path / "scenarios",
                    )
        finally:
            await observer.close()
    evidence = QualityEvidence(
        manifest_digest=canonical_digest(manifest.model_dump(mode="json")),
        authority_digest=canonical_digest(frozen.model_dump(mode="json")),
        stack=StackSnapshot.model_validate(stack.model_dump(mode="json")),
        observations=rows,
        http_admitted=budget.counts()[0],
        http_rejected=budget.counts()[1],
        tool_attempts=budget.tool_counts()[0],
        tools_rejected=budget.tool_counts()[1],
        protocol_cleanup_complete=True,
        collected_at=datetime.now(UTC),
    )
    report = verify(manifest, evidence, frozen)
    write_json(tmp_path / "report.json", report)
    assert all(r.verification_status == "matched" for r in report.scenarios), report.model_dump(
        mode="json"
    )
    assert [f.code for f in report.findings] == ["OWNED_ASSET_DISPOSAL_PENDING"]
    assert evidence.tool_attempts == 68
    assert {r.kind for r in rows[-1].after.resources} == {"ai_change_set"}
    assert len(rows[-1].after.resources) == 2
    public = tmp_path / "independent-input"
    write_json(public / "manifest.json", manifest)
    write_json(public / "evidence.json", evidence)
    write_json(public / "authority.json", frozen)
    from scripts.selftest import quality_observer

    run_child = quality_observer.subprocess.run

    def limited_child(command, **kwargs):
        assert set(kwargs["env"]) == {"PATH", "PYTHONPATH", "PYTHONUNBUFFERED"}
        return run_child(command, **kwargs)

    monkeypatch.setattr(quality_observer.subprocess, "run", limited_child)
    independent = observe(public)
    assert independent.exit_code == 2
    assert all(r.verification_status == "matched" for r in independent.scenarios)
    assert [f.code for f in independent.findings] == ["OWNED_ASSET_DISPOSAL_PENDING"]
    _tamper_checks(manifest, evidence, frozen)


def _tamper_checks(manifest, evidence, authority):
    original = canonical_digest(evidence.model_dump(mode="json"))

    def reject(changed):
        report = verify(manifest, changed, authority)
        findings = [f.code for f in report.findings if f.code != "OWNED_ASSET_DISPOSAL_PENDING"]
        assert findings or any(r.verification_status != "matched" for r in report.scenarios)

    reject(evidence.model_copy(update={"observations": evidence.observations[:-1]}))
    reject(evidence.model_copy(update={"observations": (evidence.observations[0],) * 18}))
    reject(evidence.model_copy(update={"tool_attempts": 65}))
    reject(evidence.model_copy(update={"http_rejected": 1}))
    reject(evidence.model_copy(update={"protocol_cleanup_complete": False}))
    row = evidence.observations[1]
    changed = row.model_copy(
        update={"generated": row.generated.model_copy(update={"proposed_case_count": 1})}
    )
    reject(
        evidence.model_copy(
            update={"observations": (evidence.observations[0], changed, *evidence.observations[2:])}
        )
    )
    row = evidence.observations[0]
    changed = row.model_copy(
        update={
            "calls": (
                row.calls[0].model_copy(update={"tool_name": "flowtest.publish_workflow"}),
                *row.calls[1:],
            )
        }
    )
    reject(evidence.model_copy(update={"observations": (changed, *evidence.observations[1:])}))
    row = evidence.observations[8]
    changed = row.model_copy(
        update={"credential": row.credential.model_copy(update={"sentinel_leaked": True})}
    )
    reject(
        evidence.model_copy(
            update={
                "observations": (*evidence.observations[:8], changed, *evidence.observations[9:])
            }
        )
    )
    row = evidence.observations[1]
    forged = row.generated.model_copy(
        update={
            "decision": row.generated.decision.model_copy(
                update={"readiness": "ready", "reason_codes": ()}
            )
        }
    )
    ignored = evidence.model_copy(
        update={
            "observations": (
                evidence.observations[0],
                row.model_copy(update={"generated": forged}),
                *evidence.observations[2:],
            )
        }
    )
    assert verify(manifest, ignored, authority).scenarios[1].verification_status == "matched"
    assert canonical_digest(evidence.model_dump(mode="json")) == original
