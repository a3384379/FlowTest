"""Assemble published assets solely from MCP receipts and read-only public readback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from scripts.selftest.contracts import (
    ApiSource,
    Contract,
    HostEvidence,
    McpCallReceipt,
    ProposalEvidence,
    Sha256,
    canonical_digest,
)
from scripts.selftest.generation_lifecycle import LifecycleAsset
from scripts.selftest.host_attempts import AttemptRecord
from scripts.selftest.host_contracts import HostAttemptResult
from scripts.selftest.host_gateway import BoundedGateway
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.host_observer import HostFrozenTrail, verify_host_trail
from scripts.selftest.host_sources import FrozenHostCase, FrozenHostSource, reviewed_workflows
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    object_value,
    objects_value,
    text_value,
)
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.review_fixture_driver import ReviewedCase, ReviewedWorkflow

from app.schemas.self_tests import AssistedLineage
from app.schemas.test_assets import PublishedTestCaseDefinition


class HostLifecycleSelection(Contract):
    target_project_id: UUID
    source_document_digest: Sha256
    bound_document_digest: Sha256
    source_reused: bool
    created_resource_name: str = Field(min_length=1, max_length=200)
    updated_resource_name: str = Field(min_length=1, max_length=200)


class HostSelection(Contract):
    scenario_id: str = Field(pattern=r"^ST-[A-Z]+-[0-9]{3}$")
    variant_key: str = Field(default="default", min_length=1, max_length=120)
    api_source: ApiSource
    design_kind: str = Field(min_length=1, max_length=60)
    additional_api_sources: tuple[ApiSource, ...] = Field(default=(), max_length=99)
    lifecycle: HostLifecycleSelection | None = None

    @model_validator(mode="after")
    def lifecycle_inputs(self) -> HostSelection:
        if bool(self.additional_api_sources) != (self.lifecycle is not None):
            raise ValueError("multi-operation tasks require frozen lifecycle inputs")
        return self


class HostRevision(Contract):
    scenario_id: str
    variant_key: str
    origin_batch_key: str
    fixture_batch_key: str | None
    lineage: AssistedLineage


class HostMaterialization(Contract):
    attempt_id: UUID
    authorization_digest: Sha256
    task_digest: Sha256
    catalog_digest: Sha256
    host: HostEvidence
    assets: tuple[GeneratedAsset | LifecycleAsset, ...] = Field(min_length=1, max_length=3)
    trail: HostFrozenTrail
    revisions: tuple[HostRevision, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def strict_designs(self) -> HostMaterialization:
        from scripts.selftest.generation_lifecycle import combine_generated_designs

        from app.domain.test_design import TestDesignDocument, fingerprint_design

        if self.revisions and (
            len(self.revisions) != len(self.assets)
            or {(item.scenario_id, item.variant_key) for item in self.revisions}
            != {(item.scenario_id, item.variant_key) for item in self.assets}
        ):
            raise ValueError("assisted revisions must preserve the full frozen asset set")
        for asset in self.assets:
            if isinstance(asset, GeneratedAsset):
                valid = (
                    fingerprint_design(TestDesignDocument.model_validate(asset.design))
                    == asset.design_fingerprint
                )
            else:
                combined, composition = combine_generated_designs(asset.operations)
                valid = (
                    combined.model_dump(mode="json") == asset.combined_design
                    and composition == asset.design_composition
                    and fingerprint_design(combined) == asset.combined_design_fingerprint
                )
            if not valid:
                raise ValueError("materialized generated design source changed")
        return self


def _calls(
    gateway: BoundedGateway,
    scenario: str,
    *,
    transport: Literal["stdio", "streamable-http"],
    sdk_version: str,
    protocol_version: str,
) -> tuple[McpCallReceipt, ...]:
    values = []
    for item in gateway.receipts:
        if item.outcome != "completed" or item.completed_at is None or item.result_digest is None:
            raise HarnessError("HOST_UNKNOWN_TOOL_RESULT_BLOCKS_MATERIALIZATION")
        values.append(
            McpCallReceipt(
                call_id=f"host-{item.attempt_id}-{item.sequence}",
                batch_key=gateway.authorization.batch_key,
                scenario_id=scenario,
                phase=item.phase,
                tool_name=item.tool_name,
                transport=transport,
                sdk_version=sdk_version,
                protocol_version=protocol_version,
                request_digest=item.request_digest,
                result_digest=item.result_digest,
                catalog_digest=item.catalog_digest,
                completed_at=item.completed_at,
                success=item.business_success is True,
            )
        )
    return tuple(values)


async def _case(
    api: PublicAPI, project: UUID, frozen: FrozenHostCase, *, grant: VerifiedGrant
) -> ReviewedCase:
    change = object_value(
        (await api.object("GET", f"/mcp/write/change-sets/{frozen.proposal_id}"))["data"]
    )
    items = [item for item in objects_value(change["items"]) if item["id"] == str(frozen.item_id)]
    if (
        len(items) != 1
        or change.get("project_id") != str(project)
        or change.get("source_fingerprint") != frozen.proposal_fingerprint
    ):
        raise HarnessError("HOST_CASE_REVIEW_SOURCE_CHANGED")
    item = items[0]
    immutable = {
        "id": item["id"],
        "item_type": item["item_type"],
        "action": item["action"],
        "proposed_content": item["proposed_content"],
    }
    if canonical_digest(immutable) != frozen.source_snapshot_digest:
        raise HarnessError("HOST_CASE_REVIEW_CONTENT_CHANGED")
    if (
        item.get("review_status") != "accepted"
        or item.get("materialized_resource_type") != "test_case"
        or not item.get("reviewed_by_id")
        or not item.get("materialized_resource_id")
    ):
        raise HarnessError("HOST_WAITING_FOR_CASE_REVIEW")
    identifier = text_value(item["materialized_resource_id"])
    if item["reviewed_by_id"] not in {str(value) for value in grant.authorization.reviewer_ids}:
        raise HarnessError("HOST_CASE_REVIEWER_NOT_AUTHORIZED")
    base = f"/projects/{project}/test-cases/{identifier}"
    case = await api.object("GET", base)
    versions = objects_value(await api.request("GET", base + "/versions"))
    selected = [version for version in versions if version["version"] == case["current_version"]]
    if len(selected) != 1:
        raise HarnessError("HOST_WAITING_FOR_CASE_PUBLICATION")
    definition = PublishedTestCaseDefinition.model_validate(selected[0]["definition"])
    if (
        canonical_digest(definition.model_dump(mode="json", exclude_none=True))
        != frozen.definition_digest
    ):
        raise HarnessError("HOST_PUBLISHED_CASE_DEFINITION_CHANGED")
    return ReviewedCase(
        case=case,
        version=selected[0],
        proposal=ProposalEvidence(
            project_id=project,
            proposal_id=frozen.proposal_id,
            item_id=frozen.item_id,
            route="controlled_write",
            review_status="accepted",
            materialized_resource_id=UUID(identifier),
            content_fingerprint=frozen.proposal_fingerprint,
            review_mode=grant.authorization.review_mode,
            reviewer_id=UUID(text_value(item["reviewed_by_id"])),
        ),
    )


def _selection(source: FrozenHostSource, selections: tuple[HostSelection, ...]) -> HostSelection:
    kinds = [
        item.kind for item in source.combined_design.scenarios if item.id == source.scenario_id
    ]
    if source.integration is not None:
        kinds = ["integration_lifecycle"]
    selected = [
        item
        for item in selections
        if (item.api_source, *item.additional_api_sources) == source.api_sources
        and kinds == [item.design_kind]
    ]
    if len(selected) != 1:
        raise HarnessError("HOST_FROZEN_TASK_SELECTION_CHANGED")
    return selected[0]


def _asset(
    source: FrozenHostSource,
    chosen: HostSelection,
    workflow: ReviewedWorkflow,
    case: ReviewedCase,
    calls: tuple[McpCallReceipt, ...],
    generated_at: datetime,
) -> GeneratedAsset | LifecycleAsset:
    common = {
        "scenario_id": chosen.scenario_id,
        "variant_key": chosen.variant_key,
        "compilation_fingerprint": source.compilation_fingerprint,
        "oracle_bindings": source.oracle_bindings,
        "workflow": workflow,
        "case": case,
        "calls": calls,
        "generated_at": generated_at,
        "frozen_at": datetime.now(UTC),
    }
    integration = source.integration
    if integration is None:
        return GeneratedAsset.model_validate(
            {
                **common,
                "api_source": source.api_source,
                "design": source.combined_design.model_dump(mode="json"),
                "design_fingerprint": source.design_fingerprint,
            }
        )
    lifecycle = chosen.lifecycle
    if lifecycle is None:
        raise HarnessError("HOST_LIFECYCLE_FROZEN_INPUT_REQUIRED")
    return LifecycleAsset.model_validate(
        {
            **common,
            **lifecycle.model_dump(),
            "operations": integration.operations,
            "context": integration.context,
            "integration_plan": integration.plan.model_dump(mode="json"),
            "combined_design": integration.combined_design.model_dump(mode="json"),
            "combined_design_fingerprint": source.design_fingerprint,
            "design_composition": integration.design_composition,
        }
    )


async def assemble_materialized(
    api: PublicAPI,
    *,
    grant: VerifiedGrant,
    gateway: BoundedGateway,
    record: AttemptRecord,
    sources: tuple[FrozenHostSource, ...],
    cases: tuple[FrozenHostCase, ...],
    selections: tuple[HostSelection, ...],
    workflow_result: HostAttemptResult,
    case_result: HostAttemptResult,
    transport: Literal["stdio", "streamable-http"],
    sdk_version: str,
    protocol_version: str,
    trail: HostFrozenTrail,
) -> HostMaterialization:
    if record.state != "waiting_case_review" or record.authorization_digest != grant.digest:
        raise HarnessError("HOST_MATERIALIZATION_STATE_INVALID")
    if len(sources) != len(selections) or len(cases) != len(selections):
        raise HarnessError("HOST_MATERIALIZATION_REQUIRED_SET_INCOMPLETE")
    bindings = await reviewed_workflows(api, sources, reviewer_ids=grant.authorization.reviewer_ids)
    assets = []
    for source, binding in zip(sources, bindings, strict=True):
        chosen = _selection(source, selections)
        matching = [
            case
            for case in cases
            if case.workflow_id == binding.workflow_id and case.workflow_version == binding.version
        ]
        if len(matching) != 1:
            raise HarnessError("HOST_PUBLISHED_CASE_BINDING_CHANGED")
        case = await _case(api, source.project_id, matching[0], grant=grant)
        base = f"/projects/{source.project_id}/workflows/{binding.workflow_id}"
        workflow = await api.object("GET", base)
        versions = objects_value(await api.request("GET", base + "/versions"))
        selected = [
            item
            for item in versions
            if item["version"] == binding.version and item["fingerprint"] == binding.fingerprint
        ]
        if len(selected) != 1:
            raise HarnessError("HOST_PUBLISHED_WORKFLOW_BINDING_CHANGED")
        proposal = await api.object(
            "GET", f"/projects/{source.project_id}/flow-specs/change-sets/{source.proposal_id}"
        )
        if (
            proposal.get("review_status") != "accepted"
            or proposal.get("materialized_workflow_id") != str(binding.workflow_id)
            or proposal.get("source_fingerprint") != source.proposal_fingerprint
        ):
            raise HarnessError("HOST_WORKFLOW_REVIEW_CHANGED_DURING_READBACK")
        reviewed = ReviewedWorkflow(
            workflow=workflow,
            version=selected[0],
            proposal=ProposalEvidence(
                project_id=source.project_id,
                proposal_id=source.proposal_id,
                route="flow_spec",
                review_status="accepted",
                materialized_resource_id=binding.workflow_id,
                content_fingerprint=source.proposal_fingerprint,
                review_mode=grant.authorization.review_mode,
                reviewer_id=UUID(text_value(proposal["reviewed_by_id"])),
            ),
        )
        calls = _calls(
            gateway,
            chosen.scenario_id,
            transport=transport,
            sdk_version=sdk_version,
            protocol_version=protocol_version,
        )
        assets.append(_asset(source, chosen, reviewed, case, calls, record.created_at))
    host = HostEvidence(
        host=grant.authorization.host_id,
        model=grant.authorization.model,
        skill_digest=grant.authorization.skill_digest,
        prompt_digest=canonical_digest(
            {"workflow": workflow_result.prompt_digest, "case": case_result.prompt_digest}
        ),
        authorized_budget_digest=grant.digest,
        actual_tool_calls=len(gateway.receipts),
    )
    if trail.host != host or any(verify_host_trail(trail, grant, asset.calls) for asset in assets):
        raise HarnessError("HOST_INDEPENDENT_TRAIL_CHECK_FAILED")
    return HostMaterialization(
        attempt_id=record.attempt_id,
        authorization_digest=grant.digest,
        task_digest=grant.authorization.task_digest,
        catalog_digest=gateway.catalog_digest,
        host=host,
        assets=tuple(assets),
        trail=trail,
    )
