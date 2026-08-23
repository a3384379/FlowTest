"""Typed, bounded, and redacted evidence contracts for test engineering."""

from __future__ import annotations

import ast
import json
import re
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

EVIDENCE_SCHEMA_VERSION = "flowtest-evidence-v1"
MAX_EVIDENCE_BYTES = 512 * 1024
MAX_SOURCE_FILES = 100
MAX_SOURCE_BYTES = 1024 * 1024
_COMMIT = re.compile(r"^[A-Fa-f0-9]{7,64}$")
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(authorization|cookie|password|secret|token|api[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)


class EvidenceSourceType(StrEnum):
    CONTRACT = "contract"
    SOURCE = "source"
    DATA_PROFILE = "data_profile"
    SERVICE_TOPOLOGY = "service_topology"
    WORKFLOW = "workflow"
    RUNTIME = "runtime"
    CHANGE = "change"
    EXISTING_TEST = "existing_test"
    USER_CONFIRMED_RULE = "user_confirmed_rule"


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    source_type: EvidenceSourceType
    source_ref: str = Field(min_length=1, max_length=512)
    revision: str = Field(min_length=1, max_length=160)


class EvidenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    source_type: EvidenceSourceType
    source_ref: str = Field(min_length=1, max_length=512)
    subject_ref: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=80)
    path: str = Field(default="$", min_length=1, max_length=1024)
    structured_data: dict[str, JsonValue] = Field(default_factory=dict, max_length=100)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool
    revision: str = Field(min_length=1, max_length=160)
    sensitive: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def reject_sensitive_values(self) -> EvidenceFinding:
        unsafe_path = _sensitive_value_path(self.structured_data)
        if unsafe_path is not None:
            raise ValueError(f"evidence structured_data contains sensitive value at {unsafe_path}")
        return self

    def as_ref(self) -> EvidenceRef:
        return EvidenceRef(
            id=self.id,
            source_type=self.source_type,
            source_ref=self.source_ref,
            revision=self.revision,
        )


class EvidenceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_findings: int = Field(default=2000, ge=1, le=10_000)
    max_bytes: int = Field(default=MAX_EVIDENCE_BYTES, ge=1024, le=2 * 1024 * 1024)
    truncated: bool = False


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVIDENCE_SCHEMA_VERSION
    subject_ref: str = Field(min_length=1, max_length=512)
    findings: list[EvidenceFinding] = Field(default_factory=list, max_length=10_000)
    budget: EvidenceBudget = Field(default_factory=EvidenceBudget)
    warnings: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_budget_and_refs(self) -> EvidenceBundle:
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported evidence schema version")
        identifiers = [finding.id for finding in self.findings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence finding ids must be unique")
        if len(self.findings) > self.budget.max_findings:
            raise ValueError("evidence finding budget exceeded")
        payload = self.model_dump(mode="json", exclude={"budget": {"max_bytes"}})
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > self.budget.max_bytes:
            raise ValueError("evidence byte budget exceeded")
        return self

    @property
    def refs(self) -> list[EvidenceRef]:
        return [finding.as_ref() for finding in self.findings]


class DataProfileColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    data_type: str = Field(min_length=1, max_length=80)
    nullable: bool
    primary_key: bool = False
    foreign_key: str | None = Field(default=None, max_length=320)
    unique: bool = False
    enum_candidates: list[JsonValue] = Field(default_factory=list, max_length=100)
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    null_ratio: float | None = Field(default=None, ge=0, le=1)
    masked_example: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_masked_example(self) -> DataProfileColumn:
        if self.masked_example is not None and "***" not in self.masked_example:
            raise ValueError("data profile examples must be masked")
        return self


class DataProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1, max_length=512)
    revision: str = Field(min_length=1, max_length=160)
    entity: str = Field(min_length=1, max_length=320)
    row_count_estimate: int | None = Field(default=None, ge=0)
    columns: list[DataProfileColumn] = Field(min_length=1, max_length=1000)


class SourceFileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    language: str = Field(pattern=r"^python$")
    content: str = Field(max_length=256 * 1024)

    @model_validator(mode="after")
    def validate_path(self) -> SourceFileSnapshot:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source evidence paths must be repository-relative")
        if path.suffix != ".py":
            raise ValueError("the Python provider only accepts .py files")
        return self


class SourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_url: str = Field(pattern=r"^(?:https://|ssh://|git@)[^\s]+$", max_length=512)
    commit: str = Field(pattern=_COMMIT.pattern)
    allowlist_paths: list[str] = Field(min_length=1, max_length=100)
    files: list[SourceFileSnapshot] = Field(max_length=MAX_SOURCE_FILES)

    @model_validator(mode="after")
    def validate_budget_and_allowlist(self) -> SourceSnapshot:
        prefixes = tuple(path.rstrip("/") + "/" for path in self.allowlist_paths)
        if any(not file.path.startswith(prefixes) for file in self.files):
            raise ValueError("source evidence file is outside the allowlist")
        if sum(len(file.content.encode()) for file in self.files) > MAX_SOURCE_BYTES:
            raise ValueError("source evidence byte budget exceeded")
        return self


class SourceEvidenceProvider(Protocol):
    def analyze(self, snapshot: SourceSnapshot) -> EvidenceBundle: ...


class PythonSourceEvidenceProvider:
    """Analyze a bounded Python snapshot through AST only; repository code is never executed."""

    def analyze(self, snapshot: SourceSnapshot) -> EvidenceBundle:
        findings: list[EvidenceFinding] = []
        warnings: list[str] = []
        for file in sorted(snapshot.files, key=lambda item: item.path):
            try:
                tree = ast.parse(file.content, filename=file.path)
            except SyntaxError:
                warnings.append(f"无法解析 {file.path}")
                continue
            findings.extend(_python_findings(snapshot, file, tree))
        return EvidenceBundle(
            subject_ref=f"repository://{snapshot.repository_url}@{snapshot.commit}",
            findings=findings,
            warnings=warnings,
        )


def data_profile_evidence(profile: DataProfile) -> EvidenceBundle:
    findings = [
        _finding(
            source_type=EvidenceSourceType.DATA_PROFILE,
            source_ref=profile.source_ref,
            subject_ref=f"entity://{profile.entity}",
            kind="column_profile",
            path=f"column.{column.name}",
            revision=profile.revision,
            data=cast(dict[str, JsonValue], column.model_dump(mode="json", exclude_none=True)),
        )
        for column in profile.columns
    ]
    return EvidenceBundle(subject_ref=f"entity://{profile.entity}", findings=findings)


def _python_findings(
    snapshot: SourceSnapshot, file: SourceFileSnapshot, tree: ast.AST
) -> list[EvidenceFinding]:
    findings: list[EvidenceFinding] = []
    source_ref = f"source://{snapshot.repository_url}@{snapshot.commit}/{file.path}"
    for node in ast.walk(tree):
        kind, data = _python_node_evidence(node)
        if kind is None:
            continue
        line = int(getattr(node, "lineno", 1))
        findings.append(
            _finding(
                source_type=EvidenceSourceType.SOURCE,
                source_ref=source_ref,
                subject_ref=f"source-symbol://{file.path}:{line}",
                kind=kind,
                path=f"{file.path}:{line}",
                revision=snapshot.commit,
                data=data,
            )
        )
    return findings


def _python_node_evidence(node: ast.AST) -> tuple[str | None, dict[str, JsonValue]]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        route = _route_data(node)
        if route is not None:
            return "route", route
    if isinstance(node, ast.ClassDef) and any(
        _base_name(base).endswith("Enum") for base in node.bases
    ):
        values = [
            child.value.value
            for child in node.body
            if isinstance(child, ast.Assign)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, (str, int, float, bool))
        ]
        return "enum", {"name": node.name, "values": cast(list[JsonValue], values)}
    if isinstance(node, ast.Raise):
        return "error_branch", {"exception": _base_name(node.exc) if node.exc else "reraised"}
    return None, {}


def _route_data(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, JsonValue] | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            continue
        path = (
            decorator.args[0].value
            if decorator.args and isinstance(decorator.args[0], ast.Constant)
            else None
        )
        return {"handler": node.name, "method": method, "path": cast(JsonValue, path)}
    return None


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_base_name(node.value)}.{node.attr}".strip(".")
    if isinstance(node, ast.Call):
        return _base_name(node.func)
    return ""


def _finding(
    *,
    source_type: EvidenceSourceType,
    source_ref: str,
    subject_ref: str,
    kind: str,
    path: str,
    revision: str,
    data: dict[str, JsonValue],
) -> EvidenceFinding:
    key = f"{source_type.value}:{source_ref}:{subject_ref}:{kind}:{path}"
    return EvidenceFinding(
        id=f"evidence-{sha256(key.encode()).hexdigest()[:24]}",
        source_type=source_type,
        source_ref=source_ref,
        subject_ref=subject_ref,
        kind=kind,
        path=path,
        structured_data=data,
        confidence=1,
        deterministic=True,
        revision=revision,
    )


def _sensitive_value_path(value: JsonValue, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _SECRET_KEY.search(str(key)) and not _is_redacted_marker(child):
                return child_path
            nested = _sensitive_value_path(child, child_path)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for index, child in enumerate(value):
            nested = _sensitive_value_path(child, f"{path}[{index}]")
            if nested is not None:
                return nested
    return None


def _is_redacted_marker(value: JsonValue) -> bool:
    return (
        value is None
        or value is False
        or value is True
        or (isinstance(value, str) and value in {"", "***"})
    )
