"""Generate immutable bad-target assets via real MCP; only request data is fixture-bound."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from scripts.selftest.bad_targets_contracts import BadOperation, BadTargetAsset, BadTargetGolden
from scripts.selftest.bad_targets_plan import compile_dependency, freeze_assertions
from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import ApiSource, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    objects_value,
    text_value,
    write_json,
)
from scripts.selftest.mcp_generation_journey import begin_context, propose_case
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.review_driver import FixtureReviewDriver, ReviewDriver

from app.domain.test_design import TestDesignDocument, fingerprint_design


def operation_document(golden: BadTargetGolden, batch: str) -> JsonObject:
    path = f"/selftest/{batch}/{golden.scenario_id}"
    response: JsonObject = {
        "description": "固定合成响应契约",
        "content": {"application/json": {"schema": golden.schema_}},
    }
    operation: JsonObject = {"responses": {str(golden.status): response}}
    paths: JsonObject = {path + "/request": {"get": operation}}
    if golden.fault_kind == "dependency_fault":
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["value"],
                        "properties": {
                            "value": {"const": golden.good_value},
                        },
                    },
                    "example": {"value": golden.good_value},
                }
            },
        }
        paths = {
            path + "/request": {"post": operation},
            path + "/sequence": {
                "get": {
                    "responses": {"200": response},
                    "parameters": [
                        {
                            "name": "iteration_key",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                }
            },
        }
    document: JsonObject = {
        "openapi": "3.0.3",
        "info": {"title": f"{batch}:{golden.scenario_id}", "version": "1"},
        "paths": paths,
    }
    if golden.fault_kind == "auth_fault":
        operation["security"] = [{"SyntheticBearer": []}]
        object_value(operation["responses"])["200"] = {
            "description": "有授权时的合成响应",
            "content": {
                "application/json": {"schema": {"type": "object"}},
            },
        }
        document["components"] = {
            "securitySchemes": {
                "SyntheticBearer": {"type": "http", "scheme": "bearer"},
            }
        }
    return document


async def _import(
    client: ProtocolClient,
    installation: Installation,
    golden: BadTargetGolden,
    directory: Path,
) -> list[JsonObject]:
    document = operation_document(golden, client.batch_key)
    write_json(directory / "synthetic-openapi.json", document)
    common: JsonObject = {
        "project_id": str(installation.project_id),
        "service_id": str(installation.fixture_service_id),
        "environment_id": str(installation.fixture_environment_id),
    }
    preview = await client.call(
        "flowtest.preview_contract_import",
        {
            "request": {
                **common,
                "source_kind": "document",
                "document_name": golden.scenario_id + ".json",
                "document_content": json.dumps(document, ensure_ascii=False),
                "source_type": "openapi3",
                "persist": True,
            }
        },
        scenario_id=golden.scenario_id,
        phase="contract_preview",
    )
    items = objects_value(preview["items"])
    expected = 2 if golden.requests == 2 else 1
    if len(items) != expected or any(item["change"] != "added" for item in items):
        raise HarnessError("SELFTEST_BADTARGET_IMPORT_SET_MISMATCH")
    committed = await client.call(
        "flowtest.commit_contract_import",
        {
            "request": {
                **common,
                "preview_id": preview["preview_id"],
                "preview_sha256": preview["source_sha256"],
                "selected_operations": [item["import_key"] for item in items],
                "expected_current_versions": {},
            },
            "idempotency_key": f"{client.batch_key}:{golden.scenario_id}:import",
        },
        scenario_id=golden.scenario_id,
        phase="contract_commit",
    )
    write_json(directory / "contract-import.json", committed)
    results = objects_value(committed["results"])
    keys = {item["import_key"] for item in items}
    if (
        set(cast(list[str], committed["applied_keys"])) != keys
        or len(results) != expected
        or {item["import_key"] for item in results} != keys
        or any(item["definition_id"] is None for item in results)
    ):
        raise HarnessError("SELFTEST_BADTARGET_IMPORT_MAPPING_MISMATCH")
    return sorted(results, key=lambda item: 0 if item["method"] == "POST" else 1)


async def _generate(
    client: ProtocolClient,
    installation: Installation,
    golden: BadTargetGolden,
    imported: JsonObject,
    directory: Path,
) -> BadOperation:
    api_id, version = text_value(imported["definition_id"]), integer_value(imported["version"])
    inspected = await client.call(
        "flowtest.inspect_contract",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "version": version,
        },
        scenario_id=golden.scenario_id,
        phase="contract_read",
    )
    items = objects_value(inspected["items"])
    if len(items) != 1 or items[0]["id"] != api_id or items[0]["version"] != version:
        raise HarnessError("SELFTEST_BADTARGET_CONTRACT_VERSION_MISMATCH")
    auth = golden.fault_kind == "auth_fault"
    generated = await client.call(
        "flowtest.generate_test_design",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "api_version": version,
            "generation_policy": {
                "include_negative": auth,
                "include_auth": auth,
                "include_state": False,
                "include_data_constraints": False,
                "pairwise_enabled": False,
            },
        },
        scenario_id=golden.scenario_id,
        phase="design",
    )
    design, origin = object_value(generated["design"]), object_value(generated["origin"])
    selected = [
        item
        for item in objects_value(design["scenarios"])
        if item["kind"] == ("auth_missing" if auth else "happy_path")
    ]
    if (
        len(selected) != 1
        or generated["persisted"] is not False
        or origin["api_definition_id"] != api_id
        or origin["api_version"] != version
        or fingerprint_design(TestDesignDocument.model_validate(design)) != generated["fingerprint"]
    ):
        raise HarnessError("SELFTEST_BADTARGET_GENERATED_DESIGN_MISMATCH")
    coverage = await client.call(
        "flowtest.analyze_test_coverage",
        {
            "project_id": str(installation.project_id),
            "api_definition_id": api_id,
            "api_version": version,
            "generation_policy": origin["generation_policy"],
        },
        scenario_id=golden.scenario_id,
        phase="coverage",
    )
    if canonical_digest(coverage) != canonical_digest(design["coverage"]):
        raise HarnessError("SELFTEST_BADTARGET_COVERAGE_MISMATCH")
    purpose = "seed" if imported["method"] == "POST" else "consumer"
    write_json(directory / f"generated-{purpose}.json", generated)
    return BadOperation(
        purpose=purpose,
        api_source=ApiSource(
            project_id=installation.project_id,
            api_definition_id=UUID(api_id),
            api_version=version,
            contract_fingerprint=text_value(origin["contract_fingerprint"]),
        ),
        operation_ref=text_value(object_value(design["intent"])["key"]),
        design=design,
        origin=origin,
        design_fingerprint=text_value(generated["fingerprint"]),
        scenario_id=text_value(selected[0]["id"]),
    )


async def _compile_single(
    client: ProtocolClient,
    installation: Installation,
    golden: BadTargetGolden,
    operation: BadOperation,
    directory: Path,
) -> tuple[JsonObject, JsonObject, JsonObject, str]:
    source = operation.api_source
    context = await begin_context(
        client,
        installation=installation,
        scenario_id=golden.scenario_id,
        environment_id=str(installation.fixture_environment_id),
        api_id=str(source.api_definition_id),
        api_version=source.api_version,
        contract_fingerprint=source.contract_fingerprint,
    )
    compiled = await client.call(
        "flowtest.compile_test_design",
        {
            "request": {
                "project_id": str(installation.project_id),
                "design": operation.design,
                "design_fingerprint": operation.design_fingerprint,
                "origin": operation.origin,
                "scenario_ids": [operation.scenario_id],
                "environment_id": str(installation.fixture_environment_id),
                "context_binding": context,
            }
        },
        scenario_id=golden.scenario_id,
        phase="compilation",
    )
    write_json(directory / "compilation.json", compiled)
    scenarios = objects_value(compiled["scenarios"])
    if compiled["readiness"] != "ready" or len(scenarios) != 1:
        raise HarnessError("SELFTEST_BADTARGET_COMPILATION_NOT_READY")
    executable = object_value(scenarios[0]["executable_payload"])
    spec = object_value(executable["spec"])
    proposal: JsonObject = {
        **context,
        "spec": {**spec, "name": f"{client.batch_key}:{golden.scenario_id}"},
        **{
            key: executable[key]
            for key in (
                "operation_mappings",
                "operation_version_mappings",
                "service_mappings",
            )
        },
    }
    proposal.pop("context_fingerprint")
    return (
        proposal,
        object_value(executable["native_definition"]),
        operation.design,
        text_value(compiled["compilation_fingerprint"]),
    )


async def generate_bad_target(
    client: ProtocolClient,
    reviewer: PublicAPI,
    *,
    installation: Installation,
    golden: BadTargetGolden,
    output_dir: Path,
    review_driver: ReviewDriver | None = None,
) -> BadTargetAsset:
    generated_at = datetime.now(UTC)
    imported = await _import(client, installation, golden, output_dir)
    operations = tuple(
        [await _generate(client, installation, golden, item, output_dir) for item in imported]
    )
    if len(operations) == 1:
        payload, native, design, fingerprint = await _compile_single(
            client,
            installation,
            golden,
            operations[0],
            output_dir,
        )
        combined = None
        oracle_source, oracle_source_kind = operations[0].design, "design"
    else:
        payload, native, design, fingerprint, oracle_source = await compile_dependency(
            client,
            reviewer,
            installation,
            golden,
            operations,
            output_dir,
        )
        oracle_source_kind = "integration_plan"
        combined = fingerprint_design(TestDesignDocument.model_validate(design))
    assertions = freeze_assertions(native, operations, golden)
    proposal = await client.call(
        "flowtest.propose_flow_draft",
        {
            **payload,
            "project_id": str(installation.project_id),
            "source_ref": f"mcp://selftest/{client.batch_key}/{golden.scenario_id}",
            "idempotency_key": f"{client.batch_key}:{golden.scenario_id}:workflow",
            "dry_run": False,
        },
        scenario_id=golden.scenario_id,
        phase="workflow_proposal",
    )
    driver = review_driver or FixtureReviewDriver()
    flow = await driver.flow(
        reviewer,
        project_id=str(installation.project_id),
        reviewer_id=str(installation.reviewer_id),
        proposal_id=text_value(proposal["change_set_id"]),
        expected_definition=native,
        expected_api_ids=tuple(str(item.api_source.api_definition_id) for item in operations),
        output_dir=output_dir,
    )
    case = await propose_case(
        client,
        reviewer,
        installation,
        golden.scenario_id,
        design,
        flow,
        output_dir,
        review_driver=driver,
    )
    asset = BadTargetAsset(
        scenario_id=golden.scenario_id,
        variant_key=golden.fault_kind,
        operations=operations,
        combined_design_fingerprint=combined,
        assertions=assertions,
        oracle_source=oracle_source,
        oracle_source_kind=oracle_source_kind,
        workflow=flow,
        case=case,
        calls=tuple(item for item in client.receipts if item.scenario_id == golden.scenario_id),
        compilation_fingerprint=fingerprint,
        generated_at=generated_at,
        frozen_at=datetime.now(UTC),
    )
    write_json(output_dir / "generated-asset.json", asset)
    return asset
