from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

ServiceKey = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]
EndpointVariant = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=80)]


class ServiceCreate(BaseModel):
    service_key: ServiceKey
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    owner_team: str | None = Field(default=None, max_length=160)
    service_type: str = Field(default="http", pattern=r"^(http|https|grpc|graphql|other)$")
    enabled: bool = True


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    owner_team: str | None = Field(default=None, max_length=160)
    service_type: str | None = Field(default=None, pattern=r"^(http|https|grpc|graphql|other)$")
    enabled: bool | None = None


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    service_key: str
    name: str
    description: str
    owner_team: str | None
    service_type: str
    enabled: bool
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class ServiceEndpointCreate(BaseModel):
    service_id: UUID
    variant: EndpointVariant = "default"
    base_url: HttpUrl
    enabled: bool = True
    connect_timeout_ms: int = Field(default=5000, ge=100, le=300000)
    read_timeout_ms: int = Field(default=30000, ge=100, le=300000)
    tls_verify: bool = True
    proxy_ref: str | None = Field(default=None, max_length=255)
    headers: dict[str, str] = Field(default_factory=dict)
    variables: dict[str, str] = Field(default_factory=dict)
    secret_refs: list[str] = Field(default_factory=list, max_length=100)
    health_check_path: str | None = Field(default=None, max_length=2048)
    health_expected_status: int | None = Field(default=None, ge=100, le=599)


class ServiceEndpointUpdate(BaseModel):
    variant: EndpointVariant | None = None
    base_url: HttpUrl | None = None
    enabled: bool | None = None
    connect_timeout_ms: int | None = Field(default=None, ge=100, le=300000)
    read_timeout_ms: int | None = Field(default=None, ge=100, le=300000)
    tls_verify: bool | None = None
    proxy_ref: str | None = Field(default=None, max_length=255)
    headers: dict[str, str] | None = None
    variables: dict[str, str] | None = None
    secret_refs: list[str] | None = Field(default=None, max_length=100)
    health_check_path: str | None = Field(default=None, max_length=2048)
    health_expected_status: int | None = Field(default=None, ge=100, le=599)


class ServiceEndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    environment_id: UUID
    service_id: UUID
    variant: str
    base_url: str
    enabled: bool
    connect_timeout_ms: int
    read_timeout_ms: int
    tls_verify: bool
    proxy_ref: str | None
    headers: dict[str, str]
    variables: dict[str, str]
    secret_refs: list[str]
    health_check_path: str | None
    health_expected_status: int | None
    revision: int
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class ServiceEndpointConnectivityResponse(BaseModel):
    endpoint_id: UUID
    status: str
    dns: str
    http_status: int | None
    latency_ms: float | None
    redirect: bool
    error_code: str | None = None


class ServiceTargetImpactItem(BaseModel):
    id: UUID
    name: str
    reason: str


class ServiceTargetImpactPreviewResponse(BaseModel):
    strategy: str
    service_id: UUID
    service_key: str
    affected_apis: list[ServiceTargetImpactItem]
    affected_workflows: list[ServiceTargetImpactItem]
    affected_test_plans: list[ServiceTargetImpactItem]
    affected_scheduled_runs: list[ServiceTargetImpactItem]
    affected_release_gates: list[ServiceTargetImpactItem]
