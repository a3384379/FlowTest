"""Public owner/editor governance and observer export checks; no deployed acceptance claim."""

from __future__ import annotations

import copy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_selftest_auth_expiry import binding
from test_selftest_native_api_security import SecurityWorld, login
from test_selftest_native_api_security import world as world

from app.core.config import settings
from app.domain.runtime_profiles import RuntimeProfile
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.io import write_json  # noqa: E402
from scripts.selftest.security_boundaries import (  # noqa: E402
    execute_security_boundaries,
    finalize_security_boundaries,
)
from scripts.selftest.security_boundary_contracts import BoundaryResult  # noqa: E402
from scripts.selftest.verify_security_boundaries import verify_security_boundaries  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile", [RuntimeProfile.STANDALONE, RuntimeProfile.FULL, RuntimeProfile.COMPACT]
)
async def test_owned_roles_deny_self_signed_trust_and_exports_preserve_project_policy(
    world: SecurityWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: RuntimeProfile,
) -> None:
    monkeypatch.setattr(settings, "redaction_mode", "off")
    monkeypatch.setattr(settings, "runtime_profile", profile)
    admin = await login(world.client, settings.bootstrap_admin_email)
    frozen = binding().model_copy(update={"runtime_profile": profile.value})
    result = await execute_security_boundaries(
        binding=frozen,
        bootstrap_token=admin["Authorization"].removeprefix("Bearer "),
        batch_key="security-boundaries-test",
        output_dir=tmp_path / "round",
        deadline=datetime.now(UTC) + timedelta(seconds=600),
        transport=httpx.ASGITransport(app=app),
    )
    assert result.reason_codes == ("OWNED_ASSET_DISPOSAL_PENDING",), result.model_dump_json(
        indent=2
    )
    assert result.evidence.scenarios[0].permission_role == "owner"
    assert result.evidence.scenarios[1].permission_role == "editor"
    assert result.evidence.scenarios[2].artifact_purpose == "upload"
    assert result.evidence.scenarios[3].sentinel_present == (False,) * 9
    assert result.evidence.scenarios[4].sentinel_present == (True, False, True)
    assert all(
        not scene.native_run_ids and not scene.native_executions
        for scene in result.evidence.scenarios
    )
    assert result.evidence.http_attempts < 100
    stored = (tmp_path / "round/result.json").read_text()
    assert "Bearer " not in stored and "access_token" not in stored
    # A mocked host absence check only exercises finalizer behavior, not actual Docker disposal.
    stack = tmp_path / "owned"
    write_json(stack / "stack.json", frozen)
    write_json(
        stack / "ownership.json", {"project_name": frozen.project_name, "nonce": frozen.nonce}
    )
    write_json(stack / "cleanup.json", {"project_name": frozen.project_name, "status": "completed"})
    monkeypatch.setattr("scripts.selftest.security_boundaries._verify_removed", lambda _: None)
    final = finalize_security_boundaries(
        result, binding=frozen, stack_directory=stack, output_dir=tmp_path / "round"
    )
    assert final.exit_code == 0 and verify_security_boundaries(final) == ()
    assert result.evidence.cleanup_status == "pending"
    baseline = final.model_dump(mode="json")
    for change in (
        "owner_admin",
        "editor_pass",
        "missing_trace",
        "manual_trusted",
        "secret_leak",
        "off_changed",
        "run_created",
        "disposal_foreign",
    ):
        raw = copy.deepcopy(baseline)
        scenes = raw["evidence"]["scenarios"]
        if change == "owner_admin":
            scenes[0]["is_system_admin"] = True
        elif change == "editor_pass":
            scenes[1]["denials"][0]["status"] = 200
        elif change == "missing_trace":
            scenes[0]["denials"][1]["trace_id"] = None
        elif change == "manual_trusted":
            scenes[2]["artifact_purpose"] = "trusted_ci"
        elif change == "secret_leak":
            scenes[3]["sentinel_present"][0] = True
        elif change == "off_changed":
            scenes[4]["sentinel_present"][2] = False
        elif change == "run_created":
            scenes[0]["native_run_ids"] = [str(world.project)]
        else:
            raw["evidence"]["target_disposal"]["binding_nonce"] = "f" * 32
        assert verify_security_boundaries(BoundaryResult.model_validate(raw)), change
    assert baseline == final.model_dump(mode="json")
