"""Persistable projections of structured-control run reports."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ControlReportItem:
    kind: str
    ordinal: int
    status: str
    test_verdict: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ControlReportProjection:
    output_summary: dict[str, Any]
    result_summary: dict[str, Any] | None
    items: tuple[ControlReportItem, ...]


def project_control_report(
    output: Any, result: dict[str, Any] | None
) -> ControlReportProjection | None:
    if not isinstance(output, dict):
        return None
    kind, field, ordinal_field = _report_shape(output)
    if kind is None:
        return None
    raw_items = output[field]
    items: list[ControlReportItem] = []
    seen: set[int] = set()
    for raw in raw_items:
        if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
            return None
        ordinal = raw.get(ordinal_field)
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            return None
        if ordinal in seen:
            return None
        seen.add(ordinal)
        status = raw.get("status")
        verdict = raw.get(
            "test_verdict",
            "failed" if status == "failed" else "passed" if status == "passed" else "not_run",
        )
        if not isinstance(status, str) or not isinstance(verdict, str):
            return None
        items.append(ControlReportItem(kind, ordinal, status, verdict, raw))
    summary = {key: value for key, value in output.items() if key != field}
    summary.update({"report_kind": kind, "record_count": len(items), "report_paged": True})
    result_summary = result
    if isinstance(result, dict) and isinstance(result.get("output"), dict):
        result_summary = {**result, "output": summary}
    return ControlReportProjection(summary, result_summary, tuple(items))


def summarize_execution_context(context: dict[str, Any]) -> dict[str, Any]:
    outputs = context.get("node_outputs")
    if not isinstance(outputs, dict):
        return context
    summarized = {
        node_id: projection.output_summary
        if (projection := project_control_report(output, None))
        else output
        for node_id, output in outputs.items()
    }
    return {**context, "node_outputs": summarized}


def _report_shape(output: dict[str, Any]) -> tuple[str | None, str, str]:
    if isinstance(output.get("items"), list) and "completed_count" in output:
        return "iteration", "items", "input_index"
    if isinstance(output.get("branches"), list) and output.get("join") == "all":
        return "branch", "branches", "definition_index"
    return None, "", ""
