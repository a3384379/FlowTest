import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

WORKSPACE_ROOT = Path(__file__).parents[2]


def _required_gate_module() -> ModuleType:
    script_path = WORKSPACE_ROOT / "scripts" / "required_gate.py"
    spec = importlib.util.spec_from_file_location("flowtest_required_gate", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


required_gate = _required_gate_module()


def _keys(plan) -> set[str]:
    return {spec.key for spec in plan.required}


def test_required_gate_marks_irrelevant_checks_as_no_op() -> None:
    plan = required_gate.build_gate_plan(["docs/release/notes.md"])

    assert _keys(plan) == {"security"}
    assert {spec.key for spec in plan.no_op} == {
        "backend",
        "frontend",
        "compose",
        "standalone",
        "upgrade",
    }


def test_required_gate_selects_backend_dependent_checks() -> None:
    plan = required_gate.build_gate_plan(["backend/app/services/projects.py"])

    assert _keys(plan) == {"backend", "security", "compose", "standalone", "upgrade"}


def test_required_gate_selects_frontend_dependent_checks() -> None:
    plan = required_gate.build_gate_plan(["frontend/src/main.tsx"])

    assert _keys(plan) == {"frontend", "security", "compose", "standalone"}


@pytest.mark.parametrize("path", sorted(required_gate.CI_GOVERNANCE_PATHS))
def test_required_gate_blocks_pr_ci_governance_changes(path: str) -> None:
    with pytest.raises(required_gate.RequiredGateError, match="Bootstrap"):
        required_gate.enforce_trusted_governance([path], "pull_request_target")


def test_required_gate_blocks_new_workflow_that_could_spoof_required_context() -> None:
    with pytest.raises(required_gate.RequiredGateError, match="Bootstrap"):
        required_gate.enforce_trusted_governance(
            [".github/workflows/spoof-required-gate.yml"], "pull_request_target"
        )


def test_required_gate_allows_normal_pr_and_trusted_push_paths() -> None:
    required_gate.enforce_trusted_governance(
        ["backend/app/services/projects.py"], "pull_request_target"
    )
    required_gate.enforce_trusted_governance([".github/workflows/required-gate.yml"], "push")


def test_required_gate_path_rules_match_child_workflow_triggers() -> None:
    for gate_spec in required_gate.GATE_SPECS:
        if gate_spec.always_required:
            continue
        workflow = yaml.load(
            (WORKSPACE_ROOT / gate_spec.workflow_path).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        workflow_paths = set(workflow["on"]["pull_request"]["paths"])
        workflow_prefixes = {
            pattern.removesuffix("**") for pattern in workflow_paths if pattern.endswith("/**")
        }
        workflow_exact_paths = {
            pattern for pattern in workflow_paths if not pattern.endswith("/**")
        }

        assert set(gate_spec.prefixes) == workflow_prefixes
        assert set(gate_spec.exact_paths) == workflow_exact_paths


def test_required_gate_controller_runs_trusted_base_code() -> None:
    workflow = yaml.load(
        (WORKSPACE_ROOT / ".github/workflows/required-gate.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert "pull_request_target" in workflow["on"]
    assert "pull_request" not in workflow["on"]
    assert "edited" in workflow["on"]["pull_request_target"]["types"]
    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert "github.event.pull_request.number" in workflow["concurrency"]["group"]
    assert workflow["permissions"]["statuses"] == "write"
    assert "checks" not in workflow["permissions"]
    controller = workflow["jobs"]["controller"]
    assert controller["name"] == "Required Gate Controller"
    checkout = next(step for step in controller["steps"] if "uses" in step)
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha || github.sha }}"
    assert checkout["with"]["persist-credentials"] == "false"
    create_status = next(
        step
        for step in controller["steps"]
        if step.get("name") == "Create trusted Required Gate status"
    )
    assert '"repos/${GITHUB_REPOSITORY}/statuses/${HEAD_SHA}"' in create_status["run"]
    assert "-f context='Required Gate'" in create_status["run"]
    assert "-f state='pending'" in create_status["run"]
    assert controller["steps"].index(create_status) < controller["steps"].index(checkout)
    resolve_paths = next(
        step
        for step in controller["steps"]
        if step.get("name") == "Resolve changed paths from trusted metadata"
    )
    assert ".previous_filename" in resolve_paths["run"]
    assert "-ge 3000" in resolve_paths["run"]
    complete_status = next(
        step
        for step in controller["steps"]
        if step.get("name") == "Complete trusted Required Gate status"
    )
    assert complete_status["if"] == "always()"
    assert ".base.sha, .head.sha" in complete_status["run"]
    assert '"${BASE_SHA} ${HEAD_SHA}"' in complete_status["run"]
