"""Read-only observed Design/compiler projections for independent quality checks."""

from typing import Literal

from scripts.selftest.contracts import Contract
from scripts.selftest.design_quality import QualityDecision
from scripts.selftest.io import JsonObject

QualityVariant = Literal[
    "positive_control", "empty_cases", "needs_review", "truncated", "coverage_missing"
]


class QualityCaseResult(Contract):
    variant: QualityVariant
    api_id: str
    api_version: int
    contract_fingerprint: str
    design: JsonObject
    design_fingerprint: str
    policy: JsonObject
    generation: JsonObject
    generation_envelope: JsonObject
    compilation_envelope: JsonObject | None
    context: JsonObject
    compilation: JsonObject | None
    proposed_case_count: int | None = None
    proposal_id: str | None = None
    decision: QualityDecision
