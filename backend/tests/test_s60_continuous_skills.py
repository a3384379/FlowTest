import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from test_s60_skill_evaluation import _run

from app.domain.continuous_skills import CONTINUOUS_SKILL_PROFILES, ContinuousQASkillManifest
from app.mcp.server import create_mcp_server
from app.services.service_accounts import SERVICE_ACCOUNT_SCOPES

ROOT = Path(__file__).parents[2]
NAMES = tuple(profile.name for profile in CONTINUOUS_SKILL_PROFILES)


def _manifest(name: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / "skills" / name / "manifest.yaml").read_text())


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.asyncio
async def test_continuous_manifest_matches_actual_tools_and_copied_runtime(
    name: str, tmp_path: Path
) -> None:
    manifest = ContinuousQASkillManifest.model_validate(_manifest(name))
    tools = {tool.name for tool in await create_mcp_server().list_tools()}
    assert set(manifest.required_tools + manifest.optional_tools) <= tools
    assert set(manifest.required_scopes + manifest.optional_scopes) <= SERVICE_ACCOUNT_SCOPES
    package = Path(shutil.copytree(ROOT / "skills" / name, tmp_path / name))
    runtime = manifest.evaluation.runtime
    assert runtime is not None
    for reference in (
        manifest.evaluation.annotations,
        manifest.evaluation.baseline,
        manifest.evaluation.guide,
        runtime.entrypoint,
        runtime.requirements,
        runtime.source_map,
    ):
        resolved = (package / reference).resolve()
        assert package in resolved.parents
        assert resolved.is_file()
    result = _run(package, "--check")
    assert result.returncode == 0, result.stderr
    assert "backend tests were not executed" in result.stdout
    provenance = json.loads((package / runtime.source_map).read_text())
    for packaged, source in provenance["files"].items():
        assert (package / "evals" / packaged).read_bytes() == (ROOT / source).read_bytes()
    frontmatter = yaml.safe_load((package / "SKILL.md").read_text().split("---", 2)[1])
    assert frontmatter["name"] == name
    metadata = yaml.safe_load((package / "agents/openai.yaml").read_text())
    assert f"${name}" in metadata["interface"]["default_prompt"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("mutation", ["tool", "scope", "stage", "automatic", "runtime", "extra"])
def test_continuous_manifests_reject_authority_or_contract_expansion(
    name: str, mutation: str
) -> None:
    payload = _manifest(name)
    if mutation == "tool":
        payload["required_tools"].append("flowtest.accept_proposal")
    elif mutation == "scope":
        payload["optional_scopes"].append("admin")
    elif mutation == "stage":
        payload["stages"].append("automatic_publish")
    elif mutation == "automatic":
        payload["automatic_apply"] = True
    elif mutation == "runtime":
        payload["evaluation"].pop("runtime")
    else:
        payload["automatic_override"] = True
    with pytest.raises(ValidationError):
        ContinuousQASkillManifest.model_validate(payload)


def test_continuous_manifests_are_reproducible() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_continuous_skill_manifests.py"), "--check"],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_new_tool_descriptions_are_chinese_product_text() -> None:
    names = {
        "flowtest.inspect_context_diff",
        "flowtest.inspect_affected_flows",
        "flowtest.diagnose_failure",
        "flowtest.inspect_change_regression",
        "flowtest.propose_repair",
        "flowtest.propose_maintenance",
    }
    tools = {tool.name: tool for tool in await create_mcp_server().list_tools()}
    for name in names:
        assert any("\u4e00" <= char <= "\u9fff" for char in tools[name].description)
