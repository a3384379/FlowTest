"""Read approved human revisions into a new native batch without any model invocation."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import jwt
from pydantic import JsonValue
from scripts.selftest.contracts import ProposalEvidence, canonical_digest
from scripts.selftest.generation_lifecycle import LifecycleAsset
from scripts.selftest.host_contracts import HostAuthorization
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.host_materialized import HostMaterialization, HostRevision
from scripts.selftest.host_observer import verify_host_trail
from scripts.selftest.host_product_bridge import materialized_source
from scripts.selftest.host_revisions import AssistedRequest, AssistedSelection
from scripts.selftest.host_runtime_config import HostRuntimeConfig, private_file
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.review_fixture_driver import ReviewedCase, ReviewedWorkflow

from app.engine.contracts import WorkflowDefinition
from app.schemas.self_tests import (
    AgentTaskResponse,
    AssistedLineage,
    BatchResponse,
    GenerationSummary,
    RevisionDifference,
    SourceReference,
)
from app.schemas.test_assets import PublishedTestCaseDefinition

if TYPE_CHECKING:
    from scripts.selftest.host_prompts import HostTask


def differences(
    before: JsonValue, after: JsonValue, path: str = "$"
) -> tuple[RevisionDifference, ...]:
    values: list[RevisionDifference] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            suffix = (
                "." + key
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                else "[" + json.dumps(key, ensure_ascii=False) + "]"
            )
            if key in before and key in after:
                values.extend(differences(before[key], after[key], path + suffix))
            else:
                values.append(
                    RevisionDifference(
                        path=path + suffix,
                        before_digest=canonical_digest(before[key]) if key in before else None,
                        after_digest=canonical_digest(after[key]) if key in after else None,
                    )
                )
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            values.extend(differences(left, right, f"{path}[{index}]"))
    elif canonical_digest(before) != canonical_digest(after):
        values.append(
            RevisionDifference(
                path=path,
                before_digest=canonical_digest(before),
                after_digest=canonical_digest(after),
            )
        )
    if len(values) > 200:
        raise HarnessError("HOST_ASSISTED_DIFF_TOO_LARGE")
    return tuple(values)


def archived_grant(
    config: HostRuntimeConfig, expected_digest: str, frozen_at: datetime
) -> VerifiedGrant:
    """Verify an archived approval at its recorded time; never use it for launch/readiness."""
    for path in config.archived_authorization_files:
        claims = jwt.decode(
            private_file(path).decode().strip(),
            private_file(config.approval_key_file),
            algorithms=[config.approval_algorithm],
            issuer=config.approval_issuer,
            audience=config.approval_audience,
            options={
                "require": ["iss", "aud", "sub", "exp", "iat"],
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
        authorization = HostAuthorization.model_validate(claims["authorization"])
        digest = canonical_digest(authorization.model_dump(mode="json"))
        if digest != expected_digest:
            continue
        if (
            digest not in config.allowed_authorization_digests
            or claims["sub"] != authorization.approved_by
        ):
            raise HarnessError("HOST_ARCHIVED_AUTHORIZATION_NOT_APPROVED")
        if not float(claims["iat"]) <= frozen_at.timestamp() <= float(claims["exp"]):
            raise HarnessError("HOST_ARCHIVED_AUTHORIZATION_TIME_CHANGED")
        return VerifiedGrant(authorization, digest)
    raise HarnessError("HOST_ARCHIVED_AUTHORIZATION_MISSING")


def _definition(workflow: ReviewedWorkflow, case: ReviewedCase) -> JsonValue:
    return {
        "workflow": WorkflowDefinition.model_validate(workflow.version["definition"]).model_dump(
            mode="json", exclude_none=True
        ),
        "case": PublishedTestCaseDefinition.model_validate(case.version["definition"]).model_dump(
            mode="json", exclude_none=True
        ),
    }


async def _flow(
    api: PublicAPI, project: UUID, chosen: AssistedSelection, grant: VerifiedGrant
) -> ReviewedWorkflow:
    base = f"/projects/{project}"
    proposal = await api.object(
        "GET", base + f"/flow-specs/change-sets/{chosen.workflow_proposal_id}"
    )
    if (
        proposal.get("review_status") != "accepted"
        or not proposal.get("applied_at")
        or proposal.get("created_by_id") != str(chosen.editor_id)
        or proposal.get("reviewed_by_id")
        not in {str(item) for item in grant.authorization.reviewer_ids}
        or not proposal.get("materialized_workflow_id")
    ):
        raise HarnessError("HOST_ASSISTED_WORKFLOW_REVIEW_REQUIRED")
    identifier = text_value(proposal["materialized_workflow_id"])
    workflow = await api.object("GET", base + f"/workflows/{identifier}")
    versions = objects_value(await api.request("GET", base + f"/workflows/{identifier}/versions"))
    selected = [item for item in versions if item["version"] == workflow["current_version"]]
    if len(selected) != 1:
        raise HarnessError("HOST_ASSISTED_WORKFLOW_PUBLICATION_REQUIRED")
    visual = await api.object(
        "GET", base + f"/flow-specs/change-sets/{chosen.workflow_proposal_id}/visual-proposal"
    )
    wanted = WorkflowDefinition.model_validate(visual["proposed_definition"]).model_dump(
        mode="json", exclude_none=True
    )
    actual = WorkflowDefinition.model_validate(selected[0]["definition"]).model_dump(
        mode="json", exclude_none=True
    )
    if wanted != actual:
        raise HarnessError("HOST_ASSISTED_WORKFLOW_CHANGED_AFTER_REVIEW")
    return ReviewedWorkflow(
        workflow=workflow,
        version=selected[0],
        proposal=ProposalEvidence(
            project_id=project,
            proposal_id=chosen.workflow_proposal_id,
            route="flow_spec",
            review_status="accepted",
            materialized_resource_id=UUID(identifier),
            content_fingerprint=text_value(proposal["source_fingerprint"]),
            review_mode=grant.authorization.review_mode,
            reviewer_id=UUID(text_value(proposal["reviewed_by_id"])),
        ),
    )


async def _case(
    api: PublicAPI, project: UUID, chosen: AssistedSelection, grant: VerifiedGrant
) -> ReviewedCase:
    change = object_value(
        (await api.object("GET", f"/mcp/write/change-sets/{chosen.case_proposal_id}"))["data"]
    )
    items = [
        item for item in objects_value(change["items"]) if item["id"] == str(chosen.case_item_id)
    ]
    if len(items) != 1 or change.get("project_id") != str(project):
        raise HarnessError("HOST_ASSISTED_CASE_SOURCE_REQUIRED")
    item = items[0]
    if (
        item.get("item_type") != "test_case"
        or item.get("review_status") != "accepted"
        or item.get("materialized_resource_type") != "test_case"
        or item.get("reviewed_by_id")
        not in {str(value) for value in grant.authorization.reviewer_ids}
        or not item.get("materialized_resource_id")
    ):
        raise HarnessError("HOST_ASSISTED_CASE_REVIEW_REQUIRED")
    identifier = text_value(item["materialized_resource_id"])
    base = f"/projects/{project}/test-cases/{identifier}"
    case = await api.object("GET", base)
    versions = objects_value(await api.request("GET", base + "/versions"))
    selected = [value for value in versions if value["version"] == case["current_version"]]
    if len(selected) != 1:
        raise HarnessError("HOST_ASSISTED_CASE_PUBLICATION_REQUIRED")
    proposed = object_value(item["proposed_content"])["definition"]
    wanted = PublishedTestCaseDefinition.model_validate(proposed).model_dump(
        mode="json", exclude_none=True
    )
    actual = PublishedTestCaseDefinition.model_validate(selected[0]["definition"]).model_dump(
        mode="json", exclude_none=True
    )
    if wanted != actual:
        raise HarnessError("HOST_ASSISTED_CASE_CHANGED_AFTER_REVIEW")
    return ReviewedCase(
        case=case,
        version=selected[0],
        proposal=ProposalEvidence(
            project_id=project,
            proposal_id=chosen.case_proposal_id,
            item_id=chosen.case_item_id,
            route="controlled_write",
            review_status="accepted",
            materialized_resource_id=UUID(identifier),
            content_fingerprint=text_value(change["source_fingerprint"]),
            review_mode=grant.authorization.review_mode,
            reviewer_id=UUID(text_value(item["reviewed_by_id"])),
        ),
    )


async def _summary(
    api: PublicAPI, project: UUID, batch_id: UUID
) -> tuple[BatchResponse, GenerationSummary]:
    base = f"/projects/{project}/self-tests/runs/{batch_id}"
    batch = BatchResponse.model_validate(await api.object("GET", base))
    summary = GenerationSummary.model_validate(await api.object("GET", base + "/generation"))
    if (
        batch.sealed_at is None
        or batch.evidence_integrity != "complete"
        or batch.cleanup_status != "completed"
    ):
        raise HarnessError("HOST_ASSISTED_BEFORE_EVIDENCE_INCOMPLETE")
    return batch, summary


async def materialize_assisted(
    api: PublicAPI,
    *,
    task: AgentTaskResponse,
    frozen_task: HostTask,
    grant: VerifiedGrant,
    config: HostRuntimeConfig,
    directory: Path,
    attempt_id: UUID | None = None,
) -> HostMaterialization:
    request = frozen_task.assisted
    if request is None:
        raise HarnessError("HOST_ASSISTED_REQUEST_REQUIRED")
    if (
        task.frozen_manifest is None
        or task.frozen_manifest.assisted_before_batch_id != request.before_batch_id
    ):
        raise HarnessError("HOST_ASSISTED_FROZEN_BEFORE_BATCH_CHANGED")
    _, before_summary = await _summary(api, task.project_id, request.before_batch_id)
    selected = {(item.scenario_id, item.variant_key): item for item in before_summary.sources}
    chosen = {(item.scenario_id, item.variant_key): item for item in request.selections}
    if not set(chosen) <= set(selected):
        raise HarnessError("SELFTEST_ASSISTED_BEFORE_SOURCE_MISSING")
    origins = {_origin(selected[key], request.before_batch_id) for key in chosen}
    if len(origins) != 1:
        raise HarnessError("HOST_ASSISTED_MIXED_ORIGIN_ATTEMPTS")
    origin_id = next(iter(origins))
    origin_batch, origin_summary = await _summary(api, task.project_id, origin_id)
    original = HostMaterialization.model_validate(
        read_json(directory.parent / str(origin_id) / "host-materialized.json")
    )
    before = HostMaterialization.model_validate(
        read_json(directory.parent / str(request.before_batch_id) / "host-materialized.json")
    )
    archived = archived_grant(
        config,
        original.host.authorized_budget_digest,
        max(item.frozen_at for item in original.assets),
    )
    if any(verify_host_trail(original.trail, archived, item.calls) for item in original.assets):
        raise HarnessError("HOST_ASSISTED_UNKNOWN_BEFORE_TOOL_RESULT")
    original_sources = {
        (item.scenario_id, item.variant_key): item for item in origin_summary.sources
    }
    for item in original.assets:
        frozen = original_sources[(item.scenario_id, item.variant_key)]
        if (
            canonical_digest(item.model_dump(mode="json")) != frozen.generation_manifest.sha256
            or materialized_source(original, item, frozen.generation_manifest) != frozen
        ):
            raise HarnessError("HOST_ASSISTED_ORIGIN_SOURCE_CHANGED")
    if (
        original.host.host != grant.authorization.host_id
        or original.host.model != grant.authorization.model
        or original.host.skill_digest != grant.authorization.skill_digest
    ):
        raise HarnessError("HOST_ASSISTED_ORIGIN_IDENTITY_CHANGED")
    assets, revisions = [], []
    for key, wanted in chosen.items():
        revised, revision = await _revision_asset(
            api,
            task,
            frozen_task,
            grant,
            request,
            before,
            selected[key],
            key,
            wanted,
            origin_id,
            origin_batch.batch_key,
        )
        assets.append(revised)
        revisions.append(revision)
    result = HostMaterialization(
        attempt_id=attempt_id or uuid4(),
        authorization_digest=grant.digest,
        task_digest=grant.authorization.task_digest,
        catalog_digest=original.catalog_digest,
        host=original.host,
        assets=tuple(assets),
        trail=original.trail,
        revisions=tuple(revisions),
    )
    write_json(directory / "host-materialized.json", result)
    return result


def _origin(source: SourceReference, before_batch: UUID) -> UUID:
    lineage = source.assisted
    return before_batch if lineage is None else lineage.origin_batch_id


async def _revision_asset(
    api: PublicAPI,
    task: AgentTaskResponse,
    frozen_task: HostTask,
    grant: VerifiedGrant,
    request: AssistedRequest,
    before: HostMaterialization,
    frozen: SourceReference,
    key: tuple[str, str],
    wanted: AssistedSelection,
    origin_id: UUID,
    origin_key: str,
) -> tuple[GeneratedAsset | LifecycleAsset, HostRevision]:
    matches = [item for item in before.assets if (item.scenario_id, item.variant_key) == key]
    if (
        len(matches) != 1
        or canonical_digest(matches[0].model_dump(mode="json")) != frozen.generation_manifest.sha256
        or materialized_source(before, matches[0], frozen.generation_manifest) != frozen
    ):
        raise HarnessError("HOST_ASSISTED_BEFORE_SOURCE_CHANGED")
    asset = matches[0]
    workflow = await _flow(api, task.project_id, wanted, grant)
    case = await _case(api, task.project_id, wanted, grant)
    delta = differences(_definition(asset.workflow, asset.case), _definition(workflow, case))
    if not delta:
        raise HarnessError("HOST_ASSISTED_NO_ACTUAL_REVISION")
    lineage = AssistedLineage(
        authorization_digest=grant.digest,
        before_batch_id=request.before_batch_id,
        origin_batch_id=origin_id,
        before_source_digest=canonical_digest(frozen.model_dump(mode="json")),
        before_workflow=frozen.workflow,
        before_case=frozen.case,
        before_workflow_proposal=frozen.workflow_proposal,
        before_case_proposal=frozen.case_proposal,
        editor_id=wanted.editor_id,
        workflow_reviewer_id=workflow.proposal.reviewer_id,
        case_reviewer_id=case.proposal.reviewer_id,
        reason_digest=canonical_digest(wanted.reason),
        diff_digest=canonical_digest([item.model_dump(mode="json") for item in delta]),
        changes=delta,
        revision_number=1 + (frozen.assisted.revision_number if frozen.assisted else 0),
        review_mode=grant.authorization.review_mode,
    )
    update = {"workflow": workflow, "case": case, "frozen_at": datetime.now(UTC)}
    if not isinstance(asset, GeneratedAsset):
        choice = next(
            item for item in frozen_task.selections if (item.scenario_id, item.variant_key) == key
        )
        if choice.lifecycle is None:
            raise HarnessError("HOST_ASSISTED_LIFECYCLE_INPUT_REQUIRED")
        update.update(choice.lifecycle.model_dump())
    revised = asset.model_copy(update=update)
    revision = HostRevision(
        scenario_id=key[0],
        variant_key=key[1],
        origin_batch_key=origin_key,
        fixture_batch_key=origin_key if isinstance(asset, GeneratedAsset) else None,
        lineage=lineage,
    )

    return revised, revision
