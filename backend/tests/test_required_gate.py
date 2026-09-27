"""Trusted status publisher must not accept stale or incomplete PR runs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT_ROOT = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPT_ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ci_plan = load_script("ci_plan")
ci_summary = load_script("ci_summary")
gate = load_script("required_gate")
SHA = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
REPO = "a3384379/FlowTest"


def plan(paths: list[str] | None = None) -> Any:
    return ci_plan.build_plan(
        paths or ["README.md"], set(), base_sha=BASE, head_sha=SHA, tested_sha=MERGE
    )


def run_for(selected: Any, *, conclusion: str = "success", run_id: int = 42) -> dict[str, Any]:
    return {
        "id": run_id,
        "repository": {"full_name": REPO},
        "workflow_id": 99,
        "path": ".github/workflows/pr-validation.yml@refs/pull/7/merge",
        "event": "pull_request",
        "display_title": "PR Validation active",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": conclusion,
    }


def jobs_for(
    selected: Any, *, plan_result: str = "success", shadow_result: str = "success", run_id: int = 42
) -> list[dict[str, Any]]:
    return [
        {
            "name": f"CI Plan {MERGE}",
            "run_id": run_id,
            "status": "completed",
            "conclusion": plan_result,
        },
        {
            "name": f"PR Validation Shadow {MERGE} {gate.fingerprint(selected)}",
            "run_id": run_id,
            "status": "completed",
            "conclusion": shadow_result,
        },
    ]


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "timed_out", "missing"])
def test_shadow_refuses_required_job_without_real_success(result: str) -> None:
    selected = plan()
    needs = {"plan": {"result": "success"}, "quick": {"result": result}}
    valid, lines = ci_summary.evaluate(json.loads(selected.to_json()), needs)
    assert not valid
    assert any(f"quick: {result}" in line for line in lines)


def test_shadow_records_not_applicable_separately() -> None:
    selected = plan()
    valid, lines = ci_summary.evaluate(
        json.loads(selected.to_json()),
        {"plan": {"result": "success"}, "quick": {"result": "success"}},
    )
    assert valid
    assert "windows: not_applicable" in lines


def test_shadow_job_contract_matches_planner() -> None:
    assert ci_summary.ALL_JOBS == ci_plan.ALL_JOBS


@pytest.mark.parametrize(
    "payload",
    [None, {"required": []}, {"required": ["quick", "quick"]}, {"required": ["nonexistent"]}],
)
def test_invalid_plan_fails(payload: dict[str, Any] | None) -> None:
    assert not ci_summary.evaluate(payload, {})[0]


def test_shadow_rejects_failed_plan_and_inconsistent_not_applicable() -> None:
    selected = json.loads(plan().to_json())
    assert not ci_summary.evaluate(selected, {"plan": {"result": "failure"}})[0]
    selected["not_applicable"] = []
    assert not ci_summary.evaluate(selected, {"plan": {"result": "success"}})[0]


def test_current_run_must_match_plan_fingerprint_and_tested_sha() -> None:
    selected = plan()
    assert gate.evaluate_run(run_for(selected), jobs_for(selected), selected, REPO, 99)[0]
    changed = ci_plan.build_plan(
        ["README.md"], {"ci:milestone"}, base_sha=BASE, head_sha=SHA, tested_sha=MERGE
    )
    assert not gate.evaluate_run(run_for(selected), jobs_for(selected), changed, REPO, 99)[0]
    wrong_sha = ci_plan.build_plan(
        ["README.md"], set(), base_sha=BASE, head_sha=SHA, tested_sha="d" * 40
    )
    assert not gate.evaluate_run(run_for(selected), jobs_for(selected), wrong_sha, REPO, 99)[0]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda run: run.update({"workflow_id": 88}),
        lambda run: run.update({"head_sha": BASE}),
        lambda run: run.update({"event": "workflow_dispatch"}),
        lambda run: run.update({"display_title": "PR Validation ignored"}),
        lambda run: run.update({"repository": {"full_name": "other/repo"}}),
        lambda run: run.update({"conclusion": "failure"}),
    ],
)
def test_wrong_run_identity_or_result_rejected(mutation: Any) -> None:
    selected = plan()
    run = run_for(selected)
    mutation(run)
    assert not gate.evaluate_run(run, jobs_for(selected), selected, REPO, 99)[0]


def test_same_named_job_from_other_run_is_rejected() -> None:
    selected = plan()
    assert not gate.evaluate_run(
        run_for(selected), jobs_for(selected, run_id=41), selected, REPO, 99
    )[0]


def test_missing_or_skipped_shadow_rejected() -> None:
    selected = plan()
    assert not gate.evaluate_run(
        run_for(selected), jobs_for(selected, shadow_result="skipped"), selected, REPO, 99
    )[0]
    assert not gate.evaluate_run(run_for(selected), jobs_for(selected)[:1], selected, REPO, 99)[0]


def test_governance_change_cannot_self_approve() -> None:
    selected = plan(["scripts/ci_plan.py"])
    assert not gate.evaluate_run(run_for(selected), jobs_for(selected), selected, REPO, 99)[0]
    valid, lines = ci_summary.evaluate(
        json.loads(selected.to_json()), {"plan": {"result": "success"}}
    )
    assert not valid
    assert "backend-full: bootstrap_only" in lines
    assert not any("missing" in line for line in lines)


def test_compact_requires_its_own_successful_compatibility_job() -> None:
    selected = json.loads(plan(["deploy/compact/start.sh"]).to_json())
    needs = {
        "plan": {"result": "success"},
        "quick": {"result": "success"},
        "compose": {"result": "success"},
    }
    assert not ci_summary.evaluate(selected, needs)[0]
    assert not ci_summary.evaluate(selected, {**needs, "compact": {"result": "failure"}})[0]
    assert ci_summary.evaluate(selected, {**needs, "compact": {"result": "success"}})[0]


class FakeGitHub:
    def __init__(self, pages: dict[str, Any]) -> None:
        self.pages = pages

    def get(self, path: str) -> Any:
        return self.pages[path]


@pytest.mark.parametrize(
    "run_status,latest_id,expected_posts,expected_checked",
    [
        ("in_progress", 42, 1, 0),
        ("completed", 42, 0, 1),
        ("in_progress", 43, 0, 0),
    ],
)
def test_wakeup_reconciles_actual_run_state(
    monkeypatch: pytest.MonkeyPatch,
    run_status: str,
    latest_id: int,
    expected_posts: int,
    expected_checked: int,
) -> None:
    class FakePublisher(FakeGitHub):
        repository = REPO

        def __init__(self, pages: dict[str, Any]) -> None:
            super().__init__(pages)
            self.posts: list[tuple[str, str]] = []

        def post(self, sha: str, state: str, description: str, run_id: int) -> None:
            self.posts.append((sha, state))

    pr = {
        "state": "open",
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": SHA, "ref": "feature", "repo": {"full_name": REPO}},
    }
    notified = {
        "id": 42,
        "run_attempt": 1,
        "head_sha": SHA,
        "display_title": "PR Validation active",
        "repository": {"full_name": REPO},
        "pull_requests": [{"number": 7}],
    }
    latest = {
        "id": latest_id,
        "run_attempt": 1,
        "display_title": "PR Validation active",
        "head_branch": "feature",
        "head_repository": {"full_name": REPO},
    }
    run = {**run_for(plan()), "status": run_status, "run_attempt": 1}
    run_path = (
        f"actions/workflows/pr-validation.yml/runs?event=pull_request&head_sha={SHA}&per_page=100"
    )
    gh = FakePublisher(
        {
            "pulls/7": pr,
            run_path: {"total_count": 1, "workflow_runs": [latest]},
            "actions/workflows/pr-validation.yml": {"id": 99},
            "actions/runs/42": run,
        }
    )
    checked: list[int] = []
    monkeypatch.setattr(
        gate,
        "publish_checked_run",
        lambda _gh, _notified, _pr, number, _current: checked.append(number),
    )
    gate.publish_current_run(gh, {"workflow_run": notified}, "main")
    assert len(gh.posts) == expected_posts
    assert len(checked) == expected_checked
    if expected_posts:
        assert gh.posts == [(SHA, "pending")]


def test_delayed_wakeup_reads_terminal_state_after_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[int] = []
    monkeypatch.setattr(
        gate,
        "publish_checked_run",
        lambda _gh, _notified, _pr, number, _current: checked.append(number),
    )

    class FakePublisher(FakeGitHub):
        repository = REPO

        def __init__(self, pages: dict[str, Any]) -> None:
            super().__init__(pages)
            self.posts: list[str] = []

        def post(self, sha: str, state: str, description: str, run_id: int) -> None:
            self.posts.append(state)

    pr = {
        "state": "open",
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": SHA, "ref": "feature", "repo": {"full_name": REPO}},
    }
    notified = {
        "id": 42,
        "run_attempt": 1,
        "head_sha": SHA,
        "display_title": "PR Validation active",
        "repository": {"full_name": REPO},
        "pull_requests": [{"number": 7}],
    }
    latest = {
        "id": 42,
        "run_attempt": 1,
        "display_title": "PR Validation active",
        "head_branch": "feature",
        "head_repository": {"full_name": REPO},
    }
    run_path = (
        f"actions/workflows/pr-validation.yml/runs?event=pull_request&head_sha={SHA}&per_page=100"
    )
    gh = FakePublisher(
        {
            "pulls/7": pr,
            run_path: {"total_count": 1, "workflow_runs": [latest]},
            "actions/workflows/pr-validation.yml": {"id": 99},
            "actions/runs/42": {**run_for(plan()), "status": "in_progress", "run_attempt": 1},
        }
    )
    gate.publish_current_run(gh, {"workflow_run": notified}, "main")
    original_get = gh.get
    reads = 0

    def delayed_completion(path: str) -> Any:
        nonlocal reads
        if path == "actions/runs/42":
            reads += 1
            if reads == 2:
                gh.pages[path]["status"] = "completed"
        return original_get(path)

    monkeypatch.setattr(gh, "get", delayed_completion)
    monkeypatch.setattr(gate.time, "sleep", lambda _seconds: None)
    gate.publish_current_run(gh, {"action": "completed", "workflow_run": notified}, "main")
    assert gh.posts == ["pending"]
    assert reads >= 2
    assert checked == [7]


def test_latest_run_rejects_old_completion_and_ignores_irrelevant_label_run() -> None:
    pr = {"head": {"sha": SHA, "ref": "feature", "repo": {"full_name": REPO}}}
    runs = [
        {
            "id": 11,
            "conclusion": "success",
            "display_title": "PR Validation active",
            "head_branch": "feature",
            "head_repository": {"full_name": REPO},
        },
        {
            "id": 12,
            "conclusion": None,
            "display_title": "PR Validation ignored",
            "head_branch": "feature",
            "head_repository": {"full_name": REPO},
        },
        {
            "id": 13,
            "conclusion": "failure",
            "display_title": "PR Validation active",
            "head_branch": "feature",
            "head_repository": {"full_name": REPO},
        },
    ]
    path = (
        f"actions/workflows/pr-validation.yml/runs?event=pull_request&head_sha={SHA}&per_page=100"
    )
    gh = FakeGitHub({path: {"total_count": 3, "workflow_runs": runs}})
    assert gate.latest_run(gh, pr)["id"] == 13


@pytest.mark.parametrize("changed_at", ["latest", "final_run"])
def test_attempt_change_before_terminal_post_does_not_publish(
    monkeypatch: pytest.MonkeyPatch, changed_at: str
) -> None:
    selected = plan()
    pr = {
        "state": "open",
        "merge_commit_sha": MERGE,
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": SHA, "ref": "feature", "repo": {"full_name": REPO}},
        "labels": [],
    }
    current = {"id": 42, "run_attempt": 1}

    class FakePublisher:
        repository = REPO

        def __init__(self) -> None:
            self.run_reads = 0
            self.posts: list[str] = []

        def get(self, path: str) -> Any:
            if path == "actions/workflows/pr-validation.yml":
                return {"id": 99}
            if path == "pulls/7":
                return pr
            if path == "actions/runs/42":
                self.run_reads += 1
                attempt = 2 if changed_at == "final_run" and self.run_reads == 2 else 1
                return {**run_for(selected), "run_attempt": attempt}
            raise AssertionError(path)

        def pr_plan(self, number: int, tested_sha: str) -> Any:
            return selected

        def jobs(self, run_id: int) -> list[dict[str, Any]]:
            return jobs_for(selected)

        def post(self, sha: str, state: str, description: str, run_id: int) -> None:
            self.posts.append(state)

    gh = FakePublisher()
    monkeypatch.setattr(gate, "validate_merge", lambda _gh, _pr: MERGE)
    monkeypatch.setattr(
        gate,
        "latest_run",
        lambda _gh, _pr: {"id": 42, "run_attempt": 2 if changed_at == "latest" else 1},
    )
    gate.publish_checked_run(gh, {"run_attempt": 1}, pr, 7, current)
    assert gh.posts == []


def test_merge_commit_must_match_exact_base_and_head() -> None:
    pr = {"merge_commit_sha": MERGE, "base": {"sha": BASE}, "head": {"sha": SHA}}
    gh = FakeGitHub({f"commits/{MERGE}": {"parents": [{"sha": BASE}, {"sha": SHA}]}})
    assert gate.validate_merge(gh, pr) == MERGE
    gh.pages[f"commits/{MERGE}"]["parents"].reverse()
    with pytest.raises(gate.GateError):
        gate.validate_merge(gh, pr)


def test_pr_validation_identity_ignores_irrelevant_metadata() -> None:
    original = {
        "state": "open",
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO, "pushed_at": "old"}},
        "head": {"sha": SHA, "ref": "feature", "repo": {"full_name": REPO}},
        "merge_commit_sha": MERGE,
        "labels": [{"name": "ci:milestone"}, {"name": "reviewed"}],
    }
    refreshed = {
        **original,
        "base": {**original["base"], "repo": {"full_name": REPO, "pushed_at": "new"}},
        "labels": [{"name": "ci:milestone"}, {"name": "unrelated"}],
    }
    assert gate.pr_validation_identity(refreshed) == gate.pr_validation_identity(original)
    refreshed["labels"] = [{"name": "ci:light"}]
    assert gate.pr_validation_identity(refreshed) != gate.pr_validation_identity(original)


def test_plan_fingerprint_is_content_bound() -> None:
    assert hashlib.sha256(plan().to_json().encode()).hexdigest() == gate.fingerprint(plan())
