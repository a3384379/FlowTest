"""The trusted CI driver must fail closed without importing candidate host code."""

import argparse
import copy
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts import selftest_ci as driver  # noqa: E402
from scripts.selftest import local_stack  # noqa: E402
from scripts.selftest.io import HarnessError  # noqa: E402


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "blocked", "missing", "incomplete"])
def test_archive_rejects_zero_or_inconsistent_green_reports(tmp_path: Path, mutation: str) -> None:
    from datetime import datetime

    from scripts.selftest.contracts import BatchEvidence, BatchManifest
    from scripts.selftest.verify import verify_batch
    from test_selftest_verification import COLLECTED, evidence_payload, manifest_payload

    source, public = tmp_path / "source", tmp_path / "public"
    source.mkdir()
    public.mkdir()
    manifest = BatchManifest.model_validate(manifest_payload())
    evidence = BatchEvidence.model_validate(evidence_payload())
    report = verify_batch(manifest, evidence, now=datetime.fromisoformat(COLLECTED))
    assert report.exit_code == 0
    (source / "manifest.json").write_text(manifest.model_dump_json())
    (source / "evidence.json").write_text(evidence.model_dump_json())
    (source / "verification.json").write_text(report.model_dump_json())
    for name in ("execution.junit.xml", "verification.junit.xml"):
        (source / name).write_text('<testsuite tests="1"/>')
    assert driver._copy_report(source, public, "baseline").exit_code == 0
    altered = copy.deepcopy(report.model_dump(mode="json"))
    if mutation == "empty":
        altered["scenarios"] = []
    elif mutation == "duplicate":
        altered["scenarios"] *= 2
    elif mutation == "blocked":
        altered["batch_verdict"] = "blocked"
    elif mutation == "missing":
        altered["evidence_integrity"] = "missing"
    else:
        altered["scenarios"][0]["verification_status"] = "incomplete"
    (source / "verification.json").write_text(json.dumps(altered))
    with pytest.raises(driver.CIHarnessError, match="INCOMPLETE_OR_INCONSISTENT"):
        driver._copy_report(source, public, "tampered")
    assert not (public / "tampered-verification.json").exists()


@pytest.mark.parametrize(
    "mutation", ["budget_missing", "wrong_digest", "rejected", "counter", "incomplete", "blocked"]
)
def test_runtime_archive_requires_complete_fixed_variants_and_exact_budget(mutation: str) -> None:
    from datetime import UTC, datetime, timedelta

    from scripts.selftest.runtime_faults import FrozenRuntimeBatch, RuntimePackReport, load_pack

    pack, digest = load_pack(ROOT / "selftest/packs/runtime-faults-v1/expectations.json")
    now = datetime.now(UTC)
    manifest = FrozenRuntimeBatch.model_validate(
        {
            "batch_key": "runtime-" + "1" * 20,
            "pack_digest": digest,
            "driver_digest": "a" * 64,
            "expected_variants": [item.model_dump(mode="json") for item in pack.variants],
            "builds": {"candidate": "sha256:" + "b" * 64, "fixture": "sha256:" + "c" * 64},
            "source_digest": "d" * 64,
            "profile": "compact",
            "nonce": "1" * 32,
            "created_at": now,
            "deadline": now + timedelta(seconds=600),
        }
    )
    report = RuntimePackReport.model_validate(
        {
            "pack_digest": digest,
            "completed_count": 15,
            "verdict": "passed",
            "exit_code": 0,
            "run001_same_frozen_plan_distinct_runs": True,
            "request_count": 36,
            "runtime_profile": "compact",
            "budget": {
                "parent_batch_key": manifest.batch_key,
                "nonce": manifest.nonce,
                "limit": 100,
                "expires_at": manifest.deadline.timestamp(),
                "admitted_count": 36,
                "rejected_count": 0,
                "fixture_digest": digest,
                "registration_epoch": "frozen-epoch",
            },
            "scenarios": [
                {
                    "scenario_id": item.scenario_id,
                    "variant": item.variant,
                    "status": "matched",
                    "native_status": item.native_status,
                    "findings": [],
                }
                for item in pack.variants
            ],
        }
    )
    assert driver.runtime_report_complete(manifest, report)
    altered = report.model_dump(mode="json")
    if mutation == "budget_missing":
        altered["budget"] = None
    elif mutation == "wrong_digest":
        altered["budget"]["fixture_digest"] = "e" * 64
    elif mutation == "rejected":
        altered["budget"]["rejected_count"] = 1
    elif mutation == "counter":
        altered["budget"]["admitted_count"] = 35
    elif mutation == "incomplete":
        altered["completed_count"] = 14
    else:
        altered["verdict"] = "blocked"
    assert not driver.runtime_report_complete(manifest, RuntimePackReport.model_validate(altered))


def arguments(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    values = {
        "candidate": tmp_path / "candidate",
        "directory": tmp_path / "run",
        "tested_sha": "a" * 40,
        "observer_sha": "b" * 40,
        "allow_dirty": False,
        "bootstrap_review": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_execution_environment_excludes_ci_and_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    monkeypatch.setenv("GITHUB_TOKEN", "secret-value")
    monkeypatch.setenv("FLOWTEST_SELFTEST_OBSERVER_TOKEN", "secret-value")
    environment = driver.execution_environment(ROOT)
    assert all("secret-value" not in value for value in environment.values())
    assert environment["PYTHONPATH"] == f"{ROOT}:{ROOT / 'backend'}"


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"allow_dirty": True}, "DIRTY_ONLY_FOR_BOOTSTRAP"),
        ({"candidate": ROOT}, "INDEPENDENT_OBSERVER_REQUIRED"),
    ],
)
def test_normal_ci_cannot_silently_fall_back_to_candidate_observer(
    tmp_path: Path, overrides: dict[str, object], code: str
) -> None:
    with pytest.raises(driver.CIHarnessError, match=code):
        driver.validate_inputs(arguments(tmp_path, **overrides))


def test_exact_checkouts_are_verified_before_any_container_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = Mock(side_effect=driver.CIHarnessError("SELFTEST_CI_CHECKOUT_MISMATCH"))
    monkeypatch.setattr(driver, "require_checkout", check)
    with pytest.raises(driver.CIHarnessError, match="CHECKOUT_MISMATCH"):
        driver.validate_inputs(arguments(tmp_path))
    assert check.call_count == 1
    assert not (tmp_path / "run").exists()


def test_missing_or_corrupt_verification_is_blocked_and_private_files_are_not_archived(
    tmp_path: Path,
) -> None:
    reports, public = tmp_path / "reports", tmp_path / "public"
    for index in (1, 2):
        path = reports / "fixed-core" / f"round-{index}"
        path.mkdir(parents=True)
        (path / "private.env").write_text("SECRET=do-not-export")
        (path / "mcp.stderr").write_text("do-not-export")
    (reports / "fixed-core/round-2/verification.json").write_text("{}")
    results = driver.archive_summaries(reports, public)
    assert len(results) == 2 and all(item.exit_code == 2 for item in results)
    assert list(public.iterdir()) == []


def test_cleanup_failure_produces_receipt_and_cannot_be_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = driver.RunPaths.create(tmp_path / "run")
    monkeypatch.setattr(driver, "stop_owned_stack", lambda _: "failed")
    with pytest.raises(driver.CIHarnessError, match="INCOMPLETE_OR_CLEANUP_FAILED"):
        driver.finalize(arguments(tmp_path), paths, [driver.StageResult("fixed-core", 0)])
    receipt = json.loads((paths.public / "ci-receipt.json").read_text())
    assert receipt["cleanup"] == "failed"
    assert receipt["formal_required_gate_published"] is False
    assert receipt["provenance"] == "local_untrusted"


def test_candidate_build_hash_includes_deletions_migrations_and_lock(tmp_path: Path) -> None:
    for directory in ("backend/app", "backend/migrations", "mock-target/app"):
        (tmp_path / directory).mkdir(parents=True)
    for name in (
        "backend/app/a.py",
        "backend/migrations/a.py",
        "mock-target/app/a.py",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/alembic.ini",
        "mock-target/pyproject.toml",
        "mock-target/uv.lock",
    ):
        (tmp_path / name).write_text("initial")
    before = local_stack.source_digest(tmp_path)
    (tmp_path / "backend/migrations/a.py").write_text("migration-changed")
    changed = local_stack.source_digest(tmp_path)
    assert before != changed
    (tmp_path / "backend/app/a.py").unlink()
    assert changed != local_stack.source_digest(tmp_path)
    (tmp_path / "mock-target/app/link.py").symlink_to(tmp_path / "backend/uv.lock")
    with pytest.raises(HarnessError, match="SYMLINK"):
        local_stack.source_digest(tmp_path)


def test_ci_uses_distinct_checkouts_and_only_public_upload_paths() -> None:
    document = yaml.safe_load((ROOT / ".github/workflows/compose-ci.yml").read_text())
    steps = document["jobs"]["selftest"]["steps"]
    checkouts = [step for step in steps if "checkout@" in step.get("uses", "")]
    assert [step["with"]["path"] for step in checkouts] == ["candidate", "trusted"]
    assert all(step["with"]["persist-credentials"] is False for step in checkouts)
    run = next(step for step in steps if "Run reviewed" in step.get("name", ""))
    assert run["working-directory"] == "trusted"
    upload = next(step for step in steps if "upload-artifact@" in step.get("uses", ""))
    paths = upload["with"]["path"].splitlines()
    assert paths == [
        "${{ runner.temp }}/native-selftest/public/",
        "${{ runner.temp }}/native-selftest/run/public/",
        "${{ runner.temp }}/native-selftest/run/extensions/public/",
        "${{ runner.temp }}/native-selftest/run/expiry/public/",
        "${{ runner.temp }}/native-selftest/run/workers/public/",
        "${{ runner.temp }}/native-selftest/run/product/public/",
    ]
    assert "private" not in upload["with"]["path"]
    regression = yaml.safe_load((ROOT / ".github/workflows/full-regression.yml").read_text())
    trigger = regression.get("on", regression.get(True))
    assert trigger["schedule"] == [{"cron": "0 3 * * 1"}]


def test_finalizer_failure_cannot_be_hidden_by_a_preexisting_passed_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = driver.RunPaths.create(tmp_path / "run")
    manifest = paths.reports / "native-api/round-1/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}")
    monkeypatch.setattr(driver, "stop_owned_stack", lambda _: "completed")

    def summaries(_: Path, public: Path) -> list[driver.BatchSummary]:
        public.mkdir(parents=True, exist_ok=True)
        return [driver.BatchSummary("native-api-round-1", 0, "passed")]

    monkeypatch.setattr(driver, "archive_summaries", summaries)
    monkeypatch.setattr(driver, "command", lambda *args, **kwargs: 2)
    with pytest.raises(driver.CIHarnessError, match="INCOMPLETE_OR_CLEANUP_FAILED"):
        driver.finalize(arguments(tmp_path), paths, [])
    receipt = json.loads((paths.public / "ci-receipt.json").read_text())
    assert {"stage": "native-api-after-disposal", "exit_code": 2} in receipt["stages"]
    assert receipt["negative_probes"] == [
        {"label": "protocol34", "exit_code": 2, "verdict": "blocked", "batch_key": None},
        {"label": "governance42", "exit_code": 2, "verdict": "blocked", "batch_key": None},
    ]


def test_profile_and_source_cleanup_preserve_separate_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        driver,
        "archive_observer_canaries",
        lambda _: driver.BatchSummary("observer-canaries", 0, "passed"),
    )
    monkeypatch.setattr(
        driver,
        "_probe_summaries",
        lambda *_: (
            driver.BatchSummary("protocol34", 0, "passed"),
            driver.BatchSummary("governance42", 0, "passed"),
        ),
    )
    paths = driver.RunPaths.create(tmp_path / "run", "compact")
    for directory in (paths.stack, paths.directory / "stack"):
        directory.mkdir()
        (directory / "ownership.json").write_text("{}")
    calls: list[tuple[list[str], Path]] = []

    def command(arguments: list[str], *, log: Path, timeout: int) -> int:
        calls.append((arguments, log))
        return 0

    monkeypatch.setattr(driver, "command", command)
    monkeypatch.setattr(
        driver,
        "archive_runtime_faults",
        lambda _: driver.BatchSummary("runtime-faults", 0, "passed"),
    )

    def summaries(_: Path, public: Path) -> list[driver.BatchSummary]:
        public.mkdir(parents=True, exist_ok=True)
        return [
            driver.BatchSummary(label, 0, "passed")
            for label in (
                "fixed-core-round-1",
                "extended-core-round-1",
                "engine-additional-round-1",
                "mcp-core-round-1",
                "mcp-core-round-2",
                "native-api-round-1",
                "engine-golden-round-1",
                "supplemental-api-round-1",
                "s5-native-round-1",
                "s5-product-files-round-1",
            )
        ]

    monkeypatch.setattr(driver, "archive_summaries", summaries)
    driver.finalize(arguments(tmp_path), paths, [])
    assert [call[0][2] for call in calls] == [
        "scripts.selftest.profile_stack",
        "scripts.selftest.local_stack",
    ]
    assert [call[1].name for call in calls] == ["cleanup-compact.log", "cleanup-standalone.log"]


def test_a_successful_subset_cannot_hide_an_absent_required_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = driver.RunPaths.create(tmp_path / "run")
    monkeypatch.setattr(driver, "stop_owned_stack", lambda _: "completed")

    def summaries(_: Path, public: Path) -> list[driver.BatchSummary]:
        public.mkdir(parents=True, exist_ok=True)
        return [driver.BatchSummary("fixed-core-round-1", 0, "passed")]

    monkeypatch.setattr(driver, "archive_summaries", summaries)
    with pytest.raises(driver.CIHarnessError, match="INCOMPLETE_OR_CLEANUP_FAILED"):
        driver.finalize(arguments(tmp_path), paths, [])
    receipt = json.loads((paths.public / "ci-receipt.json").read_text())
    assert receipt["missing_batches"] == [
        "engine-additional-round-1",
        "engine-golden-round-1",
        "extended-core-round-1",
        "mcp-core-round-1",
        "mcp-core-round-2",
        "native-api-round-1",
        "s5-native-round-1",
        "s5-product-files-round-1",
        "supplemental-api-round-1",
    ]


def test_compact_requires_runtime_fault_evidence_even_if_every_native_round_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        driver,
        "_probe_summaries",
        lambda *_: (
            driver.BatchSummary("protocol34", 0, "passed"),
            driver.BatchSummary("governance42", 0, "passed"),
        ),
    )
    paths = driver.RunPaths.create(tmp_path / "run", "compact")
    monkeypatch.setattr(driver, "stop_owned_stack", lambda _: "completed")

    def summaries(_: Path, public: Path) -> list[driver.BatchSummary]:
        public.mkdir(parents=True, exist_ok=True)
        return [
            driver.BatchSummary(label, 0, "passed")
            for label in (
                "fixed-core-round-1",
                "extended-core-round-1",
                "engine-additional-round-1",
                "mcp-core-round-1",
                "mcp-core-round-2",
                "native-api-round-1",
                "engine-golden-round-1",
                "supplemental-api-round-1",
                "s5-native-round-1",
                "s5-product-files-round-1",
            )
        ]

    monkeypatch.setattr(driver, "archive_summaries", summaries)
    with pytest.raises(driver.CIHarnessError, match="INCOMPLETE_OR_CLEANUP_FAILED"):
        driver.finalize(arguments(tmp_path), paths, [])
    receipt = json.loads((paths.public / "ci-receipt.json").read_text())
    assert receipt["missing_batches"] == []
    assert receipt["runtime_faults"] == {
        "label": "runtime-faults",
        "exit_code": 2,
        "verdict": "blocked",
        "batch_key": None,
    }
    standalone = driver.archive_runtime_faults(driver.RunPaths.create(tmp_path / "standalone"))
    assert standalone is not None and standalone.exit_code == 2


def test_required_p0_supplements_cannot_be_satisfied_by_old_six_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        driver,
        "_probe_summaries",
        lambda *_: (
            driver.BatchSummary("protocol34", 0, "passed"),
            driver.BatchSummary("governance42", 0, "passed"),
        ),
    )
    paths = driver.RunPaths.create(tmp_path / "run")
    monkeypatch.setattr(driver, "stop_owned_stack", lambda _: "completed")

    def historical(_: Path, public: Path) -> list[driver.BatchSummary]:
        public.mkdir(parents=True, exist_ok=True)
        return [
            driver.BatchSummary(label, 0, "passed")
            for label in (
                "fixed-core-round-1",
                "extended-core-round-1",
                "engine-additional-round-1",
                "mcp-core-round-1",
                "mcp-core-round-2",
                "native-api-round-1",
            )
        ]

    monkeypatch.setattr(driver, "archive_summaries", historical)
    with pytest.raises(driver.CIHarnessError, match="INCOMPLETE_OR_CLEANUP_FAILED"):
        driver.finalize(arguments(tmp_path), paths, [])
    receipt = json.loads((paths.public / "ci-receipt.json").read_text())
    assert receipt["missing_batches"] == [
        "engine-golden-round-1",
        "s5-native-round-1",
        "s5-product-files-round-1",
        "supplemental-api-round-1",
    ]


@pytest.mark.parametrize(
    "probe_labels", [(), ("protocol34",), ("protocol34", "protocol34"), ("protocol34", "other")]
)
def test_native_success_cannot_replace_exact_negative_probe_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe_labels: tuple[str, ...]
) -> None:
    paths = driver.RunPaths.create(tmp_path / "run")
    monkeypatch.setattr(driver, "stop_owned_stack", lambda _: "completed")
    monkeypatch.setattr(
        driver,
        "_probe_summaries",
        lambda *_: tuple(driver.BatchSummary(label, 0, "passed") for label in probe_labels),
    )

    def successful(_: Path, public: Path) -> list[driver.BatchSummary]:
        public.mkdir(parents=True, exist_ok=True)
        return [
            driver.BatchSummary(label, 0, "passed")
            for label in (
                "fixed-core-round-1",
                "extended-core-round-1",
                "engine-additional-round-1",
                "engine-golden-round-1",
                "mcp-core-round-1",
                "mcp-core-round-2",
                "native-api-round-1",
                "supplemental-api-round-1",
                "s5-native-round-1",
                "s5-product-files-round-1",
            )
        ]

    monkeypatch.setattr(driver, "archive_summaries", successful)
    with pytest.raises(driver.CIHarnessError, match="INCOMPLETE_OR_CLEANUP_FAILED"):
        driver.finalize(arguments(tmp_path), paths, [])
    receipt = json.loads((paths.public / "ci-receipt.json").read_text())
    assert receipt["missing_batches"] == []
    assert receipt["formal_required_gate_published"] is False
