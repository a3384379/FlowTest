"""Explicit review strategies: public CI fixture review or read-only human review waits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from scripts.selftest.contracts import Contract, ProposalEvidence
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.review_fixture_driver import (
    ReviewedCase,
    ReviewedWorkflow,
    _fixture_graph,
    _same_definition,
    review_case,
    review_flow,
)


class ReviewDriver(Protocol):
    async def flow(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        reviewer_id: str,
        proposal_id: str,
        expected_definition: JsonObject,
        expected_api_ids: tuple[str, ...],
        output_dir: Path,
    ) -> ReviewedWorkflow: ...
    async def case(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        reviewer_id: str,
        proposal_id: str,
        expected_definition: JsonObject,
        output_dir: Path,
    ) -> ReviewedCase: ...


class FixtureReviewDriver:
    async def flow(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        reviewer_id: str,
        proposal_id: str,
        expected_definition: JsonObject,
        expected_api_ids: tuple[str, ...],
        output_dir: Path,
    ) -> ReviewedWorkflow:
        return await review_flow(
            api,
            project_id=project_id,
            reviewer_id=reviewer_id,
            proposal_id=proposal_id,
            expected_definition=expected_definition,
            expected_api_ids=expected_api_ids,
            output_dir=output_dir,
        )

    async def case(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        reviewer_id: str,
        proposal_id: str,
        expected_definition: JsonObject,
        output_dir: Path,
    ) -> ReviewedCase:
        return await review_case(
            api,
            project_id=project_id,
            reviewer_id=reviewer_id,
            proposal_id=proposal_id,
            expected_definition=expected_definition,
            output_dir=output_dir,
        )


class PendingReview(Contract):
    project_id: UUID
    proposal_id: UUID
    item_id: UUID | None = None
    route: Literal["flow_spec", "controlled_write"]
    content_fingerprint: str


type PendingCallback = Callable[[PendingReview], Awaitable[None]]


class HumanReviewDriver:
    """Reads the existing proposals/versions; it never approves, applies or publishes."""

    def __init__(
        self,
        deadline: datetime,
        on_pending: PendingCallback,
        *,
        review_mode: Literal["human", "ci_fixture"] = "human",
    ) -> None:
        self.deadline, self.on_pending = deadline, on_pending
        self.review_mode = review_mode

    def _check_deadline(self) -> None:
        if datetime.now(UTC) >= self.deadline:
            raise HarnessError("SELFTEST_HUMAN_REVIEW_DEADLINE_EXPIRED")

    async def _accepted_flow(
        self, api: PublicAPI, *, project_id: str, proposal_id: str, fingerprint: str
    ) -> JsonObject:
        while True:
            self._check_deadline()
            proposal = await api.object(
                "GET", f"/projects/{project_id}/flow-specs/change-sets/{proposal_id}"
            )
            if (
                proposal["project_id"] != project_id
                or proposal["source_fingerprint"] != fingerprint
            ):
                raise HarnessError("SELFTEST_HUMAN_REVIEW_SOURCE_CHANGED")
            if proposal["review_status"] == "rejected":
                raise HarnessError("SELFTEST_HUMAN_REVIEW_REJECTED")
            if (
                proposal["review_status"] == "accepted"
                and proposal.get("applied_at")
                and proposal.get("materialized_workflow_id")
            ):
                return proposal
            await asyncio.sleep(1)

    async def _accepted_item(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        proposal_id: str,
        kind: Literal["workflow", "test_case"],
        fingerprint: str,
        expected_definition: JsonObject,
        output_dir: Path,
    ) -> JsonObject:
        while True:
            self._check_deadline()
            change = object_value(
                (await api.object("GET", f"/mcp/write/change-sets/{proposal_id}"))["data"]
            )
            if change["project_id"] != project_id or change["source_fingerprint"] != fingerprint:
                raise HarnessError("SELFTEST_HUMAN_REVIEW_SOURCE_CHANGED")
            items = [item for item in objects_value(change["items"]) if item["item_type"] == kind]
            if len(items) != 1:
                raise HarnessError("SELFTEST_HUMAN_REVIEW_ITEM_AMBIGUOUS")
            item = items[0]
            if item["review_status"] == "rejected":
                raise HarnessError("SELFTEST_HUMAN_REVIEW_REJECTED")
            if item["review_status"] == "accepted" and item["materialized_resource_id"]:
                return item
            await asyncio.sleep(1)

    async def _published(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        resource_id: str,
        kind: Literal["workflows", "test-cases"],
        expected_definition: JsonObject,
        output_dir: Path,
    ) -> tuple[JsonObject, JsonObject]:
        base = f"/projects/{project_id}/{kind}/{resource_id}"
        while True:
            self._check_deadline()
            resource = await api.object("GET", base)
            _same_definition(
                expected_definition,
                object_value(resource["draft_definition"]),
                output_dir=output_dir,
                stage="human_review_draft",
            )
            versions = objects_value(await api.request("GET", base + "/versions"))
            current = resource.get("current_version")
            matches = [version for version in versions if version["version"] == current]
            if matches:
                _same_definition(
                    expected_definition,
                    object_value(matches[0]["definition"]),
                    output_dir=output_dir,
                    stage="human_review_published",
                )
                return resource, matches[0]
            await asyncio.sleep(1)

    async def flow(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        reviewer_id: str,
        proposal_id: str,
        expected_definition: JsonObject,
        expected_api_ids: tuple[str, ...],
        output_dir: Path,
    ) -> ReviewedWorkflow:
        _fixture_graph(expected_definition, expected_api_ids)
        visual = await api.object(
            "GET", f"/projects/{project_id}/flow-specs/change-sets/{proposal_id}/visual-proposal"
        )
        proposal = object_value(visual["proposal"])
        _same_definition(
            expected_definition,
            object_value(visual["proposed_definition"]),
            output_dir=output_dir,
            stage="human_visual_proposal",
        )
        fingerprint = text_value(proposal["source_fingerprint"])
        await self.on_pending(
            PendingReview(
                project_id=UUID(project_id),
                proposal_id=UUID(proposal_id),
                route="flow_spec",
                content_fingerprint=fingerprint,
            )
        )
        sealed = await self._accepted_flow(
            api,
            project_id=project_id,
            proposal_id=proposal_id,
            fingerprint=fingerprint,
        )
        identifier = text_value(sealed["materialized_workflow_id"])
        resource, version = await self._published(
            api,
            project_id=project_id,
            resource_id=identifier,
            kind="workflows",
            expected_definition=expected_definition,
            output_dir=output_dir,
        )
        evidence = ProposalEvidence(
            project_id=UUID(project_id),
            proposal_id=UUID(proposal_id),
            route="flow_spec",
            content_fingerprint=fingerprint,
            review_status="accepted",
            materialized_resource_id=UUID(identifier),
            review_mode=self.review_mode,
            reviewer_id=UUID(text_value(sealed["reviewed_by_id"])),
        )
        result = ReviewedWorkflow(workflow=resource, version=version, proposal=evidence)
        write_json(output_dir / "reviewed-workflow.json", result)
        return result

    async def case(
        self,
        api: PublicAPI,
        *,
        project_id: str,
        reviewer_id: str,
        proposal_id: str,
        expected_definition: JsonObject,
        output_dir: Path,
    ) -> ReviewedCase:
        change = object_value(
            (await api.object("GET", f"/mcp/write/change-sets/{proposal_id}"))["data"]
        )
        cases = [
            item for item in objects_value(change["items"]) if item["item_type"] == "test_case"
        ]
        if len(cases) != 1 or change["project_id"] != project_id:
            raise HarnessError("SELFTEST_HUMAN_CASE_ITEM_AMBIGUOUS")
        _same_definition(
            expected_definition,
            object_value(object_value(cases[0]["proposed_content"])["definition"]),
            output_dir=output_dir,
            stage="human_case_proposal",
        )
        fingerprint = text_value(change["source_fingerprint"])
        await self.on_pending(
            PendingReview(
                project_id=UUID(project_id),
                proposal_id=UUID(proposal_id),
                item_id=UUID(text_value(cases[0]["id"])),
                route="controlled_write",
                content_fingerprint=fingerprint,
            )
        )
        item = await self._accepted_item(
            api,
            project_id=project_id,
            proposal_id=proposal_id,
            kind="test_case",
            fingerprint=fingerprint,
            expected_definition=expected_definition,
            output_dir=output_dir,
        )
        resource, version = await self._published(
            api,
            project_id=project_id,
            resource_id=text_value(item["materialized_resource_id"]),
            kind="test-cases",
            expected_definition=expected_definition,
            output_dir=output_dir,
        )
        result = ReviewedCase(
            case=resource,
            version=version,
            proposal=self._evidence(project_id, proposal_id, item, fingerprint, "controlled_write"),
        )
        write_json(output_dir / "reviewed-case.json", result)
        return result

    def _evidence(
        self,
        project: str,
        proposal: str,
        item: JsonObject,
        fingerprint: str,
        route: Literal["flow_spec", "controlled_write"],
    ) -> ProposalEvidence:
        return ProposalEvidence(
            project_id=UUID(project),
            proposal_id=UUID(proposal),
            item_id=UUID(text_value(item["id"])),
            route=route,
            content_fingerprint=fingerprint,
            review_status="accepted",
            materialized_resource_id=UUID(text_value(item["materialized_resource_id"])),
            review_mode=self.review_mode,
            reviewer_id=UUID(text_value(item["reviewed_by_id"])),
        )
