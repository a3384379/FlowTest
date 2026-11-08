"""Typed source characterization using actual design generator/compiler, without a model."""

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from mcp.types import CallToolResult

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.generation_lifecycle import bind_lifecycle_plan  # noqa: E402
from scripts.selftest.host_contracts import HostGeneratedDesign  # noqa: E402
from scripts.selftest.host_gateway import ToolExchange  # noqa: E402
from scripts.selftest.host_integration_sources import integration_source  # noqa: E402
from scripts.selftest.io import HarnessError  # noqa: E402
from test_selftest_generation_lifecycle import _generated_inputs, _installation  # noqa: E402

from app.domain.integration_plans import (  # noqa: E402
    IntegrationPlannerRequest,
    PlanActor,
    PlanTargetEnvironment,
    build_integration_plan,
    compile_integration_plan,
)
from app.domain.test_design_compilation import FrozenGenerationOrigin  # noqa: E402
from app.domain.test_engineering import GenerationPolicy  # noqa: E402
from app.schemas.flow_spec import FlowSpecVisualProposalResponse  # noqa: E402


def fixture():
    installed = _installation()
    _, _, selected, generated = _generated_inputs(installed)
    plan = build_integration_plan(
        IntegrationPlannerRequest(
            context_revision_id=uuid4(),
            context_fingerprint="a" * 64,
            objective="Synthetic host lifecycle",
            actors=[PlanActor(id="fixture", role="owner")],
            target_environment=PlanTargetEnvironment(
                key="target", source_ref=f"environment://{installed.target_environment_id}"
            ),
            selected_operations=selected,
        )
    )
    bound = bind_lifecycle_plan(plan, installed, "batch-one")
    compiled = compile_integration_plan(bound)
    assert compiled.importable
    proposal_id = uuid4()

    def exchange(name, args, data):
        return ToolExchange(
            1, name, args, CallToolResult(content=[], structured_content={"data": data})
        )

    exchanges = [
        exchange("flowtest.plan_integration_test", {}, plan.model_dump(mode="json")),
        exchange(
            "flowtest.compile_integration_flowspec",
            {"plan": bound.model_dump(mode="json")},
            compiled.model_dump(mode="json"),
        ),
    ]
    for item in generated:
        origin = FrozenGenerationOrigin(
            api_definition_id=item.api_source.api_definition_id,
            api_version=1,
            contract_fingerprint=item.api_source.contract_fingerprint,
            generation_policy=GenerationPolicy(
                max_scenarios=50, include_negative=False, include_auth=True, include_state=False
            ),
            generator_build="sha256:" + "c" * 64,
        )
        design = HostGeneratedDesign(
            fingerprint=item.design_fingerprint, design=item.design, origin=origin, persisted=False
        )
        exchanges.append(
            exchange("flowtest.generate_test_design", {}, design.model_dump(mode="json"))
        )
    exchanges.append(
        exchange(
            "flowtest.propose_flow_draft",
            {"context_id": str(uuid4()), "context_revision_id": str(plan.context_revision_id)},
            {"change_set_id": str(proposal_id)},
        )
    )
    visual = FlowSpecVisualProposalResponse.model_construct(
        proposal=SimpleNamespace(id=proposal_id),
        integration_plan=bound,
        compilation=compiled,
        operation_mappings={
            item.operation_ref: item.api_source.api_definition_id for item in generated
        },
        operation_version_mappings={item.operation_ref: 1 for item in generated},
    )
    gateway = SimpleNamespace(
        exchanges=exchanges, authorization=SimpleNamespace(project_id=installed.project_id)
    )
    return gateway, visual, generated


def test_actual_multi_operation_design_oracles_compilation_and_exact_origins_are_preserved():
    gateway, visual, generated = fixture()
    source, oracles = integration_source(gateway, visual)
    assert tuple(item.purpose for item in source.operations) == (
        "login",
        "create",
        "list",
        "patch",
        "delete",
    )
    assert {item.api_source for item in source.operations} == {
        item.api_source for item in generated
    }
    assert len(source.combined_design.oracles) == sum(
        len(item.design["oracles"]) for item in generated
    )
    assert len(oracles) == len(visual.integration_plan.oracles)


def test_source_version_mutation_and_dropped_generated_oracle_are_blocked():
    gateway, visual, _ = fixture()
    changed = deepcopy(visual)
    ref = next(iter(changed.operation_version_mappings))
    changed.operation_version_mappings[ref] = 2
    with pytest.raises(HarnessError, match="EXACT_API_BINDING_CHANGED"):
        integration_source(gateway, changed)
    changed = deepcopy(visual)
    changed.integration_plan.oracles.pop()
    with pytest.raises(HarnessError, match="COMPILE_CALL_MISSING"):
        integration_source(gateway, changed)
