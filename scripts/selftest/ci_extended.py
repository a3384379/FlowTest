"""Separate bounded deployment waves for extension packs and actual JWT expiry."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from scripts.selftest.boundary_verify import BoundaryPack
from scripts.selftest.boundary_verify import verify as verify_boundary
from scripts.selftest.ci_extended_reports import (
    PackSummary,
    archive,
    archive_bad_targets,
    normalize,
)
from scripts.selftest.configured_probes import GroupResult, _only_disposal
from scripts.selftest.contracts import Contract
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.local_stack import StackBinding

if TYPE_CHECKING:
    from scripts.selftest_ci import RunPaths, StageResult


@dataclass(frozen=True)
class JourneySpec:
    label: str
    module: str
    count: int


JOURNEYS = (
    JourneySpec("semantic", "scripts.selftest.semantic_run", 5),
    JourneySpec("delta", "scripts.selftest.run_contract_delta", 7),
    JourneySpec("control", "scripts.selftest.run_native_control", 3),
    JourneySpec("security", "scripts.selftest.run_boundaries", 5),
    JourneySpec("initialization", "scripts.selftest.run_boundaries", 3),
)


class ExtendedReceipt(Contract):
    runtime_profile: Literal["standalone", "full", "compact"]
    exit_code: Literal[0, 2]
    summaries: tuple[PackSummary, ...]
    reason_codes: tuple[str, ...]
    cleanup: Literal["completed", "failed", "not_started"]
    auth_cleanup: Literal["completed", "failed", "not_started"]
    worker_cleanup: Literal["completed", "failed", "not_started", "not_applicable"] = "not_started"
    product_cleanup: Literal["completed", "failed", "not_started"] = "not_started"
    model_calls: Literal[0] = 0
    trust: Literal["local_untrusted"] = "local_untrusted"


def _command(
    paths: RunPaths,
    stages: list[StageResult],
    name: str,
    args: list[str],
    *,
    accepted: tuple[int, ...] = (0,),
    timeout: int = 660,
) -> None:
    from scripts.selftest_ci import StageResult, command

    status = command(
        [paths.python, "-m", *args],
        log=paths.directory / f"private-logs/{name}.log",
        timeout=timeout,
    )
    stages.append(StageResult(name, status))
    if status not in accepted:
        raise HarnessError("SELFTEST_EXTENDED_STAGE_FAILED:" + name)


def start_wave(
    paths: RunPaths, source: Path, stages: list[StageResult], *, minutes: int = 15
) -> None:
    module = (
        "scripts.selftest.stack_clone"
        if paths.profile == "standalone"
        else "scripts.selftest.profile_stack"
    )
    args = [module]
    if paths.profile != "standalone":
        args.append("start")
    args += [
        "--directory",
        str(paths.stack),
        "--source-stack-directory",
        str(source),
        "--target-access-token-minutes",
        str(minutes),
    ]
    if paths.profile != "standalone":
        args += ["--profile", paths.profile]
    _command(
        paths,
        stages,
        "extension-start" if minutes == 15 else "auth-expiry-start",
        args,
        timeout=900,
    )
    source_binding = StackBinding.model_validate(read_json(source / "stack.json"))
    current = StackBinding.model_validate(read_json(paths.stack / "stack.json"))
    for field in (
        "candidate_image_digest",
        "fixture_image_digest",
        "source_digest",
        "dependency_digest",
    ):
        if getattr(source_binding, field) != getattr(current, field):
            raise HarnessError("SELFTEST_EXTENDED_WAVE_BUILD_CHANGED")


def journey_command(paths: RunPaths, spec: JourneySpec, *, final: bool = False) -> list[str]:
    args = [
        spec.module,
        "--directory",
        str(paths.stack),
        "--output",
        str(paths.directory / spec.label),
    ]
    if spec.label in {"security", "initialization"}:
        args += ["--pack", spec.label]
    return [*args, "--finalize-disposable"] if final else args


def require_pending(paths: RunPaths, spec: JourneySpec) -> None:
    source = paths.directory / spec.label
    code: int
    if spec.label in {"security", "initialization"}:
        pack: Literal["security", "initialization"] = (
            "security" if spec.label == "security" else "initialization"
        )
        report = verify_boundary(pack, read_json(source / "result.json"))
        code, ids, reasons = report.exit_code, report.scenario_ids, report.reason_codes
    else:
        code, ids, reasons = normalize(spec.label, source)
    expected = (
        "SEMANTIC_OWNED_DISPOSAL_PENDING"
        if spec.label == "semantic"
        else "OWNED_ASSET_DISPOSAL_PENDING"
    )
    if code != 2 or len(ids) != spec.count or len(set(ids)) != spec.count or reasons != (expected,):
        raise HarnessError("SELFTEST_EXTENDED_PRE_DISPOSAL_INCOMPLETE:" + spec.label)


def _archive_configured_failure(paths: RunPaths, error: BaseException) -> None:
    destination = paths.public / "configured-failure"
    write_json(
        destination / "driver-failure.json",
        GroupResult(exit_code=2, reports=(), reason_codes=failure_codes(error)),
    )
    try:
        source = paths.directory / "configured/group-verification.json"
        if source.stat().st_size > 1048576:
            raise HarnessError("SELFTEST_EXTENDED_PUBLIC_REPORT_TOO_LARGE")
        report = GroupResult.model_validate(read_json(source))
    except (HarnessError, OSError, ValueError) as source_error:
        write_json(
            destination / "source-unavailable.json",
            GroupResult(exit_code=2, reports=(), reason_codes=failure_codes(source_error)),
        )
    else:
        write_json(destination / "observed-verification.json", report)


def _configured_group(paths: RunPaths, stages: list[StageResult]) -> list[str]:
    args = [
        "scripts.selftest.configured_probes",
        "--directory",
        str(paths.stack),
        "--output",
        str(paths.directory / "configured"),
    ]
    try:
        _command(paths, stages, "configured-before-disposal", args, accepted=(2,))
        group = GroupResult.model_validate(
            read_json(paths.directory / "configured/group-verification.json")
        )
        if (
            group.reason_codes
            or len(group.reports) != 3
            or not all(_only_disposal(r) for r in group.reports)
        ):
            raise HarnessError("SELFTEST_EXTENDED_CONFIGURED_INCOMPLETE")
    except (HarnessError, OSError, ValueError, subprocess.SubprocessError) as error:
        _archive_configured_failure(paths, error)
        raise
    return args


def run_wave(paths: RunPaths, source: Path, stages: list[StageResult]) -> tuple[PackSummary, ...]:
    from scripts.selftest_ci import stop_owned_stack

    try:
        start_wave(paths, source, stages)
        _command(
            paths,
            stages,
            "badtargets",
            [
                "scripts.selftest.run",
                "--directory",
                str(paths.stack),
                "--output-dir",
                str(paths.directory / "badtargets"),
                "--suite",
                "mcp-badtargets",
                "--rounds",
                "1",
            ],
        )
        initial_binding = StackBinding.model_validate(read_json(paths.stack / "stack.json"))
        badtargets = archive_bad_targets(
            paths.directory / "badtargets/round-1", paths.public, initial_binding
        )
        # All grants recreate the runner before any disposal-dependent pack freezes it.
        group_args = _configured_group(paths, stages)
        for spec in JOURNEYS:
            _command(
                paths,
                stages,
                spec.label + "-before-disposal",
                journey_command(paths, spec),
                accepted=(2,),
            )
            require_pending(paths, spec)
    finally:
        cleanup = stop_owned_stack(paths)
    if cleanup != "completed":
        raise HarnessError("SELFTEST_EXTENDED_CLEANUP_FAILED")
    _command(
        paths,
        stages,
        "configured-after-disposal",
        [*group_args, "--finalize-disposable"],
    )
    binding = StackBinding.model_validate(read_json(paths.stack / "stack.json"))
    summaries = [
        archive(
            label,
            count,
            paths.directory / "configured" / label / "public",
            paths.public,
            binding,
        )
        for label, count in (("faults", 14), ("quality", 18), ("review", 12))
    ]
    for spec in JOURNEYS:
        _command(
            paths,
            stages,
            spec.label + "-after-disposal",
            journey_command(paths, spec, final=True),
        )
        boundary: BoundaryPack | None = (
            "security"
            if spec.label == "security"
            else "initialization"
            if spec.label == "initialization"
            else None
        )
        summaries.append(
            archive(
                spec.label,
                spec.count,
                paths.directory / spec.label,
                paths.public,
                binding,
                boundary=boundary,
            )
        )
    return (badtargets, *summaries)


def run_auth(paths: RunPaths, source: Path, stages: list[StageResult]) -> PackSummary:
    from scripts.selftest_ci import stop_owned_stack

    try:
        start_wave(paths, source, stages, minutes=1)
        _command(
            paths,
            stages,
            "auth-expiry",
            [
                "scripts.selftest.run_boundaries",
                "--pack",
                "auth-expiry",
                "--directory",
                str(paths.stack),
                "--output",
                str(paths.directory / "auth-expiry"),
            ],
        )
        binding = StackBinding.model_validate(read_json(paths.stack / "stack.json"))
        summary = archive(
            "auth-expiry",
            1,
            paths.directory / "auth-expiry",
            paths.public,
            binding,
            boundary="auth-expiry",
        )
    finally:
        cleanup = stop_owned_stack(paths)
    if cleanup != "completed":
        raise HarnessError("SELFTEST_EXTENDED_AUTH_CLEANUP_FAILED")
    return summary


def run(paths: RunPaths, source: Path, stages: list[StageResult]) -> ExtendedReceipt:
    from scripts.selftest_ci import RunPaths, stop_owned_stack

    wave = RunPaths.create(paths.directory / "extensions", paths.profile)
    auth = RunPaths.create(paths.directory / "expiry", paths.profile)
    workers = RunPaths.create(paths.directory / "workers", paths.profile)
    product = RunPaths.create(paths.directory / "product", paths.profile)
    summaries: tuple[PackSummary, ...] = ()
    reasons: tuple[str, ...] = ()
    try:
        summaries = run_wave(wave, source, stages)
        summaries = (*summaries, run_auth(auth, source, stages))
        if paths.profile != "standalone":
            summaries = (*summaries, run_workers(workers, source, stages))
        summaries = (*summaries, *run_product(product, source, stages))
    except (HarnessError, OSError, ValueError, subprocess.SubprocessError) as error:
        reasons = (
            str(error) if isinstance(error, HarnessError) else "SELFTEST_EXTENDED_INPUT_INVALID",
        )
    finally:
        cleanup, auth_cleanup = stop_owned_stack(wave), stop_owned_stack(auth)
        worker_cleanup = (
            stop_owned_stack(workers) if paths.profile != "standalone" else "not_applicable"
        )
        product_cleanup = stop_owned_stack(product)
    receipt = ExtendedReceipt(
        runtime_profile=paths.profile,
        exit_code=0
        if len(summaries) == (12 if paths.profile == "standalone" else 13)
        and not reasons
        and cleanup == auth_cleanup == "completed"
        and worker_cleanup == ("not_applicable" if paths.profile == "standalone" else "completed")
        and product_cleanup == "completed"
        else 2,
        summaries=summaries,
        reason_codes=reasons,
        cleanup=cleanup,
        auth_cleanup=auth_cleanup,
        worker_cleanup=worker_cleanup,
        product_cleanup=product_cleanup,
    )
    paths.public.mkdir(parents=True, exist_ok=True)
    write_json(paths.public / "ci-extended-receipt.json", receipt)
    return receipt


def run_workers(paths: RunPaths, source: Path, stages: list[StageResult]) -> PackSummary:
    from scripts.selftest_ci import stop_owned_stack

    spec = JourneySpec("workers", "scripts.selftest.run_worker_faults", 4)
    try:
        start_wave(paths, source, stages)
        _command(
            paths,
            stages,
            "worker-faults",
            journey_command(paths, spec),
            accepted=(2,),
            timeout=360,
        )
        require_pending(paths, spec)
    finally:
        cleanup = stop_owned_stack(paths)
    if cleanup != "completed":
        raise HarnessError("SELFTEST_EXTENDED_WORKER_CLEANUP_FAILED")
    _command(paths, stages, "worker-faults-final", journey_command(paths, spec, final=True))
    binding = StackBinding.model_validate(read_json(paths.stack / "stack.json"))
    return archive("workers", 4, paths.directory / "workers", paths.public, binding)


def run_product(
    paths: RunPaths, source: Path, stages: list[StageResult]
) -> tuple[PackSummary, PackSummary]:
    from scripts.selftest_ci import stop_owned_stack

    spec = JourneySpec("product", "scripts.selftest.run_product_boundaries", 27)
    try:
        start_wave(paths, source, stages)
        _command(paths, stages, "product-boundaries", journey_command(paths, spec), accepted=(2,))
        require_pending(paths, spec)
        compiler = [
            "scripts.selftest.run_compile_boundaries",
            "--directory",
            str(paths.stack),
            "--product",
            str(paths.directory / "product"),
            "--output",
            str(paths.directory / "compiler"),
        ]
        _command(paths, stages, "compiler-boundaries", compiler, accepted=(2,))
        require_pending(
            paths, JourneySpec("compiler", "scripts.selftest.run_compile_boundaries", 38)
        )
    finally:
        cleanup = stop_owned_stack(paths)
    if cleanup != "completed":
        raise HarnessError("SELFTEST_EXTENDED_PRODUCT_CLEANUP_FAILED")
    _command(paths, stages, "product-boundaries-final", journey_command(paths, spec, final=True))
    _command(paths, stages, "compiler-boundaries-final", [*compiler, "--finalize-disposable"])
    binding = StackBinding.model_validate(read_json(paths.stack / "stack.json"))
    return (
        archive("product", 27, paths.directory / "product", paths.public, binding),
        archive("compiler", 38, paths.directory / "compiler", paths.public, binding),
    )


def main() -> int:
    from scripts.selftest_ci import RunPaths

    parser = argparse.ArgumentParser(description="执行固定构建的扩展验收及真实令牌过期; 不调用模型")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source-stack-directory", type=Path, required=True)
    parser.add_argument(
        "--profile", choices=("standalone", "full", "compact"), default="standalone"
    )
    args = parser.parse_args()
    if args.directory.exists():
        raise HarnessError("SELFTEST_EXTENDED_OUTPUT_EXISTS_NO_REPLAY")
    receipt = run(RunPaths.create(args.directory, args.profile), args.source_stack_directory, [])
    print(json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False))
    return receipt.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
