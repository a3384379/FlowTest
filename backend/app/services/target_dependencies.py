"""Bounded, read-only HTTP routing dependency analysis for one unsaved candidate."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from app.domain.api_assets import JsonValue
from app.domain.target_dependencies import (
    CandidateDependencyDiagnostic,
    CandidateDependencyItem,
    CandidateDependencyPreview,
    DependencyAPIVersion,
    DependencyPlan,
    DependencyPlanItem,
    TargetDependencyCatalog,
)
from app.domain.target_preview import (
    PreviewAPIChange,
    PreviewEnvironmentChange,
    PreviewServiceChange,
    TargetPreviewCommand,
)
from app.engine.contracts import (
    CONTROL_CONFIG_MODELS,
    ApiNodeConfig,
    NodeType,
    ReferencedControlBody,
    SubFlowNodeConfig,
    WorkflowDefinition,
    WorkflowNode,
    control_bodies,
    parse_control_config,
    parse_node_config,
)
from app.schemas.test_assets import StoredPublishedTestCaseDefinition

type WorkflowRef = tuple[UUID, int | None]


@dataclass(frozen=True, slots=True)
class _Scope:
    kind: Literal["service", "endpoint", "environment_default", "api_binding"]
    id: UUID
    service_id: UUID | None = None
    environment_id: UUID | None = None
    variants: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _RunTarget:
    workflow_id: UUID
    workflow_version: int
    environment_id: UUID


class CandidateDependencyAnalyzer:
    def __init__(
        self,
        catalog: TargetDependencyCatalog,
        *,
        max_nodes: int = 10000,
        max_comparisons: int = 100000,
    ) -> None:
        self._catalog = catalog
        self._max_nodes = max_nodes
        self._max_comparisons = max_comparisons

    def analyze(self, command: TargetPreviewCommand) -> CandidateDependencyPreview:
        return _CandidateScan(
            self._catalog, command, self._max_nodes, self._max_comparisons
        ).result()


class _CandidateScan:
    def __init__(
        self,
        catalog: TargetDependencyCatalog,
        command: TargetPreviewCommand,
        max_nodes: int,
        max_comparisons: int,
    ) -> None:
        self.catalog = catalog
        self.apis = {item.id: item for item in catalog.apis}
        self.api_versions = {(item.api_id, item.version): item for item in catalog.api_versions}
        self.environments = {item.id: item for item in catalog.environments}
        self.service_ids = {item.key: item.id for item in catalog.services}
        self.workflows = {item.id: item for item in catalog.workflows}
        self.definitions: dict[WorkflowRef, dict[str, JsonValue]] = {
            (item.workflow_id, item.version): item.definition for item in catalog.workflow_versions
        }
        self.definitions.update({(item.id, None): item.draft for item in catalog.workflows})
        self.cases = {
            (item.case_id, item.version): item.definition for item in catalog.case_versions
        }
        self.suites = {(item.suite_id, item.version): item.cases for item in catalog.suite_versions}
        self.parsed: dict[WorkflowRef, WorkflowDefinition | None] = {}
        self.matches: dict[tuple[WorkflowRef, UUID | None], bool] = {}
        self.diagnostics: dict[
            tuple[str, UUID | None, str | None], CandidateDependencyDiagnostic
        ] = {}
        self.remaining_nodes = max_nodes
        self.remaining_comparisons = max_comparisons
        self.scope = self._scope(command)
        for label in catalog.truncated:
            self.diagnostic("CATALOG_LIMIT", f"{label}超过本次读取边界, 不能认定为完整影响范围")

    def _scope(self, command: TargetPreviewCommand) -> _Scope:
        change = command.change
        if isinstance(change, PreviewAPIChange):
            return _Scope("api_binding", change.api_id)
        if isinstance(change, PreviewEnvironmentChange):
            return _Scope(
                "environment_default", change.environment_id, environment_id=change.environment_id
            )
        if isinstance(change, PreviewServiceChange):
            return _Scope("service", change.service_id, service_id=change.service_id)
        endpoint = next(
            (item for item in self.catalog.endpoints if item.id == change.endpoint_id), None
        )
        if endpoint is None:
            self.diagnostic(
                "CANDIDATE_SOURCE_UNAVAILABLE", "候选地址元数据未完整读入", change.endpoint_id
            )
            return _Scope("endpoint", change.endpoint_id)
        return _Scope(
            "endpoint",
            endpoint.id,
            endpoint.service_id,
            endpoint.environment_id,
            frozenset({endpoint.variant, change.variant or endpoint.variant}),
        )

    def result(self) -> CandidateDependencyPreview:
        apis = self._affected_apis()
        workflows = self._affected_workflows()
        plans = [plan for plan in self.catalog.plans if self._plan_matches(plan)]
        plan_items = tuple(
            CandidateDependencyItem(plan.id, plan.name, "固定计划成员的流程版本与环境引用候选配置")
            for plan in plans
        )
        scheduled = tuple(
            CandidateDependencyItem(
                plan.id,
                plan.name,
                "计划已配置定时触发" + ("" if plan.enabled else "(当前已禁用)"),
            )
            for plan in plans
            if plan.scheduled
        )
        policies = (
            tuple(
                CandidateDependencyItem(
                    policy.id,
                    policy.name,
                    "可以选择受影响计划的新运行作为证据; 尚未计算具体发布判断",
                )
                for policy in self.catalog.release_policies
            )
            if plans
            else ()
        )
        return CandidateDependencyPreview(
            scope_kind=self.scope.kind,
            scope_id=self.scope.id,
            complete=not self.diagnostics,
            diagnostics=tuple(self.diagnostics.values()),
            affected_apis=apis,
            affected_workflows=workflows,
            affected_test_plans=plan_items,
            affected_scheduled_runs=scheduled,
            affected_release_gates=policies,
        )

    def _affected_apis(self) -> tuple[CandidateDependencyItem, ...]:
        identifiers = {
            item.api_id for item in self.catalog.api_versions if self._api_version_matches(item)
        }
        if self.scope.kind == "api_binding":
            identifiers = {self.scope.id}
        items: list[CandidateDependencyItem] = []
        for identifier in sorted(identifiers):
            api = self.apis.get(identifier)
            if api is None:
                self.diagnostic("API_SOURCE_UNAVAILABLE", "引用的接口元数据未完整读入", identifier)
                continue
            items.append(
                CandidateDependencyItem(api.id, api.name, _api_reason(self.scope.kind), api.active)
            )
        return tuple(items)

    def _api_version_matches(self, version: DependencyAPIVersion) -> bool:
        if self.scope.kind == "endpoint" and self.scope.service_id is None:
            return False
        if self.scope.kind == "api_binding":
            return version.api_id == self.scope.id
        if self.scope.kind == "environment_default":
            return version.service_id is None
        if version.service_id == self.scope.service_id and version.service_id is not None:
            return True
        if version.service_id is not None:
            return False
        return self._inherited_service_matches(self.scope.environment_id)

    def _affected_workflows(self) -> tuple[CandidateDependencyItem, ...]:
        references: dict[UUID, list[str]] = {}
        for reference in self.definitions:
            if self._workflow_matches(reference, None, ()):
                label = "草稿" if reference[1] is None else f"已发布 v{reference[1]}"
                references.setdefault(reference[0], []).append(label)
        items: list[CandidateDependencyItem] = []
        for identifier, versions in references.items():
            workflow = self.workflows.get(identifier)
            if workflow is None:
                self.diagnostic("WORKFLOW_SOURCE_UNAVAILABLE", "流程元数据未完整读入", identifier)
                continue
            items.append(
                CandidateDependencyItem(
                    identifier,
                    workflow.name,
                    f"{'、'.join(versions)}中的HTTP节点直接或通过固定子流程引用候选配置",
                    not workflow.archived,
                )
            )
        return tuple(sorted(items, key=lambda item: (item.name, item.id)))

    def _workflow_matches(
        self, reference: WorkflowRef, environment_id: UUID | None, stack: tuple[WorkflowRef, ...]
    ) -> bool:
        key = (reference, environment_id)
        if key in self.matches:
            return self.matches[key]
        if len(stack) >= 32:
            self.diagnostic(
                "WORKFLOW_REFERENCE_DEPTH",
                "固定子流程引用超过分析深度, 已识别结果不完整",
                reference[0],
            )
            return False
        if reference in stack:
            self.diagnostic(
                "WORKFLOW_REFERENCE_CYCLE", "固定子流程引用存在循环, 已识别结果不完整", reference[0]
            )
            return False
        definition = self._definition(reference)
        if definition is None:
            return False
        matched = False
        for node in definition.all_nodes():
            if not self._comparison_available(reference[0], node.id):
                break
            matched = self._node_matches(node, environment_id, (*stack, reference)) or matched
        self.matches[key] = matched
        return matched

    def _definition(self, reference: WorkflowRef) -> WorkflowDefinition | None:
        if reference in self.parsed:
            return self.parsed[reference]
        raw = self.definitions.get(reference)
        if raw is None:
            self.diagnostic(
                "WORKFLOW_REFERENCE_UNAVAILABLE",
                "引用的流程版本不存在、越界或未完整读入",
                reference[0],
            )
            return None
        count = _node_count(raw)
        if count > self.remaining_nodes:
            self.diagnostic(
                "NODE_SCAN_LIMIT", "流程节点超过本次分析边界, 已识别结果不完整", reference[0]
            )
            self.parsed[reference] = None
            return None
        self.remaining_nodes -= count
        try:
            definition = WorkflowDefinition.model_validate(raw)
        except ValidationError:
            self.diagnostic(
                "WORKFLOW_DEFINITION_INVALID", "流程定义无法按当前合同解析", reference[0]
            )
            self.parsed[reference] = None
            return None
        self.parsed[reference] = definition
        return definition

    def _comparison_available(self, workflow_id: UUID, node_id: str) -> bool:
        if self.remaining_comparisons <= 0:
            self.diagnostic(
                "REFERENCE_SCAN_LIMIT",
                "引用比较超过本次分析边界, 已识别结果不完整",
                workflow_id,
                node_id,
            )
            return False
        self.remaining_comparisons -= 1
        return True

    def _node_matches(
        self, node: WorkflowNode, environment_id: UUID | None, stack: tuple[WorkflowRef, ...]
    ) -> bool:
        try:
            if node.effective_type is NodeType.API:
                return self._api_node_matches(
                    ApiNodeConfig.model_validate(node.effective_config), environment_id
                )
            references = _child_references(node)
        except (ValidationError, ValueError):
            self.diagnostic(
                "NODE_DEPENDENCY_INVALID", "节点引用无法按当前合同解析", stack[-1][0], node.id
            )
            return False
        matched = False
        for reference in references:
            matched = self._workflow_matches(reference, environment_id, stack) or matched
        return matched

    def _api_node_matches(self, config: ApiNodeConfig, environment_id: UUID | None) -> bool:
        if self.scope.kind == "endpoint" and self.scope.service_id is None:
            return False
        if self.scope.kind == "api_binding":
            return config.api_definition_id == self.scope.id and config.api_version is None
        version = self._api_version(config)
        if version is None:
            return False
        if self.scope.kind == "environment_default":
            return (
                not config.service_override
                and version.service_id is None
                and self._environment_matches(environment_id)
            )
        if self.scope.kind == "endpoint" and not self._endpoint_context_matches(
            config, environment_id
        ):
            return False
        if config.service_override:
            return self.service_ids.get(config.service_override) == self.scope.service_id
        if version.service_id is not None:
            return version.service_id == self.scope.service_id
        return self._inherited_service_matches(environment_id or self.scope.environment_id)

    def _api_version(self, config: ApiNodeConfig) -> DependencyAPIVersion | None:
        api = self.apis.get(config.api_definition_id)
        version_number = (
            config.api_version
            if config.api_version is not None
            else (api.current_version if api is not None else None)
        )
        version = (
            self.api_versions.get((config.api_definition_id, version_number))
            if version_number is not None
            else None
        )
        if version is None:
            self.diagnostic(
                "API_VERSION_UNAVAILABLE",
                "节点引用的接口版本不存在、越界或未完整读入",
                config.api_definition_id,
            )
        return version

    def _environment_matches(self, environment_id: UUID | None) -> bool:
        return environment_id is None or environment_id == self.scope.environment_id

    def _endpoint_context_matches(self, config: ApiNodeConfig, environment_id: UUID | None) -> bool:
        return (
            self._environment_matches(environment_id)
            and (config.endpoint_variant or "default") in self.scope.variants
        )

    def _inherited_service_matches(self, environment_id: UUID | None) -> bool:
        if environment_id is None:
            return any(
                item.default_service_id == self.scope.service_id
                for item in self.catalog.environments
            )
        environment = self.environments.get(environment_id)
        if environment is None:
            self.diagnostic(
                "ENVIRONMENT_REFERENCE_UNAVAILABLE",
                "来源环境不存在、越界或未完整读入",
                environment_id,
            )
            return False
        return environment.default_service_id == self.scope.service_id

    def _plan_matches(self, plan: DependencyPlan) -> bool:
        matched = False
        for item in plan.items:
            for target in self._run_targets(item):
                if target.environment_id not in self.environments:
                    self.diagnostic(
                        "PLAN_ENVIRONMENT_UNAVAILABLE",
                        "计划成员的固定环境未完整读入",
                        target.environment_id,
                    )
                    continue
                matched = (
                    self._workflow_matches(
                        (target.workflow_id, target.workflow_version), target.environment_id, ()
                    )
                    or matched
                )
        return matched

    def _run_targets(self, item: DependencyPlanItem) -> tuple[_RunTarget, ...]:
        if item.kind == "workflow":
            if (
                item.workflow_id is None
                or item.workflow_version is None
                or item.environment_id is None
            ):
                self.diagnostic(
                    "PLAN_MEMBER_INVALID", "计划流程成员缺少固定版本或环境", item.target_id
                )
                return ()
            return (_RunTarget(item.workflow_id, item.workflow_version, item.environment_id),)
        if item.kind == "case":
            target = self._case_target(item.target_id, item.target_version)
            return (target,) if target is not None else ()
        members = self.suites.get((item.target_id, item.target_version))
        if members is None:
            self.diagnostic(
                "SUITE_VERSION_UNAVAILABLE", "计划引用的套件版本未完整读入", item.target_id
            )
            return ()
        return tuple(
            target
            for member in members
            if (target := self._case_target(member.case_id, member.version)) is not None
        )

    def _case_target(self, case_id: UUID, version: int) -> _RunTarget | None:
        raw = self.cases.get((case_id, version))
        if raw is None:
            self.diagnostic("CASE_VERSION_UNAVAILABLE", "计划引用的用例版本未完整读入", case_id)
            return None
        try:
            definition = StoredPublishedTestCaseDefinition.model_validate(raw)
        except ValidationError:
            self.diagnostic("CASE_DEFINITION_INVALID", "固定用例定义无法按当前合同解析", case_id)
            return None
        return _RunTarget(
            definition.workflow_id, definition.workflow_version, definition.environment_id
        )

    def diagnostic(
        self, code: str, message: str, resource_id: UUID | None = None, node_id: str | None = None
    ) -> None:
        if len(self.diagnostics) < 100:
            self.diagnostics.setdefault(
                (code, resource_id, node_id),
                CandidateDependencyDiagnostic(code, message, resource_id, node_id),
            )


def _node_count(raw: dict[str, JsonValue]) -> int:
    main = raw.get("nodes")
    count = len(main) if isinstance(main, list) else 0
    regions = raw.get("regions")
    if not isinstance(regions, list):
        return count
    for region in regions:
        if not isinstance(region, dict):
            continue
        nodes = region.get("nodes")
        if isinstance(nodes, list):
            count += len(nodes)
    return count


def _child_references(node: WorkflowNode) -> tuple[WorkflowRef, ...]:
    if node.effective_type in {NodeType.SUBFLOW, NodeType.FOR_EACH}:
        config = parse_node_config(node)
        if isinstance(config, SubFlowNodeConfig):
            return ((config.workflow_id, config.workflow_version),)
    if node.type is NodeType.CAPABILITY and node.capability_id in CONTROL_CONFIG_MODELS:
        return tuple(
            (body.workflow_id, body.workflow_version)
            for _role, body in control_bodies(parse_control_config(node))
            if isinstance(body, ReferencedControlBody)
        )
    return ()


def _api_reason(kind: str) -> str:
    if kind == "api_binding":
        return "候选将新增接口版本; 跟随当前版本的节点受影响, 固定旧API版本保持原绑定"
    if kind == "environment_default":
        return "存在未绑定服务的接口版本, 在候选环境执行时继承环境默认服务"
    return "接口版本绑定候选服务或在相关环境继承该服务; 地址变体在请求时选择"
