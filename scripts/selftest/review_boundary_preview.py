"""A real accepted, unapplied Preview is cancelled and its cleanup is read independently."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from scripts.selftest.collect_evidence import _journal_snapshot
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.review_boundary_contracts import (
    PreviewApprovalProjection,
    PreviewExecution,
    PreviewNode,
    ReviewObservation,
    ReviewScenario,
)
from scripts.selftest.review_boundary_setup import PACK_PATH

if TYPE_CHECKING:
    from scripts.selftest.review_boundary_journey import ReviewJourney


async def execution(
    journey: ReviewJourney, execution_id: str, *, terminal: bool
) -> PreviewExecution:
    for _ in range(60):
        raw = await journey.reader.object(
            "GET", f"/ci/projects/{journey.project}/workflow-executions/{execution_id}/evidence"
        )
        ready = (
            raw["status"] not in {"queued", "running"} if terminal else raw["status"] != "queued"
        )
        if ready:
            projection: JsonObject = {
                key: raw[key] for key in PreviewExecution.model_fields if key != "nodes"
            }
            projection["nodes"] = [
                {key: row[key] for key in PreviewNode.model_fields}
                for row in objects_value(raw["nodes"])
            ]
            return PreviewExecution.model_validate(projection)
        await asyncio.sleep(1)
    raise HarnessError("SELFTEST_REVIEW_PREVIEW_EXECUTION_READ_TIMEOUT")


async def preview_cancel(
    journey: ReviewJourney, scenario: ReviewScenario, observer: PublicAPI
) -> ReviewObservation:
    journey.scenario_id, journey.http = scenario.scenario_id, []
    started = datetime.now(UTC)
    before = await journey.inventory.snapshot()
    offset = len(journey.client.receipts)
    await journey.flow()
    root = journey.flow_root()
    scope = journey.manifest.scope
    approval_body: JsonObject = {
        "environment_id": str(scope.fixture_environment_id),
        "executor_service_account_id": str(journey.manifest.writer_machine_id),
        "budget": read_json(PACK_PATH)["preview_budget"],
        "ttl_seconds": 180,
    }
    await journey.obj(
        "unreviewed_preview_denied",
        "POST",
        root + "/preview-approvals",
        approval_body,
        expected=(409,),
    )
    await journey.obj(
        "review_preview",
        "POST",
        root + "/review",
        {"accept": True, "note": "review_mode=ci_fixture; 仅允许受限Preview"},
    )
    await journey.obj(
        "production_preview_denied",
        "POST",
        root + "/preview-approvals",
        {**approval_body, "environment_id": str(scope.production_environment_id)},
        expected=(403,),
    )
    approved = await journey.obj(
        "preview_approval", "POST", root + "/preview-approvals", approval_body, expected=(201,)
    )
    approval = PreviewApprovalProjection.model_validate(
        {key: approved[key] for key in PreviewApprovalProjection.model_fields}
    )
    arguments: JsonObject = {
        "project_id": journey.project,
        "change_set_id": str(journey.proposal_id),
        "environment_id": str(scope.fixture_environment_id),
        "approval_id": str(approval.id),
        "idempotency_key": journey.client.batch_key + ":preview-once",
    }
    first = await journey.client.call(
        "flowtest.preview_flow_proposal",
        arguments,
        scenario_id=scenario.scenario_id,
        phase="preview_once",
    )
    repeated = await journey.client.call(
        "flowtest.preview_flow_proposal",
        arguments,
        scenario_id=scenario.scenario_id,
        phase="preview_same_key",
    )
    identifiers = tuple(
        UUID(text_value(object_value(item["execution"])["id"])) for item in (first, repeated)
    )
    denied = await journey.client.boundary_call(
        "flowtest.preview_flow_proposal",
        {**arguments, "idempotency_key": journey.client.batch_key + ":preview-reuse"},
        scenario_id=scenario.scenario_id,
    )
    await execution(journey, str(identifiers[0]), terminal=False)
    await journey.client.call(
        "flowtest.cancel_preview",
        {"request": {"project_id": journey.project, "execution_id": str(identifiers[0])}},
        scenario_id=scenario.scenario_id,
        phase="graceful_preview_cancel",
    )
    observed = await execution(journey, str(identifiers[0]), terminal=True)
    # The journal is bounded to ten pages by its reader. Reserve all ten before
    # dispatch; an unused reservation cannot allow requests beyond the cap.
    if not all(journey.client._budget.reserve() for _ in range(10)):
        raise HarnessError("SELFTEST_REVIEW_JOURNAL_BUDGET_EXHAUSTED")
    target = await _journal_snapshot(
        observer, journey.client.batch_key, "ST-MCP-022-" + scenario.transport
    )
    after = await journey.inventory.snapshot()
    result = ReviewObservation(
        scenario_id=scenario.scenario_id,
        started_at=started,
        completed_at=datetime.now(UTC),
        before=before,
        after=after,
        proposal_id=journey.proposal_id,
        proposal_arguments=journey.proposal_arguments,
        proposal_result=journey.proposal_result,
        proposal_envelope=journey.proposal_envelope,
        approval_id=approval.id,
        preview=observed,
        preview_approval=approval,
        preview_execution_ids=identifiers,
        tool_results=(denied,),
        journal=target,
        http=tuple(journey.http),
        calls=tuple(journey.client.receipts[offset:]),
    )
    write_json(journey.output / scenario.scenario_id / "observation.json", result)
    return result
