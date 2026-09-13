import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.engine.contracts import WorkflowDefinition, parse_node_config

FIXTURES = Path(__file__).resolve().parents[2] / "docs/workflow-editor-codeplan/fixtures"


@pytest.mark.parametrize("filename", sorted(path.name for path in FIXTURES.glob("*.json")))
def test_editor_plan_fixtures(filename: str) -> None:
    payload = json.loads((FIXTURES / filename).read_text())
    if filename.startswith("07-"):
        with pytest.raises(ValidationError, match=r"unreachable|without a path"):
            WorkflowDefinition.model_validate(payload)
        return
    definition = WorkflowDefinition.model_validate(payload)
    for node in definition.nodes:
        parse_node_config(node)
    assert len(definition.nodes) == len(payload["nodes"])
    assert len(definition.edges) == len(payload["edges"])
