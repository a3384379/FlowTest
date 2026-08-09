from app.domain.assertions import (
    AssertionKind,
    AssertionSpec,
    ComparisonOperator,
    ResponseSnapshot,
    evaluate_assertions,
)


def test_all_supported_assertions() -> None:
    snapshot = ResponseSnapshot(
        status_code=200,
        elapsed_ms=125.5,
        headers={"Content-Type": "application/json", "X-Trace": "abc-123"},
        body={"user": {"id": 42, "name": "Alice"}, "roles": ["editor", "viewer"]},
    )
    specs = (
        AssertionSpec(AssertionKind.STATUS_CODE, expected=200),
        AssertionSpec(
            AssertionKind.RESPONSE_TIME,
            operator=ComparisonOperator.LESS_THAN,
            expected=500,
        ),
        AssertionSpec(
            AssertionKind.HEADER,
            operator=ComparisonOperator.CONTAINS,
            target="content-type",
            expected="json",
        ),
        AssertionSpec(AssertionKind.JSONPATH, target="$.user.id", expected=42),
        AssertionSpec(
            AssertionKind.JMESPATH,
            operator=ComparisonOperator.MATCHES,
            target="user.name",
            expected="^Ali",
        ),
        AssertionSpec(
            AssertionKind.JSON_SCHEMA,
            expected={
                "type": "object",
                "required": ["user"],
                "properties": {"user": {"type": "object"}},
            },
        ),
    )

    outcomes = evaluate_assertions(snapshot, specs)

    assert all(outcome.passed for outcome in outcomes)
    assert outcomes[3].actual == 42


def test_failed_and_invalid_assertions_return_explainable_outcomes() -> None:
    snapshot = ResponseSnapshot(
        status_code=404,
        elapsed_ms=10,
        headers={},
        body={"items": [1, 2]},
    )
    specs = (
        AssertionSpec(AssertionKind.STATUS_CODE, expected=200),
        AssertionSpec(
            AssertionKind.HEADER,
            operator=ComparisonOperator.EXISTS,
            target="X-Missing",
        ),
        AssertionSpec(AssertionKind.JSONPATH, target="invalid[[", expected=1),
        AssertionSpec(AssertionKind.JSON_SCHEMA, expected="not-a-schema"),
    )

    outcomes = evaluate_assertions(snapshot, specs)

    assert not any(outcome.passed for outcome in outcomes)
    assert "实际值" in outcomes[0].message
    assert "失败" in outcomes[2].message
    assert "expected" in outcomes[3].message


def test_numeric_and_collection_operators_reject_wrong_types() -> None:
    snapshot = ResponseSnapshot(status_code=200, elapsed_ms=1, headers={}, body={})
    specs = (
        AssertionSpec(
            AssertionKind.JMESPATH,
            operator=ComparisonOperator.NOT_EQUALS,
            target="missing",
            expected="value",
        ),
        AssertionSpec(
            AssertionKind.JMESPATH,
            operator=ComparisonOperator.GREATER_THAN,
            target="missing",
            expected=1,
        ),
    )

    outcomes = evaluate_assertions(snapshot, specs)

    assert outcomes[0].passed
    assert not outcomes[1].passed


def test_assertion_edge_cases_are_reported_without_raising() -> None:
    snapshot = ResponseSnapshot(
        status_code=200,
        elapsed_ms=10,
        headers={},
        body={"roles": ["editor", "viewer"], "count": 2},
    )
    specs = (
        AssertionSpec(AssertionKind.HEADER, target=None),
        AssertionSpec(
            AssertionKind.JSONPATH,
            operator=ComparisonOperator.EXISTS,
            target="$.missing",
        ),
        AssertionSpec(
            AssertionKind.JSONPATH,
            target="$.roles[*]",
            expected=["editor", "viewer"],
        ),
        AssertionSpec(AssertionKind.JMESPATH, target=None),
        AssertionSpec(
            AssertionKind.JSON_SCHEMA,
            expected={"type": "object", "required": ["missing"]},
        ),
        AssertionSpec(
            AssertionKind.STATUS_CODE,
            operator=ComparisonOperator.CONTAINS,
            expected=2,
        ),
        AssertionSpec(
            AssertionKind.RESPONSE_TIME,
            operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
            expected=10,
        ),
        AssertionSpec(
            AssertionKind.RESPONSE_TIME,
            operator=ComparisonOperator.GREATER_THAN,
            expected=9,
        ),
        AssertionSpec(
            AssertionKind.RESPONSE_TIME,
            operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
            expected=10,
        ),
    )

    outcomes = evaluate_assertions(snapshot, specs)

    assert [outcome.passed for outcome in outcomes] == [
        False,
        False,
        True,
        False,
        False,
        False,
        True,
        True,
        True,
    ]
