# Chinese product copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

"""Pure contracts and deterministic adapters for external code and database evidence."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal, cast
from urllib.parse import quote

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
    evidence_state_scalar_text,
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
_SPRING_WEB_ANNOTATION_PREFIX = r"(?:(?:org\.springframework\.web\.bind\.annotation)\.)?"
_SPRING_KAFKA_ANNOTATION_PREFIX = r"(?:(?:org\.springframework\.kafka\.annotation)\.)?"
_REQUEST_COLLECTION_TYPES: Final = (
    "Collection",
    "Deque",
    "Iterable",
    "List",
    "Queue",
    "SequencedCollection",
    "Set",
)
_RESPONSE_SINGLE_VALUE_CONTAINERS: Final = (
    *_REQUEST_COLLECTION_TYPES,
    "CompletableFuture",
    "CompletionStage",
    "Flux",
    "HttpEntity",
    "Mono",
    "Optional",
    "Page",
    "Publisher",
    "ResponseEntity",
    "Slice",
    "Stream",
)
_ROUTE_ACTION_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "add",
        "changestatus",
        "create",
        "delete",
        "download",
        "edit",
        "export",
        "import",
        "importdata",
        "importtemplate",
        "list",
        "query",
        "remove",
        "reset",
        "resetpwd",
        "save",
        "search",
        "update",
        "upload",
    }
)
_RESPONSE_MAP_CONTAINERS: Final = (
    "ConcurrentMap",
    "HashMap",
    "LinkedHashMap",
    "Map",
    "NavigableMap",
    "SortedMap",
)
_TRANSPORT_ONLY_PARAMETER_ANNOTATIONS: Final = (
    "AuthenticationPrincipal",
    "CookieValue",
    "CurrentSecurityContext",
    "MatrixVariable",
    "PathVariable",
    "RequestAttribute",
    "RequestHeader",
    "RequestParam",
    "SessionAttribute",
)
_TRANSPORT_ONLY_PARAMETER_TYPES: Final = (
    "Authentication",
    "BindingResult",
    "Errors",
    "HttpServletRequest",
    "HttpServletResponse",
    "InputStream",
    "Locale",
    "Model",
    "OutputStream",
    "Principal",
    "RedirectAttributes",
    "SessionStatus",
    "TimeZone",
    "WebRequest",
    "ZoneId",
)
_SPRING_STRING_CONSTANT_VALUES: Final = {
    "MediaType.ALL_VALUE": "*/*",
    "MediaType.APPLICATION_ATOM_XML_VALUE": "application/atom+xml",
    "MediaType.APPLICATION_CBOR_VALUE": "application/cbor",
    "MediaType.APPLICATION_FORM_URLENCODED_VALUE": "application/x-www-form-urlencoded",
    "MediaType.APPLICATION_GRAPHQL_RESPONSE_VALUE": "application/graphql-response+json",
    "MediaType.APPLICATION_JSON_VALUE": "application/json",
    "MediaType.APPLICATION_NDJSON_VALUE": "application/x-ndjson",
    "MediaType.APPLICATION_OCTET_STREAM_VALUE": "application/octet-stream",
    "MediaType.APPLICATION_PDF_VALUE": "application/pdf",
    "MediaType.APPLICATION_PROBLEM_JSON_VALUE": "application/problem+json",
    "MediaType.APPLICATION_PROBLEM_XML_VALUE": "application/problem+xml",
    "MediaType.APPLICATION_PROTOBUF_VALUE": "application/x-protobuf",
    "MediaType.APPLICATION_RSS_XML_VALUE": "application/rss+xml",
    "MediaType.APPLICATION_STREAM_JSON_VALUE": "application/stream+json",
    "MediaType.APPLICATION_XHTML_XML_VALUE": "application/xhtml+xml",
    "MediaType.APPLICATION_XML_VALUE": "application/xml",
    "MediaType.IMAGE_GIF_VALUE": "image/gif",
    "MediaType.IMAGE_JPEG_VALUE": "image/jpeg",
    "MediaType.IMAGE_PNG_VALUE": "image/png",
    "MediaType.MULTIPART_FORM_DATA_VALUE": "multipart/form-data",
    "MediaType.MULTIPART_MIXED_VALUE": "multipart/mixed",
    "MediaType.TEXT_EVENT_STREAM_VALUE": "text/event-stream",
    "MediaType.TEXT_HTML_VALUE": "text/html",
    "MediaType.TEXT_MARKDOWN_VALUE": "text/markdown",
    "MediaType.TEXT_PLAIN_VALUE": "text/plain",
    "MediaType.TEXT_XML_VALUE": "text/xml",
}
_MAPPING_ANNOTATION = re.compile(
    rf"@{_SPRING_WEB_ANNOTATION_PREFIX}"
    r"(?:(?P<method>Get|Post|Put|Patch|Delete)Mapping|RequestMapping)\b"
)
_MAPPING_ANNOTATION_MARKER = re.compile(
    rf"@{_SPRING_WEB_ANNOTATION_PREFIX}(?:Get|Post|Put|Patch|Delete|Request)Mapping\b"
)
_REQUEST_MAPPING = re.compile(rf"@{_SPRING_WEB_ANNOTATION_PREFIX}RequestMapping\b")
_REQUEST_MAPPING_MARKER = re.compile(rf"@{_SPRING_WEB_ANNOTATION_PREFIX}RequestMapping\b")
_CONTROLLER_ANNOTATION = re.compile(
    r"@(?:(?:org\.springframework\.web\.bind\.annotation\.)?RestController|"
    r"(?:org\.springframework\.stereotype\.)?Controller)\b"
)
_JPA_ENTITY_ANNOTATION = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Entity\b")
_JPA_ENTITY_ANNOTATION_MARKER = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Entity\b")
_JPA_TABLE_ANNOTATION = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Table\b")
_JPA_TABLE_ANNOTATION_MARKER = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Table\b")
_JPA_COLUMN_ANNOTATION = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Column\b")
_JPA_COLUMN_ANNOTATION_MARKER = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Column\b")
_JPA_TRANSIENT_ANNOTATION = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Transient\b")
_JPA_TRANSIENT_ANNOTATION_MARKER = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Transient\b")
_JPA_ACCESS_ANNOTATION = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Access\b")
_JPA_ACCESS_ANNOTATION_MARKER = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Access\b")
_JPA_ID_ANNOTATION = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Id\b")
_JPA_ID_ANNOTATION_MARKER = re.compile(r"@(?:(?:jakarta|javax)\.persistence\.)?Id\b")
_JACKSON_IGNORE_ANNOTATION = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.annotation\.)?JsonIgnore)\b"
)
_JACKSON_IGNORE_ANNOTATION_MARKER = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.annotation\.)?JsonIgnore)\b"
)
_JACKSON_PROPERTY_ANNOTATION = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.annotation\.)?JsonProperty)\b"
)
_JACKSON_PROPERTY_ANNOTATION_MARKER = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.annotation\.)?JsonProperty)\b"
)
_JACKSON_NAMING_ANNOTATION = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.databind\.annotation\.)?JsonNaming)\b"
)
_JACKSON_NAMING_ANNOTATION_MARKER = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.databind\.annotation\.)?JsonNaming)\b"
)
_JACKSON_VALUE_ANNOTATION = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.annotation\.)?JsonValue)\b"
)
_JACKSON_VALUE_ANNOTATION_MARKER = re.compile(
    r"@(?:(?:com\.fasterxml\.jackson\.annotation\.)?JsonValue)\b"
)
_TYPE_DECLARATION = re.compile(
    r"\b(?P<kind>class|record|enum|interface)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
)
_FIELD_DECLARATION = re.compile(
    r"\b(?P<modifiers>(?:(?:public|protected|private|static|final|transient)\s+)*)"
    r"(?P<type>[A-Za-z0-9_$<>,.?\[\] \t]+?)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:\s*=\s*[^;]{0,1000})?\s*;"
)
_JAVA_STRING_CONSTANT_DECLARATION = re.compile(
    r"\b(?P<modifiers>(?:(?:public|protected|private|static|final)\s+)*)"
    r"(?:java\.lang\.)?String\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*="
    r"(?P<expression>[^;]+);"
)
_VALIDATION_CONSTRAINT_ANNOTATION_NAMES = (
    r"AssertFalse|AssertTrue|DecimalMax|DecimalMin|Digits|Email|Future|FutureOrPresent|"
    r"Max|Min|Negative|NegativeOrZero|NotBlank|NotEmpty|NotNull|Null|Past|PastOrPresent|"
    r"Pattern|Positive|PositiveOrZero|Size"
)
_VALIDATION_ANNOTATION_SOURCE = (
    rf"(?:(?:(?:jakarta|javax)\.validation\.constraints\.)?"
    rf"(?:{_VALIDATION_CONSTRAINT_ANNOTATION_NAMES})|"
    r"(?:(?:jakarta|javax)\.validation\.)?Valid)"
)
_VALIDATION_ANNOTATION = re.compile(rf"@{_VALIDATION_ANNOTATION_SOURCE}\b")
_VALIDATION_ANNOTATION_MARKER = re.compile(rf"@{_VALIDATION_ANNOTATION_SOURCE}\b")
_VALIDATED_GETTER = re.compile(
    rf"(?P<annotations>(?:\s*@{_VALIDATION_ANNOTATION_SOURCE}\b[^\n]*(?:\r?\n|$))+)"
    r"\s*public\s+[A-Za-z0-9_$<>,.?\[\]]+\s+get(?P<name>[A-Z][A-Za-z0-9_$]*)\s*\("
)
_SERVICE_CALL = re.compile(
    r"\b(?P<target>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\.(?P<method>[A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
_THROWS = re.compile(r"\bthrows\s+([A-Za-z_$][A-Za-z0-9_$.]*)")
_THROW_NEW = re.compile(r"\bthrow\s+new\s+([A-Za-z_$][A-Za-z0-9_$.]*)")
_KAFKA_SEND = re.compile(
    r'\b(?P<target>[A-Za-z_$][A-Za-z0-9_$]*)\.send\s*\(\s*"'
    r'(?P<topic>(?:\\.|[^"\\])*)"\s*(?=[,)])'
)
_KAFKA_TEMPLATE_DECLARATION = re.compile(
    r"\b(?:(?:org\.springframework\.kafka\.core\.)?KafkaTemplate)\s*"
    r"(?:<[^;(){}=]+>)?\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\b"
)
_KAFKA_LISTENER = re.compile(rf"@{_SPRING_KAFKA_ANNOTATION_PREFIX}KafkaListener\b")
_KAFKA_LISTENER_MARKER = re.compile(rf"@{_SPRING_KAFKA_ANNOTATION_PREFIX}KafkaListener\b")
_JAVA_STRING_LITERAL = r'"(?:\\.|[^"\\])*"'
_JAVA_NON_CODE = re.compile(
    r"//[^\r\n]*(?:\r?\n|$)"
    r"|/\*.*?(?:\*/|$)"
    r'|"""(?:(?!""").)*(?:"""|$)'
    r'|"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'",
    re.DOTALL,
)
_JAVA_METHOD_SIGNATURE = re.compile(
    r"(?:\s*@[A-Za-z0-9_$.]+)*(?!\s*private\b)\s*"
    r"(?P<modifiers>"
    r"(?:(?:public|protected|abstract|default|final|native|static|strictfp|synchronized)"
    r"\s+|@[A-Za-z0-9_$.]+\s*)*)"
    r"(?:<[^>{};]+>\s+)?"
    r"(?P<return>[A-Za-z0-9_$<>,.?\[\]\s]+?)\s+"
    r"(?P<handler>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\s*\((?P<params>[^)]*)\)\s*(?:throws\s+(?P<throws>[^;{]+))?"
    r"(?P<terminator>[;{])"
)

type JavaHttpMethod = Literal[
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "TRACE",
]
_SPRING_HTTP_METHODS: Final[tuple[JavaHttpMethod, ...]] = (
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "TRACE",
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
    method: JavaHttpMethod
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
    field_name: str = Field(min_length=1, max_length=160)
    java_field_name: str | None = Field(default=None, pattern=_IDENTIFIER)
    field_type: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_field_type(self) -> JavaDtoFieldClaim:
        require_no_sensitive_scalar_values(
            [
                self.dto_type,
                self.field_name,
                *([self.java_field_name] if self.java_field_name is not None else []),
                self.field_type,
            ]
        )
        return self


class JavaBeanValidationClaim(JavaClaimBase):
    kind: Literal["bean_validation"] = "bean_validation"
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512, pattern=_REF)
    dto_type: str = Field(pattern=_IDENTIFIER)
    field_name: str = Field(min_length=1, max_length=160)
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
    direction: Literal["request", "response"] | None = None
    dto_type: str | None = Field(default=None, pattern=_IDENTIFIER)
    field_name: str | None = Field(default=None, min_length=1, max_length=160)
    java_field_name: str | None = Field(default=None, pattern=_IDENTIFIER)
    values: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_state_values(self) -> JavaEnumStateClaim:
        if (self.direction is None) != (self.dto_type is None):
            raise ValueError("enum state DTO direction and type must be provided together")
        if self.direction is not None and self.field_name is None:
            raise ValueError("route-scoped enum state must identify its DTO field")
        require_no_sensitive_scalar_values(
            [
                *([self.dto_type] if self.dto_type is not None else []),
                *([self.field_name] if self.field_name is not None else []),
                *([self.java_field_name] if self.java_field_name is not None else []),
                *self.values,
            ]
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
        if self.row_count == 0 and (
            self.enum_candidates or self.minimum is not None or self.maximum is not None
        ):
            raise ValueError("database empty distribution must not include observed values")
        if self.null_ratio == 1 and (
            (self.distinct_count or 0) > 0
            or self.enum_candidates
            or self.minimum is not None
            or self.maximum is not None
        ):
            raise ValueError("database all-null distribution must not include observed values")
        if (
            self.row_count is not None
            and self.null_ratio is not None
            and self.distinct_count is not None
            and Decimal(self.distinct_count)
            > (
                Decimal(self.row_count) * (Decimal(1) - Decimal(str(self.null_ratio)))
            ).to_integral_value(rounding=ROUND_CEILING)
        ):
            raise ValueError("database distinct count must not exceed non-null row count")
        self._validate_zero_distinct_distribution()
        if (
            self.distinct_count is not None
            and len({evidence_state_scalar_text(value) for value in self.enum_candidates})
            > self.distinct_count
        ):
            raise ValueError("database observed candidates must not exceed distinct count")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("database observed minimum must not exceed maximum")
        if (
            self.distinct_count == 1
            and self.minimum is not None
            and self.maximum is not None
            and self.minimum != self.maximum
        ):
            raise ValueError("database observed singleton extrema must be equal")
        numeric_candidates = [
            value
            for value in self.enum_candidates
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        numeric_candidate_values = set(numeric_candidates)
        self._validate_singleton_candidate_extrema(numeric_candidate_values)
        if (
            self.minimum is not None
            and any(candidate < self.minimum for candidate in numeric_candidates)
        ) or (
            self.maximum is not None
            and any(candidate > self.maximum for candidate in numeric_candidates)
        ):
            raise ValueError("database numeric candidates must fall within observed extrema")
        extrema = [value for value in (self.minimum, self.maximum) if value is not None]
        require_no_sensitive_scalar_values([*extrema, *self.enum_candidates])
        return self

    def _validate_singleton_candidate_extrema(
        self, numeric_candidate_values: set[int | float]
    ) -> None:
        if self.distinct_count != 1 or len(numeric_candidate_values) != 1:
            return
        singleton_candidate = next(iter(numeric_candidate_values))
        if (self.minimum is not None and singleton_candidate != self.minimum) or (
            self.maximum is not None and singleton_candidate != self.maximum
        ):
            raise ValueError("database observed singleton candidate must equal observed extrema")

    def _validate_zero_distinct_distribution(self) -> None:
        if self.distinct_count != 0:
            return
        if (
            self.row_count is not None
            and self.null_ratio is not None
            and Decimal(self.row_count) * (Decimal(1) - Decimal(str(self.null_ratio))) > 0
        ):
            raise ValueError("database non-null rows require a positive distinct count")
        if self.enum_candidates or self.minimum is not None or self.maximum is not None:
            raise ValueError("database zero-distinct distribution must not include observed values")


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
        if self.primary_key and self.nullable:
            raise ValueError("database primary key must not be nullable")
        if (
            not self.nullable
            and self.observed_distribution is not None
            and self.observed_distribution.null_ratio is not None
            and self.observed_distribution.null_ratio > 0
        ):
            raise ValueError("database non-nullable column must not have observed nulls")
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
        string_constants = _java_string_constants(snapshot.files)
        type_analysis = _java_type_analysis(snapshot.files, string_constants)
        interface_contracts = _java_interface_route_contracts(snapshot.files, string_constants)
        unresolved_mappings = _java_unresolved_mapping_locations(
            snapshot.files,
            string_constants,
        )
        unresolved_mapping_conditions = _java_unresolved_mapping_condition_locations(
            snapshot.files,
            string_constants,
        )
        unresolved_kafka_topics = _java_unresolved_kafka_locations(
            snapshot.files,
            string_constants,
        )
        claims: list[JavaEvidenceClaim] = []
        structural_truncated = False
        unresolved_jpa_tables: set[str] = set()
        for file in sorted(snapshot.files, key=lambda item: item.path):
            file_routes = _java_routes(file, interface_contracts.routes, string_constants)
            claims.extend(_route_claims(file, file_routes, type_analysis))
            structural_claims, file_truncated, file_unresolved_tables = _structural_java_claims(
                file,
                file_routes,
                type_analysis.fields,
                type_analysis.property_access_types,
                string_constants,
            )
            claims.extend(structural_claims)
            structural_truncated = structural_truncated or file_truncated
            unresolved_jpa_tables.update(file_unresolved_tables)
        bounded_claims, claim_truncated = _bounded_java_claims(claims)
        truncated = structural_truncated or claim_truncated
        warnings = [
            ExternalEvidenceWarning(
                code="JAVA_POC_STATIC_ONLY",
                message="Java/Spring POC 仅执行静态文本分析，未编译或执行目标代码。",
            )
        ]
        if type_analysis.ambiguous_types:
            warnings.append(
                ExternalEvidenceWarning(
                    code="JAVA_POC_INCOMPLETE_AMBIGUOUS_TYPE",
                    message=(
                        "Java/Spring POC 发现同名类型，无法安全绑定字段，分析不完整："
                        f"{_java_type_name_summary(type_analysis.ambiguous_types)}。"
                    ),
                )
            )
        if type_analysis.inherited_types:
            warnings.append(
                ExternalEvidenceWarning(
                    code="JAVA_POC_INCOMPLETE_INHERITANCE",
                    message=(
                        "Java/Spring POC 不展开继承字段或控制器父类路由，"
                        "以下类型的分析不完整："
                        f"{_java_type_name_summary(type_analysis.inherited_types)}。"
                    ),
                )
            )
        if type_analysis.property_access_types:
            warnings.append(
                ExternalEvidenceWarning(
                    code="JAVA_POC_INCOMPLETE_PROPERTY_ACCESS",
                    message=(
                        "Java/Spring POC 不解析 JPA 属性访问映射，以下实体的列分析不完整："
                        f"{_java_type_name_summary(type_analysis.property_access_types)}。"
                    ),
                )
            )
        if type_analysis.unresolved_enum_serialization_types:
            warnings.append(
                ExternalEvidenceWarning(
                    code="JAVA_POC_INCOMPLETE_ENUM_SERIALIZATION",
                    message=(
                        "Java/Spring POC 无法静态解析 @JsonValue 枚举序列化，"
                        "已停止生成对应状态候选："
                        f"{_java_type_name_summary(type_analysis.unresolved_enum_serialization_types)}。"
                    ),
                )
            )
        if type_analysis.unresolved_json_naming_types:
            warnings.append(
                ExternalEvidenceWarning(
                    code="JAVA_POC_INCOMPLETE_JSON_NAMING",
                    message=(
                        "Java/Spring POC 无法静态解析部分 @JsonNaming 策略，"
                        "已停止生成对应 DTO 字段证据："
                        f"{_java_type_name_summary(type_analysis.unresolved_json_naming_types)}。"
                    ),
                )
            )
        if type_analysis.unresolved_json_property_types:
            warnings.append(
                ExternalEvidenceWarning(
                    code="JAVA_POC_INCOMPLETE_JSON_PROPERTY",
                    message=(
                        "Java/Spring POC 无法静态解析部分 @JsonProperty 字段名，"
                        "已停止生成对应 DTO 字段证据："
                        f"{_java_type_name_summary(type_analysis.unresolved_json_property_types)}。"
                    ),
                )
            )
        warnings.extend(
            _java_reference_warnings(
                interface_contracts.unresolved_interfaces,
                unresolved_mappings,
                unresolved_mapping_conditions,
                unresolved_kafka_topics,
                tuple(sorted(unresolved_jpa_tables)),
                type_analysis.unresolved_column_types,
            )
        )
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
            deterministic=(
                all(claim.deterministic for claim in bounded_claims)
                and not truncated
                and not type_analysis.ambiguous_types
                and not type_analysis.inherited_types
                and not type_analysis.property_access_types
                and not interface_contracts.unresolved_interfaces
                and not unresolved_mappings
                and not unresolved_mapping_conditions
                and not unresolved_kafka_topics
                and not unresolved_jpa_tables
                and not type_analysis.unresolved_column_types
                and not type_analysis.unresolved_enum_serialization_types
                and not type_analysis.unresolved_json_naming_types
                and not type_analysis.unresolved_json_property_types
            ),
            warnings=warnings,
        )


def _java_reference_warnings(
    unresolved_interfaces: tuple[str, ...],
    unresolved_mappings: tuple[str, ...],
    unresolved_mapping_conditions: tuple[str, ...],
    unresolved_kafka_topics: tuple[str, ...],
    unresolved_jpa_tables: tuple[str, ...],
    unresolved_jpa_columns: tuple[str, ...],
) -> list[ExternalEvidenceWarning]:
    warnings: list[ExternalEvidenceWarning] = []
    definitions = (
        (
            unresolved_interfaces,
            "JAVA_POC_INCOMPLETE_INTERFACE_HIERARCHY",
            "Java/Spring POC 无法安全解析部分接口继承关系，分析不完整：",
        ),
        (
            unresolved_mappings,
            "JAVA_POC_INCOMPLETE_MAPPING_PATH",
            "Java/Spring POC 无法解析部分 Mapping 路径常量或表达式，分析不完整：",
        ),
        (
            unresolved_mapping_conditions,
            "JAVA_POC_INCOMPLETE_MAPPING_CONDITION",
            "Java/Spring POC 无法解析部分 Mapping 条件常量或表达式，分析不完整：",
        ),
        (
            unresolved_kafka_topics,
            "JAVA_POC_INCOMPLETE_KAFKA_TOPIC",
            "Java/Spring POC 无法解析部分 Kafka Topic 常量、占位符或表达式，分析不完整：",
        ),
        (
            unresolved_jpa_tables,
            "JAVA_POC_INCOMPLETE_JPA_TABLE",
            "Java/Spring POC 无法解析部分 JPA Table 名称，已停止推断对应表绑定：",
        ),
        (
            unresolved_jpa_columns,
            "JAVA_POC_INCOMPLETE_JPA_COLUMN",
            "Java/Spring POC 无法解析部分 JPA Column 名称，已停止推断对应列绑定：",
        ),
    )
    for references, code, prefix in definitions:
        if references:
            warnings.append(
                ExternalEvidenceWarning(
                    code=code,
                    message=f"{prefix}{_java_type_name_summary(references)}。",
                )
            )
    return warnings


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
        require_no_sensitive_scalar_values([finding.kind, finding.path, *finding.warnings])
    source = ExternalEvidenceSource(ref=source_ref, revision=source_revision)
    provider_type = _bundle_provider_type(bundle)
    findings = [
        _external_finding(
            identifier=f"bundle-{finding.id}",
            kind=_bundle_finding_kind(finding.kind),
            semantic_role=_bundle_semantic_role(finding),
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
    retained_findings = [
        finding for finding in envelope.findings if not _is_mapping_conflict_finding(finding)
    ]
    retained_envelope = envelope.model_copy(update={"findings": retained_findings})
    retained_evidence = [
        item for item in evidence if not _is_mapping_conflict_finding(item.finding)
    ]
    provisional = [*retained_evidence, *_envelope_mapping_inputs(retained_envelope)]
    conflicts = derive_entity_mapping(provisional).conflicts
    if not conflicts:
        return retained_envelope
    available = max(0, 100 - len(retained_findings))
    if len(conflicts) > available:
        raise EntityMappingBudgetExceeded(
            "entity mapping conflict findings exceed envelope capacity"
        )
    addition_ids = [
        _claim_id("mapping-conflict", conflict.kind.value, conflict.source_ref)
        for conflict in conflicts
    ]
    existing_ids = {finding.id for finding in retained_findings}
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
    payload = retained_envelope.model_dump(mode="json")
    payload["findings"] = [
        item.model_dump(mode="json") for item in [*retained_findings, *additions]
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


def _is_mapping_conflict_finding(finding: ExternalEvidenceFinding) -> bool:
    return isinstance(finding.structured_data, EntityMappingExternalEvidenceStructuredData)


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
        EvidenceSourceType.SOURCE: EvidenceProviderType.REPOSITORY,
        EvidenceSourceType.DATA_PROFILE: EvidenceProviderType.DATA_PROFILE,
        EvidenceSourceType.SERVICE_TOPOLOGY: EvidenceProviderType.SERVICE_TOPOLOGY,
        EvidenceSourceType.EXISTING_TEST: EvidenceProviderType.EXISTING_TEST,
        EvidenceSourceType.WORKFLOW: EvidenceProviderType.WORKFLOW,
        EvidenceSourceType.RUNTIME: EvidenceProviderType.RUNTIME,
        EvidenceSourceType.CHANGE: EvidenceProviderType.CHANGE,
        EvidenceSourceType.USER_CONFIRMED_RULE: EvidenceProviderType.USER_CONFIRMED_RULE,
    }[source_type]


def _bundle_finding_kind(kind: str) -> EvidenceFindingKind:
    if kind == "route":
        return EvidenceFindingKind.OPERATION
    if "constraint" in kind or kind == "column_profile":
        return EvidenceFindingKind.CONSTRAINT
    if kind in {"enum", "error_branch"}:
        return EvidenceFindingKind.BEHAVIOR
    return EvidenceFindingKind.KNOWLEDGE


def _bundle_semantic_role(finding: EvidenceFinding) -> EvidenceSemanticRole:
    return EvidenceSemanticRole(finding.as_ref().semantic_role)


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
class _JavaStateCandidate:
    mapping: EntityMappingCandidate
    field_name: str | None
    java_field_name: str | None


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
            field_identity = _bounded_reference_identity(field.field_name)
            field_ref = f"field://{field.dto_type}/{field_identity}?operation={operation_identity}"
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
    java_field_name = field.java_field_name or field.field_name
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
        if item[0].field_name.casefold() == java_field_name.casefold()
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
                parsed.table_columns,
            )
            if not column_candidates:
                continue
            corroborated_java_ids.update(corroborated_ids)
            for candidate in column_candidates:
                _append_mapping_candidate(candidates, candidate)
    for java_candidate in java_candidates:
        if java_candidate.mapping.id not in corroborated_java_ids:
            _append_mapping_candidate(candidates, java_candidate.mapping)
    return list(candidates.values())


def _java_state_candidates(
    states: list[tuple[JavaEnumStateClaim, str]],
) -> list[_JavaStateCandidate]:
    return [
        _JavaStateCandidate(
            mapping=_candidate(
                kind=EntityMappingCandidateKind.OPERATION_STATE,
                source_ref=_state_field_ref(
                    state.operation_ref,
                    state.field_name,
                    direction=state.direction,
                    dto_type=state.dto_type,
                ),
                target_ref=f"state-set://{state.enum_ref.removeprefix('java://')}",
                operation_ref=state.operation_ref,
                field_ref=(
                    _state_field_ref(
                        state.operation_ref,
                        state.field_name,
                        direction=state.direction,
                        dto_type=state.dto_type,
                    )
                    if state.field_name is not None
                    else None
                ),
                state_values=state.values,
                confidence=state.confidence,
                deterministic=state.deterministic,
                evidence_refs=[evidence_ref],
            ),
            field_name=state.field_name,
            java_field_name=state.java_field_name,
        )
        for state, evidence_ref in states
        if state.operation_ref is not None
    ]


def _database_state_candidates(
    operation_ref: str,
    operation_table: EntityMappingCandidate,
    parsed_column: _ParsedDatabaseColumn,
    java_candidates: list[_JavaStateCandidate],
    table_columns: list[tuple[JavaTableColumnClaim, str]],
) -> tuple[list[EntityMappingCandidate], set[str]]:
    column = parsed_column.claim
    value_sets = _database_state_value_sets(column)
    field_candidates = [
        candidate
        for candidate in java_candidates
        if _state_candidate_matches_column(
            candidate,
            operation_ref,
            parsed_column,
            table_columns,
        )
    ]
    if not value_sets or (
        not field_candidates and _normalized_name(column.name) not in {"status", "state"}
    ):
        return [], set()
    candidates: list[EntityMappingCandidate] = []
    corroborated_ids: set[str] = set()
    for values in value_sets:
        corroborating = [
            candidate for candidate in field_candidates if candidate.mapping.state_values == values
        ]
        corroborated_ids.update(candidate.mapping.id for candidate in corroborating)
        anchors: list[_JavaStateCandidate | None] = [*corroborating] or [None]
        for anchor in anchors:
            anchor_mapping = anchor.mapping if anchor is not None else None
            table_column_links = (
                _state_table_column_links(anchor, parsed_column, table_columns)
                if anchor is not None
                else []
            )
            source_ref = (
                anchor_mapping.source_ref
                if anchor_mapping is not None
                else _state_field_ref(operation_ref, column.name)
            )
            field_ref = anchor_mapping.field_ref if anchor_mapping is not None else source_ref
            corroborating_evidence = (
                sorted(
                    {
                        *anchor_mapping.evidence_refs,
                        *(evidence_ref for _claim, evidence_ref in table_column_links),
                    }
                )[:6]
                if anchor_mapping is not None
                else []
            )
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
                            *([anchor_mapping.confidence] if anchor_mapping is not None else []),
                            *(claim.confidence for claim, _ref in table_column_links),
                        ]
                    ),
                    deterministic=(
                        parsed_column.deterministic
                        and operation_table.deterministic
                        and (anchor_mapping is None or anchor_mapping.deterministic)
                        and all(claim.deterministic for claim, _ref in table_column_links)
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
    candidate: _JavaStateCandidate,
    operation_ref: str,
    parsed_column: _ParsedDatabaseColumn,
    table_columns: list[tuple[JavaTableColumnClaim, str]],
) -> bool:
    if candidate.mapping.operation_ref != operation_ref:
        return False
    explicit_links = _state_table_column_links_for_table(
        candidate,
        parsed_column,
        table_columns,
    )
    if explicit_links:
        return any(
            claim.column_name.casefold() == parsed_column.claim.name.casefold()
            for claim, _evidence_ref in explicit_links
        )
    column_name = parsed_column.claim.name
    if candidate.field_name is None:
        return _normalized_name(column_name) in {"status", "state"}
    return _normalized_name(candidate.field_name) == _normalized_name(column_name)


def _state_table_column_links(
    candidate: _JavaStateCandidate,
    parsed_column: _ParsedDatabaseColumn,
    table_columns: list[tuple[JavaTableColumnClaim, str]],
) -> list[tuple[JavaTableColumnClaim, str]]:
    return [
        item
        for item in _state_table_column_links_for_table(
            candidate,
            parsed_column,
            table_columns,
        )
        if item[0].column_name.casefold() == parsed_column.claim.name.casefold()
    ]


def _state_table_column_links_for_table(
    candidate: _JavaStateCandidate,
    parsed_column: _ParsedDatabaseColumn,
    table_columns: list[tuple[JavaTableColumnClaim, str]],
) -> list[tuple[JavaTableColumnClaim, str]]:
    if candidate.java_field_name is None:
        return []
    return [
        item
        for item in table_columns
        if (
            (claim := item[0]).field_name.casefold() == candidate.java_field_name.casefold()
            and _table_ref_matches_database_table(
                claim.table_ref,
                parsed_column.schema,
                parsed_column.table,
            )
        )
    ]


def _state_field_ref(
    operation_ref: str,
    field_name: str | None,
    *,
    direction: Literal["request", "response"] | None = None,
    dto_type: str | None = None,
) -> str:
    if field_name is None:
        return operation_ref
    operation_identity = sha256(operation_ref.encode()).hexdigest()
    field_identity = _state_field_identity(field_name)
    if direction is not None and dto_type is not None:
        dto_identity = sha256(dto_type.encode()).hexdigest()[:24]
        return f"state-field://{operation_identity}/{direction}/{dto_identity}/{field_identity}"
    return f"state-field://{operation_identity}/{field_identity}"


def _state_field_identity(field_name: str) -> str:
    return _bounded_reference_identity(field_name)


def _bounded_reference_identity(value: str) -> str:
    encoded = quote(value, safe="")
    if len(encoded) <= 120:
        return encoded
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def _database_state_value_sets(column: DatabaseColumnEvidence) -> list[list[str]]:
    declared = sorted({evidence_state_scalar_text(value) for value in column.enum_values})
    observed = (
        sorted(
            {
                evidence_state_scalar_text(value)
                for value in column.observed_distribution.enum_candidates
            }
        )
        if column.observed_distribution is not None
        else []
    )
    result: list[list[str]] = []
    for values in (declared, observed):
        if values and values not in result:
            result.append(values)
    return result


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
    if not segments:
        return ""
    resource_index = (
        -2 if len(segments) > 1 and _normalized_name(segments[-1]) in _ROUTE_ACTION_SUFFIXES else -1
    )
    return _normalized_name(segments[resource_index])


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
    method: JavaHttpMethod
    path: str
    operation_ref: str
    controller_ref: str
    handler: str
    return_type: str
    parameters: str
    declared_exceptions: list[str]
    conditions: tuple[str, ...] = ()
    call_target_types: dict[str, str] = Field(default_factory=dict)
    body: str
    source_line: int


@dataclass(frozen=True, slots=True)
class _JavaMethodImplementation:
    return_type: str
    parameters: str
    declared_exceptions: tuple[str, ...]
    body: str
    source_line: int


@dataclass(frozen=True)
class _JavaParameter:
    declared_type: str
    name: str
    annotations: frozenset[str]


@dataclass(frozen=True)
class _JavaInterfaceDefinition:
    routes: tuple[_JavaRoute, ...]
    parents: tuple[str, ...]
    base_paths: tuple[str, ...]
    base_methods: tuple[JavaHttpMethod, ...] | None
    base_conditions: tuple[str, ...] | None


@dataclass(frozen=True)
class _JavaInterfaceContracts:
    routes: dict[str, tuple[_JavaRoute, ...]]
    unresolved_interfaces: tuple[str, ...]


@dataclass(frozen=True)
class _JavaStringConstants:
    qualified_values: dict[str, str]
    simple_values: dict[str, str]
    local_values: dict[str, dict[str, str]]

    def resolve(self, reference: str, enclosing_type: str) -> str | None:
        if "." not in reference:
            local = self.local_values.get(enclosing_type, {}).get(reference)
            return local if local is not None else self.simple_values.get(reference)
        direct = self.qualified_values.get(reference)
        if direct is not None:
            return direct
        shortened = ".".join(reference.rsplit(".", 2)[-2:])
        qualified = self.qualified_values.get(shortened)
        if qualified is not None:
            return qualified
        return _SPRING_STRING_CONSTANT_VALUES.get(shortened)


JavaJsonAccess = Literal["auto", "read_only", "write_only", "read_write"]
JavaField = tuple[
    str,
    str,
    list[tuple[str, str]],
    str | None,
    bool,
    JavaJsonAccess,
    str | None,
    bool,
]


@dataclass(frozen=True)
class _JavaEnumDefinition:
    source_path: str
    enum_ref: str
    values: tuple[str, ...]
    deterministic: bool


@dataclass(frozen=True)
class _JavaTypeAnalysis:
    fields: dict[str, list[JavaField]]
    enums: dict[str, _JavaEnumDefinition]
    ambiguous_types: tuple[str, ...]
    inherited_types: tuple[str, ...]
    property_access_types: tuple[str, ...]
    unresolved_column_types: tuple[str, ...]
    unresolved_enum_serialization_types: tuple[str, ...]
    unresolved_json_naming_types: tuple[str, ...]
    unresolved_json_property_types: tuple[str, ...]


def _java_type_analysis(
    files: list[JavaSourceFileSnapshot],
    string_constants: _JavaStringConstants,
) -> _JavaTypeAnalysis:
    definitions: dict[
        str,
        list[list[JavaField]],
    ] = defaultdict(list)
    enum_definitions: dict[str, list[_JavaEnumDefinition]] = defaultdict(list)
    inherited_types: set[str] = set()
    property_access_types: set[str] = set()
    unresolved_column_types: set[str] = set()
    unresolved_enum_serialization_types: set[str] = set()
    unresolved_json_naming_types: set[str] = set()
    unresolved_json_property_types: set[str] = set()
    for file in files:
        masked_content = _mask_java_non_code(file.content)
        top_level_prefixes = _top_level_declaration_prefixes(file.content, masked_content)
        for declaration in _TYPE_DECLARATION.finditer(masked_content):
            name = declaration.group("name")
            body = _type_body(file.content, declaration.end())
            fields = (
                _record_fields(file.content, declaration, string_constants)
                if declaration.group("kind") == "record"
                else _class_fields(body, string_constants, name)
            )
            fields, unresolved_naming_types = _java_fields_with_json_naming(
                file.content,
                masked_content,
                declaration,
                top_level_prefixes,
                fields,
                name,
            )
            unresolved_json_naming_types.update(unresolved_naming_types)
            if any(field[7] for field in fields):
                unresolved_json_property_types.add(name)
            definitions[name].append(fields)
            if any(field[4] for field in fields):
                unresolved_column_types.add(name)
            if _java_type_extends(masked_content, declaration):
                inherited_types.add(name)
            if (
                declaration.start() in top_level_prefixes
                and (
                    _is_entity_type(file.path, name)
                    or _has_jpa_entity_annotation(
                        file.content,
                        masked_content,
                        top_level_prefixes[declaration.start()],
                        declaration.start(),
                    )
                )
                and _java_uses_property_access(
                    file.content,
                    masked_content,
                    declaration,
                    top_level_prefixes[declaration.start()],
                )
            ):
                property_access_types.add(name)
            if declaration.group("kind") == "enum":
                values, truncated, serialization_unresolved = _enum_values(
                    body,
                    string_constants,
                    name,
                )
                unresolved_enum_serialization_types.update((name,) * serialization_unresolved)
                if values and not serialization_unresolved:
                    source_path = (
                        f"{file.path}:{file.content.count(chr(10), 0, declaration.start()) + 1}"
                    )
                    enum_definitions[name].append(
                        _JavaEnumDefinition(
                            source_path=source_path,
                            enum_ref=_java_structural_ref("java", source_path, name),
                            values=tuple(values),
                            deterministic=not truncated,
                        )
                    )
    ambiguous_types = tuple(sorted(name for name, items in definitions.items() if len(items) > 1))
    return _JavaTypeAnalysis(
        fields={name: items[0] for name, items in definitions.items() if len(items) == 1},
        enums={
            name: items[0]
            for name, items in enum_definitions.items()
            if len(items) == 1 and name not in ambiguous_types
        },
        ambiguous_types=ambiguous_types,
        inherited_types=tuple(sorted(inherited_types)),
        property_access_types=tuple(sorted(property_access_types)),
        unresolved_column_types=tuple(sorted(unresolved_column_types)),
        unresolved_enum_serialization_types=tuple(sorted(unresolved_enum_serialization_types)),
        unresolved_json_naming_types=tuple(sorted(unresolved_json_naming_types)),
        unresolved_json_property_types=tuple(sorted(unresolved_json_property_types)),
    )


def _java_fields_with_json_naming(
    content: str,
    masked_content: str,
    declaration: re.Match[str],
    top_level_prefixes: dict[int, int],
    fields: list[JavaField],
    type_name: str,
) -> tuple[list[JavaField], tuple[str, ...]]:
    prefix_start = top_level_prefixes.get(
        declaration.start(),
        _java_nested_declaration_prefix_start(masked_content, declaration.start()),
    )
    naming_strategy, naming_unresolved = _java_json_naming_strategy(
        content,
        masked_content,
        prefix_start,
        declaration.start(),
    )
    if naming_strategy == "snake_case":
        return [(*field[:6], field[6] or _snake_case(field[0]), field[7]) for field in fields], ()
    return fields, (type_name,) * naming_unresolved


def _java_nested_declaration_prefix_start(masked_content: str, declaration_start: int) -> int:
    return (
        max(
            masked_content.rfind(";", 0, declaration_start),
            masked_content.rfind("{", 0, declaration_start),
            masked_content.rfind("}", 0, declaration_start),
        )
        + 1
    )


def _java_type_extends(masked_content: str, declaration: re.Match[str]) -> bool:
    if declaration.group("kind") != "class":
        return False
    opening = masked_content.find("{", declaration.end())
    if opening < 0:
        return False
    header = masked_content[declaration.end() : opening]
    return re.search(r"\bextends\s+[A-Za-z_$][A-Za-z0-9_$.]*", header) is not None


def _java_uses_property_access(
    content: str,
    masked_content: str,
    declaration: re.Match[str],
    prefix_start: int,
) -> bool:
    if declaration.group("kind") != "class":
        return False
    access_matches = _active_java_annotation_matches(
        content,
        masked_content,
        _JPA_ACCESS_ANNOTATION_MARKER,
        _JPA_ACCESS_ANNOTATION,
        start=prefix_start,
        end=declaration.start(),
    )
    if any(
        re.search(
            r"\bPROPERTY\b",
            _mask_java_non_code(_java_annotation_arguments(content, match.end())),
        )
        is not None
        for match in access_matches
    ):
        return True

    opening = masked_content.find("{", declaration.end())
    if opening < 0:
        return False
    closing = _matching_brace(content, opening)
    body = content[opening + 1 : closing]
    masked_body = _mask_nested_java_blocks(_mask_java_non_code(body))
    for match in _active_java_annotation_matches(
        body,
        masked_body,
        _JPA_ID_ANNOTATION_MARKER,
        _JPA_ID_ANNOTATION,
    ):
        _arguments, annotation_end = _java_annotation_arguments_and_end(body, match.end())
        following = _mask_java_annotation_arguments(
            masked_body[annotation_end : annotation_end + 1000]
        )
        terminators = [
            position for marker in (";", "{") if (position := following.find(marker)) >= 0
        ]
        member_declaration = following[: min(terminators)] if terminators else following
        if (
            re.search(
                r"\bget[A-Z][A-Za-z0-9_$]*\s*\([^)]*\)",
                member_declaration,
            )
            is not None
        ):
            return True
    return False


def _java_type_name_summary(names: tuple[str, ...]) -> str:
    return ", ".join(names)[:800]


def _type_body(content: str, start: int) -> str:
    brace = content.find("{", start)
    if brace < 0:
        return ""
    end = _matching_brace(content, brace)
    return content[brace + 1 : end]


def _record_fields(
    content: str,
    declaration: re.Match[str],
    string_constants: _JavaStringConstants,
) -> list[JavaField]:
    opening = content.find("(", declaration.end())
    if opening < 0:
        return []
    closing = _matching_parenthesis(content, opening)
    components = _split_top_level_java_components(content[opening + 1 : closing])
    return [
        field
        for component in components
        if (
            field := _record_component_field(
                component,
                string_constants,
                declaration.group("name"),
            )
        )
        is not None
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
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> JavaField | None:
    masked_component = _mask_java_non_code(component)
    if _has_jpa_transient_annotation(component, masked_component) or _has_jackson_ignore_annotation(
        component, masked_component
    ):
        return None
    annotations = _java_validation_annotations(component, masked_component)
    column_name, column_name_unresolved = _java_column_name(
        component,
        masked_component,
        string_constants,
        enclosing_type,
    )
    masked = _mask_java_annotation_arguments(masked_component)
    declaration = re.sub(r"@[A-Za-z_$][A-Za-z0-9_$.]*", " ", masked)
    normalized = " ".join(declaration.split())
    match = re.fullmatch(
        r"(?P<type>.+?)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)",
        normalized,
    )
    if match is None:
        return None
    serialized_name, serialized_name_unresolved = _jackson_property_name(
        component,
        masked_component,
        string_constants,
        enclosing_type,
    )
    return (
        match.group("name"),
        match.group("type"),
        annotations,
        column_name,
        column_name_unresolved,
        _jackson_property_access(component, masked_component),
        serialized_name,
        serialized_name_unresolved,
    )


def _class_fields(
    body: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> list[JavaField]:
    fields: list[JavaField] = []
    code_body = _mask_java_non_code(body)
    masked_body = _mask_nested_java_blocks(code_body)
    declaration_body = _mask_java_annotation_arguments(masked_body)
    for match in _FIELD_DECLARATION.finditer(declaration_body):
        modifiers = set(match.group("modifiers").split())
        if modifiers.intersection({"static", "transient"}):
            continue
        declarators = _java_field_declarators(match.group(0))
        if not declarators:
            continue
        prefix_start = max(
            _java_member_prefix_start(code_body, match.start()),
            match.start() - 500,
        )
        annotation_content = body[prefix_start : match.start()]
        annotation_mask = masked_body[prefix_start : match.start()]
        if _has_jpa_transient_annotation(
            annotation_content, annotation_mask
        ) or _has_jackson_ignore_annotation(annotation_content, annotation_mask):
            continue
        annotations = _java_validation_annotations(annotation_content, annotation_mask)
        column_name, column_name_unresolved = _java_column_name(
            annotation_content,
            annotation_mask,
            string_constants,
            enclosing_type,
        )
        serialized_name, serialized_name_unresolved = _jackson_property_name(
            annotation_content,
            annotation_mask,
            string_constants,
            enclosing_type,
        )
        fields.extend(
            (
                field_name,
                field_type,
                annotations,
                column_name,
                column_name_unresolved,
                _jackson_property_access(annotation_content, annotation_mask),
                serialized_name,
                serialized_name_unresolved,
            )
            for field_name, field_type in declarators
        )
    ignored_getters = _jackson_ignored_getter_properties(body, masked_body)
    fields = [field for field in fields if field[0] not in ignored_getters]
    known = {field[0] for field in fields}
    for accessor_field in _java_accessor_fields(
        body,
        code_body,
        string_constants,
        enclosing_type,
    ):
        if accessor_field[0] not in known and accessor_field[0] not in ignored_getters:
            fields.append(accessor_field)
            known.add(accessor_field[0])
    accessor_access, accessor_names, unresolved_accessor_names = (
        _jackson_accessor_property_metadata(
            body,
            masked_body,
            string_constants,
            enclosing_type,
        )
    )
    fields = [
        (
            *field[:5],
            accessor_access.get(field[0], field[5]),
            accessor_names.get(field[0], field[6]),
            field[7] or field[0] in unresolved_accessor_names,
        )
        for field in fields
    ]
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
            fields[index] = (
                old[0],
                old[1],
                sorted(set([*old[2], *annotations])),
                old[3],
                old[4],
                old[5],
                old[6],
                old[7],
            )
    return fields


def _java_accessor_fields(
    body: str,
    code_body: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> list[JavaField]:
    fields: dict[str, JavaField] = {}
    member_mask = _mask_nested_java_blocks(code_body)
    marker_pattern = re.compile(r"\b(?:get|is|set)[A-Z][A-Za-z0-9_$]*\s*\(")
    for marker in marker_pattern.finditer(member_mask):
        member_start = _java_member_prefix_start(code_body, marker.start())
        following = body[member_start : member_start + 2000]
        masked_following = _mask_java_annotation_arguments(_mask_java_non_code(following))
        signature = _JAVA_METHOD_SIGNATURE.match(masked_following)
        if signature is None or signature.group("terminator") != "{":
            continue
        handler = signature.group("handler")
        if not re.fullmatch(r"(?:get|is|set)[A-Z][A-Za-z0-9_$]*", handler):
            continue
        annotation_content = following[: signature.start("return")]
        annotation_mask = masked_following[: signature.start("return")]
        explicit_property = bool(
            _active_java_annotation_matches(
                annotation_content,
                annotation_mask,
                _JACKSON_PROPERTY_ANNOTATION_MARKER,
                _JACKSON_PROPERTY_ANNOTATION,
            )
        )
        if "public" not in signature.group("modifiers").split() and not explicit_property:
            continue
        if _has_jackson_ignore_annotation(annotation_content, annotation_mask):
            continue
        parameters = _java_parameter_declarations(
            following[signature.start("params") : signature.end("params")]
        )
        if parameters is None:
            continue
        parsed = _java_accessor_field_signature(
            handler,
            following[signature.start("return") : signature.end("return")],
            parameters,
        )
        if parsed is None:
            continue
        field_name, field_type, default_access = parsed
        declared_access = _jackson_property_access(annotation_content, annotation_mask)
        access = default_access if declared_access == "auto" else declared_access
        serialized_name, serialized_name_unresolved = _jackson_property_name(
            annotation_content,
            annotation_mask,
            string_constants,
            enclosing_type,
        )
        candidate: JavaField = (
            field_name,
            field_type,
            _java_validation_annotations(annotation_content, annotation_mask),
            None,
            False,
            access,
            serialized_name,
            serialized_name_unresolved,
        )
        existing = fields.get(field_name)
        fields[field_name] = (
            candidate if existing is None else _merge_java_accessor_fields(existing, candidate)
        )
    return list(fields.values())


def _java_accessor_field_signature(
    handler: str,
    return_type: str,
    parameters: list[_JavaParameter],
) -> tuple[str, str, JavaJsonAccess] | None:
    if handler.startswith(("get", "is")) and not parameters:
        field_type = return_type.strip()
        if field_type == "void":
            return None
        if handler.startswith("is") and _outer_java_type(field_type) not in {
            "boolean",
            "Boolean",
        }:
            return None
        suffix = handler[2:] if handler.startswith("is") else handler[3:]
        return suffix[0].lower() + suffix[1:], field_type, "read_only"
    if handler.startswith("set") and len(parameters) == 1:
        suffix = handler[3:]
        return suffix[0].lower() + suffix[1:], parameters[0].declared_type, "write_only"
    return None


def _merge_java_accessor_fields(first: JavaField, second: JavaField) -> JavaField:
    access: JavaJsonAccess = first[5] if first[5] == second[5] else "read_write"
    return (
        first[0],
        first[1],
        sorted(set([*first[2], *second[2]])),
        None,
        False,
        access,
        second[6] or first[6],
        first[7] or second[7],
    )


def _java_member_prefix_start(content: str, end: int) -> int:
    member_start = 0
    brace_depth = 0
    group_depth = {"(": 0, "[": 0}
    closing_groups = {")": "(", "]": "["}
    for index, character in enumerate(content[:end]):
        if character in group_depth:
            group_depth[character] += 1
            continue
        if character in closing_groups:
            opening = closing_groups[character]
            group_depth[opening] = max(0, group_depth[opening] - 1)
            continue
        if any(group_depth.values()):
            continue
        if character == "{":
            brace_depth += 1
        elif character == "}" and brace_depth > 0:
            brace_depth -= 1
            if brace_depth == 0:
                member_start = index + 1
        elif character == ";" and brace_depth == 0:
            member_start = index + 1
    return member_start


def _java_field_declarators(declaration: str) -> list[tuple[str, str]]:
    statement = declaration.removesuffix(";").strip()
    modifier = re.compile(r"^(?:public|protected|private|static|final|transient)\b\s*")
    while (match := modifier.match(statement)) is not None:
        statement = statement[match.end() :]
    components = _split_top_level_java_components(statement)
    if not components:
        return []
    identifier = r"[A-Za-z_$][A-Za-z0-9_$]*"
    first = re.fullmatch(
        rf"(?P<type>.+?)\s+(?P<name>{identifier})"
        r"(?P<dimensions>(?:\s*\[\])*)(?:\s*=.*)?",
        components[0].strip(),
        re.DOTALL,
    )
    if first is None:
        return []
    base_type = " ".join(first.group("type").split())
    result = [
        (
            first.group("name"),
            f"{base_type}{'[]' * first.group('dimensions').count('[')}",
        )
    ]
    for component in components[1:]:
        declarator = re.fullmatch(
            rf"(?P<name>{identifier})(?P<dimensions>(?:\s*\[\])*)(?:\s*=.*)?",
            component.strip(),
            re.DOTALL,
        )
        if declarator is None:
            return []
        result.append(
            (
                declarator.group("name"),
                f"{base_type}{'[]' * declarator.group('dimensions').count('[')}",
            )
        )
    return result


def _java_validation_annotations(
    content: str,
    masked_content: str,
) -> list[tuple[str, str]]:
    return [
        (
            annotation.group(0).rsplit(".", 1)[-1].removeprefix("@"),
            _java_annotation_arguments(content, annotation.end())[:500],
        )
        for annotation in _active_java_annotation_matches(
            content,
            masked_content,
            _VALIDATION_ANNOTATION_MARKER,
            _VALIDATION_ANNOTATION,
        )
    ]


def _java_column_name(
    content: str,
    masked_content: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> tuple[str | None, bool]:
    matches = _active_java_annotation_matches(
        content,
        masked_content,
        _JPA_COLUMN_ANNOTATION_MARKER,
        _JPA_COLUMN_ANNOTATION,
    )
    if not matches:
        return None, False
    arguments = _java_annotation_arguments(content, matches[-1].end())
    present, value = _java_named_string_argument(
        arguments,
        "name",
        string_constants,
        enclosing_type,
    )
    return value, present and value is None


def _has_jpa_transient_annotation(content: str, masked_content: str) -> bool:
    return bool(
        _active_java_annotation_matches(
            content,
            masked_content,
            _JPA_TRANSIENT_ANNOTATION_MARKER,
            _JPA_TRANSIENT_ANNOTATION,
        )
    )


def _has_jackson_ignore_annotation(content: str, masked_content: str) -> bool:
    return any(
        _jackson_ignore_enabled(content, match)
        for match in _active_java_annotation_matches(
            content,
            masked_content,
            _JACKSON_IGNORE_ANNOTATION_MARKER,
            _JACKSON_IGNORE_ANNOTATION,
        )
    )


def _jackson_ignored_getter_properties(content: str, masked_content: str) -> set[str]:
    properties: set[str] = set()
    for match in _active_java_annotation_matches(
        content,
        masked_content,
        _JACKSON_IGNORE_ANNOTATION_MARKER,
        _JACKSON_IGNORE_ANNOTATION,
    ):
        if not _jackson_ignore_enabled(content, match):
            continue
        _arguments, annotation_end = _java_annotation_arguments_and_end(content, match.end())
        following = _mask_java_annotation_arguments(masked_content[annotation_end:])
        getter = re.match(
            r"\s*(?:(?:public|protected|final)\s+)*[A-Za-z0-9_$<>,.?\[\]\s]+?"
            r"\s+(?:get|is)(?P<name>[A-Z][A-Za-z0-9_$]*)\s*\(",
            following,
        )
        if getter is not None:
            name = getter.group("name")
            properties.add(name[0].lower() + name[1:])
    return properties


def _jackson_ignore_enabled(content: str, annotation: re.Match[str]) -> bool:
    arguments = _java_annotation_arguments(content, annotation.end())
    inner = arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    return re.fullmatch(r"\s*(?:value\s*=\s*)?false\s*", inner) is None


def _jackson_property_access(
    content: str,
    masked_content: str,
) -> JavaJsonAccess:
    access: JavaJsonAccess = "auto"
    for match in _active_java_annotation_matches(
        content,
        masked_content,
        _JACKSON_PROPERTY_ANNOTATION_MARKER,
        _JACKSON_PROPERTY_ANNOTATION,
    ):
        access = _jackson_property_access_from_match(content, match)
    return access


def _jackson_property_access_from_match(
    content: str,
    annotation: re.Match[str],
) -> JavaJsonAccess:
    arguments = _java_annotation_arguments(content, annotation.end())
    match = re.search(
        r"\baccess\s*=\s*(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*"
        r"(?P<access>AUTO|READ_ONLY|WRITE_ONLY|READ_WRITE)\b",
        _mask_java_non_code(arguments),
    )
    if match is None:
        return "auto"
    return cast(JavaJsonAccess, match.group("access").lower())


def _jackson_property_name(
    content: str,
    masked_content: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> tuple[str | None, bool]:
    serialized_name: str | None = None
    unresolved = False
    for match in _active_java_annotation_matches(
        content,
        masked_content,
        _JACKSON_PROPERTY_ANNOTATION_MARKER,
        _JACKSON_PROPERTY_ANNOTATION,
    ):
        candidate, candidate_unresolved = _jackson_property_name_from_match(
            content,
            match,
            string_constants,
            enclosing_type,
        )
        if candidate is not None:
            serialized_name = candidate
            unresolved = False
        elif candidate_unresolved:
            serialized_name = None
            unresolved = True
    return serialized_name, unresolved


def _jackson_property_name_from_match(
    content: str,
    annotation: re.Match[str],
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> tuple[str | None, bool]:
    arguments = _java_annotation_arguments(content, annotation.end())
    inner = arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    masked_inner = _mask_java_non_code(inner)
    assignment = re.search(r"\bvalue\s*=", masked_inner)
    if assignment is not None:
        expression = _java_annotation_expression(
            inner,
            assignment.end(),
            allow_identifier=True,
        )
    elif re.search(r"\b[A-Za-z_$][A-Za-z0-9_$]*\s*=", masked_inner) is not None:
        return None, False
    else:
        expression = _java_annotation_expression(inner, 0, allow_identifier=True)
    if not expression:
        return None, False
    value = _java_string_expression_value(expression, string_constants, enclosing_type)
    if value == "":
        return None, False
    if value is None or not 1 <= len(value) <= 160:
        return None, True
    return value, False


def _java_json_naming_strategy(
    content: str,
    masked_content: str,
    start: int,
    end: int,
) -> tuple[Literal["snake_case"] | None, bool]:
    matches = _active_java_annotation_matches(
        content,
        masked_content,
        _JACKSON_NAMING_ANNOTATION_MARKER,
        _JACKSON_NAMING_ANNOTATION,
        start=start,
        end=end,
    )
    if not matches:
        return None, False
    arguments = _java_annotation_arguments(content, matches[-1].end())
    strategy = re.search(
        r"(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*(?P<name>[A-Za-z_$][A-Za-z0-9_$]*Strategy)"
        r"\s*\.class\b",
        _mask_java_non_code(arguments),
    )
    if strategy is not None and strategy.group("name") == "SnakeCaseStrategy":
        return "snake_case", False
    return None, True


def _jackson_accessor_property_metadata(
    content: str,
    masked_content: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> tuple[dict[str, JavaJsonAccess], dict[str, str], set[str]]:
    access_properties: dict[str, JavaJsonAccess] = {}
    named_properties: dict[str, str] = {}
    unresolved_names: set[str] = set()
    for match in _active_java_annotation_matches(
        content,
        masked_content,
        _JACKSON_PROPERTY_ANNOTATION_MARKER,
        _JACKSON_PROPERTY_ANNOTATION,
    ):
        access = _jackson_property_access_from_match(content, match)
        _arguments, annotation_end = _java_annotation_arguments_and_end(content, match.end())
        following = _mask_java_annotation_arguments(masked_content[annotation_end:])
        accessor = re.match(
            r"(?:\s*@[A-Za-z0-9_$.]+)*\s*"
            r"(?:(?:public|protected|private|final)\s+|@[A-Za-z0-9_$.]+\s+)*"
            r"[A-Za-z0-9_$<>,.?\[\]\s]+?\s+"
            r"(?:get|is|set)(?P<name>[A-Z][A-Za-z0-9_$]*)\s*\(",
            following,
        )
        if accessor is not None:
            name = accessor.group("name")
            property_name = name[0].lower() + name[1:]
            if access != "auto":
                access_properties[property_name] = access
            serialized_name, serialized_name_unresolved = _jackson_property_name_from_match(
                content,
                match,
                string_constants,
                enclosing_type,
            )
            if serialized_name is not None:
                named_properties[property_name] = serialized_name
                unresolved_names.discard(property_name)
            elif serialized_name_unresolved:
                named_properties.pop(property_name, None)
                unresolved_names.add(property_name)
    return access_properties, named_properties, unresolved_names


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


def _java_string_constants(files: list[JavaSourceFileSnapshot]) -> _JavaStringConstants:
    qualified_candidates: dict[str, list[str]] = defaultdict(list)
    simple_candidates: dict[str, list[str]] = defaultdict(list)
    local_candidates: dict[tuple[str, str], list[str]] = defaultdict(list)
    for file in sorted(files, key=lambda item: item.path):
        masked_content = _mask_java_non_code(file.content)
        for declaration, _prefix_start in _java_top_level_declarations(file, masked_content):
            type_name = declaration.group("name")
            for name, value in _java_declared_string_constants(
                file.content,
                masked_content,
                declaration,
            ):
                qualified_candidates[f"{type_name}.{name}"].append(value)
                simple_candidates[name].append(value)
                local_candidates[(type_name, name)].append(value)
    qualified_values = {
        name: values[0] for name, values in qualified_candidates.items() if len(values) == 1
    }
    simple_values = {
        name: values[0] for name, values in simple_candidates.items() if len(values) == 1
    }
    local_values: dict[str, dict[str, str]] = defaultdict(dict)
    for (type_name, name), values in local_candidates.items():
        if len(values) == 1:
            local_values[type_name][name] = values[0]
    return _JavaStringConstants(
        qualified_values=qualified_values,
        simple_values=simple_values,
        local_values=dict(local_values),
    )


def _java_declared_string_constants(
    content: str,
    masked_content: str,
    declaration: re.Match[str],
) -> list[tuple[str, str]]:
    opening = masked_content.find("{", declaration.end())
    if opening < 0:
        return []
    closing = _matching_brace(content, opening)
    body_start = opening + 1
    shallow_mask = _mask_nested_java_blocks(masked_content[body_start:closing])
    constants: list[tuple[str, str]] = []
    for match in _JAVA_STRING_CONSTANT_DECLARATION.finditer(shallow_mask):
        modifiers = set(match.group("modifiers").split())
        if declaration.group("kind") != "interface" and not {"static", "final"}.issubset(modifiers):
            continue
        expression = content[
            body_start + match.start("expression") : body_start + match.end("expression")
        ]
        value = _java_string_expression_value(expression, None, "")
        if value is not None:
            constants.append((match.group("name"), value))
    return constants


def _java_unresolved_mapping_locations(
    files: list[JavaSourceFileSnapshot],
    string_constants: _JavaStringConstants,
) -> tuple[str, ...]:
    unresolved: set[str] = set()
    for file in sorted(files, key=lambda item: item.path):
        masked_content = _mask_java_non_code(file.content)
        for declaration, prefix_start in _java_top_level_declarations(file, masked_content):
            opening = masked_content.find("{", declaration.end())
            if opening < 0:
                continue
            closing = _matching_brace(file.content, opening)
            shallow_mask = list(masked_content)
            shallow_mask[opening + 1 : closing] = _mask_nested_java_blocks(
                masked_content[opening + 1 : closing]
            )
            for match in _active_java_annotation_matches(
                file.content,
                "".join(shallow_mask),
                _MAPPING_ANNOTATION_MARKER,
                _MAPPING_ANNOTATION,
                start=prefix_start,
                end=closing,
            ):
                arguments = _java_annotation_arguments(file.content, match.end())
                if not _mapping_paths(arguments, string_constants, declaration.group("name")):
                    line = file.content.count("\n", 0, match.start()) + 1
                    unresolved.add(f"{file.path}:{line}")
    return tuple(sorted(unresolved))


def _java_unresolved_mapping_condition_locations(
    files: list[JavaSourceFileSnapshot],
    string_constants: _JavaStringConstants,
) -> tuple[str, ...]:
    unresolved: set[str] = set()
    for file in sorted(files, key=lambda item: item.path):
        masked_content = _mask_java_non_code(file.content)
        for declaration, prefix_start in _java_top_level_declarations(file, masked_content):
            opening = masked_content.find("{", declaration.end())
            if opening < 0:
                continue
            closing = _matching_brace(file.content, opening)
            shallow_mask = list(masked_content)
            shallow_mask[opening + 1 : closing] = _mask_nested_java_blocks(
                masked_content[opening + 1 : closing]
            )
            for match in _active_java_annotation_matches(
                file.content,
                "".join(shallow_mask),
                _MAPPING_ANNOTATION_MARKER,
                _MAPPING_ANNOTATION,
                start=prefix_start,
                end=closing,
            ):
                arguments = _java_annotation_arguments(file.content, match.end())
                conditions = _mapping_conditions(
                    arguments,
                    string_constants,
                    declaration.group("name"),
                )
                if conditions is None:
                    line = file.content.count("\n", 0, match.start()) + 1
                    unresolved.add(f"{file.path}:{line}")
    return tuple(sorted(unresolved))


def _java_unresolved_kafka_locations(
    files: list[JavaSourceFileSnapshot],
    string_constants: _JavaStringConstants,
) -> tuple[str, ...]:
    unresolved: set[str] = set()
    for file in sorted(files, key=lambda item: item.path):
        masked_content = _mask_java_non_code(file.content)
        template_names = _java_kafka_template_names(masked_content)
        listener_matches = _active_java_annotation_matches(
            file.content,
            masked_content,
            _KAFKA_LISTENER_MARKER,
            _KAFKA_LISTENER,
        )
        for match in listener_matches:
            enclosing_type = _java_enclosing_top_level_type(
                file,
                masked_content,
                match.start(),
            )
            arguments = _java_annotation_arguments(file.content, match.end())
            if not _kafka_listener_topics(arguments, string_constants, enclosing_type):
                line = file.content.count("\n", 0, match.start()) + 1
                unresolved.add(f"{file.path}:{line}")
        for marker in _java_kafka_send_markers(masked_content, template_names):
            parsed = _KAFKA_SEND.match(file.content, marker.start())
            topic = (
                _decode_java_string_literal(parsed.group("topic")) if parsed is not None else None
            )
            if topic is None or _java_has_runtime_expression(topic):
                line = file.content.count("\n", 0, marker.start()) + 1
                unresolved.add(f"{file.path}:{line}")
    return tuple(sorted(unresolved))


def _java_kafka_template_names(masked_content: str) -> frozenset[str]:
    return frozenset(
        {
            "KafkaTemplate",
            "kafkaTemplate",
            *(
                match.group("name")
                for match in _KAFKA_TEMPLATE_DECLARATION.finditer(masked_content)
            ),
        }
    )


def _java_kafka_send_markers(
    masked_content: str,
    template_names: frozenset[str],
) -> list[re.Match[str]]:
    targets = "|".join(re.escape(name) for name in sorted(template_names))
    return list(re.finditer(rf"\b(?:{targets})\.send\b", masked_content))


def _java_enclosing_top_level_type(
    file: JavaSourceFileSnapshot,
    masked_content: str,
    position: int,
) -> str:
    for declaration, _prefix_start in _java_top_level_declarations(file, masked_content):
        opening = masked_content.find("{", declaration.end())
        if opening >= 0 and opening < position < _matching_brace(file.content, opening):
            return declaration.group("name")
    return ""


def _java_routes(
    file: JavaSourceFileSnapshot,
    interface_routes: dict[str, tuple[_JavaRoute, ...]],
    string_constants: _JavaStringConstants,
) -> list[_JavaRoute]:
    masked_content = _mask_java_non_code(file.content)
    routes: list[_JavaRoute] = []
    for selected in _java_controller_declarations(file, masked_content):
        local_routes = _java_controller_routes(
            file,
            masked_content,
            selected,
            string_constants,
        )
        routes.extend(local_routes)
        operation_refs = {route.operation_ref for route in local_routes}
        for route in _java_bound_interface_routes(
            file,
            masked_content,
            selected,
            interface_routes,
            string_constants,
        ):
            if route.operation_ref not in operation_refs:
                routes.append(route)
                operation_refs.add(route.operation_ref)
    return routes


def _java_interface_route_contracts(
    files: list[JavaSourceFileSnapshot],
    string_constants: _JavaStringConstants,
) -> _JavaInterfaceContracts:
    definitions: dict[str, list[_JavaInterfaceDefinition]] = defaultdict(list)
    for file in sorted(files, key=lambda item: item.path):
        masked_content = _mask_java_non_code(file.content)
        for selected in _java_top_level_declarations(file, masked_content):
            declaration, _prefix_start = selected
            if declaration.group("kind") != "interface":
                continue
            base_paths, base_methods, base_conditions = _java_type_mapping(
                file,
                masked_content,
                declaration,
                selected[1],
                string_constants,
            )
            definitions[declaration.group("name")].append(
                _JavaInterfaceDefinition(
                    routes=tuple(
                        _java_controller_routes(
                            file,
                            masked_content,
                            selected,
                            string_constants,
                            allow_abstract_methods=True,
                        )
                    ),
                    parents=_java_extended_interfaces(masked_content, declaration),
                    base_paths=tuple(base_paths),
                    base_methods=tuple(base_methods) if base_methods is not None else None,
                    base_conditions=(
                        tuple(base_conditions) if base_conditions is not None else None
                    ),
                )
            )
    unique = {name: items[0] for name, items in definitions.items() if len(items) == 1}
    unresolved = {name for name, items in definitions.items() if len(items) != 1}
    resolved: dict[str, tuple[_JavaRoute, ...]] = {}
    visiting: set[str] = set()

    def resolve(name: str) -> tuple[_JavaRoute, ...]:
        if name in resolved:
            return resolved[name]
        if name in visiting:
            unresolved.add(name)
            return ()
        definition = unique.get(name)
        if definition is None:
            unresolved.add(name)
            return ()
        visiting.add(name)
        routes = list(definition.routes)
        for parent in definition.parents:
            routes.extend(_java_rebased_interface_routes(resolve(parent), definition, name))
        visiting.remove(name)
        resolved[name] = tuple(routes)
        return resolved[name]

    for interface_name in sorted(unique):
        resolve(interface_name)
    return _JavaInterfaceContracts(resolved, tuple(sorted(unresolved)))


def _java_rebased_interface_routes(
    contracts: tuple[_JavaRoute, ...],
    definition: _JavaInterfaceDefinition,
    interface_name: str,
) -> list[_JavaRoute]:
    if definition.base_conditions is None:
        return []
    routes: list[_JavaRoute] = []
    for contract in contracts:
        if definition.base_methods is not None and contract.method not in definition.base_methods:
            continue
        conditions = _merge_mapping_conditions(
            definition.base_conditions,
            contract.conditions,
        )
        for base_path in definition.base_paths:
            full_path = _join_route_path(base_path, contract.path)
            routes.append(
                contract.model_copy(
                    update={
                        "path": full_path,
                        "operation_ref": _java_operation_ref(
                            contract.method,
                            full_path,
                            conditions,
                        ),
                        "controller_ref": f"java://{interface_name}",
                        "conditions": tuple(conditions),
                    }
                )
            )
    return routes


def _java_controller_routes(
    file: JavaSourceFileSnapshot,
    masked_content: str,
    selected: tuple[re.Match[str], int],
    string_constants: _JavaStringConstants,
    *,
    allow_abstract_methods: bool = False,
) -> list[_JavaRoute]:
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
    base_paths, base_methods, base_conditions = _java_type_mapping(
        file,
        masked_content,
        declaration,
        declaration_prefix_start,
        string_constants,
    )
    if base_conditions is None:
        return []
    controller = declaration.group("name")
    call_target_types = (
        _java_call_target_types(file, masked_content, declaration)
        if declaration.group("kind") == "class"
        else {}
    )
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
            base_methods,
            base_conditions,
            controller,
            string_constants,
            call_target_types=call_target_types,
            allow_abstract_methods=allow_abstract_methods,
        )
    ]


def _java_bound_interface_routes(
    file: JavaSourceFileSnapshot,
    masked_content: str,
    selected: tuple[re.Match[str], int],
    interface_routes: dict[str, tuple[_JavaRoute, ...]],
    string_constants: _JavaStringConstants,
) -> list[_JavaRoute]:
    declaration, _prefix_start = selected
    controller = declaration.group("name")
    base_paths, base_methods, base_conditions = _java_type_mapping(
        file,
        masked_content,
        declaration,
        selected[1],
        string_constants,
    )
    if base_conditions is None:
        return []
    call_target_types = _java_call_target_types(file, masked_content, declaration)
    routes: list[_JavaRoute] = []
    for interface_name in _java_implemented_interfaces(masked_content, declaration):
        for contract in interface_routes.get(interface_name, ()):
            if base_methods is not None and contract.method not in base_methods:
                continue
            implementation = _java_controller_method_implementation(
                file,
                masked_content,
                declaration,
                contract,
            )
            implementation_update: dict[str, object] = {}
            if implementation is None:
                body = contract.body
                source_line = file.content.count("\n", 0, declaration.start()) + 1
            else:
                body = implementation.body
                source_line = implementation.source_line
                implementation_update = {
                    "return_type": implementation.return_type,
                    "parameters": implementation.parameters,
                    "declared_exceptions": list(implementation.declared_exceptions),
                }
            conditions = _merge_mapping_conditions(
                base_conditions,
                contract.conditions,
            )
            for base_path in base_paths:
                full_path = _join_route_path(base_path, contract.path)
                routes.append(
                    contract.model_copy(
                        update={
                            "path": full_path,
                            "operation_ref": _java_operation_ref(
                                contract.method,
                                full_path,
                                conditions,
                            ),
                            "controller_ref": f"java://{controller}",
                            "conditions": tuple(conditions),
                            "call_target_types": call_target_types,
                            "body": body,
                            "source_line": source_line,
                            **implementation_update,
                        }
                    )
                )
    return routes


def _java_type_mapping(
    file: JavaSourceFileSnapshot,
    masked_content: str,
    declaration: re.Match[str],
    declaration_prefix_start: int,
    string_constants: _JavaStringConstants,
) -> tuple[
    list[str],
    list[JavaHttpMethod] | None,
    list[str] | None,
]:
    base_matches = _active_java_annotation_matches(
        file.content,
        masked_content,
        _REQUEST_MAPPING_MARKER,
        _REQUEST_MAPPING,
        start=declaration_prefix_start,
        end=declaration.start(),
    )
    if not base_matches:
        return [""], None, []
    base_arguments = _java_annotation_arguments(file.content, base_matches[-1].end())
    return (
        _mapping_paths(
            base_arguments,
            string_constants,
            declaration.group("name"),
        ),
        _mapping_http_methods(base_matches[-1], base_arguments),
        _mapping_conditions(
            base_arguments,
            string_constants,
            declaration.group("name"),
        ),
    )


def _java_implemented_interfaces(
    masked_content: str,
    declaration: re.Match[str],
) -> tuple[str, ...]:
    opening = masked_content.find("{", declaration.end())
    if opening < 0:
        return ()
    header = masked_content[declaration.end() : opening]
    implemented = re.search(r"\bimplements\s+(.+?)(?=\bpermits\b|$)", header, re.DOTALL)
    if implemented is None:
        return ()
    return tuple(
        _outer_java_type(component)
        for component in _split_top_level_java_components(implemented.group(1))
        if component.strip()
    )


def _java_extended_interfaces(
    masked_content: str,
    declaration: re.Match[str],
) -> tuple[str, ...]:
    opening = masked_content.find("{", declaration.end())
    if opening < 0:
        return ()
    header = masked_content[declaration.end() : opening]
    extended = re.search(r"\bextends\s+(.+?)(?=\bpermits\b|$)", header, re.DOTALL)
    if extended is None:
        return ()
    return tuple(
        _outer_java_type(component)
        for component in _split_top_level_java_components(extended.group(1))
        if component.strip()
    )


def _java_controller_method_implementation(
    file: JavaSourceFileSnapshot,
    masked_content: str,
    declaration: re.Match[str],
    contract: _JavaRoute,
) -> _JavaMethodImplementation | None:
    class_opening = masked_content.find("{", declaration.end())
    if class_opening < 0:
        return None
    class_end = _matching_brace(file.content, class_opening)
    route_masked_content = list(masked_content)
    route_masked_content[class_opening + 1 : class_end] = _mask_nested_java_blocks(
        masked_content[class_opening + 1 : class_end]
    )
    route_mask = "".join(route_masked_content)
    class_body = masked_content[class_opening + 1 : class_end]
    expected_types = _java_parameter_type_signature(contract.parameters)
    if expected_types is None:
        return None
    handler_marker = re.compile(rf"\b{re.escape(contract.handler)}\s*\(")
    for match in handler_marker.finditer(route_mask, class_opening + 1, class_end):
        relative_handler_start = match.start() - class_opening - 1
        method_start = (
            class_opening
            + 1
            + _java_member_prefix_start(
                class_body,
                relative_handler_start,
            )
        )
        following = file.content[method_start : method_start + 2000]
        masked_following = _mask_java_annotation_arguments(_mask_java_non_code(following))
        signature = _JAVA_METHOD_SIGNATURE.match(masked_following)
        if (
            signature is None
            or signature.group("handler") != contract.handler
            or signature.group("terminator") != "{"
        ):
            continue
        parameters = following[signature.start("params") : signature.end("params")]
        if _java_parameter_type_signature(parameters) != expected_types:
            continue
        body_opening = method_start + signature.end()
        body_end = _matching_brace(file.content, body_opening - 1)
        return _JavaMethodImplementation(
            return_type=following[signature.start("return") : signature.end("return")],
            parameters=parameters,
            declared_exceptions=tuple(
                _declared_java_exceptions(
                    following[signature.start("throws") : signature.end("throws")]
                    if signature.group("throws") is not None
                    else None
                )
            ),
            body=file.content[body_opening:body_end],
            source_line=file.content.count(
                "\n",
                0,
                method_start + signature.start("handler"),
            )
            + 1,
        )
    return None


def _java_parameter_type_signature(parameters: str) -> tuple[str, ...] | None:
    declarations = _java_parameter_declarations(parameters)
    if declarations is None:
        return None
    return tuple(
        _normalized_java_declared_type(parameter.declared_type) for parameter in declarations
    )


def _java_controller_declarations(
    file: JavaSourceFileSnapshot,
    masked_content: str,
) -> list[tuple[re.Match[str], int]]:
    candidates = [
        selected
        for selected in _java_top_level_declarations(file, masked_content)
        if selected[0].group("kind") in {"class", "record"}
        and (
            selected[0].group("kind") == "record"
            or not _java_class_is_abstract(masked_content, selected)
        )
    ]
    if not candidates:
        return []
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
    return annotated


def _java_class_is_abstract(
    masked_content: str,
    selected: tuple[re.Match[str], int],
) -> bool:
    declaration, prefix_start = selected
    prefix = _mask_java_annotation_arguments(masked_content[prefix_start : declaration.start()])
    return re.search(r"\babstract\b", prefix) is not None


def _java_call_target_types(
    file: JavaSourceFileSnapshot,
    masked_content: str,
    declaration: re.Match[str],
) -> dict[str, str]:
    class_opening = masked_content.find("{", declaration.end())
    if class_opening < 0:
        return {}
    class_end = _matching_brace(file.content, class_opening)
    class_body = masked_content[class_opening + 1 : class_end]
    member_mask = _mask_nested_java_blocks(class_body)
    targets: dict[str, str] = {}
    for field in _FIELD_DECLARATION.finditer(member_mask):
        for name, declared_type in _java_field_declarators(field.group(0)):
            if _java_call_kind_from_declared_type(declared_type) is not None:
                targets[name] = _outer_java_type(declared_type)
    controller = declaration.group("name")
    constructor_marker = re.compile(rf"\b{re.escape(controller)}\s*\(")
    constructor_signature = re.compile(
        rf"(?:\s*@[A-Za-z0-9_$.]+)*\s*(?:(?:public|protected|private)\s+)?"
        rf"{re.escape(controller)}\s*\((?P<params>[^)]*)\)"
    )
    for marker in constructor_marker.finditer(member_mask):
        member_start = _java_member_prefix_start(class_body, marker.start())
        following = file.content[class_opening + 1 + member_start : class_end]
        masked_following = _mask_java_annotation_arguments(_mask_java_non_code(following))
        signature = constructor_signature.match(masked_following)
        if signature is None:
            continue
        parameters = _java_parameter_declarations(signature.group("params"))
        if parameters is None:
            continue
        for parameter in parameters:
            if _java_call_kind_from_declared_type(parameter.declared_type) is not None:
                targets.setdefault(parameter.name, _outer_java_type(parameter.declared_type))
    return targets


def _java_call_kind_from_declared_type(
    declared_type: str,
) -> Literal["service_call", "feign_call"] | None:
    normalized = _outer_java_type(declared_type).lower()
    if normalized.endswith("client"):
        return "feign_call"
    if normalized.endswith(("service", "repository", "mapper")):
        return "service_call"
    return None


def _java_top_level_declarations(
    file: JavaSourceFileSnapshot,
    masked_content: str,
) -> list[tuple[re.Match[str], int]]:
    top_level_mask = _mask_nested_java_blocks(masked_content)
    declarations = list(_TYPE_DECLARATION.finditer(top_level_mask))
    selected: list[tuple[re.Match[str], int]] = []
    declaration_prefix_start = 0
    for declaration in declarations:
        selected.append((declaration, declaration_prefix_start))
        opening = masked_content.find("{", declaration.end())
        if opening >= 0:
            declaration_prefix_start = _matching_brace(file.content, opening) + 1
    return selected


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
    base_methods: list[JavaHttpMethod] | None,
    base_conditions: list[str],
    controller: str,
    string_constants: _JavaStringConstants,
    *,
    call_target_types: dict[str, str] | None = None,
    allow_abstract_methods: bool = False,
) -> list[_JavaRoute]:
    mapping_arguments, mapping_end = _java_annotation_arguments_and_end(
        file.content,
        mapping.end(),
    )
    following = file.content[mapping_end : mapping_end + 2000]
    masked_following = _mask_java_annotation_arguments(_mask_java_non_code(following))
    signature = _JAVA_METHOD_SIGNATURE.match(masked_following)
    if signature is None:
        return []
    if allow_abstract_methods and re.search(r"\bstatic\b", signature.group("modifiers")):
        return []
    if signature.group("terminator") == ";" and not allow_abstract_methods:
        return []
    paths = _mapping_paths(mapping_arguments, string_constants, controller)
    methods = _mapping_http_methods(mapping, mapping_arguments)
    if base_methods is not None:
        methods = [method for method in methods if method in base_methods]
    mapping_conditions = _mapping_conditions(
        mapping_arguments,
        string_constants,
        controller,
    )
    if mapping_conditions is None:
        return []
    conditions = _merge_mapping_conditions(base_conditions, mapping_conditions)
    body_start = mapping_end + signature.end() - 1
    body_end = (
        _matching_brace(file.content, body_start)
        if signature.group("terminator") == "{"
        else body_start
    )
    handler = signature.group("handler")
    return [
        _JavaRoute(
            method=method,
            path=full_path,
            operation_ref=_java_operation_ref(method, full_path, conditions),
            controller_ref=f"java://{controller}",
            handler=handler,
            return_type=following[signature.start("return") : signature.end("return")],
            parameters=following[signature.start("params") : signature.end("params")],
            declared_exceptions=_declared_java_exceptions(
                following[signature.start("throws") : signature.end("throws")]
                if signature.group("throws") is not None
                else None
            ),
            conditions=tuple(conditions),
            call_target_types=call_target_types or {},
            body=(
                file.content[body_start + 1 : body_end]
                if signature.group("terminator") == "{"
                else ""
            ),
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
) -> list[JavaHttpMethod]:
    composed_method = mapping.groupdict().get("method")
    if composed_method is not None:
        return [
            cast(
                JavaHttpMethod,
                composed_method.upper(),
            )
        ]
    content = (
        arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    )
    method_assignment = re.search(r"\bmethod\s*=", _mask_java_non_code(content))
    if method_assignment is None:
        methods = list(_SPRING_HTTP_METHODS)
    else:
        expression = _java_annotation_expression(
            content,
            method_assignment.end(),
            allow_identifier=True,
        )
        methods = (
            list(_SPRING_HTTP_METHODS)
            if re.fullmatch(r"\{\s*\}", expression) is not None
            else re.findall(
                r"(?<![A-Za-z0-9_$])(?:RequestMethod\.)?"
                r"(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|TRACE)\b",
                expression,
            )
        )
    return list(dict.fromkeys(methods))


def _mapping_conditions(
    arguments: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> list[str] | None:
    content = (
        arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    )
    masked_content = _mask_java_non_code(content)
    conditions: list[str] = []
    for name in ("params", "headers", "consumes", "produces"):
        assignment = re.search(rf"\b{name}\s*=", masked_content)
        if assignment is None:
            continue
        expression = _java_annotation_expression(
            content,
            assignment.end(),
            allow_identifier=True,
        )
        if re.fullmatch(r"\{\s*\}", expression) is not None:
            continue
        values = _java_mapping_path_values(
            expression,
            string_constants,
            enclosing_type,
        )
        if not values:
            return None
        conditions.extend(f"{name}:{value}" for value in sorted(set(values)))
    return conditions


def _merge_mapping_conditions(
    base_conditions: list[str] | tuple[str, ...],
    overriding_conditions: list[str] | tuple[str, ...],
) -> list[str]:
    overridden_media = {
        condition.partition(":")[0]
        for condition in overriding_conditions
        if condition.startswith(("consumes:", "produces:"))
    }
    retained_base = [
        condition
        for condition in base_conditions
        if condition.partition(":")[0] not in overridden_media
    ]
    return [*retained_base, *overriding_conditions]


def _java_operation_ref(
    method: JavaHttpMethod,
    path: str,
    conditions: list[str],
) -> str:
    operation_ref = f"operation://{method}{path}"
    if conditions:
        encoded = json.dumps(sorted(set(conditions)), ensure_ascii=False, separators=(",", ":"))
        operation_ref += f"#conditions-{sha256(encoded.encode()).hexdigest()[:16]}"
    if len(operation_ref) <= 512:
        return operation_ref
    digest = sha256(operation_ref.encode()).hexdigest()[:24]
    return f"{operation_ref[:487]}-{digest}"


def _declared_java_exceptions(clause: str | None) -> list[str]:
    if clause is None:
        return []
    return [
        name
        for item in clause.split(",")
        if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*", name := item.strip())
    ]


def _mapping_paths(
    arguments: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> list[str]:
    content = (
        arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    )
    named = re.search(r"\b(?:value|path)\s*=", _mask_java_non_code(content))
    stripped = content.strip()
    if named is None and re.match(r"[A-Za-z_$][A-Za-z0-9_$]*\s*=", stripped) is not None:
        return [""]
    expression = (
        _java_annotation_expression(content, named.end(), allow_identifier=True)
        if named is not None
        else _java_annotation_expression(content, 0, allow_identifier=True)
    )
    paths = _java_mapping_path_values(expression, string_constants, enclosing_type)
    if paths:
        return list(dict.fromkeys(paths))
    if named is not None or expression:
        return []
    if not stripped or re.match(r"[A-Za-z_$][A-Za-z0-9_$]*\s*=", stripped) is not None:
        return [""]
    return []


def _java_mapping_path_values(
    expression: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> list[str]:
    stripped = expression.strip()
    if not stripped:
        return []
    components = (
        _split_top_level_java_components(stripped[1:-1])
        if stripped.startswith("{") and stripped.endswith("}")
        else [stripped]
    )
    values: list[str] = []
    for component in components:
        value = _java_string_expression_value(component, string_constants, enclosing_type)
        if value is None:
            return []
        values.append(value)
    return values


def _java_string_expression_value(
    expression: str,
    string_constants: _JavaStringConstants | None,
    enclosing_type: str,
) -> str | None:
    values: list[str] = []
    for component in _split_top_level_java_operator(expression.strip(), "+"):
        literal = re.fullmatch(_JAVA_STRING_LITERAL, component.strip())
        if literal is not None:
            decoded = _decode_java_string_literal(component.strip()[1:-1])
            if decoded is None:
                return None
            values.append(decoded)
            continue
        reference = component.strip()
        if (
            string_constants is None
            or re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*", reference) is None
        ):
            return None
        resolved = string_constants.resolve(reference, enclosing_type)
        if resolved is None:
            return None
        values.append(resolved)
    resolved = "".join(values) if values else None
    if resolved is None or _java_has_runtime_expression(resolved):
        return None
    return resolved


def _java_has_runtime_expression(value: str) -> bool:
    return "${" in value or "#{" in value


def _split_top_level_java_operator(content: str, operator: str) -> list[str]:
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
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif character == operator and depth == 0:
            components.append(content[start:index].strip())
            start = index + 1
        index += 1
    components.append(content[start:].strip())
    return components


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
    end = _java_annotation_expression_end(content, index)
    expression = content[index:end].strip()
    if expression.startswith("{") or re.match(_JAVA_STRING_LITERAL, expression) is not None:
        return expression
    if allow_identifier and re.match(r"[A-Za-z_$][A-Za-z0-9_$.]*", expression) is not None:
        return expression
    return ""


def _java_annotation_expression_end(content: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(content):
        non_code = _JAVA_NON_CODE.match(content, index)
        if non_code is not None:
            index = non_code.end()
            continue
        character = content[index]
        if character in "([{":
            depth += 1
        elif character in ")]}" and depth > 0:
            depth -= 1
        elif character == "," and depth == 0:
            return index
        index += 1
    return len(content)


def _java_literal_values(expression: str) -> list[str]:
    stripped = expression.strip()
    single_literal = re.fullmatch(_JAVA_STRING_LITERAL, stripped)
    array_pattern = rf"\{{\s*{_JAVA_STRING_LITERAL}(?:\s*,\s*{_JAVA_STRING_LITERAL})*\s*,?\s*\}}"
    if single_literal is None and re.fullmatch(array_pattern, stripped) is None:
        return []
    values: list[str] = []
    for match in re.finditer(r'"((?:\\.|[^"\\])*)"', stripped):
        decoded = _decode_java_string_literal(match.group(1))
        if decoded is None:
            return []
        values.append(decoded)
    return values


def _decode_java_string_literal(value: str) -> str | None:
    decoded: list[str] = []
    index = 0
    simple_escapes = {
        "b": "\b",
        "t": "\t",
        "n": "\n",
        "f": "\f",
        "r": "\r",
        '"': '"',
        "'": "'",
        "\\": "\\",
        "s": " ",
    }
    while index < len(value):
        if value[index] != "\\":
            decoded.append(value[index])
            index += 1
            continue
        index += 1
        if index >= len(value):
            return None
        marker = value[index]
        if marker in simple_escapes:
            decoded.append(simple_escapes[marker])
            index += 1
            continue
        if marker == "u":
            while index < len(value) and value[index] == "u":
                index += 1
            code_unit = value[index : index + 4]
            if len(code_unit) != 4 or re.fullmatch(r"[0-9A-Fa-f]{4}", code_unit) is None:
                return None
            decoded.append(chr(int(code_unit, 16)))
            index += 4
            continue
        if marker in "01234567":
            maximum_digits = 3 if marker in "0123" else 2
            end = index + 1
            while end < len(value) and end - index < maximum_digits and value[end] in "01234567":
                end += 1
            decoded.append(chr(int(value[index:end], 8)))
            index = end
            continue
        return None
    return "".join(decoded)


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
    type_analysis: _JavaTypeAnalysis,
) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    kafka_template_names = _java_kafka_template_names(_mask_java_non_code(file.content))
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
        claims.extend(_route_dto_claims(path, route, type_analysis))
        claims.extend(_route_call_claims(path, route))
        claims.extend(_route_exception_claims(path, route))
        claims.extend(_route_kafka_claims(path, route, kafka_template_names))
    return claims


def _route_dto_claims(
    source_path: str,
    route: _JavaRoute,
    type_analysis: _JavaTypeAnalysis,
) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    parameter_types = _parameter_types(route.parameters)
    for dto_type in parameter_types:
        claims.extend(
            _dto_field_claims(
                source_path,
                route.operation_ref,
                "request",
                dto_type,
                type_analysis,
            )
        )
    return_type = _response_dto_type(route.return_type)
    if return_type is not None:
        claims.extend(
            _dto_field_claims(
                source_path,
                route.operation_ref,
                "response",
                return_type,
                type_analysis,
            )
        )
    return claims


def _dto_field_claims(
    source_path: str,
    operation_ref: str,
    direction: Literal["request", "response"],
    dto_type: str,
    type_analysis: _JavaTypeAnalysis,
) -> list[JavaEvidenceClaim]:
    if dto_type in {
        *type_analysis.unresolved_json_naming_types,
        *type_analysis.unresolved_json_property_types,
    }:
        return []
    claims: list[JavaEvidenceClaim] = []
    for (
        field_name,
        field_type,
        validation_annotations,
        _column_name,
        _column_name_unresolved,
        json_access,
        serialized_name,
        _serialized_name_unresolved,
    ) in type_analysis.fields.get(dto_type, []):
        if not _jackson_access_allows(json_access, direction):
            continue
        evidence_name = serialized_name or field_name
        claims.append(
            JavaDtoFieldClaim(
                id=_claim_id("dto", operation_ref, direction, dto_type, evidence_name),
                source_path=source_path,
                operation_ref=operation_ref,
                direction=direction,
                dto_type=dto_type,
                field_name=evidence_name,
                java_field_name=field_name,
                field_type=field_type,
                confidence=0.9,
                deterministic=True,
            )
        )
        claims.extend(
            JavaBeanValidationClaim(
                id=_claim_id(
                    "validation",
                    operation_ref,
                    dto_type,
                    evidence_name,
                    annotation,
                    arguments,
                ),
                source_path=source_path,
                operation_ref=operation_ref,
                dto_type=dto_type,
                field_name=evidence_name,
                annotation=annotation,
                constraint=(arguments or "present")[:500],
                confidence=0.9,
                deterministic=True,
            )
            for annotation, arguments in validation_annotations
        )
        enum_definition = type_analysis.enums.get(_simple_type(field_type))
        if enum_definition is not None:
            claims.append(
                JavaEnumStateClaim(
                    id=_claim_id(
                        "enum-route",
                        operation_ref,
                        direction,
                        dto_type,
                        evidence_name,
                        enum_definition.enum_ref,
                    ),
                    source_path=enum_definition.source_path,
                    operation_ref=operation_ref,
                    enum_ref=enum_definition.enum_ref,
                    direction=direction,
                    dto_type=dto_type,
                    field_name=evidence_name,
                    java_field_name=field_name,
                    values=list(enum_definition.values),
                    confidence=0.8,
                    deterministic=enum_definition.deterministic,
                )
            )
    return claims


def _jackson_access_allows(
    access: JavaJsonAccess,
    direction: Literal["request", "response"],
) -> bool:
    if access == "write_only":
        return direction == "request"
    if access == "read_only":
        return direction == "response"
    return True


def _parameter_types(parameters: str) -> list[str]:
    declarations = _java_parameter_declarations(parameters)
    if declarations is None:
        return []
    return [
        _request_dto_type(parameter.declared_type)
        for parameter in declarations
        if not _java_parameter_is_transport_only(parameter)
    ]


def _java_parameter_declarations(parameters: str) -> list[_JavaParameter] | None:
    if not parameters.strip():
        return []
    declarations: list[_JavaParameter] = []
    for parameter in _split_top_level_java_components(parameters):
        annotations = frozenset(
            match.group(1).rsplit(".", 1)[-1]
            for match in re.finditer(r"@([A-Za-z_$][A-Za-z0-9_$.]*)", parameter)
        )
        masked = _mask_java_annotation_arguments(parameter)
        cleaned = re.sub(r"@[A-Za-z_$][A-Za-z0-9_$.]*", " ", masked).strip()
        declaration = re.fullmatch(
            r"(?:final\s+)*(?P<type>.+?)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
            r"(?P<array>(?:\s*\[\])*)",
            cleaned,
            re.DOTALL,
        )
        if declaration is None:
            return None
        declared_type = declaration.group("type").strip()
        if declaration.group("array"):
            declared_type += re.sub(r"\s+", "", declaration.group("array"))
        declarations.append(
            _JavaParameter(
                declared_type=declared_type,
                name=declaration.group("name"),
                annotations=annotations,
            )
        )
    return declarations


def _normalized_java_declared_type(value: str) -> str:
    simplified = re.sub(
        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+",
        lambda match: match.group(0).rsplit(".", 1)[-1],
        value,
    )
    return re.sub(r"\s+", "", simplified.replace("...", "[]"))


def _java_parameter_is_transport_only(parameter: _JavaParameter) -> bool:
    if parameter.annotations.intersection(_TRANSPORT_ONLY_PARAMETER_ANNOTATIONS):
        return True
    return _outer_java_type(parameter.declared_type) in _TRANSPORT_ONLY_PARAMETER_TYPES


def _request_dto_type(value: str) -> str:
    current = value.strip()
    for _depth in range(10):
        outer_type = _outer_java_type(current)
        if outer_type not in _REQUEST_COLLECTION_TYPES:
            return outer_type
        opening = current.find("<")
        closing = current.rfind(">")
        if opening < 0 or closing < opening:
            return outer_type
        arguments = _split_top_level_java_components(current[opening + 1 : closing])
        if len(arguments) != 1:
            return outer_type
        current = arguments[0].strip()
        if current.startswith("?"):
            bounded = re.fullmatch(r"\?\s+extends\s+(.+)", current, re.DOTALL)
            if bounded is None:
                return outer_type
            current = bounded.group(1).strip()
    return _outer_java_type(current)


def _response_dto_type(value: str) -> str | None:
    current = value.strip()
    for _depth in range(10):
        outer_type = _outer_java_type(current)
        opening = current.find("<")
        closing = current.rfind(">")
        if opening < 0 or closing < opening:
            return outer_type
        arguments = _split_top_level_java_components(current[opening + 1 : closing])
        if outer_type in _RESPONSE_SINGLE_VALUE_CONTAINERS and len(arguments) == 1:
            current = arguments[0].strip()
        elif outer_type in _RESPONSE_MAP_CONTAINERS and len(arguments) == 2:
            current = arguments[1].strip()
        else:
            return None
        if current.startswith("?"):
            bounded = re.fullmatch(r"\?\s+extends\s+(.+)", current, re.DOTALL)
            if bounded is None:
                return None
            current = bounded.group(1).strip()
    return None


def _outer_java_type(value: str) -> str:
    declaration = value.replace("...", " ").split("<", 1)[0].rstrip("[] ")
    identifiers = re.findall(
        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*",
        declaration,
    )
    return identifiers[-1].rsplit(".", 1)[-1] if identifiers else declaration


def _simple_type(value: str) -> str:
    identifiers = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*", value)
    return identifiers[-1].rsplit(".", 1)[-1] if identifiers else value.rstrip("[]")


def _route_call_claims(source_path: str, route: _JavaRoute) -> list[JavaEvidenceClaim]:
    claims: list[JavaEvidenceClaim] = []
    for call in _SERVICE_CALL.finditer(_mask_java_non_code(route.body)):
        target = call.group("target")
        method = call.group("method")
        normalized_target = target.lower()
        declared_type = route.call_target_types.get(target)
        kind = (
            _java_call_kind_from_declared_type(declared_type) if declared_type is not None else None
        )
        if kind is None and normalized_target.endswith("client"):
            kind = "feign_call"
        elif kind is None and normalized_target.endswith(("service", "repository", "mapper")):
            kind = "service_call"
        if kind is None:
            continue
        callee_target = declared_type or target
        claims.append(
            JavaCallClaim(
                id=_claim_id(kind, route.operation_ref, callee_target, method),
                kind=kind,
                source_path=source_path,
                operation_ref=route.operation_ref,
                caller_ref=f"{route.controller_ref}.{route.handler}",
                callee_ref=f"java://{callee_target}.{method}",
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


def _route_kafka_claims(
    source_path: str,
    route: _JavaRoute,
    kafka_template_names: frozenset[str],
) -> list[JavaEvidenceClaim]:
    masked_body = _mask_java_non_code(route.body)
    matches = [
        parsed
        for marker in _java_kafka_send_markers(masked_body, kafka_template_names)
        if (parsed := _KAFKA_SEND.match(route.body, marker.start())) is not None
    ]
    produced: list[JavaEvidenceClaim] = []
    for match in matches:
        topic = _decode_java_string_literal(match.group("topic"))
        if topic is None or _java_has_runtime_expression(topic):
            continue
        produced.append(
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
        )
    return produced


def _structural_java_claims(
    file: JavaSourceFileSnapshot,
    routes: list[_JavaRoute],
    type_fields: dict[str, list[JavaField]],
    property_access_types: tuple[str, ...],
    string_constants: _JavaStringConstants,
) -> tuple[list[JavaEvidenceClaim], bool, tuple[str, ...]]:
    claims: list[JavaEvidenceClaim] = []
    truncated = False
    unresolved_tables: set[str] = set()
    masked_content = _mask_java_non_code(file.content)
    declarations = list(_TYPE_DECLARATION.finditer(masked_content))
    top_level_prefixes = _top_level_declaration_prefixes(file.content, masked_content)
    top_level_starts = set(top_level_prefixes)
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
            and (
                _is_entity_type(file.path, name)
                or _has_jpa_entity_annotation(
                    file.content,
                    masked_content,
                    top_level_prefixes[declaration.start()],
                    declaration.start(),
                )
            )
        ):
            table_ref = _java_entity_table_ref(
                file.content,
                masked_content,
                top_level_prefixes[declaration.start()],
                declaration.start(),
                fallback_name=_snake_case(name),
                string_constants=string_constants,
                enclosing_type=name,
            )
            if table_ref is None:
                unresolved_tables.add(source_path)
                operation_refs: list[str] = []
            else:
                table_name = table_ref.rsplit("/", 1)[-1]
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
                    table_ref=table_ref,
                    operation_refs=operation_refs,
                    confidence=0.65,
                    deterministic=False,
                )
            )
            if table_ref is not None and name not in property_access_types:
                claims.extend(
                    JavaTableColumnClaim(
                        id=_claim_id("column", source_path, name, field_name),
                        source_path=source_path,
                        entity_ref=_java_structural_ref("entity", source_path, name),
                        table_ref=table_ref,
                        field_name=field_name,
                        column_name=column_name or _snake_case(field_name),
                        confidence=0.65,
                        deterministic=False,
                    )
                    for (
                        field_name,
                        _field_type,
                        _annotations,
                        column_name,
                        column_name_unresolved,
                        _json_access,
                        _serialized_name,
                        _serialized_name_unresolved,
                    ) in type_fields.get(name, [])
                    if not column_name_unresolved
                )
        if kind == "enum":
            values, values_truncated, serialization_unresolved = _enum_values(
                _type_body(file.content, declaration.end()),
                string_constants,
                name,
            )
            truncated = truncated or values_truncated
            if values and not serialization_unresolved:
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
    claims.extend(_listener_claims(file, string_constants))
    return claims, truncated, tuple(sorted(unresolved_tables))


def _top_level_declaration_prefixes(content: str, masked_content: str) -> dict[int, int]:
    declarations = list(_TYPE_DECLARATION.finditer(_mask_nested_java_blocks(masked_content)))
    prefixes: dict[int, int] = {}
    prefix_start = 0
    for declaration in declarations:
        prefixes[declaration.start()] = prefix_start
        opening = masked_content.find("{", declaration.end())
        if opening >= 0:
            prefix_start = _matching_brace(content, opening) + 1
    return prefixes


def _has_jpa_entity_annotation(
    content: str,
    masked_content: str,
    start: int,
    end: int,
) -> bool:
    return bool(
        _active_java_annotation_matches(
            content,
            masked_content,
            _JPA_ENTITY_ANNOTATION_MARKER,
            _JPA_ENTITY_ANNOTATION,
            start=start,
            end=end,
        )
    )


def _java_entity_table_ref(
    content: str,
    masked_content: str,
    start: int,
    end: int,
    *,
    fallback_name: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> str | None:
    matches = _active_java_annotation_matches(
        content,
        masked_content,
        _JPA_TABLE_ANNOTATION_MARKER,
        _JPA_TABLE_ANNOTATION,
        start=start,
        end=end,
    )
    if not matches:
        return f"table://{fallback_name}"
    arguments = _java_annotation_arguments(content, matches[-1].end())
    table_name_present, resolved_table_name = _java_named_string_argument(
        arguments,
        "name",
        string_constants,
        enclosing_type,
    )
    if table_name_present and resolved_table_name is None:
        return None
    table_name = resolved_table_name or fallback_name
    schema_name_present, schema_name = _java_named_string_argument(
        arguments,
        "schema",
        string_constants,
        enclosing_type,
    )
    if schema_name_present and schema_name is None:
        return None
    if schema_name is not None:
        return f"table://{schema_name}/{table_name}"
    return f"table://{table_name}"


def _java_named_string_argument(
    arguments: str,
    name: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> tuple[bool, str | None]:
    inner = arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    assignment = re.search(rf"\b{re.escape(name)}\s*=", _mask_java_non_code(inner))
    if assignment is None:
        return False, None
    expression = _java_annotation_expression(
        inner,
        assignment.end(),
        allow_identifier=True,
    )
    value = _java_string_expression_value(expression, string_constants, enclosing_type)
    if value is None or re.fullmatch(_IDENTIFIER, value) is None:
        return True, None
    return True, value


def _is_entity_type(path: str, name: str) -> bool:
    lowered = path.lower()
    return "/domain/" in lowered or "/entity/" in lowered or name.endswith("Entity")


def _enum_values(
    body: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> tuple[list[str], bool, bool]:
    masked_body = _mask_java_non_code(body)
    serialization_unresolved = bool(
        _active_java_annotation_matches(
            body,
            masked_body,
            _JACKSON_VALUE_ANNOTATION_MARKER,
            _JACKSON_VALUE_ANNOTATION,
        )
    )
    header = _top_level_java_prefix(body, ";")
    values: list[str] = []
    for component in _split_top_level_java_components(header):
        component_start = _java_leading_annotations_end(component)
        match = re.match(
            r"\s*(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\b",
            _mask_java_non_code(component)[component_start:],
        )
        if match is not None:
            annotation_prefix = component[:component_start]
            property_present, serialized_name = _jackson_enum_property_value(
                annotation_prefix,
                _mask_java_non_code(annotation_prefix),
                string_constants,
                enclosing_type,
            )
            serialization_unresolved = serialization_unresolved or (
                property_present and serialized_name is None
            )
            values.append(serialized_name or match.group("name"))
    return values[:100], len(values) > 100, serialization_unresolved


def _jackson_enum_property_value(
    content: str,
    masked_content: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> tuple[bool, str | None]:
    matches = _active_java_annotation_matches(
        content,
        masked_content,
        _JACKSON_PROPERTY_ANNOTATION_MARKER,
        _JACKSON_PROPERTY_ANNOTATION,
    )
    if not matches:
        return False, None
    arguments = _java_annotation_arguments(content, matches[-1].end())
    inner = arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    if not inner.strip():
        return False, None
    assignment = re.search(r"\bvalue\s*=", _mask_java_non_code(inner))
    if assignment is not None:
        expression = _java_annotation_expression(inner, assignment.end(), allow_identifier=True)
        return True, _java_string_expression_value(
            expression,
            string_constants,
            enclosing_type,
        )
    if re.search(r"\b[A-Za-z_$][A-Za-z0-9_$]*\s*=", _mask_java_non_code(inner)):
        return False, None
    expression = _java_annotation_expression(inner, 0, allow_identifier=True)
    return True, _java_string_expression_value(expression, string_constants, enclosing_type)


def _java_leading_annotations_end(content: str) -> int:
    masked_content = _mask_java_non_code(content)
    index = 0
    while True:
        while index < len(masked_content) and masked_content[index].isspace():
            index += 1
        annotation = re.match(r"@[A-Za-z_$][A-Za-z0-9_$.]*", masked_content[index:])
        if annotation is None:
            return index
        index += annotation.end()
        while index < len(masked_content) and masked_content[index].isspace():
            index += 1
        if index < len(masked_content) and masked_content[index] == "(":
            index = _matching_parenthesis(content, index) + 1


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


def _listener_claims(
    file: JavaSourceFileSnapshot,
    string_constants: _JavaStringConstants,
) -> list[JavaEvidenceClaim]:
    masked_content = _mask_java_non_code(file.content)
    matches = _active_java_annotation_matches(
        file.content,
        masked_content,
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
        for topic in _kafka_listener_topics(
            _java_annotation_arguments(file.content, match.end()),
            string_constants,
            _java_enclosing_top_level_type(file, masked_content, match.start()),
        )
    ]


def _kafka_listener_topics(
    arguments: str,
    string_constants: _JavaStringConstants,
    enclosing_type: str,
) -> list[str]:
    content = (
        arguments[1:-1] if arguments.startswith("(") and arguments.endswith(")") else arguments
    )
    named = re.search(r"\btopics\s*=", _mask_java_non_code(content))
    expression = (
        _java_annotation_expression(content, named.end(), allow_identifier=True)
        if named is not None
        else _java_annotation_expression(content, 0, allow_identifier=True)
    )
    return list(
        dict.fromkeys(_java_mapping_path_values(expression, string_constants, enclosing_type))
    )


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
        "enum_state": 8,
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
    limited = bounded[:MAX_ADAPTER_CLAIMS]
    route_refs = {
        claim.operation_ref for claim in limited if isinstance(claim, JavaControllerRouteClaim)
    }
    retained = [
        adjusted
        for claim in limited
        if (adjusted := _claim_with_retained_routes(claim, route_refs)) is not None
    ]
    return retained, len(retained) < len(unique)


def _claim_with_retained_routes(
    claim: JavaEvidenceClaim,
    retained_routes: set[str],
) -> JavaEvidenceClaim | None:
    if isinstance(claim, JavaEntityClaim):
        return claim.model_copy(
            update={
                "operation_refs": [
                    reference for reference in claim.operation_refs if reference in retained_routes
                ]
            }
        )
    if (
        isinstance(
            claim,
            (
                JavaDtoFieldClaim,
                JavaBeanValidationClaim,
                JavaCallClaim,
                JavaPersistenceClaim,
                JavaEnumStateClaim,
                JavaExceptionClaim,
                JavaKafkaEventClaim,
            ),
        )
        and claim.operation_ref is not None
    ):
        return claim if claim.operation_ref in retained_routes else None
    return claim


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
