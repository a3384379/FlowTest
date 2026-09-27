"""Run only explicitly named backend or frontend test files."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAMES = ("backend", "frontend")


def valid_test_name(project: str, name: str) -> bool:
    if project == "backend":
        return name.startswith("test_") and name.endswith(".py")
    return name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))


def test_paths(project: str) -> list[str]:
    raw = os.environ.get("TARGETS", "")
    try:
        targets = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("TARGETS must be a nonempty JSON array of test paths") from exc
    if not isinstance(targets, list) or not targets:
        raise ValueError("TARGETS must be a nonempty JSON array of test paths")

    project_root = ROOT / project
    test_root = project_root / ("tests" if project == "backend" else "src")
    paths: list[str] = []
    for target in targets:
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Each target must be a nonempty test file path")
        relative = Path(target)
        if relative.is_absolute() or ".." in relative.parts:
            message = f"Target must stay inside {test_root.relative_to(ROOT)}: {target}"
            raise ValueError(message)
        resolved = (project_root / relative).resolve()
        if not resolved.is_relative_to(test_root.resolve()) or not resolved.is_file():
            raise ValueError(f"Target must be an existing test file: {target}")
        if not valid_test_name(project, resolved.name):
            raise ValueError(f"Target must be a test file: {target}")
        paths.append(str(relative))
    return paths


def main() -> int:
    valid_arguments = (
        len(sys.argv) in (2, 3)
        and sys.argv[1] in PROJECT_NAMES
        and (len(sys.argv) == 2 or sys.argv[2] == "--dry-run")
    )
    if not valid_arguments:
        print(
            "Usage: run_targeted_tests.py {backend|frontend} [--dry-run]",
            file=sys.stderr,
        )
        return 2
    project = sys.argv[1]
    try:
        paths = test_paths(project)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    command = (
        ["uv", "run", "pytest", "--no-cov", *paths]
        if project == "backend"
        else ["pnpm", "test", *paths]
    )
    project_root = ROOT / project
    print(f"In {project_root}: {shlex.join(command)}", flush=True)
    if len(sys.argv) == 3:
        return 0
    # The command prefix is fixed; every file path was resolved inside the test root.
    return subprocess.run(command, cwd=project_root, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
