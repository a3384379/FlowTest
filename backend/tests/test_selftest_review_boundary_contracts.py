"""Preview fixture must be importable without broadening its execution budget."""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.selftest.io import read_json
from scripts.selftest.review_boundary_setup import PACK_PATH
from scripts.selftest.review_boundary_source import preview_spec

from app.domain.flow_spec_v2 import (
    FlowSpecV2,
    assess_flow_spec_v2_compatibility,
    flow_spec_v2_to_workflow_definition,
    validate_flow_spec_v2,
)
from app.domain.sandbox_preview import PreviewBudget
from app.services.workflows import _bounded_preview_definition


def test_preview_fixture_is_portable_and_execution_authorization_remains_narrow():
    raw = preview_spec("fixture", "/selftest/fixture/ST-MCP-022/request", "a" * 64)
    spec = FlowSpecV2.model_validate(raw)
    assert validate_flow_spec_v2(spec).valid
    assert assess_flow_spec_v2_compatibility(spec).compatible
    assert spec.run_policy.request_budget == spec.run_policy.cleanup_request_budget == 1
    assert spec.run_policy.force_cancel_skips_cleanup is False
    assert read_json(PACK_PATH)["preview_budget"] == {
        "max_nodes": 10,
        "max_requests": 2,
        "max_dataset_rows": 1,
        "max_parallelism": 1,
        "max_runtime_seconds": 30,
    }
    native = flow_spec_v2_to_workflow_definition(
        spec,
        operation_mappings={"fixture.cleanup": uuid4()},
        operation_versions={"fixture.cleanup": 1},
    )
    bounded = _bounded_preview_definition(
        native, PreviewBudget.model_validate(read_json(PACK_PATH)["preview_budget"])
    )
    assert bounded.run_policy.request_budget == bounded.run_policy.cleanup_request_budget == 1
