"""An ordinary B project editor for H recovery, never shared with model or O."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import _user, login
from scripts.selftest.bootstrap_journal import BootstrapJournal
from scripts.selftest.io import HarnessError, PublicAPI, write_json


async def target_cleanup_identity(
    administrator: PublicAPI,
    base_url: str,
    *,
    project: UUID,
    organization: UUID,
    nonce: str,
    initial_password: str,
    directory: Path,
    journal: BootstrapJournal,
) -> str:
    email = f"h-target-cleanup-{nonce[:12]}@example.com"
    initial = initial_password
    user = await _user(administrator, email, initial, journal, "product_target_cleanup")
    await administrator.object(
        "PUT",
        f"/organizations/{organization}/members/{user}",
        {"user_id": user, "role": "member"},
    )
    await administrator.object(
        "PUT",
        f"/projects/{project}/members/{user}",
        {"user_id": user, "role": "editor"},
    )
    token, _ = await login(base_url, email, initial)
    actor = PublicAPI(base_url, token, str(organization))
    try:
        profile = await actor.object("GET", "/auth/me")
        permissions = await actor.object("GET", f"/projects/{project}/permissions")
        if (
            profile.get("id") != user
            or profile.get("is_system_admin") is not False
            or permissions.get("effective_role") != "editor"
        ):
            raise HarnessError("SELFTEST_TARGET_CLEANUP_IDENTITY_INVALID")
    finally:
        await actor.close()
    write_json(
        directory / "target-cleanup-identity.json",
        {
            "user_id": user,
            "project_id": str(project),
            "organization_id": str(organization),
            "effective_role": "editor",
            "is_system_admin": False,
            "issued_at": datetime.now(UTC).isoformat(),
            "assigned_to": "harness_only",
            "authority": "exact_owned_resource_recovery",
        },
    )
    return token
