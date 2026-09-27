"""Characterize the trusted, deterministic PR routing policy."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

MODULE_PATH = Path(__file__).parents[2] / "scripts/ci_plan.py"
SPEC = importlib.util.spec_from_file_location("ci_plan", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ci_plan: ModuleType = importlib.util.module_from_spec(SPEC)

sys.modules[SPEC.name] = ci_plan
SPEC.loader.exec_module(ci_plan)
SHA = "a" * 40


def plan(paths: list[str], labels: set[str] | None = None) -> Any:
    return ci_plan.build_plan(paths, labels or set(), base_sha=SHA, head_sha=SHA, tested_sha=SHA)


@pytest.mark.parametrize(
    ("path", "tier", "required"),
    [
        ("README.md", "docs", {"quick"}),
        ("docs/release/s46-ga-gate.md", "standard", {"backend-standard"}),
        ("frontend/src/features/navigation/ShellSidebar.tsx", "standard", {"frontend-standard"}),
        ("backend/app/services/imports.py", "standard", {"backend-standard"}),
        ("backend/app/domain/execution.py", "integration", {"backend-full", "compose"}),
        ("backend/app/core/security.py", "integration", {"backend-full", "compose"}),
        ("backend/alembic/versions/123.py", "integration", {"upgrade", "windows"}),
        ("backend/uv.lock", "integration", {"security", "compose"}),
        ("deploy/standalone/mcp.ps1", "integration", {"windows"}),
        ("deploy/upgrade/verify.sh", "integration", {"upgrade", "compose"}),
        ("deploy/compact/start.sh", "integration", {"compact", "compose"}),
        ("skills/flowtest-generate-integration-flow/SKILL.md", "standard", {"skills"}),
        (".github/workflows/required-gate.yml", "full", {"policy", "backend-full"}),
        ("scripts/build_skill_evaluation.py", "full", {"policy", "skills"}),
        ("new-area/输入 文档.md", "full", {"security", "windows"}),
    ],
)
def test_routing(path: str, tier: str, required: set[str]) -> None:
    result = plan([path])
    assert result.tier_floor == tier
    assert required <= set(result.required)


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/services/auth.py",
        "backend/app/services/oidc.py",
        "backend/app/http/oidc.py",
        "backend/app/api/dependencies.py",
        "backend/app/core/context.py",
        "backend/app/services/organizations.py",
        "backend/app/repositories/access.py",
    ],
)
def test_identity_boundaries_require_integration_consumers(path: str) -> None:
    selected = plan([path])
    assert selected.tier == "integration"
    assert {"backend-full", "frontend-full", "compose", "security"} <= set(selected.required)


def test_policy_entrypoints_use_isolated_python() -> None:
    workflow = (Path(__file__).parents[2] / ".github/workflows/pr-validation.yml").read_text()
    assert "python3 -I scripts/ci_plan.py" in workflow
    assert "python3 -I scripts/ci_summary.py" in workflow


def test_isolated_planner_ignores_adjacent_module(tmp_path: Path) -> None:
    shutil.copyfile(MODULE_PATH, tmp_path / "ci_plan.py")
    (tmp_path / "hashlib.py").write_text("raise RuntimeError('adjacent module loaded')\n")
    result = subprocess.run(
        [sys.executable, "-I", str(tmp_path / "ci_plan.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_labels_only_raise_scope() -> None:
    code = ["backend/app/domain/execution.py"]
    assert plan(code, {"ci:light"}).tier == "integration"
    full = plan(["README.md"], {"ci:light", "ci:milestone"})
    assert full.tier == "full"
    assert "security" in full.required
    assert plan(["README.md"], {"unrelated"}).tier == "docs"
    assert plan(["README.md"], {"ci:milestone"}).tier == "full"
    assert plan(["README.md"]).tier == "docs"
    assert len(plan(["README.md"]).policy_digest) == 64


def test_targets_include_direct_consumers_and_fallback() -> None:
    targeted = plan(["frontend/src/features/navigation/navigation-config.tsx"])
    assert "src/features/navigation/ShellSidebar.test.tsx" in targeted.frontend_targets
    assert "src/App.test.tsx" in targeted.frontend_targets
    assert (
        "src/App.test.tsx"
        in plan(["frontend/src/features/navigation/ShellSidebar.tsx"]).frontend_targets
    )
    assert plan(["backend/app/services/imports.py"]).backend_targets == (
        "tests/test_imports_api.py",
    )
    assert plan(["docs/release/s46-ga-gate.md"]).backend_targets == ("tests/test_s46_ga_gate.py",)
    assert plan(["backend/app/services/new_service.py"]).backend_targets == ()


def test_rename_considers_old_and_new_paths() -> None:
    result = plan(["docs/说明.md", "backend/app/domain/旧 引擎.py"])
    assert result.tier == "integration"
    assert "backend-full" in result.required


def test_special_filenames_remain_data() -> None:
    result = plan(["docs/中文 空格\n$(date).md"])
    assert result.tier == "docs"
    assert json.loads(result.to_json())["tier"] == "docs"


@pytest.mark.parametrize("paths", [[], [""], ["../README.md"], ["/tmp/file"], ["nul\x00path"]])
def test_invalid_paths_fail_closed(paths: list[str]) -> None:
    with pytest.raises(ci_plan.PlanError):
        plan(paths)


class StubGitHub(ci_plan.GitHub):
    def __init__(self, pages: dict[str, Any]) -> None:
        self.pages = pages

    def get(self, path: str) -> Any:
        return self.pages[path]


def pr_payload(count: int) -> dict[str, Any]:
    return {
        "state": "open",
        "changed_files": count,
        "base": {"sha": SHA},
        "head": {"sha": SHA},
        "labels": [],
    }


def test_api_pagination_and_rename() -> None:
    first = [{"filename": f"docs/{index}.md", "status": "modified"} for index in range(100)]
    client = StubGitHub(
        {
            "pulls/7": pr_payload(101),
            "pulls/7/files?per_page=100&page=1": first,
            "pulls/7/files?per_page=100&page=2": [
                {
                    "filename": "docs/新 名称.md",
                    "previous_filename": "backend/app/domain/旧.py",
                    "status": "renamed",
                }
            ],
        }
    )
    assert client.pr_plan(7, SHA).tier == "integration"


@pytest.mark.parametrize(
    "changed_count,files", [(0, []), (2, [{"filename": "README.md"}]), (3000, [])]
)
def test_incomplete_api_list_fails(changed_count: int, files: list[dict[str, str]]) -> None:
    client = StubGitHub(
        {"pulls/7": pr_payload(changed_count), "pulls/7/files?per_page=100&page=1": files}
    )
    with pytest.raises(ci_plan.PlanError):
        client.pr_plan(7, SHA)


def test_rename_without_previous_filename_fails() -> None:
    client = StubGitHub(
        {
            "pulls/7": pr_payload(1),
            "pulls/7/files?per_page=100&page=1": [{"filename": "docs/new.md", "status": "renamed"}],
        }
    )
    with pytest.raises(ci_plan.PlanError):
        client.pr_plan(7, SHA)


def test_pagination_failure_cannot_become_docs() -> None:
    class FailingGitHub(StubGitHub):
        def get(self, path: str) -> Any:
            if path.endswith("page=2"):
                raise ci_plan.PlanError("page 2 unavailable")
            return super().get(path)

    first = [{"filename": f"docs/{index}.md"} for index in range(100)]
    client = FailingGitHub({"pulls/7": pr_payload(101), "pulls/7/files?per_page=100&page=1": first})
    with pytest.raises(ci_plan.PlanError):
        client.pr_plan(7, SHA)


def test_changed_pr_snapshot_cannot_mix_file_versions() -> None:
    class MovingGitHub(StubGitHub):
        calls = 0

        def get(self, path: str) -> Any:
            if path == "pulls/7":
                self.calls += 1
                if self.calls == 2:
                    return {**pr_payload(1), "head": {"sha": "b" * 40}}
            return super().get(path)

    client = MovingGitHub(
        {"pulls/7": pr_payload(1), "pulls/7/files?per_page=100&page=1": [{"filename": "README.md"}]}
    )
    with pytest.raises(ci_plan.PlanError):
        client.pr_plan(7, SHA)


def test_irrelevant_pr_metadata_change_does_not_invalidate_plan() -> None:
    original = {
        **pr_payload(1),
        "base": {"sha": SHA, "repo": {"full_name": "a3384379/FlowTest", "pushed_at": "old"}},
        "labels": [{"name": "ci:milestone"}, {"name": "reviewed"}],
    }

    class MovingGitHub(StubGitHub):
        calls = 0

        def get(self, path: str) -> Any:
            if path == "pulls/7":
                self.calls += 1
                if self.calls == 2:
                    return {
                        **original,
                        "base": {
                            "sha": SHA,
                            "repo": {"full_name": "a3384379/FlowTest", "pushed_at": "new"},
                        },
                        "labels": [{"name": "ci:milestone"}, {"name": "unrelated"}],
                    }
            return super().get(path)

    client = MovingGitHub(
        {"pulls/7": original, "pulls/7/files?per_page=100&page=1": [{"filename": "README.md"}]}
    )
    assert client.pr_plan(7, SHA).tier == "full"


def test_only_one_automatic_pr_entry_and_workflow_call_reuse() -> None:
    root = Path(__file__).parents[2] / ".github/workflows"
    workflows = {
        path.name: yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for path in root.glob("*.yml")
    }
    automatic = [name for name, body in workflows.items() if "pull_request" in body["on"]]
    assert automatic == ["pr-validation.yml"]
    assert "paths" not in workflows["pr-validation.yml"]["on"]["pull_request"]
    assert "workflow_dispatch" not in workflows["required-gate.yml"]["on"]
    assert "workflow_run" in workflows["required-gate.yml"]["on"]
    assert "pull_request_target" not in workflows["required-gate.yml"]["on"]
    assert workflows["required-gate.yml"]["on"]["workflow_run"]["types"] == [
        "requested",
        "in_progress",
        "completed",
    ]
    assert "github.run_id" in workflows["pr-validation.yml"]["concurrency"]["group"]
    assert "opened" in workflows["pr-validation.yml"]["on"]["pull_request"]["types"]
    assert "synchronize" in workflows["pr-validation.yml"]["on"]["pull_request"]["types"]
    for name in (
        "quick-ci.yml",
        "backend-ci.yml",
        "frontend-ci.yml",
        "compose-ci.yml",
        "security-ci.yml",
        "standalone-windows.yml",
        "upgrade-ci.yml",
        "skills-ci.yml",
    ):
        assert "workflow_call" in workflows[name]["on"]
        assert "pull_request" not in workflows[name]["on"]
