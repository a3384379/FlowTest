"""Pure, bounded contracts for V6 test contexts and external evidence."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from hashlib import sha256
from typing import Final, Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTEXT_REVISION_SCHEMA_VERSION: Final[Literal["flowtest-context-revision-v1"]] = (
    "flowtest-context-revision-v1"
)
CONTEXT_KNOWLEDGE_SCHEMA_VERSION: Final[Literal["flowtest-context-knowledge-v1"]] = (
    "flowtest-context-knowledge-v1"
)
CONTEXT_CONFLICT_SCHEMA_VERSION: Final[Literal["flowtest-context-conflicts-v1"]] = (
    "flowtest-context-conflicts-v1"
)
EXTERNAL_EVIDENCE_SCHEMA_VERSION: Final[Literal["flowtest-external-evidence-v1"]] = (
    "flowtest-external-evidence-v1"
)
MCP_CONTEXT_EVIDENCE_SERVER_VERSION: Final[str] = "s49-context-evidence-v1"
MAX_EXTERNAL_EVIDENCE_BYTES = 256 * 1024
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9._/-]{0,159}$")
_VERSION_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE)-----")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_BASIC = re.compile(r"\bBasic\s+[A-Za-z0-9+/=]{8,}", re.IGNORECASE)
_JWT = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_SECRET_ASSIGNMENT = re.compile(
    r"\b(?:authorization|cookie|password|passwd|secret|token|api[_ -]?key)"
    r"\s*[:=]\s*['\"]?[^\s,;'\"]{4,}",
    re.IGNORECASE,
)
_SET_COOKIE = re.compile(r"\bSet-Cookie\s*:\s*\S+", re.IGNORECASE)
_CONNECTION_STRING = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|mssql)://",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)\+?[1-9]\d{9,14}(?!\d)")
_CARD = re.compile(r"(?<!\d)\d{13,19}(?!\d)")


class TestContextStatus(StrEnum):
    COLLECTING = "collecting"
    READY = "ready"
    INCOMPLETE = "incomplete"
    CONFLICTED = "conflicted"
    EXPIRED = "expired"
    CLOSED = "closed"


class EvidenceProviderType(StrEnum):
    REPOSITORY = "repository"
    CONTRACT = "contract"
    DATA_PROFILE = "data_profile"
    EXISTING_TEST = "existing_test"
    WORKFLOW = "workflow"
    RUNTIME = "runtime"
    DATABASE = "database"


class EvidenceSemanticRole(StrEnum):
    NORMATIVE = "normative"
    OBSERVED = "observed"
    MIXED = "mixed"
    COVERAGE = "coverage"
    SUPPORTING = "supporting"
    CONFLICT = "conflict"


class EvidenceFindingKind(StrEnum):
    OPERATION = "operation"
    BINDING = "binding"
    CONSTRAINT = "constraint"
    BEHAVIOR = "behavior"
    EXISTING_TEST = "existing_test"
    DATA_PROFILE = "data_profile"
    CONFLICT = "conflict"
    KNOWLEDGE = "knowledge"


class EvidenceContentSource(StrEnum):
    STRUCTURED_ANALYSIS = "structured_analysis"
    CODE_COMMENT = "code_comment"
    INTERFACE_DESCRIPTION = "interface_description"
    DATABASE_COMMENT = "database_comment"


class RevisionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1, max_length=512, pattern=r"^\S+$")
    revision: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")


class ContextKnowledgeFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,79}$")
    value: str = Field(min_length=1, max_length=1000)


class ContextKnowledgeNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._:-]{0,119}$")
    kind: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,79}$")
    label: str = Field(min_length=1, max_length=240)
    facts: list[ContextKnowledgeFact] = Field(default_factory=list, max_length=50)


class ContextKnowledgeEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._:-]{0,119}$")
    target: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._:-]{0,119}$")
    relation: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,79}$")


class ContextKnowledgeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-context-knowledge-v1"] = CONTEXT_KNOWLEDGE_SCHEMA_VERSION
    nodes: list[ContextKnowledgeNode] = Field(default_factory=list, max_length=500)
    edges: list[ContextKnowledgeEdge] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_graph(self) -> ContextKnowledgeSnapshot:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("knowledge node ids must be unique")
        for node in self.nodes:
            facts = [(fact.name, fact.value) for fact in node.facts]
            if len(facts) != len(set(facts)):
                raise ValueError("knowledge node facts must be unique")
        edges = [(edge.source, edge.target, edge.relation) for edge in self.edges]
        if len(edges) != len(set(edges)):
            raise ValueError("knowledge edges must be unique")
        known = set(node_ids)
        if any(edge.source not in known or edge.target not in known for edge in self.edges):
            raise ValueError("knowledge edges must reference known nodes")
        return self


class ContextConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_ref: str = Field(min_length=1, max_length=512)
    finding_fingerprints: list[str] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_fingerprints(self) -> ContextConflict:
        if any(_SHA256.fullmatch(value) is None for value in self.finding_fingerprints):
            raise ValueError("conflict finding fingerprints must be SHA-256 values")
        if len(self.finding_fingerprints) != len(set(self.finding_fingerprints)):
            raise ValueError("conflict finding fingerprints must be unique")
        return self


class ContextConflictSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-context-conflicts-v1"] = CONTEXT_CONFLICT_SCHEMA_VERSION
    conflicts: list[ContextConflict] = Field(default_factory=list, max_length=100)


class ContextCompletenessSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[EvidenceProviderType] = Field(min_length=1, max_length=20)
    present: list[EvidenceProviderType] = Field(default_factory=list, max_length=20)
    missing: list[EvidenceProviderType] = Field(default_factory=list, max_length=20)
    complete: bool

    @model_validator(mode="after")
    def validate_sets(self) -> ContextCompletenessSnapshot:
        required = set(self.required)
        present = set(self.present)
        if set(self.missing) != required - present:
            raise ValueError("completeness missing types do not match required types")
        if self.complete != (not self.missing):
            raise ValueError("completeness flag does not match missing types")
        return self


class ContextRevisionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-context-revision-v1"] = CONTEXT_REVISION_SCHEMA_VERSION
    repository_revisions: list[RevisionReference] = Field(default_factory=list, max_length=100)
    contract_revisions: list[RevisionReference] = Field(default_factory=list, max_length=100)
    data_profile_revisions: list[RevisionReference] = Field(default_factory=list, max_length=100)
    existing_test_revision: RevisionReference | None = None
    knowledge_snapshot: ContextKnowledgeSnapshot = Field(default_factory=ContextKnowledgeSnapshot)
    conflict_snapshot: ContextConflictSnapshot = Field(default_factory=ContextConflictSnapshot)
    completeness: ContextCompletenessSnapshot
    evidence_fingerprints: list[str] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def validate_fingerprints(self) -> ContextRevisionSnapshot:
        for references in (
            self.repository_revisions,
            self.contract_revisions,
            self.data_profile_revisions,
        ):
            identities = [(item.source_ref, item.revision) for item in references]
            if len(identities) != len(set(identities)):
                raise ValueError("revision references must be unique")
        if any(_SHA256.fullmatch(value) is None for value in self.evidence_fingerprints):
            raise ValueError("evidence fingerprints must be SHA-256 values")
        if len(self.evidence_fingerprints) != len(set(self.evidence_fingerprints)):
            raise ValueError("evidence fingerprints must be unique")
        return self


class ExternalEvidenceProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EvidenceProviderType
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_identity(self) -> ExternalEvidenceProvider:
        if (
            _IDENTIFIER.fullmatch(self.name) is None
            or _VERSION_IDENTIFIER.fullmatch(self.version) is None
        ):
            raise ValueError("provider name and version must be bounded identifiers")
        return self


class ExternalEvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=512, pattern=r"^\S+$")
    revision: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")


class ExternalEvidenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    kind: EvidenceFindingKind
    semantic_role: EvidenceSemanticRole
    source_ref: str = Field(min_length=1, max_length=512, pattern=r"^\S+$")
    source_revision: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")
    subject_ref: str = Field(min_length=1, max_length=512, pattern=r"^\S+$")
    source_path: str = Field(default="$", min_length=1, max_length=1024)
    source_content: EvidenceContentSource = EvidenceContentSource.STRUCTURED_ANALYSIS
    content_role: Literal["untrusted_data"] = "untrusted_data"
    statement: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool
    semantic_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_semantic_fingerprint(self) -> ExternalEvidenceFinding:
        if self.semantic_fingerprint != finding_semantic_fingerprint(self):
            raise ValueError("finding semantic fingerprint does not match its content")
        return self


class ExternalEvidenceRedaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    method: Literal["removed", "masked", "hashed", "referenced"]
    reason: str = Field(min_length=1, max_length=500)


class ExternalEvidenceWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    message: str = Field(min_length=1, max_length=1000)


class ExternalEvidenceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-external-evidence-v1"] = EXTERNAL_EVIDENCE_SCHEMA_VERSION
    provider: ExternalEvidenceProvider
    source: ExternalEvidenceSource
    subject_ref: str = Field(min_length=1, max_length=512, pattern=r"^\S+$")
    findings: list[ExternalEvidenceFinding] = Field(min_length=1, max_length=100)
    redactions: list[ExternalEvidenceRedaction] = Field(default_factory=list, max_length=100)
    warnings: list[ExternalEvidenceWarning] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool

    @model_validator(mode="after")
    def validate_envelope(self) -> ExternalEvidenceEnvelope:
        identifiers = [finding.id for finding in self.findings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence finding ids must be unique")
        for finding in self.findings:
            if finding.source_ref != self.source.ref:
                raise ValueError("finding source_ref must match the envelope source")
            if finding.source_revision != self.source.revision:
                raise ValueError("finding source_revision must match the envelope source")
            if finding.subject_ref != self.subject_ref:
                raise ValueError("finding subject_ref must match the envelope subject")
        payload = self.model_dump(mode="json")
        if len(_canonical_json(payload)) > MAX_EXTERNAL_EVIDENCE_BYTES:
            raise ValueError("external evidence byte budget exceeded")
        unsafe = first_sensitive_value(payload)
        if unsafe is not None:
            raise ValueError(f"external evidence contains sensitive data at {unsafe}")
        return self


def finding_semantic_fingerprint(finding: ExternalEvidenceFinding) -> str:
    payload = finding.model_dump(mode="json", exclude={"semantic_fingerprint"})
    return sha256(_canonical_json(payload)).hexdigest()


def external_evidence_fingerprint(envelope: ExternalEvidenceEnvelope) -> str:
    return sha256(_canonical_json(envelope.model_dump(mode="json"))).hexdigest()


def external_evidence_item_fingerprint(
    envelope: ExternalEvidenceEnvelope, finding: ExternalEvidenceFinding
) -> str:
    payload = {
        "schema_version": envelope.schema_version,
        "provider": envelope.provider.model_dump(mode="json"),
        "source": envelope.source.model_dump(mode="json"),
        "subject_ref": envelope.subject_ref,
        "finding": finding.model_dump(mode="json"),
        "redactions": [item.model_dump(mode="json") for item in envelope.redactions],
        "warnings": [item.model_dump(mode="json") for item in envelope.warnings],
        "confidence": envelope.confidence,
        "deterministic": envelope.deterministic,
    }
    return sha256(_canonical_json(payload)).hexdigest()


def context_revision_fingerprint(snapshot: ContextRevisionSnapshot) -> str:
    normalized = normalize_revision_snapshot(snapshot)
    return sha256(_canonical_json(normalized.model_dump(mode="json"))).hexdigest()


def normalize_revision_snapshot(snapshot: ContextRevisionSnapshot) -> ContextRevisionSnapshot:
    payload = snapshot.model_dump(mode="json")
    for key in ("repository_revisions", "contract_revisions", "data_profile_revisions"):
        payload[key] = sorted(payload[key], key=lambda item: (item["source_ref"], item["revision"]))
    payload["evidence_fingerprints"] = sorted(payload["evidence_fingerprints"])
    knowledge = payload["knowledge_snapshot"]
    knowledge["nodes"] = sorted(knowledge["nodes"], key=lambda item: item["id"])
    for node in knowledge["nodes"]:
        node["facts"] = sorted(node["facts"], key=lambda item: (item["name"], item["value"]))
    knowledge["edges"] = sorted(
        knowledge["edges"], key=lambda item: (item["source"], item["target"], item["relation"])
    )
    conflicts = payload["conflict_snapshot"]["conflicts"]
    for conflict in conflicts:
        conflict["finding_fingerprints"] = sorted(conflict["finding_fingerprints"])
    payload["conflict_snapshot"]["conflicts"] = sorted(
        conflicts,
        key=lambda item: (
            item["subject_ref"],
            item["summary"],
            tuple(item["finding_fingerprints"]),
        ),
    )
    completeness = payload["completeness"]
    for key in ("required", "present", "missing"):
        completeness[key] = sorted(set(completeness[key]))
    return ContextRevisionSnapshot.model_validate(payload)


def completeness_snapshot(
    required: list[EvidenceProviderType], present: list[EvidenceProviderType]
) -> ContextCompletenessSnapshot:
    normalized_required = sorted(set(required), key=str)
    normalized_present = sorted(set(present), key=str)
    missing = sorted(set(normalized_required) - set(normalized_present), key=str)
    return ContextCompletenessSnapshot(
        required=normalized_required,
        present=normalized_present,
        missing=missing,
        complete=not missing,
    )


def first_sensitive_value(value: object, *, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            found = first_sensitive_value(child, path=f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(value, list):
        for index, child in enumerate(value):
            found = first_sensitive_value(child, path=f"{path}[{index}]")
            if found is not None:
                return found
        return None
    if not isinstance(value, str):
        return None
    return path if _is_sensitive_literal(value, path=path) else None


def referenced_project_id(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.scheme != "flowtest" or parsed.netloc.lower() != "projects":
        return None
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    return segments[0] if segments else None


def _is_sensitive_literal(value: str, *, path: str) -> bool:
    if any(
        pattern.search(value)
        for pattern in (
            _PEM,
            _BEARER,
            _BASIC,
            _JWT,
            _AWS_KEY,
            _SECRET_ASSIGNMENT,
            _SET_COOKIE,
            _CONNECTION_STRING,
            _EMAIL,
        )
    ):
        return True
    if _looks_like_high_entropy_credential(value):
        return True
    if path.endswith((".statement", ".message", ".reason")) and any(
        pattern.search(value) for pattern in (_PHONE, _CARD)
    ):
        return True
    parsed = urlsplit(value)
    return parsed.username is not None or parsed.password is not None


def _looks_like_high_entropy_credential(value: str) -> bool:
    if not 32 <= len(value) <= 512 or re.fullmatch(r"[A-Za-z0-9_+/=-]+", value) is None:
        return False
    return (
        any(character.islower() for character in value)
        and any(character.isupper() for character in value)
        and any(character.isdigit() for character in value)
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
