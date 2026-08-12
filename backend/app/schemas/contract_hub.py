from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from app.domain.contract_hub import ReleaseVersion, ServiceDisplayName, ServiceKey

Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ServiceCatalogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_key: ServiceKey
    display_name: ServiceDisplayName
    description: Description = ""


class ServiceCatalogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    service_key: str
    display_name: str
    description: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class PactBrokerImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consumer: ServiceDisplayName
    provider: ServiceDisplayName
    consumer_version: ReleaseVersion


class PactContractResponse(BaseModel):
    id: UUID
    project_id: UUID
    consumer_service_id: UUID
    consumer_name: str
    provider_service_id: UUID
    provider_name: str
    consumer_version: str
    pact_specification_version: str
    source_type: Literal["upload", "broker"]
    source_name: str
    content_sha256: str
    interaction_count: int
    created_by_id: UUID
    created_at: datetime


class ProviderVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_version: ReleaseVersion
    target_base_url: str = Field(
        min_length=8,
        max_length=2048,
        pattern=r"^https?://[^\s]+$",
    )


class ProviderVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    pact_contract_version_id: UUID
    provider_version: str
    target_base_url: str
    status: Literal["passed", "failed"]
    interaction_count: int
    passed_count: int
    failed_count: int
    results: list[dict[str, JsonValue]]
    verified_by_id: UUID
    created_at: datetime


class ContractHubSummaryResponse(BaseModel):
    service_count: int
    openapi_contract_count: int
    pact_contract_count: int
    pending_verification_count: int
    failed_verification_count: int
    breaking_change_count: int
    broker_available: bool


class ServiceGraphNode(BaseModel):
    id: UUID
    service_key: str
    display_name: str
    contract_kinds: list[Literal["openapi", "pact"]]


class ServiceGraphEdge(BaseModel):
    consumer_service_id: UUID
    provider_service_id: UUID
    pact_contract_count: int
    latest_consumer_version: str
    latest_status: Literal["passed", "failed", "pending"]


class ServiceGraphResponse(BaseModel):
    nodes: list[ServiceGraphNode]
    edges: list[ServiceGraphEdge]


class CompatibilityCell(BaseModel):
    provider_version: str
    status: Literal["passed", "failed", "pending"]
    verification_id: UUID | None
    verified_at: datetime | None


class CompatibilityRow(BaseModel):
    pact_contract_version_id: UUID
    consumer_service_id: UUID
    consumer_name: str
    consumer_version: str
    cells: list[CompatibilityCell]


class CompatibilityMatrixResponse(BaseModel):
    provider_service_id: UUID
    provider_name: str
    provider_versions: list[str]
    rows: list[CompatibilityRow]


class DeploymentCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_service_id: UUID
    provider_version: ReleaseVersion


class DeploymentCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    provider_service_id: UUID
    provider_version: str
    decision: Literal["safe", "unsafe", "unknown"]
    evidence: dict[str, JsonValue]
    checked_by_id: UUID
    created_at: datetime
