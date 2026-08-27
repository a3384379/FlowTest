from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.domain.api_assets import AuthKind, BodyKind, ExtractionKind, HttpMethod, JsonValue
from app.domain.assertions import AssertionKind, ComparisonOperator
from app.domain.scopes import HeaderScope, VariableScope
from app.domain.test_engineering import OperationContract

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]
APIDefinitionName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


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
    default_service_id: UUID | None = None
    variables: dict[VariableName, str] | None = None
    headers: dict[str, str] | None = None


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    base_url: str
    default_service_id: UUID | None
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


class ExtractionRuleInput(BaseModel):
    name: VariableName
    kind: ExtractionKind
    expression: str = Field(min_length=1, max_length=2048)


class APIVersionAssertionInput(BaseModel):
    kind: AssertionKind
    operator: ComparisonOperator = ComparisonOperator.EQUALS
    target: str | None = Field(default=None, max_length=2048)
    expected: JsonValue = None


class MultipartFileReference(BaseModel):
    field: str = Field(min_length=1, max_length=160)
    artifact_id: UUID


class MultipartBody(BaseModel):
    fields: dict[str, str] = Field(default_factory=dict)
    files: list[MultipartFileReference] = Field(default_factory=list, max_length=20)


class APIVersionInput(BaseModel):
    method: HttpMethod
    path: str = Field(min_length=1, max_length=2048)
    query_parameters: list[RequestParameter] = Field(default_factory=list, max_length=200)
    headers: dict[str, str] = Field(default_factory=dict)
    variables: dict[VariableName, str] = Field(default_factory=dict)
    body_kind: BodyKind = BodyKind.NONE
    body: JsonValue = None
    auth: AuthConfiguration = Field(default_factory=AuthConfiguration)
    extraction_rules: list[ExtractionRuleInput] = Field(default_factory=list, max_length=100)
    assertions: list[APIVersionAssertionInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_body_shape(self) -> "APIVersionInput":
        if self.body_kind is BodyKind.MULTIPART:
            MultipartBody.model_validate(self.body)
        return self


class APIDefinitionCreate(BaseModel):
    name: APIDefinitionName
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None
    service_id: UUID | None = None
    request: APIVersionInput


class APIDefinitionUpdate(BaseModel):
    name: APIDefinitionName | None = None
    description: str | None = Field(default=None, max_length=4000)
    folder_id: UUID | None = None
    service_id: UUID | None = None


class APIVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    api_definition_id: UUID
    version: int
    method: HttpMethod
    path: str
    query_parameters: list[RequestParameter]
    headers: dict[str, str]
    variables: dict[str, str]
    body_kind: BodyKind
    body: JsonValue
    auth_kind: AuthKind
    auth_config: dict[str, str]
    extraction_rules: list[ExtractionRuleInput]
    assertions: list[APIVersionAssertionInput]
    canonical_contract: OperationContract | None = None
    contract_fingerprint: str | None = None
    contract_completeness: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("canonical_contract", mode="before")
    @classmethod
    def normalize_empty_contract(cls, value: object) -> object:
        return None if value == {} else value


class APIDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    folder_id: UUID | None
    service_id: UUID | None
    name: str
    description: str
    current_version: int
    is_active: bool
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class APIDetailResponse(BaseModel):
    definition: APIDefinitionResponse
    version: APIVersionResponse


class PreviewRequest(BaseModel):
    environment_id: UUID
    service_override: str | None = Field(default=None, max_length=160)
    endpoint_variant: str | None = Field(default=None, max_length=80)
    version: int | None = Field(default=None, ge=1)
    runtime_variables: dict[VariableName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)
    query_parameters_override: list[RequestParameter] | None = Field(
        default=None,
        max_length=200,
    )
    headers_override: dict[str, str] | None = None
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
    target: dict[str, JsonValue] = Field(default_factory=dict)
