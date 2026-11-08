"""An unrelated CLI bootstrap rotation must not revoke the product H's own actor."""

import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

from httpx import ASGITransport
from test_selftest_native_api_security import SecurityWorld, login, payload
from test_selftest_native_api_security import world as world

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.io import PublicAPI
from scripts.selftest.product_setup import _dedicated_mcp_identity

from app.core.config import settings
from app.main import app


async def test_product_mcp_account_survives_rotation_of_independent_cli_account(
    world: SecurityWorld, tmp_path: Path
) -> None:
    administrator = await login(world.client, settings.bootstrap_admin_email)
    generic = payload(
        await world.client.post(
            f"/api/v1/organizations/{world.organization}/service-accounts",
            headers=administrator,
            json={"name": "独立CLI身份", "account_key": "isolated-cli", "scopes": ["mcp:read"]},
        ),
        201,
    )
    user = PublicAPI(
        "http://test",
        administrator["Authorization"].removeprefix("Bearer "),
        world.organization,
        transport=ASGITransport(app=app),
    )
    try:
        product_id, product_token = await _dedicated_mcp_identity(
            user, UUID(world.organization), tmp_path
        )
    finally:
        await user.close()
    assert str(product_id) != generic["id"]
    receipt = (tmp_path / "mcp-account-receipt.json").read_text()
    assert product_token not in receipt and generic["token"] not in receipt
    assert (tmp_path / "mcp-account-receipt.json").stat().st_mode & 0o077 == 0
    response = await world.client.post(
        f"/api/v1/organizations/{world.organization}/service-accounts/{generic['id']}/rotate",
        headers=administrator,
    )
    payload(response, 200)
    old = await world.client.post(
        "/api/v1/mcp/connection",
        headers={"Authorization": "Bearer " + generic["token"]},
        json={},
    )
    assert old.status_code == 401
    product = payload(
        await world.client.post(
            "/api/v1/mcp/connection",
            headers={"Authorization": "Bearer " + product_token},
            json={},
        ),
        200,
    )
    assert product["service_account_id"] == str(product_id)


async def test_target_cleanup_actor_is_project_editor_and_never_admin_or_observer(
    world: SecurityWorld, tmp_path: Path, monkeypatch: object
) -> None:
    from scripts.selftest import bootstrap as bootstrap_module
    from scripts.selftest import product_target_identity as identity_module
    from scripts.selftest.bootstrap_journal import BootstrapJournal

    administrator = await login(world.client, settings.bootstrap_admin_email)
    token = administrator["Authorization"].removeprefix("Bearer ")
    real_api = PublicAPI

    def api_factory(
        base_url: str, credential: str = "", organization: str | None = None, **options: object
    ) -> PublicAPI:
        return real_api(base_url, credential, organization, transport=ASGITransport(app=app))

    monkeypatch.setattr(bootstrap_module, "PublicAPI", api_factory)
    monkeypatch.setattr(identity_module, "PublicAPI", api_factory)
    api = api_factory("http://test", token, world.organization)
    try:
        for _ in range(2):
            editor_token = await identity_module.target_cleanup_identity(
                api,
                "http://test",
                project=UUID(world.project),
                organization=UUID(world.organization),
                nonce="7" * 32,
                initial_password="Cleanup-" + "x" * 40,
                directory=tmp_path,
                journal=BootstrapJournal(tmp_path, "7" * 32),
            )
        receipt = (tmp_path / "target-cleanup-identity.json").read_text()
        assert editor_token not in receipt and token not in receipt
        assert (tmp_path / "target-cleanup-identity.json").stat().st_mode & 0o077 == 0
        actor = api_factory("http://test", editor_token, world.organization)
        try:
            me = await actor.object("GET", "/auth/me")
            assert me["is_system_admin"] is False
            permissions = await actor.object("GET", f"/projects/{world.project}/permissions")
            assert permissions["effective_role"] == "editor"
            resource = await api.object(
                "POST",
                f"/projects/{world.project}/environments",
                {
                    "name": "owned-cleanup-test",
                    "base_url": "https://owned.invalid",
                    "classification": "test",
                },
            )
            assert datetime.fromisoformat(resource["created_at"]).tzinfo is not None
            await actor.request(
                "DELETE", f"/projects/{world.project}/environments/{resource['id']}"
            )
            unrelated = await api.object("POST", "/projects", {"name": "foreign cleanup project"})
            foreign = await api.object(
                "POST",
                f"/projects/{unrelated['id']}/environments",
                {
                    "name": "foreign-resource",
                    "base_url": "https://foreign.invalid",
                    "classification": "test",
                },
            )
            blocked = await actor.request(
                "DELETE",
                f"/projects/{unrelated['id']}/environments/{foreign['id']}",
                allow_status=(403, 404),
            )
            assert blocked["error"]["code"]
            rows = await api.request("GET", f"/projects/{unrelated['id']}/environments")
            assert foreign["id"] in {item["id"] for item in rows}
            denied = await actor.request(
                "POST",
                "/users",
                {
                    "email": "must-deny@example.com",
                    "password": "Deny-Password123",
                    "display_name": "denied",
                },
                allow_status=(403,),
            )
            assert denied["error"]["code"]
        finally:
            await actor.close()
    finally:
        await api.close()
