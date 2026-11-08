"""Inventory and anti-green checks, not deployment acceptance evidence."""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.acceptance_ledger import (  # noqa: E402
    AcceptanceLedger,
    LocalCheck,
    load_ledger,
    render_ledger,
)


def payload() -> dict:
    return json.loads((ROOT / "docs/self-verification/acceptance-matrix.json").read_text())


def test_acceptance_catalog_preserves_all_94_ids_and_341_independent_variants() -> None:
    ledger = load_ledger()
    assert len(ledger.items) == 94
    assert sum(len(item.variants) for item in ledger.items) == 341
    assert len(ledger.sources) == 6
    assert ledger.trust == "local_untrusted"
    assert ledger.budget_per_batch.max_requests <= 500
    assert ledger.budget_per_batch.max_runtime_seconds <= 600
    assert ledger.budget_per_batch.max_recursion_depth == 1
    assert all(item.implementation_paths for item in ledger.items)
    for item in ledger.items:
        for variant in item.variants:
            assert variant.implementation_paths
            for relative in variant.implementation_paths:
                assert (ROOT / relative).exists(), (item.acceptance_id, relative)
            for target in variant.named_tests:
                relative, name = target.split("::")
                tree = ast.parse((ROOT / relative).read_text())
                assert name in {
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                }, target
    assert "94" in render_ledger(ledger)


@pytest.mark.parametrize("tamper", ["missing", "duplicate", "replace", "duplicate_variant"])
def test_acceptance_catalog_rejects_denominator_changes(tamper: str) -> None:
    value = payload()
    if tamper == "missing":
        value["items"].pop()
    elif tamper == "duplicate":
        value["items"][-1] = copy.deepcopy(value["items"][0])
    elif tamper == "replace":
        value["items"][-1]["acceptance_id"] = "ST-MCP-999"
    else:
        value["items"][0]["variants"].append(copy.deepcopy(value["items"][0]["variants"][0]))
    with pytest.raises(ValidationError):
        AcceptanceLedger.model_validate(value)


@pytest.mark.parametrize("profiles", [[], ["standalone"]])
def test_local_or_single_profile_pass_cannot_close_all_applicable_profiles(
    profiles: list[str],
) -> None:
    value = payload()
    variant = value["items"][0]["variants"][0]
    variant["validation_status"] = "product_acceptance_pass"
    variant["profiles"] = [
        {
            "profile": profile,
            "status": "product_acceptance_pass",
            "command": "synthetic-unit-command",
            "exit_code": 0,
            "evidence_dir": "/unit-only/not-deployment",
            "source_digest": "a" * 64,
            "verification_scope": "full_pack",
        }
        for profile in profiles
    ]
    with pytest.raises(ValidationError, match="空集或部分 profile"):
        AcceptanceLedger.model_validate(value)


def test_unrecorded_local_test_and_logless_pass_are_rejected() -> None:
    value = payload()
    value["items"][0]["variants"][0]["local_check_ids"] = ["does-not-exist"]
    with pytest.raises(ValidationError, match="不存在的本地检查"):
        AcceptanceLedger.model_validate(value)
    with pytest.raises(ValidationError, match="实际退出码和日志"):
        LocalCheck(
            check_id="unit-only",
            kind="unit",
            command="synthetic-unit-command",
            status="passed",
            exit_code=0,
            note="不能省略日志",
        )


def test_native_mapping_cannot_be_claimed_without_a_frozen_scenario() -> None:
    value = payload()
    variant = value["items"][0]["variants"][0]
    variant["mapping_kind"] = "native_pack"
    variant["scenario_ids"] = []
    with pytest.raises(ValidationError, match="冻结场景"):
        AcceptanceLedger.model_validate(value)
