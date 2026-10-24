"""Validate the exact 94-item acceptance inventory without promoting local checks."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from scripts.selftest.contracts import Contract, Identity, Sha256
from scripts.selftest.io import HarnessError, read_json

LEDGER_PATH = Path(__file__).resolve().parents[2] / "docs/self-verification/acceptance-matrix.json"
ImplementationStatus = Literal["planned", "partial", "in_progress_other_owner", "implemented"]
ValidationStatus = Literal["not_run", "incomplete", "failed", "product_acceptance_pass"]
Profile = Literal[
    "full", "compact", "standalone", "ci", "host", "gui-full", "gui-compact", "gui-standalone"
]


class SourceDocument(Contract):
    filename: Identity
    sha256: Sha256


class Budget(Contract):
    max_requests: int = Field(ge=1, le=500)
    max_runtime_seconds: int = Field(ge=1, le=600)
    max_recursion_depth: Literal[1]


class ProfileValidation(Contract):
    profile: Profile
    status: ValidationStatus
    evidence_dir: str | None = None
    command: str | None = None
    exit_code: int | None = None
    source_digest: Sha256 | None = None
    verification_scope: Literal["full_pack", "selected_suites", "diagnostic_subset"] | None = None
    reason: str = ""

    @model_validator(mode="after")
    def real_pass_requires_evidence(self) -> ProfileValidation:
        if self.status == "product_acceptance_pass" and (
            not self.evidence_dir
            or not self.command
            or self.exit_code != 0
            or self.source_digest is None
            or self.verification_scope is None
        ):
            raise ValueError("真实验收通过必须有构建、命令、退出码、范围及证据目录")
        return self


class LocalCheck(Contract):
    check_id: Identity
    kind: Literal["unit", "asgi_integration", "static"]
    command: str
    status: Literal["passed", "failed", "not_run"]
    exit_code: int | None = None
    log_path: str | None = None
    note: str

    @model_validator(mode="after")
    def passed_check_has_log(self) -> LocalCheck:
        if self.status == "passed" and (self.exit_code != 0 or not self.log_path):
            raise ValueError("本地通过必须绑定实际退出码和日志")
        return self


class AcceptanceVariant(Contract):
    variant_key: Identity
    stage: Literal["S1", "S2", "S3", "S4", "S5"]
    implementation_status: ImplementationStatus
    validation_status: ValidationStatus
    reason: str
    profiles: tuple[ProfileValidation, ...]
    local_check_ids: tuple[Identity, ...] = ()
    scenario_ids: tuple[Identity, ...] = ()
    implementation_paths: tuple[str, ...] = ()
    named_tests: tuple[str, ...] = ()
    mapping_kind: Literal["native_pack", "related_characterization", "unimplemented"] = (
        "related_characterization"
    )
    remaining_work: str = ""
    required_profiles: tuple[Profile, ...] = Field(
        default=("full", "compact", "standalone"), min_length=1
    )

    @model_validator(mode="after")
    def no_empty_aggregate_pass(self) -> AcceptanceVariant:
        names = [item.profile for item in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("同一变体的 profile 不能重复")
        if len(self.required_profiles) != len(set(self.required_profiles)):
            raise ValueError("适用 profile 不能重复")
        if self.mapping_kind == "native_pack" and not self.scenario_ids:
            raise ValueError("native pack 映射必须指明冻结场景")
        if self.validation_status == "product_acceptance_pass" and (
            not set(self.required_profiles) <= set(names)
            or any(item.status != "product_acceptance_pass" for item in self.profiles)
        ):
            raise ValueError("变体不能从空集或部分 profile 推导完整验收通过")
        return self


class AcceptanceItem(Contract):
    acceptance_id: Identity
    priority: Literal["P0", "P1", "P2"]
    source_priority: str
    title: str
    stage: Literal["S1", "S2", "S3", "S4", "S5"]
    raw_expectation: str
    independent_acceptance: str
    profile_requirement: str
    implementation_status: ImplementationStatus
    implementation_paths: tuple[str, ...]
    variants: tuple[AcceptanceVariant, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def distinct_variants(self) -> AcceptanceItem:
        keys = [item.variant_key for item in self.variants]
        if len(keys) != len(set(keys)):
            raise ValueError("同一正式 ID 的 variant_key 不能重复")
        return self


class HistoricalEvidence(Contract):
    kind: Literal["historical_product_acceptance"]
    path: str
    pack: Identity
    scope: str
    source_digest: Sha256 | None = None


class AcceptanceLedger(Contract):
    schema_version: Literal["flowtest-acceptance-ledger-v1"]
    source_baseline: str
    sources: tuple[SourceDocument, ...] = Field(min_length=6, max_length=6)
    scope: str
    budget_per_batch: Budget
    trust: Literal["local_untrusted"]
    validation_rule: str
    historical_evidence: tuple[HistoricalEvidence, ...] = ()
    local_checks: tuple[LocalCheck, ...] = ()
    items: tuple[AcceptanceItem, ...] = Field(min_length=94, max_length=94)

    @model_validator(mode="after")
    def exact_catalog(self) -> AcceptanceLedger:
        families = (
            ("INIT", 4),
            ("API", 12),
            ("ENG", 16),
            ("RUN", 6),
            ("SEC", 4),
            ("CAN", 5),
            ("GUI", 3),
            ("CI", 3),
            ("RET", 1),
            ("MCP", 40),
        )
        expected = {
            f"ST-{family}-{number:03}"
            for family, count in families
            for number in range(1, count + 1)
        }
        actual = [item.acceptance_id for item in self.items]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("账本必须精确保留正式 94 项, 不能删项、重复或替换")
        check_ids = [check.check_id for check in self.local_checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("本地检查 ID 不能重复")
        references = {
            name
            for item in self.items
            for variant in item.variants
            for name in variant.local_check_ids
        }
        if not references <= set(check_ids):
            raise ValueError("变体引用不存在的本地检查")
        return self


def load_ledger(path: Path = LEDGER_PATH) -> AcceptanceLedger:
    return AcceptanceLedger.model_validate(read_json(path))


def render_ledger(ledger: AcceptanceLedger) -> str:
    lines = [
        "# 自测验收实施与证据账本",
        "",
        (
            "本账本保留六份 v2 附件的全部 94 个父 ID, 拆为独立变体。"
            "实施、本地检查、部署 profile 验收分别记录; 单元/ASGI 通过不能升级为真实部署验收。"
            "完整机器记录及六附件 SHA-256 见 [acceptance-matrix.json](acceptance-matrix.json)。"
        ),
        "",
        (
            "每批最多 500 次目标请求、600 秒、递归深度 1。F/C/S 分别验收; "
            "真实 Host 缺席时为 NOT_RUN / WAITING_FOR_HOST。历史子集证据不用于当前构建放行。"
        ),
        "",
        "| 正式 ID | 阶段 | 优先级 | 实施 | 独立变体 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in ledger.items:
        variants = "、".join(
            f"{variant.variant_key} ({variant.validation_status})" for variant in item.variants
        )
        lines.append(
            f"| {item.acceptance_id} | {item.stage} | {item.priority} | "
            f"{item.implementation_status} | {variants} |"
        )
    lines.extend(["", "本地检查(不代表部署 profile 已通过): ", ""])
    lines.extend(
        f"- `{check.check_id}`: {check.kind} / {check.status}; {check.note}。"
        f"日志: `{check.log_path or '未运行'}`。"
        for check in ledger.local_checks
    )
    lines.extend(
        [
            "",
            (
                "原始执行、独立核验、完整性、来源信任及清理分开。"
                "完整父 ID 只有全部适用变体和 profile 的真实证据齐全才能关闭; "
                "源矩阵的共同 profile 要求不能由局部列表缩减。"
                "`validation.md` 保持实际命令和发布门槛的独立记录。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="检查94项验收账本; 本地检查不升级为部署验收")
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--render", action="store_true")
    arguments = parser.parse_args()
    ledger = load_ledger(arguments.ledger)
    if arguments.render:
        arguments.ledger.with_suffix(".md").write_text(render_ledger(ledger), encoding="utf-8")
    if len(ledger.items) != 94:
        raise HarnessError("SELFTEST_ACCEPTANCE_CATALOG_MISMATCH")
    print(
        f"94 acceptance IDs, {sum(len(item.variants) for item in ledger.items)} variants; "
        "deployment evidence remains separate"
    )


if __name__ == "__main__":
    main()
