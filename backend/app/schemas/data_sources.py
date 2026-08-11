from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.data_nodes import CredentialKind, CredentialSecretProvider

CredentialName = Annotated[str, Field(min_length=1, max_length=160)]
MockSlug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,79}$")]


class CredentialCreate(BaseModel):
    project_id: UUID
    name: CredentialName
    kind: CredentialKind
    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str = Field(default="", max_length=255)
    username: str = Field(default="", max_length=255)
    secret: str = Field(min_length=1, max_length=65536)
    secret_provider: CredentialSecretProvider = CredentialSecretProvider.LOCAL
    tls_enabled: bool = False

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "CredentialCreate":
        if self.kind is not CredentialKind.REDIS and not self.database_name.strip():
            raise ValueError("PostgreSQL/MySQL Credential 必须配置数据库名")
        return self


class CredentialUpdate(BaseModel):
    name: CredentialName | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    secret: str | None = Field(default=None, min_length=1, max_length=65536)
    tls_enabled: bool | None = None


class CredentialMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    kind: CredentialKind
    host: str
    port: int
    database_name: str
    username: str
    secret_provider: CredentialSecretProvider
    tls_enabled: bool
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class MockServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: MockSlug
    description: str = Field(default="", max_length=4000)


class MockServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    is_enabled: bool | None = None


class MockServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    slug: str
    description: str
    is_enabled: bool
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class MockRouteWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    method: str = Field(pattern=r"^(GET|POST|PUT|PATCH|DELETE)$")
    path_pattern: str = Field(min_length=1, max_length=1024)
    query_conditions: dict[str, str] = Field(default_factory=dict)
    header_conditions: dict[str, str] = Field(default_factory=dict)
    response_status: int = Field(default=200, ge=100, le=599)
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: JsonValue = None
    delay_ms: int = Field(default=0, ge=0, le=30000)
    scenario: str | None = Field(default=None, min_length=1, max_length=80)
    priority: int = Field(default=0, ge=-1000, le=1000)
    is_enabled: bool = True


class MockRouteResponse(MockRouteWrite):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mock_service_id: UUID
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class MockRequestLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mock_service_id: UUID
    mock_route_id: UUID | None
    method: str
    path: str
    query_parameters: dict[str, str]
    headers: dict[str, str]
    body: JsonValue
    matched: bool
    scenario: str | None
    response_status: int
    duration_ms: int
    created_at: datetime
