#!/usr/bin/env python3
"""Vendor canonical evaluation assets into all five independently installable skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = WORKSPACE_ROOT / "backend/tests/fixtures/v6_golden"
PACKAGE_ROOT = WORKSPACE_ROOT / "skills/flowtest-generate-integration-flow/evals"
CONTINUOUS_PACKAGES = (
    "flowtest-project-onboarding",
    "flowtest-complete-coverage",
    "flowtest-change-aware-regression",
    "flowtest-triage-and-repair",
)


def bundle_sources() -> dict[str, Path]:
    sources = {
        "v6_evaluation.py": WORKSPACE_ROOT / "backend/app/domain/v6_evaluation.py",
        "annotations.json": GOLDEN_ROOT / "evaluation-annotations.json",
        "baseline.json": GOLDEN_ROOT / "evaluation-baseline.json",
    }
    for source in sorted(GOLDEN_ROOT.rglob("*")):
        if not source.is_file() or source.name.startswith("evaluation-"):
            continue
        sources[f"fixtures/{source.relative_to(GOLDEN_ROOT).as_posix()}"] = source
    return sources


def bundle_contents(*, include_runtime: bool = False) -> dict[str, bytes]:
    sources = bundle_sources()
    if include_runtime:
        for name in ("evaluate.py", "requirements.txt"):
            sources[name] = PACKAGE_ROOT / name
    contents = {destination: source.read_bytes() for destination, source in sources.items()}
    provenance = {
        "schema_version": "flowtest-skill-evaluation-source-map-v1",
        "evaluation_scope": "committed_annotations_only",
        "executes_backend_tests": False,
        "files": {
            destination: source.relative_to(WORKSPACE_ROOT).as_posix()
            for destination, source in sorted(sources.items())
        },
    }
    contents["source-map.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
    return contents


def sync_bundle(*, check: bool, package_root: Path | None = None) -> None:
    root = package_root if package_root is not None else PACKAGE_ROOT
    if not root.resolve().is_relative_to(WORKSPACE_ROOT.resolve()):
        raise ValueError("evaluation package must remain within the workspace")
    contents = bundle_contents(include_runtime=root != PACKAGE_ROOT)
    actual_fixtures = {
        path.relative_to(root).as_posix()
        for path in (root / "fixtures").rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_fixtures - contents.keys():
        raise ValueError("unexpected obsolete fixtures remain in the evaluation bundle")
    for relative_path, expected in contents.items():
        destination = root / relative_path
        if destination.is_symlink() or root.resolve() not in destination.resolve().parents:
            raise ValueError("evaluation bundle destination must remain within the package")
        if check:
            if not destination.is_file() or destination.read_bytes() != expected:
                raise ValueError(f"evaluation bundle is stale: {relative_path}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sync_bundle(check=args.check)
    for name in CONTINUOUS_PACKAGES:
        sync_bundle(check=args.check, package_root=WORKSPACE_ROOT / "skills" / name / "evals")
    print("Skill evaluation bundle: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
