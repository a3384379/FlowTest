"""Pure S58 failure-diagnosis and repair-scope contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.failure_triage import FailureSignal, FailureTriageResult, triage_failures
from app.domain.flow_spec import FlowSpec, FlowSpecNode
from app.domain.flow_spec_v2 import FlowSpecV2

RepairKind = Literal["binding", "data", "cleanup", "contract_drift", "oracle"]


class RepairPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_allowed: bool
    allowed_kinds: tuple[RepairKind, ...] = ()
    requires_human_review: bool = True
    product_defect_guard: bool = False
    reason_codes: tuple[str, ...] = ()


class FailureDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["flowtest-failure-diagnosis-v1"] = "flowtest-failure-diagnosis-v1"
    triage: FailureTriageResult
    repair_policy: RepairPolicy


class RepairScopeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RepairKind
    oracle_weakening: bool = False


class RepairScopeError(ValueError):
    """Raised when a proposed document crosses its declared repair boundary."""


def diagnose_failure(signals: list[FailureSignal]) -> FailureDiagnosis:
    triage = triage_failures(signals)
    classification = triage.primary_classification
    product_defect = classification == "PRODUCT_DEFECT" or (
        "PRODUCT_DEFECT" in triage.secondary_candidates
    )
    kinds = list(_ALLOWED_KINDS.get(classification, ()))
    if classification in _ALLOWED_KINDS and any(
        signal.phase == "cleanup" and signal.item_status == "failed" for signal in signals
    ):
        kinds.append("cleanup")
    allowed = tuple(dict.fromkeys(kinds))
    reason_codes = (
        ("PRODUCT_DEFECT_TEST_MUTATION_FORBIDDEN",)
        if product_defect
        else ("NO_SAFE_REPAIR_KIND",)
        if not allowed
        else ("TYPED_REPAIR_PROPOSAL_REQUIRES_REVIEW",)
    )
    return FailureDiagnosis(
        triage=triage,
        repair_policy=RepairPolicy(
            proposal_allowed=bool(allowed) and not product_defect,
            allowed_kinds=allowed if not product_defect else (),
            product_defect_guard=product_defect,
            reason_codes=reason_codes,
        ),
    )


def validate_repair_scope(
    *,
    before: FlowSpec | FlowSpecV2,
    after: FlowSpec | FlowSpecV2,
    diagnosis: FailureDiagnosis,
    kind: RepairKind,
    acknowledge_oracle_weakening: bool,
) -> RepairScopeResult:
    policy = diagnosis.repair_policy
    if policy.product_defect_guard:
        raise RepairScopeError("Product Defect 不允许生成测试修复 Proposal")
    if not policy.proposal_allowed or kind not in policy.allowed_kinds:
        raise RepairScopeError("失败分类不允许该类型的修复 Proposal")
    if type(before) is not type(after):
        raise RepairScopeError("修复不能改变 FlowSpec Schema Version")
    if before == after:
        raise RepairScopeError("修复 Proposal 必须包含实际变更")

    candidate, oracle_weakening = _scoped_candidate(before, after, kind)
    if candidate != after:
        raise RepairScopeError("修复内容超出声明的 Patch 类型边界")
    if oracle_weakening and not acknowledge_oracle_weakening:
        raise RepairScopeError("Oracle 变更必须显式确认可能弱化断言")
    return RepairScopeResult(kind=kind, oracle_weakening=oracle_weakening)


def _scoped_candidate(
    before: FlowSpec | FlowSpecV2,
    after: FlowSpec | FlowSpecV2,
    kind: RepairKind,
) -> tuple[FlowSpec | FlowSpecV2, bool]:
    if kind == "binding":
        return before.model_copy(update={"edges": after.edges, "bindings": after.bindings}), False
    if kind == "data":
        return before.model_copy(
            update={"variables": after.variables, "parameters": after.parameters}
        ), False
    if kind == "cleanup":
        if not isinstance(before, FlowSpecV2) or not isinstance(after, FlowSpecV2):
            raise RepairScopeError("Cleanup Repair 要求 FlowSpec v2")
        return before.model_copy(
            update={"cleanup": after.cleanup, "run_policy": after.run_policy}
        ), False
    if kind == "contract_drift":
        _require_contract_operation_identity(before, after)
        return before.model_copy(
            update={
                "operations": after.operations,
                "assertions": after.assertions,
                "nodes": _replace_assert_nodes(before, after),
            }
        ), _oracle_changed(before, after)
    return before.model_copy(
        update={
            "assertions": after.assertions,
            "nodes": _replace_assert_nodes(before, after),
        }
    ), True


def _replace_assert_nodes(
    before: FlowSpec | FlowSpecV2,
    after: FlowSpec | FlowSpecV2,
) -> list[FlowSpecNode]:
    after_by_id = {node.id: node for node in after.nodes}
    result: list[FlowSpecNode] = []
    for node in before.nodes:
        replacement = after_by_id.get(node.id)
        if replacement is None:
            result.append(node)
        elif node.kind in {"assert", "assertion", "assertion.evaluate"}:
            result.append(node.model_copy(update={"config": replacement.config}))
        else:
            result.append(node)
    return result


def _oracle_changed(before: FlowSpec | FlowSpecV2, after: FlowSpec | FlowSpecV2) -> bool:
    if before.assertions != after.assertions:
        return True
    before_asserts = [
        node for node in before.nodes if node.kind in {"assert", "assertion", "assertion.evaluate"}
    ]
    after_asserts = [
        node for node in after.nodes if node.kind in {"assert", "assertion", "assertion.evaluate"}
    ]
    return before_asserts != after_asserts


def _require_contract_operation_identity(
    before: FlowSpec | FlowSpecV2,
    after: FlowSpec | FlowSpecV2,
) -> None:
    if len(before.operations) != len(after.operations):
        raise RepairScopeError("Contract Drift Repair 不能增删 Operation")
    before_by_ref = {item.ref: item for item in before.operations}
    after_by_ref = {item.ref: item for item in after.operations}
    if before_by_ref.keys() != after_by_ref.keys():
        raise RepairScopeError("Contract Drift Repair 不能改变 Operation Identity")
    stable_fields = ("service_ref", "name", "method", "path")
    for ref, original in before_by_ref.items():
        updated = after_by_ref[ref]
        if any(getattr(original, field) != getattr(updated, field) for field in stable_fields):
            raise RepairScopeError("Contract Drift Repair 只能更新版本和契约指纹")


_ALLOWED_KINDS: dict[str, tuple[RepairKind, ...]] = {
    "BAD_TEST": ("binding", "oracle"),
    "BAD_TEST_DATA": ("data", "binding"),
    "CONTRACT_DRIFT": ("contract_drift", "oracle"),
}
