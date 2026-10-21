from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import JsonValue

from app.domain.mock_preview import (
    MockPreviewRequest,
    MockPreviewRule,
    match_mock_preview,
    render_mock_preview,
)
from app.domain.mock_preview_limits import MockPreviewError, MockPreviewLimits
from app.domain.mock_services import render_mock_template


def _rule() -> MockPreviewRule:
    return MockPreviewRule(
        route_id=uuid4(),
        name="订单草稿",
        method="POST",
        path_pattern="/orders/{id}",
        query_conditions={"mode": "full"},
        header_conditions={"X-Team": "orders"},
        response_status=201,
        response_headers={"X-Static": "{{path.id}}"},
        response_body={"id": "{{path.id}}", "value": "{{body.value}}"},
        scenario=None,
        priority=10,
        delay_ms=30000,
        is_enabled=True,
        is_draft=True,
    )


def _request() -> MockPreviewRequest:
    return MockPreviewRequest(
        "POST", "/orders/42", {"mode": "full"}, {"x-team": "orders"}, {"value": 7}, None
    )


def test_preview_preserves_exact_types_and_literal_headers_without_sleeping() -> None:
    draft = _rule()
    request = replace(_request(), body={"value": [True, None, {"nested": 3}]})
    decision = match_mock_preview(
        draft=draft,
        candidates=[draft],
        request=request,
        service_enabled=True,
        limits=MockPreviewLimits(),
    )
    result = render_mock_preview(decision, MockPreviewLimits())
    assert (
        result.response is not None and result.selected is not None and decision.context is not None
    )
    assert result.response.body == render_mock_template(draft.response_body, decision.context)
    assert result.response.body == {"id": "42", "value": [True, None, {"nested": 3}]}
    assert result.response.headers == {"X-Static": "{{path.id}}"}
    assert result.selected.delay_ms == 30000


@pytest.mark.parametrize(
    "sample,field",
    [
        (replace(_request(), method="GET"), "method"),
        (replace(_request(), path="/orders/42/"), "path_pattern"),
        (replace(_request(), query={"mode": "short"}), "query_conditions"),
        (replace(_request(), headers={"X-Team": "other"}), "header_conditions"),
        (replace(_request(), scenario="missing"), "scenario"),
    ],
)
def test_unmatched_requests_show_exact_failed_conditions(
    sample: MockPreviewRequest, field: str
) -> None:
    draft = _rule()
    decision = match_mock_preview(
        draft=draft,
        candidates=[draft],
        request=sample,
        service_enabled=True,
        limits=MockPreviewLimits(),
    )
    result = render_mock_preview(decision, MockPreviewLimits())
    assert not result.draft_matches and result.selected is None
    assert result.response is not None and result.response.status_code == 404
    assert not next(check for check in result.checks if check.field == field).matched


def test_priority_ties_use_creation_order_and_new_drafts_follow_saved_rules() -> None:
    draft = _rule()
    older = replace(
        draft, route_id=uuid4(), is_draft=False, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    newer = replace(draft, route_id=uuid4(), is_draft=False, created_at=datetime(2026, 1, 2))
    decision = match_mock_preview(
        draft=draft,
        candidates=[newer, draft, older],
        request=_request(),
        service_enabled=True,
        limits=MockPreviewLimits(),
    )
    assert decision.selected == older
    promoted = replace(draft, priority=11)
    decision = match_mock_preview(
        draft=promoted,
        candidates=[newer, promoted, older],
        request=_request(),
        service_enabled=True,
        limits=MockPreviewLimits(),
    )
    assert decision.selected == promoted


def test_disabled_service_does_not_emit_a_fictional_response() -> None:
    draft = _rule()
    decision = match_mock_preview(
        draft=draft,
        candidates=[draft],
        request=_request(),
        service_enabled=False,
        limits=MockPreviewLimits(),
    )
    result = render_mock_preview(decision, MockPreviewLimits())
    assert not result.service_enabled and result.selected is None and result.response is None


def test_unrecognized_syntax_is_literal_and_json_pointer_keys_are_escaped() -> None:
    draft = replace(_rule(), response_body={"a/b~c": "{{unknown.value}} {{path.id}} {{oops"})
    decision = match_mock_preview(
        draft=draft,
        candidates=[draft],
        request=_request(),
        service_enabled=True,
        limits=MockPreviewLimits(),
    )
    result = render_mock_preview(decision, MockPreviewLimits())
    assert result.response is not None and result.response.body == {
        "a/b~c": "{{unknown.value}} 42 {{oops"
    }
    assert len(result.warnings) == 2
    assert all(warning.pointer == "/a~1b~0c" for warning in result.warnings)


@pytest.mark.parametrize(
    "body,request_body",
    [
        ("prefix {{body.value}}", {"value": []}),
        ({"nested": ["{{body.missing}}"]}, {}),
    ],
)
def test_template_failures_identify_the_original_value(
    body: JsonValue, request_body: JsonValue
) -> None:
    draft = replace(_rule(), response_body=body)
    request = replace(_request(), body=request_body)
    decision = match_mock_preview(
        draft=draft,
        candidates=[draft],
        request=request,
        service_enabled=True,
        limits=MockPreviewLimits(),
    )
    with pytest.raises(MockPreviewError) as caught:
        render_mock_preview(decision, MockPreviewLimits())
    assert caught.value.code == "MOCK_PREVIEW_TEMPLATE_ERROR"
    assert caught.value.field == "response_body"
    assert caught.value.pointer == ("" if isinstance(body, str) else "/nested/0")


@pytest.mark.parametrize(
    "limits,body,request_body",
    [
        (MockPreviewLimits(source_bytes=512), "a" * 513, {}),
        (MockPreviewLimits(source_depth=2), [[[[]]]], {}),
        (MockPreviewLimits(source_nodes=3), [1, 2, 3], {}),
        (MockPreviewLimits(output_bytes=40), "{{body.value}}-{{body.value}}", {"value": "a" * 30}),
        (
            MockPreviewLimits(output_nodes=3),
            ["{{body.value}}", "{{body.value}}"],
            {"value": [1, 2]},
        ),
        (MockPreviewLimits(output_depth=1), {"value": "{{body.value}}"}, {"value": {"child": 1}}),
        (MockPreviewLimits(warning_count=1), ["{{unknown.one}}", "{{unknown.two}}"], {}),
    ],
)
def test_preview_limits_fail_explicitly_without_a_partial_result(
    limits: MockPreviewLimits, body: JsonValue, request_body: JsonValue
) -> None:
    draft = replace(_rule(), response_body=body)
    request = replace(_request(), body=request_body)
    with pytest.raises(MockPreviewError) as caught:
        decision = match_mock_preview(
            draft=draft, candidates=[draft], request=request, service_enabled=True, limits=limits
        )
        render_mock_preview(decision, limits)
    assert caught.value.code == "MOCK_PREVIEW_LIMIT_EXCEEDED"


def test_candidate_and_aggregate_metadata_limits_never_match_a_truncated_catalog() -> None:
    draft = _rule()
    with pytest.raises(MockPreviewError, match="超过1条"):
        match_mock_preview(
            draft=draft,
            candidates=[draft, draft],
            request=_request(),
            service_enabled=True,
            limits=MockPreviewLimits(candidate_count=1),
        )
    with pytest.raises(MockPreviewError) as caught:
        match_mock_preview(
            draft=draft,
            candidates=[draft],
            request=_request(),
            service_enabled=True,
            limits=MockPreviewLimits(metadata_bytes=10),
        )
    assert caught.value.code == "MOCK_PREVIEW_LIMIT_EXCEEDED"


def test_unicode_and_nonfinite_values_are_rejected_as_standard_json_errors() -> None:
    draft = _rule()
    for body in ["\ud800", float("nan")]:
        with pytest.raises(MockPreviewError, match="标准JSON"):
            match_mock_preview(
                draft=replace(draft, response_body=body),
                candidates=[draft],
                request=_request(),
                service_enabled=True,
                limits=MockPreviewLimits(),
            )
