from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.domain.api_assets import AuthKind, BodyKind, HttpMethod, JsonValue
from app.domain.scopes import HeaderScope, VariableScope

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]


class ProjectConfigurationUpdate(BaseModel):
    variables: dict[VariableName, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class ProjectConfigurationResponse(ProjectConfigurationUpdate):
    project_id: UUID


class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_url: HttpUrl
    variables: dict[VariableName, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: HttpUrl | None = None
    variables: dict[VariableName, str] | None = None
    headers: dict[str, str] | None = None


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    base_url: str
    variables: dict[str, str]
    headers: dict[str, str]
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class SecretWrite(BaseModel):
    name: VariableName
    value: str = Field(min_length=1, max_length=65536)
    environment_id: UUID | None = None


class SecretMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    environment_id: UUID | None
    name: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class RequestParameter(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    value: str = Field(default="", max_length=65536)
    enabled: bool = True


class AuthConfiguration(BaseModel):
    kind: AuthKind = AuthKind.NONE
    values: dict[str, str] = Field(default_factory=dict)


class APIVersionInput(BaseModel):
    method: HttpMethod
    path: str = Field(min_length=1, max_length=2048)
    query_parameters: list[RequestParameter] = Field(default_factory=list, max_length=200)
    headers: dict[str, str] = Field(default_factory=dict)
    body_kind: BodyKind = BodyKind.NONE
    body: JsonValue = None
    auth: AuthConfiguration = Field(default_factory=AuthConfiguration)


class APIDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None
    request: APIVersionInput


class APIDefinitionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    folder_id: UUID | None = None


class APIVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    api_definition_id: UUID
    version: int
    method: HttpMethod
    path: str
    query_parameters: list[RequestParameter]
    headers: dict[str, str]
    body_kind: BodyKind
    body: JsonValue
    auth_kind: AuthKind
    auth_config: dict[str, str]
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class APIDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    folder_id: UUID | None
    name: str
    description: str
    current_version: int
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class APIDetailResponse(BaseModel):
    definition: APIDefinitionResponse
    version: APIVersionResponse


class PreviewRequest(BaseModel):
    environment_id: UUID
    runtime_variables: dict[VariableName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)
    body_override: JsonValue = None
    use_body_override: bool = False


class ResolvedHeaderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    value: str
    source: HeaderScope


class ResolvedVariableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    value: str
    source: VariableScope
    secret: bool = False


class PreviewResponse(BaseModel):
    method: HttpMethod
    url: str
    headers: list[ResolvedHeaderResponse]
    body: JsonValue
    variables: list[ResolvedVariableResponse]
