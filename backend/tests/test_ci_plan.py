"""Characterize the trusted, deterministic PR routing policy."""

from __future__ import annotations

import configparser
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


def plan(
    paths: list[str],
    labels: set[str] | None = None,
    removed_paths: frozenset[str] = frozenset(),
) -> Any:
    return ci_plan.build_plan(
        paths,
        labels or set(),
        base_sha=SHA,
        head_sha=SHA,
        tested_sha=SHA,
        removed_paths=removed_paths,
    )


@pytest.mark.parametrize(
    ("path", "tier", "required"),
    [
        ("README.md", "docs", {"quick"}),
        ("docs/release/s46-ga-gate.md", "standard", {"backend-standard"}),
        ("frontend/src/features/navigation/ShellSidebar.tsx", "standard", {"frontend-standard"}),
        ("backend/app/services/imports.py", "standard", {"backend-standard"}),
        ("backend/app/domain/execution.py", "integration", {"backend-full", "compose"}),
        ("backend/app/core/security.py", "integration", {"backend-full", "compose"}),
        (
            "backend/migrations/versions/20260809_0001_access_control.py",
            "integration",
            {"upgrade", "windows", "backend-full"},
        ),
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


def test_alembic_config_and_real_migration_root_are_routed() -> None:
    root = Path(__file__).parents[2]
    config = configparser.ConfigParser()
    config.read(root / "backend/alembic.ini")
    migration_root = root / "backend" / config["alembic"]["script_location"]
    assert migration_root.is_dir()
    assert migration_root == root / "backend/migrations"
    for path in (
        "backend/alembic.ini",
        "backend/migrations/env.py",
        "backend/migrations/versions/20260809_0001_access_control.py",
        "backend/app/models/workflows.py",
        "backend/app/repositories/workflows.py",
    ):
        selected = plan([path])
        assert selected.tier == "integration"
        assert {"backend-full", "upgrade", "windows"} <= set(selected.required)


@pytest.mark.parametrize("labels", [set(), {"ci:light"}])
@pytest.mark.parametrize(
    "paths",
    [
        ["backend/app/core/standalone_schema.py"],
        ["backend/app/core/standalone_schema.py", "backend/tests/test_standalone_runtime.py"],
    ],
)
def test_standalone_schema_requires_runtime_validation(paths: list[str], labels: set[str]) -> None:
    selected = plan(paths, labels)
    assert selected.tier_floor == "integration"
    assert set(selected.required) == {"quick", "backend-full", "windows"}


@pytest.mark.parametrize("labels", [set(), {"ci:light"}])
@pytest.mark.parametrize(
    "paths",
    [
        ["backend/app/migrations_support/canonical_contract_v2.py"],
        [
            "backend/app/migrations_support/canonical_contract_v2.py",
            "backend/tests/test_s47_3_semantic_integrity.py",
        ],
    ],
)
def test_shared_migration_helper_requires_both_upgrade_shapes(
    paths: list[str], labels: set[str]
) -> None:
    selected = plan(paths, labels)
    assert selected.tier_floor == "integration"
    assert set(selected.required) == {"quick", "backend-full", "windows", "upgrade"}


@pytest.mark.parametrize("status", ["removed", "renamed"])
def test_removed_or_renamed_migration_helper_keeps_upgrade_risk(status: str) -> None:
    helper = "backend/app/migrations_support/canonical_contract_v2.py"
    item = {"filename": helper, "status": status}
    if status == "renamed":
        item = {
            "filename": "backend/app/core/storage.py",
            "previous_filename": helper,
            "status": status,
        }
    files = [item]
    selected = plan(
        ci_plan._paths_from_files(files),
        removed_paths=ci_plan._removed_paths_from_files(files),
    )
    assert selected.tier_floor == "integration"
    assert {"backend-full", "windows", "upgrade"} <= set(selected.required)
    assert selected.backend_targets == ()


def test_unrelated_backend_helper_keeps_standard_scope() -> None:
    selected = plan(["backend/app/core/storage.py"])
    assert set(selected.required) == {"quick", "backend-standard"}


def test_api_schema_keeps_consumers_without_database_upgrade() -> None:
    selected = plan(["backend/app/schemas/workflows.py"])
    assert selected.tier_floor == "integration"
    assert set(selected.required) == {"quick", "backend-full", "frontend-full", "compose"}


@pytest.mark.parametrize(
    ("path", "required"),
    [
        ("backend/docker-bake.ci.hcl", {"policy", "backend-full", "compose", "security"}),
        ("backend/Dockerfile", {"backend-full", "compose", "security"}),
        ("backend/.dockerignore", {"backend-full", "compose", "security"}),
        (
            "backend/patches/cpython-3.13-cve-2026-82049.patch",
            {"backend-full", "compose", "security"},
        ),
        ("frontend/nginx.conf", {"frontend-full", "compose", "security"}),
        ("frontend/.dockerignore", {"frontend-full", "compose", "security"}),
        ("mock-target/Dockerfile", {"compose", "security"}),
        ("mock-target/pyproject.toml", {"compose", "security"}),
        ("mock-target/uv.lock", {"compose", "security"}),
        ("deploy/compact/images.env.example", {"compact", "compose", "security"}),
    ],
)
def test_real_image_inputs_require_build_and_scan(path: str, required: set[str]) -> None:
    assert (Path(__file__).parents[2] / path).exists()
    selected = plan([path], {"ci:light"})
    assert required <= set(selected.required)
    assert selected.tier in {"integration", "full"}


def test_governance_and_compact_change_still_requires_compact() -> None:
    selected = plan(["scripts/ci_plan.py", "deploy/compact/compose.yaml"])
    assert selected.governance_change
    assert {"policy", "compact"} <= set(selected.required)


def test_postgres_walg_image_is_built_verified_and_scanned() -> None:
    root = Path(__file__).parents[2]
    bake = (root / "backend/docker-bake.ci.hcl").read_text()
    security_group = bake.split('group "ci-security" {', 1)[1].split("}", 1)[0]
    assert '"postgres"' in security_group
    workflow = yaml.load(
        (root / ".github/workflows/security-ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    steps = workflow["jobs"]["source-and-images"]["steps"]
    identity_step = next(
        step for step in steps if step.get("name") == "Verify scanned image identities"
    )
    assert "flowtest-postgres-walg:17.11-v3.0.9-patched" in identity_step["run"]
    scan = next(step for step in steps if step.get("name") == "Scan Postgres WALG image")
    assert scan["with"]["image"] == "flowtest-postgres-walg:17.11-v3.0.9-patched"
    compose_workflow = yaml.load(
        (root / ".github/workflows/compose-ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    compose_steps = compose_workflow["jobs"]["smoke"]["steps"]
    compose_identity = next(
        step
        for step in compose_steps
        if step.get("name") == "Verify loaded Compose image identities"
    )
    assert scan["with"]["image"] in compose_identity["run"]


def test_renamed_image_input_uses_both_directories() -> None:
    paths = ci_plan._paths_from_files(
        [
            {
                "filename": "frontend/nginx.conf",
                "previous_filename": "backend/.dockerignore",
                "status": "renamed",
            }
        ]
    )
    selected = plan(paths)
    assert {"backend-full", "frontend-full", "compose", "security"} <= set(selected.required)


@pytest.mark.parametrize("old_path", ["mock-target/pyproject.toml", "mock-target/uv.lock"])
def test_renamed_mock_dependency_keeps_old_image_risk(old_path: str) -> None:
    files = [
        {"filename": "docs/mock-dependency.md", "previous_filename": old_path, "status": "renamed"}
    ]
    paths = ci_plan._paths_from_files(files)
    selected = plan(
        paths,
        {"ci:light"},
        ci_plan._removed_paths_from_files(files),
    )
    assert selected.tier_floor == "integration"
    assert {"quick", "compose", "security"} <= set(selected.required)


@pytest.mark.parametrize("path", ["mock-target/pyproject.toml", "mock-target/uv.lock"])
def test_mock_dependency_requires_security_without_label(path: str) -> None:
    selected = plan([path])
    assert set(selected.required) == {"quick", "compose", "security"}


def test_mock_application_source_does_not_require_image_scan() -> None:
    selected = plan(["mock-target/app/main.py"])
    assert set(selected.required) == {"quick", "compose"}


@pytest.mark.parametrize("labels", [set(), {"ci:light"}])
@pytest.mark.parametrize(
    "path",
    [
        "frontend/e2e/workflow-editor-audit.spec.ts",
        "frontend/e2e/support/auth.ts",
        "frontend/e2e/workflow-editor-visual.spec.ts-snapshots/1280x800-01-default-edit-chromium-linux.png",
        "frontend/playwright.config.ts",
    ],
)
def test_playwright_inputs_require_browser_acceptance(path: str, labels: set[str]) -> None:
    selected = plan([path], labels)
    assert selected.tier_floor == "standard"
    assert set(selected.required) == {"quick", "frontend-standard", "compose"}


def test_playwright_input_with_unit_test_keeps_browser_acceptance() -> None:
    selected = plan(["frontend/e2e/support/auth.ts", "frontend/src/App.test.tsx"])
    assert "compose" in selected.required


@pytest.mark.parametrize("status", ["removed", "renamed"])
def test_removed_or_renamed_playwright_input_keeps_browser_acceptance(status: str) -> None:
    old_path = "frontend/e2e/workflow-editor-audit.spec.ts"
    item = {"filename": old_path, "status": status}
    if status == "renamed":
        item = {"filename": "docs/e2e-notes.md", "previous_filename": old_path, "status": status}
    files = [item]
    selected = plan(
        ci_plan._paths_from_files(files),
        removed_paths=ci_plan._removed_paths_from_files(files),
    )
    assert "compose" in selected.required


def test_compose_browser_steps_require_playwright_execution() -> None:
    root = Path(__file__).parents[2]
    workflow = yaml.load(
        (root / ".github/workflows/compose-ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    smoke = workflow["jobs"]["smoke"]
    assert "continue-on-error" not in smoke
    steps = {step.get("name"): step for step in smoke["steps"]}
    assert "e2e:setup" in steps["Authenticate browser acceptance session"]["run"]
    s29 = steps["Verify S29 browser acceptance flow"]
    remaining = steps["Verify non-S29 browser acceptance flow"]
    assert "playwright test" in s29["run"]
    assert "e2e/s29-execution-fabric.spec.ts" in s29["run"]
    assert "playwright test" in remaining["run"]
    assert '--grep-invert "S29 Worker"' in remaining["run"]
    for step in (s29, remaining):
        assert "if" not in step
        assert "continue-on-error" not in step
        assert "--pass-with-no-tests" not in step["run"]
        assert "|| true" not in step["run"]
    config = (root / "frontend/playwright.config.ts").read_text()
    assert "testDir: './e2e'" in config
    assert "forbidOnly: Boolean(process.env.CI)" in config


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


def test_changed_tests_join_known_source_targets() -> None:
    backend = plan(["backend/app/services/imports.py", "backend/tests/test_imports_api.py"])
    assert backend.backend_targets == ("tests/test_imports_api.py",)
    assert plan(["backend/tests/test_imports_api.py"]).backend_targets == (
        "tests/test_imports_api.py",
    )
    frontend = plan(
        [
            "frontend/src/features/navigation/ShellSidebar.tsx",
            "frontend/src/features/navigation/ShellSidebar.test.tsx",
        ]
    )
    assert "src/features/navigation/ShellSidebar.test.tsx" in frontend.frontend_targets
    assert "src/App.test.tsx" in frontend.frontend_targets
    assert plan(["backend/tests/test_new_feature.py"]).backend_targets == (
        "tests/test_new_feature.py",
    )


@pytest.mark.parametrize(
    "paths",
    [
        ["backend/app/services/imports.py", "backend/app/services/new_service.py"],
        ["backend/app/services/imports.py", "backend/tests/conftest.py"],
    ],
)
def test_unknown_or_removed_backend_input_falls_back_to_full_side(paths: list[str]) -> None:
    assert plan(paths).backend_targets == ()


def test_removed_or_renamed_test_falls_back_on_pr_metadata() -> None:
    old = "backend/tests/test_imports_api.py"
    assert plan([old], removed_paths=frozenset({old})).backend_targets == ()
    files = [
        {
            "filename": "backend/tests/test_imports_api_v2.py",
            "previous_filename": old,
            "status": "renamed",
        }
    ]
    paths = ci_plan._paths_from_files(files)
    removed = ci_plan._removed_paths_from_files(files)
    assert plan(paths, removed_paths=removed).backend_targets == ()
    assert ci_plan._removed_paths_from_files([{"filename": old, "status": "removed"}]) == {old}


def test_unknown_or_removed_frontend_input_falls_back_to_full_side() -> None:
    assert (
        plan(
            ["frontend/src/features/navigation/ShellSidebar.tsx", "frontend/vitest.config.ts"]
        ).frontend_targets
        == ()
    )
    old = "frontend/src/features/navigation/Removed.test.tsx"
    assert plan([old], removed_paths=frozenset({old})).frontend_targets == ()


def test_targeted_runner_propagates_no_tests_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_path = Path(__file__).parents[2] / "scripts/run_targeted_tests.py"
    spec = importlib.util.spec_from_file_location("run_targeted_tests", runner_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setenv("TARGETS", json.dumps(["tests/test_ci_plan.py"]))
    monkeypatch.setattr(sys, "argv", [str(runner_path), "backend"])
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 5),
    )
    assert runner.main() == 5


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


def test_automatic_pr_entries_and_workflow_call_reuse() -> None:
    root = Path(__file__).parents[2] / ".github/workflows"
    workflows = {
        path.name: yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for path in root.glob("*.yml")
    }
    automatic = [name for name, body in workflows.items() if "pull_request" in body["on"]]
    assert set(automatic) == {"pr-validation.yml", "ci-bootstrap-validation.yml"}
    assert "paths" not in workflows["pr-validation.yml"]["on"]["pull_request"]
    bootstrap = workflows["ci-bootstrap-validation.yml"]
    assert set(bootstrap["on"]["pull_request"]["paths"]) == set(ci_plan.GOVERNANCE_FILES) | {
        f"{prefix}**" for prefix in ci_plan.GOVERNANCE_PREFIXES
    }
    assert bootstrap["permissions"] == {"contents": "read"}
    assert bootstrap["concurrency"]["cancel-in-progress"] == "true"
    assert "github.event.pull_request.number" in bootstrap["concurrency"]["group"]
    assert set(bootstrap["jobs"]) == {
        "bootstrap-quick",
        "bootstrap-backend",
        "bootstrap-frontend",
        "bootstrap-compose",
        "bootstrap-security",
        "bootstrap-windows",
        "bootstrap-upgrade",
        "bootstrap-skills",
    }
    assert "workflow_dispatch" not in workflows["required-gate.yml"]["on"]
    assert "workflow_run" in workflows["required-gate.yml"]["on"]
    assert "pull_request_target" not in workflows["required-gate.yml"]["on"]
    assert workflows["required-gate.yml"]["on"]["workflow_run"]["types"] == [
        "requested",
        "in_progress",
        "completed",
    ]
    publisher_concurrency = workflows["required-gate.yml"]["concurrency"]
    assert "github.event.workflow_run.head_sha" in publisher_concurrency["group"]
    assert publisher_concurrency["queue"] == "max"
    assert publisher_concurrency["cancel-in-progress"] == "false"
    active_group = workflows["pr-validation.yml"]["concurrency"]["group"]
    assert "github.run_id" not in active_group
    assert "'ignored'" in active_group and "'active'" in active_group
    assert "github.event.label.name" in active_group
    assert workflows["pr-validation.yml"]["concurrency"]["cancel-in-progress"] == "true"
    for name, job in workflows["pr-validation.yml"]["jobs"].items():
        if name != "compact" and job.get("needs") == "plan":
            assert "governance_change" in job["if"]
    assert set(ci_plan.ALL_JOBS) - {"policy"} <= set(workflows["pr-validation.yml"]["jobs"])
    compact = workflows["pr-validation.yml"]["jobs"]["compact"]
    assert "governance_change" not in compact["if"]
    assert "compact" in workflows["pr-validation.yml"]["jobs"]["shadow"]["needs"]
    assert "run_rc_gates" not in str(compact)
    assert "./deploy/compact/start.sh" in str(compact)
    assert "scripts/smoke_s32.py" in str(compact)
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
