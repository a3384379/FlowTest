from app.domain.control_reports import project_control_report, summarize_execution_context


def test_iteration_projection_preserves_exact_records_and_compacts_context() -> None:
    output = {
        "input_count": 2,
        "completed_count": 2,
        "failed_count": 1,
        "items": [
            {"input_index": 0, "status": "passed", "test_verdict": "passed", "nodes": []},
            {"input_index": 1, "status": "failed", "test_verdict": "failed", "nodes": []},
        ],
    }
    result = {"status": "passed", "output": output, "observations": []}
    projection = project_control_report(output, result)
    assert projection is not None
    assert projection.output_summary == {
        "input_count": 2,
        "completed_count": 2,
        "failed_count": 1,
        "report_kind": "iteration",
        "record_count": 2,
        "report_paged": True,
    }
    assert projection.result_summary is not None
    assert "items" not in projection.result_summary["output"]
    assert [item.ordinal for item in projection.items] == [0, 1]
    assert projection.items[1].payload == output["items"][1]
    context = {"node_outputs": {"loop": output, "unrelated": {"value": 7}}}
    summary = summarize_execution_context(context)
    assert summary["node_outputs"]["loop"] == projection.output_summary
    assert summary["node_outputs"]["unrelated"] == {"value": 7}
    assert context["node_outputs"]["loop"] == output


def test_parallel_projection_and_invalid_records() -> None:
    output = {
        "join": "all",
        "started_count": 1,
        "branches": [
            {
                "definition_index": 0,
                "branch_id": "first",
                "status": "passed",
                "test_verdict": "passed",
                "nodes": [],
            }
        ],
    }
    projection = project_control_report(output, None)
    assert projection is not None
    assert projection.output_summary["report_kind"] == "branch"
    assert projection.items[0].ordinal == 0
    assert project_control_report({**output, "branches": [output["branches"][0]] * 2}, None) is None
    assert (
        project_control_report(
            {**output, "branches": [{**output["branches"][0], "definition_index": True}]}, None
        )
        is None
    )
