from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

from app.domain.sandbox_preview import MCP_SANDBOX_PREVIEW_SERVER_VERSION
from app.domain.v6_evaluation import (
    EvaluationAnnotation,
    EvaluationBaseline,
    build_evaluation_baseline,
)
from app.domain.v6_skill import IntegrationFlowSkillManifest
from app.services.service_accounts import SERVICE_ACCOUNT_SCOPES

WORKSPACE_ROOT = Path(__file__).parents[2]
SKILL_ROOT = WORKSPACE_ROOT / "skills" / "flowtest-generate-integration-flow"
GOLDEN_ROOT = Path(__file__).parent / "fixtures" / "v6_golden"


def _mapping(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))


def _annotations() -> list[EvaluationAnnotation]:
    payload = json.loads((GOLDEN_ROOT / "evaluation-annotations.json").read_text(encoding="utf-8"))
    return [EvaluationAnnotation.model_validate(item) for item in payload]


def test_flagship_skill_manifest_matches_live_mcp_contract() -> None:
    manifest = IntegrationFlowSkillManifest.model_validate(_mapping(SKILL_ROOT / "manifest.yaml"))
    mcp_contract = json.loads((GOLDEN_ROOT / "mcp-contract.json").read_text(encoding="utf-8"))
    available_tools = set(mcp_contract["tools"])

    assert manifest.minimum_mcp_version == MCP_SANDBOX_PREVIEW_SERVER_VERSION
    assert set(manifest.required_tools) | set(manifest.optional_tools) <= available_tools
    assert set(manifest.required_scopes) | set(manifest.optional_scopes) <= SERVICE_ACCOUNT_SCOPES
    assert manifest.stages[-2:] == ["visual_review", "optional_sandbox_preview"]

    tool_contract = " ".join(manifest.required_tools + manifest.optional_tools).lower()
    assert all(
        forbidden not in tool_contract
        for forbidden in ("publish", "production", "execute_code", "write_sql", "delete")
    )


def test_flagship_skill_package_is_installable_and_has_no_scaffold_placeholders() -> None:
    required_files = {
        "SKILL.md",
        "manifest.yaml",
        "agents/openai.yaml",
        "references/workflow.md",
        "references/examples.md",
        "references/golden-evaluation.md",
        "CHANGELOG.md",
    }
    assert required_files <= {
        str(path.relative_to(SKILL_ROOT)) for path in SKILL_ROOT.rglob("*") if path.is_file()
    }
    combined = "\n".join(
        (SKILL_ROOT / path).read_text(encoding="utf-8") for path in sorted(required_files)
    )
    assert "TODO" not in combined

    openai = _mapping(SKILL_ROOT / "agents/openai.yaml")
    assert "$flowtest-generate-integration-flow" in openai["interface"]["default_prompt"]
    assert openai["policy"]["allow_implicit_invocation"] is True


def test_skill_contract_forbids_product_defect_auto_weakening() -> None:
    manifest = IntegrationFlowSkillManifest.model_validate(_mapping(SKILL_ROOT / "manifest.yaml"))

    assert any("product defect" in item for item in manifest.stop_conditions)
    assert any(
        "never accept, apply, publish, or execute" in item for item in manifest.security_rules
    )


def test_skill_reinspects_accepted_unapplied_proposal_before_preview() -> None:
    manifest = IntegrationFlowSkillManifest.model_validate(_mapping(SKILL_ROOT / "manifest.yaml"))
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (SKILL_ROOT / "references/workflow.md").read_text(encoding="utf-8")

    skill_preview = skill[skill.index("8. Only") :]
    inspect_index = skill_preview.index("inspect_flow_proposal")
    preview_index = skill_preview.index("preview_flow_proposal")
    assert inspect_index < preview_index
    assert "accepted" in skill_preview[inspect_index:preview_index]
    assert "applied=false" in skill_preview[inspect_index:preview_index]

    workflow_preview = workflow[workflow.index("| Preview, optional") :]
    assert "inspect_flow_proposal" in workflow_preview
    assert "preview_flow_proposal" in workflow_preview
    assert "accepted" in workflow_preview
    assert "applied=false" in workflow_preview
    assert any(
        "not been accepted" in item and "already applied" in item
        for item in manifest.stop_conditions
    )
    assert any(
        "accepted review status" in item and "applied=false" in item
        for item in manifest.security_rules
    )


def test_golden_evidence_references_resolve_to_real_tests() -> None:
    for annotation in _annotations():
        for reference in annotation.evidence_refs:
            if not reference.startswith("pytest://"):
                continue
            module_name, test_name = reference.removeprefix("pytest://").split("/", 1)
            test_file = Path(__file__).parent / f"{module_name}.py"
            source = test_file.read_text(encoding="utf-8")
            assert f"def {test_name}(" in source


def test_committed_evaluation_baseline_matches_annotations_and_passes_hard_gates() -> None:
    expected = build_evaluation_baseline(_annotations())
    committed = EvaluationBaseline.model_validate_json(
        (GOLDEN_ROOT / "evaluation-baseline.json").read_text(encoding="utf-8")
    )

    assert committed == expected
    assert committed.release_gates_passed is True
