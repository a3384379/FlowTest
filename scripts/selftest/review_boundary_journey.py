"""Real SDK proposals, explicit fixture review and bounded recovery observations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import JsonValue
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.quality_protocol import QualityProtocol
from scripts.selftest.review_boundary_contracts import (
    ReviewHTTPReceipt,
    ReviewManifest,
    ReviewObservation,
    ReviewScenario,
    ReviewSource,
)
from scripts.selftest.review_boundary_http import (
    ReviewAPI,
    ReviewHTTPUnexpected,
    UnknownReviewResult,
)
from scripts.selftest.security_boundary_http import BoundaryAPI


class ReviewJourney:
    def __init__(
        self,
        manifest: ReviewManifest,
        source: ReviewSource,
        client: QualityProtocol,
        reviewer: ReviewAPI,
        inventory: ProbeReader,
        reader: BoundaryAPI,
        output: Path,
    ) -> None:
        self.manifest, self.source, self.client = manifest, source, client
        self.reviewer, self.inventory, self.reader, self.output = (
            reviewer,
            inventory,
            reader,
            output,
        )
        self.project = str(manifest.scope.project_id)
        self.workflow_id: UUID | None = None
        self.http: list[ReviewHTTPReceipt] = []
        self.proposal_arguments: JsonObject = {}
        self.proposal_result: JsonObject = {}
        self.proposal_envelope: JsonObject = {}
        self.workflow_read_envelope: JsonObject | None = None
        self.scenario_id = ""

    @property
    def proposal_id(self) -> UUID:
        return UUID(
            text_value(self.proposal_result.get("change_set_id") or self.proposal_result.get("id"))
        )

    def flow_root(self) -> str:
        return f"/projects/{self.project}/flow-specs/change-sets/{self.proposal_id}"

    async def value(
        self,
        step: str,
        method: Literal["GET", "POST", "PUT", "PATCH"],
        path: str,
        body: JsonObject | None = None,
        *,
        expected: tuple[int, ...] = (200,),
        lose_body: bool = False,
    ) -> JsonValue:
        try:
            result, receipt = await self.reviewer.action(
                step, method, path, body, expected=expected, lose_body=lose_body
            )
        except ReviewHTTPUnexpected as error:
            write_json(self.output / self.scenario_id / "failed-http.json", error.receipt)
            raise
        self.http.append(receipt)
        return result

    async def obj(
        self,
        step: str,
        method: Literal["GET", "POST", "PUT", "PATCH"],
        path: str,
        body: JsonObject | None = None,
        *,
        expected: tuple[int, ...] = (200,),
    ) -> JsonObject:
        return object_value(await self.value(step, method, path, body, expected=expected))

    async def propose(self, tool: str, arguments: JsonObject) -> JsonObject:
        self.proposal_arguments = arguments
        self.proposal_result = await self.client.call(
            tool, arguments, scenario_id=self.scenario_id, phase="fixture_proposal"
        )
        self.proposal_envelope = object_value(self.client.last_structured_result)
        return self.proposal_result

    async def flow(self, *, update: bool = False) -> None:
        arguments: JsonObject = {
            "project_id": self.project,
            "context_id": self.source.context["context_id"],
            "context_revision_id": self.source.context["context_revision_id"],
            "spec": self.source.spec,
            "operation_mappings": {"fixture.cleanup": str(self.source.api_id)},
            "operation_version_mappings": {"fixture.cleanup": self.source.api_version},
            "service_mappings": {},
            "dry_run": False,
            "idempotency_key": self.client.batch_key + ":" + self.scenario_id,
        }
        if update:
            arguments.update({"workflow_id": str(self.workflow_id), "expected_revision": 1})
        await self.propose("flowtest.propose_flow_draft", arguments)

    async def read_flow(self) -> JsonObject:
        observed = await self.client.call(
            "flowtest.inspect_flow",
            {"workflow_id": str(self.workflow_id)},
            scenario_id=self.scenario_id,
            phase="independent_readback",
        )
        self.workflow_read_envelope = object_value(self.client.last_structured_result)
        return observed

    async def unknown_publish(self) -> None:
        applied = await self.obj("apply", "POST", self.flow_root() + "/apply")
        self.workflow_id = UUID(text_value(applied["workflow_id"]))
        path = f"/projects/{self.project}/workflows/{self.workflow_id}/versions"
        try:
            await self.value(
                "publish_unknown",
                "POST",
                path,
                {"change_note": "本轮受限fixture发布"},
                expected=(200,),
                lose_body=True,
            )
            # Inject the loss before a publication body reaches the journey.
            # Never replay the mutation: resolve the exact single version by GET.
            raise UnknownReviewResult()
        except UnknownReviewResult:
            write_json(
                self.output / self.scenario_id / "first-outcome.json",
                {"code": "UNKNOWN_PUBLICATION_RESULT", "post_attempts": 1, "replayed": False},
            )
        versions = objects_value(await self.value("publish_readback", "GET", path))
        if len(versions) != 1 or versions[0]["version"] != 1:
            raise HarnessError("SELFTEST_REVIEW_UNKNOWN_PUBLICATION_NOT_RESOLVED")
        await self.read_flow()

    async def stale_proposal(self) -> None:
        await self.flow(update=True)
        await self.obj(
            "review_update",
            "POST",
            self.flow_root() + "/review",
            {"accept": True, "note": "review_mode=ci_fixture"},
        )
        await self.obj(
            "manual_edit",
            "PATCH",
            f"/projects/{self.project}/workflows/{self.workflow_id}",
            {"expected_revision": 1, "name": self.client.batch_key + ":human-edit"},
        )
        await self.obj("stale_apply", "POST", self.flow_root() + "/apply", expected=(409,))
        await self.read_flow()

    async def run_row(self, scenario: ReviewScenario) -> ReviewObservation:
        from scripts.selftest.review_boundary_decisions import (
            concurrent_accept,
            partial_resume,
            stale_approval,
        )

        if scenario.action == "preview_cancel":
            raise HarnessError("SELFTEST_PREVIEW_REQUIRES_OBSERVER_CONTEXT")
        self.scenario_id, self.http = scenario.scenario_id, []
        self.workflow_read_envelope = None
        started, before, offset = (
            datetime.now(UTC),
            await self.inventory.snapshot(),
            len(self.client.receipts),
        )
        checkpoint = None
        approval_id = None
        if scenario.action == "unknown_publish":
            await self.unknown_publish()
        elif scenario.action == "stale_proposal":
            await self.stale_proposal()
        elif scenario.action == "stale_approval":
            approval_id = await stale_approval(self)
        elif scenario.action == "concurrent_accept":
            await concurrent_accept(self)
        elif scenario.action == "partial_resume":
            checkpoint = await partial_resume(self)
        after = await self.inventory.snapshot()
        result = ReviewObservation(
            scenario_id=scenario.scenario_id,
            started_at=started,
            completed_at=datetime.now(UTC),
            before=before,
            checkpoint=checkpoint,
            after=after,
            proposal_id=self.proposal_id,
            proposal_arguments=self.proposal_arguments,
            proposal_result=self.proposal_result,
            proposal_envelope=self.proposal_envelope,
            workflow_read_envelope=self.workflow_read_envelope,
            workflow_id=self.workflow_id,
            approval_id=approval_id,
            http=tuple(self.http),
            calls=tuple(self.client.receipts[offset:]),
        )
        write_json(self.output / scenario.scenario_id / "observation.json", result)
        return result
