#!/usr/bin/env python3
# User-facing CI copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001
"""Summarize one PR Validation run using native needs results."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# This script runs with Python's isolated path. Keep the job contract local so
# a PR-added module beside the planner cannot intercept the shadow summary.
ALL_JOBS = (
    "quick",
    "backend-standard",
    "backend-full",
    "frontend-standard",
    "frontend-full",
    "compose",
    "security",
    "windows",
    "upgrade",
    "compact",
    "skills",
    "policy",
)


def evaluate(plan: dict[str, Any] | None, needs: dict[str, Any]) -> tuple[bool, list[str]]:
    if plan is None or not isinstance(plan.get("required"), list):
        return False, ["计划缺失或生成失败"]
    if needs.get("plan", {}).get("result") != "success":
        return False, ["计划 job 未成功"]
    required = plan["required"]
    if (
        not required
        or "quick" not in required
        or len(required) != len(set(required))
        or not set(required) <= set(ALL_JOBS)
    ):
        return False, ["计划任务无效"]
    if set(plan.get("not_applicable", [])) != set(ALL_JOBS) - set(required):
        return False, ["不适用清单与必需任务不一致"]
    lines = [
        f"base={plan.get('base_sha')} head={plan.get('head_sha')} tested={plan.get('tested_sha')}",
        f"policy=scripts/ci_plan.py@{plan.get('policy_digest')}",
        f"档位: {plan.get('tier')}；原因: {', '.join(plan.get('reasons', []))}",
    ]
    valid = not plan.get("governance_change", False)
    for key in ALL_JOBS:
        if key in required:
            result = needs.get(key, {}).get("result", "missing")
            lines.append(f"{key}: {result}")
            valid &= result == "success"
        else:
            lines.append(f"{key}: not_applicable")
    if plan.get("governance_change"):
        lines.append("治理文件需 Bootstrap 受信审核")
    return valid, lines


def main() -> int:
    raw_plan = os.environ.get("CI_PLAN", "")
    try:
        plan = json.loads(raw_plan) if raw_plan else None
        needs = json.loads(os.environ["CI_NEEDS"])
    except (json.JSONDecodeError, KeyError):
        plan, needs = None, {}
    valid, lines = evaluate(plan, needs)
    text = "\n".join(lines) + "\n"
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write("### PR Validation Shadow\n\n```text\n" + text + "```\n")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
