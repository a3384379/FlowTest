from dataclasses import replace
from uuid import uuid4

import pytest

from app.domain.api_assets import JsonValue
from app.domain.target_dependencies import (
    DependencyAPI,
    DependencyAPIVersion,
    DependencyCaseVersion,
    DependencyEndpoint,
    DependencyEnvironment,
    DependencyPlan,
    DependencyPlanItem,
    DependencyReleasePolicy,
    DependencyService,
    DependencyWorkflow,
    DependencyWorkflowVersion,
    TargetDependencyCatalog,
)
from app.domain.target_preview import (
    PreviewAPIChange,
    PreviewEndpointChange,
    PreviewEnvironmentChange,
    PreviewServiceChange,
    TargetPreviewCommand,
)
from app.services.target_dependencies import CandidateDependencyAnalyzer


def graph(node: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "schema_version": "4.0",
        "run_policy": {"request_budget": 10, "max_runtime_seconds": 60},
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {"id": "request", "name": "节点", "position": {"x": 1, "y": 0}, **node},
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 2, "y": 0}},
        ],
        "edges": [
            {"id": "one", "source": "start", "target": "request"},
            {"id": "two", "source": "request", "target": "end"},
        ],
    }


def catalog() -> TargetDependencyCatalog:
    api, service, environment, endpoint = uuid4(), uuid4(), uuid4(), uuid4()
    return TargetDependencyCatalog(
        apis=(DependencyAPI(api, "接口", 1, True),),
        api_versions=(DependencyAPIVersion(api, 1, None),),
        environments=(DependencyEnvironment(environment, service),),
        services=(DependencyService(service, "orders"),),
        endpoints=(DependencyEndpoint(endpoint, environment, service, "default"),),
        workflows=(),
        workflow_versions=(),
        case_versions=(),
        suite_versions=(),
        plans=(),
        release_policies=(),
    )


def workflow(data: TargetDependencyCatalog, config: dict[str, JsonValue]) -> DependencyWorkflow:
    return DependencyWorkflow(
        uuid4(),
        "引用流程",
        False,
        graph({"type": "api", "config": {"api_definition_id": str(data.apis[0].id), **config}}),
    )


@pytest.mark.parametrize("kind", ["service", "endpoint", "environment_default", "api_binding"])
def test_each_candidate_matches_inherited_service_and_inline_native_http(kind: str) -> None:
    data = catalog()
    original = workflow(data, {})
    assert isinstance(original.draft["nodes"], list)
    group = {
        "id": "request",
        "name": "组",
        "position": {"x": 1, "y": 0},
        "type": "capability",
        "capability_id": "flow.control.group",
        "capability_version": "1.0.0",
        "configuration": {"body": {"kind": "inline", "region_id": "body"}},
        "bindings": [],
    }
    original.draft["nodes"][1] = group
    original.draft["regions"] = [
        {
            "id": "body",
            "owner_node_id": "request",
            "role": "body",
            "entry_node_id": "http",
            "exit_node_ids": ["http"],
            "nodes": [
                {
                    "id": "http",
                    "name": "区域请求",
                    "type": "capability",
                    "position": {"x": 0, "y": 0},
                    "capability_id": "http.request",
                    "capability_version": "2.0.0",
                    "configuration": {"api_definition_id": str(data.apis[0].id)},
                    "bindings": [],
                }
            ],
        }
    ]
    changes = {
        "service": PreviewServiceChange(data.services[0].id, False),
        "endpoint": PreviewEndpointChange(data.endpoints[0].id, variant="renamed"),
        "environment_default": PreviewEnvironmentChange(data.environments[0].id, None),
        "api_binding": PreviewAPIChange(data.apis[0].id, data.services[0].id),
    }
    result = CandidateDependencyAnalyzer(replace(data, workflows=(original,))).analyze(
        TargetPreviewCommand(changes[kind])
    )
    assert result.complete is True, result.diagnostics
    assert [item.id for item in result.affected_workflows] == [original.id]


def test_fixed_structured_child_body_retains_reference_and_archive_availability() -> None:
    data = catalog()
    child = workflow(data, {"api_version": 1})
    parent = DependencyWorkflow(
        uuid4(),
        "归档父流程",
        True,
        graph(
            {
                "type": "capability",
                "capability_id": "flow.control.group",
                "capability_version": "1.0.0",
                "configuration": {
                    "body": {
                        "kind": "workflow_ref",
                        "workflow_id": str(child.id),
                        "workflow_version": 1,
                    }
                },
                "bindings": [],
            }
        ),
    )
    data = replace(
        data,
        workflows=(child, parent),
        workflow_versions=(DependencyWorkflowVersion(child.id, 1, child.draft),),
    )
    result = CandidateDependencyAnalyzer(data).analyze(
        TargetPreviewCommand(PreviewServiceChange(data.services[0].id))
    )
    assert result.complete is True, result.diagnostics
    assert {item.id for item in result.affected_workflows} == {child.id, parent.id}
    assert (
        next(item for item in result.affected_workflows if item.id == parent.id).available is False
    )
    binding = CandidateDependencyAnalyzer(data).analyze(
        TargetPreviewCommand(PreviewAPIChange(data.apis[0].id, None))
    )
    assert binding.affected_workflows == ()  # fixed API v1 stays fixed even through a child body


@pytest.mark.parametrize(
    "failure",
    [
        "missing_child",
        "cycle",
        "invalid_definition",
        "invalid_api",
        "missing_api",
        "node_limit",
        "comparison_limit",
        "depth",
    ],
)
def test_incomplete_analysis_has_explicit_diagnostics_instead_of_asserting_zero(
    failure: str,
) -> None:
    data = catalog()
    item = workflow(data, {})
    nodes, comparisons = 10000, 100000
    versions = ()
    if failure == "missing_child":
        item = replace(
            item,
            draft=graph(
                {"type": "subflow", "config": {"workflow_id": str(uuid4()), "workflow_version": 1}}
            ),
        )
    elif failure == "cycle":
        item = replace(
            item,
            draft=graph(
                {"type": "subflow", "config": {"workflow_id": str(item.id), "workflow_version": 1}}
            ),
        )
        versions = (DependencyWorkflowVersion(item.id, 1, item.draft),)
    elif failure == "depth":
        identifiers = [uuid4() for _ in range(34)]
        versions = tuple(
            DependencyWorkflowVersion(
                identifier,
                1,
                graph(
                    {
                        "type": "subflow",
                        "config": {
                            "workflow_id": str(identifiers[index + 1]),
                            "workflow_version": 1,
                        },
                    }
                ),
            )
            for index, identifier in enumerate(identifiers[:-1])
        )
        item = replace(
            item,
            draft=graph(
                {
                    "type": "subflow",
                    "config": {"workflow_id": str(identifiers[0]), "workflow_version": 1},
                }
            ),
        )
    elif failure == "invalid_definition":
        item = replace(item, draft={"nodes": []})
    elif failure == "invalid_api":
        item = replace(
            item, draft=graph({"type": "api", "config": {"api_definition_id": "invalid"}})
        )
    elif failure == "missing_api":
        item = workflow(data, {"api_version": 99})
    elif failure == "node_limit":
        nodes = 0
    else:
        comparisons = 0
    data = replace(data, workflows=(item,), workflow_versions=versions)
    result = CandidateDependencyAnalyzer(
        data, max_nodes=nodes, max_comparisons=comparisons
    ).analyze(TargetPreviewCommand(PreviewServiceChange(data.services[0].id)))
    assert result.complete is False and result.diagnostics
    assert all(diagnostic.code and diagnostic.message for diagnostic in result.diagnostics)


@pytest.mark.parametrize(
    "kind", ["workflow", "case", "suite", "invalid_case", "missing_case", "missing_environment"]
)
def test_plan_source_errors_are_incomplete_and_cannot_create_release_conclusions(kind: str) -> None:
    data = catalog()
    reference = workflow(data, {})
    target_id = uuid4()
    workflow_id = reference.id if kind != "workflow" else None
    case_id = uuid4()
    cases = (DependencyCaseVersion(case_id, 1, {}),) if kind == "invalid_case" else ()
    item_kind = (
        "workflow"
        if kind in {"workflow", "missing_environment"}
        else "suite"
        if kind == "suite"
        else "case"
    )
    item = DependencyPlanItem(
        item_kind, case_id if item_kind == "case" else target_id, 1, workflow_id, 1, uuid4()
    )
    plan = DependencyPlan(uuid4(), "不完整计划", True, True, (item,))
    data = replace(
        data,
        workflows=(reference,),
        workflow_versions=(DependencyWorkflowVersion(reference.id, 1, reference.draft),),
        case_versions=cases,
        plans=(plan,),
        release_policies=(DependencyReleasePolicy(uuid4(), "策略"),),
    )
    result = CandidateDependencyAnalyzer(data).analyze(
        TargetPreviewCommand(PreviewServiceChange(data.services[0].id))
    )
    assert result.complete is False
    assert result.affected_test_plans == result.affected_release_gates == ()


def test_potential_release_policies_are_only_metadata_not_evaluated_gates() -> None:
    data = catalog()
    reference = workflow(data, {})
    plan = DependencyPlan(
        uuid4(),
        "受影响计划",
        True,
        False,
        (
            DependencyPlanItem(
                "workflow", reference.id, 1, reference.id, 1, data.environments[0].id
            ),
        ),
    )
    policy = DependencyReleasePolicy(uuid4(), "潜在策略")
    data = replace(
        data,
        workflows=(reference,),
        workflow_versions=(DependencyWorkflowVersion(reference.id, 1, reference.draft),),
        plans=(plan,),
        release_policies=(policy,),
    )
    result = CandidateDependencyAnalyzer(data).analyze(
        TargetPreviewCommand(PreviewServiceChange(data.services[0].id))
    )
    assert result.complete
    assert result.affected_release_gates[0].id == policy.id
    assert "尚未计算具体发布判断" in result.affected_release_gates[0].reason
    assert result.affected_scheduled_runs == ()


def test_missing_candidate_and_catalog_boundaries_never_return_complete_zero() -> None:
    data = replace(catalog(), truncated=("流程目录",))
    result = CandidateDependencyAnalyzer(data).analyze(
        TargetPreviewCommand(PreviewEndpointChange(uuid4()))
    )
    assert not result.complete
    assert {item.code for item in result.diagnostics} == {
        "CATALOG_LIMIT",
        "CANDIDATE_SOURCE_UNAVAILABLE",
    }
