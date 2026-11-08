"""Published slots are real references; negative fixtures never count as generation."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.contract_delta_budget import DeltaAPI
from scripts.selftest.contract_delta_contracts import (
    BoundaryObservation,
    DeltaManifest,
    DeltaPhaseFreeze,
    Variant,
)
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.mcp_protocol_runner import ProtocolClient


async def execution_ids(viewer: PublicAPI, project: str) -> tuple[UUID, ...]:
    page = await viewer.object(
        "GET", f"/projects/{project}/workflow-executions?page=1&page_size=100"
    )
    rows = objects_value(page["items"])
    if page["total"] != len(rows) or len(rows) >= 100:
        raise HarnessError("DELTA_EXECUTION_INVENTORY_INCOMPLETE")
    ids = tuple(UUID(text_value(item["id"])) for item in rows)
    if len(ids) != len(set(ids)):
        raise HarnessError("DELTA_EXECUTION_INVENTORY_DUPLICATE")
    return ids


async def boundary(
    writer: DeltaAPI,
    viewer: PublicAPI,
    *,
    frozen: DeltaManifest,
    variant: Variant,
    path: str,
    payload: JsonObject,
    workflow_id: str | None,
    case_id: str | None = None,
    before_fingerprint: str | None = None,
    after_fingerprint: str | None = None,
    proposal_id: str | None = None,
) -> BoundaryObservation:
    project = str(frozen.installation.project_id)
    before = await execution_ids(viewer, project)
    status, response = await writer.response(
        "POST", path, payload, idempotency_key=frozen.batch_key + ":" + variant
    )
    error = object_value(response.get("error", {}))
    code = text_value(error.get("code"))
    after = await execution_ids(viewer, project)
    return BoundaryObservation(
        variant=variant,
        project_id=UUID(project),
        workflow_id=UUID(workflow_id) if workflow_id else None,
        case_id=UUID(case_id) if case_id else None,
        method="POST",
        path=path,
        proposal_id=UUID(proposal_id) if proposal_id else None,
        status_code=status,
        error_code=code,
        trace_present=isinstance(error.get("trace_id", response.get("trace_id")), str),
        before_execution_ids=before,
        after_execution_ids=after,
        request_digest=canonical_digest(payload),
        before_fingerprint=before_fingerprint,
        after_fingerprint=after_fingerprint,
        observed_at=datetime.now(UTC),
    )


def _empty_workflow() -> JsonObject:
    return {
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "开始",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "type": "end",
                "name": "结束",
                "config": {},
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        "run_policy": {"request_budget": 1, "max_runtime_seconds": 60},
    }


async def _proposal(
    client: ProtocolClient,
    writer: PublicAPI,
    frozen: DeltaManifest,
    phase: DeltaPhaseFreeze,
    variant: str,
    definition: JsonObject,
) -> tuple[str, str]:
    proposed = await client.call(
        "flowtest.propose_test_design",
        {
            "project_id": str(frozen.installation.project_id),
            "title": frozen.batch_key + ":" + variant,
            "confidence": 1.0,
            "risk_level": "low",
            "design": phase.asset.design,
            "test_cases": [{"name": frozen.batch_key + ":" + variant, "definition": definition}],
            "idempotency_key": frozen.batch_key + ":" + variant + ":case",
            "dry_run": False,
        },
        scenario_id="ST-MCP-040",
        phase=variant + ":case_proposal",
    )
    base = f"/mcp/write/change-sets/{proposed['id']}"
    detail = object_value((await writer.object("GET", base))["data"])
    items = objects_value(detail["items"])
    design_items = [item for item in items if item["item_type"] == "test_design"]
    case_items = [item for item in items if item["item_type"] == "test_case"]
    if len(items) != 2 or len(design_items) != 1 or len(case_items) != 1:
        raise HarnessError("DELTA_SLOT_PROPOSAL_ITEMS_CHANGED")
    await writer.object(
        "POST", base + f"/items/{design_items[0]['id']}/accept", {"note": "ci_fixture槽位边界"}
    )
    return text_value(proposed["id"]), base + f"/items/{case_items[0]['id']}/accept"


async def _accept_case(
    client: ProtocolClient,
    writer: PublicAPI,
    frozen: DeltaManifest,
    phase: DeltaPhaseFreeze,
    variant: str,
    definition: JsonObject,
) -> tuple[str, JsonObject]:
    proposal, path = await _proposal(client, writer, frozen, phase, variant, definition)
    await writer.object("POST", path, {"note": "ci_fixture槽位边界"})
    detail = object_value(
        (await writer.object("GET", f"/mcp/write/change-sets/{proposal}"))["data"]
    )
    accepted = [item for item in objects_value(detail["items"]) if item["item_type"] == "test_case"]
    if len(accepted) != 1 or accepted[0]["review_status"] != "accepted":
        raise HarnessError("DELTA_SLOT_CASE_NOT_MATERIALIZED")
    identifier = text_value(accepted[0]["materialized_resource_id"])
    case = await writer.object(
        "GET", f"/projects/{frozen.installation.project_id}/test-cases/{identifier}"
    )
    return proposal, case


async def foreign(
    client: ProtocolClient,
    writer: DeltaAPI,
    provisioner: PublicAPI,
    viewer: PublicAPI,
    frozen: DeltaManifest,
    phase: DeltaPhaseFreeze,
    directory: Path,
) -> BoundaryObservation:
    organization = str(frozen.installation.organization_id)
    project = await provisioner.object(
        "POST",
        "/projects",
        {"name": frozen.batch_key + ":foreign-slot", "organization_id": organization},
    )
    other_id = text_value(project["id"])
    if other_id == str(frozen.installation.project_id):
        raise HarnessError("DELTA_FOREIGN_PROJECT_REUSED")
    flow = await provisioner.object(
        "POST",
        f"/projects/{other_id}/workflows",
        {"name": frozen.batch_key + ":foreign-slot", "definition": _empty_workflow()},
    )
    version = await provisioner.object(
        "POST", f"/projects/{other_id}/workflows/{flow['id']}/versions", {}
    )
    if frozen.installation.capture_viewer_id is not None:
        await provisioner.object(
            "PUT",
            f"/projects/{other_id}/members/{frozen.installation.capture_viewer_id}",
            {"user_id": str(frozen.installation.capture_viewer_id), "role": "viewer"},
        )
    observed = await viewer.object("GET", f"/projects/{other_id}/workflows/{flow['id']}")
    if (observed["project_id"], observed["current_version"]) != (other_id, version["version"]):
        raise HarnessError("DELTA_FOREIGN_PUBLICATION_NOT_OBSERVED")
    write_json(
        directory / "foreign-fixture.json",
        {
            "project_id": other_id,
            "workflow_id": flow["id"],
            "version": version["version"],
            "fingerprint": version["fingerprint"],
        },
    )
    definition: JsonObject = {
        "workflow_id": flow["id"],
        "workflow_version": version["version"],
        "environment_id": str(frozen.installation.fixture_environment_id),
    }
    proposal, path = await _proposal(client, writer, frozen, phase, "slot_foreign", definition)
    result = await boundary(
        writer,
        viewer,
        frozen=frozen,
        variant="slot_foreign",
        path=path,
        payload={"note": "ci_fixture槽位边界"},
        workflow_id=text_value(flow["id"]),
        proposal_id=proposal,
    )
    detail = object_value(
        (await writer.object("GET", f"/mcp/write/change-sets/{proposal}"))["data"]
    )
    row = next(item for item in objects_value(detail["items"]) if item["item_type"] == "test_case")
    return result.model_copy(
        update={
            "workflow_project_id": UUID(other_id),
            "workflow_version": version["version"],
            "workflow_fingerprint": version["fingerprint"],
            "proposal_item_id": UUID(text_value(row["id"])),
            "proposal_review_status": row["review_status"],
            "materialized_case_id": row["materialized_resource_id"],
            "slot": phase.slot,
        }
    )


async def unpublished(
    client: ProtocolClient,
    writer: DeltaAPI,
    viewer: PublicAPI,
    frozen: DeltaManifest,
    phase: DeltaPhaseFreeze,
) -> BoundaryObservation:
    base = f"/projects/{frozen.installation.project_id}"
    flow = await writer.object(
        "POST",
        base + "/workflows",
        {"name": frozen.batch_key + ":unpublished-slot", "definition": _empty_workflow()},
    )
    if flow["current_version"] is not None:
        raise HarnessError("DELTA_NEGATIVE_FIXTURE_ALREADY_PUBLISHED")
    proposal, case = await _accept_case(
        client,
        writer,
        frozen,
        phase,
        "slot_unpublished",
        {
            "workflow_id": flow["id"],
            "environment_id": str(frozen.installation.fixture_environment_id),
        },
    )
    result = await boundary(
        writer,
        viewer,
        frozen=frozen,
        variant="slot_unpublished",
        path=base + f"/test-cases/{case['id']}/versions",
        payload={},
        workflow_id=text_value(flow["id"]),
        case_id=text_value(case["id"]),
        proposal_id=proposal,
    )
    unchanged = await viewer.object("GET", base + f"/test-cases/{case['id']}")
    return result.model_copy(
        update={
            "workflow_project_id": frozen.installation.project_id,
            "case_current_version": unchanged["current_version"],
            "slot": phase.slot,
            "materialized_case_id": UUID(text_value(case["id"])),
            "proposal_review_status": "accepted",
        }
    )


async def drift(
    client: ProtocolClient,
    writer: DeltaAPI,
    viewer: PublicAPI,
    frozen: DeltaManifest,
    before: DeltaPhaseFreeze,
    after: DeltaPhaseFreeze,
) -> BoundaryObservation:
    base = f"/projects/{frozen.installation.project_id}/test-cases"
    original = object_value(before.asset.case.version["definition"])
    proposal, case = await _accept_case(client, writer, frozen, before, "slot_drift", original)
    changed = {
        **original,
        "workflow_id": after.asset.workflow.workflow["id"],
        "workflow_version": after.asset.workflow.version["version"],
    }
    updated = await writer.object("PATCH", base + f"/{case['id']}", {"definition": changed})
    result = await boundary(
        writer,
        viewer,
        frozen=frozen,
        variant="slot_drift",
        path=base + f"/{case['id']}/runs",
        payload={
            "source": "draft",
            "publish_draft": True,
            "expected_draft_fingerprint": case["draft_fingerprint"],
        },
        workflow_id=text_value(after.asset.workflow.workflow["id"]),
        case_id=text_value(case["id"]),
        before_fingerprint=text_value(case["draft_fingerprint"]),
        after_fingerprint=text_value(updated["draft_fingerprint"]),
        proposal_id=proposal,
    )
    unchanged = await viewer.object("GET", base + f"/{case['id']}")
    return result.model_copy(
        update={
            "workflow_project_id": frozen.installation.project_id,
            "workflow_version": after.asset.workflow.version["version"],
            "workflow_fingerprint": after.asset.workflow.version["fingerprint"],
            "case_current_version": unchanged["current_version"],
            "slot": before.slot,
            "materialized_case_id": UUID(text_value(case["id"])),
            "proposal_review_status": "accepted",
        }
    )
