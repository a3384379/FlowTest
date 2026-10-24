"""Grant recreation is allowed only before collection; O cannot reuse stale success."""

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest import configured_probe_observer as observer
from scripts.selftest import configured_probes as group
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import StackBinding
from test_selftest_ci_runner_lineage import binding
from test_selftest_review_boundary_verify import bundle


@dataclass(frozen=True)
class Prepared:
    binding: StackBinding
    manifest: object


@pytest.mark.asyncio
async def test_all_grants_complete_before_any_final_identity_is_frozen(tmp_path, monkeypatch):
    manifest, _, _ = bundle()
    original = binding()
    order = []
    selected = []
    stack = tmp_path / "stack"
    stack.mkdir()

    def prepare(name):
        async def call(directory, output):
            order.append(name)
            current = original.model_copy(update={"runner_container_id": str(len(order)) * 64})
            write_json(stack / "stack.json", current)
            result = Prepared(current, manifest)
            selected.append(result)
            return result

        return call

    for name in ("fault", "quality", "review"):
        monkeypatch.setattr(group, "prepare_" + name, prepare(name))
    monkeypatch.setattr(group, "verify_binding", lambda *_: None)
    result = await group.prepare_all(stack, tmp_path / "output")
    assert order == ["fault", "quality", "review"]
    assert [r.binding.runner_container_id for r in selected] == ["1" * 64, "2" * 64, "3" * 64]
    assert all(
        r.binding.runner_container_id == "3" * 64
        for r in (result.fault, result.quality, result.review)
    )
    receipt = read_json(tmp_path / "output/collection-binding.json")
    assert receipt["phase"] == "all_grants_installed_before_collection"


@pytest.mark.parametrize(
    "field",
    [
        "target_container_id",
        "nonce",
        "runner_volume",
        "source_digest",
        "candidate_image_digest",
        "runtime_profile",
        "target_url",
    ],
)
def test_grant_cohort_rejects_every_non_runner_identity_change(field):
    original = binding()
    changed = original.model_copy(update={field: "changed"})
    with pytest.raises(HarnessError, match="CONFIGURED_GROUP_STACK_DRIFT"):
        group.require_same_owned_stack(original, changed)


@pytest.mark.parametrize("mode", ["missing", "false_success", "wrong_identity"])
def test_observer_removes_old_green_and_rejects_inconsistent_child(tmp_path, monkeypatch, mode):
    manifest, _, _ = bundle()
    spec = observer.SPECS[2]
    ids = tuple(r.scenario_id for r in manifest.scenarios)
    report = observer.ConfiguredReport(
        batch_key=manifest.batch_key,
        exit_code=0,
        findings=(),
        scenarios=tuple(
            observer.Verdict(scenario_id=i, verification_status="matched", findings=()) for i in ids
        ),
        claim=spec.claim,
    )
    destination = tmp_path / "configured-o"
    write_json(destination / "verification.json", report)
    for name in ("execution.junit.xml", "verification.junit.xml"):
        (destination / name).write_text("old green")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-o")
    monkeypatch.setenv("FLOWTEST_TOKEN", "must-not-reach-o")

    def child(command, **kwargs):
        assert set(kwargs["env"]) == {"PATH", "PYTHONPATH", "PYTHONUNBUFFERED"}
        assert read_json(destination / "verification.json")["exit_code"] == 2
        assert not (destination / "execution.junit.xml").exists()
        if mode != "missing":
            payload = json.loads(report.model_dump_json())
            if mode == "wrong_identity":
                payload["batch_key"] = "wrong"
            else:
                payload["scenarios"][0]["verification_status"] = "incomplete"
            write_json(destination / "verification.json", payload)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(observer.subprocess, "run", child)
    result = observer.observe(
        spec,
        tmp_path,
        batch_key=manifest.batch_key,
        scenario_ids=ids,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    assert result.exit_code == 2
    assert result.findings[0].code == "CONFIGURED_OBSERVER_PROCESS_UNAVAILABLE"


@pytest.mark.parametrize("existing", [False, True])
def test_group_cli_projects_safe_failure_without_overwriting_existing_output(
    tmp_path, monkeypatch, capsys, existing
):
    output = tmp_path / "group"
    prior = group.GroupResult(exit_code=0, reports=())
    if existing:
        write_json(output / "group-verification.json", prior)
    original = (output / "group-verification.json").read_bytes() if existing else None

    async def rejected(*_):
        if existing:
            raise FileExistsError("private-value")
        raise HarnessError("SELFTEST_HTTP_422:SERVICE_ACCOUNT_EXPIRY_INVALID:trace=private-value")

    monkeypatch.setattr(group, "run", rejected)
    monkeypatch.setattr(
        sys, "argv", ["configured", "--directory", str(tmp_path), "--output", str(output)]
    )
    assert group.main() == (1 if existing else 2)
    assert "private-value" not in capsys.readouterr().out
    if existing:
        assert (output / "group-verification.json").read_bytes() == original
    else:
        report = group.GroupResult.model_validate(read_json(output / "group-verification.json"))
        assert report.exit_code == 2 and not report.reports
        assert report.reason_codes == ("SELFTEST_HTTP_422_SERVICE_ACCOUNT_EXPIRY_INVALID",)
