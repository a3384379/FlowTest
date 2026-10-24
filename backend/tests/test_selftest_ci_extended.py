"""Extension gates require every pack, independent identity checks and exact cleanup."""

import argparse
import importlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts import selftest_ci as driver
from scripts.selftest import ci_extended, ci_extended_reports
from scripts.selftest.io import HarnessError, write_json
from test_selftest_ci_runner_lineage import binding
from test_selftest_review_boundary_verify import FIXTURE, bundle


@pytest.mark.parametrize(
    "module", ["scripts.selftest.run_native_control", "scripts.selftest.run_contract_delta"]
)
def test_cli_failure_after_missing_evidence_preserves_first_failure(tmp_path, monkeypatch, module):
    entry = importlib.import_module(module)
    output = tmp_path / "evidence"
    first = {"failure_codes": ["FIRST_PUBLIC_HTTP_FAILURE"], "outcome": "incomplete"}
    write_json(output / "failure.json", first)
    original = (output / "failure.json").read_bytes()

    def fail(*args):
        raise HarnessError("SELFTEST_SECOND_FAILURE")

    monkeypatch.setattr(entry, "finalize", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "entry",
            "--directory",
            str(tmp_path / "owned"),
            "--output",
            str(output),
            "--finalize-disposable",
        ],
    )
    with pytest.raises(SystemExit) as raised:
        entry.main()
    assert raised.value.code == 2
    assert (output / "failure.json").read_bytes() == original
    assert len(list(output.glob("failure-*.json"))) == 1


def test_saved_green_review_cannot_bypass_independent_recomputation(tmp_path):
    for name in ("manifest.json", "evidence.json", "authority.json"):
        shutil.copyfile(FIXTURE / name, tmp_path / name)
    manifest, evidence, authority = bundle()
    from scripts.selftest.review_boundary_verify import verify

    report = verify(manifest, evidence, authority, now=evidence.collected_at)
    write_json(
        tmp_path / "verification.json", report.model_copy(update={"exit_code": 0, "findings": ()})
    )
    with pytest.raises(HarnessError, match="EXTENDED_REPORT_CHANGED"):
        ci_extended_reports.normalize("review", tmp_path)


@pytest.mark.parametrize(
    "field",
    ["candidate_image_digest", "fixture_image_digest", "source_digest", "dependency_digest"],
)
def test_new_wave_rejects_a_different_build(tmp_path, monkeypatch, field):
    paths = driver.RunPaths.create(tmp_path / "wave")
    original = binding()
    source = tmp_path / "source"
    write_json(source / "stack.json", original)
    write_json(paths.stack / "stack.json", original.model_copy(update={field: "wrong"}))
    monkeypatch.setattr(ci_extended, "_command", lambda *_args, **_kwargs: None)
    with pytest.raises(HarnessError, match="EXTENDED_WAVE_BUILD_CHANGED"):
        ci_extended.start_wave(paths, source, [])


@pytest.mark.parametrize("status", [0, 2])
def test_baseline_pass_does_not_grant_overall_success_without_extensions(
    tmp_path, monkeypatch, status
):
    args = argparse.Namespace(profile="full")
    monkeypatch.setattr(driver, "validate_inputs", lambda _: tmp_path / "ci")
    monkeypatch.setattr(driver, "run_stages", lambda *_: 0)
    order = []

    def finalized(*_args, **kwargs):
        assert kwargs["keep_build_source"] is True
        order.append("baseline-finalized")

    def extensions(*_):
        order.append("extensions")
        return SimpleNamespace(exit_code=status)

    def cleanup(paths):
        assert paths.profile == "standalone"
        order.append("build-source-cleaned")
        return "completed"

    monkeypatch.setattr(driver, "finalize", finalized)
    monkeypatch.setattr(ci_extended, "run", extensions)
    monkeypatch.setattr(driver, "stop_owned_stack", cleanup)
    if status:
        with pytest.raises(driver.CIHarnessError, match="EXTENSIONS_INCOMPLETE"):
            driver._run(args)
    else:
        assert driver._run(args) == 0
    assert order == ["baseline-finalized", "extensions", "build-source-cleaned"]


def test_short_token_stack_is_created_separately_and_removed_on_failure(tmp_path, monkeypatch):
    paths = driver.RunPaths.create(tmp_path / "expiry", "compact")
    calls = []

    def start(selected, source, stages, *, minutes):
        calls.append((selected.stack, minutes))

    monkeypatch.setattr(ci_extended, "start_wave", start)

    def fail(*args, **kwargs):
        raise HarnessError("AUTH_PROBE_FAILURE")

    monkeypatch.setattr(ci_extended, "_command", fail)
    monkeypatch.setattr(
        driver,
        "stop_owned_stack",
        lambda selected: calls.append((selected.stack, "removed")) or "completed",
    )
    with pytest.raises(HarnessError, match="AUTH_PROBE_FAILURE"):
        ci_extended.run_auth(paths, tmp_path / "build", [])
    assert calls == [(paths.stack, 1), (paths.stack, "removed")]


def test_journey_commands_never_reconfigure_after_identity_freeze(tmp_path):
    paths = driver.RunPaths.create(tmp_path / "wave")
    for spec in ci_extended.JOURNEYS:
        command = ci_extended.journey_command(paths, spec)
        assert "scripts.selftest.configured_probes" not in command
        assert "--target-access-token-minutes" not in command
        assert ci_extended.journey_command(paths, spec, final=True) == [
            *command,
            "--finalize-disposable",
        ]


def summary(label, profile):
    return ci_extended_reports.PackSummary(
        label=label,
        expected_count=1,
        observed_ids=(label,),
        exit_code=0,
        reason_codes=(),
        report_sha256="a" * 64,
        source_digest="b" * 64,
        candidate_image_digest="sha256:" + "c" * 64,
        fixture_image_digest="sha256:" + "d" * 64,
        verifier_digest="e" * 64,
        runtime_profile=profile,
    )


@pytest.mark.parametrize("profile", ["full", "compact"])
@pytest.mark.parametrize("failure", ["worker", "cleanup"])
def test_worker_wave_failure_cannot_be_hidden_by_all_other_green_packs(
    tmp_path, monkeypatch, profile, failure
):
    paths = driver.RunPaths.create(tmp_path / "run", profile)
    monkeypatch.setattr(
        ci_extended, "run_wave", lambda *_: tuple(summary(str(i), profile) for i in range(9))
    )
    monkeypatch.setattr(ci_extended, "run_auth", lambda *_: summary("auth", profile))

    def workers(*_):
        if failure == "worker":
            raise HarnessError("ACTUAL_WORKER_FAILURE")
        return summary("workers", profile)

    monkeypatch.setattr(ci_extended, "run_workers", workers)
    monkeypatch.setattr(
        driver,
        "stop_owned_stack",
        lambda selected: (
            "failed"
            if failure == "cleanup" and selected.directory.name == "workers"
            else "completed"
        ),
    )
    monkeypatch.setattr(
        ci_extended,
        "run_product",
        lambda *_: (summary("product", paths.profile), summary("compiler", paths.profile)),
    )
    receipt = ci_extended.run(paths, tmp_path / "source", [])
    assert receipt.exit_code == 2
    if failure == "worker":
        assert receipt.reason_codes == ("ACTUAL_WORKER_FAILURE",)
    else:
        assert receipt.worker_cleanup == "failed"


def test_standalone_does_not_invoke_celery_fault_injection(tmp_path, monkeypatch):
    paths = driver.RunPaths.create(tmp_path / "run", "standalone")
    monkeypatch.setattr(
        ci_extended,
        "run_wave",
        lambda *_: tuple(summary(str(i), "standalone") for i in range(9)),
    )
    monkeypatch.setattr(ci_extended, "run_auth", lambda *_: summary("auth", "standalone"))
    monkeypatch.setattr(
        ci_extended, "run_workers", lambda *_: pytest.fail("Standalone has no Celery worker")
    )
    monkeypatch.setattr(driver, "stop_owned_stack", lambda *_: "completed")
    monkeypatch.setattr(
        ci_extended,
        "run_product",
        lambda *_: (summary("product", paths.profile), summary("compiler", paths.profile)),
    )
    receipt = ci_extended.run(paths, tmp_path / "source", [])
    assert receipt.exit_code == 0
    assert receipt.worker_cleanup == "not_applicable"


def test_worker_fault_failure_always_removes_exact_wave_before_returning(tmp_path, monkeypatch):
    paths = driver.RunPaths.create(tmp_path / "workers", "compact")
    calls = []
    monkeypatch.setattr(ci_extended, "start_wave", lambda *_: None)

    def fail(*_, **__):
        raise HarnessError("WORKER_FAULT_INPUT_INCOMPLETE")

    monkeypatch.setattr(ci_extended, "_command", fail)
    monkeypatch.setattr(
        driver,
        "stop_owned_stack",
        lambda selected: calls.append(selected.stack) or "completed",
    )
    with pytest.raises(HarnessError, match="WORKER_FAULT_INPUT_INCOMPLETE"):
        ci_extended.run_workers(paths, tmp_path / "source", [])
    assert calls == [paths.stack]


@pytest.mark.parametrize("profile", ["standalone", "full", "compact"])
@pytest.mark.parametrize("failure", ["missing_compiler", "product_failure", "cleanup"])
def test_product_or_compiler_failure_blocks_all_other_green_extensions(
    tmp_path, monkeypatch, profile, failure
):
    paths = driver.RunPaths.create(tmp_path / "run", profile)
    monkeypatch.setattr(
        ci_extended, "run_wave", lambda *_: tuple(summary(str(i), profile) for i in range(9))
    )
    monkeypatch.setattr(ci_extended, "run_auth", lambda *_: summary("auth", profile))
    monkeypatch.setattr(ci_extended, "run_workers", lambda *_: summary("workers", profile))

    def product(*_):
        if failure == "product_failure":
            raise HarnessError("ACTUAL_PRODUCT_BOUNDARY_FAILED")
        rows = (summary("product", profile), summary("compiler", profile))
        return rows[:1] if failure == "missing_compiler" else rows

    monkeypatch.setattr(ci_extended, "run_product", product)
    monkeypatch.setattr(
        driver,
        "stop_owned_stack",
        lambda selected: (
            "failed"
            if failure == "cleanup" and selected.directory.name == "product"
            else "completed"
        ),
    )
    receipt = ci_extended.run(paths, tmp_path / "source", [])
    assert receipt.exit_code == 2
    if failure == "cleanup":
        assert receipt.product_cleanup == "failed"
    if failure == "product_failure":
        assert receipt.reason_codes == ("ACTUAL_PRODUCT_BOUNDARY_FAILED",)
