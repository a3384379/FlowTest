#!/usr/bin/env python3
# User-facing CI copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001
"""Aggregate path-selected GitHub Actions checks into one stable required gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

GITHUB_API_URL = "https://api.github.com"
GITHUB_ACTIONS_APP_ID = 15368
SUCCESS = "success"
TERMINAL_FAILURES = frozenset(
    {"action_required", "cancelled", "failure", "stale", "startup_failure", "timed_out"}
)
RUN_ID_PATTERN = re.compile(r"/actions/runs/(?P<run_id>\d+)/")

BACKEND_SCRIPTS = frozenset(
    {
        "scripts/capacity_s11.py",
        "scripts/capacity_s19.py",
        "scripts/capacity_s29.py",
        "scripts/capacity_workflow.py",
        "scripts/smoke_s3.py",
        "scripts/smoke_s4.py",
        "scripts/smoke_s5.py",
        "scripts/smoke_s6.py",
        "scripts/smoke_s7.py",
        "scripts/smoke_s8.py",
        "scripts/smoke_s9.py",
        "scripts/smoke_s10.py",
        "scripts/smoke_s11.py",
        "scripts/smoke_s18.py",
        "scripts/smoke_s19.py",
        "scripts/smoke_s21.py",
        "scripts/smoke_s22.py",
        "scripts/smoke_s23.py",
        "scripts/smoke_s24.py",
        "scripts/smoke_s25.py",
        "scripts/smoke_s26.py",
        "scripts/smoke_s27.py",
        "scripts/smoke_s28.py",
        "scripts/smoke_s29.py",
        "scripts/smoke_s30.py",
        "scripts/smoke_s47.py",
        "scripts/storage_transfer.py",
        "scripts/verify_kafka_compat.py",
        "scripts/verify_s47_2_contract_migration.py",
        "scripts/verify_s47_3_contract_migration.py",
    }
)
COMPOSE_SCRIPTS = (
    BACKEND_SCRIPTS
    - {
        "scripts/verify_s47_2_contract_migration.py",
        "scripts/verify_s47_3_contract_migration.py",
    }
) | {
    "scripts/backup.sh",
    "scripts/smoke_s31.py",
    "scripts/smoke_s32.py",
    "scripts/verify_restore.sh",
}
UPGRADE_SCRIPTS = frozenset(
    {
        "scripts/smoke_s11.py",
        "scripts/storage_transfer.py",
        "scripts/verify_v2_v3_data.py",
        "scripts/verify_v2_v3_upgrade.sh",
    }
)


@dataclass(frozen=True, slots=True)
class GateSpec:
    key: str
    label: str
    workflow_path: str
    checks: tuple[str, ...]
    prefixes: tuple[str, ...] = ()
    exact_paths: frozenset[str] = frozenset()
    always_required: bool = False

    def required_for(self, paths: frozenset[str]) -> bool:
        return self.always_required or any(
            path in self.exact_paths or path.startswith(self.prefixes) for path in paths
        )


GATE_SPECS = (
    GateSpec(
        key="backend",
        label="Backend CI",
        workflow_path=".github/workflows/backend-ci.yml",
        checks=("test", "integration"),
        prefixes=("backend/", "skills/"),
        exact_paths=BACKEND_SCRIPTS | {".github/workflows/backend-ci.yml"},
    ),
    GateSpec(
        key="frontend",
        label="Frontend CI",
        workflow_path=".github/workflows/frontend-ci.yml",
        checks=("build",),
        prefixes=("frontend/",),
        exact_paths=frozenset({".github/workflows/frontend-ci.yml"}),
    ),
    GateSpec(
        key="security",
        label="Security CI",
        workflow_path=".github/workflows/security-ci.yml",
        checks=("source-and-images",),
        always_required=True,
    ),
    GateSpec(
        key="compose",
        label="Compose Smoke Test",
        workflow_path=".github/workflows/compose-ci.yml",
        checks=("smoke",),
        prefixes=(
            "backend/",
            "frontend/",
            "mock-target/",
            "deploy/compact/",
            "deploy/compatibility/",
            "deploy/s47/",
        ),
        exact_paths=COMPOSE_SCRIPTS | {"compose.yaml", ".github/workflows/compose-ci.yml"},
    ),
    GateSpec(
        key="standalone",
        label="Standalone Windows Bundle",
        workflow_path=".github/workflows/standalone-windows.yml",
        checks=("bundle",),
        prefixes=("backend/", "frontend/", "deploy/standalone/"),
        exact_paths=frozenset(
            {
                ".github/workflows/standalone-windows.yml",
                "scripts/storage_transfer.py",
            }
        ),
    ),
    GateSpec(
        key="upgrade",
        label="V2 to V3 Upgrade CI",
        workflow_path=".github/workflows/upgrade-ci.yml",
        checks=("rehearse-v2-to-v3-upgrade-and-rollback",),
        prefixes=("backend/", "deploy/upgrade/", "mock-target/"),
        exact_paths=UPGRADE_SCRIPTS | {".github/workflows/upgrade-ci.yml"},
    ),
)

CI_GOVERNANCE_PATHS = frozenset(
    {spec.workflow_path for spec in GATE_SPECS}
    | {
        ".github/workflows/required-gate.yml",
        "scripts/required_gate.py",
    }
)
CI_GOVERNANCE_PREFIXES = (".github/workflows/",)


@dataclass(frozen=True, slots=True)
class GatePlan:
    required: tuple[GateSpec, ...]
    no_op: tuple[GateSpec, ...]


class CheckApp(TypedDict, total=False):
    id: int


class CheckRun(TypedDict, total=False):
    id: int
    name: str
    status: str
    conclusion: str | None
    details_url: str
    app: CheckApp | None


class WorkflowRun(TypedDict, total=False):
    id: int
    path: str
    event: str
    head_sha: str


class RequiredGateError(RuntimeError):
    """Raised when a required child check cannot satisfy the gate."""


class GitHubClient:
    def __init__(self, *, repository: str, token: str) -> None:
        self._repository = repository
        self._token = token

    def check_runs(self, sha: str) -> list[CheckRun]:
        encoded_sha = quote(sha, safe="")
        payload = self._get(
            f"/repos/{self._repository}/commits/{encoded_sha}/check-runs?filter=latest&per_page=100"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("check_runs"), list):
            raise RequiredGateError("GitHub Checks API 返回了无效响应")
        return cast(list[CheckRun], payload["check_runs"])

    def workflow_run(self, run_id: int) -> WorkflowRun:
        payload = self._get(f"/repos/{self._repository}/actions/runs/{run_id}")
        if not isinstance(payload, dict):
            raise RequiredGateError("GitHub Actions API 返回了无效响应")
        return cast(WorkflowRun, payload)

    def _get(self, path: str) -> object:
        request = Request(  # noqa: S310 - URL always starts with the fixed GitHub API origin
            f"{GITHUB_API_URL}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "flowtest-required-gate",
            },
        )
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API origin
            return json.load(response)


def build_gate_plan(paths: Iterable[str]) -> GatePlan:
    normalized = _normalized_paths(paths)
    required = tuple(spec for spec in GATE_SPECS if spec.required_for(normalized))
    no_op = tuple(spec for spec in GATE_SPECS if spec not in required)
    return GatePlan(required=required, no_op=no_op)


def enforce_trusted_governance(paths: Iterable[str], event_name: str) -> None:
    if event_name != "pull_request_target":
        return
    modified = sorted(
        path
        for path in _normalized_paths(paths)
        if path in CI_GOVERNANCE_PATHS or path.startswith(CI_GOVERNANCE_PREFIXES)
    )
    if modified:
        raise RequiredGateError(
            "CI 治理文件只能通过受控 Bootstrap 流程更新: " + ", ".join(modified)
        )


def _normalized_paths(paths: Iterable[str]) -> frozenset[str]:
    return frozenset(path.strip().removeprefix("./") for path in paths if path.strip())


def wait_for_required_checks(
    *,
    client: GitHubClient,
    plan: GatePlan,
    sha: str,
    timeout_seconds: int,
    poll_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    workflow_cache: dict[int, WorkflowRun] = {}
    previous_summary = ""
    while time.monotonic() < deadline:
        states = _check_states(client, plan.required, sha, workflow_cache)
        summary = _state_summary(states)
        if summary != previous_summary:
            print(summary, flush=True)
            previous_summary = summary
        failures = [name for name, state in states.items() if state.startswith("failed:")]
        if failures:
            raise RequiredGateError("子门禁失败: " + ", ".join(failures))
        if states and all(state == SUCCESS for state in states.values()):
            return
        time.sleep(max(1, poll_seconds))
    raise RequiredGateError(f"等待子门禁超时（{timeout_seconds} 秒）")


def _check_states(
    client: GitHubClient,
    specs: tuple[GateSpec, ...],
    sha: str,
    workflow_cache: dict[int, WorkflowRun],
) -> dict[str, str]:
    check_runs = sorted(
        client.check_runs(sha), key=lambda item: int(item.get("id", 0)), reverse=True
    )
    states: dict[str, str] = {}
    for spec in specs:
        for check_name in spec.checks:
            key = f"{spec.label}/{check_name}"
            run = _matching_check_run(
                client,
                check_runs,
                check_name,
                spec.workflow_path,
                sha,
                workflow_cache,
            )
            states[key] = _check_state(run)
    return states


def _matching_check_run(
    client: GitHubClient,
    check_runs: list[CheckRun],
    check_name: str,
    workflow_path: str,
    sha: str,
    workflow_cache: dict[int, WorkflowRun],
) -> CheckRun | None:
    for check_run in check_runs:
        if check_run.get("name") != check_name:
            continue
        if not _is_github_actions_check(check_run):
            continue
        run_id = _workflow_run_id(check_run.get("details_url", ""))
        if run_id is None:
            continue
        workflow = workflow_cache.get(run_id)
        if workflow is None:
            workflow = client.workflow_run(run_id)
            workflow_cache[run_id] = workflow
        if _workflow_matches(workflow, workflow_path, sha):
            return check_run
    return None


def _is_github_actions_check(check_run: CheckRun) -> bool:
    app = check_run.get("app")
    return app is not None and app.get("id") == GITHUB_ACTIONS_APP_ID


def _workflow_run_id(details_url: str) -> int | None:
    match = RUN_ID_PATTERN.search(details_url)
    return int(match.group("run_id")) if match else None


def _workflow_matches(workflow: WorkflowRun, expected_path: str, sha: str) -> bool:
    workflow_path = str(workflow.get("path", "")).split("@", 1)[0]
    return (
        workflow_path == expected_path
        and workflow.get("head_sha") == sha
        and workflow.get("event") in {"pull_request", "push"}
    )


def _check_state(check_run: CheckRun | None) -> str:
    if check_run is None or check_run.get("status") != "completed":
        return "pending"
    conclusion = check_run.get("conclusion")
    if conclusion == SUCCESS:
        return SUCCESS
    if conclusion in TERMINAL_FAILURES:
        return f"failed:{conclusion}"
    return f"failed:{conclusion or 'unknown'}"


def _state_summary(states: Mapping[str, str]) -> str:
    return "；".join(f"{name}={state}" for name, state in states.items())


def _write_step_summary(plan: GatePlan, *, status: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    required = ", ".join(spec.label for spec in plan.required) or "无"
    no_op = ", ".join(spec.label for spec in plan.no_op) or "无"
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(
            "## Required Gate\n\n"
            f"- 状态：{status}\n"
            f"- 必需子门禁：{required}\n"
            f"- No-op Success：{no_op}\n"
        )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--paths-file", type=Path, required=True)
    parser.add_argument("--event-name", default=os.getenv("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--timeout-seconds", type=int, default=5400)
    parser.add_argument("--poll-seconds", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    token = os.getenv("GITHUB_TOKEN", "")
    if not args.repository or not token:
        print("Required Gate 缺少 GITHUB_REPOSITORY 或 GITHUB_TOKEN", flush=True)
        return 2
    paths = args.paths_file.read_text(encoding="utf-8").splitlines()
    plan = build_gate_plan(paths)
    _write_step_summary(plan, status="等待子门禁")
    required = ", ".join(spec.label for spec in plan.required)
    no_op = ", ".join(spec.label for spec in plan.no_op) or "无"
    print(f"必需子门禁：{required}；No-op Success：{no_op}", flush=True)
    try:
        enforce_trusted_governance(paths, args.event_name)
        wait_for_required_checks(
            client=GitHubClient(repository=args.repository, token=token),
            plan=plan,
            sha=args.sha,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (RequiredGateError, HTTPError, URLError) as error:
        _write_step_summary(plan, status=f"失败：{error}")
        print(f"Required Gate 失败：{error}", flush=True)
        return 1
    _write_step_summary(plan, status="成功")
    print("Required Gate 成功", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
