"""Captured unit inputs and an explicit archival clock, not new deployment acceptance."""

import shutil
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4
from xml.etree.ElementTree import parse

import pytest
from test_selftest_mcp_probe_verify import captured as captured
from test_selftest_mcp_probe_verify import snapshot

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import selftest_ci as driver  # noqa: E402
from scripts.selftest import ci_probes as subject  # noqa: E402
from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.io import read_json, write_json  # noqa: E402
from scripts.selftest.local_stack import BuildReceipt, StackBinding  # noqa: E402
from scripts.selftest.mcp_negative_contracts import ProtocolEvidence, ProtocolManifest  # noqa: E402
from scripts.selftest.mcp_probe_contracts import ProbeFixture  # noqa: E402
from scripts.selftest.mcp_probe_evidence import DeployedEvidence, ScenarioSnapshots  # noqa: E402
from scripts.selftest.mcp_probe_verify import verify_deployed, write_deployed_reports  # noqa: E402


def protocol(captured):
    _, old, previous = captured
    directory = ROOT / "backend/tests/fixtures/mcp_negative_actual_valid_write"
    manifest = ProtocolManifest.model_validate(read_json(directory / "manifest.json"))
    raw = ProtocolEvidence.model_validate(read_json(directory / "evidence.json"))
    nonce = uuid4().hex
    manifest = manifest.model_copy(
        update={"nonce": nonce, "source_digest": old.stack.source_digest}
    )
    raw = raw.model_copy(update={"nonce": nonce, "source_digest": old.stack.source_digest})
    authority = previous.model_copy(
        update={
            "probe_id": UUID(nonce),
            "manifest_digest": canonical_digest(manifest.model_dump(mode="json")),
            "fixtures": (
                ProbeFixture(
                    project_id=manifest.fixture.project_a,
                    organization_id=manifest.fixture.organization_a,
                ),
                ProbeFixture(
                    project_id=manifest.fixture.project_b,
                    organization_id=manifest.fixture.organization_b,
                ),
            ),
            "issued_at": manifest.created_at,
            "expires_at": manifest.expires_at,
        }
    )
    snapshots = tuple(
        ScenarioSnapshots(
            scenario_id=row.scenario_id,
            before=snapshot(authority, {}, row.started_at + timedelta(microseconds=1)),
            after=snapshot(authority, {}, row.completed_at - timedelta(microseconds=1)),
        )
        for row in raw.scenarios
    )
    rpc = sum(len(row.requests) for row in raw.scenarios)
    outbound = raw.http_requests
    raw = raw.model_copy(update={"http_requests": outbound + rpc})
    evidence = DeployedEvidence(
        pack_kind="protocol34",
        manifest_digest=authority.manifest_digest,
        authority_digest=canonical_digest(authority.model_dump(mode="json")),
        stack=old.stack,
        protocol=raw,
        governance=None,
        snapshots=snapshots,
        gateway_cleanup_complete=True,
        disposal_receipt=None,
        collected_at=raw.collected_at,
        request_budget_mode="conservative_outbound_plus_candidate_rpc",
        http_outbound_admitted=outbound,
        candidate_rpc_admitted=rpc,
        candidate_rpc_rejected=0,
    )
    return manifest, evidence, authority


@pytest.fixture
def harness(tmp_path, monkeypatch, captured):
    paths = driver.RunPaths.create(tmp_path / "ci")
    paths.stack.mkdir()
    manifest, evidence, authority = captured
    governance = (manifest, evidence.model_copy(update={"disposal_receipt": None}), authority)
    captures = {"protocol34": protocol(captured), "governance42": governance}
    binding = StackBinding.model_validate(evidence.stack.model_dump(mode="json"))
    write_json(paths.stack / "stack.json", binding)
    write_json(
        paths.stack / "build-receipt.json",
        BuildReceipt.model_validate(
            binding.model_dump(mode="json", include=set(BuildReceipt.model_fields))
        ),
    )
    write_json(
        paths.stack / "ownership.json",
        {"project_name": binding.project_name, "nonce": binding.nonce},
    )
    write_json(
        paths.stack / "cleanup.json", {"project_name": binding.project_name, "status": "completed"}
    )
    monkeypatch.setattr(subject, "builds", lambda _: authority.builds)
    monkeypatch.setattr(
        subject,
        "verify_deployed",
        lambda m, e, a, now: verify_deployed(m, e, a, now=e.collected_at + timedelta(seconds=2)),
    )
    removed = []
    monkeypatch.setattr(subject, "_verify_removed", lambda project: removed.append(project))
    commands = []

    def command(args, *, log, timeout):
        kind = args[args.index("--pack") + 1]
        output = Path(args[args.index("--output") + 1]) / "public"
        final = "--finalize-disposable" in args
        commands.append((kind, final, log, timeout))
        m, e, a = captures[kind]
        if final:
            write_json(output / "evidence.pre-disposal.json", e)
            e = e.model_copy(
                update={
                    "disposal_receipt": evidence.disposal_receipt.model_copy(
                        update={"removed_at": e.collected_at + timedelta(seconds=1)}
                    )
                }
            )
        write_json(output / "manifest.json", m)
        write_json(output / "authority.json", a)
        write_json(output / "evidence.json", e)
        report = verify_deployed(m, e, a, now=e.collected_at + timedelta(seconds=2))
        write_deployed_reports(report, e, output)
        return report.exit_code

    monkeypatch.setattr(driver, "command", command)
    return paths, captures, commands, removed


def test_both_packs_require_real_owned_disposal_then_recompute_and_archive_only_safe_files(harness):
    paths, _, commands, removed = harness
    stages = []
    assert subject.run_probe_stages(paths, stages) == 0
    assert [(row.stage, row.exit_code) for row in stages] == [
        ("protocol34-before-disposal", 2),
        ("governance42-before-disposal", 2),
    ]
    result = subject.finalize_probe_stages(paths, "completed", stages)
    assert [(row.label, row.exit_code, row.verdict) for row in result] == [
        ("protocol34", 0, "passed"),
        ("governance42", 0, "passed"),
    ]
    assert [(kind, final) for kind, final, _, _ in commands] == [
        ("protocol34", False),
        ("governance42", False),
        ("protocol34", True),
        ("governance42", True),
    ]
    assert all(timeout <= 660 and "private-logs" in str(log) for _, _, log, timeout in commands)
    assert len(removed) == 2
    assert len(list(paths.public.iterdir())) == 8
    assert not any("authority" in p.name or "evidence" in p.name for p in paths.public.iterdir())
    assert parse(paths.public / "probe-protocol34-execution.junit.xml").findall(".//failure")
    assert not parse(paths.public / "probe-protocol34-verification.junit.xml").findall(".//failure")
    for kind in ("protocol34", "governance42"):
        before = read_json(paths.directory / f"probe-{kind}/public/verification.pre-disposal.json")
        assert (
            before["exit_code"] == 2
            and before["findings"][0]["code"] == "OWNED_ASSET_DISPOSAL_PENDING"
        )
        identity = read_json(paths.public / f"probe-{kind}-identity.json")
        assert identity["scenario_count"] == (34 if kind == "protocol34" else 42)
        assert (
            identity["claim"] == "governance_negative_only"
            and identity["trust"] == "local_untrusted"
        )


@pytest.mark.parametrize(
    "change", ["cleanup", "owned", "missing", "report", "build", "count", "source"]
)
def test_missing_or_changed_proof_never_becomes_success_or_invokes_unsafe_finalizer(
    harness, change
):
    paths, _, commands, _ = harness
    stages = []
    assert subject.run_probe_stages(paths, stages) == 0
    public = paths.directory / "probe-governance42/public"
    cleanup = "completed"
    if change == "cleanup":
        cleanup = "failed"
    elif change == "owned":
        write_json(paths.stack / "cleanup.json", {"project_name": "foreign", "status": "completed"})
    elif change == "missing":
        (public / "manifest.json").unlink()
    elif change == "report":
        data = read_json(public / "verification.json")
        data.update(exit_code=0, findings=[])
        write_json(public / "verification.json", data)
    elif change == "build":
        data = read_json(public / "authority.json")
        data["builds"]["verifier"] = "forged"
        write_json(public / "authority.json", data)
    elif change == "count":
        data = read_json(public / "manifest.json")
        data["scenarios"].pop()
        write_json(public / "manifest.json", data)
    else:
        data = read_json(public / "evidence.json")
        data["stack"]["source_digest"] = "e" * 64
        write_json(public / "evidence.json", data)
    results = subject.finalize_probe_stages(paths, cleanup, stages)
    assert len(results) == 2 and any(
        row.exit_code == 2 and row.verdict == "blocked" for row in results
    )
    assert not any(kind == "governance42" and final for kind, final, _, _ in commands)


def test_other_exit_two_finding_is_not_accepted_as_disposal_only(harness, monkeypatch):
    paths, _, _, _ = harness
    original = driver.command

    def damaged(*args, **kwargs):
        code = original(*args, **kwargs)
        public = paths.directory / "probe-protocol34/public"
        raw = read_json(public / "verification.json")
        raw["findings"].append({"code": "OTHER_INCOMPLETE", "status": "incomplete"})
        write_json(public / "verification.json", raw)
        return code

    monkeypatch.setattr(driver, "command", damaged)
    assert subject.run_probe_stages(paths, []) == 2
    assert not (paths.directory / "probe-governance42").exists()
    failure = paths.public / "probe-protocol34-before-disposal-failure"
    reason = read_json(failure / "verification.json")
    assert reason["exit_code"] == 2
    assert reason["findings"][0]["code"] == "SELFTEST_CI_PROBE_REPORT_NOT_REPRODUCIBLE"
    observed = read_json(failure / "observed-verification.json")
    assert {row["code"] for row in observed["findings"]} == {
        "OWNED_ASSET_DISPOSAL_PENDING",
        "OTHER_INCOMPLETE",
    }
    assert {item.name for item in failure.iterdir()} == {
        "verification.json",
        "observed-verification.json",
        "execution.junit.xml",
        "verification.junit.xml",
    }


@pytest.mark.parametrize("changed", ["observation", "first_report"])
def test_finalizer_cannot_change_raw_observation_or_hide_missing_required_pack(
    harness, monkeypatch, changed
):
    paths, _, commands, _ = harness
    assert subject.run_probe_stages(paths, []) == 0
    original = driver.command

    def damaged(*args, **kwargs):
        code = original(*args, **kwargs)
        values = args[0]
        if "--finalize-disposable" in values:
            output = Path(values[values.index("--output") + 1]) / "public"
            if changed == "observation":
                target = output / "evidence.pre-disposal.json"
                data = read_json(target)
                data["http_outbound_admitted"] += 1
                write_json(target, data)
            else:
                (output / "verification.pre-disposal.json").unlink()
        return code

    monkeypatch.setattr(driver, "command", damaged)
    shutil.rmtree(paths.directory / "probe-governance42")
    results = subject.finalize_probe_stages(paths, "completed", [])
    assert [(row.label, row.exit_code) for row in results] == [
        ("protocol34", 2),
        ("governance42", 2),
    ]
    assert len(commands) == 3


def test_expired_probe_deadline_blocks_before_finalizer_instead_of_reusing_old_green(
    harness, monkeypatch
):
    paths, _, commands, _ = harness
    assert subject.run_probe_stages(paths, []) == 0
    monkeypatch.setattr(
        subject,
        "verify_deployed",
        lambda m, e, a, now: verify_deployed(m, e, a, now=m.expires_at + timedelta(seconds=1)),
    )
    result = subject.finalize_probe_stages(paths, "completed", [])
    assert all(row.exit_code == 2 for row in result) and len(commands) == 2


def test_existing_probe_output_is_never_replayed_or_taken_as_a_new_run(harness):
    paths, _, commands, _ = harness
    (paths.directory / "probe-protocol34").mkdir()
    assert subject.run_probe_stages(paths, []) == 2 and commands == []
