"""Pure contracts and governance rules for S42 test design proposals."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

TEST_DESIGN_SCHEMA_VERSION = "1.0"
LOW_CONFIDENCE_THRESHOLD = 0.8
HIGH_RISK_LEVELS = frozenset({"high", "critical"})
_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_.:-]{0,119}$"
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "authorization",
        "api_key",
        "card_number",
        "cookie",
        "credential",
        "email",
        "password",
        "passwd",
        "phone",
        "private_key",
        "pii",
        "secret",
        "ssn",
        "token",
    }
)
_SAFE_SECRET_REF = re.compile(r"^secret://[A-Za-z0-9._:/-]{1,480}$")
_EMAIL_VALUE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CARD_VALUE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")


class TestIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=2000)
    actors: list[str] = Field(default_factory=list, max_length=20)
    preconditions: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)


class KnowledgeNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=240)
    attributes: dict[str, JsonValue] = Field(default_factory=dict, max_length=50)


class KnowledgeEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    target: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    relation: str = Field(min_length=1, max_length=80)


class KnowledgeGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[KnowledgeNode] = Field(default_factory=list, max_length=500)
    edges: list[KnowledgeEdge] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_references(self) -> KnowledgeGraph:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("knowledge graph node ids must be unique")
        known = set(node_ids)
        if any(edge.source not in known or edge.target not in known for edge in self.edges):
            raise ValueError("knowledge graph edges must reference known nodes")
        return self


class StateNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    terminal: bool = False


class StateTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    target: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    event: str = Field(min_length=1, max_length=160)
    guard: str | None = Field(default=None, max_length=1000)


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_state: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    states: list[StateNode] = Field(min_length=1, max_length=200)
    transitions: list[StateTransition] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_references(self) -> StateModel:
        state_ids = [state.id for state in self.states]
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("state ids must be unique")
        known = set(state_ids)
        if self.initial_state not in known:
            raise ValueError("initial state must reference a known state")
        if any(
            transition.source not in known or transition.target not in known
            for transition in self.transitions
        ):
            raise ValueError("state transitions must reference known states")
        return self


class OracleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER, min_length=1, max_length=120)
    kind: Literal["status", "json_path", "schema", "expression"]
    expression: str = Field(min_length=1, max_length=1000)
    operator: Literal["equals", "not_equals", "contains", "matches", "exists"] = "equals"
    expected: JsonValue | None = None
    confidence: float = Field(ge=0, le=1)
    source_ref: str | None = Field(default=None, max_length=512)


class CoverageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(min_length=1, max_length=240)
    requirement: str = Field(min_length=1, max_length=1000)
    covered: bool = False
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class CoverageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[CoverageEntry] = Field(default_factory=list, max_length=500)

    @property
    def covered_count(self) -> int:
        return sum(entry.covered for entry in self.entries)

    @property
    def coverage_percent(self) -> float:
        if not self.entries:
            return 100.0
        return round(self.covered_count * 100 / len(self.entries), 2)


class TestDesignDocument(BaseModel):
    """A normalized design document; it is not a replacement for TestCase rows."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    intent: TestIntent
    knowledge_graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)
    state_model: StateModel
    oracles: list[OracleSpec] = Field(min_length=1, max_length=200)
    coverage: CoverageModel = Field(default_factory=CoverageModel)
    test_case_refs: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_oracles(self) -> TestDesignDocument:
        oracle_ids = [oracle.id for oracle in self.oracles]
        if len(oracle_ids) != len(set(oracle_ids)):
            raise ValueError("oracle ids must be unique")
        return self


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    confidence: float
    risk_level: Literal["low", "medium", "high", "critical"]
    requires_review: bool
    manual_approval_required: bool
    reason_codes: tuple[str, ...]


def evaluate_governance(
    *,
    confidence: float,
    risk_level: Literal["low", "medium", "high", "critical"],
    design: TestDesignDocument,
) -> GovernanceDecision:
    low_confidence_oracles = any(
        oracle.confidence < LOW_CONFIDENCE_THRESHOLD for oracle in design.oracles
    )
    reasons: list[str] = ["controlled_write_draft_only"]
    if confidence < LOW_CONFIDENCE_THRESHOLD or low_confidence_oracles:
        reasons.append("low_confidence_assertion_review")
    if risk_level in HIGH_RISK_LEVELS:
        reasons.append("manual_approval_required")
    return GovernanceDecision(
        confidence=confidence,
        risk_level=risk_level,
        requires_review=True,
        manual_approval_required=risk_level in HIGH_RISK_LEVELS,
        reason_codes=tuple(reasons),
    )


def sensitive_paths(value: object, *, path: str = "$", _key: str | None = None) -> tuple[str, ...]:
    """Return paths only; never include sensitive values in an error or audit record."""

    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _is_sensitive_key(key_text) and not _safe_secret_value(child):
                findings.append(child_path)
                continue
            findings.extend(sensitive_paths(child, path=child_path, _key=key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(sensitive_paths(child, path=f"{path}[{index}]", _key=_key))
    elif (
        isinstance(value, str)
        and not _safe_secret_value(value)
        and (_EMAIL_VALUE.search(value) or _CARD_VALUE.search(value))
    ):
        findings.append(path)
    return tuple(findings)


def fingerprint_design(value: TestDesignDocument) -> str:
    payload = value.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalized_design(value: TestDesignDocument) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value.model_dump(mode="json"))


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    if normalized in {"secret_ref", "secret_refs", "token_ref", "token_refs"}:
        return False
    parts = set(normalized.split("_"))
    return normalized in _SENSITIVE_KEY_PARTS or bool(parts & _SENSITIVE_KEY_PARTS)


def _safe_secret_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_SAFE_SECRET_REF.fullmatch(value))
    if isinstance(value, list):
        return all(_safe_secret_value(item) for item in value)
    return False
