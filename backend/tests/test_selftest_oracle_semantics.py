"""Published assertion semantics must match the frozen generated Design."""

import copy
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from test_design_compilation import frozen_request as frozen_request

from app.domain.test_design_compilation import CompileTestDesignRequest, compile_frozen_design
from app.domain.test_engineering import OperationContract

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.collect_evidence import _published_workflow
from scripts.selftest.contracts import ApiSource, OracleBinding, ProposalEvidence, canonical_digest
from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_generation_journey import GeneratedAsset
from scripts.selftest.review_fixture_driver import ReviewedCase, ReviewedWorkflow


@pytest.fixture
def generated_asset(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract],
) -> GeneratedAsset:
    request, contract = frozen_request
    compiled = compile_frozen_design(request, contract)
    result = compiled.scenarios[0]
    assert result.readiness == "ready" and result.executable_payload is not None
    definition = result.executable_payload.native_definition.model_dump(mode="json")
    flow_id, case_id = uuid4(), uuid4()
    proposal = ProposalEvidence(
        project_id=request.project_id,
        proposal_id=uuid4(),
        route="flow_spec",
        review_status="accepted",
        materialized_resource_id=flow_id,
        content_fingerprint=canonical_digest(definition),
        review_mode="ci_fixture",
        reviewer_id=uuid4(),
    )
    workflow = ReviewedWorkflow(
        workflow={"id": str(flow_id)},
        version={
            "id": str(uuid4()),
            "version": 1,
            "fingerprint": canonical_digest(definition),
            "definition": definition,
        },
        proposal=proposal,
    )
    case = ReviewedCase(
        case={"id": str(case_id)},
        version={"id": str(uuid4()), "version": 1},
        proposal=proposal.model_copy(
            update={
                "route": "controlled_write",
                "item_id": uuid4(),
                "materialized_resource_id": case_id,
            }
        ),
    )
    return GeneratedAsset(
        scenario_id="ST-MCP-014",
        variant_key="semantic_guard",
        api_source=ApiSource(
            project_id=request.project_id,
            api_definition_id=request.origin.api_definition_id,
            api_version=request.origin.api_version,
            contract_fingerprint=request.origin.contract_fingerprint,
        ),
        design=request.design.model_dump(mode="json"),
        design_fingerprint=request.design_fingerprint,
        compilation_fingerprint=compiled.compilation_fingerprint,
        oracle_bindings=tuple(
            OracleBinding(
                oracle_id=item.oracle_id,
                node_id=item.node_id,
                assertion_name="workflow_assertion",
                expression=item.normalized_expression,
                expected_value_digest=item.expected_value_fingerprint,
            )
            for item in result.oracle_bindings
        ),
        workflow=workflow,
        case=case,
        calls=(),
        generated_at=datetime.now(UTC),
        frozen_at=datetime.now(UTC),
    )


def test_published_unmodified_generated_oracle_semantics_are_accepted(
    generated_asset: GeneratedAsset,
) -> None:
    assert _published_workflow(generated_asset).assertions == generated_asset.oracle_bindings


@pytest.mark.parametrize(
    "mutation", ["operator", "assertion_type", "dynamic_expected", "wrong_field", "wrong_source"]
)
def test_published_oracle_semantic_mutation_is_rejected_before_execution(
    generated_asset: GeneratedAsset, mutation: str
) -> None:
    version = copy.deepcopy(generated_asset.workflow.version)
    definition = version["definition"]
    assert isinstance(definition, dict) and isinstance(definition["nodes"], list)
    candidates = [
        node
        for node in definition["nodes"]
        if isinstance(node, dict)
        and node["type"] == "assert"
        and isinstance(node["config"], dict)
        and (
            node["config"].get("assertion_type") == "json_schema"
            if mutation == "assertion_type"
            else node["config"].get("assertion_type", "comparison") == "comparison"
        )
    ]
    assert candidates
    node = candidates[0]
    config = node["config"]
    assert isinstance(config, dict)
    if mutation == "operator":
        config["operator"] = "not_equals"
    elif mutation == "assertion_type":
        config["assertion_type"] = "comparison"
    elif mutation == "dynamic_expected":
        config["expected_source_node_id"] = config["source_node_id"]
        config["expected_expression"] = config["expression"]
    elif mutation == "wrong_field":
        config["expression"] = "body.unrelated"
    else:
        config["source_node_id"] = "start"
    version["fingerprint"] = canonical_digest(definition)
    changed = generated_asset.model_copy(
        update={"workflow": generated_asset.workflow.model_copy(update={"version": version})}
    )
    with pytest.raises(HarnessError, match="PUBLISHED_ORACLE"):
        _published_workflow(changed)
