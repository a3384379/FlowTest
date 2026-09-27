#!/usr/bin/env python3
# User-facing CI copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001
"""Publish the one protected status from trusted PR metadata and one Actions run.

This script runs only from the default branch in a privileged workflow. It never
checks out or executes PR content, and never waits for another workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ci_plan import GitHub, Plan, PlanError

CONTEXT = "Required Gate"
WORKFLOW = ".github/workflows/pr-validation.yml"
PLAN_PREFIX = "CI Plan "
SHADOW_PREFIX = "PR Validation Shadow "
SHA_CHARS = frozenset("0123456789abcdef")


class GateError(RuntimeError):
    """The metadata cannot justify a protected success status."""


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and set(value) <= SHA_CHARS


def require_pr(pr: dict[str, Any], repository: str, default_branch: str) -> None:
    if pr.get("state") != "open" or pr.get("base", {}).get("ref") != default_branch:
        raise GateError("PR 未开放或目标不是受信默认分支")
    if pr.get("base", {}).get("repo", {}).get("full_name") != repository:
        raise GateError("PR 基线仓库不匹配")
    if not valid_sha(pr.get("base", {}).get("sha")) or not valid_sha(pr.get("head", {}).get("sha")):
        raise GateError("PR base/head SHA 无效")


def validate_merge(gh: GitHub, pr: dict[str, Any]) -> str:
    merge_sha = pr.get("merge_commit_sha")
    if not valid_sha(merge_sha):
        raise GateError("PR 测试合并 SHA 缺失")
    commit = gh.get(f"commits/{merge_sha}")
    if not isinstance(commit, dict):
        raise GateError("测试合并提交响应无效")
    parents = commit.get("parents", [])
    if [item.get("sha") for item in parents] != [pr["base"]["sha"], pr["head"]["sha"]]:
        raise GateError("测试合并提交与当前 base/head 不匹配")
    return cast(str, merge_sha)


def pr_validation_identity(pr: dict[str, Any]) -> tuple[object, ...]:
    """Identify the PR revision and policy inputs without mutable repository metadata."""
    base = pr.get("base")
    head = pr.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise GateError("PR base/head 元数据无效")
    base_repo = base.get("repo") or {}
    head_repo = head.get("repo") or {}
    labels = frozenset(
        item.get("name")
        for item in pr.get("labels", [])
        if isinstance(item, dict) and item.get("name") in {"ci:light", "ci:milestone"}
    )
    return (
        pr.get("state"),
        base.get("sha"),
        base.get("ref"),
        base_repo.get("full_name"),
        head.get("sha"),
        head.get("ref"),
        head_repo.get("full_name"),
        pr.get("merge_commit_sha"),
        labels,
    )


def fingerprint(plan: Plan) -> str:
    return hashlib.sha256(plan.to_json().encode()).hexdigest()


def evaluate_jobs(run_id: int, jobs: list[dict[str, Any]], plan: Plan) -> tuple[bool, str]:
    names: dict[str, dict[str, Any]] = {}
    for job in jobs:
        name = job.get("name")
        if not isinstance(name, str) or name in names or job.get("run_id") != run_id:
            return False, "运行任务清单有重复或来源不匹配"
        names[name] = job
    expected = (
        PLAN_PREFIX + plan.tested_sha,
        SHADOW_PREFIX + plan.tested_sha + " " + fingerprint(plan),
    )
    for name in expected:
        matched = names.get(name)
        if (
            not matched
            or matched.get("status") != "completed"
            or matched.get("conclusion") != "success"
        ):
            return False, "计划或影子汇总未成功，或计划与当前 PR 不一致"
    return True, "当前 PR 验证及受信计划均通过"


def evaluate_run(
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    plan: Plan,
    repository: str,
    workflow_id: int,
) -> tuple[bool, str]:
    if run.get("repository", {}).get("full_name") != repository:
        return False, "工作流仓库不匹配"
    if run.get("workflow_id") != workflow_id or run.get("path", "").split("@")[0] != WORKFLOW:
        return False, "工作流身份不匹配"
    if run.get("event") != "pull_request" or run.get("head_sha") != plan.head_sha:
        return False, "运行事件或 Head 不匹配"
    if run.get("display_title") != "PR Validation active":
        return False, "运行入口不匹配"
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return False, "PR 验证运行未成功"
    if plan.governance_change:
        return False, "CI 治理变更需要 Bootstrap 审核"
    return evaluate_jobs(run["id"], jobs, plan)


class Publisher(GitHub):
    def post(self, sha: str, state: str, description: str, run_id: int) -> None:
        if not valid_sha(sha) or state not in {"pending", "failure", "success"}:
            raise GateError("状态参数无效")
        payload = json.dumps(
            {
                "state": state,
                "context": CONTEXT,
                "description": description[:140],
                "target_url": f"https://github.com/{self.repository}/actions/runs/{run_id}",
            }
        ).encode()
        request = Request(
            f"https://api.github.com/repos/{self.repository}/statuses/{sha}",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS host
                if response.status != 201:
                    raise GateError("GitHub 未确认状态发布")
        except (HTTPError, URLError) as exc:
            raise GateError("Required Gate 状态发布失败") from exc

    def jobs(self, run_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, 31):
            payload = self.get(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}")
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                raise GateError("Actions 任务清单无效")
            batch = payload["jobs"]
            result.extend(batch)
            if len(batch) < 100:
                if len(result) != payload.get("total_count"):
                    raise GateError("Actions 任务清单不完整")
                return result
        raise GateError("Actions 任务清单达到分页上限")


def associated_pr_number(gh: Publisher, run: dict[str, Any]) -> int:
    references = run.get("pull_requests") or []
    numbers = {item.get("number") for item in references if isinstance(item, dict)}
    if not numbers:
        head_sha = run.get("head_sha")
        if not valid_sha(head_sha):
            raise GateError("运行 Head 无效")
        pulls = gh.get(f"commits/{quote(cast(str, head_sha), safe='')}/pulls")
        if not isinstance(pulls, list):
            raise GateError("提交关联 PR 响应无效")
        numbers = {item.get("number") for item in pulls if item.get("state") == "open"}
    if len(numbers) != 1 or not all(isinstance(number, int) for number in numbers):
        raise GateError("运行未唯一关联开放 PR")
    return cast(int, numbers.pop())


def latest_run(gh: Publisher, pr: dict[str, Any]) -> dict[str, Any]:
    sha = pr["head"]["sha"]
    payload = gh.get(
        f"actions/workflows/pr-validation.yml/runs?event=pull_request&head_sha={sha}&per_page=100"
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise GateError("PR 验证运行列表无效")
    if payload.get("total_count", 0) > 100:
        raise GateError("PR 验证运行列表超过单页上限")
    candidates = [
        run
        for run in payload["workflow_runs"]
        if run.get("display_title") == "PR Validation active"
        and run.get("head_branch") == pr["head"]["ref"]
        and run.get("head_repository", {}).get("full_name") == pr["head"]["repo"]["full_name"]
    ]
    if not candidates:
        raise GateError("当前 PR 没有有效验证运行")
    return max(candidates, key=lambda run: run["id"])


def current_event_run(
    gh: Publisher, event: dict[str, Any], default_branch: str
) -> tuple[dict[str, Any], dict[str, Any], int, dict[str, Any]] | None:
    notified = event.get("workflow_run", {})
    if notified.get("display_title") != "PR Validation active":
        return None
    if notified.get("repository", {}).get("full_name") != gh.repository:
        raise GateError("完成事件仓库不匹配")
    number = associated_pr_number(gh, notified)
    pr = gh.get(f"pulls/{number}")
    if not isinstance(pr, dict):
        raise GateError("PR 元数据无效")
    require_pr(pr, gh.repository, default_branch)
    if notified.get("head_sha") != pr["head"]["sha"]:
        return None
    current = latest_run(gh, pr)
    if notified.get("id") != current.get("id") or notified.get("run_attempt") != current.get(
        "run_attempt"
    ):
        return None  # A stale notification cannot overwrite the current attempt.
    return notified, pr, number, current


def publish_current_run(gh: Publisher, event: dict[str, Any], default_branch: str) -> None:
    resolved = current_event_run(gh, event, default_branch)
    if resolved is None:
        return
    notified, pr, number, current = resolved
    workflow = gh.get("actions/workflows/pr-validation.yml")
    run = gh.get(f"actions/runs/{current['id']}")
    if event.get("action") == "completed":
        for _ in range(3):
            if isinstance(run, dict) and run.get("status") == "completed":
                break
            time.sleep(2)
            run = gh.get(f"actions/runs/{current['id']}")
        if not isinstance(run, dict) or run.get("status") != "completed":
            raise GateError("完成事件对应的运行尚未进入终态")
    if not isinstance(workflow, dict) or not isinstance(run, dict):
        raise GateError("运行身份不可用")
    if (
        run.get("workflow_id") != workflow.get("id")
        or run.get("id") != notified.get("id")
        or run.get("run_attempt") != notified.get("run_attempt")
        or run.get("path", "").split("@")[0] != WORKFLOW
        or run.get("event") != "pull_request"
    ):
        raise GateError("运行身份不匹配")
    if run.get("status") == "completed":
        publish_checked_run(gh, notified, pr, number, current)
    else:
        gh.post(pr["head"]["sha"], "pending", "等待当前 PR 验证与受信汇总", current["id"])


def publish_checked_run(
    gh: Publisher,
    notified: dict[str, Any],
    pr: dict[str, Any],
    number: int,
    current: dict[str, Any],
) -> None:
    merge_sha = validate_merge(gh, pr)
    try:
        plan = gh.pr_plan(number, merge_sha)
    except PlanError as exc:
        gh.post(pr["head"]["sha"], "failure", "受信 CI 计划不可用", current["id"])
        raise GateError("受信 CI 计划不可用") from exc
    workflow = gh.get("actions/workflows/pr-validation.yml")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("id"), int):
        raise GateError("PR 工作流身份不可用")
    run = gh.get(f"actions/runs/{current['id']}")
    if not isinstance(run, dict) or run.get("run_attempt") != notified.get("run_attempt"):
        raise GateError("运行实例已改变")
    valid, description = evaluate_run(
        run, gh.jobs(current["id"]), plan, gh.repository, workflow["id"]
    )
    refreshed = gh.get(f"pulls/{number}")
    if not isinstance(refreshed, dict) or pr_validation_identity(
        refreshed
    ) != pr_validation_identity(pr):
        return  # A new PR state must get its own run and status.
    latest = latest_run(gh, pr)
    if latest.get("id") != current["id"] or latest.get("run_attempt") != current.get("run_attempt"):
        return
    final_run = gh.get(f"actions/runs/{current['id']}")
    if (
        not isinstance(final_run, dict)
        or final_run.get("run_attempt") != current.get("run_attempt")
        or final_run.get("status") != "completed"
    ):
        return
    gh.post(plan.head_sha, "success" if valid else "failure", description, current["id"])
    if not valid:
        raise GateError(description)


def main() -> int:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        repository = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GITHUB_TOKEN"]
        default_branch = event["repository"]["default_branch"]
        gh = Publisher(repository, token)
        if os.environ["GITHUB_EVENT_NAME"] != "workflow_run":
            raise GateError("不支持的门禁事件")
        if event.get("action") not in {"requested", "in_progress", "completed"}:
            raise GateError("不支持的 workflow_run 活动类型")
        publish_current_run(gh, event, default_branch)
    except (GateError, KeyError, ValueError, PlanError) as exc:
        print(f"Required Gate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
