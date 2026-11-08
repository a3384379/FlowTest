"""Explicit fixture decisions never grant the proposing machine review authority."""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import JsonValue
from scripts.selftest.contracts import Contract
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.mcp_probe_contracts import ProbeSnapshot

if TYPE_CHECKING:
    from scripts.selftest.review_boundary_journey import ReviewJourney


class ReviewResumeCheckpoint(Contract):
    proposal_id: UUID
    accepted_item_ids: tuple[UUID, ...]
    remaining_item_id: UUID


class KnownReviewPause(Exception):
    """A deliberate known-state pause, not a claimed host/process crash."""


def design_arguments(
    journey: ReviewJourney, *, high: bool = False, partial: bool = False
) -> JsonObject:
    cases: list[JsonValue] = []
    if partial:
        cases = [
            {
                "name": f"{journey.client.batch_key}:partial:{index}",
                "description": "review_mode=ci_fixture",
                "tags": ["selftest"],
                "definition": {
                    "workflow_id": str(journey.workflow_id),
                    "workflow_version": 1,
                    "environment_id": str(journey.manifest.scope.fixture_environment_id),
                    "runtime_variables": {},
                    "runtime_headers": {},
                },
            }
            for index in range(2)
        ]
    return {
        "project_id": journey.project,
        "idempotency_key": journey.client.batch_key + ":" + journey.scenario_id,
        "dry_run": False,
        "title": journey.client.batch_key + ":" + journey.scenario_id,
        "confidence": 1.0,
        "risk_level": "high" if high else "low",
        "test_cases": cases,
        "design": {
            "intent": {
                "key": "synthetic.governance",
                "objective": "合成治理验证, 不执行发布运行",
                "acceptance_criteria": ["只允许已批准草稿"],
            },
            "oracles": [
                {
                    "id": "status",
                    "kind": "status",
                    "expression": "$.status",
                    "operator": "equals",
                    "expected": 200,
                    "confidence": 1.0,
                }
            ],
        },
    }


def item_path(journey: ReviewJourney, item_id: str) -> str:
    return f"/mcp/write/change-sets/{journey.proposal_id}/items/{item_id}/accept"


async def stale_approval(journey: ReviewJourney) -> UUID:
    proposed = await journey.propose(
        "flowtest.propose_test_design", design_arguments(journey, high=True)
    )
    item = objects_value(proposed["items"])[0]
    approved = await journey.obj(
        "approve_high",
        "POST",
        f"/mcp/write/change-sets/{journey.proposal_id}/approve",
        {"note": "只批准冻结原文; review_mode=ci_fixture"},
    )
    approval = UUID(text_value(object_value(object_value(approved["data"])["approval"])["id"]))
    changed = copy.deepcopy(object_value(item["proposed_content"]))
    objects_value(changed["oracles"])[0]["expected"] = 201
    await journey.obj(
        "changed_content_denied",
        "POST",
        item_path(journey, text_value(item["id"])),
        {"approval_id": str(approval), "content": changed},
        expected=(409,),
    )
    await journey.obj(
        "original_accepted",
        "POST",
        item_path(journey, text_value(item["id"])),
        {"approval_id": str(approval)},
    )
    return approval


async def concurrent_accept(journey: ReviewJourney) -> None:
    proposed = await journey.propose("flowtest.propose_test_design", design_arguments(journey))
    item = objects_value(proposed["items"])[0]
    path = item_path(journey, text_value(item["id"]))
    await asyncio.gather(
        journey.obj("concurrent_accept", "POST", path, {}, expected=(200, 409)),
        journey.obj("concurrent_accept", "POST", path, {}, expected=(200, 409)),
    )


async def partial_resume(journey: ReviewJourney) -> ProbeSnapshot:
    proposed = await journey.propose(
        "flowtest.propose_test_design", design_arguments(journey, partial=True)
    )
    items = objects_value(proposed["items"])
    if len(items) != 3:
        raise HarnessError("SELFTEST_REVIEW_PARTIAL_ITEM_SET_INVALID")
    for item in items[:2]:
        await journey.obj("partial_accept", "POST", item_path(journey, text_value(item["id"])), {})
    state = ReviewResumeCheckpoint(
        proposal_id=journey.proposal_id,
        accepted_item_ids=tuple(UUID(text_value(item["id"])) for item in items[:2]),
        remaining_item_id=UUID(text_value(items[2]["id"])),
    )
    path = journey.output / journey.scenario_id / "known-state-checkpoint.json"
    write_json(path, state)
    checkpoint = await journey.inventory.snapshot()
    try:
        raise KnownReviewPause()
    except KnownReviewPause:
        recovered = ReviewResumeCheckpoint.model_validate(read_json(path))
        envelope = await journey.obj(
            "resume_readback", "GET", f"/mcp/write/change-sets/{recovered.proposal_id}"
        )
        current = objects_value(object_value(envelope["data"])["items"])
    accepted = {
        UUID(text_value(item["id"])) for item in current if item["review_status"] == "accepted"
    }
    pending = {
        UUID(text_value(item["id"])) for item in current if item["review_status"] == "pending"
    }
    if accepted != set(recovered.accepted_item_ids) or pending != {recovered.remaining_item_id}:
        raise HarnessError("SELFTEST_REVIEW_PARTIAL_READBACK_CHANGED")
    await journey.obj(
        "resume_accept", "POST", item_path(journey, str(recovered.remaining_item_id)), {}
    )
    await journey.obj(
        "reaccept_denied",
        "POST",
        item_path(journey, str(recovered.accepted_item_ids[0])),
        {},
        expected=(409,),
    )
    return checkpoint
