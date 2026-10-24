"""Actual generated inputs retain required-denominator failures before formal execution."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from test_selftest_bad_targets import _actual_loopback, _inputs
from test_selftest_fixed_baseline import RunningAPI
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.design_quality import QualityRubric, review_design_quality  # noqa: E402
from scripts.selftest.mcp_protocol_runner import stdio_protocol  # noqa: E402
from scripts.selftest.quality_scenarios import QualityVariant, generate_quality_case  # noqa: E402


@pytest.mark.asyncio
async def test_real_sdk_keeps_empty_review_truncated_and_missing_coverage_out_of_ready(
    tasking_context: TaskingTestContext,
    tmp_path: Path,
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    installed, token, _ = await _inputs(api)
    variants: tuple[QualityVariant, ...] = (
        "positive_control",
        "empty_cases",
        "needs_review",
        "truncated",
        "coverage_missing",
    )
    try:
        async with (
            _actual_loopback() as base,
            stdio_protocol(
                python=Path(sys.executable),
                backend=ROOT / "backend",
                api_url=base,
                token=token,
                batch_key="quality-sdk",
                output_dir=tmp_path / "sdk",
            ) as client,
        ):
            rows = [
                await generate_quality_case(client, installed, variant, tmp_path / variant)
                for variant in variants
            ]
        assert [row.decision.readiness for row in rows] == [
            "ready",
            "incomplete",
            "needs_review",
            "incomplete",
            "incomplete",
        ], [row.model_dump(mode="json") for row in rows]
        assert rows[1].proposed_case_count == 0 and rows[1].proposal_id
        assert rows[2].compilation["readiness"] == "needs_review"
        assert len(rows[3].design["scenarios"]) == 1
        assert "REQUIRED_SCENARIO_COVERAGE_MISSING" in rows[3].decision.reason_codes
        assert "REQUIRED_SCENARIO_COVERAGE_MISSING" in rows[4].decision.reason_codes
        assert not any(path.endswith("/runs") or path.endswith("/versions") for path in api.posts)
        cases = await api.object("GET", f"/projects/{installed.project_id}/test-cases")
        plans = await api.object("GET", f"/projects/{installed.project_id}/test-plans")
        assert cases["total"] == plans["total"] == 0
        raw = copy.deepcopy(rows[0].design)
        raw["scenarios"] = []
        empty = review_design_quality(
            raw, None, QualityRubric(required_kinds=("happy_path",), required_cases=1)
        )
        assert empty.readiness == "blocked" and empty.required_count == 1
    finally:
        await api.close()
