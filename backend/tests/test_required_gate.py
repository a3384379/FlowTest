import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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


def test_required_gate_governance_changes_are_linted() -> None:
    workflow_plan = required_gate.build_gate_plan([".github/workflows/required-gate.yml"])
    script_plan = required_gate.build_gate_plan(["scripts/required_gate.py"])

    assert _keys(workflow_plan) == {"backend", "security"}
    assert _keys(script_plan) == {"backend", "security"}


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
