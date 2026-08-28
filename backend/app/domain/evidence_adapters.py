# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

"""Pure contracts and deterministic adapters for external code and database evidence."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue, model_validator

from app.domain.evidence import EvidenceBundle, EvidenceFinding, EvidenceSourceType
from app.domain.test_contexts import (
    DatabaseExternalEvidenceStructuredData,
    EntityMappingExternalEvidenceStructuredData,
    EvidenceBundleExternalEvidenceStructuredData,
    EvidenceContentSource,
    EvidenceFindingKind,
    EvidenceProviderType,
    EvidenceSemanticRole,
    ExternalDatabaseColumnClaim,
    ExternalDatabaseTableClaim,
    ExternalEntityMappingConflictClaim,
    ExternalEvidenceBundleClaim,
    ExternalEvidenceEnvelope,
    ExternalEvidenceFinding,
    ExternalEvidenceProvider,
    ExternalEvidenceRedaction,
    ExternalEvidenceSource,
    ExternalEvidenceStructuredData,
    ExternalEvidenceWarning,
    JavaExternalEvidenceStructuredData,
    finding_semantic_fingerprint,
    first_sensitive_value,
)

JAVA_EVIDENCE_SCHEMA_VERSION: Final[Literal["flowtest-java-evidence-v1"]] = (
    "flowtest-java-evidence-v1"
)
DATABASE_EVIDENCE_SCHEMA_VERSION: Final[Literal["flowtest-database-evidence-v1"]] = (
    "flowtest-database-evidence-v1"
)
ENTITY_MAPPING_SCHEMA_VERSION: Final[Literal["flowtest-entity-mapping-v1"]] = (
    "flowtest-entity-mapping-v1"
)
MCP_EVIDENCE_ADAPTER_SERVER_VERSION: Final[str] = "s52-evidence-adapter-v1"
MAX_ADAPTER_CLAIMS = 80
MAX_JAVA_SOURCE_FILES = 50
MAX_JAVA_SOURCE_BYTES = 1024 * 1024
MAX_MAPPING_RELEVANT_CLAIMS = 500
MAX_MAPPING_CANDIDATES = 1000
MAX_MAPPING_CONFLICTS = 100
_REF = r"^\S+$"
_IDENTIFIER = r"^[A-Za-z_$][A-Za-z0-9_$.-]{0,159}$"
_WRITE_SQL = re.compile(
    r"\b(?:alter|call|create|delete|drop|execute|grant|insert|merge|replace|revoke|truncate|update)\b",
    re.IGNORECASE,
)
_MAPPING_ANNOTATION = re.compile(
    r"@(?P<method>Get|Post|Put|Patch|Delete)Mapping(?:\s*\((?P<args>[^)]*)\))?"
)
_REQUEST_MAPPING = re.compile(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)"')
_TYPE_DECLARATION = re.compile(
    r"\b(?P<kind>class|record|enum|interface)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
)
_FIELD_DECLARATION = re.compile(
    r"\bprivate\s+(?:static\s+|final\s+|transient\s+)*"
    r"(?P<type>[A-Za-z0-9_$<>,.?\[\]]+)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*;"
)
_VALIDATION_ANNOTATION = re.compile(
    r"@(?P<name>NotNull|NotBlank|NotEmpty|Size|Min|Max|Positive|PositiveOrZero|"
    r"Negative|NegativeOrZero|Email|Pattern|DecimalMin|DecimalMax|Valid)\b(?P<args>\([^)]*\))?"
)
_SERVICE_CALL = re.compile(
    r"\b(?P<target>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\.(?P<method>[A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
_THROWS = re.compile(r"\bthrows\s+([A-Za-z_$][A-Za-z0-9_$.]*)")
_THROW_NEW = re.compile(r"\bthrow\s+new\s+([A-Za-z_$][A-Za-z0-9_$.]*)")
_KAFKA_SEND = re.compile(r"\b(?:kafkaTemplate|KafkaTemplate)\.send\s*\(\s*\"([^\"]+)\"")
_KAFKA_LISTENER = re.compile(r'@KafkaListener\s*\([^)]*(?:topics\s*=\s*)?"([^"]+)"')


class EvidenceAdapterProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9._/-]{0,159}$")
    version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")


class JavaClaimBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160, pattern=_IDENTIFIER)
    source_path: str = Field(min_length=1, max_length=1024)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool


class JavaControllerRouteClaim(JavaClaimBase):
    kind: Literal["controller_route"] = "controller_route"
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    controller_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    handler: str = Field(pattern=_IDENTIFIER)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(min_length=1, max_length=500, pattern=r"^/[^\s]*$")


class JavaDtoFieldClaim(JavaClaimBase):
    kind: Literal["dto_field"] = "dto_field"
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    direction: Literal["request", "response"]
    dto_type: str = Field(pattern=_IDENTIFIER)
    field_name: str = Field(pattern=_IDENTIFIER)
    field_type: str = Field(min_length=1, max_length=160)


class JavaBeanValidationClaim(JavaClaimBase):
    kind: Literal["bean_validation"] = "bean_validation"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    dto_type: str = Field(pattern=_IDENTIFIER)
    field_name: str = Field(pattern=_IDENTIFIER)
    annotation: str = Field(pattern=_IDENTIFIER)
    constraint: str = Field(min_length=1, max_length=500)


class JavaCallClaim(JavaClaimBase):
    kind: Literal["service_call", "feign_call"]
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    caller_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    callee_ref: str = Field(min_length=1, max_length=512, pattern=_REF)


class JavaPersistenceClaim(JavaClaimBase):
    kind: Literal["mapper_repository"] = "mapper_repository"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    repository_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    method_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    entity_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)


class JavaEntityClaim(JavaClaimBase):
    kind: Literal["entity"] = "entity"
    entity_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    class_name: str = Field(pattern=_IDENTIFIER)
    table_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    operation_refs: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_operation_refs(self) -> JavaEntityClaim:
        if len(self.operation_refs) != len(set(self.operation_refs)):
            raise ValueError("entity operation refs must be unique")
        if any(re.fullmatch(_REF, value) is None for value in self.operation_refs):
            raise ValueError("entity operation refs must be bounded references")
        return self


class JavaTableColumnClaim(JavaClaimBase):
    kind: Literal["table_column"] = "table_column"
    entity_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    table_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    field_name: str = Field(pattern=_IDENTIFIER)
    column_name: str = Field(pattern=_IDENTIFIER)


class JavaEnumStateClaim(JavaClaimBase):
    kind: Literal["enum_state"] = "enum_state"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    enum_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    field_name: str | None = Field(default=None, pattern=_IDENTIFIER)
    values: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_state_values(self) -> JavaEnumStateClaim:
        _require_no_sensitive_scalar_values(self.values)
        return self


class JavaExceptionClaim(JavaClaimBase):
    kind: Literal["exception"] = "exception"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    exception_type: str = Field(pattern=_IDENTIFIER)
    outcome: str = Field(min_length=1, max_length=160, pattern=_IDENTIFIER)


class JavaKafkaEventClaim(JavaClaimBase):
    kind: Literal["kafka_event"] = "kafka_event"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    direction: Literal["produce", "consume"]
    topic_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    event_type: str = Field(pattern=_IDENTIFIER)


type JavaEvidenceClaim = Annotated[
    JavaControllerRouteClaim
    | JavaDtoFieldClaim
    | JavaBeanValidationClaim
    | JavaCallClaim
    | JavaPersistenceClaim
    | JavaEntityClaim
    | JavaTableColumnClaim
    | JavaEnumStateClaim
    | JavaExceptionClaim
    | JavaKafkaEventClaim,
    Field(discriminator="kind"),
]


class JavaEvidenceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-java-evidence-v1"] = JAVA_EVIDENCE_SCHEMA_VERSION
    provider: EvidenceAdapterProvider
    source: ExternalEvidenceSource
    subject_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    claims: list[JavaEvidenceClaim] = Field(min_length=1, max_length=MAX_ADAPTER_CLAIMS)
    redactions: list[ExternalEvidenceRedaction] = Field(default_factory=list, max_length=100)
    warnings: list[ExternalEvidenceWarning] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool

    @model_validator(mode="after")
    def validate_submission(self) -> JavaEvidenceSubmission:
        _require_unique_claim_ids(self.claims)
        _require_no_sensitive_data(self)
        return self


class DatabaseObservedDistribution(BaseModel):
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
    def validate_enum_candidates(self) -> DatabaseObservedDistribution:
        _require_no_sensitive_scalar_values(self.enum_candidates)
        return self


class DatabaseColumnEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_IDENTIFIER)
    data_type: str = Field(min_length=1, max_length=160)
    nullable: bool
    primary_key: bool = False
    foreign_key: str | None = Field(default=None, min_length=1, max_length=320, pattern=_REF)
    unique: bool = False
    enum_values: list[str | int | FiniteFloat | bool] = Field(default_factory=list, max_length=100)
    check_expression: str | None = Field(default=None, min_length=1, max_length=1000)
    observed_distribution: DatabaseObservedDistribution | None = None
    masked_example: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_safe_constraints(self) -> DatabaseColumnEvidence:
        if self.masked_example is not None and "***" not in self.masked_example:
            raise ValueError("database examples must be masked")
        if self.check_expression is not None and _WRITE_SQL.search(self.check_expression):
            raise ValueError("database evidence must not contain write SQL")
        _require_no_sensitive_scalar_values(self.enum_values)
        return self


class DatabaseTableEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(pattern=_IDENTIFIER)
    name: str = Field(pattern=_IDENTIFIER)
    columns: list[DatabaseColumnEvidence] = Field(min_length=1, max_length=MAX_ADAPTER_CLAIMS)

    @model_validator(mode="after")
    def validate_column_names(self) -> DatabaseTableEvidence:
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("database column names must be unique per table")
        return self


class DatabaseEvidenceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-database-evidence-v1"] = DATABASE_EVIDENCE_SCHEMA_VERSION
    provider: EvidenceAdapterProvider
    source: ExternalEvidenceSource
    subject_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    tables: list[DatabaseTableEvidence] = Field(min_length=1, max_length=20)
    redactions: list[ExternalEvidenceRedaction] = Field(default_factory=list, max_length=100)
    warnings: list[ExternalEvidenceWarning] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool

    @model_validator(mode="after")
    def validate_submission(self) -> DatabaseEvidenceSubmission:
        table_count = sum(len(table.columns) + 1 for table in self.tables)
        if table_count > MAX_ADAPTER_CLAIMS:
            raise ValueError("database evidence claim budget exceeded")
        identities = [(table.schema_name, table.name) for table in self.tables]
        if len(identities) != len(set(identities)):
            raise ValueError("database table identities must be unique")
        _require_no_sensitive_data(self)
        return self


class EntityMappingCandidateKind(StrEnum):
    OPERATION_ENTITY = "operation_entity"
    REQUEST_FIELD_COLUMN = "request_field_column"
    RESPONSE_FIELD_COLUMN = "response_field_column"
    OPERATION_STATE = "operation_state"


class EntityMappingSelectionStatus(StrEnum):
    PROPOSED = "proposed"
    USER_CONFIRMED = "user_confirmed"
    REJECTED = "rejected"


class EntityMappingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^mapping-[a-f0-9]{24}$")
    kind: EntityMappingCandidateKind
    source_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    target_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    field_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    state_values: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0, le=1)
    deterministic: bool
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    selection_status: EntityMappingSelectionStatus = EntityMappingSelectionStatus.PROPOSED


class EntityMappingConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    kind: EntityMappingCandidateKind
    candidate_ids: list[str] = Field(min_length=2, max_length=MAX_MAPPING_CANDIDATES)
    summary: str = Field(min_length=1, max_length=500)


class EntityMappingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-entity-mapping-v1"] = ENTITY_MAPPING_SCHEMA_VERSION
    candidates: list[EntityMappingCandidate] = Field(
        default_factory=list, max_length=MAX_MAPPING_CANDIDATES
    )
    conflicts: list[EntityMappingConflict] = Field(
        default_factory=list, max_length=MAX_MAPPING_CONFLICTS
    )
    requires_user_confirmation: bool = True

    @model_validator(mode="after")
    def validate_result(self) -> EntityMappingResult:
        candidate_ids = [candidate.id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("entity mapping candidate ids must be unique")
        known = set(candidate_ids)
        for conflict in self.conflicts:
            if not set(conflict.candidate_ids) <= known:
                raise ValueError("mapping conflicts must reference known candidates")
            selected = [
                candidate
                for candidate in self.candidates
                if candidate.id in conflict.candidate_ids
                and candidate.selection_status is EntityMappingSelectionStatus.USER_CONFIRMED
            ]
            if len(selected) > 1:
                raise ValueError("mapping conflicts cannot contain multiple confirmed candidates")
        return self


class MappingEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    finding: ExternalEvidenceFinding
    confidence: float | None = Field(default=None, ge=0, le=1)
    deterministic: bool | None = None

    @property
    def effective_confidence(self) -> float:
        provided = self.finding.confidence if self.confidence is None else self.confidence
        return min(self.finding.confidence, provided)

    @property
    def effective_deterministic(self) -> bool:
        if self.deterministic is None:
            return self.finding.deterministic
        return self.finding.deterministic and self.deterministic


class EntityMappingBudgetExceeded(ValueError):
    """Raised when bounded mapping derivation cannot represent every candidate."""


class JavaSourceFileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=256 * 1024)

    @model_validator(mode="after")
    def validate_path(self) -> JavaSourceFileSnapshot:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".java":
            raise ValueError("Java POC accepts repository-relative .java files only")
        return self


class JavaSourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: EvidenceAdapterProvider
    source: ExternalEvidenceSource
    subject_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    files: list[JavaSourceFileSnapshot] = Field(min_length=1, max_length=MAX_JAVA_SOURCE_FILES)
    execute_analyzed_code: Literal[False] = False

    @model_validator(mode="after")
    def validate_budget(self) -> JavaSourceSnapshot:
        if sum(len(file.content.encode()) for file in self.files) > MAX_JAVA_SOURCE_BYTES:
            raise ValueError("Java POC source byte budget exceeded")
        identities = [file.path for file in self.files]
        if len(identities) != len(set(identities)):
            raise ValueError("Java POC source paths must be unique")
        return self


class JavaSpringPocProvider:
    """Statically inspect bounded Java text; never compile or execute analyzed code."""

    def analyze(self, snapshot: JavaSourceSnapshot) -> JavaEvidenceSubmission:
        type_fields = _java_type_fields(snapshot.files)
        claims: list[JavaEvidenceClaim] = []
        for file in sorted(snapshot.files, key=lambda item: item.path):
            file_routes = _java_routes(file)
            claims.extend(_route_claims(file, file_routes, type_fields))
            claims.extend(_structural_java_claims(file, file_routes, type_fields))
        bounded_claims = _bounded_java_claims(claims)
        return JavaEvidenceSubmission(
            provider=snapshot.provider,
            source=snapshot.source,
            subject_ref=snapshot.subject_ref,
            claims=bounded_claims,
            confidence=min((claim.confidence for claim in bounded_claims), default=0.5),
            deterministic=all(claim.deterministic for claim in bounded_claims),
            warnings=[
                ExternalEvidenceWarning(
                    code="JAVA_POC_STATIC_ONLY",
                    message="Java/Spring POC 仅执行静态文本分析，未编译或执行目标代码。",
                )
            ],
        )


def adapt_java_evidence(submission: JavaEvidenceSubmission) -> ExternalEvidenceEnvelope:
    findings = [_java_external_finding(submission, claim) for claim in submission.claims]
    return ExternalEvidenceEnvelope(
        provider=ExternalEvidenceProvider(
            type=EvidenceProviderType.REPOSITORY,
            name=submission.provider.name,
            version=submission.provider.version,
        ),
        source=submission.source,
        subject_ref=submission.subject_ref,
        findings=findings,
        redactions=submission.redactions,
        warnings=submission.warnings,
        confidence=submission.confidence,
        deterministic=submission.deterministic,
    )


def adapt_database_evidence(submission: DatabaseEvidenceSubmission) -> ExternalEvidenceEnvelope:
    findings: list[ExternalEvidenceFinding] = []
    for table in submission.tables:
        findings.append(
            _external_finding(
                identifier=f"database-table-{table.schema_name}-{table.name}",
                kind=EvidenceFindingKind.KNOWLEDGE,
                semantic_role=EvidenceSemanticRole.NORMATIVE,
                source=submission.source,
                subject_ref=submission.subject_ref,
                source_path=f"$.tables.{table.schema_name}.{table.name}",
                statement="数据库表结构证据。",
                structured_data=DatabaseExternalEvidenceStructuredData(
                    claim_kind="table",
                    claim=ExternalDatabaseTableClaim(
                        schema_name=table.schema_name,
                        name=table.name,
                    ),
                ),
                confidence=submission.confidence,
                deterministic=submission.deterministic,
            )
        )
        findings.extend(_database_column_findings(submission, table))
    return ExternalEvidenceEnvelope(
        provider=ExternalEvidenceProvider(
            type=EvidenceProviderType.DATABASE,
            name=submission.provider.name,
            version=submission.provider.version,
        ),
        source=submission.source,
        subject_ref=submission.subject_ref,
        findings=findings,
        redactions=submission.redactions,
        warnings=submission.warnings,
        confidence=submission.confidence,
        deterministic=submission.deterministic,
    )


def adapt_evidence_bundle(
    bundle: EvidenceBundle,
    *,
    provider_name: str,
    provider_version: str,
    source_ref: str,
    source_revision: str,
    subject_ref: str,
) -> ExternalEvidenceEnvelope:
    source = ExternalEvidenceSource(ref=source_ref, revision=source_revision)
    provider_type = _bundle_provider_type(bundle)
    findings = [
        _external_finding(
            identifier=f"bundle-{finding.id}",
            kind=_bundle_finding_kind(finding.kind),
            semantic_role=_bundle_semantic_role(finding.source_type),
            source=source,
            subject_ref=subject_ref,
            source_path=finding.path,
            statement="兼容 Evidence Bundle 的结构化证据。",
            structured_data=_evidence_bundle_structured_data(finding),
            confidence=finding.confidence,
            deterministic=finding.deterministic,
        )
        for finding in bundle.findings
    ]
    if not findings:
        raise ValueError("evidence bundle must contain at least one finding")
    warnings = [
        ExternalEvidenceWarning(code="BUNDLE_WARNING", message=message)
        for message in bundle.warnings
    ]
    return ExternalEvidenceEnvelope(
        provider=ExternalEvidenceProvider(
            type=provider_type,
            name=provider_name,
            version=provider_version,
        ),
        source=source,
        subject_ref=subject_ref,
        findings=findings,
        warnings=warnings,
        confidence=min(finding.confidence for finding in bundle.findings),
        deterministic=all(finding.deterministic for finding in bundle.findings),
    )


def _evidence_bundle_structured_data(
    finding: EvidenceFinding,
) -> EvidenceBundleExternalEvidenceStructuredData:
    structured_payload = json.dumps(
        finding.structured_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return EvidenceBundleExternalEvidenceStructuredData(
        claim_kind=finding.kind,
        claim=ExternalEvidenceBundleClaim(
            **finding.model_dump(mode="json", exclude={"structured_data"}),
            structured_data_fingerprint=sha256(structured_payload).hexdigest(),
        ),
    )


def derive_entity_mapping(evidence: list[MappingEvidenceInput]) -> EntityMappingResult:
    parsed = _parse_mapping_evidence(evidence)
    _require_mapping_claim_budget(parsed)
    candidates = [
        *_operation_entity_candidates(parsed),
        *_field_column_candidates(parsed),
        *_operation_state_candidates(parsed),
    ]
    normalized = _deduplicate_candidates(candidates)
    if len(normalized) > MAX_MAPPING_CANDIDATES:
        raise EntityMappingBudgetExceeded("entity mapping candidate budget exceeded")
    conflicts = _mapping_conflicts(normalized)
    if len(conflicts) > MAX_MAPPING_CONFLICTS:
        raise EntityMappingBudgetExceeded("entity mapping conflict budget exceeded")
    return EntityMappingResult(
        candidates=normalized,
        conflicts=conflicts,
        requires_user_confirmation=bool(normalized),
    )


def with_mapping_conflict_findings(
    envelope: ExternalEvidenceEnvelope,
    evidence: list[MappingEvidenceInput],
) -> ExternalEvidenceEnvelope:
    provisional = [*evidence, *_envelope_mapping_inputs(envelope)]
    existing_keys = _existing_mapping_conflict_keys(evidence)
    conflicts = [
        conflict
        for conflict in derive_entity_mapping(provisional).conflicts
        if (conflict.kind.value, conflict.source_ref) not in existing_keys
    ]
    if not conflicts:
        return envelope
    available = max(0, 100 - len(envelope.findings))
    additions = [
        _external_finding(
            identifier=_claim_id("mapping-conflict", conflict.kind.value, conflict.source_ref),
            kind=EvidenceFindingKind.CONFLICT,
            semantic_role=EvidenceSemanticRole.CONFLICT,
            source=envelope.source,
            subject_ref=envelope.subject_ref,
            source_path="$.entity_mapping",
            statement="实体映射存在多个候选，需要人工确认。",
            structured_data=EntityMappingExternalEvidenceStructuredData(
                claim=ExternalEntityMappingConflictClaim(
                    mapping_kind=conflict.kind.value,
                    source_ref=conflict.source_ref,
                    candidate_count=len(conflict.candidate_ids),
                )
            ),
            confidence=0,
            deterministic=True,
        )
        for conflict in conflicts[: min(20, available)]
    ]
    payload = envelope.model_dump(mode="json")
    payload["findings"] = [
        item.model_dump(mode="json") for item in [*envelope.findings, *additions]
    ]
    return ExternalEvidenceEnvelope.model_validate(payload)


def _java_external_finding(
    submission: JavaEvidenceSubmission, claim: JavaEvidenceClaim
) -> ExternalEvidenceFinding:
    role = (
        EvidenceSemanticRole.NORMATIVE if claim.deterministic else EvidenceSemanticRole.SUPPORTING
    )
    return _external_finding(
        identifier=f"java-{claim.id}",
        kind=_java_finding_kind(claim.kind),
        semantic_role=role,
        source=submission.source,
        subject_ref=submission.subject_ref,
        source_path=claim.source_path,
        statement=f"Java/Spring 结构化证据：{claim.kind}。",
        structured_data=JavaExternalEvidenceStructuredData.model_validate(
            {
                "adapter": "java",
                "claim_kind": claim.kind,
                "claim": claim.model_dump(mode="json"),
            }
        ),
        confidence=claim.confidence,
        deterministic=claim.deterministic,
    )


def _database_column_findings(
    submission: DatabaseEvidenceSubmission, table: DatabaseTableEvidence
) -> list[ExternalEvidenceFinding]:
    findings: list[ExternalEvidenceFinding] = []
    for column in table.columns:
        role = (
            EvidenceSemanticRole.MIXED
            if column.observed_distribution is not None
            else EvidenceSemanticRole.NORMATIVE
        )
        findings.append(
            _external_finding(
                identifier=f"database-column-{table.schema_name}-{table.name}-{column.name}",
                kind=EvidenceFindingKind.CONSTRAINT,
                semantic_role=role,
                source=submission.source,
                subject_ref=submission.subject_ref,
                source_path=f"$.tables.{table.schema_name}.{table.name}.columns.{column.name}",
                statement="数据库列约束与脱敏分布证据。",
                structured_data=DatabaseExternalEvidenceStructuredData(
                    claim_kind="column",
                    claim=ExternalDatabaseColumnClaim.model_validate(
                        {
                            **column.model_dump(mode="json"),
                            "schema_name": table.schema_name,
                            "table_name": table.name,
                        }
                    ),
                ),
                confidence=submission.confidence,
                deterministic=submission.deterministic,
            )
        )
    return findings


def _external_finding(
    *,
    identifier: str,
    kind: EvidenceFindingKind,
    semantic_role: EvidenceSemanticRole,
    source: ExternalEvidenceSource,
    subject_ref: str,
    source_path: str,
    statement: str,
    structured_data: ExternalEvidenceStructuredData,
    confidence: float,
    deterministic: bool,
) -> ExternalEvidenceFinding:
    provisional = ExternalEvidenceFinding.model_construct(
        id=identifier[:160],
        kind=kind,
        semantic_role=semantic_role,
        source_ref=source.ref,
        source_revision=source.revision,
        subject_ref=subject_ref,
        source_path=source_path,
        source_content=EvidenceContentSource.STRUCTURED_ANALYSIS,
        content_role="untrusted_data",
        statement=statement,
        structured_data=structured_data,
        confidence=confidence,
        deterministic=deterministic,
        semantic_fingerprint="",
    )
    payload = provisional.model_dump(mode="json")
    payload["semantic_fingerprint"] = finding_semantic_fingerprint(provisional)
    return ExternalEvidenceFinding.model_validate(payload)


def _require_unique_claim_ids(claims: list[JavaEvidenceClaim]) -> None:
    identifiers = [claim.id for claim in claims]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Java evidence claim ids must be unique")


def _require_no_sensitive_data(value: BaseModel) -> None:
    unsafe = first_sensitive_value(value.model_dump(mode="json"))
    if unsafe is not None:
        raise ValueError(f"evidence adapter contains sensitive data at {unsafe}")


def _require_no_sensitive_scalar_values(
    values: Sequence[str | int | float | bool],
) -> None:
    for value in values:
        if first_sensitive_value({"value": str(value)}) is not None:
            raise ValueError("evidence adapter contains sensitive scalar value")


def _existing_mapping_conflict_keys(
    evidence: list[MappingEvidenceInput],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for item in evidence:
        data = item.finding.structured_data
        if not isinstance(data, EntityMappingExternalEvidenceStructuredData):
            continue
        keys.add((data.claim.mapping_kind, data.claim.source_ref))
    return keys


def _java_finding_kind(kind: str) -> EvidenceFindingKind:
    if kind == "controller_route":
        return EvidenceFindingKind.OPERATION
    if kind in {"dto_field", "table_column"}:
        return EvidenceFindingKind.BINDING
    if kind == "bean_validation":
        return EvidenceFindingKind.CONSTRAINT
    if kind in {"exception", "enum_state"}:
        return EvidenceFindingKind.BEHAVIOR
    return EvidenceFindingKind.KNOWLEDGE


def _bundle_provider_type(bundle: EvidenceBundle) -> EvidenceProviderType:
    source_types = {finding.source_type for finding in bundle.findings}
    if source_types == {EvidenceSourceType.DATA_PROFILE}:
        return EvidenceProviderType.DATA_PROFILE
    if source_types == {EvidenceSourceType.CONTRACT}:
        return EvidenceProviderType.CONTRACT
    if source_types == {EvidenceSourceType.EXISTING_TEST}:
        return EvidenceProviderType.EXISTING_TEST
    return EvidenceProviderType.REPOSITORY


def _bundle_finding_kind(kind: str) -> EvidenceFindingKind:
    if kind == "route":
        return EvidenceFindingKind.OPERATION
    if "constraint" in kind or kind == "column_profile":
        return EvidenceFindingKind.CONSTRAINT
    if kind in {"enum", "error_branch"}:
        return EvidenceFindingKind.BEHAVIOR
    return EvidenceFindingKind.KNOWLEDGE


def _bundle_semantic_role(source_type: EvidenceSourceType) -> EvidenceSemanticRole:
    if source_type is EvidenceSourceType.RUNTIME:
        return EvidenceSemanticRole.OBSERVED
    if source_type is EvidenceSourceType.DATA_PROFILE:
        return EvidenceSemanticRole.MIXED
    if source_type is EvidenceSourceType.EXISTING_TEST:
        return EvidenceSemanticRole.COVERAGE
    return EvidenceSemanticRole.NORMATIVE


class _ParsedEvidence:
    def __init__(self) -> None:
        self.routes: list[tuple[JavaControllerRouteClaim, str]] = []
        self.fields: list[tuple[JavaDtoFieldClaim, str]] = []
        self.entities: list[tuple[JavaEntityClaim, str]] = []
        self.columns: list[_ParsedDatabaseColumn] = []
        self.states: list[tuple[JavaEnumStateClaim, str]] = []


@dataclass(frozen=True, slots=True)
class _ParsedDatabaseColumn:
    claim: DatabaseColumnEvidence
    schema: str
    table: str
    evidence_ref: str
    confidence: float
    deterministic: bool


@dataclass(frozen=True, slots=True)
class _ParsedDatabaseTable:
    evidence_refs: tuple[str, ...]
    confidence: float
    deterministic: bool


def _require_mapping_claim_budget(parsed: _ParsedEvidence) -> None:
    count = sum(
        len(items)
        for items in (
            parsed.routes,
            parsed.fields,
            parsed.entities,
            parsed.columns,
            parsed.states,
        )
    )
    if count > MAX_MAPPING_RELEVANT_CLAIMS:
        raise EntityMappingBudgetExceeded("entity mapping evidence budget exceeded")


def _parse_mapping_evidence(evidence: list[MappingEvidenceInput]) -> _ParsedEvidence:
    parsed = _ParsedEvidence()
    for item in evidence:
        data = item.finding.structured_data
        if isinstance(data, JavaExternalEvidenceStructuredData):
            _append_java_mapping_claim(
                parsed,
                data.claim_kind,
                cast(dict[str, JsonValue], data.claim.model_dump(mode="json")),
                item.evidence_ref,
                item.effective_confidence,
                item.effective_deterministic,
            )
        elif (
            isinstance(data, DatabaseExternalEvidenceStructuredData)
            and data.claim_kind == "column"
            and isinstance(data.claim, ExternalDatabaseColumnClaim)
        ):
            parsed.columns.append(
                _ParsedDatabaseColumn(
                    claim=DatabaseColumnEvidence.model_validate(
                        data.claim.model_dump(mode="json", exclude={"schema_name", "table_name"})
                    ),
                    schema=data.claim.schema_name,
                    table=data.claim.table_name,
                    evidence_ref=item.evidence_ref,
                    confidence=item.effective_confidence,
                    deterministic=item.effective_deterministic,
                )
            )
    return parsed


def _append_java_mapping_claim(
    parsed: _ParsedEvidence,
    claim_kind: str,
    claim: dict[str, JsonValue],
    evidence_ref: str,
    confidence: float,
    deterministic: bool,
) -> None:
    if claim_kind == "controller_route":
        parsed.routes.append(
            (
                _effective_java_claim(
                    JavaControllerRouteClaim.model_validate(claim), confidence, deterministic
                ),
                evidence_ref,
            )
        )
    elif claim_kind == "dto_field":
        parsed.fields.append(
            (
                _effective_java_claim(
                    JavaDtoFieldClaim.model_validate(claim), confidence, deterministic
                ),
                evidence_ref,
            )
        )
    elif claim_kind == "entity":
        parsed.entities.append(
            (
                _effective_java_claim(
                    JavaEntityClaim.model_validate(claim), confidence, deterministic
                ),
                evidence_ref,
            )
        )
    elif claim_kind == "enum_state":
        parsed.states.append(
            (
                _effective_java_claim(
                    JavaEnumStateClaim.model_validate(claim), confidence, deterministic
                ),
                evidence_ref,
            )
        )


def _effective_java_claim[T: JavaClaimBase](
    claim: T,
    confidence: float,
    deterministic: bool,
) -> T:
    return claim.model_copy(
        update={
            "confidence": min(claim.confidence, confidence),
            "deterministic": claim.deterministic and deterministic,
        }
    )


def _operation_entity_candidates(parsed: _ParsedEvidence) -> list[EntityMappingCandidate]:
    candidates: dict[str, EntityMappingCandidate] = {}
    tables = _table_evidence(parsed.columns)
    for route, route_evidence in parsed.routes:
        matching_entities = _matching_entities(route, parsed.entities)
        for table_ref, table in tables.items():
            table_name = table_ref.rsplit("/", 1)[-1]
            score, entity_evidence = _entity_match_score(route, table_name, matching_entities)
            if score == 0:
                continue
            _append_mapping_candidate(
                candidates,
                _candidate(
                    kind=EntityMappingCandidateKind.OPERATION_ENTITY,
                    source_ref=route.operation_ref,
                    target_ref=f"entity://{table_ref.removeprefix('table://')}",
                    operation_ref=route.operation_ref,
                    confidence=min(route.confidence, score, table.confidence),
                    deterministic=(route.deterministic and score == 1 and table.deterministic),
                    evidence_refs=[route_evidence, *table.evidence_refs, *entity_evidence],
                ),
            )
    return list(candidates.values())


def _matching_entities(
    route: JavaControllerRouteClaim,
    entities: list[tuple[JavaEntityClaim, str]],
) -> list[tuple[JavaEntityClaim, str]]:
    explicit = [
        (entity, ref) for entity, ref in entities if route.operation_ref in entity.operation_refs
    ]
    return explicit or entities


def _entity_match_score(
    route: JavaControllerRouteClaim,
    table_name: str,
    entities: list[tuple[JavaEntityClaim, str]],
) -> tuple[float, list[str]]:
    table_token = _normalized_name(table_name)
    for entity, evidence_ref in entities:
        if entity.table_ref is not None and _table_ref_matches(entity.table_ref, table_name):
            return min(entity.confidence, 1.0), [evidence_ref]
        if _normalized_name(entity.class_name) == table_token:
            return min(entity.confidence, 0.9), [evidence_ref]
    route_token = _route_resource_token(route.path)
    if route_token and (table_token == route_token or table_token.endswith(route_token)):
        return 0.75, []
    return 0, []


def _table_evidence(
    columns: list[_ParsedDatabaseColumn],
) -> dict[str, _ParsedDatabaseTable]:
    values: dict[str, list[_ParsedDatabaseColumn]] = defaultdict(list)
    for column in columns:
        values[f"table://{column.schema}/{column.table}"].append(column)
    return {
        key: _ParsedDatabaseTable(
            evidence_refs=tuple(sorted({column.evidence_ref for column in table_columns})[:20]),
            confidence=min(column.confidence for column in table_columns),
            deterministic=all(column.deterministic for column in table_columns),
        )
        for key, table_columns in values.items()
    }


def _field_column_candidates(parsed: _ParsedEvidence) -> list[EntityMappingCandidate]:
    operation_tables = _operation_tables(_operation_entity_candidates(parsed))
    candidates: dict[str, EntityMappingCandidate] = {}
    for field, field_evidence in parsed.fields:
        table_targets = operation_tables.get(field.operation_ref, set())
        for parsed_column in parsed.columns:
            column = parsed_column.claim
            entity_ref = f"entity://{parsed_column.schema}/{parsed_column.table}"
            if table_targets and entity_ref not in table_targets:
                continue
            if _normalized_name(field.field_name) != _normalized_name(column.name):
                continue
            kind = (
                EntityMappingCandidateKind.REQUEST_FIELD_COLUMN
                if field.direction == "request"
                else EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN
            )
            operation_identity = sha256(field.operation_ref.encode()).hexdigest()
            field_ref = (
                f"field://{field.dto_type}/{field.field_name}?operation={operation_identity}"
            )
            _append_mapping_candidate(
                candidates,
                _candidate(
                    kind=kind,
                    source_ref=field_ref,
                    target_ref=(
                        f"column://{parsed_column.schema}/{parsed_column.table}/{column.name}"
                    ),
                    operation_ref=field.operation_ref,
                    field_ref=field_ref,
                    confidence=min(field.confidence, parsed_column.confidence),
                    deterministic=field.deterministic and parsed_column.deterministic,
                    evidence_refs=[field_evidence, parsed_column.evidence_ref],
                ),
            )
    return list(candidates.values())


def _operation_state_candidates(parsed: _ParsedEvidence) -> list[EntityMappingCandidate]:
    java_candidates = _java_state_candidates(parsed.states)
    candidates: dict[str, EntityMappingCandidate] = {}
    corroborated_java_ids: set[str] = set()
    operation_tables = _operation_tables(_operation_entity_candidates(parsed))
    for operation_ref, entities in operation_tables.items():
        for parsed_column in parsed.columns:
            column = parsed_column.claim
            if f"entity://{parsed_column.schema}/{parsed_column.table}" not in entities:
                continue
            values = _database_state_values(column)
            if not values or _normalized_name(column.name) not in {"status", "state"}:
                continue
            corroborating = [
                candidate
                for candidate in java_candidates
                if candidate.operation_ref == operation_ref and candidate.state_values == values
            ]
            corroborated_java_ids.update(candidate.id for candidate in corroborating)
            _append_mapping_candidate(
                candidates,
                _candidate(
                    kind=EntityMappingCandidateKind.OPERATION_STATE,
                    source_ref=operation_ref,
                    target_ref=(
                        f"state-set://{parsed_column.schema}/{parsed_column.table}/{column.name}"
                    ),
                    operation_ref=operation_ref,
                    state_values=values,
                    confidence=min(
                        [
                            parsed_column.confidence,
                            *(candidate.confidence for candidate in corroborating),
                        ]
                    ),
                    deterministic=(
                        parsed_column.deterministic
                        and all(candidate.deterministic for candidate in corroborating)
                    ),
                    evidence_refs=[
                        parsed_column.evidence_ref,
                        *(ref for candidate in corroborating for ref in candidate.evidence_refs),
                    ],
                ),
            )
    for candidate in java_candidates:
        if candidate.id not in corroborated_java_ids:
            _append_mapping_candidate(candidates, candidate)
    return list(candidates.values())


def _java_state_candidates(
    states: list[tuple[JavaEnumStateClaim, str]],
) -> list[EntityMappingCandidate]:
    return [
        _candidate(
            kind=EntityMappingCandidateKind.OPERATION_STATE,
            source_ref=state.operation_ref,
            target_ref=f"state-set://{state.enum_ref.removeprefix('java://')}",
            operation_ref=state.operation_ref,
            state_values=state.values,
            confidence=state.confidence,
            deterministic=state.deterministic,
            evidence_refs=[evidence_ref],
        )
        for state, evidence_ref in states
        if state.operation_ref is not None
    ]


def _database_state_values(column: DatabaseColumnEvidence) -> list[str]:
    values = list(column.enum_values)
    if column.observed_distribution is not None:
        values.extend(column.observed_distribution.enum_candidates)
    return sorted({str(value) for value in values})[:100]


def _operation_tables(
    candidates: list[EntityMappingCandidate],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        result[candidate.operation_ref].add(candidate.target_ref)
    return result


def _candidate(
    *,
    kind: EntityMappingCandidateKind,
    source_ref: str,
    target_ref: str,
    operation_ref: str,
    confidence: float,
    deterministic: bool,
    evidence_refs: list[str],
    field_ref: str | None = None,
    state_values: list[str] | None = None,
) -> EntityMappingCandidate:
    refs = sorted(set(evidence_refs))[:20]
    values = sorted(set(state_values or []))[:100]
    key = "|".join([kind.value, source_ref, target_ref, operation_ref, field_ref or "", *values])
    return EntityMappingCandidate(
        id=f"mapping-{sha256(key.encode()).hexdigest()[:24]}",
        kind=kind,
        source_ref=source_ref,
        target_ref=target_ref,
        operation_ref=operation_ref,
        field_ref=field_ref,
        state_values=values,
        confidence=confidence,
        deterministic=deterministic,
        evidence_refs=refs,
    )


def _append_mapping_candidate(
    candidates: dict[str, EntityMappingCandidate], candidate: EntityMappingCandidate
) -> None:
    existing = candidates.get(candidate.id)
    if existing is not None:
        candidates[candidate.id] = _merge_mapping_candidates(existing, candidate)
        return
    if len(candidates) >= MAX_MAPPING_CANDIDATES:
        raise EntityMappingBudgetExceeded("entity mapping candidate budget exceeded")
    candidates[candidate.id] = candidate


def _merge_mapping_candidates(
    first: EntityMappingCandidate,
    second: EntityMappingCandidate,
) -> EntityMappingCandidate:
    return first.model_copy(
        update={
            "evidence_refs": sorted({*first.evidence_refs, *second.evidence_refs})[:20],
            "confidence": max(first.confidence, second.confidence),
            "deterministic": first.deterministic and second.deterministic,
        }
    )


def _deduplicate_candidates(
    candidates: list[EntityMappingCandidate],
) -> list[EntityMappingCandidate]:
    grouped: dict[str, list[EntityMappingCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.id].append(candidate)
    unique = []
    for group in grouped.values():
        merged = group[0]
        for candidate in group[1:]:
            merged = _merge_mapping_candidates(merged, candidate)
        unique.append(merged)
    return sorted(
        unique,
        key=lambda item: (item.kind.value, item.source_ref, item.target_ref, item.id),
    )


def _mapping_conflicts(
    candidates: list[EntityMappingCandidate],
) -> list[EntityMappingConflict]:
    groups: dict[tuple[EntityMappingCandidateKind, str], list[EntityMappingCandidate]] = (
        defaultdict(list)
    )
    for candidate in candidates:
        groups[(candidate.kind, candidate.source_ref)].append(candidate)
    return [
        EntityMappingConflict(
            source_ref=source_ref,
            kind=kind,
            candidate_ids=[candidate.id for candidate in group],
            summary="存在多个映射候选，必须由用户明确确认。",
        )
        for (kind, source_ref), group in sorted(
            groups.items(), key=lambda item: (item[0][0].value, item[0][1])
        )
        if len({candidate.target_ref for candidate in group}) > 1
    ]


def _envelope_mapping_inputs(envelope: ExternalEvidenceEnvelope) -> list[MappingEvidenceInput]:
    return [
        MappingEvidenceInput(
            evidence_ref=f"evidence://semantic/{finding.semantic_fingerprint}",
            finding=finding,
            confidence=min(finding.confidence, envelope.confidence),
            deterministic=finding.deterministic and envelope.deterministic,
        )
        for finding in envelope.findings
    ]


def _normalized_name(value: str) -> str:
    tokens = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower().split("_")
    normalized = "".join(token for token in tokens if token not in {"sys", "tbl", "table"})
    if normalized.endswith("ies"):
        return normalized[:-3] + "y"
    if normalized.endswith("s") and not normalized.endswith(("ss", "status")):
        return normalized[:-1]
    return normalized


def _route_resource_token(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment and "{" not in segment]
    return _normalized_name(segments[-1]) if segments else ""


def _table_ref_matches(table_ref: str, table_name: str) -> bool:
    return _normalized_name(table_ref.rsplit("/", 1)[-1]) == _normalized_name(table_name)


class _JavaRoute(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    operation_ref: str
    controller_ref: str
    handler: str
    return_type: str
    parameters: str
    body: str
    source_line: int


def _java_type_fields(
    files: list[JavaSourceFileSnapshot],
) -> dict[str, list[tuple[str, str, list[tuple[str, str]]]]]:
    result: dict[str, list[tuple[str, str, list[tuple[str, str]]]]] = {}
    for file in files:
        for declaration in _TYPE_DECLARATION.finditer(file.content):
            name = declaration.group("name")
            body = _type_body(file.content, declaration.end())
            fields = (
                _record_fields(file.content, declaration)
                if declaration.group("kind") == "record"
                else _class_fields(body)
            )
            result[name] = fields
    return result


def _type_body(content: str, start: int) -> str:
    brace = content.find("{", start)
    if brace < 0:
        return ""
    end = _matching_brace(content, brace)
    return content[brace + 1 : end]


def _record_fields(
    content: str, declaration: re.Match[str]
) -> list[tuple[str, str, list[tuple[str, str]]]]:
    opening = content.find("(", declaration.end())
    closing = content.find(")", opening + 1)
    if opening < 0 or closing < 0:
        return []
    return [
        (parts[-1], parts[-2], [])
        for component in content[opening + 1 : closing].split(",")
        if len(parts := component.strip().split()) >= 2
    ]


def _class_fields(body: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    fields: list[tuple[str, str, list[tuple[str, str]]]] = []
    for match in _FIELD_DECLARATION.finditer(body):
        prefix = body[max(0, match.start() - 500) : match.start()]
        annotations = [
            (annotation.group("name"), (annotation.group("args") or "")[:300])
            for annotation in _VALIDATION_ANNOTATION.finditer(prefix.split(";")[-1])
        ]
        fields.append((match.group("name"), match.group("type"), annotations))
    getter_pattern = re.compile(
        r"(?P<annotations>(?:\s*@(?:NotNull|NotBlank|NotEmpty|Size|Min|Max|Email|Pattern)[^\n]*\n)+)"
        r"\s*public\s+[A-Za-z0-9_$<>,.?\[\]]+\s+get(?P<name>[A-Z][A-Za-z0-9_$]*)\s*\("
    )
    known = {field[0] for field in fields}
    for match in getter_pattern.finditer(body):
        name = match.group("name")
        field_name = name[0].lower() + name[1:]
        annotations = [
            (annotation.group("name"), (annotation.group("args") or "")[:300])
            for annotation in _VALIDATION_ANNOTATION.finditer(match.group("annotations"))
        ]
        if field_name in known:
            index = next(index for index, field in enumerate(fields) if field[0] == field_name)
            old = fields[index]
            fields[index] = (old[0], old[1], sorted(set([*old[2], *annotations])))
    return fields


def _java_routes(file: JavaSourceFileSnapshot) -> list[_JavaRoute]:
    declaration = next(
        (
            item
            for item in _TYPE_DECLARATION.finditer(file.content)
            if item.group("kind") == "class"
        ),
        None,
    )
    if declaration is None:
        return []
    before_class = file.content[: declaration.start()]
    base_matches = list(_REQUEST_MAPPING.finditer(before_class))
    base_path = base_matches[-1].group(1) if base_matches else ""
    controller = declaration.group("name")
    return [
        route
        for match in _MAPPING_ANNOTATION.finditer(file.content[declaration.end() :])
        if (
            route := _route_after_mapping(
                file,
                declaration.end() + match.start(),
                declaration.end() + match.end(),
                match,
                base_path,
                controller,
            )
        )
        is not None
    ]


def _route_after_mapping(
    file: JavaSourceFileSnapshot,
    mapping_start: int,
    mapping_end: int,
    mapping: re.Match[str],
    base_path: str,
    controller: str,
) -> _JavaRoute | None:
    following = file.content[mapping_end : mapping_end + 2000]
    signature = re.search(
        r"(?:\s*@[A-Za-z0-9_$.]+(?:\([^)]*\))?)*\s*public\s+"
        r"(?P<return>[A-Za-z0-9_$<>,.?\[\]]+)\s+(?P<handler>[A-Za-z_$][A-Za-z0-9_$]*)"
        r"\s*\((?P<params>[^)]*)\)\s*(?:throws\s+[^{]+)?\{",
        following,
    )
    if signature is None:
        return None
    path = _mapping_path(mapping.group("args") or "")
    full_path = _join_route_path(base_path, path)
    method = cast(Literal["GET", "POST", "PUT", "PATCH", "DELETE"], mapping.group("method").upper())
    body_start = mapping_end + signature.end() - 1
    body_end = _matching_brace(file.content, body_start)
    handler = signature.group("handler")
    return _JavaRoute(
        method=method,
        path=full_path,
        operation_ref=f"operation://{method}{full_path}",
        controller_ref=f"java://{controller}",
        handler=handler,
        return_type=signature.group("return"),
        parameters=signature.group("params"),
        body=file.content[body_start + 1 : body_end],
        source_line=file.content.count("\n", 0, mapping_start) + 1,
    )


def _mapping_path(arguments: str) -> str:
    match = re.search(r'"([^"]*)"', arguments)
    return match.group(1) if match else ""


def _join_route_path(base: str, path: str) -> str:
    segments = [segment.strip("/") for segment in (base, path) if segment.strip("/")]
    return "/" + "/".join(segments)


def _matching_brace(content: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(content)):
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(content)


def _route_claims(
    file: JavaSourceFileSnapshot,
    routes: list[_JavaRoute],
    type_fields: dict[str, list[tuple[str, str, list[tuple[str, str]]]]],
) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    for route in routes:
        path = f"{file.path}:{route.source_line}"
        claims.append(
            JavaControllerRouteClaim(
                id=_claim_id("route", route.operation_ref),
                source_path=path,
                operation_ref=route.operation_ref,
                controller_ref=route.controller_ref,
                handler=route.handler,
                method=route.method,
                path=route.path,
                confidence=1,
                deterministic=True,
            )
        )
        claims.extend(_route_dto_claims(path, route, type_fields))
        claims.extend(_route_call_claims(path, route))
        claims.extend(_route_exception_claims(path, route))
        claims.extend(_route_kafka_claims(path, route))
    return claims


def _route_dto_claims(
    source_path: str,
    route: _JavaRoute,
    type_fields: dict[str, list[tuple[str, str, list[tuple[str, str]]]]],
) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    parameter_types = _parameter_types(route.parameters)
    for dto_type in parameter_types:
        claims.extend(
            _dto_field_claims(source_path, route.operation_ref, "request", dto_type, type_fields)
        )
    return_type = _simple_type(route.return_type)
    claims.extend(
        _dto_field_claims(source_path, route.operation_ref, "response", return_type, type_fields)
    )
    return claims


def _dto_field_claims(
    source_path: str,
    operation_ref: str,
    direction: Literal["request", "response"],
    dto_type: str,
    type_fields: dict[str, list[tuple[str, str, list[tuple[str, str]]]]],
) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    for field_name, field_type, validation_annotations in type_fields.get(dto_type, []):
        claims.append(
            JavaDtoFieldClaim(
                id=_claim_id("dto", operation_ref, direction, dto_type, field_name),
                source_path=source_path,
                operation_ref=operation_ref,
                direction=direction,
                dto_type=dto_type,
                field_name=field_name,
                field_type=field_type,
                confidence=0.9,
                deterministic=True,
            )
        )
        claims.extend(
            JavaBeanValidationClaim(
                id=_claim_id("validation", operation_ref, dto_type, field_name, annotation),
                source_path=source_path,
                operation_ref=operation_ref,
                dto_type=dto_type,
                field_name=field_name,
                annotation=annotation,
                constraint=(arguments or "present")[:500],
                confidence=0.9,
                deterministic=True,
            )
            for annotation, arguments in validation_annotations
        )
    return claims


def _parameter_types(parameters: str) -> list[str]:
    result: list[str] = []
    for parameter in parameters.split(","):
        cleaned = re.sub(r"@[A-Za-z0-9_$.]+(?:\([^)]*\))?", "", parameter).strip()
        parts = cleaned.split()
        if len(parts) >= 2:
            result.append(_simple_type(parts[-2]))
    return result


def _simple_type(value: str) -> str:
    simple = value.rsplit(".", 1)[-1]
    match = re.search(r"<([^,>]+)", simple)
    return match.group(1).strip().rsplit(".", 1)[-1] if match else simple.rstrip("[]")


def _route_call_claims(source_path: str, route: _JavaRoute) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    for call in _SERVICE_CALL.finditer(route.body):
        target = call.group("target")
        method = call.group("method")
        normalized_target = target.lower()
        if not normalized_target.endswith(("service", "client", "repository", "mapper")):
            continue
        kind: Literal["service_call", "feign_call"] = (
            "feign_call" if normalized_target.endswith("client") else "service_call"
        )
        claims.append(
            JavaCallClaim(
                id=_claim_id(kind, route.operation_ref, target, method),
                kind=kind,
                source_path=source_path,
                operation_ref=route.operation_ref,
                caller_ref=f"{route.controller_ref}.{route.handler}",
                callee_ref=f"java://{target}.{method}",
                confidence=0.85,
                deterministic=True,
            )
        )
    return claims


def _route_exception_claims(source_path: str, route: _JavaRoute) -> list[JavaEvidenceClaim]:
    names = sorted(set([*_THROWS.findall(route.body), *_THROW_NEW.findall(route.body)]))
    return [
        JavaExceptionClaim(
            id=_claim_id("exception", route.operation_ref, name),
            source_path=source_path,
            operation_ref=route.operation_ref,
            exception_type=name.rsplit(".", 1)[-1],
            outcome="exception",
            confidence=0.9,
            deterministic=True,
        )
        for name in names
    ]


def _route_kafka_claims(source_path: str, route: _JavaRoute) -> list[JavaEvidenceClaim]:
    produced: list[JavaEvidenceClaim] = [
        JavaKafkaEventClaim(
            id=_claim_id("kafka", route.operation_ref, "produce", topic),
            source_path=source_path,
            operation_ref=route.operation_ref,
            direction="produce",
            topic_ref=f"kafka://{topic}",
            event_type="UnknownEvent",
            confidence=0.7,
            deterministic=False,
        )
        for topic in _KAFKA_SEND.findall(route.body)
    ]
    return produced


def _structural_java_claims(
    file: JavaSourceFileSnapshot,
    routes: list[_JavaRoute],
    type_fields: dict[str, list[tuple[str, str, list[tuple[str, str]]]]],
) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    declarations = list(_TYPE_DECLARATION.finditer(file.content))
    for declaration in declarations:
        name = declaration.group("name")
        source_path = f"{file.path}:{file.content.count(chr(10), 0, declaration.start()) + 1}"
        if declaration.group("kind") == "interface" and name.endswith(("Mapper", "Repository")):
            claims.append(
                JavaPersistenceClaim(
                    id=_claim_id("repository", name),
                    source_path=source_path,
                    repository_ref=f"java://{name}",
                    confidence=1,
                    deterministic=True,
                )
            )
        if _is_entity_type(file.path, name):
            table_name = _snake_case(name)
            operation_refs = [
                route.operation_ref
                for route in routes
                if _route_resource_token(route.path) == _normalized_name(table_name)
            ]
            claims.append(
                JavaEntityClaim(
                    id=_claim_id("entity", name),
                    source_path=source_path,
                    entity_ref=f"entity://{name}",
                    class_name=name,
                    table_ref=f"table://{table_name}",
                    operation_refs=operation_refs,
                    confidence=0.65,
                    deterministic=False,
                )
            )
            claims.extend(
                JavaTableColumnClaim(
                    id=_claim_id("column", name, field_name),
                    source_path=source_path,
                    entity_ref=f"entity://{name}",
                    table_ref=f"table://{table_name}",
                    field_name=field_name,
                    column_name=_snake_case(field_name),
                    confidence=0.65,
                    deterministic=False,
                )
                for field_name, _field_type, _annotations in type_fields.get(name, [])
            )
        if declaration.group("kind") == "enum":
            values = _enum_values(_type_body(file.content, declaration.end()))
            if values:
                claims.append(
                    JavaEnumStateClaim(
                        id=_claim_id("enum", name),
                        source_path=source_path,
                        enum_ref=f"java://{name}",
                        values=values,
                        confidence=0.8,
                        deterministic=True,
                    )
                )
    claims.extend(_listener_claims(file))
    return claims


def _is_entity_type(path: str, name: str) -> bool:
    lowered = path.lower()
    return "/domain/" in lowered or "/entity/" in lowered or name.endswith("Entity")


def _enum_values(body: str) -> list[str]:
    header = body.split(";", 1)[0]
    return re.findall(r"\b([A-Z][A-Z0-9_]*)\b", header)[:100]


def _listener_claims(file: JavaSourceFileSnapshot) -> list[JavaEvidenceClaim]:
    return [
        JavaKafkaEventClaim(
            id=_claim_id("kafka", file.path, "consume", topic),
            source_path=f"{file.path}:1",
            direction="consume",
            topic_ref=f"kafka://{topic}",
            event_type="UnknownEvent",
            confidence=0.7,
            deterministic=False,
        )
        for topic in _KAFKA_LISTENER.findall(file.content)
    ]


def _deduplicate_java_claims(claims: list[JavaEvidenceClaim]) -> list[JavaEvidenceClaim]:
    unique = {claim.id: claim for claim in claims}
    return [unique[key] for key in sorted(unique)]


def _bounded_java_claims(claims: list[JavaEvidenceClaim]) -> list[JavaEvidenceClaim]:
    limits = {
        "controller_route": 12,
        "dto_field": 18,
        "bean_validation": 8,
        "service_call": 10,
        "feign_call": 3,
        "mapper_repository": 4,
        "entity": 4,
        "table_column": 8,
        "enum_state": 3,
        "exception": 3,
        "kafka_event": 3,
    }
    grouped: dict[str, list[JavaEvidenceClaim]] = defaultdict(list)
    for claim in _deduplicate_java_claims(claims):
        grouped[claim.kind].append(claim)
    bounded = [
        claim
        for kind in limits
        for claim in sorted(grouped[kind], key=lambda item: (item.source_path, item.id))[
            : limits[kind]
        ]
    ]
    return bounded[:MAX_ADAPTER_CLAIMS]


def _claim_id(*parts: str) -> str:
    key = "|".join(parts)
    digest = (
        sha256(key.encode()).hexdigest()[:24].translate(str.maketrans("0123456789", "ghijklmnop"))
    )
    return f"claim-{digest}"


def _snake_case(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()
