from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.access import ProjectCapability, ProjectRole, TeamGrantRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    is_active: bool
    is_system_admin: bool
    requires_password_change: bool
    oidc_provider: str | None
    oidc_subject: str | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    # The UI accepts the local Standalone alias ``admin`` as well as an email
    # address.  Keep the wire field named ``email`` for API compatibility.
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- OAuth token type identifier
    expires_in: int
    user: UserResponse


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- OAuth token type identifier
    expires_in: int


class OIDCStatusResponse(BaseModel):
    enabled: bool
    provider: str | None


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    is_system_admin: bool = False


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    is_system_admin: bool | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    created_by_id: UUID
    role: ProjectRole | None = None
    created_at: datetime
    updated_at: datetime


class ProjectPermissionResponse(BaseModel):
    effective_role: str
    capabilities: list[ProjectCapability]
    matrix: dict[str, list[ProjectCapability]]


class ProjectSecurityPolicy(BaseModel):
    allowed_hosts: list[str] = Field(default_factory=list, max_length=100)
    allowed_private_cidrs: list[str] = Field(default_factory=list, max_length=100)


class ProjectRetentionPolicy(BaseModel):
    retention_days: int = Field(ge=1, le=3650)
    maximum_days: int = Field(ge=30, le=3650)


class ProjectRetentionUpdate(BaseModel):
    retention_days: int = Field(ge=1, le=3650)


class ProjectCapacityPolicy(BaseModel):
    execution_concurrency_limit: int = Field(ge=1, le=500)
    queued_run_limit: int = Field(ge=1, le=5000)


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None
    project_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    details: dict[str, Any]
    created_at: datetime


class MemberUpsert(BaseModel):
    user_id: UUID
    role: ProjectRole


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    user_id: UUID
    role: ProjectRole
    created_at: datetime
    updated_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class TeamMemberWrite(BaseModel):
    user_id: UUID


class TeamMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class ProjectTeamGrantWrite(BaseModel):
    team_id: UUID
    role: TeamGrantRole


class ProjectTeamGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    team_id: UUID
    role: TeamGrantRole
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: UUID | None = None


class FolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    parent_id: UUID | None
    name: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
