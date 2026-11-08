"""Generate one real Design, then explicitly propose synthetic semantic counterexamples."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue
from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import (
    JsonObject,
    PublicAPI,
    integer_value,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.mcp_generation_journey import (
    GeneratedAsset,
    begin_context,
    generate_canary,
    propose_case,
)
from scripts.selftest.mcp_protocol_runner import ProtocolClient
from scripts.selftest.review_fixture_driver import review_flow
from scripts.selftest.semantic_contracts import SemanticArtifact, SemanticVariant
from scripts.selftest.semantic_mutations import mutate_assertion

from app.domain.flow_spec_v2 import FlowSpecV2, flow_spec_v2_to_workflow_definition


def _mutated_spec(executable: JsonObject, variant: SemanticVariant, name: str) -> JsonObject:
    native = mutate_assertion(object_value(executable["native_definition"]), variant)
    nodes = {item["id"]: item for item in objects_value(native["nodes"])}
    spec = deepcopy(object_value(executable["spec"]))
    spec["name"] = name[:200]
    selected: list[JsonValue] = []
    for node in objects_value(spec["nodes"]):
        if node["id"] not in nodes:
            continue
        if node["kind"] == "assert":
            node["config"] = nodes[node["id"]]["config"]
        selected.append(node)
    spec["nodes"], spec["edges"] = selected, native["edges"]
    return spec


def project_artifact(asset: GeneratedAsset, variant: SemanticVariant) -> SemanticArtifact:
    version, case = asset.workflow.version, asset.case.version
    definition = object_value(case["definition"])
    return SemanticArtifact(
        variant=variant,
        api_source=asset.api_source,
        design=asset.design,
        design_fingerprint=asset.design_fingerprint,
        compilation_fingerprint=asset.compilation_fingerprint,
        oracle_bindings=asset.oracle_bindings,
        definition=object_value(version["definition"]),
        definition_digest=canonical_digest(version["definition"]),
        workflow_id=UUID(text_value(asset.workflow.workflow["id"])),
        workflow_version_id=UUID(text_value(version["id"])),
        workflow_version=integer_value(version["version"]),
        workflow_fingerprint=text_value(version["fingerprint"]),
        case_id=UUID(text_value(asset.case.case["id"])),
        case_version=integer_value(case["version"]),
        environment_id=UUID(text_value(definition["environment_id"])),
        workflow_proposal=asset.workflow.proposal,
        case_proposal=asset.case.proposal,
        calls=asset.calls,
        frozen_at=asset.frozen_at,
    )


async def _mutant(
    client: ProtocolClient,
    reviewer: PublicAPI,
    installation: Installation,
    original: GeneratedAsset,
    executable: JsonObject,
    variant: SemanticVariant,
    output: Path,
) -> GeneratedAsset:
    scenario = "ST-MCP-014-" + variant
    context = await begin_context(
        client,
        installation=installation,
        scenario_id=scenario,
        environment_id=str(installation.fixture_environment_id),
        api_id=str(original.api_source.api_definition_id),
        api_version=original.api_source.api_version,
        contract_fingerprint=original.api_source.contract_fingerprint,
    )
    spec = _mutated_spec(executable, variant, client.batch_key + ":" + scenario)
    mappings = {
        key: UUID(text_value(value))
        for key, value in object_value(executable["operation_mappings"]).items()
    }
    versions = {
        key: integer_value(value)
        for key, value in object_value(executable["operation_version_mappings"]).items()
    }
    native = flow_spec_v2_to_workflow_definition(
        FlowSpecV2.model_validate(spec),
        operation_mappings=mappings,
        operation_versions=versions,
    ).model_dump(mode="json")
    write_json(
        output / "explicit-negative-mutation.json",
        {
            "variant": variant,
            "base_design_fingerprint": original.design_fingerprint,
            "base_compilation_fingerprint": original.compilation_fingerprint,
            "purpose": "故意错误的专用负向产物; 独立审核必须拒绝",
            "definition": native,
        },
    )
    proposed = await client.call(
        "flowtest.propose_flow_draft",
        {
            "project_id": str(installation.project_id),
            "context_id": context["context_id"],
            "context_revision_id": context["context_revision_id"],
            "spec": spec,
            "operation_mappings": executable["operation_mappings"],
            "operation_version_mappings": executable["operation_version_mappings"],
            "service_mappings": executable["service_mappings"],
            "source_ref": f"mcp://selftest/{client.batch_key}/{scenario}",
            "idempotency_key": f"{client.batch_key}:{scenario}:workflow",
            "dry_run": False,
        },
        scenario_id=scenario,
        phase="explicit_negative_workflow_proposal",
    )
    flow = await review_flow(
        reviewer,
        project_id=str(installation.project_id),
        reviewer_id=str(installation.reviewer_id),
        proposal_id=text_value(proposed["change_set_id"]),
        expected_definition=native,
        expected_api_ids=(str(original.api_source.api_definition_id),),
        output_dir=output,
    )
    case = await propose_case(
        client, reviewer, installation, scenario, original.design, flow, output
    )
    return original.model_copy(
        update={
            "scenario_id": scenario,
            "variant_key": variant,
            "workflow": flow,
            "case": case,
            "calls": tuple(item for item in client.receipts if item.scenario_id == scenario),
            "frozen_at": datetime.now(UTC),
        }
    )


async def generate_semantic_assets(
    client: ProtocolClient,
    reviewer: PublicAPI,
    *,
    installation: Installation,
    output_dir: Path,
) -> tuple[GeneratedAsset, ...]:
    original = await generate_canary(
        client,
        reviewer,
        installation=installation,
        scenario_id="ST-MCP-026",
        expected_actual=1,
        output_dir=output_dir / "positive_control",
    )
    compiled = read_json(output_dir / "positive_control/design-compilation.json")
    executable = object_value(objects_value(compiled["scenarios"])[0]["executable_payload"])
    variants: tuple[SemanticVariant, ...] = (
        "missing_assertion",
        "wrong_field",
        "wrong_operator",
        "expected_from_actual",
    )
    assets = [original]
    for variant in variants:
        assets.append(
            await _mutant(
                client,
                reviewer,
                installation,
                original,
                executable,
                variant,
                output_dir / variant,
            )
        )
    return tuple(assets)
