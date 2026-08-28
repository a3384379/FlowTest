"""Pure, bounded contracts for V6 test contexts and external evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Final, Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

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
MCP_FLOW_PROPOSAL_SERVER_VERSION: Final[str] = "s51-flow-proposal-v1"
MAX_EXTERNAL_EVIDENCE_BYTES = 256 * 1024
MAX_CONTEXT_REVISION_REFERENCES = 100
MAX_CONTEXT_CONFLICTS = 100
MAX_CONTEXT_EVIDENCE_ITEMS = 2000
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
_ADAPTER_REF = r"^\S+$"
_ADAPTER_IDENTIFIER = r"^[A-Za-z_$][A-Za-z0-9_$.-]{0,159}$"
_WRITE_SQL = re.compile(
    r"\b(?:alter|call|create|delete|drop|execute|grant|insert|merge|replace|revoke|truncate|update)\b",
    re.IGNORECASE,
)


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
    conflicts: list[ContextConflict] = Field(default_factory=list, max_length=MAX_CONTEXT_CONFLICTS)


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
    repository_revisions: list[RevisionReference] = Field(
        default_factory=list, max_length=MAX_CONTEXT_REVISION_REFERENCES
    )
    contract_revisions: list[RevisionReference] = Field(
        default_factory=list, max_length=MAX_CONTEXT_REVISION_REFERENCES
    )
    data_profile_revisions: list[RevisionReference] = Field(
        default_factory=list, max_length=MAX_CONTEXT_REVISION_REFERENCES
    )
    existing_test_revision: RevisionReference | None = None
    knowledge_snapshot: ContextKnowledgeSnapshot = Field(default_factory=ContextKnowledgeSnapshot)
    conflict_snapshot: ContextConflictSnapshot = Field(default_factory=ContextConflictSnapshot)
    completeness: ContextCompletenessSnapshot
    evidence_fingerprints: list[str] = Field(
        default_factory=list, max_length=MAX_CONTEXT_EVIDENCE_ITEMS
    )

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


class EmptyExternalEvidenceStructuredData(BaseModel):
    """Preserve the pre-adapter empty-object fingerprint without accepting wildcard data."""

    model_config = ConfigDict(extra="forbid")


class ExternalJavaClaimBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160, pattern=_ADAPTER_IDENTIFIER)
    source_path: str = Field(min_length=1, max_length=1024)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool

    @model_validator(mode="after")
    def validate_source_path(self) -> ExternalJavaClaimBase:
        require_no_sensitive_scalar_values([self.source_path])
        return self


class ExternalJavaControllerRouteClaim(ExternalJavaClaimBase):
    kind: Literal["controller_route"] = "controller_route"
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    controller_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    handler: str = Field(pattern=_ADAPTER_IDENTIFIER)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(min_length=1, max_length=500, pattern=r"^/[^\s]*$")


class ExternalJavaDtoFieldClaim(ExternalJavaClaimBase):
    kind: Literal["dto_field"] = "dto_field"
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    direction: Literal["request", "response"]
    dto_type: str = Field(pattern=_ADAPTER_IDENTIFIER)
    field_name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    field_type: str = Field(min_length=1, max_length=160)


class ExternalJavaBeanValidationClaim(ExternalJavaClaimBase):
    kind: Literal["bean_validation"] = "bean_validation"
    operation_ref: str | None = Field(
        default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF
    )
    dto_type: str = Field(pattern=_ADAPTER_IDENTIFIER)
    field_name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    annotation: str = Field(pattern=_ADAPTER_IDENTIFIER)
    constraint: str = Field(min_length=1, max_length=500)


class ExternalJavaCallClaim(ExternalJavaClaimBase):
    kind: Literal["service_call", "feign_call"]
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    caller_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    callee_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)


class ExternalJavaPersistenceClaim(ExternalJavaClaimBase):
    kind: Literal["mapper_repository"] = "mapper_repository"
    operation_ref: str | None = Field(
        default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF
    )
    repository_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    method_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF)
    entity_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF)


class ExternalJavaEntityClaim(ExternalJavaClaimBase):
    kind: Literal["entity"] = "entity"
    entity_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    class_name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    table_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF)
    operation_refs: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_operation_refs(self) -> ExternalJavaEntityClaim:
        if len(self.operation_refs) != len(set(self.operation_refs)):
            raise ValueError("entity operation refs must be unique")
        if any(re.fullmatch(_ADAPTER_REF, value) is None for value in self.operation_refs):
            raise ValueError("entity operation refs must be bounded references")
        return self


class ExternalJavaTableColumnClaim(ExternalJavaClaimBase):
    kind: Literal["table_column"] = "table_column"
    entity_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    table_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    field_name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    column_name: str = Field(pattern=_ADAPTER_IDENTIFIER)


class ExternalJavaEnumStateClaim(ExternalJavaClaimBase):
    kind: Literal["enum_state"] = "enum_state"
    operation_ref: str | None = Field(
        default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF
    )
    enum_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    field_name: str | None = Field(default=None, pattern=_ADAPTER_IDENTIFIER)
    values: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_state_values(self) -> ExternalJavaEnumStateClaim:
        require_no_sensitive_scalar_values(self.values)
        return self


class ExternalJavaExceptionClaim(ExternalJavaClaimBase):
    kind: Literal["exception"] = "exception"
    operation_ref: str | None = Field(
        default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF
    )
    exception_type: str = Field(pattern=_ADAPTER_IDENTIFIER)
    outcome: str = Field(min_length=1, max_length=160, pattern=_ADAPTER_IDENTIFIER)


class ExternalJavaKafkaEventClaim(ExternalJavaClaimBase):
    kind: Literal["kafka_event"] = "kafka_event"
    operation_ref: str | None = Field(
        default=None, min_length=1, max_length=512, pattern=_ADAPTER_REF
    )
    direction: Literal["produce", "consume"]
    topic_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    event_type: str = Field(pattern=_ADAPTER_IDENTIFIER)


type ExternalJavaClaim = Annotated[
    ExternalJavaControllerRouteClaim
    | ExternalJavaDtoFieldClaim
    | ExternalJavaBeanValidationClaim
    | ExternalJavaCallClaim
    | ExternalJavaPersistenceClaim
    | ExternalJavaEntityClaim
    | ExternalJavaTableColumnClaim
    | ExternalJavaEnumStateClaim
    | ExternalJavaExceptionClaim
    | ExternalJavaKafkaEventClaim,
    Field(discriminator="kind"),
]


class JavaExternalEvidenceStructuredData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: Literal["java"] = "java"
    claim_kind: Literal[
        "controller_route",
        "dto_field",
        "bean_validation",
        "service_call",
        "feign_call",
        "mapper_repository",
        "entity",
        "table_column",
        "enum_state",
        "exception",
        "kafka_event",
    ]
    claim: ExternalJavaClaim

    @model_validator(mode="after")
    def validate_claim_kind(self) -> JavaExternalEvidenceStructuredData:
        if self.claim_kind != self.claim.kind:
            raise ValueError("Java external claim kind must match its payload")
        return self


class ExternalDatabaseObservedDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_count: int | None = Field(default=None, ge=0)
    distinct_count: int | None = Field(default=None, ge=0)
    null_ratio: float | None = Field(default=None, ge=0, le=1)
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None
    enum_candidates: list[str | int | FiniteFloat | bool] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def validate_enum_candidates(self) -> ExternalDatabaseObservedDistribution:
        require_no_sensitive_scalar_values(self.enum_candidates)
        return self


class ExternalDatabaseTableClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    name: str = Field(pattern=_ADAPTER_IDENTIFIER)


class ExternalDatabaseColumnClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    table_name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    name: str = Field(pattern=_ADAPTER_IDENTIFIER)
    data_type: str = Field(min_length=1, max_length=160)
    nullable: bool
    primary_key: bool = False
    foreign_key: str | None = Field(
        default=None, min_length=1, max_length=320, pattern=_ADAPTER_REF
    )
    unique: bool = False
    enum_values: list[str | int | FiniteFloat | bool] = Field(default_factory=list, max_length=100)
    check_expression: str | None = Field(default=None, min_length=1, max_length=1000)
    observed_distribution: ExternalDatabaseObservedDistribution | None = None
    masked_example: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_safe_constraints(self) -> ExternalDatabaseColumnClaim:
        if self.masked_example is not None and "***" not in self.masked_example:
            raise ValueError("database examples must be masked")
        if self.masked_example is not None:
            require_no_sensitive_scalar_values([self.masked_example])
        if self.check_expression is not None and _WRITE_SQL.search(self.check_expression):
            raise ValueError("database evidence must not contain write SQL")
        if self.check_expression is not None:
            require_no_sensitive_scalar_values([self.check_expression])
        require_no_sensitive_scalar_values(self.enum_values)
        return self


class DatabaseExternalEvidenceStructuredData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: Literal["database"] = "database"
    claim_kind: Literal["table", "column"]
    claim: ExternalDatabaseTableClaim | ExternalDatabaseColumnClaim

    @model_validator(mode="after")
    def validate_claim_kind(self) -> DatabaseExternalEvidenceStructuredData:
        expected = "column" if isinstance(self.claim, ExternalDatabaseColumnClaim) else "table"
        if self.claim_kind != expected:
            raise ValueError("database external claim kind must match its payload")
        return self


class ExternalEvidenceBundleClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    source_type: Literal[
        "contract",
        "source",
        "data_profile",
        "service_topology",
        "workflow",
        "runtime",
        "change",
        "existing_test",
        "user_confirmed_rule",
    ]
    source_ref: str = Field(min_length=1, max_length=512)
    subject_ref: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=1024)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool
    revision: str = Field(min_length=1, max_length=160)
    sensitive: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=20)
    structured_data_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceBundleExternalEvidenceStructuredData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: Literal["evidence_bundle"] = "evidence_bundle"
    claim_kind: str = Field(min_length=1, max_length=80)
    claim: ExternalEvidenceBundleClaim

    @model_validator(mode="after")
    def validate_claim_kind(self) -> EvidenceBundleExternalEvidenceStructuredData:
        if self.claim_kind != self.claim.kind:
            raise ValueError("Evidence Bundle claim kind must match its payload")
        return self


class ExternalEntityMappingConflictClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_kind: Literal[
        "operation_entity",
        "request_field_column",
        "response_field_column",
        "operation_state",
    ]
    source_ref: str = Field(min_length=1, max_length=512, pattern=_ADAPTER_REF)
    candidate_count: int = Field(ge=2, le=1000)


class EntityMappingExternalEvidenceStructuredData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: Literal["entity_mapping"] = "entity_mapping"
    claim_kind: Literal["conflict"] = "conflict"
    claim: ExternalEntityMappingConflictClaim


type ExternalEvidenceAdapterStructuredData = Annotated[
    JavaExternalEvidenceStructuredData
    | DatabaseExternalEvidenceStructuredData
    | EvidenceBundleExternalEvidenceStructuredData
    | EntityMappingExternalEvidenceStructuredData,
    Field(discriminator="adapter"),
]
type ExternalEvidenceStructuredData = (
    EmptyExternalEvidenceStructuredData | ExternalEvidenceAdapterStructuredData
)


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
    structured_data: ExternalEvidenceStructuredData = Field(
        default_factory=EmptyExternalEvidenceStructuredData
    )
    confidence: float = Field(ge=0, le=1)
    deterministic: bool
    semantic_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_semantic_fingerprint(self) -> ExternalEvidenceFinding:
        if isinstance(self.structured_data, EntityMappingExternalEvidenceStructuredData) and (
            self.kind is not EvidenceFindingKind.CONFLICT
            or self.semantic_role is not EvidenceSemanticRole.CONFLICT
        ):
            raise ValueError("entity mapping markers must be conflict findings")
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
        _require_compatible_adapter_provider(self)
        payload = self.model_dump(mode="json")
        if len(_canonical_json(payload)) > MAX_EXTERNAL_EVIDENCE_BYTES:
            raise ValueError("external evidence byte budget exceeded")
        unsafe = first_sensitive_value(payload)
        if unsafe is not None:
            raise ValueError(f"external evidence contains sensitive data at {unsafe}")
        return self


def _require_compatible_adapter_provider(envelope: ExternalEvidenceEnvelope) -> None:
    adapters = _envelope_adapters(envelope.findings)
    primary_adapters = adapters - {"entity_mapping"}
    if len(primary_adapters) > 1:
        raise ValueError("external evidence adapters must not be mixed")
    if "entity_mapping" in adapters and not primary_adapters.intersection({"java", "database"}):
        raise ValueError("entity mapping markers require Java or database evidence")
    if (
        primary_adapters == {"java"}
        and envelope.provider.type is not EvidenceProviderType.REPOSITORY
    ):
        raise ValueError("Java external evidence requires a repository provider")
    if (
        primary_adapters == {"database"}
        and envelope.provider.type is not EvidenceProviderType.DATABASE
    ):
        raise ValueError("database external evidence requires a database provider")
    if primary_adapters == {"evidence_bundle"}:
        expected = _evidence_bundle_provider(envelope.findings)
        if envelope.provider.type is not expected:
            raise ValueError("Evidence Bundle provider does not match its source types")


def _envelope_adapters(findings: list[ExternalEvidenceFinding]) -> set[str]:
    adapter_types = (
        JavaExternalEvidenceStructuredData,
        DatabaseExternalEvidenceStructuredData,
        EvidenceBundleExternalEvidenceStructuredData,
        EntityMappingExternalEvidenceStructuredData,
    )
    return {
        finding.structured_data.adapter
        for finding in findings
        if isinstance(finding.structured_data, adapter_types)
    }


def _evidence_bundle_provider(
    findings: list[ExternalEvidenceFinding],
) -> EvidenceProviderType:
    source_types = {
        finding.structured_data.claim.source_type
        for finding in findings
        if isinstance(finding.structured_data, EvidenceBundleExternalEvidenceStructuredData)
    }
    if source_types == {"data_profile"}:
        return EvidenceProviderType.DATA_PROFILE
    if source_types == {"contract"}:
        return EvidenceProviderType.CONTRACT
    if source_types == {"existing_test"}:
        return EvidenceProviderType.EXISTING_TEST
    return EvidenceProviderType.REPOSITORY


def finding_semantic_fingerprint(finding: ExternalEvidenceFinding) -> str:
    payload = finding.model_dump(mode="json", exclude={"semantic_fingerprint"})
    if not payload["structured_data"]:
        del payload["structured_data"]
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


def require_no_sensitive_scalar_values(
    values: Sequence[str | int | float | bool],
) -> None:
    for value in values:
        if first_sensitive_value({"value": str(value)}) is not None:
            raise ValueError("external evidence contains sensitive scalar value")


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
    if path.endswith(
        (
            ".statement",
            ".message",
            ".reason",
            ".value",
            ".label",
            ".objective",
            ".name",
            ".id",
        )
    ) and any(pattern.search(value) for pattern in (_PHONE, _CARD)):
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
