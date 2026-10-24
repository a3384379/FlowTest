"""Independent bounded engine facts, without candidate runtime verdict helpers."""

from __future__ import annotations

from collections import Counter

from scripts.selftest.contracts import (
    AssertionExpectation,
    BatchEvidence,
    BatchManifest,
    ExecutionEvidence,
    ExpectedOutcome,
    Finding,
    FixtureMetrics,
    NestedNodeExpectation,
    NodeEvidence,
    ScenarioExpectation,
    ScenarioObservation,
    canonical_digest,
)


def _finding(code: str, incomplete: bool = False) -> Finding:
    return Finding(
        code=code,
        status="incomplete" if incomplete else "mismatched",
        message="附加引擎独立证据不完整或与运行前冻结事实不符",
    )


def _node_set(
    values: tuple[NodeEvidence, ...], expected: tuple[NestedNodeExpectation, ...]
) -> bool:
    fields = {"node_id", "phase", "status", "error_code", "attempts"}
    actual = [canonical_digest(node.model_dump(mode="json", include=fields)) for node in values]
    golden = [canonical_digest(node.model_dump(mode="json")) for node in expected]
    return sorted(actual) == sorted(golden)


def _metric_shape(metrics: FixtureMetrics, total: int, start: float, end: float) -> bool:
    events = metrics.events
    if (
        not metrics.complete
        or len(events) != total
        or len({event.request_id for event in events}) != total
    ):
        return False
    if sorted(event.sequence for event in events) != list(range(1, total + 1)):
        return False
    return all(
        event.completed_at is not None
        and start <= event.started_at <= event.completed_at <= end
        and event.outcome is not None
        for event in events
    )


def _computed_metrics(metrics: FixtureMetrics) -> tuple[int, int, Counter[str]]:
    timeline = []
    outcomes: Counter[str] = Counter()
    for event in metrics.events:
        timeline.append((event.started_at, 1, event.sequence, event.active_at_begin))
        if event.completed_at is not None:
            timeline.append((event.completed_at, -1, event.sequence, 0))
        outcomes[event.outcome or "unfinished"] += 1
    active = peak = 0
    for _, delta, _sequence, at_begin in sorted(timeline):
        active += delta
        if delta == 1 and at_begin != active:
            return -1, active, outcomes
        peak = max(peak, active)
    return peak, active, outcomes


def _metrics(
    manifest: BatchManifest, golden: ExpectedOutcome, actual: ScenarioObservation
) -> tuple[Finding, ...]:
    expected = golden.fixture_metrics
    if expected is None:
        return ()
    journal = actual.journal
    if journal is None or journal.metrics is None:
        return (_finding("FIXTURE_METRICS_MISSING", True),)
    metrics = journal.metrics
    if not _metric_shape(
        metrics,
        journal.request_count,
        manifest.created_at.timestamp(),
        manifest.expires_at.timestamp(),
    ):
        return (_finding("FIXTURE_METRICS_INCOMPLETE", True),)
    peak, active, outcomes = _computed_metrics(metrics)
    wanted = expected.model_dump()
    observed = {name: getattr(metrics, name) for name in wanted}
    counts = (
        peak,
        active,
        outcomes["completed"],
        outcomes["cancelled"],
        outcomes["failed"],
    )
    stored = (
        metrics.peak_concurrency,
        metrics.active_count,
        metrics.completed_count,
        metrics.cancelled_count,
        metrics.failed_count,
    )
    if observed != wanted or counts != stored:
        return (_finding("FIXTURE_CONCURRENCY_MISMATCH"),)
    return ()


def _dataset(
    manifest: BatchManifest, expected: ScenarioExpectation, actual: ScenarioObservation
) -> tuple[Finding, ...]:
    golden = expected.expected.dataset
    if golden is None:
        return ()
    execution = actual.execution
    if (
        execution is None
        or execution.dataset is None
        or not execution.children_complete
        or not actual.children_complete
    ):
        return (_finding("DATASET_CHILDREN_INCOMPLETE", True),)
    binding = golden.model_dump(mode="json", include={"artifact_id", "sha256", "row_count"})
    if execution.dataset.model_dump(mode="json") != binding:
        return (_finding("DATASET_BINDING_MISMATCH"),)
    children = actual.children
    if len(children) < golden.row_count or len(execution.children) < golden.row_count:
        return (_finding("DATASET_CHILDREN_INCOMPLETE", True),)
    refs = {(item.execution_id, item.row_index, item.status) for item in execution.children}
    observed = {(item.id, item.dataset_row_index, item.status) for item in children}
    if (
        len(children) != golden.row_count
        or len(refs) != golden.row_count
        or len({item.id for item in children}) != golden.row_count
        or len({item.execution_id for item in execution.children}) != golden.row_count
        or refs != observed
        or {item.dataset_row_index for item in children} != set(golden.row_indices)
    ):
        return (_finding("DATASET_CHILD_SET_MISMATCH"),)
    for child in children:
        if not _child_matches(manifest, expected, actual, child):
            return (_finding("DATASET_CHILD_BINDING_MISMATCH"),)
        if not _node_set(child.nodes, golden.nodes):
            return (_finding("DATASET_CHILD_NODE_MISMATCH"),)
        if not _child_assertions(child, golden.assertions):
            return (_finding("DATASET_CHILD_ASSERTION_MISMATCH"),)
    return ()


def _child_matches(
    manifest: BatchManifest,
    expected: ScenarioExpectation,
    actual: ScenarioObservation,
    child: ExecutionEvidence,
) -> bool:
    parent = actual.execution
    if parent is None:
        return False
    return (
        child.parent_execution_id == parent.id
        and child.project_id == manifest.project_id
        and child.workflow_id == parent.workflow_id
        and child.workflow_version_id == parent.workflow_version_id
        and child.environment_id == parent.environment_id
        and child.status == "passed"
        and child.error_code is None
        and child.completed_at is not None
        and manifest.created_at <= child.started_at <= child.completed_at <= manifest.expires_at
        and child.dataset == parent.dataset
        and set(child.api_sources) == set(expected.expected_api_sources)
    )


def _child_assertions(child: ExecutionEvidence, goldens: tuple[AssertionExpectation, ...]) -> bool:
    from scripts.selftest.verify import _assertion_matches

    nodes = {item.node_id: item for item in child.nodes}
    for golden in goldens:
        node = nodes.get(golden.node_id)
        values = (
            ()
            if node is None
            else tuple(item for item in node.assertions if item.name == golden.name)
        )
        if (
            node is None
            or node.phase != golden.phase
            or node.status != "passed"
            or node.attempts < 1
            or len(values) != 1
            or not _assertion_matches(golden, values[0])
        ):
            return False
    return True


def _disposal(
    manifest: BatchManifest, expected: ExpectedOutcome, actual: ScenarioObservation
) -> tuple[Finding, ...]:
    golden = expected.required_disposal
    if golden is None:
        return (
            (_finding("OWNED_ASSET_DISPOSAL_REQUIREMENT_MISSING", True),)
            if expected.dataset is not None
            else ()
        )
    receipt = actual.target_disposal
    if receipt is None:
        return (_finding("OWNED_ASSET_DISPOSAL_PENDING", True),)
    names = {
        "project_name",
        "target_container_id",
        "target_volume",
        "target_image",
        "binding_nonce",
    }
    if (
        receipt.model_dump(include=names) != golden.model_dump()
        or golden.target_image != manifest.builds.target
        or not all((receipt.containers_absent, receipt.volumes_absent, receipt.networks_absent))
        or actual.execution is None
        or actual.execution.completed_at is None
        or receipt.removed_at.tzinfo is None
        or not actual.execution.completed_at <= receipt.removed_at <= manifest.expires_at
    ):
        return (_finding("OWNED_ASSET_DISPOSAL_MISMATCH"),)
    return ()


def _budget(manifest: BatchManifest, actual: ScenarioObservation) -> tuple[Finding, ...]:
    journal = actual.journal
    if journal is None:
        return ()
    budget = journal.budget
    if budget is None:
        return (
            ()
            if manifest.fixture_budget is None
            else (_finding("FIXTURE_BUDGET_RECEIPT_MISSING", True),)
        )
    if manifest.fixture_budget is not None and (
        journal.metrics is None or not journal.metrics.complete or journal.metrics.active_count != 0
    ):
        return (_finding("FIXTURE_BUDGET_REQUESTS_UNSETTLED", True),)
    scope = manifest.fixture_budget
    names = {"parent_batch_key", "nonce", "limit", "expires_at"}
    if (
        (scope is not None and budget.model_dump(include=names) != scope.model_dump())
        or budget.fixture_digest != journal.fixture_digest
        or budget.registration_epoch != journal.fixture_epoch
    ):
        return (_finding("FIXTURE_BUDGET_BINDING_MISMATCH"),)
    if (
        budget.expires_at <= manifest.created_at.timestamp()
        or (
            actual.execution is not None
            and actual.execution.completed_at is not None
            and budget.expires_at < actual.execution.completed_at.timestamp()
        )
        or budget.admitted_count < journal.request_count
        or budget.admitted_count > budget.limit
        or budget.rejected_count
    ):
        return (_finding("FIXTURE_BUDGET_EXCEEDED_OR_INCOMPLETE"),)
    return ()


def engine_findings(
    manifest: BatchManifest, expected: ScenarioExpectation, actual: ScenarioObservation
) -> tuple[Finding, ...]:
    execution = actual.execution
    if execution is None:
        return ()
    findings = []
    if expected.expected.top_nodes and not _node_set(execution.nodes, expected.expected.top_nodes):
        findings.append(_finding("TOP_NODE_SET_MISMATCH"))
    if expected.expected_api_sources and set(execution.api_sources) != set(
        expected.expected_api_sources
    ):
        findings.append(_finding("FROZEN_API_SET_MISMATCH"))
    if expected.expected.subflows and (
        not execution.subflows_complete or execution.subflows != expected.expected.subflows
    ):
        findings.append(_finding("SUBFLOW_BINDING_MISMATCH"))
    return (
        *findings,
        *_budget(manifest, actual),
        *_metrics(manifest, expected.expected, actual),
        *_dataset(manifest, expected, actual),
        *_disposal(manifest, expected.expected, actual),
    )


def batch_budget_findings(manifest: BatchManifest, evidence: BatchEvidence) -> tuple[Finding, ...]:
    """A final shared counter must account for every observed namespace exactly once."""
    if manifest.fixture_budget is None:
        return ()
    journals = [item.journal for item in evidence.scenarios if item.journal is not None]
    if not journals:
        return ()
    if any(item.budget is None for item in journals):
        return (_finding("FIXTURE_BUDGET_RECEIPT_MISSING", True),)
    receipts = [item.budget for item in journals if item.budget is not None]
    total = sum(item.request_count for item in journals)
    if max(item.admitted_count for item in receipts) != total:
        return (_finding("FIXTURE_BATCH_COUNTER_MISMATCH"),)
    return ()
