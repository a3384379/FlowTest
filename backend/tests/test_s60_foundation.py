import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api
from test_s59d_change_regression import _bound

from app.core.config import settings
from app.core.errors import AppError
from app.models.access import User
from app.models.ai import AIChangeSet
from app.models.change_regression import ChangeRegressionRun
from app.models.test_contexts import TestContext as ContextModel
from app.models.test_design import ChangeSetApproval
from app.services.change_regression import ChangeRegressionService
from app.services.regression_maintenance import RegressionMaintenanceService
from app.services.test_contexts import TestContextService as ContextService


def test_generated_bundle_rejects_obsolete_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Path(__file__).parents[2] / "scripts/build_skill_evaluation.py"
    namespace = runpy.run_path(str(script))
    sync = namespace["sync_bundle"]
    monkeypatch.setitem(sync.__globals__, "WORKSPACE_ROOT", tmp_path)
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    monkeypatch.setitem(sync.__globals__, "GOLDEN_ROOT", canonical)
    package = tmp_path / "package"
    monkeypatch.setitem(sync.__globals__, "PACKAGE_ROOT", package)
    domain = tmp_path / "backend/app/domain/v6_evaluation.py"
    domain.parent.mkdir(parents=True)
    domain.write_text("# test evaluation source\n")
    for name in ("evaluation-annotations.json", "evaluation-baseline.json", "old.json"):
        (canonical / name).write_text("{}\n")
    sync(check=False)
    (canonical / "old.json").rename(canonical / "new.json")
    # Regeneration must not silently bless stale files left by a rename.
    with pytest.raises(ValueError, match=r"obsolete|unexpected"):
        sync(check=False)
    with pytest.raises(ValueError, match=r"obsolete|unexpected"):
        sync(check=True)


@pytest.mark.asyncio
async def test_context_expiry_does_not_commit_unvalidated_approval(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = failure_repair_api
    monkeypatch.setattr(settings, "feature_impact_engine_enabled", True)
    root, _, bound = await _bound(fixture)
    async with fixture["sessions"]() as session:
        actor = await session.scalar(select(User))
        change_set = AIChangeSet(
            project_id=fixture["project_id"],
            title="Approval ordering",
            status="accepted",
            source_type="change_regression",
            source_snapshot={},
            source_fingerprint="c" * 64,
            created_by_id=actor.id,
        )
        session.add(change_set)
        await session.flush()
        run = await session.get(ChangeRegressionRun, UUID(bound["id"]))
        run.change_set_id = change_set.id
        context = await session.scalar(select(ContextModel))
        context.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        change_set_id = change_set.id

    async def no_gaps(*args: Any) -> None:
        return None

    async def expired_review(
        service: RegressionMaintenanceService, run: ChangeRegressionRun, actor: User
    ) -> None:
        context = await service._session.scalar(select(ContextModel))
        await ContextService(service._session)._mark_expired(actor=actor, context=context)
        raise AppError(code="TEST_CONTEXT_EXPIRED", message="上下文已过期", status_code=409)

    monkeypatch.setattr(ChangeRegressionService, "_require_resolved_plan_gaps", no_gaps)
    monkeypatch.setattr(RegressionMaintenanceService, "require_review", expired_review)
    result = await fixture["client"].post(
        f"{root}/approve", headers=fixture["headers"], json={"note": "先验证所有维护前置条件"}
    )
    assert result.status_code == 409, result.text
    async with fixture["sessions"]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ChangeSetApproval)
                .where(ChangeSetApproval.change_set_id == change_set_id)
            )
            == 0
        )
