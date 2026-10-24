"""Cross-check observed, published resource relationships; source_ref is never evidence."""

from __future__ import annotations

from datetime import datetime

from scripts.selftest.contracts import (
    BatchManifest,
    DigestAssertionEvidence,
    Finding,
    GenerationProvenance,
    ScenarioExpectation,
    ScenarioObservation,
    canonical_digest,
)


def verify_generation_provenance(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    observed: ScenarioObservation,
) -> tuple[Finding, ...]:
    source = observed.provenance
    if source is None or observed.execution is None:
        return (_missing("GENERATION_PROVENANCE_MISSING", "缺少本轮生成来源或正式执行"),)
    findings = list(_identity_findings(manifest, expected, source))
    findings.extend(_resource_findings(manifest, source))
    findings.extend(_design_source_findings(manifest, expected, source))
    findings.extend(_suite_findings(expected, source))
    findings.extend(_execution_findings(observed, source))
    findings.extend(_oracle_findings(expected, observed, source))
    findings.extend(_call_findings(manifest, expected, source))
    return tuple(findings)


def _identity_findings(
    manifest: BatchManifest, expected: ScenarioExpectation, source: GenerationProvenance
) -> tuple[Finding, ...]:
    checks = (
        (source.batch_key == manifest.batch_key, "GENERATION_BATCH_MISMATCH", "来源属于其他批次"),
        (
            source.scenario_id == expected.scenario_id,
            "GENERATION_SCENARIO_MISMATCH",
            "生成场景不匹配",
        ),
        (
            source.generation_mode == manifest.generation_mode,
            "GENERATION_MODE_MISMATCH",
            "生成模式不匹配",
        ),
        (not source.assisted, "GENERATION_ASSISTED", "人工修订不能计为首次生成成功"),
        (
            source.generation_mode != "host_llm_mcp" or source.host is not None,
            "HOST_EVIDENCE_MISSING",
            "真实宿主模式缺少宿主、模型或预算证据",
        ),
    )
    return _failed_checks(checks)


def _resource_findings(
    manifest: BatchManifest, source: GenerationProvenance
) -> tuple[Finding, ...]:
    workflow, case, run = source.workflow, source.case, source.run
    same_project = all(
        value == manifest.project_id
        for value in (
            source.api_source.project_id,
            source.workflow_proposal.project_id,
            source.case_proposal.project_id,
            workflow.project_id,
            case.project_id,
            run.project_id,
        )
    )
    checks = (
        (same_project, "GENERATION_PROJECT_MISMATCH", "生成资源跨项目"),
        (
            set(workflow.api_sources) == _expected_sources(source),
            "WORKFLOW_API_SOURCE_MISMATCH",
            "发布流程没有固定设计来源的 API 版本及契约",
        ),
        (
            source.workflow_proposal.review_status == "accepted"
            and source.workflow_proposal.materialized_resource_id == workflow.id,
            "WORKFLOW_MATERIALIZATION_MISMATCH",
            "流程提案未被接受或物化 ID 不一致",
        ),
        (
            source.case_proposal.review_status == "accepted"
            and source.case_proposal.materialized_resource_id == case.id,
            "CASE_MATERIALIZATION_MISMATCH",
            "Case 提案未被接受或物化 ID 不一致",
        ),
        (
            source.case_proposal.route == "controlled_write"
            and source.case_proposal.item_id is not None,
            "CASE_REVIEW_ROUTE_INVALID",
            "Case 必须来自逐项接受并物化的真实变更项",
        ),
        (
            case.workflow_id == workflow.id and case.workflow_version == workflow.version,
            "CASE_WORKFLOW_VERSION_MISMATCH",
            "Case 未引用本轮已发布流程版本",
        ),
        (
            run.target_id == case.id and run.target_version == case.version,
            "PLAN_CASE_VERSION_MISMATCH",
            "计划展开快照未引用本轮 Case 发布版本",
        ),
        (
            run.workflow_id == workflow.id
            and run.workflow_version == workflow.version
            and run.environment_id == case.environment_id,
            "PLAN_WORKFLOW_VERSION_MISMATCH",
            "计划展开的流程或环境与发布引用不一致",
        ),
    )
    return _failed_checks(checks)


def _expected_sources(source: GenerationProvenance) -> set[object]:
    return {item.api_source for item in source.design_sources} or {source.api_source}


def _design_source_findings(
    manifest: BatchManifest, expected: ScenarioExpectation, source: GenerationProvenance
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    if expected.expected_api_sources and (
        _expected_sources(source) != set(expected.expected_api_sources)
        or set(source.workflow.api_sources) != set(expected.expected_api_sources)
    ):
        findings.append(
            _mismatch("FROZEN_API_SOURCE_SET_MISMATCH", "来源与运行前固定的 API 集合不符")
        )
    if expected.expected_design_sources and set(source.design_sources) != set(
        expected.expected_design_sources
    ):
        findings.append(
            _mismatch("FROZEN_DESIGN_SOURCE_SET_MISMATCH", "设计来源或设计指纹被替换或删除")
        )
    if (
        expected.expected_combined_design_fingerprint is not None
        and source.combined_design_fingerprint != expected.expected_combined_design_fingerprint
    ):
        findings.append(
            _mismatch("FROZEN_COMBINED_DESIGN_MISMATCH", "组合设计与运行前固定指纹不同")
        )
    if not source.design_sources:
        return tuple(findings)
    identities = [(item.api_source, item.operation_ref) for item in source.design_sources]
    checks = (
        (
            all(
                item.api_source.project_id == manifest.project_id for item in source.design_sources
            ),
            "DESIGN_SOURCE_PROJECT_MISMATCH",
            "设计来源跨项目",
        ),
        (
            len(identities) == len(set(identities))
            and source.api_source in _expected_sources(source),
            "DESIGN_SOURCE_SET_INVALID",
            "组合设计来源重复或主入口缺失",
        ),
        (
            source.combined_design_fingerprint == source.design_fingerprint,
            "COMBINED_DESIGN_FINGERPRINT_MISMATCH",
            "组合设计指纹与编译输入不一致",
        ),
    )
    return tuple(findings) + _failed_checks(checks)


def _suite_findings(
    expected: ScenarioExpectation, source: GenerationProvenance
) -> tuple[Finding, ...]:
    suite, run = source.suite, source.run
    if suite is None:
        return (
            ()
            if (
                run.source_suite is None
                and not expected.require_suite_provenance
                and expected.expected_suite is None
                and expected.expected_target_snapshot_digest is None
            )
            else (_missing("SUITE_EVIDENCE_MISSING", "缺少套件发布证据"),)
        )
    checks = (
        (
            suite.project_id == source.case.project_id
            and run.source_suite is not None
            and (run.source_suite.id, run.source_suite.version) == (suite.id, suite.version),
            "PLAN_SUITE_VERSION_MISMATCH",
            "计划展开没有固定本轮套件版本",
        ),
        (
            any(
                (item.case_id, item.version) == (source.case.id, source.case.version)
                for item in suite.case_versions
            )
            and len(suite.case_versions) == len({item.case_id for item in suite.case_versions}),
            "SUITE_CASE_VERSION_MISMATCH",
            "套件没有唯一引用本轮 Case 版本",
        ),
        (
            run.expected_target_snapshot_digest is not None
            and run.target_snapshot_digest == run.expected_target_snapshot_digest,
            "PLAN_TARGET_SNAPSHOT_MISMATCH",
            "计划展开摘要与运行前固定的发布定义不一致",
        ),
        (
            expected.expected_suite is None or suite == expected.expected_suite,
            "FROZEN_SUITE_MISMATCH",
            "套件来源被替换或内容与运行前固定版本不同",
        ),
        (
            expected.expected_target_snapshot_digest is None
            or run.target_snapshot_digest == expected.expected_target_snapshot_digest,
            "FROZEN_TARGET_SNAPSHOT_MISMATCH",
            "计划展开与独立 manifest 固定摘要不同",
        ),
    )
    return _failed_checks(checks)


def _execution_findings(
    observed: ScenarioObservation, source: GenerationProvenance
) -> tuple[Finding, ...]:
    execution = observed.execution
    if execution is None:
        return (_missing("EXECUTION_MISSING", "没有正式执行"),)
    checks = (
        (
            set(execution.api_sources) == _expected_sources(source)
            and set(source.workflow.api_sources) == set(execution.api_sources),
            "EXECUTION_API_SOURCE_MISMATCH",
            "实际执行 API 版本及契约与发布内容不一致",
        ),
        (
            source.run.execution_id == execution.id
            and source.run.workflow_id == execution.workflow_id
            and source.workflow.version_id == execution.workflow_version_id
            and source.run.environment_id == execution.environment_id,
            "EXECUTION_SOURCE_MISMATCH",
            "实际执行没有关联本轮计划项及发布版本",
        ),
        (
            source.workflow.fingerprint == execution.workflow_fingerprint,
            "EXECUTION_FINGERPRINT_MISMATCH",
            "执行快照流程指纹与发布内容不一致",
        ),
        (
            source.run.status == execution.status and source.run.attempts == len(observed.attempts),
            "EXECUTION_ATTEMPT_MISMATCH",
            "计划项状态或尝试数与执行证据不一致",
        ),
        (
            _aware(source.frozen_at)
            and _aware(execution.started_at)
            and source.frozen_at <= execution.started_at,
            "GENERATION_MAPPING_NOT_FROZEN",
            "节点及来源映射未在执行前冻结",
        ),
    )
    return _failed_checks(checks)


def _oracle_findings(
    expected: ScenarioExpectation, observed: ScenarioObservation, source: GenerationProvenance
) -> tuple[Finding, ...]:
    oracle_ids = [item.oracle_id for item in source.oracle_bindings]
    if len(oracle_ids) != len(set(oracle_ids)) or set(oracle_ids) != set(
        expected.required_oracle_ids
    ):
        return (_mismatch("ORACLE_SET_MISMATCH", "必需 Oracle 映射缺失、重复或被替换"),)
    if expected.expected_oracle_bindings and set(source.oracle_bindings) != set(
        expected.expected_oracle_bindings
    ):
        return (_mismatch("FROZEN_ORACLE_MAPPING_MISMATCH", "Oracle 节点映射与运行前固定内容不同"),)
    published = {item.oracle_id: item for item in source.workflow.assertions}
    findings: list[Finding] = []
    execution = observed.execution
    nodes = {} if execution is None else {item.node_id: item for item in execution.nodes}
    for binding in source.oracle_bindings:
        if published.get(binding.oracle_id) != binding:
            findings.append(_mismatch("PUBLISHED_ORACLE_MISMATCH", "发布流程的断言与编译映射不符"))
        node = nodes.get(binding.node_id)
        if (
            node is None
            or node.phase != binding.phase
            or node.status not in {"passed", "failed"}
            or node.attempts < 1
        ):
            findings.append(_missing("ORACLE_NODE_MISSING", "必需断言没有实际节点记录"))
            continue
        assertions = [item for item in node.assertions if item.name == binding.assertion_name]
        if len(assertions) != 1:
            findings.append(_missing("ORACLE_ASSERTION_MISSING", "必需 Oracle 没有唯一实际断言"))
        elif (
            assertions[0].expected_digest
            if isinstance(assertions[0], DigestAssertionEvidence)
            else canonical_digest(assertions[0].expected)
        ) != binding.expected_value_digest:
            findings.append(_mismatch("ORACLE_EXPECTED_VALUE_MISMATCH", "实际断言改变了冻结预期"))
    return tuple(findings)


def _call_findings(
    manifest: BatchManifest, expected: ScenarioExpectation, source: GenerationProvenance
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    if expected.expected_mcp_calls and source.calls != expected.expected_mcp_calls:
        findings.append(
            _mismatch("FROZEN_MCP_RECEIPT_SET_MISMATCH", "实际工具回执与运行前完整冻结序列不一致")
        )
    call_ids = [item.call_id for item in source.calls]
    tools = {item.tool_name for item in source.calls if item.success}
    if len(call_ids) != len(set(call_ids)):
        findings.append(_mismatch("MCP_RECEIPT_DUPLICATE", "工具调用回执重复"))
    if not {"flowtest.generate_test_design", "flowtest.propose_test_design"} <= tools:
        findings.append(_missing("MCP_GENERATION_CALL_MISSING", "缺少本轮设计及 Case 提案协议回执"))
    if not tools & {
        "flowtest.propose_simple_flow",
        "flowtest.propose_flow_draft",
        "flowtest.propose_control_workflow",
    }:
        findings.append(
            _missing("MCP_FLOW_PROPOSAL_CALL_MISSING", "缺少本轮流程提案的真实协议回执")
        )
    for call in source.calls:
        if call.batch_key != manifest.batch_key or call.scenario_id != expected.scenario_id:
            findings.append(_mismatch("MCP_RECEIPT_BINDING_MISMATCH", "工具回执属于其他批次或场景"))
        if call.catalog_digest != source.catalog_digest or not call.success:
            findings.append(_mismatch("MCP_RECEIPT_RESULT_INVALID", "工具目录或业务返回不匹配"))
        if not _inside(call.completed_at, manifest.created_at, source.frozen_at):
            findings.append(_mismatch("MCP_RECEIPT_REPLAY", "工具回执不属于本次生成时间窗口"))
    if not _inside(source.generated_at, manifest.created_at, source.frozen_at):
        findings.append(_mismatch("GENERATION_REPLAY", "生成记录不属于本批次"))
    return tuple(findings)


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def _inside(value: object, start: object, end: object) -> bool:
    if (
        not isinstance(value, datetime)
        or not isinstance(start, datetime)
        or not isinstance(end, datetime)
    ):
        return False
    if not all(item.tzinfo is not None for item in (value, start, end)):
        return False
    return start <= value <= end


def _failed_checks(checks: tuple[tuple[bool, str, str], ...]) -> tuple[Finding, ...]:
    return tuple(_mismatch(code, message) for valid, code, message in checks if not valid)


def _mismatch(code: str, message: str) -> Finding:
    return Finding(code=code, status="mismatched", message=message)


def _missing(code: str, message: str) -> Finding:
    return Finding(code=code, status="incomplete", message=message)
