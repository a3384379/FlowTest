#!/usr/bin/env python3
"""Build or verify the model-independent FlowTest V6 Golden evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.v6_evaluation import (
    EvaluationAnnotation,
    EvaluationBaseline,
    build_evaluation_baseline,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANNOTATIONS = (
    WORKSPACE_ROOT / "backend/tests/fixtures/v6_golden/evaluation-annotations.json"
)
DEFAULT_BASELINE = WORKSPACE_ROOT / "backend/tests/fixtures/v6_golden/evaluation-baseline.json"
ANNOTATION_ADAPTER = TypeAdapter(list[EvaluationAnnotation])


def load_annotations(path: Path) -> list[EvaluationAnnotation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ANNOTATION_ADAPTER.validate_python(payload)


def render_baseline(baseline: EvaluationBaseline) -> str:
    payload = baseline.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def check_baseline(*, annotations_path: Path, baseline_path: Path) -> None:
    expected = build_evaluation_baseline(load_annotations(annotations_path))
    committed = EvaluationBaseline.model_validate_json(baseline_path.read_text(encoding="utf-8"))
    if committed != expected:
        raise RuntimeError(
            "V6 evaluation baseline is stale; regenerate it from the committed annotations"
        )
    if not committed.release_gates_passed:
        raise RuntimeError("V6 evaluation release gates are not all passed")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.check and args.output is not None:
        raise ValueError("--check and --output are mutually exclusive")
    if args.check:
        check_baseline(annotations_path=args.annotations, baseline_path=args.baseline)
        print("V6 Golden evaluation baseline: PASS")
        return 0

    rendered = render_baseline(build_evaluation_baseline(load_annotations(args.annotations)))
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
