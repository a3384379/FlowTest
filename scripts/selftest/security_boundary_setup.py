"""Provision only fresh disposable ordinary actors through real native public APIs."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import httpx
from scripts.selftest.io import HarnessError, object_value, text_value
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.security_boundary_contracts import BoundaryIdentity
from scripts.selftest.security_boundary_http import BoundaryAPI


@dataclass(frozen=True, repr=False)
class SecurityActors:
    identity: BoundaryIdentity
    owner: BoundaryAPI
    editor: BoundaryAPI
    observer: BoundaryAPI
    anonymous: BoundaryAPI
    owner_token: str


async def _actor(admin: BoundaryAPI, batch: str, role: str) -> tuple[str, str, str]:
    email = f"{batch}-{role}@example.com"
    password = secrets.token_urlsafe(24) + "-Aa1!"
    actor = await admin.object(
        "POST",
        "/users",
        {
            "email": email,
            "display_name": f"{batch}-{role}",
            "password": password,
        },
    )
    login = await admin.object("POST", "/auth/login", {"email": email, "password": password})
    user = object_value(login["user"])
    if user["id"] != actor["id"] or user["is_system_admin"] is not False:
        raise HarnessError("SELFTEST_SECURITY_ORDINARY_ACTOR_REQUIRED")
    if user["requires_password_change"] is True:
        new_password = secrets.token_urlsafe(24) + "-Aa1!"
        changed = await admin.probe(
            "POST",
            "/auth/change-password",
            {"current_password": password, "new_password": new_password},
            access_token=text_value(login["access_token"]),
        )
        if changed.status_code != 204:
            raise HarnessError("SELFTEST_SECURITY_ACTOR_PASSWORD_CHANGE_FAILED")
        login = await admin.object(
            "POST", "/auth/login", {"email": email, "password": new_password}
        )
        user = object_value(login["user"])
    if (
        user["id"] != actor["id"]
        or user["is_system_admin"] is not False
        or user["requires_password_change"] is not False
    ):
        raise HarnessError("SELFTEST_SECURITY_ACTOR_LOGIN_NOT_READY")
    return text_value(actor["id"]), text_value(login["access_token"]), email


@asynccontextmanager
async def security_actors(
    binding: StackBinding,
    token: str,
    batch: str,
    budget: ProtocolHttpBudget,
    deadline: datetime,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[SecurityActors]:
    apis: list[BoundaryAPI] = []

    def api(access: str = "", organization: str | None = None) -> BoundaryAPI:
        value = BoundaryAPI(
            binding.target_url, budget, deadline, access, organization, transport=transport
        )
        apis.append(value)
        return value

    try:
        admin = api(token)
        roles = {role: await _actor(admin, batch, role) for role in ("owner", "editor", "observer")}
        organization = await admin.object(
            "POST",
            "/organizations",
            {
                "name": f"{batch}-隔离安全组织",
                "slug": batch.lower(),
            },
        )
        org = text_value(organization["id"])
        for actor_id, _, _ in roles.values():
            await admin.object(
                "PUT",
                f"/organizations/{org}/members/{actor_id}",
                {
                    "user_id": actor_id,
                    "role": "member",
                },
            )
        owner = api(roles["owner"][1], org)
        projects = []
        for mode in ("off", "on"):
            project = await owner.object(
                "POST",
                "/projects",
                {
                    "name": f"{batch}-{mode}",
                    "organization_id": org,
                },
            )
            projects.append(text_value(project["id"]))
        for project_id in projects:
            for role, project_role in (("editor", "editor"), ("observer", "viewer")):
                await owner.object(
                    "PUT",
                    f"/projects/{project_id}/members/{roles[role][0]}",
                    {
                        "user_id": roles[role][0],
                        "role": project_role,
                    },
                )
        identity = BoundaryIdentity(
            organization_id=UUID(org),
            project_ids=(UUID(projects[0]), UUID(projects[1])),
            owner_id=UUID(roles["owner"][0]),
            editor_id=UUID(roles["editor"][0]),
            observer_id=UUID(roles["observer"][0]),
        )
        yield SecurityActors(
            identity,
            owner,
            api(roles["editor"][1], org),
            api(roles["observer"][1], org),
            api(),
            roles["owner"][1],
        )
    finally:
        for value in apis:
            await value.close()


async def actor_permissions(
    api: BoundaryAPI,
    project: UUID,
    role: Literal["owner", "editor", "viewer"],
) -> tuple[UUID, bool, Literal["owner", "editor", "viewer"]]:
    me = await api.object("GET", "/auth/me")
    permission = await api.object("GET", f"/projects/{project}/permissions")
    if me["is_system_admin"] is not False or permission["effective_role"] != role:
        raise HarnessError("SELFTEST_SECURITY_ACTOR_ROLE_MISMATCH")
    return UUID(text_value(me["id"])), False, role
