#!/usr/bin/env python3
# User-facing CI copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001
"""Deterministic PR check selection. The trusted publisher imports this from base."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TIERS = ("docs", "standard", "integration", "full")
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
GOVERNANCE_FILES = frozenset(
    {
        "AGENTS.md",
        "CONTRIBUTING.md",
        "Makefile",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "docs/ci-milestone.md",
        "docs/development-efficiency-phase3.md",
        "backend/tests/test_ci_plan.py",
        "backend/tests/test_required_gate.py",
        "scripts/build_skill_evaluation.py",
        "scripts/ci_plan.py",
        "scripts/ci_summary.py",
        "scripts/required_gate.py",
        "scripts/run_targeted_tests.py",
    }
)
GOVERNANCE_PREFIXES = (".github/workflows/", ".github/actions/")
FRONTEND_SHARED = (
    "frontend/src/lib/",
    "frontend/src/app/",
    "frontend/src/features/workflows/",
    "frontend/src/features/projects/",
    "frontend/src/features/auth/",
)
BACKEND_CRITICAL = (
    "backend/app/domain/",
    "backend/app/engine/",
    "backend/app/execution/",
    "backend/app/core/security",
    "backend/app/schemas/",
    "backend/app/services/auth.py",
    "backend/app/services/durable_execution.py",
    "backend/app/services/execution_events.py",
    "backend/app/services/execution",
    "backend/app/services/workflows",
    "backend/app/services/workflow_snapshots.py",
    "backend/app/api/v1/endpoints/auth",
    "backend/app/api/v1/endpoints/executions.py",
    "backend/app/models/",
    "backend/app/repositories/",
    "backend/alembic/",
)
BACKEND_TEST_MAP: dict[str, tuple[str, ...]] = {
    "backend/app/services/imports.py": ("tests/test_imports_api.py",),
    "docs/release/s46-ga-gate.md": ("tests/test_s46_ga_gate.py",),
    "docs/release/s46-compatibility-matrix.md": ("tests/test_s46_ga_gate.py",),
    "docs/operations/s46-failure-injection.md": ("tests/test_s46_ga_gate.py",),
}
FRONTEND_TEST_MAP: dict[str, tuple[str, ...]] = {
    "frontend/src/features/navigation/navigation-config.tsx": (
        "src/features/navigation/navigation-config.test.tsx",
        "src/features/navigation/ShellSidebar.test.tsx",
        "src/features/navigation/navigation-preferences.test.ts",
        "src/App.test.tsx",
    ),
    "frontend/src/features/navigation/ShellSidebar.tsx": (
        "src/features/navigation/ShellSidebar.test.tsx",
        "src/App.test.tsx",
    ),
    "frontend/src/features/navigation/navigation-preferences.ts": (
        "src/features/navigation/navigation-preferences.test.ts",
        "src/features/navigation/ShellSidebar.test.tsx",
    ),
}


class PlanError(RuntimeError):
    """Metadata is incomplete or unfit for a merge decision."""


@dataclass(frozen=True)
class Plan:
    base_sha: str
    head_sha: str
    tested_sha: str
    policy_digest: str
    tier_floor: str
    tier: str
    domains: tuple[str, ...]
    required: tuple[str, ...]
    not_applicable: tuple[str, ...]
    reasons: tuple[str, ...]
    backend_targets: tuple[str, ...]
    frontend_targets: tuple[str, ...]
    governance_change: bool

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def _tier_max(left: str, right: str) -> str:
    return TIERS[max(TIERS.index(left), TIERS.index(right))]


def _docs_only(path: str) -> bool:
    return (path == "README.md" or path.startswith("docs/")) and path.endswith(".md")


def _is_governance(path: str) -> bool:
    return path in GOVERNANCE_FILES or path.startswith(GOVERNANCE_PREFIXES)


@dataclass
class Routing:
    tier: str
    domains: set[str]
    reasons: set[str]
    backend_sources: list[str]
    frontend_sources: list[str]
    governance: bool = False

    def classify(self, path: str) -> None:
        if path.startswith("/") or ".." in Path(path).parts or "\x00" in path:
            raise PlanError("变更路径无效")
        if _is_governance(path):
            self.tier = "full"
            self.governance = True
            self.domains.add("policy")
            self.reasons.add("CI/开发规则变更需要 Bootstrap 审核")
        elif path.startswith(("docs/release/", "docs/operations/")):
            self.tier = _tier_max(self.tier, "standard")
            self.domains.add("backend")
            self.backend_sources.append(path)
            self.reasons.add("发布/运维文档被测试读取或用于执行")
        elif _docs_only(path):
            self.reasons.add("独立说明文档")
        elif path.startswith("skills/"):
            self.tier = _tier_max(self.tier, "standard")
            self.domains.add("skills")
            self.reasons.add("Skill 包或 evaluation 输入")
        elif path.startswith("frontend/"):
            self.frontend(path)
        elif path.startswith("backend/"):
            self.backend(path)
        elif path.startswith(("deploy/", "mock-target/")) or path == "compose.yaml":
            self.deploy(path)
        else:
            self.tier = "full"
            self.reasons.add(f"未知路径保守执行完整验收: {path}")

    def deploy(self, path: str) -> None:
        if path.startswith("deploy/standalone/"):
            self.tier = _tier_max(self.tier, "integration")
            self.domains.update(("windows", "backend", "frontend"))
            self.reasons.add("Standalone 打包或启动")
        elif path.startswith("deploy/upgrade/"):
            self.tier = _tier_max(self.tier, "integration")
            self.domains.update(("compose", "upgrade"))
            self.reasons.add("历史升级与回退")
        elif path.startswith("deploy/compact/"):
            self.tier = _tier_max(self.tier, "integration")
            self.domains.update(("compose", "compact"))
            self.reasons.add("Compact RC 仍需现有人工复审入口")
        else:
            self.tier = _tier_max(self.tier, "integration")
            self.domains.add("compose")
            self.reasons.add("部署与目标服务")

    def frontend(self, path: str) -> None:
        self.domains.add("frontend")
        self.tier = _tier_max(self.tier, "standard")
        self.frontend_sources.append(path)
        if path.startswith(FRONTEND_SHARED):
            self.tier = _tier_max(self.tier, "integration")
            self.reasons.add("共享前端状态/契约需完整消费者测试")
        if path.startswith(("frontend/src/lib/api", "frontend/src/features/workflows/")):
            self.domains.add("compose")
            self.reasons.add("前端 API/流程契约需端到端冒烟")
        if path in {"frontend/package.json", "frontend/pnpm-lock.yaml"} or "Dockerfile" in path:
            self.tier = _tier_max(self.tier, "integration")
            self.domains.add("security")
            self.reasons.add("前端依赖或镜像输入")

    def backend(self, path: str) -> None:
        self.domains.add("backend")
        self.tier = _tier_max(self.tier, "standard")
        self.backend_sources.append(path)
        if path.startswith(BACKEND_CRITICAL):
            self.tier = _tier_max(self.tier, "integration")
            self.domains.add("compose")
            self.reasons.add("关键后端运行或数据路径")
        if path.startswith(("backend/app/domain/execution", "backend/app/engine/")):
            self.domains.update(("frontend", "windows"))
            self.reasons.add("引擎结果需前端契约与 Standalone 验证")
        if path.startswith(("backend/app/schemas/", "backend/app/api/v1/endpoints/auth")):
            self.domains.add("frontend")
            self.reasons.add("共享 API 契约需前端消费者验证")
        if path.startswith(("backend/app/services/auth.py", "backend/app/api/v1/endpoints/auth")):
            self.domains.add("security")
            self.reasons.add("认证边界需安全检查")
        if path.startswith(
            ("backend/alembic/", "backend/app/models/", "backend/app/repositories/")
        ):
            self.domains.update(("upgrade", "windows"))
            self.reasons.add("数据模型与历史升级/Standalone 兼容")
        if path in {"backend/pyproject.toml", "backend/uv.lock"} or "Dockerfile" in path:
            self.tier = _tier_max(self.tier, "integration")
            self.domains.update(("security", "compose"))
            self.reasons.add("后端依赖或镜像输入")


def _mapped_targets(sources: list[str], mapping: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    selected = [mapping.get(path) for path in sources]
    if not selected or not all(selected):
        return ()
    return tuple(sorted({target for group in selected if group for target in group}))


def _required_jobs(
    routing: Routing, tier: str
) -> tuple[set[str], tuple[str, ...], tuple[str, ...]]:
    required = {"quick"}
    backend_targets: tuple[str, ...] = ()
    frontend_targets: tuple[str, ...] = ()
    if tier == "full":
        required.update(
            ("backend-full", "frontend-full", "compose", "security", "windows", "upgrade", "skills")
        )
    else:
        if "backend" in routing.domains:
            required.add("backend-full" if tier == "integration" else "backend-standard")
            backend_targets = _mapped_targets(routing.backend_sources, BACKEND_TEST_MAP)
        if "frontend" in routing.domains:
            required.add("frontend-full" if tier == "integration" else "frontend-standard")
            frontend_targets = _mapped_targets(routing.frontend_sources, FRONTEND_TEST_MAP)
        required.update(
            routing.domains & {"compose", "security", "windows", "upgrade", "compact", "skills"}
        )
    if "compact" in routing.domains:
        required.add("compact")
    if routing.governance:
        required.add("policy")
    return required, backend_targets, frontend_targets


def _paths_from_files(files: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in files:
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename:
            raise PlanError("PR 文件路径无效")
        paths.append(filename)
        if item.get("status") == "renamed":
            old = item.get("previous_filename")
            if not isinstance(old, str) or not old:
                raise PlanError("重命名缺少旧路径")
            paths.append(old)
    return paths


def build_plan(
    paths: list[str], labels: set[str], *, base_sha: str, head_sha: str, tested_sha: str
) -> Plan:
    if not paths or any(not isinstance(path, str) or not path for path in paths):
        raise PlanError("变更路径为空或无效，不能推断为文档变更")
    if any(
        len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha)
        for sha in (base_sha, head_sha, tested_sha)
    ):
        raise PlanError("base/head/tested SHA 无效")
    routing = Routing("docs", set(), set(), [], [])
    for path in paths:
        routing.classify(path)
    floor = routing.tier
    tier = floor
    if "ci:milestone" in labels:
        tier = "full"
        routing.reasons.add("ci:milestone 请求完整验收")
    if "ci:light" in labels:
        routing.reasons.add("ci:light 保留自动最低档位")
    if {"ci:milestone", "ci:light"} <= labels:
        routing.reasons.add("两个 CI 标签同时存在，采用较重请求")
    required, backend_targets, frontend_targets = _required_jobs(routing, tier)
    return Plan(
        base_sha,
        head_sha,
        tested_sha,
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        floor,
        tier,
        tuple(sorted(routing.domains)),
        tuple(job for job in ALL_JOBS if job in required),
        tuple(job for job in ALL_JOBS if job not in required),
        tuple(sorted(routing.reasons)),
        backend_targets,
        frontend_targets,
        routing.governance,
    )


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def get(self, path: str) -> dict[str, Any] | list[Any]:
        request = Request(
            f"https://api.github.com/repos/{self.repository}/{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS host
                return cast(dict[str, Any] | list[Any], json.load(response))
        except (HTTPError, URLError, ValueError) as exc:
            raise PlanError("GitHub 元数据读取失败") from exc

    def changed_paths(self, number: int, changed_count: object) -> list[str]:
        if not isinstance(changed_count, int) or changed_count <= 0 or changed_count >= 3000:
            raise PlanError("PR 文件清单为空或达到 GitHub API 上限")
        files: list[dict[str, Any]] = []
        for page in range(1, 31):
            batch = self.get(f"pulls/{number}/files?per_page=100&page={page}")
            if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
                raise PlanError("PR 文件分页响应无效")
            files.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise PlanError("PR 文件分页达到上限")
        if len(files) != changed_count:
            raise PlanError("PR 文件清单与 changed_files 不一致")
        if len({item.get("filename") for item in files}) != changed_count:
            raise PlanError("PR 文件分页重复或不完整")
        return _paths_from_files(files)

    def pr_plan(self, number: int, tested_sha: str) -> Plan:
        pr = self.get(f"pulls/{number}")
        if not isinstance(pr, dict) or pr.get("state") != "open":
            raise PlanError("PR 元数据无效或 PR 未开放")
        paths = self.changed_paths(number, pr.get("changed_files"))
        current = self.get(f"pulls/{number}")
        if not isinstance(current, dict) or any(
            current.get(key) != pr.get(key) for key in ("base", "head", "labels", "changed_files")
        ):
            raise PlanError("读取文件期间 PR 元数据已改变")
        labels = {
            item["name"]
            for item in pr.get("labels", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        return build_plan(
            paths,
            labels,
            base_sha=pr["base"]["sha"],
            head_sha=pr["head"]["sha"],
            tested_sha=tested_sha,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        plan = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]).pr_plan(
            args.pr, args.tested_sha
        )
        if (plan.base_sha, plan.head_sha) != (args.expected_base, args.expected_head):
            raise PlanError("PR base/head 已变化，本轮计划过期")
    except (KeyError, PlanError) as exc:
        parser.exit(1, f"CI 计划失败: {exc}\n")
    result = plan.to_json()
    print(result)
    if args.output:
        with args.output.open("a", encoding="utf-8") as output:
            output.write(f"plan={result}\n")
            output.write(f"fingerprint={hashlib.sha256(result.encode()).hexdigest()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
