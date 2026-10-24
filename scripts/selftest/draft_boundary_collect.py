"""Only explicit ordinary reviewer calls accept and apply; publication is never called."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.compile_boundary_collect import CompilerActors, proposals
from scripts.selftest.compile_boundary_contracts import CompileBoundaryObservation
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.draft_boundary_contracts import DraftBoundaryObservation
from scripts.selftest.initialization_inventory import inventory
from scripts.selftest.io import HarnessError, JsonObject, object_value, objects_value, text_value
from scripts.selftest.product_boundary_common import ProductWorld
from scripts.selftest.quality_protocol import QualityProtocol, reserve_protocol_setup
from scripts.selftest.run import _protocol


def arguments(row: CompileBoundaryObservation, route: str, batch: str) -> tuple[str, JsonObject]:
    origin = object_value(row.request["origin"])
    if route == "quick":
        return "flowtest.propose_simple_flow", {
            "request": {
                "project_id": row.request["project_id"],
                "environment_id": row.request["environment_id"],
                "name": "草稿边界" + batch,
                "task_ref": batch,
                "scenario_key": "draft_only",
                "steps": [
                    {
                        "key": "request",
                        "name": "固定API",
                        "api": {"api_definition_id": origin["api_definition_id"], "version": 1},
                        "assertions": [
                            {"target": "status_code", "operator": "status_code", "expected": 201}
                        ],
                    }
                ],
            },
            "idempotency_key": batch + ":quick",
        }
    if row.response is None:
        raise HarnessError("DRAFT_BOUNDARY_COMPILATION_REQUIRED")
    payload = object_value(objects_value(row.response["scenarios"])[0]["executable_payload"])
    context = object_value(row.request["context_binding"])
    spec = object_value(payload["spec"])
    return "flowtest.propose_flow_draft", {
        "project_id": row.request["project_id"],
        "context_id": context["context_id"],
        "context_revision_id": context["context_revision_id"],
        "spec": {**spec, "name": (batch + ":" + text_value(spec["name"]))[:200]},
        "operation_mappings": payload["operation_mappings"],
        "operation_version_mappings": payload["operation_version_mappings"],
        "service_mappings": payload["service_mappings"],
        "dry_run": False,
        "idempotency_key": batch + ":flow-spec",
    }


async def one(
    world: ProductWorld, client: QualityProtocol, source: CompileBoundaryObservation, route: str
) -> DraftBoundaryObservation:
    before = await inventory(world.viewer, world.config.project_id)
    before_proposals = await proposals(world)
    name, payload = arguments(source, route, client.batch_key)
    result = await client.call(name, payload, scenario_id=route + "_draft", phase="draft_only")
    identifier = UUID(
        text_value(result["proposal_id"] if route == "quick" else result["change_set_id"])
    )
    root = f"/projects/{world.config.project_id}/flow-specs/change-sets/{identifier}"
    visual = await world.viewer.object("GET", root + "/visual-proposal")
    pending = object_value(visual["proposal"])
    proposed = await inventory(world.viewer, world.config.project_id)
    await world.user.object(
        "POST",
        root + "/review",
        {"accept": True, "note": "隔离自测草稿边界; review_mode=ci_fixture; 不发布或执行"},
    )
    applied = await world.user.object("POST", root + "/apply")
    workflow = await world.viewer.object(
        "GET", f"/projects/{world.config.project_id}/workflows/{applied['workflow_id']}"
    )
    versions = await world.viewer.request(
        "GET", f"/projects/{world.config.project_id}/workflows/{applied['workflow_id']}/versions"
    )
    sealed = await world.viewer.object("GET", root)
    actor = await world.user.object("GET", "/auth/me")
    if actor["is_system_admin"] is not False:
        raise HarnessError("DRAFT_BOUNDARY_ORDINARY_REVIEWER_REQUIRED")
    definition = object_value(workflow["draft_definition"])
    apis = [
        object_value(node["config"])
        for node in objects_value(definition["nodes"])
        if node["type"] == "api"
    ]
    return DraftBoundaryObservation(
        transport=client.transport,
        route=route,
        project_id=world.config.project_id,
        api_id=UUID(text_value(object_value(source.request["origin"])["api_definition_id"])),
        api_version=1,
        proposal_id=identifier,
        proposal_status_before=text_value(pending["status"]),
        proposal_review_before=text_value(pending["review_status"]),
        proposal_applied_before=pending["applied_at"],
        proposal_status_after=text_value(sealed["status"]),
        proposal_review_after=text_value(sealed["review_status"]),
        applied_at=sealed["applied_at"],
        reviewer_id=UUID(text_value(sealed["reviewed_by_id"])),
        expected_reviewer_id=UUID(text_value(actor["id"])),
        reviewer_is_admin=False,
        workflow_id=UUID(text_value(workflow["id"])),
        workflow_project_id=UUID(text_value(workflow["project_id"])),
        current_version=workflow["current_version"],
        published_version_count=len(objects_value(versions)),
        proposed_digest=canonical_digest(visual["proposed_definition"]),
        draft_digest=canonical_digest(definition),
        api_references=tuple(UUID(text_value(api["api_definition_id"])) for api in apis),
        api_versions=tuple(api["api_version"] for api in apis),
        before=before,
        proposed=proposed,
        after=await inventory(world.viewer, world.config.project_id),
        proposal_ids_before=before_proposals,
        proposal_ids_after=await proposals(world),
        call=client.receipts[-1],
        completed_at=datetime.now(UTC),
    )


async def collect_drafts(
    world: ProductWorld,
    issued: CompilerActors,
    rows: tuple[CompileBoundaryObservation, ...],
    output: Path,
) -> tuple[DraftBoundaryObservation, ...]:
    result = []
    for transport in ("stdio", "streamable-http"):
        reserve_protocol_setup(world.budget)
        async with _protocol(
            world.stack,
            transport,
            issued.full,
            "draft-" + world.stack.nonce[:8] + transport,
            output / transport / "drafts",
            stack_directory=world.directory,
            deadline=world.deadline,
        ) as protocol:
            client = QualityProtocol(protocol, world.budget, world.deadline)
            source = next(
                row for row in rows if row.transport == transport and row.key == "positive"
            )
            for route in ("quick", "flow_spec"):
                result.append(await one(world, client, source, route))
    return tuple(result)
