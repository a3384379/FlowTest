from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.tenant import OrganizationRole


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, min_length=1, max_length=80)
    description: str = Field(default="", max_length=4000)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str
    enabled: bool
    created_by_id: UUID | None
    role: OrganizationRole | None = None
    member_count: int | None = None
    created_at: datetime
    updated_at: datetime


class OrganizationMemberUpsert(BaseModel):
    user_id: UUID
    role: OrganizationRole


class OrganizationMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    role: OrganizationRole
    created_at: datetime
    updated_at: datetime


class ServiceAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    account_key: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=list, max_length=50)
    expires_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict, max_length=50)


class ServiceAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    account_key: str
    token_prefix: str
    scopes: list[str]
    enabled: bool
    created_by_id: UUID
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    metadata_json: dict[str, str]
    created_at: datetime
    updated_at: datetime


class ServiceAccountIssuedResponse(ServiceAccountResponse):
    token: str
