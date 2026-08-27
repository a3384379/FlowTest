#!/usr/bin/env python3
"""Prepare and verify the S47.4 immutable waiver-revision migration."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models import APIDefinition, Project
from app.models.change_regression import ChangeRegressionRun
from app.models.impact import ImpactRun
from app.models.release_gate import ReleasePolicy
from app.models.tasking import TestPlan

_IMPORT_KEY = "s47-2-contract-migration-golden"
_GAP_KEY = "4" * 64
_REQUIREMENT_FINGERPRINT = "5" * 64


async def _prepare() -> None:
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        project = await session.scalar(
            select(Project)
            .join(APIDefinition, APIDefinition.project_id == Project.id)
            .where(APIDefinition.import_key == _IMPORT_KEY)
        )
        if project is None:
            raise RuntimeError("prepare the S47.2 migration fixture before S47.4")
        impact = ImpactRun(
            project_id=project.id,
            title="S47.4 waiver migration fixture",
            source_ref="migration://s47.4",
            status="completed",
            source_fingerprint="1" * 64,
            source_summary={},
            change_count=1,
            changes=[{"key": "migration.waiver"}],
            graph={},
            summary={},
            created_by_id=project.created_by_id,
        )
        plan = TestPlan(
            project_id=project.id,
            name="S47.4 waiver migration plan",
            description="migration fixture",
            enabled=False,
            schedule_interval_seconds=None,
            schedule_cron=None,
            schedule_timezone="Asia/Shanghai",
            queue_priority=5,
            next_run_at=None,
            webhook_secret_ciphertext=b"fixture",
            webhook_secret_nonce=b"fixture",
            created_by_id=project.created_by_id,
        )
        policy = ReleasePolicy(
            project_id=project.id,
            name="S47.4 waiver migration policy",
            enabled=False,
            quality_gate_id=None,
            require_quality_gate=False,
            require_contract_compatibility=False,
            require_impact_evidence=False,
            min_impact_coverage_percent=0,
            require_release_risk=False,
            max_release_risk_score=100,
            require_performance_evidence=False,
            require_runner_evidence=False,
            created_by_id=project.created_by_id,
        )
        session.add_all([impact, plan, policy])
        await session.flush()
        run = ChangeRegressionRun(
            project_id=project.id,
            title="S47.4 waiver migration run",
            source_ref="migration://s47.4",
            source_fingerprint="2" * 64,
            candidate_ref="migration-s47.4",
            status="review_required",
            impact_run_id=impact.id,
            test_plan_id=plan.id,
            test_plan_run_id=None,
            release_policy_id=policy.id,
            release_risk_id=None,
            deployment_check_id=None,
            change_set_id=None,
            release_decision_id=None,
            selected_assets=[],
            selection_summary={},
            missing_tests=[],
            evidence={},
            failure_triage={},
            approved_by_id=None,
            approved_at=None,
            created_by_id=project.created_by_id,
        )
        session.add(run)
        await session.flush()
        await session.execute(
            text(
                "INSERT INTO semantic_gap_waivers "
                "(id, regression_run_id, project_id, gap_key, reason, approved_by_id, "
                "approved_at, expires_at, operation_identity, semantic_requirement, "
                "requirement_fingerprint) VALUES "
                "(:id, :run_id, :project_id, :gap_key, :reason, :approved_by_id, now(), NULL, "
                "CAST(:operation AS json), CAST(:requirement AS json), :fingerprint)"
            ),
            {
                "id": uuid4(),
                "run_id": run.id,
                "project_id": project.id,
                "gap_key": _GAP_KEY,
                "reason": "S47.4 historical waiver revision fixture",
                "approved_by_id": project.created_by_id,
                "operation": json.dumps({"operation": "migration.waiver"}),
                "requirement": json.dumps({"token": "migration"}),
                "fingerprint": _REQUIREMENT_FINGERPRINT,
            },
        )
        await session.commit()
    await engine.dispose()
    print(json.dumps({"status": "prepared", "revision": "20260823_0044"}))


async def _verify() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        first = (
            (
                await connection.execute(
                    text(
                        "SELECT * FROM semantic_gap_waivers WHERE gap_key = :gap_key "
                        "ORDER BY revision"
                    ),
                    {"gap_key": _GAP_KEY},
                )
            )
            .mappings()
            .one()
        )
        if first["revision"] != 1 or first["supersedes_waiver_id"] is not None:
            raise RuntimeError("S47.4 waiver revision backfill is invalid")
        second_id = uuid4()
        await connection.execute(
            text(
                "INSERT INTO semantic_gap_waivers "
                "(id, regression_run_id, project_id, gap_key, revision, supersedes_waiver_id, "
                "reason, approved_by_id, approved_at, expires_at, operation_identity, "
                "semantic_requirement, requirement_fingerprint) VALUES "
                "(:id, :run_id, :project_id, :gap_key, 2, :supersedes, :reason, "
                ":approved_by_id, now(), NULL, CAST(:operation AS json), "
                "CAST(:requirement AS json), :fingerprint)"
            ),
            {
                "id": second_id,
                "run_id": first["regression_run_id"],
                "project_id": first["project_id"],
                "gap_key": _GAP_KEY,
                "supersedes": first["id"],
                "reason": "S47.4 renewed waiver revision fixture",
                "approved_by_id": first["approved_by_id"],
                "operation": json.dumps(first["operation_identity"]),
                "requirement": json.dumps(first["semantic_requirement"]),
                "fingerprint": _REQUIREMENT_FINGERPRINT,
            },
        )
        rows = (
            (
                await connection.execute(
                    text(
                        "SELECT id, revision, supersedes_waiver_id FROM semantic_gap_waivers "
                        "WHERE gap_key = :gap_key ORDER BY revision"
                    ),
                    {"gap_key": _GAP_KEY},
                )
            )
            .mappings()
            .all()
        )
        if [row["revision"] for row in rows] != [1, 2]:
            raise RuntimeError("S47.4 waiver revisions were not preserved")
        if rows[1]["supersedes_waiver_id"] != rows[0]["id"]:
            raise RuntimeError("S47.4 waiver supersede link is invalid")
    await engine.dispose()
    print(json.dumps({"status": "verified", "revisions": [1, 2]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "verify"))
    args = parser.parse_args()
    asyncio.run(_prepare() if args.mode == "prepare" else _verify())


if __name__ == "__main__":
    main()
