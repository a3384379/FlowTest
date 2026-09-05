from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.domain.v6_evaluation import EvaluationAnnotation, build_evaluation_baseline
from app.domain.v6_skill import IntegrationFlowSkillManifest

WORKSPACE_ROOT = Path(__file__).parents[2]
SKILL_ROOT = WORKSPACE_ROOT / "skills/flowtest-generate-integration-flow"

# Run outside the checkout and fail if the standalone evaluator imports the application or uses
# a network connection. Pydantic remains an explicitly declared runtime dependency.
ISOLATED_RUNNER = """
import importlib.abc
import runpy
import socket
import sys
from pathlib import Path

class BlockApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app' or fullname.startswith('app.'):
            raise AssertionError('standalone evaluator imported FlowTest')
        return None

def no_network(*args, **kwargs):
    raise AssertionError('standalone evaluator accessed the network')

sys.meta_path.insert(0, BlockApplication())
socket.socket.connect = no_network
socket.create_connection = no_network
entrypoint = Path(sys.argv[1])
sys.path.insert(0, str(entrypoint.parent))
sys.argv = sys.argv[1:]
runpy.run_path(str(entrypoint), run_name='__main__')
"""


@pytest.fixture
def installed_skill(tmp_path: Path) -> Path:
    return Path(
        shutil.copytree(
            SKILL_ROOT, tmp_path / "installed-skill", ignore=shutil.ignore_patterns("__pycache__")
        )
    )


def _run(package: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            ISOLATED_RUNNER,
            str(package / "evals/evaluate.py"),
            *arguments,
        ],
        cwd=package.parent,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _annotations(package: Path) -> list[dict[str, Any]]:
    return json.loads((package / "evals/annotations.json").read_text(encoding="utf-8"))


def _save_annotations(package: Path, annotations: list[dict[str, Any]]) -> None:
    (package / "evals/annotations.json").write_text(json.dumps(annotations), encoding="utf-8")


def test_package_evaluates_outside_repository_without_application_or_network(
    installed_skill: Path,
) -> None:
    checked = _run(installed_skill, "--check")
    assert checked.returncode == 0, checked.stderr
    assert "backend tests were not executed" in checked.stdout
    report = _run(installed_skill)
    assert report.returncode == 0, report.stderr
    expected = build_evaluation_baseline(
        [EvaluationAnnotation.model_validate(item) for item in _annotations(installed_skill)]
    )
    assert json.loads(report.stdout) == expected.model_dump(mode="json")


def test_packaged_generated_sources_match_canonical_bytes() -> None:
    checked = subprocess.run(
        [sys.executable, str(WORKSPACE_ROOT / "scripts/build_skill_evaluation.py"), "--check"],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    provenance = json.loads((SKILL_ROOT / "evals/source-map.json").read_text(encoding="utf-8"))
    assert provenance["executes_backend_tests"] is False
    for packaged, source in provenance["files"].items():
        assert (SKILL_ROOT / "evals" / packaged).read_bytes() == (
            WORKSPACE_ROOT / source
        ).read_bytes()


def test_runtime_manifest_resolves_after_copy_and_preserves_legacy_contract(
    installed_skill: Path,
) -> None:
    payload = yaml.safe_load((installed_skill / "manifest.yaml").read_text(encoding="utf-8"))
    manifest = IntegrationFlowSkillManifest.model_validate(payload)
    evaluation = manifest.evaluation
    assert evaluation.runtime is not None
    for reference in (
        evaluation.annotations,
        evaluation.baseline,
        evaluation.guide,
        evaluation.runtime.entrypoint,
        evaluation.runtime.requirements,
        evaluation.runtime.source_map,
    ):
        resolved = (installed_skill / reference).resolve()
        assert installed_skill.resolve() in resolved.parents
        assert resolved.is_file()
    payload["evaluation"].pop("runtime")
    payload["version"] = "1.0.0-rc.1"
    payload["evaluation"]["annotations"] = (
        "backend/tests/fixtures/v6_golden/evaluation-annotations.json"
    )
    assert IntegrationFlowSkillManifest.model_validate(payload).evaluation.runtime is None


@pytest.mark.parametrize(
    "path",
    ["../outside.json", "/tmp/data.json", "https://example.com/x", "a\\b", "a/../b", "./a", "."],
)
def test_runtime_manifest_rejects_non_package_paths(path: str) -> None:
    payload = yaml.safe_load((SKILL_ROOT / "manifest.yaml").read_text(encoding="utf-8"))
    payload["evaluation"]["runtime"]["entrypoint"] = path
    with pytest.raises(ValidationError, match="package-relative"):
        IntegrationFlowSkillManifest.model_validate(payload)


def test_failed_hard_gate_is_nonzero_even_without_check(installed_skill: Path) -> None:
    annotations = _annotations(installed_skill)
    next(item for item in annotations if item["metric"] == "secret_leak")["label"] = "yes"
    _save_annotations(installed_skill, annotations)
    report = _run(installed_skill)
    assert report.returncode == 1
    assert json.loads(report.stdout)["release_gates_passed"] is False
    # Even a baseline regenerated from a failure cannot make --check pass.
    (installed_skill / "evals/baseline.json").write_text(report.stdout, encoding="utf-8")
    assert _run(installed_skill, "--check").returncode == 1


def test_missing_hard_gate_evidence_is_not_success(installed_skill: Path) -> None:
    annotations = [
        item for item in _annotations(installed_skill) if item["metric"] != "secret_leak"
    ]
    _save_annotations(installed_skill, annotations)
    report = _run(installed_skill)
    assert report.returncode == 1
    metric = next(
        item for item in json.loads(report.stdout)["metrics"] if item["metric"] == "secret_leak"
    )
    assert metric["denominator"] == 0
    assert metric["value"] is None
    assert metric["gate_status"] == "insufficient_evidence"


def test_changed_informational_result_still_invalidates_baseline(installed_skill: Path) -> None:
    annotations = _annotations(installed_skill)
    annotations[0]["label"] = "false_positive"
    _save_annotations(installed_skill, annotations)
    assert _run(installed_skill).returncode == 0
    assert _run(installed_skill, "--check").returncode == 1


@pytest.mark.parametrize("mutation", ["duplicate_case", "invalid_label", "extra_field"])
def test_malformed_annotations_fail_without_echoing_values(
    installed_skill: Path, mutation: str
) -> None:
    annotations = _annotations(installed_skill)
    sensitive_marker = "DO-NOT-ECHO-PRIVATE-EVALUATION-VALUE"
    if mutation == "duplicate_case":
        annotations.append(annotations[0])
    elif mutation == "invalid_label":
        annotations[0]["label"] = sensitive_marker
    else:
        annotations[0]["private_input"] = sensitive_marker
    _save_annotations(installed_skill, annotations)
    result = _run(installed_skill, "--check")
    assert result.returncode == 1
    assert sensitive_marker not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "payload",
    [b'[{"metric":1,"metric":2}]', b"[]", b"x" * 5_000_001, b"\xff", b"[" * 2000],
    ids=["duplicate-key", "empty", "oversized", "invalid-utf8", "deep-nesting"],
)
def test_invalid_or_oversized_json_fails_closed(installed_skill: Path, payload: bytes) -> None:
    (installed_skill / "evals/annotations.json").write_bytes(payload)
    result = _run(installed_skill, "--check")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_output_and_conflicting_options(installed_skill: Path) -> None:
    output = installed_skill.parent / "report.json"
    result = _run(installed_skill, "--output", str(output))
    assert result.returncode == 0
    assert json.loads(output.read_text())["release_gates_passed"] is True
    assert _run(installed_skill, "--output", str(output), "--check").returncode == 2
    assert (
        _run(installed_skill, "--annotations", str(installed_skill / "missing.json")).returncode
        == 1
    )
