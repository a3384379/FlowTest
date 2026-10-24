"""Run trusted H/O code against candidate-only container sources, then archive safe summaries.

The caller selects this file from the reviewed base revision. Candidate Python is
never placed on the host import path. Bootstrap review may use candidate H/O, but
is labelled separately and cannot publish a Required Gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]


class CIHarnessError(RuntimeError):
    """A bounded CI-stage code, never an arbitrary subprocess payload."""


@dataclass(frozen=True)
class BatchSummary:
    label: str
    exit_code: int
    verdict: str
    batch_key: str | None = None


@dataclass(frozen=True)
class StageResult:
    stage: str
    exit_code: int


@dataclass(frozen=True)
class RunPaths:
    directory: Path
    stack: Path
    reports: Path
    public: Path
    python: str
    profile: Literal["standalone", "full", "compact"] = "standalone"

    @classmethod
    def create(
        cls, directory: Path, profile: Literal["standalone", "full", "compact"] = "standalone"
    ) -> RunPaths:
        directory.mkdir(parents=True, mode=0o700)
        return cls(
            directory,
            directory / ("stack" if profile == "standalone" else "profile-stack"),
            directory / "reports",
            directory / "public",
            str(ROOT / "backend/.venv/bin/python"),
            profile,
        )


def require_checkout(path: Path, expected_sha: str, *, allow_dirty: bool = False) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise CIHarnessError("SELFTEST_CI_SHA_INVALID")
    git = shutil.which("git")
    if git is None:
        raise CIHarnessError("SELFTEST_CI_GIT_UNAVAILABLE")
    actual = subprocess.check_output(  # noqa: S603 - read-only git, SHA and checkout fixed by CI
        [git, "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != expected_sha:
        raise CIHarnessError("SELFTEST_CI_CHECKOUT_MISMATCH")
    if (
        not allow_dirty
        and subprocess.check_output(  # noqa: S603 - read-only status in frozen checkout
            [git, "-C", str(path), "status", "--porcelain"], text=True
        ).strip()
    ):
        raise CIHarnessError("SELFTEST_CI_DIRTY_CHECKOUT")


def execution_environment(trusted: Path) -> dict[str, str]:
    allowed = (
        "PATH",
        "HOME",
        "TMPDIR",
        "SYSTEMROOT",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(
        PYTHONPATH=os.pathsep.join((str(trusted), str(trusted / "backend"))),
        PYTHONUNBUFFERED="1",
    )
    return environment


def command(arguments: list[str], *, log: Path, timeout: int) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as output:
        os.chmod(log, 0o600)
        result = subprocess.run(  # noqa: S603 - trusted executable and explicit argument arrays
            arguments,
            cwd=ROOT,
            env=execution_environment(ROOT),
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    return result.returncode


def _copy_report(directory: Path, public: Path, label: str) -> BatchSummary:
    from scripts.selftest.contracts import BatchManifest, VerificationReport

    manifest = BatchManifest.model_validate_json((directory / "manifest.json").read_bytes())
    report = VerificationReport.model_validate_json((directory / "verification.json").read_bytes())
    if (manifest.batch_key, manifest.pack_digest) != (report.batch_key, report.pack_digest):
        raise CIHarnessError("SELFTEST_CI_REPORT_IDENTITY_MISMATCH")
    expected = [(item.scenario_id, item.variant_key) for item in manifest.scenarios]
    observed = [(item.scenario_id, item.variant_key) for item in report.scenarios]
    if expected != observed or (
        report.exit_code == 0
        and (
            report.batch_verdict != "passed"
            or report.evidence_integrity != "complete"
            or report.findings
            or any(
                item.verification_status != "matched" or item.findings for item in report.scenarios
            )
        )
    ):
        raise CIHarnessError("SELFTEST_CI_REPORT_INCOMPLETE_OR_INCONSISTENT")
    identity = {
        "batch_key": manifest.batch_key,
        "pack_digest": manifest.pack_digest,
        "policy_digest": manifest.policy_digest,
        "builds": manifest.builds.model_dump(mode="json"),
        "verification_scope": manifest.verification_scope,
        "expected_count": len(manifest.expected_scenario_set),
        "required_count": len(manifest.required_scenario_set),
        "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
        "evidence_sha256": hashlib.sha256((directory / "evidence.json").read_bytes()).hexdigest(),
    }
    (public / f"{label}-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    # Verification reports contain frozen synthetic expectations and bounded
    # statuses/digests; never copy raw MCP stderr, env, tool payloads or captures.
    (public / f"{label}-verification.json").write_text(report.model_dump_json(indent=2) + "\n")
    for name in ("execution.junit.xml", "verification.junit.xml"):
        source = directory / name
        if source.stat().st_size > 1024 * 1024:
            raise CIHarnessError("SELFTEST_CI_JUNIT_SIZE_LIMIT")
        shutil.copyfile(source, public / f"{label}-{name}")
    return BatchSummary(label, report.exit_code, report.batch_verdict, manifest.batch_key)


def archive_summaries(reports: Path, public: Path) -> list[BatchSummary]:
    public.mkdir(parents=True, exist_ok=True)
    results: list[BatchSummary] = []
    directories = sorted(reports.glob("*/round-*"))
    if len(directories) > 10:
        raise CIHarnessError("SELFTEST_CI_REPORT_COUNT_LIMIT")
    for directory in directories:
        label = f"{directory.parent.name}-{directory.name}"
        if not (directory / "verification.json").exists():
            results.append(BatchSummary(label, 2, "blocked"))
            continue
        try:
            results.append(_copy_report(directory, public, label))
        except (ValueError, OSError, CIHarnessError):
            results.append(BatchSummary(label, 2, "blocked"))
    return results


def validate_inputs(arguments: argparse.Namespace) -> Path:
    candidate, directory = Path(arguments.candidate).resolve(), Path(arguments.directory).resolve()
    if directory.exists():
        raise CIHarnessError("SELFTEST_CI_DIRECTORY_ALREADY_USED")
    if arguments.allow_dirty and not arguments.bootstrap_review:
        raise CIHarnessError("SELFTEST_CI_DIRTY_ONLY_FOR_BOOTSTRAP")
    if not arguments.bootstrap_review and candidate == ROOT:
        raise CIHarnessError("SELFTEST_CI_INDEPENDENT_OBSERVER_REQUIRED")
    require_checkout(candidate, arguments.tested_sha, allow_dirty=arguments.allow_dirty)
    require_checkout(ROOT, arguments.observer_sha, allow_dirty=arguments.allow_dirty)
    if not (ROOT / "scripts/selftest/verify.py").is_file():
        raise CIHarnessError("SELFTEST_CI_TRUSTED_OBSERVER_UNAVAILABLE")
    return directory


def run_stages(arguments: argparse.Namespace, paths: RunPaths, stages: list[StageResult]) -> int:
    start = [
        paths.python,
        "-m",
        "scripts.selftest.local_stack",
        "start",
        "--directory",
        str(paths.directory / "stack"),
        "--runtime-image",
        arguments.runtime_image,
        "--candidate-source",
        str(arguments.candidate.resolve()),
    ]
    status = command(start, log=paths.directory / "private-logs/start.log", timeout=900)
    stages.append(StageResult("start", status))
    if status:
        return status
    if paths.profile != "standalone":
        status = command(
            [
                paths.python,
                "-m",
                "scripts.selftest.profile_stack",
                "start",
                "--directory",
                str(paths.stack),
                "--source-stack-directory",
                str(paths.directory / "stack"),
                "--profile",
                paths.profile,
            ],
            log=paths.directory / "private-logs/profile-start.log",
            timeout=900,
        )
        stages.append(StageResult(f"start-{paths.profile}", status))
        if status:
            return status
    for suite, rounds in (
        ("fixed-core", 1),
        ("extended-core", 1),
        ("engine-golden", 1),
        ("mcp-core", 2),
    ):
        status = command(
            [
                paths.python,
                "-m",
                "scripts.selftest.run",
                "--directory",
                str(paths.stack),
                "--output-dir",
                str(paths.reports / suite),
                "--suite",
                suite,
                "--transport",
                "stdio",
                "--rounds",
                str(rounds),
            ],
            log=paths.directory / f"private-logs/{suite}.log",
            timeout=1500,
        )
        stages.append(StageResult(suite, status))
        if status:
            return status
    status = run_observer_canaries(paths, stages)
    if status:
        return status
    status = command(
        [
            paths.python,
            "-m",
            "scripts.selftest.run_runtime_faults",
            "--directory",
            str(paths.stack),
            "--output-dir",
            str(paths.directory / "runtime-faults"),
        ],
        log=paths.directory / "private-logs/runtime-faults.log",
        timeout=660,
    )
    stages.append(StageResult("runtime-faults", status))
    if status:
        return status
    from scripts.selftest.ci_probes import run_probe_stages

    status = run_probe_stages(paths, stages)
    if status:
        return status
    # Probe grants recreate the owned runner. Freeze disposal identities only
    # after both configurations have completed, preserving their exact IDs.
    return run_disposable_stages(paths, stages)


def run_observer_canaries(paths: RunPaths, stages: list[StageResult]) -> int:
    status = command(
        [
            paths.python,
            "-m",
            "scripts.selftest.canary_replay",
            "--reports",
            str(paths.reports),
            "--output",
            str(paths.directory / "observer-canaries"),
            "--profile",
            paths.profile,
        ],
        log=paths.directory / "private-logs/observer-canaries.log",
        timeout=180,
    )
    stages.append(StageResult("observer-canaries", status))
    return status


def run_disposable_stages(paths: RunPaths, stages: list[StageResult]) -> int:
    for suite in (
        "engine-additional",
        "native-api",
        "supplemental-api",
        "s5-native",
        "s5-product-files",
    ):
        status = command(
            round_command(paths, suite),
            log=paths.directory / f"private-logs/{suite}.log",
            timeout=700,
        )
        stages.append(StageResult(f"{suite}-before-disposal", status))
        # The post-stop verifier resolves only the owned disposal receipt.
        # Other findings remain in the immutable observation and cannot pass.
        if status not in {0, 2}:
            return status
    return 0


def round_command(paths: RunPaths, suite: str, *, finalize_disposable: bool = False) -> list[str]:
    result = [
        paths.python,
        "-m",
        "scripts.selftest.run",
        "--directory",
        str(paths.stack),
        "--output-dir",
        str(paths.reports / suite),
        "--suite",
        suite,
        "--rounds",
        "1",
    ]
    if finalize_disposable:
        result.append("--finalize-disposable")
    return result


def stop_owned_stack(paths: RunPaths) -> Literal["completed", "failed", "not_started"]:
    if not (paths.stack / "ownership.json").exists():
        return "not_started"
    try:
        status = command(
            [
                paths.python,
                "-m",
                "scripts.selftest.local_stack"
                if paths.profile == "standalone"
                else "scripts.selftest.profile_stack",
                "stop",
                "--directory",
                str(paths.stack),
            ],
            log=paths.directory / f"private-logs/cleanup-{paths.profile}.log",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return "failed"
    return "completed" if status == 0 else "failed"


def _probe_summaries(
    paths: RunPaths, cleanup: str, stages: list[StageResult]
) -> tuple[BatchSummary, ...]:
    from scripts.selftest.ci_probes import finalize_probe_stages

    return finalize_probe_stages(paths, cleanup, stages)


def _complete_probes(probes: tuple[BatchSummary, ...]) -> bool:
    return (
        len(probes) == 2
        and {item.label for item in probes} == {"protocol34", "governance42"}
        and all(item.exit_code == 0 and item.verdict == "passed" for item in probes)
    )


def finalize(
    arguments: argparse.Namespace,
    paths: RunPaths,
    stages: list[StageResult],
    *,
    keep_build_source: bool = False,
) -> None:
    cleanup = stop_owned_stack(paths)
    if paths.profile != "standalone" and not keep_build_source:
        base_cleanup = stop_owned_stack(
            replace(paths, stack=paths.directory / "stack", profile="standalone")
        )
        if base_cleanup != "completed":
            cleanup = "failed"
    finalizer_status = finalize_disposals(paths, cleanup, stages)
    probes = _probe_summaries(paths, cleanup, stages)
    summary = archive_summaries(paths.reports, paths.public)
    runtime = archive_runtime_faults(paths)
    canaries = archive_observer_canaries(paths)
    expected = {
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
    }
    actual = {item.label for item in summary}
    receipt = {
        "schema_version": "flowtest-ci-selftest-v1",
        "scope": "baseline_deployment_packs_only",
        "runtime_profile": paths.profile,
        "tested_sha": arguments.tested_sha,
        "observer_sha": arguments.observer_sha,
        "source_kind": "bootstrap_review" if arguments.bootstrap_review else "trusted_revision",
        "provenance": "local_untrusted",
        "completed_at": datetime.now(UTC).isoformat(),
        "stages": [asdict(stage) for stage in stages],
        "cleanup": cleanup,
        "batches": [asdict(batch) for batch in summary],
        "negative_probes": [asdict(probe) for probe in probes],
        "runtime_faults": None if runtime is None else asdict(runtime),
        "observer_canaries": None if canaries is None else asdict(canaries),
        "missing_batches": sorted(expected - actual),
        "unexpected_batches": sorted(actual - expected),
        "formal_required_gate_published": False,
    }
    (paths.public / "ci-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if (
        finalizer_status
        or cleanup != "completed"
        or not summary
        or not _complete_probes(probes)
        or actual != expected
        or len(summary) != len(actual)
        or any(item.exit_code for item in summary)
        or canaries is None
        or canaries.exit_code != 0
        or runtime is None
        or runtime.exit_code != 0
    ):
        raise CIHarnessError("SELFTEST_CI_INCOMPLETE_OR_CLEANUP_FAILED")


def archive_observer_canaries(paths: RunPaths) -> BatchSummary | None:
    from scripts.selftest.canary_replay import recheck
    from scripts.selftest.io import HarnessError, write_json

    try:
        report = recheck(paths.reports, paths.directory / "observer-canaries", paths.profile)
        safe_hashes = {
            Path(path).relative_to(paths.reports.resolve()).as_posix(): digest
            for path, digest in report.source_hashes.items()
        }
        paths.public.mkdir(parents=True, exist_ok=True)
        write_json(
            paths.public / "observer-canaries-verification.json",
            report.model_copy(update={"source_hashes": safe_hashes}),
        )
        return BatchSummary("observer-canaries", 0, "passed")
    except (HarnessError, ValueError, OSError):
        return None


def archive_runtime_faults(paths: RunPaths) -> BatchSummary | None:
    from scripts.selftest.runtime_faults import FrozenRuntimeBatch, RuntimePackReport

    source = paths.directory / "runtime-faults"
    try:
        manifest = FrozenRuntimeBatch.model_validate_json((source / "manifest.json").read_bytes())
        report = RuntimePackReport.model_validate_json((source / "verification.json").read_bytes())
        expected = [(item.scenario_id, item.variant) for item in manifest.expected_variants]
        observed = [(item.scenario_id, item.variant) for item in report.scenarios]
        if (
            manifest.pack_digest != report.pack_digest
            or manifest.profile != paths.profile
            or report.runtime_profile != paths.profile
            or len(set(expected)) != 15
            or expected != observed
            or (report.exit_code == 0 and not runtime_report_complete(manifest, report))
        ):
            raise CIHarnessError("SELFTEST_CI_RUNTIME_FAULT_IDENTITY_MISMATCH")
        identity = {
            "batch_key": manifest.batch_key,
            "pack_digest": manifest.pack_digest,
            "driver_digest": manifest.driver_digest,
            "builds": manifest.builds.model_dump(mode="json"),
            "source_digest": manifest.source_digest,
            "runtime_profile": manifest.profile,
            "expected_count": len(expected),
            "manifest_sha256": hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest(),
        }
        (paths.public / "runtime-faults-identity.json").write_text(
            json.dumps(identity, indent=2) + "\n"
        )
        (paths.public / "runtime-faults-verification.json").write_text(
            report.model_dump_json(indent=2) + "\n"
        )
        for name in ("execution.junit.xml", "verification.junit.xml"):
            if (source / name).stat().st_size > 1024 * 1024:
                raise CIHarnessError("SELFTEST_CI_JUNIT_SIZE_LIMIT")
            shutil.copyfile(source / name, paths.public / ("runtime-faults-" + name))
        return BatchSummary("runtime-faults", report.exit_code, report.verdict, manifest.batch_key)
    except (ValueError, OSError, CIHarnessError):
        return BatchSummary("runtime-faults", 2, "blocked")


def runtime_report_complete(manifest: object, report: object) -> bool:
    from scripts.selftest.runtime_faults import FrozenRuntimeBatch, RuntimePackReport
    from scripts.selftest.standalone_runtime_gate import gate_findings

    frozen = FrozenRuntimeBatch.model_validate(manifest)
    observed = RuntimePackReport.model_validate(report)
    budget = observed.budget
    return bool(
        observed.verdict == "passed"
        and observed.completed_count == 15
        and observed.run001_same_frozen_plan_distinct_runs
        and not observed.reason_codes
        and not gate_findings(frozen, observed.standalone_gates)
        and all(item.status == "matched" and not item.findings for item in observed.scenarios)
        and budget is not None
        and budget.parent_batch_key == frozen.batch_key
        and budget.nonce == frozen.nonce
        and budget.limit == 100
        and budget.expires_at == frozen.deadline.timestamp()
        and budget.admitted_count == observed.request_count <= 100
        and budget.rejected_count == 0
        # This pack registers its frozen fixture configuration digest; the
        # concrete M image is independently pinned in frozen.builds.fixture.
        and budget.fixture_digest == frozen.pack_digest
    )


def finalize_disposals(
    paths: RunPaths,
    cleanup: Literal["completed", "failed", "not_started"],
    stages: list[StageResult],
) -> int:
    if cleanup != "completed":
        return 2
    statuses = []
    for suite in (
        "engine-additional",
        "native-api",
        "supplemental-api",
        "s5-native",
        "s5-product-files",
    ):
        if not (paths.reports / suite / "round-1/manifest.json").exists():
            continue
        status = command(
            round_command(paths, suite, finalize_disposable=True),
            log=paths.directory / f"private-logs/{suite}-disposal.log",
            timeout=60,
        )
        statuses.append(status)
        stages.append(StageResult(f"{suite}-after-disposal", status))
    return max(statuses, default=0)


def _run(arguments: argparse.Namespace) -> int:
    from scripts.selftest.ci_extended import run as run_extended

    paths = RunPaths.create(validate_inputs(arguments), arguments.profile)
    stages: list[StageResult] = []
    try:
        try:
            status = run_stages(arguments, paths, stages)
        finally:
            finalize(arguments, paths, stages, keep_build_source=True)
        if status:
            return status
        extension = run_extended(paths, paths.directory / "stack", stages)
        if extension.exit_code:
            raise CIHarnessError("SELFTEST_CI_EXTENSIONS_INCOMPLETE")
        return 0
    finally:
        if (
            paths.profile != "standalone"
            and stop_owned_stack(
                replace(paths, stack=paths.directory / "stack", profile="standalone")
            )
            != "completed"
        ):
            raise CIHarnessError("SELFTEST_CI_BUILD_SOURCE_CLEANUP_FAILED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="以受信 H/O 核验隔离候选构建")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument(
        "--profile", choices=("standalone", "compact", "full"), default="standalone"
    )
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--observer-sha", required=True)
    parser.add_argument("--bootstrap-review", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        return _run(arguments)
    except (CIHarnessError, OSError, ValueError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, CIHarnessError) else type(error).__name__
        print(f"自测 CI 未通过: {code}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
