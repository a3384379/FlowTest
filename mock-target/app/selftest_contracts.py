"""Bounded contracts for explicitly enabled synthetic self-test fixtures."""

import json
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

FixtureKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SYNTHETIC_FILE_BYTES: Final = b"flowtest-download"
CookieStage = Literal["set", "barrier", "check"]
FixtureOperation = Literal[
    "request", "sequence", "download", "upload", "cookie/set", "cookie/barrier", "cookie/check"
]


class SyntheticCookieSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    stage: CookieStage
    value: Literal["left", "right"] | None


class BinaryResponseSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    size_bytes: int = Field(ge=1, le=4096)
    sha256: Digest
    content_type: Literal["application/octet-stream"]
    filename: Literal["flowtest.bin"]


class SyntheticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    marker: str = Field(default="", max_length=160)
    value: JsonValue = None
    branch: str = Field(default="", max_length=80)
    iteration_key: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def bounded_value(self) -> "SyntheticRequest":
        validate_synthetic_value(self.value)
        return self


class FixtureResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actual: int = Field(default=1, ge=-1_000_000, le=1_000_000)
    code: int = Field(default=0, ge=-1_000_000, le=1_000_000)
    value: JsonValue = None

    @model_validator(mode="after")
    def bounded_value(self) -> "FixtureResponseBody":
        validate_synthetic_value(self.value)
        return self


class BudgetScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    parent_batch_key: FixtureKey
    nonce: str = Field(min_length=16, max_length=160)
    limit: int = Field(default=500, ge=1, le=500)
    expires_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class BudgetReceipt(BudgetScope):
    admitted_count: int = Field(ge=0, le=500)
    rejected_count: int = Field(ge=0)
    fixture_digest: Digest
    registration_epoch: str
    expires_at: float


class FixtureConfiguration(BaseModel):
    budget_scope: BudgetScope | None = None
    model_config = ConfigDict(extra="forbid", strict=True)

    nonce: str = Field(min_length=16, max_length=160)
    fixture_digest: Digest
    ttl_seconds: int = Field(default=600, ge=1, le=3600)
    max_entries: int = Field(default=500, ge=1, le=1000)
    max_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    response_statuses: list[Annotated[int, Field(ge=200, le=599)]] = Field(
        default_factory=lambda: [200], min_length=1, max_length=20
    )
    response_body: FixtureResponseBody = Field(default_factory=FixtureResponseBody)
    delay_ms: int = Field(default=0, ge=0, le=5000)

    @model_validator(mode="after")
    def require_json_response(self) -> "FixtureConfiguration":
        if any(status in {204, 205, 304} for status in self.response_statuses):
            raise ValueError("synthetic response statuses must permit a JSON body")
        return self


class FixtureRemovalCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_nonce: str = Field(min_length=16, max_length=160)
    expected_fixture_epoch: str = Field(min_length=1, max_length=200)
    expected_registration_epoch: str = Field(min_length=1, max_length=200)


class SyntheticResponse(FixtureResponseBody):
    marker: str
    branch: str
    iteration_key: str
    request_count: int = Field(ge=1)
    fixture_epoch: str


class SyntheticHeaderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: Literal["project", "environment", "api", "case", "runtime", "node"] | None = None
    count: int = Field(default=0, ge=0, le=100)


class JournalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sequence: int = Field(ge=1)
    method: str
    path: str
    response_status: int
    marker: str
    request_body: SyntheticRequest
    response_body: SyntheticResponse | None
    binary_response: BinaryResponseSnapshot | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    authorization_present: bool
    cookie_present: bool
    fixture_epoch: str
    received_at: float
    synthetic_precedence_header: SyntheticHeaderSnapshot | None = None
    synthetic_cookie: SyntheticCookieSnapshot | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    binary_request: BinaryResponseSnapshot | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def distinct_response_kind(self) -> "JournalEntry":
        if (self.response_body is None) == (self.binary_response is None):
            raise ValueError("exactly one JSON or binary response is required")
        return self


class FixtureRequestEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)
    sequence: int = Field(ge=1, le=10000)
    started_at: float
    completed_at: float | None = None
    outcome: Literal["completed", "cancelled", "failed"] | None = None
    active_at_begin: int = Field(ge=1, le=500)


class FixtureMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    events: list[FixtureRequestEvent] = Field(max_length=500)
    complete: bool
    active_count: int = Field(ge=0)
    peak_concurrency: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class FixtureJournal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    batch_key: FixtureKey
    scenario_id: FixtureKey
    nonce: str
    fixture_digest: Digest
    fixture_epoch: str
    registration_epoch: str
    request_count: int
    entries: list[JournalEntry] = Field(max_length=1000)
    truncated: bool
    expired: bool
    epoch_changed: bool
    next_sequence: int | None
    expires_at: float
    metrics: FixtureMetrics | None = None
    budget: BudgetReceipt | None = None


def validate_synthetic_value(value: JsonValue) -> None:
    """Bound the authorized synthetic value without inspecting or masking its content."""
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 4096:
        raise ValueError("synthetic value exceeds byte limit")
    remaining: list[tuple[JsonValue, int]] = [(value, 0)]
    count = 0
    while remaining:
        child, depth = remaining.pop()
        count += 1
        if depth > 6 or count > 128:
            raise ValueError("synthetic value exceeds structure limit")
        if isinstance(child, dict):
            remaining.extend((item, depth + 1) for item in child.values())
        elif isinstance(child, list):
            remaining.extend((item, depth + 1) for item in child)
