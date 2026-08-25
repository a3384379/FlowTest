"""Typed, bounded, and redacted evidence contracts for test engineering."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

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
_EMAIL_VALUE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER_VALUE = re.compile(r"^Bearer\s+\S+$", re.IGNORECASE)
_BASIC_VALUE = re.compile(r"^Basic\s+[A-Za-z0-9+/=]{8,}$", re.IGNORECASE)
_JWT_VALUE = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
_CARD_VALUE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_AWS_ACCESS_KEY = re.compile(r"^(?:AKIA|ASIA)[A-Z0-9]{16}$")
_PHONE_VALUE = re.compile(r"^\+?[1-9]\d{9,14}$")


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
    semantic_role: Literal["normative", "observed", "mixed", "coverage", "supporting"] = (
        "supporting"
    )


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

    @model_validator(mode="before")
    @classmethod
    def redact_sensitive_values(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        structured = value.get("structured_data")
        if not isinstance(structured, dict):
            return value
        sanitized, changed = _sanitize_evidence_value(cast(JsonValue, structured))
        if not changed:
            return value
        warnings = (
            list(value.get("warnings", [])) if isinstance(value.get("warnings"), list) else []
        )
        warnings.append("sensitive evidence values redacted")
        return {
            **value,
            "structured_data": sanitized,
            "sensitive": True,
            "warnings": sorted(set(str(item) for item in warnings))[:20],
        }

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
            semantic_role=_evidence_semantic_role(self),
        )


def _evidence_semantic_role(
    finding: EvidenceFinding,
) -> Literal["normative", "observed", "mixed", "coverage", "supporting"]:
    if finding.source_type is EvidenceSourceType.EXISTING_TEST:
        return "coverage"
    if finding.source_type is EvidenceSourceType.RUNTIME:
        return "observed"
    if finding.source_type is EvidenceSourceType.DATA_PROFILE:
        keys = set(finding.structured_data)
        observed = bool(
            keys.intersection({"observed_minimum", "observed_maximum", "observed_enum_candidates"})
        )
        normative = bool(
            keys.intersection(
                {
                    "constraint_minimum",
                    "constraint_maximum",
                    "constraint_enum",
                    "check_constraint",
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "exclusiveMaximum",
                    "enum",
                    "pattern",
                    "required",
                    "nullable",
                    "unique",
                    "foreign_key",
                }
            )
        )
        if observed and normative:
            return "mixed"
        return "normative" if normative else "observed"
    if finding.source_type in {
        EvidenceSourceType.CONTRACT,
        EvidenceSourceType.SOURCE,
        EvidenceSourceType.USER_CONFIRMED_RULE,
    }:
        return "normative"
    return "supporting"


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
    observed_enum_candidates: list[JsonValue] = Field(default_factory=list, max_length=100)
    observed_minimum: float | None = None
    observed_maximum: float | None = None
    constraint_minimum: float | None = None
    constraint_maximum: float | None = None
    constraint_enum: list[JsonValue] = Field(default_factory=list, max_length=100)
    check_constraint: dict[str, JsonValue] | None = None
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
        _validate_repository_identity(self.repository_url)
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
            data=_profile_column_data(column),
        )
        for column in profile.columns
    ]
    return EvidenceBundle(subject_ref=f"entity://{profile.entity}", findings=findings)


def _profile_column_data(column: DataProfileColumn) -> dict[str, JsonValue]:
    raw = cast(dict[str, JsonValue], column.model_dump(mode="json", exclude_none=True))
    legacy_enum = raw.pop("enum_candidates", [])
    legacy_minimum = raw.pop("minimum", None)
    legacy_maximum = raw.pop("maximum", None)
    if not raw.get("observed_enum_candidates") and legacy_enum:
        raw["observed_enum_candidates"] = legacy_enum
    if raw.get("observed_minimum") is None and legacy_minimum is not None:
        raw["observed_minimum"] = legacy_minimum
    if raw.get("observed_maximum") is None and legacy_maximum is not None:
        raw["observed_maximum"] = legacy_maximum
    raw["evidence_semantics"] = "observed_distribution_and_explicit_constraints"
    return raw


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
        column = int(getattr(node, "col_offset", 0))
        findings.append(
            _finding(
                source_type=EvidenceSourceType.SOURCE,
                source_ref=source_ref,
                subject_ref=f"source-symbol://{file.path}:{line}:{column}",
                kind=kind,
                path=f"{file.path}:{line}:{column}",
                revision=snapshot.commit,
                data=data,
            )
        )
    for candidate in _source_constraint_candidates(tree):
        node = candidate.node
        line = int(getattr(node, "lineno", 1))
        column = int(getattr(node, "col_offset", 0))
        findings.append(
            _finding(
                source_type=EvidenceSourceType.SOURCE,
                source_ref=source_ref,
                subject_ref=f"source-symbol://{file.path}:{line}:{column}",
                kind=candidate.kind,
                path=f"{file.path}:{line}:{column}",
                revision=snapshot.commit,
                data=candidate.data,
                confidence=candidate.confidence,
                deterministic=candidate.deterministic,
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
        if any(not _safe_source_enum_value(value) for value in values):
            return "enum", {
                "name": node.name,
                "value_count": len(values),
                "values_redacted": True,
            }
        return "enum", {"name": node.name, "values": cast(list[JsonValue], values)}
    if isinstance(node, ast.Raise):
        return "error_branch", {"exception": _base_name(node.exc) if node.exc else "reraised"}
    return None, {}


@dataclass(frozen=True, slots=True)
class _SourceConstraint:
    node: ast.AST
    kind: str
    data: dict[str, JsonValue]
    confidence: float
    deterministic: bool


def _source_constraint_candidates(tree: ast.AST) -> list[_SourceConstraint]:
    candidates: list[_SourceConstraint] = []
    module_body = tree.body if isinstance(tree, ast.Module) else []
    candidates.extend(_statements_constraints(module_body, validator=False))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            candidates.extend(_statements_constraints(node.body, validator=_is_validator(node)))
    return candidates


def _statements_constraints(
    statements: list[ast.stmt],
    *,
    validator: bool,
    conditional_depth: int = 0,
    branch_kind: str | None = None,
) -> list[_SourceConstraint]:
    candidates: list[_SourceConstraint] = []
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(statement, ast.Assert):
            candidates.extend(
                _contextual_constraints(
                    statement.test,
                    truth=True,
                    context="assert",
                    conditional_depth=conditional_depth,
                    branch_kind=branch_kind,
                )
            )
            continue
        if isinstance(statement, ast.Return) and validator and statement.value is not None:
            candidates.extend(
                _contextual_constraints(
                    statement.value,
                    truth=True,
                    context="validator-return",
                    conditional_depth=conditional_depth,
                    branch_kind=branch_kind,
                )
            )
            continue
        if isinstance(statement, ast.If):
            candidates.extend(
                _if_constraints(
                    statement,
                    validator=validator,
                    conditional_depth=conditional_depth,
                    branch_kind=branch_kind,
                )
            )
            candidates.extend(
                _statements_constraints(
                    statement.body,
                    validator=validator,
                    conditional_depth=conditional_depth + 1,
                    branch_kind="if-body",
                )
            )
            candidates.extend(
                _statements_constraints(
                    statement.orelse,
                    validator=validator,
                    conditional_depth=conditional_depth + 1,
                    branch_kind="if-else",
                )
            )
            continue
        for nested_kind, children in _nested_statement_contexts(statement):
            candidates.extend(
                _statements_constraints(
                    children,
                    validator=validator,
                    conditional_depth=conditional_depth + 1,
                    branch_kind=nested_kind,
                )
            )
    return candidates


def _if_constraints(
    statement: ast.If,
    *,
    validator: bool,
    conditional_depth: int,
    branch_kind: str | None,
) -> list[_SourceConstraint]:
    if _body_terminates_with_raise(statement.body):
        return _contextual_constraints(
            statement.test,
            truth=False,
            context="guard-raise",
            conditional_depth=conditional_depth,
            branch_kind=branch_kind,
        )
    if validator and _body_returns_false(statement.body):
        return _contextual_constraints(
            statement.test,
            truth=False,
            context="guard-return-false",
            conditional_depth=conditional_depth,
            branch_kind=branch_kind,
        )
    return _supporting_conditions(
        statement.test,
        conditional_depth=conditional_depth,
        branch_kind=branch_kind,
    )


def _contextual_constraints(
    expression: ast.expr,
    *,
    truth: bool,
    context: str,
    conditional_depth: int,
    branch_kind: str | None,
) -> list[_SourceConstraint]:
    if conditional_depth == 0:
        return _condition_constraints(expression, truth=truth, context=context)
    return _conditional_constraints(
        expression,
        truth=truth,
        context=f"conditional-{context}",
        conditional_depth=conditional_depth,
        branch_kind=branch_kind,
    )


def _conditional_constraints(
    expression: ast.expr,
    *,
    truth: bool,
    context: str,
    conditional_depth: int,
    branch_kind: str | None,
) -> list[_SourceConstraint]:
    constraints = _comparison_constraints(expression, truth=truth)
    return [
        _SourceConstraint(
            node=node,
            kind="supporting_condition",
            data={
                **constraint,
                "context": context,
                "conditional": True,
                "conditional_depth": conditional_depth,
                "branch_kind": branch_kind,
                "requires_review": True,
            },
            confidence=0.5,
            deterministic=False,
        )
        for node, constraint in constraints
    ]


def _comparison_constraints(
    expression: ast.expr, *, truth: bool
) -> list[tuple[ast.Compare, dict[str, JsonValue]]]:
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        return _comparison_constraints(expression.operand, truth=not truth)
    return [
        (node, constraint)
        for node in ast.walk(expression)
        if isinstance(node, ast.Compare)
        and (constraint := _comparison_constraint(node, truth=truth)) is not None
    ]


def _condition_constraints(
    expression: ast.expr, *, truth: bool, context: str
) -> list[_SourceConstraint]:
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        return _condition_constraints(expression.operand, truth=not truth, context=context)
    if isinstance(expression, ast.BoolOp):
        splittable = (isinstance(expression.op, ast.And) and truth) or (
            isinstance(expression.op, ast.Or) and not truth
        )
        if splittable:
            return [
                item
                for value in expression.values
                for item in _condition_constraints(value, truth=truth, context=context)
            ]
        return [
            _SourceConstraint(
                node=expression,
                kind="validation_constraint",
                data={
                    "context": "complex-guard" if context.startswith("guard-") else context,
                    "complex_condition": True,
                    "requires_review": True,
                },
                confidence=0.5,
                deterministic=False,
            )
        ]
    if not isinstance(expression, ast.Compare):
        return []
    constraint = _comparison_constraint(expression, truth=truth)
    if constraint is None:
        return []
    return [
        _SourceConstraint(
            node=expression,
            kind="validation_constraint",
            data={**constraint, "context": context, "requires_review": False},
            confidence=1,
            deterministic=True,
        )
    ]


def _supporting_conditions(
    expression: ast.expr,
    *,
    conditional_depth: int = 0,
    branch_kind: str | None = None,
) -> list[_SourceConstraint]:
    return [
        _SourceConstraint(
            node=node,
            kind="supporting_condition",
            data={
                **constraint,
                "context": "supporting-condition",
                "conditional": conditional_depth > 0,
                "conditional_depth": conditional_depth,
                "branch_kind": branch_kind,
                "requires_review": True,
            },
            confidence=0.5,
            deterministic=False,
        )
        for node in ast.walk(expression)
        if isinstance(node, ast.Compare)
        and (constraint := _comparison_constraint(node, truth=True)) is not None
    ]


def _comparison_constraint(node: ast.Compare, *, truth: bool) -> dict[str, JsonValue] | None:
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    left = node.left
    right = node.comparators[0]
    operator = node.ops[0]
    if (
        isinstance(left, ast.Constant)
        and _number(left.value)
        and not isinstance(right, ast.Constant)
    ):
        left, right = right, left
        operator = _swap_operator(operator)
    if not isinstance(right, ast.Constant) or not _number(right.value):
        return None
    name = _base_name(left).rsplit(".", 1)[-1]
    if not name:
        return None
    if not truth:
        operator = _negate_operator(operator)
    if isinstance(operator, ast.Lt):
        return {"name": name, "exclusiveMaximum": cast(JsonValue, right.value)}
    if isinstance(operator, ast.LtE):
        return {"name": name, "maximum": cast(JsonValue, right.value)}
    if isinstance(operator, ast.Gt):
        return {"name": name, "exclusiveMinimum": cast(JsonValue, right.value)}
    if isinstance(operator, ast.GtE):
        return {"name": name, "minimum": cast(JsonValue, right.value)}
    return None


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _swap_operator(operator: ast.cmpop) -> ast.cmpop:
    mapping: dict[type[ast.cmpop], type[ast.cmpop]] = {
        ast.Lt: ast.Gt,
        ast.LtE: ast.GtE,
        ast.Gt: ast.Lt,
        ast.GtE: ast.LtE,
    }
    replacement = mapping.get(type(operator))
    return replacement() if replacement is not None else operator


def _negate_operator(operator: ast.cmpop) -> ast.cmpop:
    mapping: dict[type[ast.cmpop], type[ast.cmpop]] = {
        ast.Lt: ast.GtE,
        ast.LtE: ast.Gt,
        ast.Gt: ast.LtE,
        ast.GtE: ast.Lt,
    }
    replacement = mapping.get(type(operator))
    return replacement() if replacement is not None else operator


def _is_validator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    names = {
        _base_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        for decorator in node.decorator_list
    }
    decorated = any(
        name.rsplit(".", 1)[-1]
        in {"field_validator", "model_validator", "validator", "root_validator", "validates"}
        for name in names
    )
    normalized = node.name.lower()
    named = normalized == "validate" or normalized.startswith(("validate_", "is_valid_"))
    return decorated or named


def _body_terminates_with_raise(statements: list[ast.stmt]) -> bool:
    return bool(statements) and isinstance(statements[-1], ast.Raise)


def _body_returns_false(statements: list[ast.stmt]) -> bool:
    if not statements or not isinstance(statements[-1], ast.Return):
        return False
    value = statements[-1].value
    return isinstance(value, ast.Constant) and value.value is False


def _nested_statement_contexts(statement: ast.stmt) -> list[tuple[str, list[ast.stmt]]]:
    if isinstance(statement, (ast.Try, ast.TryStar)):
        return _try_statement_contexts(statement)
    if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
        return [("loop-body", statement.body), ("loop-else", statement.orelse)]
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return [("with-body", statement.body)]
    if isinstance(statement, ast.Match):
        return [("match-case", case.body) for case in statement.cases]
    return []


def _try_statement_contexts(
    statement: ast.Try | ast.TryStar,
) -> list[tuple[str, list[ast.stmt]]]:
    result = [
        ("try-body", statement.body),
        ("try-else", statement.orelse),
        ("try-finally", statement.finalbody),
    ]
    result.extend(("except-body", handler.body) for handler in statement.handlers)
    return result


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
    confidence: float = 1,
    deterministic: bool = True,
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
        confidence=confidence,
        deterministic=deterministic,
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


def _sanitize_evidence_value(value: JsonValue, key: str = "") -> tuple[JsonValue, bool]:
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        changed = False
        for child_key, child in value.items():
            if _SECRET_KEY.search(child_key) and not _is_redacted_marker(child):
                result[child_key] = "***"
                changed = True
                continue
            result[child_key], child_changed = _sanitize_evidence_value(child, child_key)
            changed = changed or child_changed
        return result, changed
    if isinstance(value, list):
        result_list: list[JsonValue] = []
        changed = False
        for child in value:
            sanitized, child_changed = _sanitize_evidence_value(child, key)
            result_list.append(sanitized)
            changed = changed or child_changed
        return result_list, changed
    if isinstance(value, str) and _looks_sensitive_value(value):
        return "***", True
    return value, False


def _looks_sensitive_value(value: str) -> bool:
    if value in {"", "***"} or value.startswith("secret://") or "{{secret." in value:
        return False
    return bool(
        _EMAIL_VALUE.search(value)
        or _BEARER_VALUE.fullmatch(value)
        or _BASIC_VALUE.fullmatch(value)
        or _JWT_VALUE.fullmatch(value)
        or _CARD_VALUE.search(value)
        or _AWS_ACCESS_KEY.fullmatch(value)
        or _PHONE_VALUE.fullmatch(value)
        or "-----BEGIN " in value
        or _url_contains_userinfo(value)
        or _high_entropy_credential(value)
    )


def _url_contains_userinfo(value: str) -> bool:
    if "://" not in value:
        return False
    parsed = urlsplit(value)
    return parsed.username is not None or parsed.password is not None


def _safe_source_enum_value(value: str | int | float | bool) -> bool:
    if not isinstance(value, str):
        return True
    return len(value) <= 80 and not _looks_sensitive_value(value)


def _high_entropy_credential(value: str) -> bool:
    if not 32 <= len(value) <= 512 or re.fullmatch(r"[A-Za-z0-9_+/=-]+", value) is None:
        return False
    return (
        any(character.islower() for character in value)
        and any(character.isupper() for character in value)
        and any(character.isdigit() for character in value)
    )


def _validate_repository_identity(value: str) -> None:
    if value.startswith("git@"):
        # The leading `git@` is the only allowed at-sign for SCP syntax.
        if value.count("@") != 1 or "?" in value or "#" in value or "://" in value:
            raise ValueError("repository URL must not contain credentials, query, or fragment")
        return
    parsed = urlsplit(value)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("repository URL must not contain credentials, query, or fragment")
