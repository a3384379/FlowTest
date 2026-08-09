import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from app.domain.api_assets import JsonValue


class TestTargetType(StrEnum):
    WORKFLOW = "workflow"
    CASE = "case"
    SUITE = "suite"


@dataclass(frozen=True, slots=True)
class VersionChange:
    path: str
    before: JsonValue
    after: JsonValue


def definition_fingerprint(definition: dict[str, JsonValue]) -> str:
    canonical = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def version_changes(
    before: JsonValue,
    after: JsonValue,
    *,
    path: str = "$",
) -> tuple[VersionChange, ...]:
    if before == after:
        return ()
    if isinstance(before, dict) and isinstance(after, dict):
        return _mapping_changes(before, after, path)
    return (VersionChange(path=path, before=before, after=after),)


def _mapping_changes(
    before: dict[str, JsonValue],
    after: dict[str, JsonValue],
    path: str,
) -> tuple[VersionChange, ...]:
    changes: list[VersionChange] = []
    for key in sorted(before.keys() | after.keys()):
        child_path = f"{path}.{key}"
        if key not in before:
            changes.append(VersionChange(child_path, None, after[key]))
        elif key not in after:
            changes.append(VersionChange(child_path, before[key], None))
        else:
            changes.extend(version_changes(before[key], after[key], path=child_path))
    return tuple(changes)
