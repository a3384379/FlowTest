import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import JsonValue

from app.domain.mock_preview_limits import (
    MockJsonBudget,
    MockPreviewError,
    MockPreviewLimits,
    json_pointer,
)
from app.domain.mock_services import (
    MockRequestContext,
    MockTemplateError,
    compile_mock_path,
    match_mock_conditions,
    mock_template_references,
    render_mock_template,
)


@dataclass(frozen=True, slots=True)
class MockPreviewRule:
    route_id: UUID | None
    name: str
    method: str
    path_pattern: str
    query_conditions: Mapping[str, str]
    header_conditions: Mapping[str, str]
    response_status: int
    response_headers: Mapping[str, str]
    response_body: JsonValue
    scenario: str | None
    priority: int
    delay_ms: int
    is_enabled: bool
    is_draft: bool = False
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MockPreviewRequest:
    method: str
    path: str
    query: Mapping[str, str]
    headers: Mapping[str, str]
    body: JsonValue
    scenario: str | None


@dataclass(frozen=True, slots=True)
class MockPreviewCheck:
    field: str
    matched: bool
    message: str


@dataclass(frozen=True, slots=True)
class MockPreviewWarning:
    field: str
    pointer: str
    message: str
    route_id: UUID | None


@dataclass(frozen=True, slots=True)
class MockPreviewSelected:
    route_id: UUID | None
    name: str
    is_draft: bool
    priority: int
    scenario: str | None
    delay_ms: int


@dataclass(frozen=True, slots=True)
class MockPreviewResponseValue:
    status_code: int
    headers: Mapping[str, str]
    body: JsonValue


@dataclass(frozen=True, slots=True)
class MockPreviewDecision:
    service_enabled: bool
    draft_matches: bool
    selected: MockPreviewRule | None
    context: MockRequestContext | None
    checks: tuple[MockPreviewCheck, ...]
    draft_warnings: tuple[MockPreviewWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class MockPreviewOutcome:
    service_enabled: bool
    draft_matches: bool
    selected: MockPreviewSelected | None
    checks: tuple[MockPreviewCheck, ...]
    warnings: tuple[MockPreviewWarning, ...]
    response: MockPreviewResponseValue | None


def match_mock_preview(
    *,
    draft: MockPreviewRule,
    candidates: Sequence[MockPreviewRule],
    request: MockPreviewRequest,
    service_enabled: bool,
    limits: MockPreviewLimits,
) -> MockPreviewDecision:
    if len(candidates) > limits.candidate_count:
        raise MockPreviewError(
            f"规则目录超过{limits.candidate_count}条预览上限, 未进行局部匹配",
            field="request",
            code="MOCK_PREVIEW_LIMIT_EXCEEDED",
        )
    _validate_inputs(draft, request, limits)
    _validate_candidates(candidates, limits)
    checks = _draft_checks(draft, request)
    selected, context = _select_rule(candidates, request) if service_enabled else (None, None)
    draft_matches = all(check.matched for check in checks)
    warnings = _validate_unselected_draft(draft, request, selected, draft_matches, limits)
    return MockPreviewDecision(service_enabled, draft_matches, selected, context, checks, warnings)


def _validate_unselected_draft(
    draft: MockPreviewRule,
    request: MockPreviewRequest,
    selected: MockPreviewRule | None,
    draft_matches: bool,
    limits: MockPreviewLimits,
) -> tuple[MockPreviewWarning, ...]:
    if not draft_matches or selected is draft:
        return ()
    context = _path_context(draft, request)
    decision = MockPreviewDecision(True, True, draft, context, ())
    return render_mock_preview(decision, limits).warnings


def render_mock_preview(
    decision: MockPreviewDecision, limits: MockPreviewLimits
) -> MockPreviewOutcome:
    rule, context = decision.selected, decision.context
    if rule is None or context is None:
        response = (
            MockPreviewResponseValue(404, {}, {"error": "没有匹配的 Mock 路由"})
            if decision.service_enabled
            else None
        )
        return MockPreviewOutcome(
            decision.service_enabled,
            decision.draft_matches,
            None,
            decision.checks,
            decision.draft_warnings,
            response,
        )
    _source_budget(limits, "response_body", rule.route_id).check(rule.response_body)
    renderer = _PreviewRenderer(rule, context, limits)
    body = renderer.render(rule.response_body)
    warnings = decision.draft_warnings + tuple(renderer.warnings)
    if len(warnings) > limits.warning_count:
        raise MockPreviewError(
            f"模板提示超过{limits.warning_count}项, 预览未完成",
            field="response_body",
            code="MOCK_PREVIEW_LIMIT_EXCEEDED",
        )
    MockJsonBudget(
        maximum_bytes=limits.output_bytes,
        maximum_depth=limits.output_depth,
        maximum_nodes=limits.output_nodes,
        field="response_body",
        route_id=rule.route_id,
    ).check(body)
    selected = MockPreviewSelected(
        rule.route_id, rule.name, rule.is_draft, rule.priority, rule.scenario, rule.delay_ms
    )
    return MockPreviewOutcome(
        decision.service_enabled,
        decision.draft_matches,
        selected,
        decision.checks,
        warnings,
        MockPreviewResponseValue(rule.response_status, rule.response_headers, body),
    )


def _source_budget(
    limits: MockPreviewLimits, field: str, route_id: UUID | None = None
) -> MockJsonBudget:
    return MockJsonBudget(
        maximum_bytes=limits.source_bytes,
        maximum_depth=limits.source_depth,
        maximum_nodes=limits.source_nodes,
        field=field,
        route_id=route_id,
    )


def _validate_inputs(
    draft: MockPreviewRule, request: MockPreviewRequest, limits: MockPreviewLimits
) -> None:
    _source_budget(limits, "response_body", draft.route_id).check(draft.response_body)
    _source_budget(limits, "request.body").check(request.body)
    metadata: JsonValue = {
        "draft": {
            "name": draft.name,
            "method": draft.method,
            "path": draft.path_pattern,
            "query": dict(draft.query_conditions),
            "headers": dict(draft.header_conditions),
            "response_headers": dict(draft.response_headers),
            "scenario": draft.scenario,
        },
        "request": {
            "method": request.method,
            "path": request.path,
            "query": dict(request.query),
            "headers": dict(request.headers),
        },
    }
    _source_budget(limits, "request").check(metadata)


def _validate_candidates(candidates: Sequence[MockPreviewRule], limits: MockPreviewLimits) -> None:
    budget = MockJsonBudget(
        maximum_bytes=limits.metadata_bytes,
        maximum_depth=limits.source_depth,
        maximum_nodes=limits.metadata_nodes,
        field="request",
    )
    for rule in candidates:
        metadata: JsonValue = {
            "name": rule.name,
            "path": rule.path_pattern,
            "method": rule.method,
            "scenario": rule.scenario,
            "query": dict(rule.query_conditions),
            "headers": dict(rule.header_conditions),
            "response_headers": dict(rule.response_headers),
        }
        budget.check(metadata)


def _path_context(rule: MockPreviewRule, request: MockPreviewRequest) -> MockRequestContext | None:
    try:
        match = compile_mock_path(rule.path_pattern).fullmatch(request.path)
    except MockTemplateError as error:
        raise MockPreviewError(str(error), field="path_pattern", route_id=rule.route_id) from error
    if match is None:
        return None
    return MockRequestContext(match.groupdict(), request.query, request.headers, request.body)


def _draft_checks(
    rule: MockPreviewRule, request: MockPreviewRequest
) -> tuple[MockPreviewCheck, ...]:
    context = _path_context(rule, request)
    conditions = context or MockRequestContext({}, request.query, request.headers, request.body)
    return (
        MockPreviewCheck("is_enabled", rule.is_enabled, "规则启用状态"),
        MockPreviewCheck("method", rule.method == request.method, "HTTP方法一致"),
        MockPreviewCheck(
            "scenario",
            rule.scenario == request.scenario,
            "场景完全一致; Query _scenario优先于X-FlowTest-Scenario",
        ),
        MockPreviewCheck("path_pattern", context is not None, "应用收到的请求路径匹配"),
        MockPreviewCheck(
            "query_conditions",
            match_mock_conditions(rule.query_conditions, {}, conditions),
            "全部Query条件相等",
        ),
        MockPreviewCheck(
            "header_conditions",
            match_mock_conditions({}, rule.header_conditions, conditions),
            "全部Header条件相等(名称不区分大小写)",
        ),
    )


def _select_rule(
    candidates: Sequence[MockPreviewRule], request: MockPreviewRequest
) -> tuple[MockPreviewRule | None, MockRequestContext | None]:
    for rule in sorted(
        candidates, key=lambda candidate: (-candidate.priority, _creation_order(candidate))
    ):
        if (
            not rule.is_enabled
            or rule.method != request.method
            or rule.scenario != request.scenario
        ):
            continue
        context = _path_context(rule, request)
        if context is not None and match_mock_conditions(
            rule.query_conditions, rule.header_conditions, context
        ):
            return rule, context
    return None, None


def _creation_order(rule: MockPreviewRule) -> datetime:
    if rule.created_at is None:
        return datetime.max.replace(tzinfo=UTC)
    return (
        rule.created_at.replace(tzinfo=UTC)
        if rule.created_at.tzinfo is None
        else rule.created_at.astimezone(UTC)
    )


class _PreviewRenderer:
    def __init__(
        self, rule: MockPreviewRule, context: MockRequestContext, limits: MockPreviewLimits
    ) -> None:
        self._rule = rule
        self._context = context
        self._limits = limits
        self._remaining = limits.output_bytes
        self.warnings: list[MockPreviewWarning] = []

    def render(self, value: JsonValue, pointer: str = "") -> JsonValue:
        if isinstance(value, dict):
            return {
                name: self.render(child, json_pointer(pointer, name))
                for name, child in value.items()
            }
        if isinstance(value, list):
            return [
                self.render(child, json_pointer(pointer, str(index)))
                for index, child in enumerate(value)
            ]
        if not isinstance(value, str):
            return value
        try:
            return self._render_string(value, pointer)
        except MockTemplateError as error:
            raise MockPreviewError(
                str(error),
                field="response_body",
                pointer=pointer,
                route_id=self._rule.route_id,
                code="MOCK_PREVIEW_TEMPLATE_ERROR",
            ) from error

    def _render_string(self, template: str, pointer: str) -> JsonValue:
        references = mock_template_references(template)
        first = next(references, None)
        if first and first.start == 0 and first.end == len(template):
            return render_mock_template(template, self._context)
        size = _string_wire_size(template)
        cursor = 0
        if first is not None:
            self._warn_literal(template[: first.start], pointer)
            size = self._replacement_size(template, first.start, first.end, size, pointer)
            cursor = first.end
        for reference in references:
            self._warn_literal(template[cursor : reference.start], pointer)
            size = self._replacement_size(template, reference.start, reference.end, size, pointer)
            cursor = reference.end
        self._warn_literal(template[cursor:], pointer)
        self._remaining -= size
        if self._remaining < 0:
            self._expansion_limit(pointer)
        return render_mock_template(template, self._context)

    def _replacement_size(
        self, template: str, start: int, end: int, current_size: int, pointer: str
    ) -> int:
        marker = template[start:end]
        replacement = render_mock_template(f" {marker}", self._context)
        if not isinstance(replacement, str):
            raise AssertionError("字符串插值必须返回字符串")
        size = (
            current_size
            - (_string_wire_size(marker) - 2)
            + (_string_wire_size(replacement[1:]) - 2)
        )
        if size > self._remaining:
            self._expansion_limit(pointer)
        return size

    def _warn_literal(self, text: str, pointer: str) -> None:
        if "{{" not in text and "}}" not in text:
            return
        if len(self.warnings) >= self._limits.warning_count:
            raise MockPreviewError(
                f"模板提示超过{self._limits.warning_count}项, 预览未完成",
                field="response_body",
                pointer=pointer,
                route_id=self._rule.route_id,
                code="MOCK_PREVIEW_LIMIT_EXCEEDED",
            )
        self.warnings.append(
            MockPreviewWarning(
                "response_body",
                pointer,
                "该位置包含未识别的模板语法, 按实际运行语义保留为字面文本",
                self._rule.route_id,
            )
        )

    def _expansion_limit(self, pointer: str) -> None:
        raise MockPreviewError(
            "模板展开超过响应字节上限, 预览未完成",
            field="response_body",
            pointer=pointer,
            route_id=self._rule.route_id,
            code="MOCK_PREVIEW_LIMIT_EXCEEDED",
        )


def _string_wire_size(value: str) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
