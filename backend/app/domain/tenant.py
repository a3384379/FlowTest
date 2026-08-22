"""Pure tenant and organization authorization contracts."""

from enum import StrEnum
from uuid import UUID


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

    @property
    def capabilities(self) -> frozenset[str]:
        if self is OrganizationRole.OWNER:
            return frozenset(
                {"read", "create_project", "manage_members", "manage_service_accounts"}
            )
        if self is OrganizationRole.ADMIN:
            return frozenset(
                {"read", "create_project", "manage_members", "manage_service_accounts"}
            )
        if self is OrganizationRole.MEMBER:
            return frozenset({"read", "create_project"})
        return frozenset({"read"})

    def allows(self, capability: str) -> bool:
        return capability in self.capabilities


class TenantContext:
    """The organization boundary for one authenticated application call."""

    __slots__ = (
        "actor_id",
        "is_system_admin",
        "organization_id",
        "role",
        "scopes",
        "service_account_id",
    )

    def __init__(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        role: OrganizationRole | None,
        is_system_admin: bool = False,
        service_account_id: UUID | None = None,
        scopes: frozenset[str] = frozenset(),
    ) -> None:
        self.organization_id = organization_id
        self.actor_id = actor_id
        self.role = role
        self.is_system_admin = is_system_admin
        self.service_account_id = service_account_id
        self.scopes = scopes

    def allows(self, capability: str) -> bool:
        if self.is_system_admin:
            return True
        if capability in self.scopes:
            return True
        return self.role is not None and self.role.allows(capability)
