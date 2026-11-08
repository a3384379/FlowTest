"""Real target drift is refused before a new business run; B remains recursion-blocked."""

from datetime import UTC, datetime
from uuid import uuid4

from scripts.selftest.initialization_inventory import inventory
from scripts.selftest.io import HarnessError, JsonObject, read_json
from scripts.selftest.product_agent_client import AgentRuntime
from scripts.selftest.product_boundary_actions import response_receipt
from scripts.selftest.product_boundary_common import ProductWorld
from scripts.selftest.product_boundary_contracts import ProductBoundaryObservation
from scripts.selftest.product_boundary_target import target_binding
from scripts.selftest.security_boundary_http import BoundaryAPI

from app.schemas.self_tests import InstallationResponse


async def installation_refusals(
    world: ProductWorld, installed: InstallationResponse
) -> tuple[ProductBoundaryObservation, ...]:
    before = await inventory(world.viewer, world.config.project_id)
    unknown = await world.user.probe(
        "POST",
        world.root + "/installations/preview",
        {
            "template_id": "core-v1",
            "binding_id": str(uuid4()),
        },
    )
    rows = [
        ProductBoundaryObservation(
            key="unauthorized_binding",
            requests=(response_receipt("unknown_binding", unknown),),
            observed_at=datetime.now(UTC),
        )
    ]
    mapping = installed.mapping
    if mapping is None:
        raise HarnessError("PRODUCT_BOUNDARY_INSTALLATION_MAPPING_MISSING")
    environment = f"/projects/{world.config.project_id}/environments/{mapping.environment_id}"
    run = world.root + f"/installations/{installed.id}/runs"
    for key, url in (
        ("wrong_target", "http://runner:8000"),
        ("environment_drift", world.config.binding.fixture_base_url + "/changed"),
    ):
        try:
            await world.user.object("PATCH", environment, {"base_url": url})
            preview = await world.user.probe(
                "POST",
                world.root + "/installations/preview",
                {"template_id": installed.template_id, "binding_id": str(installed.binding_id)},
            )
            preflight = preview.json()
            response = await world.user.probe("POST", run, {}, idempotency_key="boundary:" + key)
            rows.append(
                ProductBoundaryObservation(
                    key=key,
                    requests=(
                        response_receipt("drift_preview", preview),
                        response_receipt("create_batch", response),
                    ),
                    safe_fields=("preview_blocked", "SELFTEST_ENVIRONMENT_MAPPING_INVALID")
                    if preflight.get("can_apply") is False
                    and "SELFTEST_ENVIRONMENT_MAPPING_INVALID" in preflight.get("conflicts", [])
                    else (),
                    observed_at=datetime.now(UTC),
                )
            )
        finally:
            await world.user.object(
                "PATCH", environment, {"base_url": world.config.binding.fixture_base_url}
            )
    after = await inventory(world.viewer, world.config.project_id)
    return tuple(row.model_copy(update={"before": before, "after": after}) for row in rows)


async def recursion_and_isolation(world: ProductWorld) -> tuple[ProductBoundaryObservation, ...]:
    runtime = AgentRuntime.model_validate(read_json(world.state / "harness-runtime.json"))
    token = runtime.target_cleanup_token
    if not token:
        raise HarnessError("PRODUCT_BOUNDARY_TARGET_EDITOR_MISSING")
    api = BoundaryAPI(
        world.stack.target_url,
        world.budget,
        world.deadline,
        token,
        str(world.config.binding.target_organization_id),
    )
    project = world.config.binding.target_project_id
    root = f"/projects/{project}/self-tests"
    try:
        before = await inventory(api, project)
        request: JsonObject = {
            "template_id": "core-v1",
            "binding_id": str(target_binding(world).id),
        }
        preview_response = await api.probe("POST", root + "/installations/preview", request)
        preview = preview_response.json()
        payload = {
            **request,
            "preview_fingerprint": preview["fingerprint"],
            "preview_expires_at": preview["expires_at"],
        }
        # This is a negative authorized-binding fixture. No H/O identity exists on B.
        rejection = await api.probe(
            "POST",
            root + "/installations",
            payload,
            idempotency_key="product-recursion-refusal",
        )
        after = await inventory(api, project)
        isolation = ProductBoundaryObservation(
            key="a_b_isolation",
            before=await inventory(world.viewer, world.config.project_id),
            after=after,
            observed_at=datetime.now(UTC),
        )
        recursion = ProductBoundaryObservation(
            key="recursive_target",
            before=before,
            after=after,
            requests=(
                response_receipt("recursive_preview", preview_response),
                response_receipt("recursive_install", rejection),
            ),
            safe_fields=tuple(str(value) for value in preview["conflicts"]),
            observed_at=datetime.now(UTC),
        )
        return recursion, isolation
    finally:
        await api.close()
