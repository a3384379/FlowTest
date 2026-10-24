"""Compare frozen expectations with independent observations, preserving raw results."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import ValidationError

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.contracts import (
    BatchEvidence,
    BatchManifest,
    DigestAssertionEvidence,
    EvidencePage,
    ExecutionEvidence,
    ExpectedOutcome,
    Finding,
    ProjectStateEvidence,
    ProjectStateExpectation,
    ScenarioExpectation,
    ScenarioObservation,
    ScenarioVerification,
    VerificationReport,
    VerificationStatus,
    canonical_digest,
)
from scripts.selftest.verify_engine_golden import verify_binary_file
from scripts.selftest.verify_generation_provenance import (
    verify_generation_provenance,
)
from scripts.selftest.verify_s5_native import verify_s5_native


def verify_batch(
    manifest: BatchManifest, evidence: BatchEvidence, *, now: datetime | None = None
) -> VerificationReport:
    findings = list(_batch_findings(manifest, evidence))
    checked_at = now or datetime.now(UTC)
    batch_expired = checked_at.tzinfo is None or checked_at > manifest.expires_at
    if batch_expired:
        findings.append(_finding("BATCH_EXPIRED", "incomplete", "核验时批次已过期"))
    actual_ids = [item.scenario_id for item in evidence.scenarios]
    if len(actual_ids) != len(set(actual_ids)):
        findings.append(_finding("SCENARIO_DUPLICATE", "mismatched", "实际场景 ID 重复"))
    unexpected = set(actual_ids) - set(manifest.expected_scenario_set)
    if unexpected:
        findings.append(_finding("SCENARIO_UNEXPECTED", "mismatched", "存在未选入本批次的执行场景"))
    observed = {item.scenario_id: item for item in evidence.scenarios}
    results = tuple(
        _verify_scenario(manifest, expected, observed.get(expected.scenario_id))
        for expected in manifest.scenarios
    )
    statuses = {item.verification_status for item in results} | {item.status for item in findings}
    verdict, exit_code = _batch_verdict(statuses)
    integrity: Literal["complete", "missing", "expired"] = "complete"
    if evidence.expired or evidence.collected_at > manifest.expires_at or batch_expired:
        integrity = "expired"
    elif statuses & {"incomplete", "error", "unsupported"}:
        integrity = "missing"
    return VerificationReport(
        batch_key=manifest.batch_key,
        pack_digest=manifest.pack_digest,
        verification_scope=manifest.verification_scope,
        evidence_integrity=integrity,
        batch_verdict=verdict,
        exit_code=exit_code,
        findings=tuple(findings),
        scenarios=results,
    )


def _batch_findings(manifest: BatchManifest, evidence: BatchEvidence) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    identity = (
        "batch_key",
        "nonce",
        "pack_digest",
        "policy_digest",
        "builds",
        "ci_run_id",
        "ci_attempt",
    )
    for field in identity:
        if getattr(manifest, field) != getattr(evidence, field):
            findings.append(
                _finding("BATCH_IDENTITY_MISMATCH", "mismatched", f"批次身份不符: {field}")
            )
    if evidence.collected_at.tzinfo is None or evidence.collected_at < manifest.created_at:
        findings.append(_finding("EVIDENCE_REPLAY", "mismatched", "证据不在本批次时间窗口"))
    if evidence.expired or evidence.collected_at > manifest.expires_at:
        findings.append(_finding("EVIDENCE_EXPIRED", "incomplete", "证据或批次已过期"))
    if evidence.cleanup_status != "completed":
        findings.append(_finding("CLEANUP_INCOMPLETE", "incomplete", "批次必要清理未完成"))
    if evidence.observer_error is not None:
        findings.append(_finding("OBSERVER_ERROR", "error", evidence.observer_error))
    from scripts.selftest.verify_engine_additional import batch_budget_findings

    return (*findings, *batch_budget_findings(manifest, evidence))


def _verify_scenario(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation | None,
) -> ScenarioVerification:
    findings = list(_scenario_findings(manifest, expected, observed))
    statuses = {item.status for item in findings}
    status: VerificationStatus = "matched"
    priority: tuple[VerificationStatus, ...] = (
        "incomplete",
        "unsupported",
        "mismatched",
        "error",
    )
    for candidate in priority:
        if candidate in statuses:
            status = candidate
    return ScenarioVerification(
        scenario_id=expected.scenario_id,
        variant_key=expected.variant_key,
        expected=expected.expected,
        observed_status=None
        if observed is None or observed.execution is None
        else observed.execution.status,
        execution_id=None
        if observed is None or observed.execution is None
        else observed.execution.id,
        verification_status=status,
        findings=tuple(findings),
    )


def _scenario_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation | None,
) -> tuple[Finding, ...]:
    if observed is None:
        return (_finding("REQUIRED_SCENARIO_MISSING", "incomplete", "选定场景没有实际执行记录"),)
    findings = list(_availability_findings(expected, observed))
    findings.extend(_execution_findings(manifest, expected, observed))
    findings.extend(_journal_findings(manifest, expected, observed))
    findings.extend(_resource_absence_findings(manifest, expected, observed))
    findings.extend(_resource_collection_findings(manifest, expected, observed))
    findings.extend(_project_state_findings(manifest, expected, observed))
    findings.extend(_response_field_findings(manifest, expected, observed))
    findings.extend(_error_envelope_findings(manifest, expected, observed))
    findings.extend(verify_binary_file(expected.expected, observed))
    findings.extend(verify_s5_native(expected.expected, observed))
    if "control_records" in expected.required_evidence:
        findings.extend(_page_findings(observed.control_pages))
    if manifest.batch_kind == "mcp_generated" or "provenance" in expected.required_evidence:
        findings.extend(verify_generation_provenance(manifest, expected, observed))
    return tuple(findings)


def _error_envelope_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    wanted = expected.expected.error_envelopes
    if not wanted:
        return ()
    execution = observed.execution
    if execution is None or len(wanted) != len(observed.error_envelopes):
        return (_finding("ERROR_ENVELOPE_MISSING", "incomplete", "业务负向错误证据缺失"),)
    wanted_values = [canonical_digest(item.model_dump(mode="json")) for item in wanted]
    observed_values = [
        canonical_digest(
            item.model_dump(
                mode="json", exclude={"project_id", "execution_id", "response_trace_id"}
            )
        )
        for item in observed.error_envelopes
    ]
    binding_ok = all(
        item.project_id == manifest.project_id
        and item.execution_id == execution.id
        and item.response_trace_id == item.trace_id
        and _negative_node_ran(execution, item.node_id)
        for item in observed.error_envelopes
    )
    if sorted(wanted_values) != sorted(observed_values) or not binding_ok:
        return (_finding("ERROR_ENVELOPE_MISMATCH", "mismatched", "业务负向状态、错误或Trace不符"),)
    return ()


def _negative_node_ran(execution: ExecutionEvidence, node_id: str) -> bool:
    nodes = [node for node in execution.nodes if node.node_id == node_id]
    return len(nodes) == 1 and (
        nodes[0].node_type,
        nodes[0].phase,
        nodes[0].status,
        nodes[0].attempts,
    ) == ("api", "main", "passed", 1)


def _availability_findings(
    expected: ScenarioExpectation, observed: ScenarioObservation
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    if observed.variant_key != expected.variant_key:
        findings.append(_finding("VARIANT_MISMATCH", "mismatched", "执行变体不匹配"))
    if observed.read_error is not None:
        findings.append(_finding("EVIDENCE_READ_ERROR", "error", observed.read_error))
    if observed.truncated or not observed.evidence_complete:
        findings.append(_finding("EVIDENCE_TRUNCATED", "incomplete", "场景证据不完整或被截断"))
    if expected.cleanup_required and observed.cleanup_status != "completed":
        findings.append(_finding("SCENARIO_CLEANUP_INCOMPLETE", "incomplete", "场景必要清理未完成"))
    if (
        "postcondition" in expected.required_evidence
        and expected.expected.resource_absence is None
        and observed.postcondition_matched is not True
    ):
        findings.append(
            _finding("POSTCONDITION_MISSING", "incomplete", "缺少匹配的独立业务后置查询")
        )
    return tuple(findings)


def _resource_absence_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    golden, actual = expected.expected.resource_absence, observed.resource_absence
    if golden is None:
        return ()
    if actual is None or not actual.complete:
        return (_finding("POSTCONDITION_MISSING", "incomplete", "业务资源后置查询缺失或不完整"),)
    checks = (
        (
            actual.project_id == golden.project_id and actual.resource_kind == golden.resource_kind,
            "POSTCONDITION_SCOPE_MISMATCH",
            "业务后置查询范围错误",
        ),
        (
            actual.observed_at.tzinfo is not None
            and manifest.created_at <= actual.observed_at <= manifest.expires_at
            and observed.execution is not None
            and observed.execution.completed_at is not None
            and actual.observed_at >= observed.execution.completed_at,
            "POSTCONDITION_REPLAY",
            "业务后置查询没有发生在本次执行完成后",
        ),
        (
            not set(golden.absent_names) & set(actual.returned_names),
            "POSTCONDITION_RESOURCE_PRESENT",
            "应删除的本批业务资源仍存在",
        ),
    )
    return tuple(
        _finding(code, "mismatched", message) for valid, code, message in checks if not valid
    )


def _resource_collection_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    goldens = expected.expected.resource_absences
    if not goldens:
        return ()
    actual = {(item.project_id, item.resource_kind): item for item in observed.resource_absences}
    required = {(item.project_id, item.resource_kind) for item in goldens}
    if len(actual) != len(observed.resource_absences) or set(actual) != required:
        return (_finding("POSTCONDITION_SET_MISMATCH", "incomplete", "业务后置查询集合缺失或重复"),)
    return tuple(
        finding
        for golden in goldens
        for finding in _resource_absence_findings(
            manifest,
            expected.model_copy(
                update={
                    "expected": expected.expected.model_copy(update={"resource_absence": golden})
                }
            ),
            observed.model_copy(
                update={"resource_absence": actual[(golden.project_id, golden.resource_kind)]}
            ),
        )
    )


def _project_state_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    golden, actual = expected.expected.project_state, observed.project_state
    if golden is None:
        return ()
    if actual is None:
        return (_finding("PROJECT_STATE_MISSING", "incomplete", "创建项目的独立查询证据缺失"),)
    wanted = canonical_digest(golden.model_dump(mode="json"))
    projection = actual.model_dump(mode="json", include=set(type(golden).model_fields))
    checks = (
        (
            wanted == canonical_digest(projection),
            "PROJECT_STATE_MISMATCH",
            "项目组织、创建者或名称不符",
        ),
        (
            actual.created_at.tzinfo is not None
            and manifest.created_at <= actual.created_at <= manifest.expires_at,
            "PROJECT_CREATION_REPLAY",
            "项目创建时间不属于本批",
        ),
        (
            observed.execution is not None
            and observed.execution.completed_at is not None
            and actual.observed_at.tzinfo is not None
            and observed.execution.completed_at <= actual.observed_at <= manifest.expires_at,
            "PROJECT_OBSERVATION_REPLAY",
            "项目查询没有发生在本次执行后",
        ),
        (
            _disposal_matches(manifest, golden, actual),
            "DISPOSABLE_TARGET_CLEANUP_PENDING",
            "无项目删除API, 等待精确销毁本批隔离目标",
        ),
    )
    return tuple(
        _finding(code, "incomplete" if code.endswith("PENDING") else "mismatched", message)
        for valid, code, message in checks
        if not valid
    )


def _disposal_matches(
    manifest: BatchManifest,
    expected: ProjectStateExpectation,
    actual: ProjectStateEvidence,
) -> bool:
    receipt = actual.disposal_receipt
    identity = expected.disposable_target
    if actual.disposal_status != "completed" or receipt is None or identity is None:
        return False
    identity_matches = canonical_digest(identity.model_dump(mode="json")) == canonical_digest(
        receipt.model_dump(mode="json", include=set(type(identity).model_fields))
    )
    return (
        identity_matches
        and identity.target_image == manifest.builds.target
        and receipt.binding_nonce == expected.disposal_binding_nonce
        and receipt.containers_absent
        and receipt.volumes_absent
        and receipt.networks_absent
        and receipt.removed_at.tzinfo is not None
        and actual.observed_at <= receipt.removed_at <= manifest.expires_at
    )


def _response_field_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    goldens, fields = expected.expected.response_fields, observed.response_fields
    if not goldens and "response_fields" not in expected.required_evidence:
        return ()
    actual = {(item.api_source, item.node_id, item.field): item for item in fields}
    required = {(item.api_source, item.node_id, item.field) for item in goldens}
    if len(actual) != len(fields) or set(actual) != required:
        return (
            _finding(
                "RESPONSE_FIELD_SET_MISMATCH",
                "incomplete",
                "响应字段证据缺失、重复或来源被替换",
            ),
        )
    findings: list[Finding] = []
    execution = observed.execution
    for golden in goldens:
        value = actual[(golden.api_source, golden.node_id, golden.field)]
        nodes = (
            ()
            if execution is None
            else tuple(node for node in execution.nodes if node.node_id == golden.node_id)
        )
        if (
            len(nodes) != 1
            or nodes[0].node_type != "api"
            or nodes[0].phase != "main"
            or nodes[0].status != "passed"
            or nodes[0].attempts != 1
        ):
            findings.append(
                _finding(
                    "RESPONSE_FIELD_NODE_MISSING",
                    "incomplete",
                    "缺少唯一实际完成的响应来源 API 节点",
                )
            )
        if execution is None or (
            value.batch_key != manifest.batch_key
            or value.scenario_id != expected.scenario_id
            or value.project_id != manifest.project_id
            or value.api_source.project_id != manifest.project_id
            or value.execution_id != execution.id
            or value.workflow_version_id != execution.workflow_version_id
            or value.observed_at.tzinfo is None
            or execution.completed_at is None
            or not execution.completed_at <= value.observed_at <= manifest.expires_at
        ):
            findings.append(
                _finding(
                    "RESPONSE_FIELD_BINDING_MISMATCH",
                    "mismatched",
                    "响应字段属于其他执行、范围或时间窗口",
                )
            )
        if value.actual != golden.expected:
            findings.append(
                _finding(
                    "RESPONSE_FIELD_VALUE_MISMATCH",
                    "mismatched",
                    "响应名称与本批运行前固定业务期望不同",
                )
            )
    return tuple(findings)


def _execution_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    execution = observed.execution
    if execution is None:
        return (_finding("EXECUTION_MISSING", "incomplete", "没有正式执行证据"),)
    findings = list(_attempt_findings(expected, observed))
    if execution.project_id != manifest.project_id or execution.run_purpose != "standard":
        findings.append(
            _finding("EXECUTION_BINDING_MISMATCH", "mismatched", "执行跨项目或仅为 Preview")
        )
    if not manifest.created_at <= execution.started_at <= manifest.expires_at:
        findings.append(_finding("EXECUTION_REPLAY", "mismatched", "执行不属于本批次时间窗口"))
    if execution.status in {"queued", "running"}:
        findings.append(
            _finding("OBSERVER_DEADLINE_EXCEEDED", "incomplete", "截止时原执行尚未终态")
        )
    elif execution.status != expected.expected.execution_status:
        findings.append(
            _finding("EXECUTION_STATUS_MISMATCH", "mismatched", "原始执行状态不符合固定期望")
        )
    if execution.error_code != expected.expected.error_code:
        findings.append(
            _finding("EXECUTION_ERROR_MISMATCH", "mismatched", "原始错误码不符合固定期望")
        )
    if (
        expected.cleanup_required
        and execution.cleanup_status == "failed"
        and expected.expected.cleanup_status != "failed"
    ):
        findings.append(_finding("EXECUTION_CLEANUP_FAILED", "mismatched", "原执行清理阶段失败"))
    from scripts.selftest.verify_engine_additional import engine_findings

    findings.extend(engine_findings(manifest, expected, observed))
    findings.extend(_phase_status_findings(expected.expected, execution))
    findings.extend(_nested_node_findings(expected.expected, execution))
    findings.extend(_node_findings(expected.expected, observed))
    findings.extend(_terminal_completion_findings(observed))
    return tuple(findings)


def _phase_status_findings(
    expected: ExpectedOutcome, execution: ExecutionEvidence
) -> tuple[Finding, ...]:
    return tuple(
        _finding(
            "EXECUTION_PHASE_STATUS_MISMATCH",
            "mismatched",
            "原执行阶段状态不符合固定期望",
        )
        for wanted, actual in (
            (expected.main_status, execution.main_status),
            (expected.cleanup_status, execution.cleanup_status),
        )
        if wanted is not None and wanted != actual
    )


def _nested_node_findings(
    expected: ExpectedOutcome, execution: ExecutionEvidence
) -> tuple[Finding, ...]:
    if not expected.nested_nodes:
        return ()
    if not execution.nested_nodes_complete:
        return (_finding("NESTED_NODES_INCOMPLETE", "incomplete", "嵌套节点证据不完整"),)
    fields = {"node_id", "phase", "status", "error_code", "attempts"}
    wanted = [canonical_digest(item.model_dump(mode="json")) for item in expected.nested_nodes]
    actual = [
        canonical_digest(item.model_dump(mode="json", include=fields))
        for item in execution.nested_nodes
    ]
    if sorted(wanted) != sorted(actual):
        return (_finding("NESTED_NODE_SET_MISMATCH", "mismatched", "嵌套节点集合或失败事实不符"),)
    return ()


def _terminal_completion_findings(observed: ScenarioObservation) -> tuple[Finding, ...]:
    if any(
        item.status in {"passed", "failed", "cancelled"} and item.completed_at is None
        for item in observed.attempts
    ):
        return (_finding("EXECUTION_COMPLETION_MISSING", "incomplete", "终态执行缺少完成时间"),)
    return ()


def _attempt_findings(
    expected: ScenarioExpectation, observed: ScenarioObservation
) -> tuple[Finding, ...]:
    attempts = observed.attempts
    findings: list[Finding] = []
    if len(attempts) != expected.expected_attempts:
        findings.append(_finding("ATTEMPT_MISSING", "incomplete", "执行尝试数与冻结预期不符"))
    if len({item.id for item in attempts}) != len(attempts):
        findings.append(_finding("ATTEMPT_DUPLICATE", "mismatched", "执行尝试 ID 重复"))
    if attempts and attempts[-1] != observed.execution:
        findings.append(
            _finding("ATTEMPT_LATEST_MISMATCH", "mismatched", "最后一次尝试与实际执行不一致")
        )
    if any(item.status in {"queued", "running"} for item in attempts):
        findings.append(_finding("ATTEMPT_NONTERMINAL", "incomplete", "仍有非终态的执行尝试"))
    if any(item.status != expected.expected.execution_status for item in attempts):
        findings.append(
            _finding(
                "EARLIER_ATTEMPT_MISMATCH",
                "mismatched",
                "重试不能覆盖先前不符合预期的结果",
            )
        )
    if any(item.error_code != expected.expected.error_code for item in attempts):
        findings.append(
            _finding("EARLIER_ATTEMPT_ERROR_MISMATCH", "mismatched", "历史尝试错误码不同")
        )
    if observed.execution is not None and any(
        (
            item.project_id,
            item.workflow_id,
            item.workflow_version_id,
            item.environment_id,
        )
        != (
            observed.execution.project_id,
            observed.execution.workflow_id,
            observed.execution.workflow_version_id,
            observed.execution.environment_id,
        )
        for item in attempts
    ):
        findings.append(
            _finding("ATTEMPT_IDENTITY_MISMATCH", "mismatched", "历史尝试引用了不同资产")
        )
    return tuple(findings)


def _node_findings(expected: ExpectedOutcome, observed: ScenarioObservation) -> tuple[Finding, ...]:
    execution = observed.execution
    if execution is None:
        return ()
    nodes = {item.node_id: item for item in (*execution.nodes, *execution.nested_nodes)}
    findings: list[Finding] = []
    if len(nodes) != len(execution.nodes) + len(execution.nested_nodes):
        findings.append(_finding("NODE_DUPLICATE", "mismatched", "节点执行记录重复"))
    if expected.node_id is not None:
        node = nodes.get(expected.node_id)
        if node is None:
            findings.append(
                _finding("FAILURE_NODE_MISSING", "mismatched", "没有执行到固定失败节点")
            )
        elif (node.phase, node.status, node.error_code) != (
            expected.phase,
            "failed",
            expected.error_code,
        ):
            findings.append(
                _finding(
                    "FAILURE_LOCATION_MISMATCH",
                    "mismatched",
                    "失败节点、阶段或错误码不匹配",
                )
            )
    for assertion in expected.assertions:
        node = nodes.get(assertion.node_id)
        matching = (
            []
            if node is None
            else [item for item in node.assertions if item.name == assertion.name]
        )
        if (
            node is None
            or node.phase != assertion.phase
            or len(matching) != 1
            or node.status not in {"passed", "failed"}
            or node.attempts < 1
        ):
            findings.append(
                _finding(
                    "ASSERTION_EVIDENCE_MISSING",
                    "incomplete",
                    "断言记录缺失、重复或阶段不匹配",
                )
            )
        elif not _assertion_matches(assertion, matching[0]):
            findings.append(
                _finding(
                    "ASSERTION_VALUE_MISMATCH",
                    "mismatched",
                    "实际断言值或结论与黄金期望不符",
                )
            )
    return tuple(findings)


def _assertion_matches(expected: object, actual: object) -> bool:
    from scripts.selftest.contracts import AssertionEvidence, AssertionExpectation

    if not isinstance(expected, AssertionExpectation):
        return False
    if isinstance(actual, DigestAssertionEvidence):
        return (
            actual.passed == expected.passed
            and actual.expected_digest == canonical_digest(expected.expected)
            and actual.actual_digest == canonical_digest(expected.actual)
        )
    if isinstance(actual, AssertionEvidence):
        return canonical_digest(actual.model_dump(mode="json")) == canonical_digest(
            expected.model_dump(mode="json", exclude={"node_id", "phase"})
        )
    return False


def _journal_findings(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    if (
        "fixture_journal" not in expected.required_evidence
        and not expected.expected.expected_request_value_presence
    ):
        return ()
    journal = observed.journal
    if journal is None:
        return (_finding("FIXTURE_RECEIPT_MISSING", "incomplete", "缺少独立目标回执"),)
    findings: list[Finding] = []
    if (journal.batch_key, journal.scenario_id, journal.nonce) != (
        expected.fixture_batch_key or manifest.batch_key,
        expected.scenario_id,
        manifest.nonce,
    ):
        findings.append(
            _finding("FIXTURE_BINDING_MISMATCH", "mismatched", "目标回执属于其他批次或场景")
        )
    if (
        journal.fixture_digest != manifest.builds.fixture
        or journal.fixture_epoch != manifest.fixture_epoch
    ):
        findings.append(
            _finding(
                "FIXTURE_IDENTITY_MISMATCH",
                "mismatched",
                "目标夹具构建或进程 epoch 发生变化",
            )
        )
    if journal.truncated or journal.expired or journal.request_count != len(journal.entries):
        findings.append(
            _finding(
                "FIXTURE_RECEIPT_INCOMPLETE",
                "incomplete",
                "目标回执过期、截断或计数不完整",
            )
        )
    if journal.epoch_changed or any(
        item.fixture_epoch not in {None, journal.fixture_epoch} for item in journal.entries
    ):
        findings.append(_finding("FIXTURE_EPOCH_CHANGED", "mismatched", "目标进程重启, 证据不连续"))
    sequences = [item.sequence for item in journal.entries]
    if sequences != list(range(1, journal.request_count + 1)):
        findings.append(
            _finding(
                "FIXTURE_SEQUENCE_MISMATCH",
                "mismatched",
                "目标请求回执重复或序列不完整",
            )
        )
    if (
        expected.expected.request_count is not None
        and journal.request_count != expected.expected.request_count
    ):
        findings.append(
            _finding("REQUEST_COUNT_MISMATCH", "mismatched", "目标实际请求次数与固定期望不符")
        )
    findings.extend(_fixture_response_findings(expected, observed))
    findings.extend(_request_value_presence_findings(expected, observed))
    return tuple(findings)


def _request_value_presence_findings(
    expected: ScenarioExpectation, observed: ScenarioObservation
) -> tuple[Finding, ...]:
    wanted = expected.expected.expected_request_value_presence
    if not wanted:
        return ()
    journal = observed.journal
    if journal is None:
        return (_finding("FIXTURE_RECEIPT_MISSING", "incomplete", "缺少独立请求存在性回执"),)
    actual = tuple(item.request_value_present for item in journal.entries)
    if actual != wanted:
        return (
            _finding(
                "REQUEST_VALUE_PRESENCE_MISMATCH",
                "mismatched",
                "合成请求的value遗漏与显式null不符",
            ),
        )
    return ()


def _fixture_response_findings(
    expected: ScenarioExpectation, observed: ScenarioObservation
) -> tuple[Finding, ...]:
    journal = observed.journal
    responses = expected.expected.fixture_responses
    if journal is None or not responses:
        return ()
    if len(responses) != len(journal.entries):
        return (_finding("FIXTURE_RESPONSE_MISSING", "incomplete", "独立响应证据条数不匹配"),)
    findings: list[Finding] = []
    for wanted, actual in zip(responses, journal.entries, strict=True):
        body = actual.response_body
        matches = body is not None and (
            wanted.response_status,
            wanted.actual,
            wanted.code,
            wanted.authorization_present,
            wanted.cookie_present,
        ) == (
            actual.response_status,
            body.actual,
            body.code,
            actual.authorization_present,
            actual.cookie_present,
        )
        if not matches:
            findings.append(
                _finding(
                    "FIXTURE_RESPONSE_MISMATCH",
                    "mismatched",
                    "独立目标响应或认证状态不匹配",
                )
            )
        if (
            wanted.synthetic_precedence_header is not None
            and wanted.synthetic_precedence_header != actual.synthetic_precedence_header
        ):
            findings.append(
                _finding(
                    "SYNTHETIC_HEADER_MISMATCH",
                    "mismatched",
                    "独立合成 Header 值或重复数不符",
                )
            )
    return tuple(findings)


def _page_findings(pages: tuple[EvidencePage, ...]) -> tuple[Finding, ...]:
    if not pages:
        return (_finding("CONTROL_PAGE_MISSING", "incomplete", "缺少控制记录分页证据"),)
    first = pages[0]
    page_count = max(1, (first.total + first.page_size - 1) // first.page_size)
    valid = (
        [page.page for page in pages] == list(range(1, page_count + 1))
        and all(
            page.total == first.total and page.page_size == first.page_size and not page.truncated
            for page in pages
        )
        and [ordinal for page in pages for ordinal in page.ordinals] == list(range(first.total))
    )
    return (
        ()
        if valid
        else (_finding("CONTROL_PAGE_INCOMPLETE", "incomplete", "控制记录分页截断、重复或缺失"),)
    )


def _batch_verdict(
    statuses: set[VerificationStatus],
) -> tuple[Literal["passed", "failed", "blocked"], Literal[0, 1, 2]]:
    if "mismatched" in statuses:
        return "failed", 1
    if statuses & {"incomplete", "error", "pending", "unsupported"}:
        return "blocked", 2
    return "passed", 0


def _finding(code: str, status: VerificationStatus, message: str) -> Finding:
    return Finding(code=code, status=status, message=message)


def write_report(report: VerificationReport, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "verification.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    suite = Element("testsuite", name="flowtest-independent-verification")
    for result in report.scenarios:
        case = SubElement(
            suite,
            "testcase",
            classname=report.verification_scope,
            name=f"{result.scenario_id}:{result.variant_key}",
        )
        SubElement(case, "system-out").text = json.dumps(
            {
                "execution_id": str(result.execution_id),
                "observed_status": result.observed_status,
            },
            ensure_ascii=False,
        )
        if result.verification_status != "matched":
            SubElement(
                case, "failure", message=result.verification_status
            ).text = result.model_dump_json()
    if report.findings:
        case = SubElement(suite, "testcase", classname="integrity", name="batch-integrity")
        SubElement(case, "failure", message=report.batch_verdict).text = json.dumps(
            [item.model_dump(mode="json") for item in report.findings],
            ensure_ascii=False,
        )
    suite.set("tests", str(len(suite)))
    suite.set("failures", str(sum(item.find("failure") is not None for item in suite)))
    (directory / "verification.junit.xml").write_bytes(
        tostring(suite, encoding="utf-8", xml_declaration=True)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="独立核验自测证据; 不授予正式 CI 信任")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = BatchManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
        evidence = BatchEvidence.model_validate_json(args.evidence.read_text(encoding="utf-8"))
        report = verify_batch(manifest, evidence)
    except (OSError, ValidationError, ValueError) as error:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        report = VerificationReport(
            batch_key="invalid-input",
            pack_digest="0" * 64,
            verification_scope="diagnostic_subset",
            evidence_integrity="missing",
            batch_verdict="blocked",
            exit_code=2,
            scenarios=(),
            findings=(_finding("OBSERVER_INPUT_ERROR", "error", type(error).__name__),),
        )
        write_report(report, args.output_dir)
        return 2
    write_report(report, args.output_dir)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
