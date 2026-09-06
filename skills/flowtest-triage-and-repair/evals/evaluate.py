#!/usr/bin/env python3
"""Evaluate committed annotations without importing FlowTest or connecting to a server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from v6_evaluation import (
    EvaluationAnnotation,
    EvaluationBaseline,
    build_evaluation_baseline,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
MAX_INPUT_BYTES = 5_000_000


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load(path: Path) -> Any:
    with path.open("rb") as stream:
        payload = stream.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("evaluation input exceeds the size limit")
    return json.loads(payload, object_pairs_hook=_unique_object)


def evaluate(annotations_path: Path) -> EvaluationBaseline:
    annotations = TypeAdapter(list[EvaluationAnnotation]).validate_python(_load(annotations_path))
    return build_evaluation_baseline(annotations)


def check_baseline(actual: EvaluationBaseline, baseline_path: Path) -> None:
    committed = EvaluationBaseline.model_validate(_load(baseline_path))
    if committed != actual:
        raise ValueError("evaluation baseline is stale")
    if not actual.release_gates_passed:
        raise ValueError("evaluation release gates did not pass")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=PACKAGE_ROOT / "annotations.json")
    parser.add_argument("--baseline", type=Path, default=PACKAGE_ROOT / "baseline.json")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.check and args.output is not None:
        parser.error("--check and --output are mutually exclusive")
    return args


def main() -> int:
    args = _arguments()
    try:
        result = evaluate(args.annotations)
        if args.check:
            check_baseline(result, args.baseline)
            print("PASS: committed annotation baseline only; backend tests were not executed.")
        else:
            rendered = json.dumps(result.model_dump(mode="json"), indent=2) + "\n"
            if args.output is None:
                print(rendered, end="")
            else:
                args.output.write_text(rendered, encoding="utf-8")
        return 0 if result.release_gates_passed else 1
    except (ValueError, OSError, RecursionError):
        # Validation errors may contain caller-supplied values. Do not echo them.
        print(
            "FAIL: invalid input, stale baseline, unreadable file, or failed gate.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
