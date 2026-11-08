"""Pin generated Case versions in a published Suite before starting an ordinary Plan."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from scripts.selftest.contracts import Contract, Sha256, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    text_value,
    write_json,
)


class PublishedCaseAsset(Protocol):
    """Published public Case data; review evidence belongs to its originating route."""

    @property
    def case(self) -> JsonObject: ...

    @property
    def version(self) -> JsonObject: ...


class FrozenPlanCase(Contract):
    case_id: UUID
    version: int
    target_snapshot_digest: Sha256


class PlanSelection(Contract):
    project_id: UUID
    suite_id: UUID
    suite_version: int
    suite_fingerprint: Sha256
    plan_id: UUID
    cases: tuple[FrozenPlanCase, ...]
    frozen_at: datetime


class StartedPlan(Contract):
    selection: PlanSelection
    run_id: UUID


def _frozen_case(case: PublishedCaseAsset, suite_id: str, suite_version: int) -> FrozenPlanCase:
    case_id, version = text_value(case.case["id"]), integer_value(case.version["version"])
    snapshot: JsonObject = {
        "target_type": "case",
        "target_id": case_id,
        "target_version": version,
        "definition": case.version["definition"],
        "source_suite": {"id": suite_id, "version": suite_version},
    }
    return FrozenPlanCase(
        case_id=UUID(case_id), version=version, target_snapshot_digest=canonical_digest(snapshot)
    )


async def prepare_plan(
    reviewer: PublicAPI,
    *,
    project_id: str,
    cases: tuple[PublishedCaseAsset, ...],
    batch_key: str,
    output_dir: Path,
) -> PlanSelection:
    if not cases or len({case.case["id"] for case in cases}) != len(cases):
        raise HarnessError("SELFTEST_CASE_SELECTION_EMPTY_OR_DUPLICATED")
    definition: JsonObject = {
        "items": [
            {"test_case_id": case.case["id"], "test_case_version": case.version["version"]}
            for case in cases
        ]
    }
    suite = await reviewer.object(
        "POST",
        f"/projects/{project_id}/test-suites",
        {"name": batch_key, "description": "本批现场生成用例的固定套件", "definition": definition},
    )
    suite_id = text_value(suite["id"])
    published = await reviewer.object(
        "POST",
        f"/projects/{project_id}/test-suites/{suite_id}/versions",
        {"change_note": "执行前固定本批真实 Case 版本"},
    )
    if canonical_digest(published["definition"]) != canonical_digest(definition):
        raise HarnessError("SELFTEST_SUITE_CASE_VERSION_CHANGED")
    suite_version = integer_value(published["version"])
    plan = await reviewer.object(
        "POST",
        f"/projects/{project_id}/test-plans",
        {
            "name": batch_key,
            "description": "展开本批固定套件版本; 默认重试 0",
            "items": [
                {
                    "target_type": "suite",
                    "target_id": suite_id,
                    "target_version": suite_version,
                    "max_retries": 0,
                }
            ],
        },
    )
    plan_id = text_value(plan["id"])
    selection = PlanSelection(
        project_id=UUID(project_id),
        suite_id=UUID(suite_id),
        suite_version=suite_version,
        suite_fingerprint=text_value(published["fingerprint"]),
        plan_id=UUID(plan_id),
        cases=tuple(_frozen_case(case, suite_id, suite_version) for case in cases),
        frozen_at=datetime.now(UTC),
    )
    # The created Plan response contains a write-only webhook secret; never persist it.
    write_json(output_dir / "plan-selection.json", selection)
    return selection


async def launch_plan(
    reviewer: PublicAPI, *, selection: PlanSelection, batch_key: str
) -> StartedPlan:
    run = await reviewer.object(
        "POST",
        f"/projects/{selection.project_id}/test-plans/{selection.plan_id}/runs",
        idempotency_key=batch_key + ":run",
    )
    return StartedPlan(selection=selection, run_id=UUID(text_value(object_value(run)["id"])))
