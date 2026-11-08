"""Deterministic revision differences over normalized asset definitions."""

import json
import re
from dataclasses import dataclass

from pydantic import JsonValue

from app.domain.self_tests import document_digest


class RevisionDifferenceLimit(ValueError):
    """A revision must never silently truncate its changed fields."""


@dataclass(frozen=True)
class AssetDifference:
    path: str
    before_digest: str | None
    after_digest: str | None


def revision_differences(before: JsonValue, after: JsonValue) -> tuple[AssetDifference, ...]:
    changes: list[AssetDifference] = []
    _walk("$", before, after, changes)
    return tuple(changes)


def _member(path: str, key: str) -> str:
    return (
        f"{path}.{key}"
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        else f"{path}[{json.dumps(key, ensure_ascii=False)}]"
    )


def _append(
    path: str,
    before: JsonValue,
    after: JsonValue,
    changes: list[AssetDifference],
    *,
    before_present: bool = True,
    after_present: bool = True,
) -> None:
    left = document_digest(before) if before_present else None
    right = document_digest(after) if after_present else None
    if left == right:
        return
    if len(changes) >= 200 or len(path) > 4096:
        raise RevisionDifferenceLimit("修订差异超过有界范围")
    changes.append(AssetDifference(path, left, right))


def _walk(
    path: str,
    before: JsonValue,
    after: JsonValue,
    changes: list[AssetDifference],
) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            child = _member(path, key)
            if key not in before or key not in after:
                _append(
                    child,
                    before.get(key),
                    after.get(key),
                    changes,
                    before_present=key in before,
                    after_present=key in after,
                )
            else:
                _walk(child, before[key], after[key], changes)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            _walk(f"{path}[{index}]", left, right, changes)
    else:
        _append(path, before, after, changes)
