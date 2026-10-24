"""Actual child installers hit public HTTP; inventories use an independent ordinary viewer."""

from __future__ import annotations

import copy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_selftest_auth_expiry import binding
from test_selftest_bad_targets import _actual_loopback
from test_selftest_native_api_security import SecurityWorld, login
from test_selftest_native_api_security import world as world

from app.core.config import settings
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.initialization_boundaries import (  # noqa: E402
    execute_initialization_boundaries,
    finalize_initialization_boundaries,
)
from scripts.selftest.initialization_contracts import InitializationResult  # noqa: E402
from scripts.selftest.io import write_json  # noqa: E402
from scripts.selftest.verify_initialization_boundaries import (  # noqa: E402
    verify_initialization_boundaries,
)


@pytest.mark.asyncio
async def test_real_child_installers_preserve_single_mapping_and_never_replay_unknown_post(
    world: SecurityWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await login(world.client, settings.bootstrap_admin_email)
    async with _actual_loopback() as base:
        frozen = binding().model_copy(update={"target_url": base})
        result = await execute_initialization_boundaries(
            binding=frozen,
            bootstrap_token=admin["Authorization"].removeprefix("Bearer "),
            batch_key="initialization-boundaries-test",
            output_dir=tmp_path / "round",
            deadline=datetime.now(UTC) + timedelta(seconds=600),
            transport=httpx.ASGITransport(app=app),
        )
    assert result.reason_codes == ("OWNED_ASSET_DISPOSAL_PENDING",), result.model_dump_json(
        indent=2
    )
    assert [
        tuple(worker.exit_code for worker in scene.workers) for scene in result.evidence.scenarios
    ] == [(0, 4, 0), (3, 0), (2, 2)]
    assert (
        result.evidence.scenarios[0].installation
        == result.evidence.scenarios[0].resumed_installation
    )
    assert (
        result.evidence.scenarios[1].after.environment_ids
        == result.evidence.scenarios[1].repeat.environment_ids
    )
    unknown = result.evidence.scenarios[2]
    assert unknown.unknown_posts_before_restart == unknown.unknown_posts_after_restart
    assert not unknown.repeat.api_ids and not unknown.repeat.workflow_ids
    assert all(
        not scene.repeat.run_ids and not scene.repeat.execution_ids
        for scene in result.evidence.scenarios
    )
    assert result.evidence.http_attempts < 500
    stored = (tmp_path / "round/result.json").read_text()
    assert "Bearer " not in stored and 'token"' not in stored
    stack = tmp_path / "stack"
    write_json(stack / "stack.json", frozen)
    write_json(
        stack / "ownership.json", {"project_name": frozen.project_name, "nonce": frozen.nonce}
    )
    write_json(stack / "cleanup.json", {"project_name": frozen.project_name, "status": "completed"})
    monkeypatch.setattr(
        "scripts.selftest.initialization_boundaries._verify_removed", lambda _: None
    )
    final = finalize_initialization_boundaries(
        result, binding=frozen, stack_directory=stack, output_dir=tmp_path / "round"
    )
    assert final.exit_code == 0
    baseline = final.model_dump(mode="json")
    for change in (
        "second_writer",
        "extra_api",
        "unknown_replay",
        "missing_mapping",
        "changed_phase",
        "foreign_disposal",
    ):
        raw = copy.deepcopy(baseline)
        scenes = raw["evidence"]["scenarios"]
        if change == "second_writer":
            scenes[0]["workers"][1]["exit_code"] = 0
        elif change == "extra_api":
            scenes[0]["repeat"]["api_ids"].append(str(world.project))
        elif change == "unknown_replay":
            scenes[2]["unknown_posts_after_restart"] += 1
        elif change == "missing_mapping":
            scenes[1]["published_mapping_matches"] = False
        elif change == "changed_phase":
            scenes[1]["after"]["environment_ids"] = []
        else:
            raw["evidence"]["target_disposal"]["binding_nonce"] = "f" * 32
        assert verify_initialization_boundaries(InitializationResult.model_validate(raw)), change
    assert baseline == final.model_dump(mode="json")
