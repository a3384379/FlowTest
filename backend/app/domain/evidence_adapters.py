# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

"""Pure contracts and deterministic adapters for external code and database evidence."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    ValidationError,
    model_validator,
)

from app.domain.evidence import EvidenceBundle, EvidenceFinding, EvidenceSourceType
from app.domain.test_contexts import (
    MAX_EXTERNAL_EVIDENCE_BYTES,
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
    require_no_sensitive_reference_values,
    require_no_sensitive_scalar_values,
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
    r"@(?:(?P<method>Get|Post|Put|Patch|Delete)Mapping|RequestMapping)\b"
)
_MAPPING_ANNOTATION_MARKER = re.compile(r"@(?:Get|Post|Put|Patch|Delete|Request)Mapping\b")
_REQUEST_MAPPING = re.compile(r"@RequestMapping\b")
_REQUEST_MAPPING_MARKER = re.compile(r"@RequestMapping\b")
_CONTROLLER_ANNOTATION = re.compile(r"@(?:RestController|Controller)\b")
_TYPE_DECLARATION = re.compile(
    r"\b(?P<kind>class|record|enum|interface)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
)
_FIELD_DECLARATION = re.compile(
    r"\bprivate\s+(?:static\s+|final\s+|transient\s+)*"
    r"(?P<type>[A-Za-z0-9_$<>,.?\[\]]+)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:\s*=\s*[^;]{0,1000})?\s*;"
)
_VALIDATION_ANNOTATION_NAMES = (
    r"NotNull|NotBlank|NotEmpty|Size|Min|Max|Positive|PositiveOrZero|"
    r"Negative|NegativeOrZero|Email|Pattern|DecimalMin|DecimalMax|Valid"
)
_VALIDATION_ANNOTATION = re.compile(rf"@(?P<name>{_VALIDATION_ANNOTATION_NAMES})\b")
_VALIDATION_ANNOTATION_MARKER = re.compile(rf"@(?:{_VALIDATION_ANNOTATION_NAMES})\b")
_VALIDATED_GETTER = re.compile(
    rf"(?P<annotations>(?:\s*@(?:{_VALIDATION_ANNOTATION_NAMES})\b[^\n]*(?:\r?\n|$))+)"
    r"\s*public\s+[A-Za-z0-9_$<>,.?\[\]]+\s+get(?P<name>[A-Z][A-Za-z0-9_$]*)\s*\("
)
_SERVICE_CALL = re.compile(
    r"\b(?P<target>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\.(?P<method>[A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
_THROWS = re.compile(r"\bthrows\s+([A-Za-z_$][A-Za-z0-9_$.]*)")
_THROW_NEW = re.compile(r"\bthrow\s+new\s+([A-Za-z_$][A-Za-z0-9_$.]*)")
_KAFKA_SEND = re.compile(r"\b(?:kafkaTemplate|KafkaTemplate)\.send\s*\(\s*\"([^\"]+)\"")
_KAFKA_SEND_MARKER = re.compile(r"\b(?:kafkaTemplate|KafkaTemplate)\.send\b")
_KAFKA_LISTENER = re.compile(r"@KafkaListener\b")
_KAFKA_LISTENER_MARKER = re.compile(r"@KafkaListener\b")
_JAVA_NON_CODE = re.compile(
    r"//[^\r\n]*(?:\r?\n|$)"
    r"|/\*.*?(?:\*/|$)"
    r'|"""(?:(?!""").)*(?:"""|$)'
    r'|"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'",
    re.DOTALL,
)


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

    @model_validator(mode="after")
    def validate_source_path(self) -> JavaClaimBase:
        require_no_sensitive_scalar_values([self.source_path])
        require_no_sensitive_reference_values(self)
        return self


class JavaControllerRouteClaim(JavaClaimBase):
    kind: Literal["controller_route"] = "controller_route"
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    controller_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    handler: str = Field(pattern=_IDENTIFIER)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(min_length=1, max_length=500, pattern=r"^/[^\s]*$")

    @model_validator(mode="after")
    def validate_route_path(self) -> JavaControllerRouteClaim:
        require_no_sensitive_scalar_values([self.handler, self.path])
        return self


class JavaDtoFieldClaim(JavaClaimBase):
    kind: Literal["dto_field"] = "dto_field"
    operation_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    direction: Literal["request", "response"]
    dto_type: str = Field(pattern=_IDENTIFIER)
    field_name: str = Field(pattern=_IDENTIFIER)
    field_type: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_field_type(self) -> JavaDtoFieldClaim:
        require_no_sensitive_scalar_values([self.dto_type, self.field_name, self.field_type])
        return self


class JavaBeanValidationClaim(JavaClaimBase):
    kind: Literal["bean_validation"] = "bean_validation"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    dto_type: str = Field(pattern=_IDENTIFIER)
    field_name: str = Field(pattern=_IDENTIFIER)
    annotation: str = Field(pattern=_IDENTIFIER)
    constraint: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_constraint(self) -> JavaBeanValidationClaim:
        require_no_sensitive_scalar_values(
            [self.dto_type, self.field_name, self.annotation, self.constraint]
        )
        return self


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
        require_no_sensitive_scalar_values([self.class_name])
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

    @model_validator(mode="after")
    def validate_identifiers(self) -> JavaTableColumnClaim:
        require_no_sensitive_scalar_values([self.field_name, self.column_name])
        return self


class JavaEnumStateClaim(JavaClaimBase):
    kind: Literal["enum_state"] = "enum_state"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    enum_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    field_name: str | None = Field(default=None, pattern=_IDENTIFIER)
    values: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_state_values(self) -> JavaEnumStateClaim:
        require_no_sensitive_scalar_values(
            [*([self.field_name] if self.field_name is not None else []), *self.values]
        )
        return self


class JavaExceptionClaim(JavaClaimBase):
    kind: Literal["exception"] = "exception"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    exception_type: str = Field(pattern=_IDENTIFIER)
    outcome: str = Field(min_length=1, max_length=160, pattern=_IDENTIFIER)

    @model_validator(mode="after")
    def validate_identifiers(self) -> JavaExceptionClaim:
        require_no_sensitive_scalar_values([self.exception_type, self.outcome])
        return self


class JavaKafkaEventClaim(JavaClaimBase):
    kind: Literal["kafka_event"] = "kafka_event"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    direction: Literal["produce", "consume"]
    topic_ref: str = Field(min_length=1, max_length=512, pattern=_REF)
    event_type: str = Field(pattern=_IDENTIFIER)

    @model_validator(mode="after")
    def validate_event_type(self) -> JavaKafkaEventClaim:
        require_no_sensitive_scalar_values([self.event_type])
        return self


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
        _require_java_envelope_budget(self)
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
    def validate_observed_values(self) -> DatabaseObservedDistribution:
        if (
            self.row_count is not None
            and self.distinct_count is not None
            and self.distinct_count > self.row_count
        ):
            raise ValueError("database observed distinct count must not exceed row count")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("database observed minimum must not exceed maximum")
        extrema = [value for value in (self.minimum, self.maximum) if value is not None]
        require_no_sensitive_scalar_values([*extrema, *self.enum_candidates])
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
        require_no_sensitive_scalar_values([self.name, self.data_type])
        if self.foreign_key is not None:
            require_no_sensitive_scalar_values([self.foreign_key])
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


class DatabaseTableEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(pattern=_IDENTIFIER)
    name: str = Field(pattern=_IDENTIFIER)
    columns: list[DatabaseColumnEvidence] = Field(min_length=1, max_length=MAX_ADAPTER_CLAIMS)

    @model_validator(mode="after")
    def validate_column_names(self) -> DatabaseTableEvidence:
        require_no_sensitive_scalar_values([self.schema_name, self.name])
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
        _require_database_envelope_budget(self)
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
        structural_truncated = False
        for file in sorted(snapshot.files, key=lambda item: item.path):
            file_routes = _java_routes(file)
            claims.extend(_route_claims(file, file_routes, type_fields))
            structural_claims, file_truncated = _structural_java_claims(
                file, file_routes, type_fields
            )
            claims.extend(structural_claims)
            structural_truncated = structural_truncated or file_truncated
        bounded_claims, claim_truncated = _bounded_java_claims(claims)
        truncated = structural_truncated or claim_truncated
        warnings = [
            ExternalEvidenceWarning(
                code="JAVA_POC_STATIC_ONLY",
                message="Java/Spring POC 仅执行静态文本分析，未编译或执行目标代码。",
            )
        ]
        if truncated:
            warnings.append(
                ExternalEvidenceWarning(
                    code="JAVA_POC_INCOMPLETE_BUDGET",
                    message="Java/Spring POC 证据超过有界配额，分析结果已截断且不完整。",
                )
            )
        return JavaEvidenceSubmission(
            provider=snapshot.provider,
            source=snapshot.source,
            subject_ref=snapshot.subject_ref,
            claims=bounded_claims,
            confidence=min((claim.confidence for claim in bounded_claims), default=0.5),
            deterministic=all(claim.deterministic for claim in bounded_claims),
            warnings=warnings,
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
                identifier=_database_finding_id("table", table.schema_name, table.name),
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


def _require_database_envelope_budget(submission: DatabaseEvidenceSubmission) -> None:
    try:
        adapt_database_evidence(submission)
    except ValidationError as exc:
        if "external evidence byte budget exceeded" not in str(exc):
            raise
        raise ValueError("database evidence envelope byte budget exceeded") from None


def _require_java_envelope_budget(submission: JavaEvidenceSubmission) -> None:
    try:
        adapt_java_evidence(submission)
    except ValidationError as exc:
        if "external evidence byte budget exceeded" not in str(exc):
            raise
        raise ValueError("java evidence envelope byte budget exceeded") from None


def adapt_evidence_bundle(
    bundle: EvidenceBundle,
    *,
    provider_name: str,
    provider_version: str,
    source_ref: str,
    source_revision: str,
    subject_ref: str,
) -> ExternalEvidenceEnvelope:
    require_no_sensitive_scalar_values(bundle.warnings)
    for finding in bundle.findings:
        require_no_sensitive_scalar_values([finding.path, *finding.warnings])
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
    existing_keys = _existing_mapping_conflict_keys(provisional)
    conflicts = [
        conflict
        for conflict in derive_entity_mapping(provisional).conflicts
        if (conflict.kind.value, conflict.source_ref) not in existing_keys
    ]
    if not conflicts:
        return envelope
    available = max(0, 100 - len(envelope.findings))
    if len(conflicts) > available:
        raise EntityMappingBudgetExceeded(
            "entity mapping conflict findings exceed envelope capacity"
        )
    addition_ids = [
        _claim_id("mapping-conflict", conflict.kind.value, conflict.source_ref)
        for conflict in conflicts
    ]
    existing_ids = {finding.id for finding in envelope.findings}
    if len(addition_ids) != len(set(addition_ids)) or existing_ids.intersection(addition_ids):
        raise EntityMappingBudgetExceeded(
            "derived mapping conflict finding id collides with existing evidence"
        )
    additions = [
        _external_finding(
            identifier=identifier,
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
        for conflict, identifier in zip(conflicts, addition_ids, strict=True)
    ]
    payload = envelope.model_dump(mode="json")
    payload["findings"] = [
        item.model_dump(mode="json") for item in [*envelope.findings, *additions]
    ]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(serialized) > MAX_EXTERNAL_EVIDENCE_BYTES:
        raise EntityMappingBudgetExceeded(
            "derived mapping conflicts exceed the evidence envelope byte budget"
        )
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
                identifier=_database_finding_id(
                    "column",
                    table.schema_name,
                    table.name,
                    column.name,
                ),
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
        id=_bounded_finding_id(identifier),
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


def _existing_mapping_conflict_keys(
    evidence: list[MappingEvidenceInput],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for item in evidence:
        data = item.finding.structured_data
        if (
            not isinstance(data, EntityMappingExternalEvidenceStructuredData)
            or item.finding.kind is not EvidenceFindingKind.CONFLICT
            or item.finding.semantic_role is not EvidenceSemanticRole.CONFLICT
        ):
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
    if not source_types:
        return EvidenceProviderType.REPOSITORY
    if len(source_types) != 1:
        raise ValueError("Evidence Bundle must contain exactly one source type")
    source_type = next(iter(source_types))
    return {
        EvidenceSourceType.CONTRACT: EvidenceProviderType.CONTRACT,
        EvidenceSourceType.DATA_PROFILE: EvidenceProviderType.DATA_PROFILE,
        EvidenceSourceType.EXISTING_TEST: EvidenceProviderType.EXISTING_TEST,
        EvidenceSourceType.WORKFLOW: EvidenceProviderType.WORKFLOW,
        EvidenceSourceType.RUNTIME: EvidenceProviderType.RUNTIME,
    }.get(source_type, EvidenceProviderType.REPOSITORY)


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
        self.table_columns: list[tuple[JavaTableColumnClaim, str]] = []
        self.tables: list[_ParsedDatabaseTableClaim] = []
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
class _ParsedDatabaseTableClaim:
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


@dataclass(frozen=True, slots=True)
class _EntityMatch:
    score: float
    evidence_refs: tuple[str, ...]
    deterministic: bool


@dataclass(frozen=True, slots=True)
class _OperationEntityScope:
    entities: tuple[tuple[JavaEntityClaim, str], ...]
    allow_route_fallback: bool
    correlate_entities_with_route: bool
    blocked_table_refs: tuple[str, ...]


def _require_mapping_claim_budget(parsed: _ParsedEvidence) -> None:
    count = sum(
        len(items)
        for items in (
            parsed.routes,
            parsed.fields,
            parsed.entities,
            parsed.table_columns,
            parsed.tables,
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
        elif isinstance(data, DatabaseExternalEvidenceStructuredData):
            _append_database_mapping_claim(
                parsed,
                data,
                item.evidence_ref,
                item.effective_confidence,
                item.effective_deterministic,
            )
    return parsed


def _append_database_mapping_claim(
    parsed: _ParsedEvidence,
    data: DatabaseExternalEvidenceStructuredData,
    evidence_ref: str,
    confidence: float,
    deterministic: bool,
) -> None:
    if data.claim_kind == "table" and isinstance(data.claim, ExternalDatabaseTableClaim):
        parsed.tables.append(
            _ParsedDatabaseTableClaim(
                schema=data.claim.schema_name,
                table=data.claim.name,
                evidence_ref=evidence_ref,
                confidence=confidence,
                deterministic=deterministic,
            )
        )
    elif data.claim_kind == "column" and isinstance(data.claim, ExternalDatabaseColumnClaim):
        parsed.columns.append(
            _ParsedDatabaseColumn(
                claim=DatabaseColumnEvidence.model_validate(
                    data.claim.model_dump(mode="json", exclude={"schema_name", "table_name"})
                ),
                schema=data.claim.schema_name,
                table=data.claim.table_name,
                evidence_ref=evidence_ref,
                confidence=confidence,
                deterministic=deterministic,
            )
        )


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
    elif claim_kind == "table_column":
        parsed.table_columns.append(
            (
                _effective_java_claim(
                    JavaTableColumnClaim.model_validate(claim), confidence, deterministic
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
    tables = _table_evidence(parsed)
    for route, route_evidence in parsed.routes:
        entity_scope = _operation_entity_scope(route, parsed)
        for table_ref, table in tables.items():
            schema_name, table_name = table_ref.removeprefix("table://").rsplit("/", 1)
            entity_match = _entity_match(route, schema_name, table_name, entity_scope)
            if entity_match.score == 0:
                continue
            direct_evidence = [route_evidence, *entity_match.evidence_refs]
            table_evidence = list(table.evidence_refs)[: 20 - len(direct_evidence)]
            _append_mapping_candidate(
                candidates,
                _candidate(
                    kind=EntityMappingCandidateKind.OPERATION_ENTITY,
                    source_ref=route.operation_ref,
                    target_ref=f"entity://{table_ref.removeprefix('table://')}",
                    operation_ref=route.operation_ref,
                    confidence=min(route.confidence, entity_match.score, table.confidence),
                    deterministic=(
                        route.deterministic
                        and entity_match.score == 1
                        and entity_match.deterministic
                        and table.deterministic
                    ),
                    evidence_refs=[
                        *direct_evidence,
                        *table_evidence,
                    ],
                ),
            )
    return list(candidates.values())


def _operation_entity_scope(
    route: JavaControllerRouteClaim,
    parsed: _ParsedEvidence,
) -> _OperationEntityScope:
    explicit = [
        (entity, ref)
        for entity, ref in parsed.entities
        if route.operation_ref in entity.operation_refs
    ]
    if explicit:
        return _OperationEntityScope(
            entities=tuple(explicit),
            allow_route_fallback=False,
            correlate_entities_with_route=False,
            blocked_table_refs=(),
        )
    return _OperationEntityScope(
        entities=tuple(
            (entity, ref) for entity, ref in parsed.entities if not entity.operation_refs
        ),
        allow_route_fallback=True,
        correlate_entities_with_route=True,
        blocked_table_refs=tuple(sorted(_foreign_table_refs(parsed, route.operation_ref))),
    )


def _entity_match(
    route: JavaControllerRouteClaim,
    schema_name: str,
    table_name: str,
    scope: _OperationEntityScope,
) -> _EntityMatch:
    table_token = _normalized_name(table_name)
    route_token = _route_resource_token(route.path)
    route_correlated = bool(route_token) and (
        table_token == route_token or table_token.endswith(route_token)
    )
    entity_matches_are_allowed = not scope.correlate_entities_with_route or route_correlated
    exact_matches = [
        (entity, evidence_ref)
        for entity, evidence_ref in scope.entities
        if entity_matches_are_allowed
        and entity.table_ref is not None
        and _table_ref_matches_database_table(entity.table_ref, schema_name, table_name)
    ]
    if exact_matches:
        return _combined_entity_match(exact_matches, maximum_score=1.0, deterministic=True)
    inferred_matches = [
        (entity, evidence_ref)
        for entity, evidence_ref in scope.entities
        if entity_matches_are_allowed
        and entity.table_ref is None
        and _normalized_name(entity.class_name) == table_token
    ]
    if inferred_matches:
        return _combined_entity_match(inferred_matches, maximum_score=0.9, deterministic=False)
    if not scope.allow_route_fallback or any(
        _table_ref_matches_database_table(table_ref, schema_name, table_name)
        for table_ref in scope.blocked_table_refs
    ):
        return _EntityMatch(score=0, evidence_refs=(), deterministic=False)
    if route_correlated:
        return _EntityMatch(score=0.75, evidence_refs=(), deterministic=False)
    return _EntityMatch(score=0, evidence_refs=(), deterministic=False)


def _combined_entity_match(
    matches: list[tuple[JavaEntityClaim, str]],
    *,
    maximum_score: float,
    deterministic: bool,
) -> _EntityMatch:
    return _EntityMatch(
        score=min(maximum_score, *(entity.confidence for entity, _ref in matches)),
        evidence_refs=tuple(sorted({ref for _entity, ref in matches}))[:18],
        deterministic=deterministic and all(entity.deterministic for entity, _ref in matches),
    )


def _table_evidence(
    parsed: _ParsedEvidence,
) -> dict[str, _ParsedDatabaseTable]:
    table_claims: dict[str, list[_ParsedDatabaseTableClaim]] = defaultdict(list)
    columns: dict[str, list[_ParsedDatabaseColumn]] = defaultdict(list)
    for table in parsed.tables:
        table_claims[f"table://{table.schema}/{table.table}"].append(table)
    for column in parsed.columns:
        columns[f"table://{column.schema}/{column.table}"].append(column)
    result: dict[str, _ParsedDatabaseTable] = {}
    for key in table_claims.keys() | columns.keys():
        direct = table_claims[key]
        supplemental = columns[key]
        evidence_refs = tuple(
            dict.fromkeys(
                [
                    *(
                        item.evidence_ref
                        for item in sorted(direct, key=lambda item: item.evidence_ref)
                    ),
                    *(
                        item.evidence_ref
                        for item in sorted(supplemental, key=lambda item: item.evidence_ref)
                    ),
                ]
            )
        )[:20]
        sources: list[_ParsedDatabaseTableClaim | _ParsedDatabaseColumn] = [
            *direct,
            *supplemental,
        ]
        result[key] = _ParsedDatabaseTable(
            evidence_refs=evidence_refs,
            confidence=min(item.confidence for item in sources),
            deterministic=all(item.deterministic for item in sources),
        )
    return result


def _field_column_candidates(parsed: _ParsedEvidence) -> list[EntityMappingCandidate]:
    operation_tables = _operation_tables(_operation_entity_candidates(parsed))
    candidates: dict[str, EntityMappingCandidate] = {}
    for field, field_evidence in parsed.fields:
        table_targets = operation_tables.get(field.operation_ref, {})
        has_explicit_entity_scope = any(
            field.operation_ref in entity.operation_refs for entity, _ref in parsed.entities
        )
        blocked_table_refs = _foreign_table_refs(parsed, field.operation_ref)
        field_claims = _table_column_claims_for_field(parsed, field)
        for parsed_column in parsed.columns:
            column = parsed_column.claim
            entity_ref = f"entity://{parsed_column.schema}/{parsed_column.table}"
            if table_targets and entity_ref not in table_targets:
                continue
            if not table_targets and has_explicit_entity_scope:
                continue
            if not table_targets and any(
                _table_ref_matches_database_table(
                    table_ref,
                    parsed_column.schema,
                    parsed_column.table,
                )
                for table_ref in blocked_table_refs
            ):
                continue
            matching_claims = [
                item
                for item in field_claims
                if _table_ref_matches_database_table(
                    item[0].table_ref,
                    parsed_column.schema,
                    parsed_column.table,
                )
                and item[0].column_name.casefold() == column.name.casefold()
            ]
            if field_claims and not matching_claims:
                continue
            if not field_claims and _normalized_name(field.field_name) != _normalized_name(
                column.name
            ):
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
            operation_table = table_targets.get(entity_ref)
            operation_confidence = operation_table.confidence if operation_table else 1.0
            operation_deterministic = operation_table.deterministic if operation_table else True
            operation_evidence = operation_table.evidence_refs if operation_table else []
            claim_confidence = min(
                (claim.confidence for claim, _evidence_ref in matching_claims),
                default=1.0,
            )
            claim_deterministic = all(
                claim.deterministic for claim, _evidence_ref in matching_claims
            )
            claim_evidence = sorted({evidence_ref for _claim, evidence_ref in matching_claims})[:5]
            bounded_operation_evidence = list(operation_evidence)[: 18 - len(claim_evidence)]
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
                    confidence=min(
                        field.confidence,
                        parsed_column.confidence,
                        operation_confidence,
                        claim_confidence,
                    ),
                    deterministic=(
                        field.deterministic
                        and parsed_column.deterministic
                        and operation_deterministic
                        and claim_deterministic
                    ),
                    evidence_refs=[
                        field_evidence,
                        parsed_column.evidence_ref,
                        *claim_evidence,
                        *bounded_operation_evidence,
                    ],
                ),
            )
    return list(candidates.values())


def _table_column_claims_for_field(
    parsed: _ParsedEvidence,
    field: JavaDtoFieldClaim,
) -> list[tuple[JavaTableColumnClaim, str]]:
    operation_entities = {
        entity.entity_ref
        for entity, _evidence_ref in parsed.entities
        if field.operation_ref in entity.operation_refs
    }
    foreign_entities = {
        entity.entity_ref
        for entity, _evidence_ref in parsed.entities
        if entity.operation_refs and field.operation_ref not in entity.operation_refs
    }
    return [
        item
        for item in parsed.table_columns
        if item[0].field_name.casefold() == field.field_name.casefold()
        and (
            item[0].entity_ref in operation_entities
            if operation_entities
            else item[0].entity_ref not in foreign_entities
        )
    ]


def _foreign_table_refs(
    parsed: _ParsedEvidence,
    operation_ref: str,
) -> set[str]:
    foreign_entities = {
        entity.entity_ref
        for entity, _evidence_ref in parsed.entities
        if entity.operation_refs and operation_ref not in entity.operation_refs
    }
    return {
        *(
            entity.table_ref
            for entity, _evidence_ref in parsed.entities
            if entity.entity_ref in foreign_entities and entity.table_ref is not None
        ),
        *(
            claim.table_ref
            for claim, _evidence_ref in parsed.table_columns
            if claim.entity_ref in foreign_entities
        ),
    }


def _operation_state_candidates(parsed: _ParsedEvidence) -> list[EntityMappingCandidate]:
    java_candidates = _java_state_candidates(parsed.states)
    candidates: dict[str, EntityMappingCandidate] = {}
    corroborated_java_ids: set[str] = set()
    operation_tables = _operation_tables(_operation_entity_candidates(parsed))
    for operation_ref, table_candidates in operation_tables.items():
        for parsed_column in parsed.columns:
            entity_ref = f"entity://{parsed_column.schema}/{parsed_column.table}"
            operation_table = table_candidates.get(entity_ref)
            if operation_table is None:
                continue
            column_candidates, corroborated_ids = _database_state_candidates(
                operation_ref,
                operation_table,
                parsed_column,
                java_candidates,
            )
            if not column_candidates:
                continue
            corroborated_java_ids.update(corroborated_ids)
            for candidate in column_candidates:
                _append_mapping_candidate(candidates, candidate)
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
            source_ref=_state_field_ref(state.operation_ref, state.field_name),
            target_ref=f"state-set://{state.enum_ref.removeprefix('java://')}",
            operation_ref=state.operation_ref,
            field_ref=(
                _state_field_ref(state.operation_ref, state.field_name)
                if state.field_name is not None
                else None
            ),
            state_values=state.values,
            confidence=state.confidence,
            deterministic=state.deterministic,
            evidence_refs=[evidence_ref],
        )
        for state, evidence_ref in states
        if state.operation_ref is not None
    ]


def _database_state_candidates(
    operation_ref: str,
    operation_table: EntityMappingCandidate,
    parsed_column: _ParsedDatabaseColumn,
    java_candidates: list[EntityMappingCandidate],
) -> tuple[list[EntityMappingCandidate], set[str]]:
    column = parsed_column.claim
    value_sets = _database_state_value_sets(column)
    field_candidates = [
        candidate
        for candidate in java_candidates
        if _state_candidate_matches_column(candidate, operation_ref, column.name)
    ]
    if not value_sets or (
        not field_candidates and _normalized_name(column.name) not in {"status", "state"}
    ):
        return [], set()
    anchor = next(
        (candidate for candidate in field_candidates if candidate.field_ref is not None),
        field_candidates[0] if field_candidates else None,
    )
    source_ref = (
        anchor.source_ref if anchor is not None else _state_field_ref(operation_ref, column.name)
    )
    field_ref = anchor.field_ref if anchor is not None else source_ref
    candidates: list[EntityMappingCandidate] = []
    corroborated_ids: set[str] = set()
    for values in value_sets:
        corroborating = [
            candidate for candidate in field_candidates if candidate.state_values == values
        ]
        corroborated_ids.update(candidate.id for candidate in corroborating)
        corroborating_evidence = sorted(
            {
                evidence_ref
                for candidate in corroborating
                for evidence_ref in candidate.evidence_refs
            }
        )[:6]
        operation_evidence = operation_table.evidence_refs[: 19 - len(corroborating_evidence)]
        candidates.append(
            _candidate(
                kind=EntityMappingCandidateKind.OPERATION_STATE,
                source_ref=source_ref,
                target_ref=(
                    f"state-set://{parsed_column.schema}/{parsed_column.table}/{column.name}"
                ),
                operation_ref=operation_ref,
                field_ref=field_ref,
                state_values=values,
                confidence=min(
                    [
                        parsed_column.confidence,
                        operation_table.confidence,
                        *(candidate.confidence for candidate in corroborating),
                    ]
                ),
                deterministic=(
                    parsed_column.deterministic
                    and operation_table.deterministic
                    and all(candidate.deterministic for candidate in corroborating)
                ),
                evidence_refs=[
                    parsed_column.evidence_ref,
                    *corroborating_evidence,
                    *operation_evidence,
                ],
            )
        )
    return candidates, corroborated_ids


def _state_candidate_matches_column(
    candidate: EntityMappingCandidate,
    operation_ref: str,
    column_name: str,
) -> bool:
    if candidate.operation_ref != operation_ref:
        return False
    if candidate.field_ref is None:
        return _normalized_name(column_name) in {"status", "state"}
    return candidate.field_ref == _state_field_ref(operation_ref, column_name)


def _state_field_ref(operation_ref: str, field_name: str | None) -> str:
    if field_name is None:
        return operation_ref
    operation_identity = sha256(operation_ref.encode()).hexdigest()
    field_identity = _normalized_name(field_name) or sha256(field_name.encode()).hexdigest()
    return f"state-field://{operation_identity}/{field_identity}"


def _database_state_value_sets(column: DatabaseColumnEvidence) -> list[list[str]]:
    declared = sorted({_state_scalar_text(value) for value in column.enum_values})
    observed = (
        sorted(
            {_state_scalar_text(value) for value in column.observed_distribution.enum_candidates}
        )
        if column.observed_distribution is not None
        else []
    )
    result: list[list[str]] = []
    for values in (declared, observed):
        if values and values not in result:
            result.append(values)
    return result


def _state_scalar_text(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _operation_tables(
    candidates: list[EntityMappingCandidate],
) -> dict[str, dict[str, EntityMappingCandidate]]:
    result: dict[str, dict[str, EntityMappingCandidate]] = defaultdict(dict)
    for candidate in candidates:
        result[candidate.operation_ref][candidate.target_ref] = candidate
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
    values = sorted(set(state_values or []))
    if len(values) > 100:
        raise EntityMappingBudgetExceeded("entity mapping state value budget exceeded")
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
            "confidence": min(first.confidence, second.confidence),
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
        if _candidate_group_is_conflicted(kind, group)
    ]


def _candidate_group_is_conflicted(
    kind: EntityMappingCandidateKind,
    candidates: list[EntityMappingCandidate],
) -> bool:
    if kind is EntityMappingCandidateKind.OPERATION_STATE:
        return len(candidates) > 1
    return len({candidate.target_ref for candidate in candidates}) > 1


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


def _table_ref_matches_database_table(
    table_ref: str,
    schema_name: str,
    table_name: str,
) -> bool:
    qualified_name = table_ref.removeprefix("table://").rstrip("/")
    if "/" in qualified_name:
        referenced_schema, referenced_table = qualified_name.rsplit("/", 1)
        referenced_schema = referenced_schema.rsplit("/", 1)[-1]
    elif "." in qualified_name:
        referenced_schema, referenced_table = qualified_name.rsplit(".", 1)
    else:
        referenced_schema, referenced_table = None, qualified_name
    table_matches = referenced_table.casefold() == table_name.casefold()
    return table_matches and (
        referenced_schema is None or referenced_schema.casefold() == schema_name.casefold()
    )


class _JavaRoute(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    operation_ref: str
    controller_ref: str
    handler: str
    return_type: str
    parameters: str
    declared_exceptions: list[str]
    body: str
    source_line: int


def _java_type_fields(
    files: list[JavaSourceFileSnapshot],
) -> dict[str, list[tuple[str, str, list[tuple[str, str]]]]]:
    definitions: dict[
        str,
        list[list[tuple[str, str, list[tuple[str, str]]]]],
    ] = defaultdict(list)
    for file in files:
        masked_content = _mask_java_non_code(file.content)
        for declaration in _TYPE_DECLARATION.finditer(masked_content):
            name = declaration.group("name")
            body = _type_body(file.content, declaration.end())
            fields = (
                _record_fields(file.content, declaration)
                if declaration.group("kind") == "record"
                else _class_fields(body)
            )
            definitions[name].append(fields)
    return {name: items[0] for name, items in definitions.items() if len(items) == 1}


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
    if opening < 0:
        return []
    closing = _matching_parenthesis(content, opening)
    components = _split_top_level_java_components(content[opening + 1 : closing])
    return [
        field
        for component in components
        if (field := _record_component_field(component)) is not None
    ]


def _split_top_level_java_components(content: str) -> list[str]:
    components: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(content):
        non_code = _JAVA_NON_CODE.match(content, index)
        if non_code is not None:
            index = non_code.end()
            continue
        character = content[index]
        if character in "([{<":
            depth += 1
        elif character in ")]}>" and depth > 0:
            depth -= 1
        elif character == "," and depth == 0:
            components.append(content[start:index])
            start = index + 1
        index += 1
    components.append(content[start:])
    return components


def _record_component_field(
    component: str,
) -> tuple[str, str, list[tuple[str, str]]] | None:
    masked_component = _mask_java_non_code(component)
    annotations = _java_validation_annotations(component, masked_component)
    masked = _mask_java_annotation_arguments(masked_component)
    declaration = re.sub(r"@[A-Za-z_$][A-Za-z0-9_$.]*", " ", masked)
    normalized = " ".join(declaration.split())
    match = re.fullmatch(
        r"(?P<type>.+?)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)",
        normalized,
    )
    if match is None:
        return None
    return match.group("name"), match.group("type"), annotations


def _class_fields(body: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    fields: list[tuple[str, str, list[tuple[str, str]]]] = []
    masked_body = _mask_nested_java_blocks(_mask_java_non_code(body))
    for match in _FIELD_DECLARATION.finditer(masked_body):
        prefix_start = max(0, match.start() - 500)
        masked_prefix = masked_body[prefix_start : match.start()]
        annotation_start = masked_prefix.rfind(";") + 1
        annotations = _java_validation_annotations(
            body[prefix_start + annotation_start : match.start()],
            masked_prefix[annotation_start:],
        )
        fields.append((match.group("name"), match.group("type"), annotations))
    known = {field[0] for field in fields}
    for match in _VALIDATED_GETTER.finditer(masked_body):
        name = match.group("name")
        field_name = name[0].lower() + name[1:]
        annotation_start, annotation_end = match.span("annotations")
        annotations = _java_validation_annotations(
            body[annotation_start:annotation_end],
            masked_body[annotation_start:annotation_end],
        )
        if field_name in known:
            index = next(index for index, field in enumerate(fields) if field[0] == field_name)
            old = fields[index]
            fields[index] = (old[0], old[1], sorted(set([*old[2], *annotations])))
    return fields


def _java_validation_annotations(
    content: str,
    masked_content: str,
) -> list[tuple[str, str]]:
    return [
        (
            annotation.group("name"),
            _java_annotation_arguments(content, annotation.end())[:500],
        )
        for annotation in _active_java_annotation_matches(
            content,
            masked_content,
            _VALIDATION_ANNOTATION_MARKER,
            _VALIDATION_ANNOTATION,
        )
    ]


def _java_annotation_arguments(content: str, annotation_end: int) -> str:
    return _java_annotation_arguments_and_end(content, annotation_end)[0]


def _java_annotation_arguments_and_end(
    content: str,
    annotation_end: int,
) -> tuple[str, int]:
    opening = annotation_end
    while opening < len(content) and content[opening].isspace():
        opening += 1
    if opening >= len(content) or content[opening] != "(":
        return "", annotation_end
    closing = _matching_parenthesis(content, opening)
    return content[opening : closing + 1], closing + 1


def _java_routes(file: JavaSourceFileSnapshot) -> list[_JavaRoute]:
    masked_content = _mask_java_non_code(file.content)
    selected = _java_controller_declaration(file, masked_content)
    if selected is None:
        return []
    declaration, declaration_prefix_start = selected
    class_opening = masked_content.find("{", declaration.end())
    if class_opening < 0:
        return []
    class_end = _matching_brace(file.content, class_opening)
    route_masked_content = list(masked_content)
    route_masked_content[class_opening + 1 : class_end] = _mask_nested_java_blocks(
        masked_content[class_opening + 1 : class_end]
    )
    route_mask = "".join(route_masked_content)
    base_matches = _active_java_annotation_matches(
        file.content,
        masked_content,
        _REQUEST_MAPPING_MARKER,
        _REQUEST_MAPPING,
        start=declaration_prefix_start,
        end=declaration.start(),
    )
    base_paths = (
        _mapping_paths(_java_annotation_arguments(file.content, base_matches[-1].end()))
        if base_matches
        else [""]
    )
    controller = declaration.group("name")
    return [
        route
        for match in _active_java_annotation_matches(
            file.content,
            route_mask,
            _MAPPING_ANNOTATION_MARKER,
            _MAPPING_ANNOTATION,
            start=declaration.end(),
            end=class_end,
        )
        for route in _routes_after_mapping(
            file,
            match.start(),
            match,
            base_paths,
            controller,
        )
    ]


def _java_controller_declaration(
    file: JavaSourceFileSnapshot,
    masked_content: str,
) -> tuple[re.Match[str], int] | None:
    top_level_mask = _mask_nested_java_blocks(masked_content)
    declarations = list(_TYPE_DECLARATION.finditer(top_level_mask))
    candidates: list[tuple[re.Match[str], int]] = []
    declaration_prefix_start = 0
    for declaration in declarations:
        if declaration.group("kind") == "class":
            candidates.append((declaration, declaration_prefix_start))
        opening = masked_content.find("{", declaration.end())
        if opening >= 0:
            declaration_prefix_start = _matching_brace(file.content, opening) + 1
    if not candidates:
        return None
    file_stem = PurePosixPath(file.path).stem
    annotated = [
        candidate
        for candidate in candidates
        if _CONTROLLER_ANNOTATION.search(
            masked_content,
            candidate[1],
            candidate[0].start(),
        )
        is not None
    ]
    return next(
        (candidate for candidate in annotated if candidate[0].group("name") == file_stem),
        annotated[0]
        if annotated
        else next(
            (candidate for candidate in candidates if candidate[0].group("name") == file_stem),
            candidates[0],
        ),
    )


def _mask_java_non_code(content: str) -> str:
    masked = list(content)
    for match in _JAVA_NON_CODE.finditer(content):
        masked[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(masked)


def _mask_nested_java_blocks(content: str) -> str:
    masked = list(content)
    depth = 0
    for index, character in enumerate(content):
        if character == "{":
            depth += 1
            masked[index] = " "
        elif character == "}":
            depth = max(0, depth - 1)
            masked[index] = " "
        elif depth > 0:
            masked[index] = " "
    return "".join(masked)


def _active_java_annotation_matches(
    content: str,
    masked_content: str,
    marker: re.Pattern[str],
    annotation: re.Pattern[str],
    *,
    start: int = 0,
    end: int | None = None,
) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    end_position = len(masked_content) if end is None else end
    for marker_match in marker.finditer(masked_content, start, end_position):
        parsed = annotation.match(content, marker_match.start())
        if parsed is not None:
            matches.append(parsed)
    return matches


def _routes_after_mapping(
    file: JavaSourceFileSnapshot,
    mapping_start: int,
    mapping: re.Match[str],
    base_paths: list[str],
    controller: str,
) -> list[_JavaRoute]:
    mapping_arguments, mapping_end = _java_annotation_arguments_and_end(
        file.content,
        mapping.end(),
    )
    following = file.content[mapping_end : mapping_end + 2000]
    masked_following = _mask_java_annotation_arguments(_mask_java_non_code(following))
    signature = re.match(
        r"(?:\s*@[A-Za-z0-9_$.]+)*\s*public\s+"
        r"(?:(?:abstract|default|final|native|static|strictfp|synchronized)\s+)*"
        r"(?:<[^>{};]+>\s+)?"
        r"(?P<return>[A-Za-z0-9_$<>,.?\[\]\s]+?)\s+"
        r"(?P<handler>[A-Za-z_$][A-Za-z0-9_$]*)"
        r"\s*\((?P<params>[^)]*)\)\s*(?:throws\s+(?P<throws>[^{]+))?\{",
        masked_following,
    )
    if signature is None:
        return []
    paths = _mapping_paths(mapping_arguments)
    methods = _mapping_http_methods(mapping, mapping_arguments)
    body_start = mapping_end + signature.end() - 1
    body_end = _matching_brace(file.content, body_start)
    handler = signature.group("handler")
    return [
        _JavaRoute(
            method=method,
            path=full_path,
            operation_ref=f"operation://{method}{full_path}",
            controller_ref=f"java://{controller}",
            handler=handler,
            return_type=following[signature.start("return") : signature.end("return")],
            parameters=following[signature.start("params") : signature.end("params")],
            declared_exceptions=_declared_java_exceptions(
                following[signature.start("throws") : signature.end("throws")]
                if signature.group("throws") is not None
                else None
            ),
            body=file.content[body_start + 1 : body_end],
            source_line=file.content.count("\n", 0, mapping_start) + 1,
        )
        for method in methods
        for base_path in base_paths
        for path in paths
        if (full_path := _join_route_path(base_path, path))
    ]


def _mapping_http_methods(
    mapping: re.Match[str],
    arguments: str,
) -> list[Literal["GET", "POST", "PUT", "PATCH", "DELETE"]]:
    composed_method = mapping.group("method")
    if composed_method is not None:
        return [
            cast(
                Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
                composed_method.upper(),
            )
        ]
    content = (
        arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    )
    method_assignment = re.search(r"\bmethod\s*=", content)
    if method_assignment is None:
        methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    else:
        expression = _java_annotation_expression(
            content,
            method_assignment.end(),
            allow_identifier=True,
        )
        methods = re.findall(
            r"(?<![A-Za-z0-9_$])(?:RequestMethod\.)?(GET|POST|PUT|PATCH|DELETE)\b",
            expression,
        )
    return [
        cast(Literal["GET", "POST", "PUT", "PATCH", "DELETE"], method)
        for method in dict.fromkeys(methods)
    ]


def _declared_java_exceptions(clause: str | None) -> list[str]:
    if clause is None:
        return []
    return [
        name
        for item in clause.split(",")
        if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*", name := item.strip())
    ]


def _mapping_paths(arguments: str) -> list[str]:
    content = (
        arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    )
    named = re.search(r"\b(?:value|path)\s*=", content)
    expression = (
        _java_annotation_expression(content, named.end())
        if named is not None
        else _positional_mapping_expression(content)
    )
    paths = [match.group(1) for match in re.finditer(r'"((?:\\.|[^"\\])*)"', expression)]
    if paths:
        return list(dict.fromkeys(paths))
    if named is not None or expression:
        return []
    stripped = content.strip()
    if not stripped or re.match(r"[A-Za-z_$][A-Za-z0-9_$]*\s*=", stripped) is not None:
        return [""]
    return []


def _positional_mapping_expression(arguments: str) -> str:
    return _java_annotation_expression(arguments, 0)


def _java_annotation_expression(
    content: str,
    start: int,
    *,
    allow_identifier: bool = False,
) -> str:
    index = start
    while index < len(content) and content[index].isspace():
        index += 1
    if index >= len(content):
        return ""
    if content[index] == "{":
        closing = _matching_brace(content, index)
        return content[index : closing + 1] if closing < len(content) else ""
    string_expression = re.match(r'"(?:\\.|[^"\\])*"', content[index:])
    if string_expression is not None:
        return string_expression.group(0)
    if allow_identifier:
        identifier = re.match(r"[A-Za-z_$][A-Za-z0-9_$.]*", content[index:])
        return identifier.group(0) if identifier is not None else ""
    return ""


def _mask_java_annotation_arguments(content: str) -> str:
    masked = list(content)
    cursor = 0
    annotation = re.compile(r"@[A-Za-z_$][A-Za-z0-9_$.]*\s*")
    while match := annotation.search(content, cursor):
        opening = match.end()
        if opening >= len(content) or content[opening] != "(":
            cursor = match.end()
            continue
        closing = _matching_parenthesis(content, opening)
        masked[opening : closing + 1] = " " * (closing - opening + 1)
        cursor = closing + 1
    return "".join(masked)


def _matching_parenthesis(content: str, opening: int) -> int:
    depth = 0
    index = opening
    while index < len(content):
        non_code = _JAVA_NON_CODE.match(content, index)
        if non_code is not None:
            index = non_code.end()
            continue
        if content[index] == "(":
            depth += 1
        elif content[index] == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(content) - 1


def _join_route_path(base: str, path: str) -> str:
    segments = [segment.strip("/") for segment in (base, path) if segment.strip("/")]
    return "/" + "/".join(segments)


def _matching_brace(content: str, opening: int) -> int:
    depth = 0
    index = opening
    while index < len(content):
        non_code = _JAVA_NON_CODE.match(content, index)
        if non_code is not None:
            index = non_code.end()
            continue
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
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
    identifiers = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*", value)
    return identifiers[-1].rsplit(".", 1)[-1] if identifiers else value.rstrip("[]")


def _route_call_claims(source_path: str, route: _JavaRoute) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    for call in _SERVICE_CALL.finditer(_mask_java_non_code(route.body)):
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
    masked_body = _mask_java_non_code(route.body)
    names = sorted(
        set(
            [
                *route.declared_exceptions,
                *_THROWS.findall(masked_body),
                *_THROW_NEW.findall(masked_body),
            ]
        )
    )
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
    matches = _active_java_annotation_matches(
        route.body,
        _mask_java_non_code(route.body),
        _KAFKA_SEND_MARKER,
        _KAFKA_SEND,
    )
    produced: list[JavaEvidenceClaim] = [
        JavaKafkaEventClaim(
            id=_claim_id("kafka", route.operation_ref, "produce", match.group(1)),
            source_path=source_path,
            operation_ref=route.operation_ref,
            direction="produce",
            topic_ref=f"kafka://{match.group(1)}",
            event_type="UnknownEvent",
            confidence=0.7,
            deterministic=False,
        )
        for match in matches
    ]
    return produced


def _structural_java_claims(
    file: JavaSourceFileSnapshot,
    routes: list[_JavaRoute],
    type_fields: dict[str, list[tuple[str, str, list[tuple[str, str]]]]],
) -> tuple[list[JavaEvidenceClaim], bool]:
    claims: list[JavaEvidenceClaim] = []
    truncated = False
    masked_content = _mask_java_non_code(file.content)
    declarations = list(_TYPE_DECLARATION.finditer(masked_content))
    top_level_starts = {
        declaration.start()
        for declaration in _TYPE_DECLARATION.finditer(_mask_nested_java_blocks(masked_content))
    }
    for declaration in declarations:
        name = declaration.group("name")
        kind = declaration.group("kind")
        source_path = f"{file.path}:{file.content.count(chr(10), 0, declaration.start()) + 1}"
        if kind == "interface" and name.endswith(("Mapper", "Repository")):
            claims.append(
                JavaPersistenceClaim(
                    id=_claim_id("repository", source_path, name),
                    source_path=source_path,
                    repository_ref=_java_structural_ref("java", source_path, name),
                    confidence=1,
                    deterministic=True,
                )
            )
        if (
            declaration.start() in top_level_starts
            and kind in {"class", "record"}
            and _is_entity_type(file.path, name)
        ):
            table_name = _snake_case(name)
            operation_refs = [
                route.operation_ref
                for route in routes
                if _route_resource_token(route.path) == _normalized_name(table_name)
            ]
            claims.append(
                JavaEntityClaim(
                    id=_claim_id("entity", source_path, name),
                    source_path=source_path,
                    entity_ref=_java_structural_ref("entity", source_path, name),
                    class_name=name,
                    table_ref=f"table://{table_name}",
                    operation_refs=operation_refs,
                    confidence=0.65,
                    deterministic=False,
                )
            )
            claims.extend(
                JavaTableColumnClaim(
                    id=_claim_id("column", source_path, name, field_name),
                    source_path=source_path,
                    entity_ref=_java_structural_ref("entity", source_path, name),
                    table_ref=f"table://{table_name}",
                    field_name=field_name,
                    column_name=_snake_case(field_name),
                    confidence=0.65,
                    deterministic=False,
                )
                for field_name, _field_type, _annotations in type_fields.get(name, [])
            )
        if kind == "enum":
            values, values_truncated = _enum_values(_type_body(file.content, declaration.end()))
            truncated = truncated or values_truncated
            if values:
                claims.append(
                    JavaEnumStateClaim(
                        id=_claim_id("enum", source_path, name),
                        source_path=source_path,
                        enum_ref=_java_structural_ref("java", source_path, name),
                        values=values,
                        confidence=0.8,
                        deterministic=not values_truncated,
                    )
                )
    claims.extend(_listener_claims(file))
    return claims, truncated


def _is_entity_type(path: str, name: str) -> bool:
    lowered = path.lower()
    return "/domain/" in lowered or "/entity/" in lowered or name.endswith("Entity")


def _enum_values(body: str) -> tuple[list[str], bool]:
    header = _top_level_java_prefix(body, ";")
    values: list[str] = []
    for component in _split_top_level_java_components(header):
        masked = _mask_java_annotation_arguments(_mask_java_non_code(component))
        declaration = re.sub(r"@[A-Za-z_$][A-Za-z0-9_$.]*", " ", masked).lstrip()
        match = re.match(r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\b", declaration)
        if match is not None:
            values.append(match.group("name"))
    return values[:100], len(values) > 100


def _top_level_java_prefix(content: str, delimiter: str) -> str:
    depth = 0
    index = 0
    while index < len(content):
        non_code = _JAVA_NON_CODE.match(content, index)
        if non_code is not None:
            index = non_code.end()
            continue
        character = content[index]
        if character in "([{<":
            depth += 1
        elif character in ")]}>" and depth > 0:
            depth -= 1
        elif character == delimiter and depth == 0:
            return content[:index]
        index += 1
    return content


def _listener_claims(file: JavaSourceFileSnapshot) -> list[JavaEvidenceClaim]:
    matches = _active_java_annotation_matches(
        file.content,
        _mask_java_non_code(file.content),
        _KAFKA_LISTENER_MARKER,
        _KAFKA_LISTENER,
    )
    return [
        JavaKafkaEventClaim(
            id=_claim_id("kafka", file.path, "consume", topic),
            source_path=f"{file.path}:{file.content.count(chr(10), 0, match.start()) + 1}",
            direction="consume",
            topic_ref=f"kafka://{topic}",
            event_type="UnknownEvent",
            confidence=0.7,
            deterministic=False,
        )
        for match in matches
        for topic in _kafka_listener_topics(_java_annotation_arguments(file.content, match.end()))
    ]


def _kafka_listener_topics(arguments: str) -> list[str]:
    content = arguments[1:-1] if arguments.startswith("(") else arguments
    named = re.search(
        r'\btopics\s*=\s*(?P<value>\{[^}]*\}|"(?:\\.|[^"\\])*")',
        content,
        re.DOTALL,
    )
    expression = (
        named.group("value") if named is not None else _positional_mapping_expression(content)
    )
    topics = [match.group(1) for match in re.finditer(r'"((?:\\.|[^"\\])*)"', expression)]
    return list(dict.fromkeys(topics))


def _deduplicate_java_claims(claims: list[JavaEvidenceClaim]) -> list[JavaEvidenceClaim]:
    unique = {claim.id: claim for claim in claims}
    return [unique[key] for key in sorted(unique)]


def _bounded_java_claims(
    claims: list[JavaEvidenceClaim],
) -> tuple[list[JavaEvidenceClaim], bool]:
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
    unique = _deduplicate_java_claims(claims)
    for claim in unique:
        grouped[claim.kind].append(claim)
    bounded = [
        claim
        for kind in limits
        for claim in sorted(grouped[kind], key=lambda item: (item.source_path, item.id))[
            : limits[kind]
        ]
    ]
    truncated = len(bounded) < len(unique) or len(bounded) > MAX_ADAPTER_CLAIMS
    return bounded[:MAX_ADAPTER_CLAIMS], truncated


def _claim_id(*parts: str) -> str:
    key = "|".join(parts)
    digest = (
        sha256(key.encode()).hexdigest()[:24].translate(str.maketrans("0123456789", "ghijklmnop"))
    )
    return f"claim-{digest}"


def _java_structural_ref(scheme: Literal["java", "entity"], source_path: str, name: str) -> str:
    identity = _claim_id("java-structural-ref", source_path, name).removeprefix("claim-")[:16]
    return f"{scheme}://{name}/{identity}"


def _database_finding_id(kind: Literal["table", "column"], *identity: str) -> str:
    encoded = json.dumps([kind, *identity], ensure_ascii=False, separators=(",", ":"))
    digest = (
        sha256(encoded.encode())
        .hexdigest()[:24]
        .translate(str.maketrans("0123456789", "ghijklmnop"))
    )
    return f"database-{kind}-{digest}"


def _bounded_finding_id(identifier: str) -> str:
    if len(identifier) <= 160:
        return identifier
    digest = sha256(identifier.encode()).hexdigest()[:24]
    return f"{identifier[:135]}-{digest}"


def _snake_case(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()
