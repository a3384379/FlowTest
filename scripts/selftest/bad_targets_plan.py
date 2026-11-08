"""Bind synthetic dependency input through the existing typed integration planner."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from pydantic import JsonValue
from scripts.selftest.bad_targets_contracts import (
    BadAssertion,
    BadOperation,
    BadTargetGolden,
)
from scripts.selftest.bootstrap import Installation
from scripts.selftest.contracts import OracleBinding, canonical_digest
from scripts.selftest.generation_lifecycle import OperationGeneration, combine_generated_designs
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

from app.domain.flow_spec import FlowSpec, flow_spec_to_workflow_definition
from app.domain.integration_plans import (
    IntegrationPlan,
    PlanBinding,
    PlanBindingCandidate,
    PlanBindingTarget,
    seal_integration_plan,
)
from app.domain.test_design import TestDesignDocument


def bind_dependency(plan: IntegrationPlan) -> IntegrationPlan:
    steps = [item for item in plan.steps if item.kind == "operation"]
    operations = {item.ref: item for item in plan.operations}
    if len(steps) != 2 or len(operations) != 2:
        raise HarnessError("SELFTEST_BADTARGET_DEPENDENCY_PLAN_SET_MISMATCH")
    seed = next(item for item in steps if operations[item.operation_ref or ""].method == "POST")
    consumer = next(item for item in steps if operations[item.operation_ref or ""].method == "GET")
    evidence = ["selftest-fixture://mcp-badtargets-v1/dependency"]
    candidate = PlanBindingCandidate(
        id="synthetic-dependency-result",
        source_kind="previous_response",
        source_step_id=seed.id,
        path="body.value.dependency_id",
        value_type="string",
        transform="identity",
        confidence=1,
        evidence_refs=evidence,
    )
    binding = PlanBinding(
        id="synthetic-dependency-query",
        candidates=[candidate],
        selected_candidate_id=candidate.id,
        target=PlanBindingTarget(
            step_id=consumer.id, location="query", key="iteration_key", value_type="string"
        ),
        capture_variable="dependency_id",
        confidence=1,
        evidence_refs=evidence,
    )
    bindings = [
        item
        for item in plan.bindings
        if not (
            item.target.step_id == consumer.id
            and item.target.location == "query"
            and item.target.key == "iteration_key"
        )
    ]
    requests = []
    for operation in plan.operations:
        request = operation.request.model_copy(update={"auth_mode": "disabled"})
        if operation.method == "POST":
            request = request.model_copy(
                update={
                    "body": {"value": {"dependency_id": "dependency-good"}},
                    "body_kind": "json",
                }
            )
        requests.append(operation.model_copy(update={"request": request, "credential_refs": []}))
    return seal_integration_plan(
        plan.model_copy(
            update={
                "steps": [seed, consumer],
                "operations": requests,
                "bindings": [*bindings, binding],
                "unresolved_items": [
                    item
                    for item in plan.unresolved_items
                    if item.id != f"missing-bind-{consumer.id}-query-iteration_key"
                ],
                "evidence_refs": [*plan.evidence_refs, *evidence],
            }
        )
    )


async def compile_dependency(
    client: ProtocolClient,
    reviewer: PublicAPI,
    installation: Installation,
    golden: BadTargetGolden,
    operations: tuple[BadOperation, ...],
    directory: Path,
) -> tuple[JsonObject, JsonObject, JsonObject, str, JsonObject]:
    context = await client.call(
        "flowtest.begin_test_context",
        {
            "project_id": str(installation.project_id),
            "name": f"{client.batch_key}:{golden.scenario_id}",
            "objective": f"{client.batch_key}:独立生成的上游依赖与下游响应一致性",
            "target_environment_id": str(installation.fixture_environment_id),
            "required_evidence": ["contract"],
            "contract_revisions": [
                {
                    "source_ref": f"api-definition://{item.api_source.api_definition_id}/version/{item.api_source.api_version}",
                    "revision": item.api_source.contract_fingerprint,
                }
                for item in operations
            ],
        },
        scenario_id=golden.scenario_id,
        phase="context",
    )
    revision = object_value(context["revision"])
    proposed = await client.call(
        "flowtest.plan_integration_test",
        {
            "project_id": str(installation.project_id),
            "context_id": context["id"],
            "context_revision_id": revision["id"],
            "actors": [
                {
                    "id": "synthetic-principal",
                    "role": "合成依赖调用者",
                    "evidence_refs": ["selftest-fixture://mcp-badtargets-v1/actor"],
                }
            ],
            "target_environment": {
                "key": "fixture",
                "source_ref": f"environment://{installation.fixture_environment_id}",
                "evidence_refs": [f"environment://{installation.fixture_environment_id}"],
            },
            "operations": [
                {
                    "definition_id": str(item.api_source.api_definition_id),
                    "api_version": item.api_source.api_version,
                    "contract_fingerprint": item.api_source.contract_fingerprint,
                    "scenario_id": item.scenario_id,
                }
                for item in operations
            ],
        },
        scenario_id=golden.scenario_id,
        phase="integration_plan",
    )
    write_json(directory / "generated-integration-plan.json", proposed)
    bound = bind_dependency(IntegrationPlan.model_validate(proposed))
    plan, identities = namespace_plan_oracles(bound)
    write_json(
        directory / "oracle-identity-map.json",
        {
            "original_plan_fingerprint": proposed["plan_fingerprint"],
            "bound_plan_fingerprint": bound.plan_fingerprint,
            "ordered_plan_fingerprint": plan.plan_fingerprint,
            "oracle_id_map": identities,
            "oracle_semantics_changed": False,
        },
    )
    write_json(directory / "integration-plan.json", plan)
    validation = await client.call(
        "flowtest.validate_integration_plan",
        {
            "plan": plan.model_dump(mode="json"),
        },
        scenario_id=golden.scenario_id,
        phase="integration_validation",
    )
    compiled = await client.call(
        "flowtest.compile_integration_flowspec",
        {
            "plan": plan.model_dump(mode="json"),
        },
        scenario_id=golden.scenario_id,
        phase="compilation",
    )
    write_json(directory / "compilation.json", compiled)
    if validation["valid"] is not True or compiled["importable"] is not True:
        raise HarnessError("SELFTEST_BADTARGET_DEPENDENCY_COMPILATION_BLOCKED")
    mapping = {item.operation_ref: item.api_source.api_definition_id for item in operations}
    versions = {item.ref: item.source_version for item in plan.operations}
    registered = objects_value(
        await reviewer.request("GET", f"/projects/{installation.project_id}/services")
    )
    matches = [item for item in registered if item["id"] == str(installation.fixture_service_id)]
    if len(matches) != 1:
        raise HarnessError("SELFTEST_BADTARGET_FIXTURE_SERVICE_MISSING")
    services = {item.service_ref: text_value(matches[0]["service_key"]) for item in plan.operations}
    native = flow_spec_to_workflow_definition(
        FlowSpec.model_validate(compiled["flow_spec"]),
        operation_mappings=mapping,
        operation_versions=versions,
        service_keys=services,
    ).model_dump(mode="json")
    combined, composition = combine_generated_designs(
        tuple(
            OperationGeneration(
                purpose=item.purpose,
                api_source=item.api_source,
                operation_ref=item.operation_ref,
                design=item.design,
                design_fingerprint=item.design_fingerprint,
                scenario_id=item.scenario_id,
            )
            for item in operations
        )
    )
    combined = TestDesignDocument.model_validate(
        combined.model_copy(
            update={
                "intent": combined.intent.model_copy(
                    update={
                        "key": "selftest-badtargets-dependency",
                        "objective": "合成上游依赖与下游响应一致性",
                        "acceptance_criteria": ["两个原始生成设计的 Schema 与状态断言均保留"],
                    }
                ),
            }
        ).model_dump(mode="json")
    )
    write_json(directory / "design-composition.json", composition)
    payload: JsonObject = {
        "context_id": context["id"],
        "context_revision_id": revision["id"],
        "integration_plan": plan.model_dump(mode="json"),
        "compilation": compiled,
        "operation_mappings": {key: str(value) for key, value in mapping.items()},
        "operation_version_mappings": cast(JsonValue, versions),
        "service_mappings": {
            item.service_ref: str(installation.fixture_service_id) for item in plan.operations
        },
    }
    return (
        payload,
        native,
        combined.model_dump(mode="json"),
        text_value(compiled["flow_spec_fingerprint"]),
        plan.model_dump(mode="json"),
    )


def freeze_assertions(
    native: JsonObject,
    operations: tuple[BadOperation, ...],
    golden: BadTargetGolden,
) -> tuple[BadAssertion, ...]:
    nodes = objects_value(native["nodes"])
    apis = {
        text_value(node["id"]): object_value(node["config"])
        for node in nodes
        if node["type"] == "api"
    }
    by_id = {str(item.api_source.api_definition_id): item for item in operations}
    result = []
    for node in nodes:
        if node["type"] != "assert":
            continue
        config = object_value(node["config"])
        api = apis[text_value(config["source_node_id"])]
        operation = by_id[text_value(api["api_definition_id"])]
        kind = "schema" if config.get("assertion_type") == "json_schema" else "status"
        expected: JsonValue = golden.schema_ if kind == "schema" else golden.status
        expression = "body" if kind == "schema" else "status_code"
        if (
            canonical_digest(config["expected"]) != canonical_digest(expected)
            or config["operator"] != "equals"
            or config["expression"] != expression
            or api["api_version"] != operation.api_source.api_version
        ):
            raise HarnessError("SELFTEST_BADTARGET_GENERATED_ORACLE_NOT_GOLDEN")
        selected = [
            item
            for item in objects_value(operation.design["oracles"])
            if item["kind"] == kind and operation.scenario_id in cast(list[str], item["applies_to"])
        ]
        if len(selected) != 1 or canonical_digest(selected[0]["expected"]) != canonical_digest(
            expected
        ):
            raise HarnessError("SELFTEST_BADTARGET_SOURCE_ORACLE_MISSING")
        oracle_id = text_value(selected[0]["id"])
        if len(operations) > 1:
            # This exact ID is produced by the integration compiler and visible in its native name.
            oracle_id = text_value(node["name"]).removeprefix("Assert ")
        result.append(
            BadAssertion(
                binding=OracleBinding(
                    oracle_id=oracle_id,
                    node_id=text_value(node["id"]),
                    assertion_name="workflow_assertion",
                    expression=expression,
                    expected_value_digest=canonical_digest(expected),
                ),
                kind=kind,
                purpose=operation.purpose,
                expected=expected,
            )
        )
    if len(result) != len(operations) * 2 or len({(a.purpose, a.kind) for a in result}) != len(
        result
    ):
        raise HarnessError("SELFTEST_BADTARGET_ORACLE_DENOMINATOR_MISMATCH")
    return tuple(result)


def namespace_plan_oracles(plan: IntegrationPlan) -> tuple[IntegrationPlan, JsonObject]:
    """Only give existing Oracles deterministic IDs: status before Schema per source step."""
    if any(item.kind not in {"status", "schema"} for item in plan.oracles):
        raise HarnessError("SELFTEST_BADTARGET_UNSUPPORTED_ORACLE")
    mapping = {
        item.id: ("a-status-" if item.kind == "status" else "b-schema-")
        + canonical_digest(item.id)[:24]
        for item in plan.oracles
    }
    if len(mapping) != len(plan.oracles) or len(set(mapping.values())) != len(mapping):
        raise HarnessError("SELFTEST_BADTARGET_ORACLE_ID_MAP_NOT_BIJECTIVE")
    result = seal_integration_plan(
        plan.model_copy(
            update={
                "oracles": [
                    item.model_copy(update={"id": mapping[item.id]}) for item in plan.oracles
                ],
                "coverage_targets": [
                    item.model_copy(
                        update={
                            "target_ref": mapping.get(item.target_ref, item.target_ref),
                            "covered_by": [mapping.get(value, value) for value in item.covered_by],
                        }
                    )
                    for item in plan.coverage_targets
                ],
            }
        )
    )
    before = {
        mapping[item.id]: item.model_dump(mode="json", exclude={"id"}) for item in plan.oracles
    }
    after = {item.id: item.model_dump(mode="json", exclude={"id"}) for item in result.oracles}
    if before != after:
        raise HarnessError("SELFTEST_BADTARGET_ORACLE_SEMANTICS_CHANGED")
    return result, cast(JsonObject, mapping)
