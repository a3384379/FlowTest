"""Real MCP contract/context, then an explicitly authored bounded Preview specification."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import JsonObject, integer_value, object_value, text_value, write_json
from scripts.selftest.mcp_generation_journey import begin_context, import_operation
from scripts.selftest.quality_protocol import QualityProtocol
from scripts.selftest.review_boundary_contracts import ReviewManifest, ReviewSource


def preview_spec(batch: str, path: str, contract_fingerprint: str) -> JsonObject:
    # This is an authored Preview/cancel fixture, never labelled as an unedited
    # generated Case or as a formal native regression Run.
    return {
        "schema_version": "flowtest-flow-spec-v2",
        "name": batch,
        "nodes": [
            {"id": "start", "kind": "start", "name": "Start"},
            {"id": "pause", "kind": "delay", "name": "PreviewPause", "config": {"seconds": 10}},
            {"id": "end", "kind": "end", "name": "End"},
        ],
        "edges": [
            {"id": "start-pause", "source": "start", "target": "pause"},
            {"id": "pause-end", "source": "pause", "target": "end"},
        ],
        "operations": [
            {
                "ref": "fixture.cleanup",
                "name": "受限Preview清理",
                "method": "GET",
                "path": path,
                "version_strategy": "pinned",
                "source_version": 1,
                "contract_fingerprint": contract_fingerprint,
            }
        ],
        "cleanup": [
            {"id": "cleanup_after_cancel", "operation_ref": "fixture.cleanup", "run_when": "always"}
        ],
        "run_policy": {
            "request_budget": 1,
            "cleanup_request_budget": 1,
            "max_runtime_seconds": 30,
            "force_cancel_skips_cleanup": False,
        },
        "security_policy": {
            "max_requests": 20,
            "secret_refs_only": True,
            "allow_private_network": False,
        },
    }


async def prepare_source(
    client: QualityProtocol, manifest: ReviewManifest, output: Path, fixture_epoch: str
) -> ReviewSource:
    scope = manifest.scope
    scenario = "ST-MCP-022-" + client.transport
    path = f"/selftest/{client.batch_key}/{scenario}/request"
    offset = len(client.receipts)
    imported = await import_operation(
        client,
        installation=scope,
        scenario_id=scenario,
        operation={
            "name": client.batch_key + ":cleanup",
            "method": "GET",
            "path": path,
            "responses": {"200": {"description": "合成清理", "schema": {"type": "object"}}},
        },
        service_id=str(scope.fixture_service_id),
        environment_id=str(scope.fixture_environment_id),
        output_dir=output,
    )
    api, version = text_value(imported["definition_id"]), integer_value(imported["version"])
    generated = await client.call(
        "flowtest.generate_test_design",
        {
            "project_id": str(scope.project_id),
            "api_definition_id": api,
            "api_version": version,
            "generation_policy": {
                "include_negative": False,
                "include_auth": False,
                "include_state": False,
                "include_data_constraints": False,
                "pairwise_enabled": False,
            },
        },
        scenario_id=scenario,
        phase="preview_contract_source",
    )
    fingerprint = text_value(object_value(generated["origin"])["contract_fingerprint"])
    context = await begin_context(
        client,
        installation=scope,
        scenario_id=scenario,
        environment_id=str(scope.fixture_environment_id),
        api_id=api,
        api_version=version,
        contract_fingerprint=fingerprint,
    )
    spec = preview_spec(client.batch_key, path, fingerprint)
    source = ReviewSource(
        transport=client.transport,
        api_id=UUID(api),
        api_version=version,
        contract_fingerprint=fingerprint,
        context=context,
        spec=spec,
        spec_digest=canonical_digest(spec),
        fixture_epoch=fixture_epoch,
        calls=tuple(client.receipts[offset:]),
        frozen_at=datetime.now(UTC),
    )
    write_json(output / "source.json", source)
    return source
