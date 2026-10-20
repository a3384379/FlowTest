"""Read-only routing candidates. These values never represent a saved revision."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PreviewServiceChange:
    service_id: UUID
    enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class PreviewEndpointChange:
    endpoint_id: UUID
    variant: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    variables: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class PreviewEnvironmentChange:
    environment_id: UUID
    service_id: UUID | None


@dataclass(frozen=True, slots=True)
class PreviewAPIChange:
    api_id: UUID
    service_id: UUID | None
    base_version: int | None = None


type PreviewChange = (
    PreviewServiceChange | PreviewEndpointChange | PreviewEnvironmentChange | PreviewAPIChange
)


@dataclass(frozen=True, slots=True)
class TargetPreviewCommand:
    change: PreviewChange
    environment_id: UUID | None = None
    api_id: UUID | None = None
    api_version: int | None = None
    service_override: str | None = None
    endpoint_variant: str = "default"


@dataclass(frozen=True, slots=True)
class PreviewResolutionError:
    code: str
    message: str
    trace_id: str
    details: None = None


@dataclass(frozen=True, slots=True)
class PreviewResolution:
    status: Literal["resolved", "unavailable"]
    url: str | None = None
    service_key: str | None = None
    endpoint_variant: str | None = None
    endpoint_revision: int | None = None
    api_version: int | None = None
    error: PreviewResolutionError | None = None


@dataclass(frozen=True, slots=True)
class TargetPreviewResult:
    before: PreviewResolution
    after: PreviewResolution
    persisted: Literal[False] = False
    network_checked: Literal[False] = False
