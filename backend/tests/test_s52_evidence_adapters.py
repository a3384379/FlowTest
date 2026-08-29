from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.domain.evidence import EvidenceBundle, PythonSourceEvidenceProvider, SourceSnapshot
from app.domain.evidence_adapters import (
    DatabaseEvidenceSubmission,
    EntityMappingBudgetExceeded,
    EntityMappingCandidateKind,
    JavaEvidenceSubmission,
    JavaSourceSnapshot,
    JavaSpringPocProvider,
    MappingEvidenceInput,
    adapt_database_evidence,
    adapt_evidence_bundle,
    adapt_java_evidence,
    derive_entity_mapping,
    with_mapping_conflict_findings,
)
from app.domain.test_contexts import (
    DatabaseExternalEvidenceStructuredData,
    EvidenceBundleExternalEvidenceStructuredData,
    ExternalDatabaseColumnClaim,
    ExternalEvidenceEnvelope,
    JavaExternalEvidenceStructuredData,
    finding_semantic_fingerprint,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "v6_golden"
RUOYI_ROOT = FIXTURE_ROOT.parents[4] / "RuoYi"
PROJECT_ID = "00000000-0000-0000-0000-000000000001"
SUBJECT_REF = f"flowtest://projects/{PROJECT_ID}/operations/orders"


def test_java_and_database_contracts_adapt_to_revisioned_external_evidence() -> None:
    java = JavaEvidenceSubmission.model_validate(_java_submission())
    database = DatabaseEvidenceSubmission.model_validate(_database_submission())

    java_envelope = adapt_java_evidence(java)
    database_envelope = adapt_database_evidence(database)

    assert java_envelope.provider.type.value == "repository"
    assert java_envelope.source.revision == "a1b2c3d4"
    assert {
        finding.structured_data.claim_kind
        for finding in java_envelope.findings
        if isinstance(finding.structured_data, JavaExternalEvidenceStructuredData)
    } == {
        "controller_route",
        "dto_field",
        "bean_validation",
        "service_call",
        "feign_call",
        "mapper_repository",
        "entity",
        "table_column",
        "enum_state",
        "exception",
        "kafka_event",
    }
    assert database_envelope.provider.type.value == "database"
    assert database_envelope.source.revision == "schema-v1"
    column_claims = [
        finding.structured_data.claim
        for finding in database_envelope.findings
        if isinstance(finding.structured_data, DatabaseExternalEvidenceStructuredData)
        and isinstance(finding.structured_data.claim, ExternalDatabaseColumnClaim)
    ]
    assert any(
        claim.primary_key is True and claim.unique is True and claim.nullable is False
        for claim in column_claims
    )
    assert any(claim.foreign_key == "public.customers.id" for claim in column_claims)
    assert any(
        claim.observed_distribution is not None
        and claim.observed_distribution.enum_candidates == ["created", "cancelled"]
        and claim.masked_example == "***ated"
        for claim in column_claims
    )
    ExternalEvidenceEnvelope.model_validate(java_envelope.model_dump(mode="json"))
    ExternalEvidenceEnvelope.model_validate(database_envelope.model_dump(mode="json"))


def test_java_contracts_reject_sensitive_paths_at_both_boundaries() -> None:
    sensitive_value = "4111111111111111"
    dedicated_payload = _java_submission()
    dedicated_payload["claims"][0]["source_path"] = f"src/{sensitive_value}.java:4"

    with pytest.raises(ValidationError, match="sensitive scalar"):
        JavaEvidenceSubmission.model_validate(dedicated_payload)

    dedicated_route = _java_submission()
    dedicated_route["claims"][0]["path"] = f"/users/{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        JavaEvidenceSubmission.model_validate(dedicated_route)

    dedicated_field = _java_submission()
    dto_field = next(claim for claim in dedicated_field["claims"] if claim["kind"] == "dto_field")
    dto_field["field_name"] = f"user{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        JavaEvidenceSubmission.model_validate(dedicated_field)

    dedicated_constraint = _java_submission()
    constraint_claim = next(
        claim for claim in dedicated_constraint["claims"] if claim["kind"] == "bean_validation"
    )
    constraint_claim["constraint"] = f'message = "{sensitive_value}"'
    with pytest.raises(ValidationError, match="sensitive scalar"):
        JavaEvidenceSubmission.model_validate(dedicated_constraint)

    dedicated_topic = _java_submission()
    kafka_claim = next(
        claim for claim in dedicated_topic["claims"] if claim["kind"] == "kafka_event"
    )
    kafka_claim["topic_ref"] = f"kafka://{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        JavaEvidenceSubmission.model_validate(dedicated_topic)

    for call_ref in ("caller_ref", "callee_ref"):
        dedicated_call = _java_submission()
        service_call = next(
            claim for claim in dedicated_call["claims"] if claim["kind"] == "service_call"
        )
        service_call[call_ref] = f"java://service/{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            JavaEvidenceSubmission.model_validate(dedicated_call)

    for persistence_ref in ("operation_ref", "repository_ref", "method_ref", "entity_ref"):
        dedicated_persistence = _java_submission()
        persistence_claim = next(
            claim
            for claim in dedicated_persistence["claims"]
            if claim["kind"] == "mapper_repository"
        )
        persistence_claim[persistence_ref] = f"java://repository/{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            JavaEvidenceSubmission.model_validate(dedicated_persistence)

    generic_payload = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    generic_payload["findings"][0]["structured_data"]["claim"]["source_path"] = (
        f"src/{sensitive_value}.java:4"
    )

    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(generic_payload)

    generic_route = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    route_finding = next(
        finding
        for finding in generic_route["findings"]
        if finding["structured_data"]["claim_kind"] == "controller_route"
    )
    route_finding["structured_data"]["claim"]["path"] = f"/users/{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(generic_route)

    generic_field = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    dto_finding = next(
        finding
        for finding in generic_field["findings"]
        if finding["structured_data"]["claim_kind"] == "dto_field"
    )
    dto_finding["structured_data"]["claim"]["field_name"] = f"user{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(generic_field)

    for identifier in ("field_name", "column_name"):
        dedicated_column = _java_submission()
        column_claim = next(
            claim for claim in dedicated_column["claims"] if claim["kind"] == "table_column"
        )
        column_claim[identifier] = f"card{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            JavaEvidenceSubmission.model_validate(dedicated_column)

        generic_column = adapt_java_evidence(
            JavaEvidenceSubmission.model_validate(_java_submission())
        ).model_dump(mode="json")
        column_finding = next(
            finding
            for finding in generic_column["findings"]
            if finding["structured_data"]["claim_kind"] == "table_column"
        )
        column_finding["structured_data"]["claim"][identifier] = f"card{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            ExternalEvidenceEnvelope.model_validate(generic_column)

    generic_constraint = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    constraint_finding = next(
        finding
        for finding in generic_constraint["findings"]
        if finding["structured_data"]["claim_kind"] == "bean_validation"
    )
    constraint_finding["structured_data"]["claim"]["constraint"] = f'message = "{sensitive_value}"'
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(generic_constraint)

    generic_topic = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    topic_finding = next(
        finding
        for finding in generic_topic["findings"]
        if finding["structured_data"]["claim_kind"] == "kafka_event"
    )
    topic_finding["structured_data"]["claim"]["topic_ref"] = f"kafka://{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(generic_topic)

    for call_ref in ("caller_ref", "callee_ref"):
        generic_call = adapt_java_evidence(
            JavaEvidenceSubmission.model_validate(_java_submission())
        ).model_dump(mode="json")
        call_finding = next(
            finding
            for finding in generic_call["findings"]
            if finding["structured_data"]["claim_kind"] == "service_call"
        )
        call_finding["structured_data"]["claim"][call_ref] = f"java://service/{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            ExternalEvidenceEnvelope.model_validate(generic_call)

    for persistence_ref in ("operation_ref", "repository_ref", "method_ref", "entity_ref"):
        generic_persistence = adapt_java_evidence(
            JavaEvidenceSubmission.model_validate(_java_submission())
        ).model_dump(mode="json")
        persistence_finding = next(
            finding
            for finding in generic_persistence["findings"]
            if finding["structured_data"]["claim_kind"] == "mapper_repository"
        )
        persistence_finding["structured_data"]["claim"][persistence_ref] = (
            f"java://repository/{sensitive_value}"
        )
        with pytest.raises(ValidationError, match="sensitive scalar"):
            ExternalEvidenceEnvelope.model_validate(generic_persistence)


def test_adapter_contracts_reject_all_remaining_sensitive_identifiers() -> None:
    sensitive_value = "13800138000"
    java_identifiers = (
        ("controller_route", "handler"),
        ("dto_field", "dto_type"),
        ("bean_validation", "dto_type"),
        ("bean_validation", "field_name"),
        ("bean_validation", "annotation"),
        ("entity", "class_name"),
        ("enum_state", "field_name"),
        ("exception", "exception_type"),
        ("exception", "outcome"),
        ("kafka_event", "event_type"),
    )
    for claim_kind, field_name in java_identifiers:
        dedicated = _java_submission()
        claim = next(claim for claim in dedicated["claims"] if claim["kind"] == claim_kind)
        claim[field_name] = f"User{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            JavaEvidenceSubmission.model_validate(dedicated)

        generic = adapt_java_evidence(
            JavaEvidenceSubmission.model_validate(_java_submission())
        ).model_dump(mode="json")
        finding = next(
            finding
            for finding in generic["findings"]
            if finding["structured_data"]["claim_kind"] == claim_kind
        )
        finding["structured_data"]["claim"][field_name] = f"User{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            ExternalEvidenceEnvelope.model_validate(generic)

    dedicated_database_identifiers = (
        ("table", "schema_name"),
        ("table", "name"),
        ("column", "name"),
    )
    for claim_kind, field_name in dedicated_database_identifiers:
        dedicated = _database_submission()
        if claim_kind == "table":
            dedicated["tables"][0][field_name] = f"tenant{sensitive_value}"
        else:
            dedicated["tables"][0]["columns"][0][field_name] = f"tenant{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            DatabaseEvidenceSubmission.model_validate(dedicated)

    generic_database_identifiers = (
        ("table", "schema_name"),
        ("table", "name"),
        ("column", "schema_name"),
        ("column", "table_name"),
        ("column", "name"),
    )
    for claim_kind, field_name in generic_database_identifiers:
        generic = adapt_database_evidence(
            DatabaseEvidenceSubmission.model_validate(_database_submission())
        ).model_dump(mode="json")
        finding = next(
            finding
            for finding in generic["findings"]
            if finding["structured_data"]["claim_kind"] == claim_kind
        )
        finding["structured_data"]["claim"][field_name] = f"tenant{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive scalar"):
            ExternalEvidenceEnvelope.model_validate(generic)


def test_adapter_contracts_reject_sensitive_source_and_subject_refs() -> None:
    sensitive_value = "13800138000"
    for submission_factory, submission_type in (
        (_java_submission, JavaEvidenceSubmission),
        (_database_submission, DatabaseEvidenceSubmission),
    ):
        sensitive_source = submission_factory()
        sensitive_source["source"]["ref"] = f"repository://{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive data"):
            submission_type.model_validate(sensitive_source)

        sensitive_subject = submission_factory()
        sensitive_subject["subject_ref"] = f"flowtest://subjects/{sensitive_value}"
        with pytest.raises(ValidationError, match="sensitive data"):
            submission_type.model_validate(sensitive_subject)

    generic = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    generic["source"]["ref"] = f"repository://{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive data"):
        ExternalEvidenceEnvelope.model_validate(generic)

    generic = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    generic["subject_ref"] = f"flowtest://subjects/{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive data"):
        ExternalEvidenceEnvelope.model_validate(generic)


def test_adapter_contracts_reject_sensitive_revision_and_version_metadata() -> None:
    sensitive_value = "13800138000"
    for submission_factory, submission_type in (
        (_java_submission, JavaEvidenceSubmission),
        (_database_submission, DatabaseEvidenceSubmission),
    ):
        sensitive_revision = submission_factory()
        sensitive_revision["source"]["revision"] = sensitive_value
        with pytest.raises(ValidationError, match="sensitive data"):
            submission_type.model_validate(sensitive_revision)

        sensitive_version = submission_factory()
        sensitive_version["provider"]["version"] = sensitive_value
        with pytest.raises(ValidationError, match="sensitive data"):
            submission_type.model_validate(sensitive_version)

    generic = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    generic["source"]["revision"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive data"):
        ExternalEvidenceEnvelope.model_validate(generic)

    generic = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    generic["provider"]["version"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive data"):
        ExternalEvidenceEnvelope.model_validate(generic)


def test_adapter_contracts_reject_sensitive_redaction_paths_and_foreign_keys() -> None:
    sensitive_value = "13800138000"
    redaction = {
        "path": f"$.users.{sensitive_value}",
        "method": "removed",
        "reason": "fixture cleanup",
    }
    for submission_factory, submission_type in (
        (_java_submission, JavaEvidenceSubmission),
        (_database_submission, DatabaseEvidenceSubmission),
    ):
        dedicated = submission_factory()
        dedicated["redactions"] = [redaction]
        with pytest.raises(ValidationError, match="sensitive scalar"):
            submission_type.model_validate(dedicated)

    generic = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    generic["redactions"] = [redaction]
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(generic)

    dedicated_database = _database_submission()
    dedicated_database["tables"][0]["columns"][0]["foreign_key"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive scalar"):
        DatabaseEvidenceSubmission.model_validate(dedicated_database)

    generic_database = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    column_finding = next(
        finding
        for finding in generic_database["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
    )
    column_finding["structured_data"]["claim"]["foreign_key"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(generic_database)


def test_adapter_contracts_reject_sensitive_declared_types() -> None:
    sensitive_value = "4111111111111111"
    dedicated_java = _java_submission()
    dto_claim = next(claim for claim in dedicated_java["claims"] if claim["kind"] == "dto_field")
    dto_claim["field_type"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive"):
        JavaEvidenceSubmission.model_validate(dedicated_java)

    dedicated_database = _database_submission()
    dedicated_database["tables"][0]["columns"][0]["data_type"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive"):
        DatabaseEvidenceSubmission.model_validate(dedicated_database)

    generic_java = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    dto_finding = next(
        finding
        for finding in generic_java["findings"]
        if finding["structured_data"]["claim_kind"] == "dto_field"
    )
    dto_finding["structured_data"]["claim"]["field_type"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive"):
        ExternalEvidenceEnvelope.model_validate(generic_java)

    generic_database = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    column_finding = next(
        finding
        for finding in generic_database["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
    )
    column_finding["structured_data"]["claim"]["data_type"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive"):
        ExternalEvidenceEnvelope.model_validate(generic_database)


def test_database_submission_rejects_oversized_derived_envelope() -> None:
    payload = _database_submission()
    payload["tables"] = [
        {
            "schema_name": "public",
            "name": "large_profiles",
            "columns": [
                {
                    "name": f"field_{index:03d}",
                    "data_type": "text",
                    "nullable": True,
                    "enum_values": ["x" * 4000],
                }
                for index in range(79)
            ],
        }
    ]

    with pytest.raises(ValidationError, match="database evidence envelope byte budget exceeded"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_java_submission_rejects_oversized_derived_envelope() -> None:
    payload = _java_submission()
    payload["redactions"] = [
        {
            "path": f"src/{index:03d}/" + ("x" * 1012),
            "method": "removed",
            "reason": "bounded-" + ("y" * 492),
        }
        for index in range(100)
    ]
    payload["warnings"] = [
        {
            "code": f"LARGE_{index:03d}",
            "message": "bounded-" + ("z" * 992),
        }
        for index in range(100)
    ]

    with pytest.raises(ValidationError, match="java evidence envelope byte budget exceeded"):
        JavaEvidenceSubmission.model_validate(payload)


def test_database_finding_ids_use_unambiguous_tuple_identity() -> None:
    payload = _database_submission()
    payload["tables"] = [
        {
            "schema_name": "a-b",
            "name": "c",
            "columns": [{"name": "d", "data_type": "text", "nullable": True}],
        },
        {
            "schema_name": "a",
            "name": "b-c",
            "columns": [{"name": "d", "data_type": "text", "nullable": True}],
        },
    ]

    envelope = adapt_database_evidence(DatabaseEvidenceSubmission.model_validate(payload))

    finding_ids = [finding.id for finding in envelope.findings]
    assert len(finding_ids) == len(set(finding_ids)) == 4
    assert sum(identifier.startswith("database-table-") for identifier in finding_ids) == 2
    assert sum(identifier.startswith("database-column-") for identifier in finding_ids) == 2


def test_database_contract_rejects_raw_examples_pii_and_write_sql() -> None:
    raw_example = _database_submission()
    raw_example["tables"][0]["columns"][0]["masked_example"] = "order-0001"
    with pytest.raises(ValidationError, match="masked"):
        DatabaseEvidenceSubmission.model_validate(raw_example)

    raw_pii = _database_submission()
    raw_pii["tables"][0]["columns"][0]["masked_example"] = "*** person@example.com"
    with pytest.raises(ValidationError, match="sensitive"):
        DatabaseEvidenceSubmission.model_validate(raw_pii)

    masked_card = _database_submission()
    masked_card["tables"][0]["columns"][0]["masked_example"] = "*** 4111111111111111"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        DatabaseEvidenceSubmission.model_validate(masked_card)

    raw_distribution_pii = _database_submission()
    raw_distribution_pii["tables"][0]["columns"][1]["observed_distribution"]["enum_candidates"] = [
        "+8613800138000"
    ]
    with pytest.raises(ValidationError, match="sensitive"):
        DatabaseEvidenceSubmission.model_validate(raw_distribution_pii)

    sensitive_minimum = _database_submission()
    sensitive_minimum["tables"][0]["columns"][1]["observed_distribution"]["minimum"] = 13800138000
    with pytest.raises(ValidationError, match="sensitive scalar"):
        DatabaseEvidenceSubmission.model_validate(sensitive_minimum)

    write_sql = _database_submission()
    write_sql["tables"][0]["columns"][1]["check_expression"] = (
        "status IN ('created'); DROP TABLE orders"
    )
    with pytest.raises(ValidationError, match="write SQL"):
        DatabaseEvidenceSubmission.model_validate(write_sql)

    sensitive_check = _database_submission()
    sensitive_check["tables"][0]["columns"][1]["check_expression"] = "phone IN ('13800138000')"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        DatabaseEvidenceSubmission.model_validate(sensitive_check)

    unknown_sql = _database_submission()
    unknown_sql["sql"] = "SELECT * FROM orders"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DatabaseEvidenceSubmission.model_validate(unknown_sql)

    non_finite_distribution = _database_submission()
    non_finite_distribution["tables"][0]["columns"][1]["observed_distribution"]["minimum"] = float(
        "nan"
    )
    with pytest.raises(ValidationError, match="finite number"):
        DatabaseEvidenceSubmission.model_validate(non_finite_distribution)

    non_finite_enum = _database_submission()
    non_finite_enum["tables"][0]["columns"][1]["enum_values"] = [float("inf")]
    with pytest.raises(ValidationError, match="finite number"):
        DatabaseEvidenceSubmission.model_validate(non_finite_enum)

    external_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    external_column = next(
        finding
        for finding in external_envelope["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
    )
    external_column["structured_data"]["claim"]["enum_values"] = [float("nan")]
    with pytest.raises(ValidationError, match="finite number"):
        ExternalEvidenceEnvelope.model_validate(external_envelope)

    external_sensitive_check = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    external_check_column = next(
        finding
        for finding in external_sensitive_check["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
        and finding["structured_data"]["claim"]["name"] == "status"
    )
    external_check_column["structured_data"]["claim"]["check_expression"] = (
        "phone IN ('13800138000')"
    )
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(external_sensitive_check)

    external_java = adapt_java_evidence(
        JavaEvidenceSubmission.model_validate(_java_submission())
    ).model_dump(mode="json")
    external_state = next(
        finding
        for finding in external_java["findings"]
        if finding["structured_data"]["claim_kind"] == "enum_state"
    )
    external_state["structured_data"]["claim"]["values"] = ["4111111111111111"]
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(external_java)

    external_enum = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    enum_column = next(
        finding
        for finding in external_enum["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
        and finding["structured_data"]["claim"]["name"] == "status"
    )
    enum_column["structured_data"]["claim"]["enum_values"] = ["4111111111111111"]
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(external_enum)

    external_distribution = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    distribution_column = next(
        finding
        for finding in external_distribution["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
        and finding["structured_data"]["claim"]["name"] == "status"
    )
    distribution_column["structured_data"]["claim"]["observed_distribution"]["enum_candidates"] = [
        "+8613800138000"
    ]
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(external_distribution)

    external_sensitive_maximum = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    maximum_column = next(
        finding
        for finding in external_sensitive_maximum["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
        and finding["structured_data"]["claim"]["name"] == "status"
    )
    maximum_column["structured_data"]["claim"]["observed_distribution"]["maximum"] = (
        4111111111111111
    )
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(external_sensitive_maximum)

    external_masked_card = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    ).model_dump(mode="json")
    masked_column = next(
        finding
        for finding in external_masked_card["findings"]
        if finding["structured_data"]["claim_kind"] == "column"
    )
    masked_column["structured_data"]["claim"]["masked_example"] = "*** 4111111111111111"
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(external_masked_card)


def test_database_distribution_rejects_inverted_extrema_at_dedicated_boundary() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {"minimum": 10, "maximum": 1}
    )

    with pytest.raises(ValidationError, match="minimum must not exceed maximum"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_distribution_rejects_inverted_extrema_at_generic_boundary() -> None:
    payload = _database_envelope_with_distribution_update({"minimum": 10.0, "maximum": 1.0})

    with pytest.raises(ValidationError, match="minimum must not exceed maximum"):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_distribution_rejects_unequal_singleton_extrema_at_dedicated_boundary() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {"distinct_count": 1, "minimum": 1.0, "maximum": 2.0, "enum_candidates": []}
    )

    with pytest.raises(ValidationError, match="singleton extrema must be equal"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_distribution_rejects_unequal_singleton_extrema_at_generic_boundary() -> None:
    payload = _database_envelope_with_distribution_update(
        {"distinct_count": 1, "minimum": 1.0, "maximum": 2.0, "enum_candidates": []}
    )

    with pytest.raises(ValidationError, match="singleton extrema must be equal"):
        ExternalEvidenceEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    "one_sided_extremum",
    [{"minimum": 1.0}, {"maximum": 3.0}],
    ids=["minimum", "maximum"],
)
def test_database_distribution_rejects_one_sided_singleton_mismatch_dedicated(
    one_sided_extremum: dict[str, float],
) -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {
            "distinct_count": 1,
            "enum_candidates": [2],
            **one_sided_extremum,
        }
    )

    with pytest.raises(ValidationError, match="singleton candidate must equal observed extrema"):
        DatabaseEvidenceSubmission.model_validate(payload)


@pytest.mark.parametrize(
    "one_sided_extremum",
    [{"minimum": 1.0}, {"maximum": 3.0}],
    ids=["minimum", "maximum"],
)
def test_database_distribution_rejects_one_sided_singleton_mismatch_generic(
    one_sided_extremum: dict[str, float],
) -> None:
    payload = _database_envelope_with_distribution_update(
        {
            "distinct_count": 1,
            "enum_candidates": [2],
            **one_sided_extremum,
        }
    )

    with pytest.raises(ValidationError, match="singleton candidate must equal observed extrema"):
        ExternalEvidenceEnvelope.model_validate(payload)


@pytest.mark.parametrize("candidate", [1, 11], ids=["below-minimum", "above-maximum"])
def test_database_distribution_rejects_numeric_candidates_outside_extrema_at_dedicated_boundary(
    candidate: int,
) -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {
            "distinct_count": 2,
            "minimum": 5.0,
            "maximum": 10.0,
            "enum_candidates": [candidate],
        }
    )

    with pytest.raises(
        ValidationError, match="numeric candidates must fall within observed extrema"
    ):
        DatabaseEvidenceSubmission.model_validate(payload)


@pytest.mark.parametrize("candidate", [1, 11], ids=["below-minimum", "above-maximum"])
def test_database_distribution_rejects_numeric_candidates_outside_extrema_at_generic_boundary(
    candidate: int,
) -> None:
    payload = _database_envelope_with_distribution_update(
        {
            "distinct_count": 2,
            "minimum": 5.0,
            "maximum": 10.0,
            "enum_candidates": [candidate],
        }
    )

    with pytest.raises(
        ValidationError, match="numeric candidates must fall within observed extrema"
    ):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_distribution_rejects_zero_distinct_for_non_null_rows_dedicated() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"] = {
        "row_count": 10,
        "null_ratio": 0,
        "distinct_count": 0,
    }

    with pytest.raises(ValidationError, match="non-null rows require a positive distinct count"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_distribution_rejects_zero_distinct_for_non_null_rows_generic() -> None:
    payload = _database_envelope_with_distribution_update(
        {
            "row_count": 10,
            "null_ratio": 0,
            "distinct_count": 0,
            "enum_candidates": [],
            "minimum": None,
            "maximum": None,
        }
    )

    with pytest.raises(ValidationError, match="non-null rows require a positive distinct count"):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_distribution_rejects_distinct_count_above_row_count_at_dedicated_boundary() -> (
    None
):
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {"row_count": 1, "distinct_count": 2}
    )

    with pytest.raises(ValidationError, match="distinct count must not exceed row count"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_distribution_rejects_distinct_count_above_row_count_at_generic_boundary() -> None:
    payload = _database_envelope_with_distribution_update({"row_count": 1, "distinct_count": 2})

    with pytest.raises(ValidationError, match="distinct count must not exceed row count"):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_distribution_bounds_unique_candidates_at_dedicated_boundary() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {"distinct_count": 1, "enum_candidates": ["active", "inactive"]}
    )

    with pytest.raises(ValidationError, match="candidates must not exceed distinct count"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_distribution_bounds_unique_candidates_at_generic_boundary() -> None:
    payload = _database_envelope_with_distribution_update(
        {"distinct_count": 1, "enum_candidates": ["active", "inactive"]}
    )

    with pytest.raises(ValidationError, match="candidates must not exceed distinct count"):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_distribution_counts_duplicate_candidates_once() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {"distinct_count": 1, "enum_candidates": ["active", "active"]}
    )

    submission = DatabaseEvidenceSubmission.model_validate(payload)

    distribution = submission.tables[0].columns[1].observed_distribution
    assert distribution is not None
    assert distribution.distinct_count == 1


def test_database_distribution_bounds_distinct_count_by_non_null_rows_at_dedicated_boundary() -> (
    None
):
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["nullable"] = True
    payload["tables"][0]["columns"][1]["observed_distribution"] = {
        "row_count": 2,
        "null_ratio": 0.5,
        "distinct_count": 2,
        "enum_candidates": ["active", "inactive"],
    }

    with pytest.raises(ValidationError, match="distinct count must not exceed non-null row count"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_distribution_bounds_distinct_count_by_non_null_rows_at_generic_boundary() -> None:
    payload = _database_envelope_with_distribution_update(
        {
            "row_count": 2,
            "null_ratio": 0.5,
            "distinct_count": 2,
            "enum_candidates": ["active", "inactive"],
        },
        nullable=True,
    )

    with pytest.raises(ValidationError, match="distinct count must not exceed non-null row count"):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_distribution_counts_candidates_by_state_scalar_identity() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"].update(
        {"distinct_count": 1, "enum_candidates": [True, 1]}
    )

    with pytest.raises(ValidationError, match="candidates must not exceed distinct count"):
        DatabaseEvidenceSubmission.model_validate(payload)

    generic = _database_envelope_with_distribution_update(
        {"distinct_count": 1, "enum_candidates": [True, 1]}
    )
    with pytest.raises(ValidationError, match="candidates must not exceed distinct count"):
        ExternalEvidenceEnvelope.model_validate(generic)

    equivalent_text = _database_submission()
    equivalent_text["tables"][0]["columns"][1]["observed_distribution"].update(
        {"distinct_count": 1, "enum_candidates": ["1", 1]}
    )
    DatabaseEvidenceSubmission.model_validate(equivalent_text)


@pytest.mark.parametrize(
    "observed_values",
    [
        {"enum_candidates": ["ghost"]},
        {"minimum": 1},
        {"maximum": 1},
    ],
    ids=["enum-candidates", "minimum", "maximum"],
)
def test_database_distribution_rejects_values_for_zero_rows_at_dedicated_boundary(
    observed_values: dict[str, Any],
) -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["nullable"] = True
    payload["tables"][0]["columns"][1]["observed_distribution"] = {
        "row_count": 0,
        "distinct_count": 0,
        **observed_values,
    }

    with pytest.raises(
        ValidationError, match="empty distribution must not include observed values"
    ):
        DatabaseEvidenceSubmission.model_validate(payload)


@pytest.mark.parametrize(
    "observed_values",
    [
        {"enum_candidates": ["ghost"]},
        {"minimum": 1},
        {"maximum": 1},
    ],
    ids=["enum-candidates", "minimum", "maximum"],
)
def test_database_distribution_rejects_values_for_zero_rows_at_generic_boundary(
    observed_values: dict[str, Any],
) -> None:
    payload = _database_envelope_with_distribution_update(
        {
            "row_count": 0,
            "distinct_count": 0,
            "enum_candidates": [],
            "minimum": None,
            "maximum": None,
            **observed_values,
        },
        nullable=True,
    )

    with pytest.raises(
        ValidationError, match="empty distribution must not include observed values"
    ):
        ExternalEvidenceEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    "observed_values",
    [
        {"distinct_count": 1},
        {"enum_candidates": ["ghost"]},
        {"minimum": 1},
        {"maximum": 1},
    ],
    ids=["distinct-count", "enum-candidates", "minimum", "maximum"],
)
def test_database_distribution_rejects_values_when_every_row_is_null_at_dedicated_boundary(
    observed_values: dict[str, Any],
) -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["nullable"] = True
    payload["tables"][0]["columns"][1]["observed_distribution"] = {
        "row_count": 10,
        "distinct_count": 0,
        "null_ratio": 1,
        **observed_values,
    }

    with pytest.raises(
        ValidationError, match="all-null distribution must not include observed values"
    ):
        DatabaseEvidenceSubmission.model_validate(payload)


@pytest.mark.parametrize(
    "observed_values",
    [
        {"distinct_count": 1},
        {"enum_candidates": ["ghost"]},
        {"minimum": 1},
        {"maximum": 1},
    ],
    ids=["distinct-count", "enum-candidates", "minimum", "maximum"],
)
def test_database_distribution_rejects_values_when_every_row_is_null_at_generic_boundary(
    observed_values: dict[str, Any],
) -> None:
    payload = _database_envelope_with_distribution_update(
        {
            "row_count": 10,
            "distinct_count": 0,
            "null_ratio": 1,
            "enum_candidates": [],
            "minimum": None,
            "maximum": None,
            **observed_values,
        },
        nullable=True,
    )

    with pytest.raises(
        ValidationError, match="all-null distribution must not include observed values"
    ):
        ExternalEvidenceEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    "observed_values",
    [
        {"enum_candidates": ["ghost"]},
        {"minimum": 1},
        {"maximum": 1},
    ],
    ids=["enum-candidates", "minimum", "maximum"],
)
def test_database_distribution_rejects_values_when_distinct_count_is_zero_at_dedicated_boundary(
    observed_values: dict[str, Any],
) -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["nullable"] = True
    payload["tables"][0]["columns"][1]["observed_distribution"] = {
        "distinct_count": 0,
        **observed_values,
    }

    with pytest.raises(
        ValidationError, match="zero-distinct distribution must not include observed values"
    ):
        DatabaseEvidenceSubmission.model_validate(payload)


@pytest.mark.parametrize(
    "observed_values",
    [
        {"enum_candidates": ["ghost"]},
        {"minimum": 1},
        {"maximum": 1},
    ],
    ids=["enum-candidates", "minimum", "maximum"],
)
def test_database_distribution_rejects_values_when_distinct_count_is_zero_at_generic_boundary(
    observed_values: dict[str, Any],
) -> None:
    payload = _database_envelope_with_distribution_update(
        {
            "row_count": None,
            "distinct_count": 0,
            "null_ratio": None,
            "enum_candidates": [],
            "minimum": None,
            "maximum": None,
            **observed_values,
        },
        nullable=True,
    )

    with pytest.raises(
        ValidationError, match="zero-distinct distribution must not include observed values"
    ):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_column_rejects_observed_nulls_when_non_nullable_at_dedicated_boundary() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][1]["observed_distribution"]["null_ratio"] = 0.01

    with pytest.raises(ValidationError, match="non-nullable column must not have observed nulls"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_column_rejects_observed_nulls_when_non_nullable_at_generic_boundary() -> None:
    payload = _database_envelope_with_distribution_update({"null_ratio": 0.01})

    with pytest.raises(ValidationError, match="non-nullable column must not have observed nulls"):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_database_column_rejects_nullable_primary_key_at_dedicated_boundary() -> None:
    payload = _database_submission()
    payload["tables"][0]["columns"][0]["nullable"] = True

    with pytest.raises(ValidationError, match="primary key must not be nullable"):
        DatabaseEvidenceSubmission.model_validate(payload)


def test_database_column_rejects_nullable_primary_key_at_generic_boundary() -> None:
    envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    )
    finding_index, finding = next(
        (index, finding)
        for index, finding in enumerate(envelope.findings)
        if isinstance(finding.structured_data, DatabaseExternalEvidenceStructuredData)
        and isinstance(finding.structured_data.claim, ExternalDatabaseColumnClaim)
        and finding.structured_data.claim.primary_key
    )
    structured_data = cast(DatabaseExternalEvidenceStructuredData, finding.structured_data)
    claim = cast(ExternalDatabaseColumnClaim, structured_data.claim)
    changed_claim = claim.model_copy(update={"nullable": True})
    changed_structured_data = structured_data.model_copy(update={"claim": changed_claim})
    provisional = finding.model_copy(
        update={
            "structured_data": changed_structured_data,
            "semantic_fingerprint": "0" * 64,
        }
    )
    changed_finding = provisional.model_copy(
        update={"semantic_fingerprint": finding_semantic_fingerprint(provisional)}
    )
    findings = list(envelope.findings)
    findings[finding_index] = changed_finding
    payload = envelope.model_copy(update={"findings": findings}).model_dump(mode="json")

    with pytest.raises(ValidationError, match="primary key must not be nullable"):
        ExternalEvidenceEnvelope.model_validate(payload)


def test_java_adapter_bounds_finding_ids_without_collisions() -> None:
    payload = _java_submission()
    shared_prefix = "claim" + ("a" * 154)
    payload["claims"][0]["id"] = f"{shared_prefix}x"
    payload["claims"][1]["id"] = f"{shared_prefix}y"

    envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(payload))

    finding_ids = [finding.id for finding in envelope.findings[:2]]
    assert len(finding_ids) == len(set(finding_ids)) == 2
    assert all(len(identifier) == 160 for identifier in finding_ids)
    assert all(identifier.startswith("java-claima") for identifier in finding_ids)


def test_external_structured_contract_rejects_unknown_or_mismatched_claims() -> None:
    envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission()))
    unknown_field = envelope.model_dump(mode="json")
    unknown_field["findings"][0]["structured_data"]["claim"]["unknown_shape"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExternalEvidenceEnvelope.model_validate(unknown_field)

    mismatched_kind = envelope.model_dump(mode="json")
    mismatched_kind["findings"][0]["structured_data"]["claim_kind"] = "dto_field"
    with pytest.raises(ValidationError, match="kind must match"):
        ExternalEvidenceEnvelope.model_validate(mismatched_kind)

    ambiguous_database = _database_submission()
    second_table = json.loads(json.dumps(ambiguous_database["tables"][0]))
    second_table["name"] = "archived_orders"
    ambiguous_database["tables"].append(second_table)
    ambiguous_java = _java_submission()
    _add_archived_order_entity(ambiguous_java)
    java_inputs = _mapping_inputs(
        adapt_java_evidence(JavaEvidenceSubmission.model_validate(ambiguous_java)),
        "java",
    )
    valid_conflict_envelope = with_mapping_conflict_findings(
        adapt_database_evidence(DatabaseEvidenceSubmission.model_validate(ambiguous_database)),
        java_inputs,
    )
    assert (
        with_mapping_conflict_findings(valid_conflict_envelope, java_inputs)
        == valid_conflict_envelope
    )
    conflict_envelope = valid_conflict_envelope.model_dump(mode="json")
    marker = next(
        finding
        for finding in conflict_envelope["findings"]
        if finding["structured_data"].get("adapter") == "entity_mapping"
    )
    marker["semantic_role"] = "normative"
    with pytest.raises(ValidationError, match="mapping markers must be conflict findings"):
        ExternalEvidenceEnvelope.model_validate(conflict_envelope)


def test_derived_mapping_conflict_rejects_existing_finding_id_collision() -> None:
    java_payload = _java_submission()
    _add_archived_order_entity(java_payload)
    java_inputs = _mapping_inputs(
        adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
        "java",
    )
    database_payload = _database_submission()
    second_table = json.loads(json.dumps(database_payload["tables"][0]))
    second_table["name"] = "archived_orders"
    database_payload["tables"].append(second_table)
    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(database_payload)
    )
    expanded = with_mapping_conflict_findings(database_envelope, java_inputs)
    marker = next(finding for finding in expanded.findings if finding.kind.value == "conflict")
    colliding = database_envelope.findings[0].model_copy(
        update={"id": marker.id, "semantic_fingerprint": "0" * 64}
    )
    colliding = colliding.model_copy(
        update={"semantic_fingerprint": finding_semantic_fingerprint(colliding)}
    )
    collision_envelope = database_envelope.model_copy(
        update={"findings": [colliding, *database_envelope.findings[1:]]}
    )

    with pytest.raises(EntityMappingBudgetExceeded, match="finding id collides"):
        with_mapping_conflict_findings(collision_envelope, java_inputs)


def test_external_structured_contract_binds_adapters_to_provider_types() -> None:
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission()))
    mislabeled_java = java_envelope.model_dump(mode="json")
    mislabeled_java["provider"]["type"] = "database"
    with pytest.raises(ValidationError, match="requires a repository provider"):
        ExternalEvidenceEnvelope.model_validate(mislabeled_java)

    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    )
    mislabeled_database = database_envelope.model_dump(mode="json")
    mislabeled_database["provider"]["type"] = "repository"
    with pytest.raises(ValidationError, match="requires a database provider"):
        ExternalEvidenceEnvelope.model_validate(mislabeled_database)

    database_finding = database_envelope.findings[0].model_copy(
        update={
            "source_ref": java_envelope.source.ref,
            "source_revision": java_envelope.source.revision,
            "subject_ref": java_envelope.subject_ref,
            "semantic_fingerprint": "0" * 64,
        }
    )
    database_finding = database_finding.model_copy(
        update={"semantic_fingerprint": finding_semantic_fingerprint(database_finding)}
    )
    mixed = java_envelope.model_dump(mode="json")
    mixed["findings"].append(database_finding.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="must not be mixed"):
        ExternalEvidenceEnvelope.model_validate(mixed)


def test_entity_mapping_candidates_are_traceable_and_ambiguity_is_never_selected() -> None:
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission()))
    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    )
    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(java_envelope, "java"),
            *_mapping_inputs(database_envelope, "database"),
        ]
    )

    kinds = {candidate.kind for candidate in mapping.candidates}
    assert kinds >= {
        EntityMappingCandidateKind.OPERATION_ENTITY,
        EntityMappingCandidateKind.REQUEST_FIELD_COLUMN,
        EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN,
        EntityMappingCandidateKind.OPERATION_STATE,
    }
    assert all(candidate.evidence_refs for candidate in mapping.candidates)
    assert all(candidate.selection_status.value == "proposed" for candidate in mapping.candidates)
    assert mapping.conflicts == []

    ambiguous_database = _database_submission()
    second_table = json.loads(json.dumps(ambiguous_database["tables"][0]))
    second_table["name"] = "archived_orders"
    ambiguous_database["tables"].append(second_table)
    ambiguous_java = _java_submission()
    _add_archived_order_entity(ambiguous_java)
    ambiguous = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(ambiguous_java)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(ambiguous_database)
                ),
                "database-ambiguous",
            ),
        ]
    )

    assert ambiguous.conflicts
    conflicted_ids = {
        candidate_id for conflict in ambiguous.conflicts for candidate_id in conflict.candidate_ids
    }
    assert conflicted_ids
    assert all(
        candidate.selection_status.value == "proposed"
        for candidate in ambiguous.candidates
        if candidate.id in conflicted_ids
    )


def test_entity_mapping_ids_stay_stable_and_merge_corroborating_evidence() -> None:
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission()))
    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    )
    original_inputs = [
        *_mapping_inputs(java_envelope, "java"),
        *_mapping_inputs(database_envelope, "database"),
    ]
    original = derive_entity_mapping(original_inputs)
    corroborated = derive_entity_mapping(
        [
            *original_inputs,
            *_mapping_inputs(java_envelope, "java-corroborating"),
            *_mapping_inputs(database_envelope, "database-corroborating"),
        ]
    )

    assert {candidate.id for candidate in corroborated.candidates} == {
        candidate.id for candidate in original.candidates
    }
    assert len(corroborated.candidates) == len(original.candidates)
    assert all(len(candidate.evidence_refs) >= 4 for candidate in corroborated.candidates)


def test_database_state_mapping_preserves_low_confidence_and_nondeterminism() -> None:
    database_payload = _database_submission()
    database_payload["confidence"] = 0.25
    database_payload["deterministic"] = False
    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission())),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    state = next(
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_STATE
        and candidate.target_ref.startswith("state-set://public/orders/status")
    )
    assert state.confidence == 0.25
    assert state.deterministic is False
    database_backed = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind
        in {
            EntityMappingCandidateKind.OPERATION_ENTITY,
            EntityMappingCandidateKind.REQUEST_FIELD_COLUMN,
            EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN,
        }
    ]
    assert database_backed
    assert all(candidate.confidence <= 0.25 for candidate in database_backed)
    assert all(candidate.deterministic is False for candidate in database_backed)


def test_database_boolean_state_values_corroborate_json_style_java_values() -> None:
    java_payload = _java_submission()
    java_state = next(claim for claim in java_payload["claims"] if claim["kind"] == "enum_state")
    java_state["values"] = ["false", "true"]
    database_payload = _database_submission()
    status_column = next(
        column for column in database_payload["tables"][0]["columns"] if column["name"] == "status"
    )
    status_column["enum_values"] = [False, True]
    status_column["observed_distribution"]["enum_candidates"] = [False, True]

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    states = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_STATE
    ]
    assert len(states) == 1
    assert states[0].state_values == ["false", "true"]
    assert not any(
        conflict.kind is EntityMappingCandidateKind.OPERATION_STATE
        for conflict in mapping.conflicts
    )


def test_database_state_corroborates_each_dto_direction_independently() -> None:
    java_payload = _java_submission()
    java_payload["claims"] = [
        claim for claim in java_payload["claims"] if claim["kind"] != "enum_state"
    ]
    common = {
        "kind": "enum_state",
        "source_path": "src/OrderStatus.java:3",
        "confidence": 0.96,
        "deterministic": True,
        "operation_ref": "operation://POST/api/orders",
        "field_name": "status",
    }
    java_payload["claims"].extend(
        [
            {
                **common,
                "id": "request-state",
                "enum_ref": "java://CreateOrderStatus",
                "direction": "request",
                "dto_type": "CreateOrderRequest",
                "values": ["requested"],
            },
            {
                **common,
                "id": "response-state",
                "enum_ref": "java://OrderStatus",
                "direction": "response",
                "dto_type": "OrderDto",
                "values": ["created", "cancelled"],
            },
        ]
    )

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java-directional",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(_database_submission())
                ),
                "database-directional",
            ),
        ]
    )

    states = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_STATE
    ]
    assert len(states) == 2
    request_state = next(candidate for candidate in states if "/request/" in candidate.source_ref)
    response_state = next(candidate for candidate in states if "/response/" in candidate.source_ref)
    assert request_state.target_ref == "state-set://CreateOrderStatus"
    assert request_state.state_values == ["requested"]
    assert response_state.target_ref == "state-set://public/orders/status"
    assert response_state.state_values == ["cancelled", "created"]
    assert any("database-directional" in ref for ref in response_state.evidence_refs)
    assert any("java-directional" in ref for ref in response_state.evidence_refs)
    assert not [
        conflict
        for conflict in mapping.conflicts
        if conflict.kind is EntityMappingCandidateKind.OPERATION_STATE
    ]


def test_database_normative_and_observed_state_sets_remain_conflicting_candidates() -> None:
    java_payload = _java_submission()
    java_payload["claims"] = [
        claim for claim in java_payload["claims"] if claim["kind"] != "enum_state"
    ]
    database_payload = _database_submission()
    status_column = next(
        column for column in database_payload["tables"][0]["columns"] if column["name"] == "status"
    )
    status_column["enum_values"] = ["open", "closed"]
    status_column["observed_distribution"]["enum_candidates"] = ["broken"]

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    states = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_STATE
    ]
    assert {tuple(candidate.state_values) for candidate in states} == {
        ("closed", "open"),
        ("broken",),
    }
    conflict = next(
        conflict
        for conflict in mapping.conflicts
        if conflict.kind is EntityMappingCandidateKind.OPERATION_STATE
    )
    assert set(conflict.candidate_ids) == {candidate.id for candidate in states}


def test_differing_state_values_conflict_even_when_target_ref_matches() -> None:
    java_payload = _java_submission()
    first_state = next(claim for claim in java_payload["claims"] if claim["kind"] == "enum_state")
    second_state = json.loads(json.dumps(first_state))
    second_state["id"] = "state-order-revised"
    second_state["values"] = ["created", "refunded"]
    java_payload["claims"].append(second_state)

    mapping = derive_entity_mapping(
        _mapping_inputs(
            adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
            "java",
        )
    )

    state_candidates = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_STATE
    ]
    assert len(state_candidates) == 2
    assert len({candidate.target_ref for candidate in state_candidates}) == 1
    state_conflict = next(
        conflict
        for conflict in mapping.conflicts
        if conflict.kind is EntityMappingCandidateKind.OPERATION_STATE
    )
    assert set(state_conflict.candidate_ids) == {candidate.id for candidate in state_candidates}


def test_operation_entity_mapping_preserves_entity_nondeterminism() -> None:
    java_payload = _java_submission()
    java_payload["confidence"] = 1
    route = next(claim for claim in java_payload["claims"] if claim["kind"] == "controller_route")
    route["confidence"] = 1
    entity = next(claim for claim in java_payload["claims"] if claim["kind"] == "entity")
    entity["confidence"] = 1
    entity["deterministic"] = False

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(_database_submission())
                ),
                "database",
            ),
        ]
    )

    operation_entity = next(
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.target_ref == "entity://public/orders"
    )
    assert operation_entity.deterministic is False


def test_operation_entity_mapping_aggregates_all_exact_entity_evidence() -> None:
    java_payload = _java_submission()
    second_entity = json.loads(
        json.dumps(next(claim for claim in java_payload["claims"] if claim["kind"] == "entity"))
    )
    second_entity.update(
        {
            "id": "entity-order-secondary",
            "entity_ref": "entity://OrderSecondary",
            "class_name": "OrderSecondary",
            "confidence": 0.4,
            "deterministic": False,
        }
    )
    java_payload["claims"].append(second_entity)
    java_inputs = _mapping_inputs(
        adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
        "java",
    )
    entity_evidence_refs = {
        item.evidence_ref
        for item in java_inputs
        if isinstance(item.finding.structured_data, JavaExternalEvidenceStructuredData)
        and item.finding.structured_data.claim_kind == "entity"
    }

    mapping = derive_entity_mapping(
        [
            *java_inputs,
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(_database_submission())
                ),
                "database",
            ),
        ]
    )

    operation_entity = next(
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.target_ref == "entity://public/orders"
    )
    assert entity_evidence_refs <= set(operation_entity.evidence_refs)
    assert operation_entity.confidence == 0.4
    assert operation_entity.deterministic is False


def test_operation_entity_mapping_matches_dotted_schema_table_reference() -> None:
    java_payload = _java_submission()
    operation_ref = "operation://POST/api/purchases"
    route = next(claim for claim in java_payload["claims"] if claim["kind"] == "controller_route")
    route["operation_ref"] = operation_ref
    route["path"] = "/api/purchases"
    entity = next(claim for claim in java_payload["claims"] if claim["kind"] == "entity")
    entity["class_name"] = "PurchaseRecord"
    entity["table_ref"] = "table://public.orders"
    entity["operation_refs"] = [operation_ref]
    database_payload = _database_submission()
    other_schema = json.loads(json.dumps(database_payload["tables"][0]))
    other_schema["schema_name"] = "private"
    database_payload["tables"].append(other_schema)

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    assert any(
        candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.operation_ref == operation_ref
        and candidate.target_ref == "entity://public/orders"
        for candidate in mapping.candidates
    )
    assert not any(
        candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.target_ref == "entity://private/orders"
        for candidate in mapping.candidates
    )


def test_operation_entity_mapping_uses_resource_before_action_suffix() -> None:
    java_payload = _java_submission()
    route = next(claim for claim in java_payload["claims"] if claim["kind"] == "controller_route")
    route["operation_ref"] = "operation://POST/system/user/add"
    route["path"] = "/system/user/add"
    entity = next(claim for claim in java_payload["claims"] if claim["kind"] == "entity")
    entity["class_name"] = "SysUser"
    entity["entity_ref"] = "entity://SysUser"
    entity["table_ref"] = "table://public/sys_user"
    entity["operation_refs"] = []
    java_payload["claims"] = [route, entity]

    database_payload = _database_submission()
    database_payload["tables"][0]["name"] = "sys_user"

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java-action-route",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database-action-route",
            ),
        ]
    )

    assert any(
        candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.operation_ref == "operation://POST/system/user/add"
        and candidate.target_ref == "entity://public/sys_user"
        for candidate in mapping.candidates
    )


def test_unscoped_exact_entities_still_require_route_correlation() -> None:
    java_payload = _java_submission()
    order_entity = next(claim for claim in java_payload["claims"] if claim["kind"] == "entity")
    order_entity["operation_refs"] = []
    java_payload["claims"].append(
        {
            "id": "entity-user",
            "kind": "entity",
            "source_path": "src/User.java:4",
            "confidence": 0.96,
            "deterministic": True,
            "entity_ref": "entity://User",
            "class_name": "User",
            "table_ref": "table://public/users",
            "operation_refs": [],
        }
    )
    database_payload = _database_submission()
    users_table = json.loads(json.dumps(database_payload["tables"][0]))
    users_table["name"] = "users"
    database_payload["tables"].append(users_table)

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    operation_entities = {
        candidate.target_ref
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.operation_ref == "operation://POST/api/orders"
    }
    assert operation_entities == {"entity://public/orders"}


def test_explicit_operation_entity_disables_route_table_fallback() -> None:
    database_payload = _database_submission()
    route_suffix_table = json.loads(json.dumps(database_payload["tables"][0]))
    route_suffix_table["name"] = "customer_orders"
    database_payload["tables"].append(route_suffix_table)

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission())),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    operation_entities = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.operation_ref == "operation://POST/api/orders"
    ]
    assert {candidate.target_ref for candidate in operation_entities} == {"entity://public/orders"}
    assert not any(
        conflict.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        for conflict in mapping.conflicts
    )


def test_database_table_finding_independently_drives_traceable_entity_mapping() -> None:
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission()))
    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    )
    table_finding = next(
        finding
        for finding in database_envelope.findings
        if isinstance(finding.structured_data, DatabaseExternalEvidenceStructuredData)
        and finding.structured_data.claim_kind == "table"
    )
    table_only = database_envelope.model_copy(update={"findings": [table_finding]})
    table_input = _mapping_inputs(table_only, "database-table")[0]

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(java_envelope, "java"),
            table_input,
        ]
    )

    operation_entity = next(
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.target_ref == "entity://public/orders"
    )
    assert table_input.evidence_ref in operation_entity.evidence_refs
    assert not any(
        candidate.kind
        in {
            EntityMappingCandidateKind.REQUEST_FIELD_COLUMN,
            EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN,
        }
        for candidate in mapping.candidates
    )


def test_operation_entity_fallback_excludes_entities_scoped_elsewhere() -> None:
    java_payload = _java_submission()
    route = next(claim for claim in java_payload["claims"] if claim["kind"] == "controller_route")
    route["operation_ref"] = "operation://POST/api/purchases"
    route["path"] = "/api/purchases"

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(_database_submission())
                ),
                "database",
            ),
        ]
    )

    assert not any(
        candidate.kind is EntityMappingCandidateKind.OPERATION_ENTITY
        and candidate.operation_ref == "operation://POST/api/purchases"
        for candidate in mapping.candidates
    )


def test_field_mapping_excludes_table_column_claims_scoped_to_other_operations() -> None:
    java_payload = _java_submission()
    operation_ref = "operation://POST/api/purchases"
    route = next(claim for claim in java_payload["claims"] if claim["kind"] == "controller_route")
    route["operation_ref"] = operation_ref
    route["path"] = "/api/purchases"
    for field in (claim for claim in java_payload["claims"] if claim["kind"] == "dto_field"):
        field["operation_ref"] = operation_ref

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(_database_submission())
                ),
                "database",
            ),
        ]
    )

    assert not any(
        candidate.kind
        in {
            EntityMappingCandidateKind.REQUEST_FIELD_COLUMN,
            EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN,
        }
        and candidate.operation_ref == operation_ref
        for candidate in mapping.candidates
    )


def test_field_mapping_does_not_escape_unmatched_explicit_entity_scope() -> None:
    java_payload = _java_submission()
    entity = next(claim for claim in java_payload["claims"] if claim["kind"] == "entity")
    entity["class_name"] = "PrivateOrder"
    entity["table_ref"] = "table://private/orders"

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(_database_submission())
                ),
                "database",
            ),
        ]
    )

    assert not any(
        candidate.kind
        in {
            EntityMappingCandidateKind.REQUEST_FIELD_COLUMN,
            EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN,
        }
        and candidate.operation_ref == "operation://POST/api/orders"
        for candidate in mapping.candidates
    )


def test_explicit_table_column_claim_drives_differently_named_field_mapping() -> None:
    java_payload = _java_submission()
    field = next(claim for claim in java_payload["claims"] if claim["id"] == "request-product")
    field["field_name"] = "userName"
    table_column = next(
        claim for claim in java_payload["claims"] if claim["id"] == "column-product"
    )
    table_column.update(
        {
            "field_name": "userName",
            "column_name": "login_name",
            "confidence": 0.4,
            "deterministic": False,
        }
    )
    database_payload = _database_submission()
    database_column = next(
        column
        for column in database_payload["tables"][0]["columns"]
        if column["name"] == "product_id"
    )
    database_column["name"] = "login_name"

    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload))
    java_inputs = _mapping_inputs(java_envelope, "java")
    table_column_evidence = next(
        item.evidence_ref
        for item in java_inputs
        if isinstance(item.finding.structured_data, JavaExternalEvidenceStructuredData)
        and item.finding.structured_data.claim_kind == "table_column"
    )
    mapping = derive_entity_mapping(
        [
            *java_inputs,
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    candidate = next(
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.REQUEST_FIELD_COLUMN
        and candidate.target_ref == "column://public/orders/login_name"
    )
    assert table_column_evidence in candidate.evidence_refs
    assert candidate.confidence == 0.4
    assert candidate.deterministic is False


def test_operation_state_mapping_scopes_independent_fields() -> None:
    java_payload = _java_submission()
    operation_ref = "operation://POST/api/orders"
    java_payload["claims"].append(
        {
            "id": "state-payment",
            "kind": "enum_state",
            "source_path": "src/PaymentStatus.java:3",
            "confidence": 0.96,
            "deterministic": True,
            "operation_ref": operation_ref,
            "enum_ref": "java://PaymentStatus",
            "field_name": "paymentStatus",
            "values": ["pending", "paid"],
        }
    )
    database_payload = _database_submission()
    database_payload["tables"][0]["columns"].append(
        {
            "name": "payment_status",
            "data_type": "varchar",
            "nullable": False,
            "enum_values": ["pending", "paid"],
        }
    )

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    states = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_STATE
    ]
    assert {candidate.target_ref for candidate in states} == {
        "state-set://public/orders/status",
        "state-set://public/orders/payment_status",
    }
    assert len({candidate.source_ref for candidate in states}) == 2
    assert all(candidate.field_ref is not None for candidate in states)
    assert not any(
        conflict.kind is EntityMappingCandidateKind.OPERATION_STATE
        for conflict in mapping.conflicts
    )


def test_database_state_sets_at_budget_remain_separate_without_truncation() -> None:
    java_payload = _java_submission()
    java_payload["claims"] = [
        claim for claim in java_payload["claims"] if claim["kind"] != "enum_state"
    ]
    database_payload = _database_submission()
    status = next(
        column for column in database_payload["tables"][0]["columns"] if column["name"] == "status"
    )
    status["enum_values"] = [f"declared-{index:03d}" for index in range(100)]
    status["observed_distribution"]["enum_candidates"] = [
        f"observed-{index:03d}" for index in range(100)
    ]
    status["observed_distribution"]["distinct_count"] = 100

    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    states = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.OPERATION_STATE
    ]
    assert len(states) == 2
    assert {len(candidate.state_values) for candidate in states} == {100}
    conflict = next(
        conflict
        for conflict in mapping.conflicts
        if conflict.kind is EntityMappingCandidateKind.OPERATION_STATE
    )
    assert set(conflict.candidate_ids) == {candidate.id for candidate in states}


def test_dependent_mappings_preserve_heuristic_operation_table_reliability() -> None:
    java_payload = _java_submission()
    java_payload["claims"] = [
        claim for claim in java_payload["claims"] if claim["kind"] != "entity"
    ]
    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(_database_submission())
                ),
                "database",
            ),
        ]
    )

    dependent = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind
        in {
            EntityMappingCandidateKind.REQUEST_FIELD_COLUMN,
            EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN,
            EntityMappingCandidateKind.OPERATION_STATE,
        }
        and "/public/orders/" in candidate.target_ref
    ]
    assert dependent
    assert all(candidate.confidence <= 0.75 for candidate in dependent)
    assert all(candidate.deterministic is False for candidate in dependent)


def test_reused_dto_field_is_scoped_to_each_operation() -> None:
    java_payload = _two_operation_java_submission()
    database_payload = _two_table_database_submission()
    mapping = derive_entity_mapping(
        [
            *_mapping_inputs(
                adapt_java_evidence(JavaEvidenceSubmission.model_validate(java_payload)),
                "java",
            ),
            *_mapping_inputs(
                adapt_database_evidence(
                    DatabaseEvidenceSubmission.model_validate(database_payload)
                ),
                "database",
            ),
        ]
    )

    field_candidates = [
        candidate
        for candidate in mapping.candidates
        if candidate.kind is EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN
    ]
    assert len(field_candidates) == 2
    assert len({candidate.source_ref for candidate in field_candidates}) == 2
    assert not any(
        conflict.kind is EntityMappingCandidateKind.RESPONSE_FIELD_COLUMN
        for conflict in mapping.conflicts
    )


def test_candidate_budget_counts_unique_candidates_after_deduplication() -> None:
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission()))
    database_envelope = adapt_database_evidence(
        DatabaseEvidenceSubmission.model_validate(_database_submission())
    )
    field = next(
        finding
        for finding in java_envelope.findings
        if isinstance(finding.structured_data, JavaExternalEvidenceStructuredData)
        and finding.structured_data.claim_kind == "dto_field"
        and finding.structured_data.claim.field_name == "productId"
    )
    column = next(
        finding
        for finding in database_envelope.findings
        if isinstance(finding.structured_data, DatabaseExternalEvidenceStructuredData)
        and isinstance(finding.structured_data.claim, ExternalDatabaseColumnClaim)
        and finding.structured_data.claim.name == "product_id"
    )

    mapping = derive_entity_mapping(
        [
            *[
                MappingEvidenceInput(
                    evidence_ref=f"evidence://field/{index}",
                    finding=field,
                    confidence=0.3 if index == 0 else 0.9,
                )
                for index in range(32)
            ],
            *[
                MappingEvidenceInput(evidence_ref=f"evidence://column/{index}", finding=column)
                for index in range(32)
            ],
        ]
    )

    assert len(mapping.candidates) == 1
    assert len(mapping.candidates[0].evidence_refs) == 20
    assert mapping.candidates[0].confidence == pytest.approx(0.3)


def test_entity_mapping_rejects_unrepresentable_evidence_volume() -> None:
    java_envelope = adapt_java_evidence(JavaEvidenceSubmission.model_validate(_java_submission()))
    route = next(
        finding
        for finding in java_envelope.findings
        if isinstance(finding.structured_data, JavaExternalEvidenceStructuredData)
        and finding.structured_data.claim_kind == "controller_route"
    )

    with pytest.raises(EntityMappingBudgetExceeded, match="evidence budget"):
        derive_entity_mapping(
            [
                MappingEvidenceInput(
                    evidence_ref=f"evidence://route/{index}",
                    finding=route,
                )
                for index in range(501)
            ]
        )


def test_python_provider_bundle_remains_compatible_with_context_adapter() -> None:
    bundle = PythonSourceEvidenceProvider().analyze(
        SourceSnapshot.model_validate(
            {
                "repository_url": "https://example.test/orders.git",
                "commit": "a1b2c3d4",
                "allowlist_paths": ["app"],
                "files": [
                    {
                        "path": "app/routes.py",
                        "language": "python",
                        "content": '@router.post("/orders")\ndef create_order():\n    return {}\n',
                    }
                ],
            }
        )
    )

    envelope = adapt_evidence_bundle(
        bundle,
        provider_name="python-source-provider",
        provider_version="1.0.0",
        source_ref="repository://orders-python",
        source_revision="a1b2c3d4",
        subject_ref=SUBJECT_REF,
    )

    assert envelope.provider.type.value == "repository"
    structured_data = envelope.findings[0].structured_data
    assert isinstance(structured_data, EvidenceBundleExternalEvidenceStructuredData)
    assert structured_data.claim.kind == "route"
    assert len(structured_data.claim.structured_data_fingerprint) == 64


@pytest.mark.parametrize(
    ("source_type", "provider_type"),
    [
        ("service_topology", "service_topology"),
        ("workflow", "workflow"),
        ("change", "change"),
    ],
)
def test_evidence_bundle_adapter_preserves_supporting_semantics(
    source_type: str,
    provider_type: str,
) -> None:
    bundle = EvidenceBundle.model_validate(
        {
            "subject_ref": SUBJECT_REF,
            "findings": [
                {
                    "id": f"{source_type}-finding",
                    "source_type": source_type,
                    "source_ref": f"evidence://{source_type}",
                    "subject_ref": SUBJECT_REF,
                    "kind": "knowledge",
                    "path": "$.orders",
                    "structured_data": {"component": "orders"},
                    "confidence": 0.9,
                    "deterministic": True,
                    "revision": "fixture-v1",
                }
            ],
        }
    )

    envelope = adapt_evidence_bundle(
        bundle,
        provider_name="bundle-provider",
        provider_version="1.0.0",
        source_ref=f"evidence://{source_type}",
        source_revision="fixture-v1",
        subject_ref=SUBJECT_REF,
    )

    assert bundle.findings[0].as_ref().semantic_role == "supporting"
    assert envelope.findings[0].semantic_role.value == "supporting"
    assert envelope.provider.type.value == provider_type


def test_evidence_bundle_rejects_sensitive_path_and_warning_metadata() -> None:
    sensitive_value = "13800138000"

    def payload() -> dict[str, Any]:
        return {
            "subject_ref": SUBJECT_REF,
            "findings": [
                {
                    "id": "profile-finding",
                    "source_type": "data_profile",
                    "source_ref": "database://orders",
                    "subject_ref": SUBJECT_REF,
                    "kind": "column_profile",
                    "path": "$.orders.id",
                    "structured_data": {"nullable": False},
                    "confidence": 0.9,
                    "deterministic": True,
                    "revision": "profile-v1",
                    "warnings": [],
                }
            ],
            "warnings": [],
        }

    sensitive_path = payload()
    sensitive_path["findings"][0]["path"] = f"$.customers.{sensitive_value}"
    with pytest.raises(ValidationError, match="sensitive"):
        EvidenceBundle.model_validate(sensitive_path)

    sensitive_finding_warning = payload()
    sensitive_finding_warning["findings"][0]["warnings"] = [f"customer {sensitive_value}"]
    with pytest.raises(ValidationError, match="sensitive"):
        EvidenceBundle.model_validate(sensitive_finding_warning)

    sensitive_bundle_warning = payload()
    sensitive_bundle_warning["warnings"] = [f"customer {sensitive_value}"]
    with pytest.raises(ValidationError, match="sensitive"):
        EvidenceBundle.model_validate(sensitive_bundle_warning)

    sensitive_kind = payload()
    sensitive_kind["findings"][0]["kind"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive"):
        EvidenceBundle.model_validate(sensitive_kind)

    safe_bundle = EvidenceBundle.model_validate(payload())
    unsafe_finding = safe_bundle.findings[0].model_copy(
        update={"path": f"$.customers.{sensitive_value}"}
    )
    unsafe_bundle = safe_bundle.model_copy(update={"findings": [unsafe_finding]})
    with pytest.raises(ValueError, match="sensitive scalar"):
        adapt_evidence_bundle(
            unsafe_bundle,
            provider_name="profile-provider",
            provider_version="1.0.0",
            source_ref="database://orders",
            source_revision="profile-v1",
            subject_ref=SUBJECT_REF,
        )

    safe_envelope = adapt_evidence_bundle(
        safe_bundle,
        provider_name="profile-provider",
        provider_version="1.0.0",
        source_ref="database://orders",
        source_revision="profile-v1",
        subject_ref=SUBJECT_REF,
    )
    for field_name, value in (
        ("path", f"$.customers.{sensitive_value}"),
        ("warnings", [f"customer {sensitive_value}"]),
    ):
        generic = safe_envelope.model_dump(mode="json")
        generic["findings"][0]["structured_data"]["claim"][field_name] = value
        with pytest.raises(ValidationError, match="sensitive scalar"):
            ExternalEvidenceEnvelope.model_validate(generic)

    sensitive_kinds = safe_envelope.model_dump(mode="json")
    structured_data = sensitive_kinds["findings"][0]["structured_data"]
    structured_data["claim_kind"] = sensitive_value
    structured_data["claim"]["kind"] = sensitive_value
    with pytest.raises(ValidationError, match="sensitive scalar"):
        ExternalEvidenceEnvelope.model_validate(sensitive_kinds)


def test_evidence_bundle_adapter_rejects_mixed_source_semantics() -> None:
    mixed_bundle = EvidenceBundle.model_validate(
        {
            "subject_ref": SUBJECT_REF,
            "findings": [
                {
                    "id": "contract-finding",
                    "source_type": "contract",
                    "source_ref": "contract://orders",
                    "subject_ref": SUBJECT_REF,
                    "kind": "schema",
                    "path": "$.components.schemas.Order",
                    "structured_data": {"required": ["id"]},
                    "confidence": 1,
                    "deterministic": True,
                    "revision": "contract-v1",
                },
                {
                    "id": "profile-finding",
                    "source_type": "data_profile",
                    "source_ref": "database://orders",
                    "subject_ref": SUBJECT_REF,
                    "kind": "column_profile",
                    "path": "$.orders.id",
                    "structured_data": {"nullable": False},
                    "confidence": 0.9,
                    "deterministic": True,
                    "revision": "profile-v1",
                },
            ],
        }
    )

    with pytest.raises(ValueError, match="one source type"):
        adapt_evidence_bundle(
            mixed_bundle,
            provider_name="mixed-provider",
            provider_version="1.0.0",
            source_ref="evidence://mixed",
            source_revision="mixed-v1",
            subject_ref=SUBJECT_REF,
        )

    contract_bundle = mixed_bundle.model_copy(update={"findings": [mixed_bundle.findings[0]]})
    contract_envelope = adapt_evidence_bundle(
        contract_bundle,
        provider_name="contract-provider",
        provider_version="1.0.0",
        source_ref="contract://orders",
        source_revision="contract-v1",
        subject_ref=SUBJECT_REF,
    )
    contract_finding = contract_envelope.findings[0]
    contract_data = cast(
        EvidenceBundleExternalEvidenceStructuredData, contract_finding.structured_data
    )
    profile_data = contract_data.model_copy(
        update={
            "claim": contract_data.claim.model_copy(
                update={"id": "profile-finding", "source_type": "data_profile"}
            )
        }
    )
    provisional = contract_finding.model_copy(
        update={
            "id": "bundle-profile-finding",
            "structured_data": profile_data,
            "semantic_fingerprint": "0" * 64,
        }
    )
    profile_finding = provisional.model_copy(
        update={"semantic_fingerprint": finding_semantic_fingerprint(provisional)}
    )
    generic_payload = contract_envelope.model_copy(
        update={"findings": [contract_finding, profile_finding]}
    ).model_dump(mode="json")

    with pytest.raises(ValidationError, match="one source type"):
        ExternalEvidenceEnvelope.model_validate(generic_payload)


def test_java_spring_poc_analyzes_fixed_fixture_without_execution() -> None:
    manifest = cast(
        dict[str, Any],
        json.loads((FIXTURE_ROOT / "small-spring" / "manifest.json").read_text()),
    )
    snapshot = JavaSourceSnapshot.model_validate(
        {
            "provider": {"name": "java-spring-poc", "version": "0.1.0"},
            "source": {"ref": "repository://small-spring", "revision": "fixture-v1"},
            "subject_ref": SUBJECT_REF,
            "files": [
                {
                    "path": relative_path,
                    "content": (FIXTURE_ROOT / "small-spring" / relative_path).read_text(),
                }
                for relative_path in manifest["files"]
                if relative_path.endswith(".java")
            ],
        }
    )

    evidence = JavaSpringPocProvider().analyze(snapshot)

    assert snapshot.execute_analyzed_code is False
    assert {
        (claim.method, claim.path) for claim in evidence.claims if claim.kind == "controller_route"
    } == {("POST", "/api/orders"), ("GET", "/api/orders/{id}")}
    assert {claim.field_name for claim in evidence.claims if claim.kind == "dto_field"} >= {
        "productId",
        "quantity",
        "id",
        "status",
    }
    assert any(claim.kind == "service_call" for claim in evidence.claims)


def test_java_spring_poc_captures_declared_method_exceptions() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://declared-errors", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
@RequestMapping("/api")
public class OrderController {
    @GetMapping("/orders/{id}")
    public Order getOrder() throws example.OrderMissingException, IllegalStateException {
        return orderService.getOrder();
    }
}
""",
                    }
                ],
            }
        )
    )

    assert {claim.exception_type for claim in evidence.claims if claim.kind == "exception"} == {
        "IllegalStateException",
        "OrderMissingException",
    }


def test_java_spring_poc_ignores_braces_in_strings_and_comments() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://brace-literals", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
@RequestMapping("/api")
public class OrderController {
    @GetMapping("/first")
    public Order first() {
        String marker = "}"; // }
        return firstService.load();
    }

    @GetMapping("/second")
    public Order second() {
        String marker = "{"; // {
        /* ignored } and { */
        return secondService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    calls = {
        (claim.operation_ref, claim.callee_ref)
        for claim in evidence.claims
        if claim.kind == "service_call"
    }
    assert calls == {
        ("operation://GET/api/first", "java://firstService.load"),
        ("operation://GET/api/second", "java://secondService.load"),
    }


def test_java_spring_poc_parses_balanced_annotated_record_components() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://annotated-record", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/UserController.java",
                        "content": """
@RestController
public class UserController {
    @GetMapping("/users")
    public UserDto getUser() {
        return userService.getUser();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/UserDto.java",
                        "content": """
public record UserDto(
    @NotBlank(message = "required") String name,
    Map<String, Integer> counts,
    int age
) {}
""",
                    },
                ],
            }
        )
    )

    response_fields = {
        (claim.field_name, claim.field_type)
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    }
    assert response_fields == {
        ("name", "String"),
        ("counts", "Map<String, Integer>"),
        ("age", "int"),
    }


def test_java_spring_poc_ignores_route_annotations_in_non_code_text() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://active-routes", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
@RequestMapping("/api")
// @RequestMapping("/shadow")
public class OrderController {
    private static final String SAMPLE = "@GetMapping(\"/string\")";

    // @GetMapping("/old")
    public Order helper() {
        return helperService.load();
    }

    @GetMapping("/live")
    // public Order removed() {
    public Order live() {
        return liveService.load();
    }

    static class NestedController {
        @GetMapping("/nested")
        public Order nested() {
            return nestedService.load();
        }
    }
}

class SecondaryController {
    @GetMapping("/secondary")
    public Order secondary() {
        return secondaryService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    assert [(claim.handler, claim.path) for claim in routes] == [("live", "/api/live")]


def test_java_spring_poc_requires_controller_annotations() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://controller-selection", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/AnnotatedController.java",
                        "content": """
class HelperBeforeAnnotated {}

@RestController
@RequestMapping("/annotated")
class ActualController {
    @GetMapping("/live")
    public Order live() { return service.load(); }
}
""",
                    },
                    {
                        "path": "src/main/java/example/FallbackController.java",
                        "content": """
class HelperBeforeNamed {}

class FallbackController {
    @GetMapping("/fallback")
    public Order fallback() { return service.load(); }
}
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    assert {(claim.controller_ref, claim.handler, claim.path) for claim in routes} == {
        ("java://ActualController", "live", "/annotated/live"),
    }


def test_java_spring_poc_resolves_local_controller_interface_mappings() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://controller-interface", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrdersApi.java",
                        "content": """
@RequestMapping("/api")
interface OrdersApi {
    @PostMapping("/orders")
    Order create(@RequestBody CreateOrderRequest request) throws OrderException;
}

class CreateOrderRequest {
    @NotNull
    String name;
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController implements OrdersApi {
    @Override
    public Order create(CreateOrderRequest request) throws OrderException {
        if (request == null) {
            throw new OrderException();
        }
        kafkaTemplate.send("orders.created", request);
        return orderService.create(request);
    }
}
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    request_fields = [
        claim
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "request"
    ]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    exceptions = [claim for claim in evidence.claims if claim.kind == "exception"]
    events = [claim for claim in evidence.claims if claim.kind == "kafka_event"]
    assert [
        (claim.controller_ref, claim.handler, claim.method, claim.path) for claim in routes
    ] == [("java://OrderController", "create", "POST", "/api/orders")]
    assert [(claim.dto_type, claim.field_name) for claim in request_fields] == [
        ("CreateOrderRequest", "name")
    ]
    assert [claim.callee_ref for claim in calls] == ["java://orderService.create"]
    assert [claim.exception_type for claim in exceptions] == ["OrderException"]
    assert [(claim.direction, claim.topic_ref) for claim in events] == [
        ("produce", "kafka://orders.created")
    ]


def test_java_spring_poc_deduplicates_repeated_interface_mapping_on_implementation() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {
                    "ref": "repository://repeated-interface-route",
                    "revision": "fixture-v1",
                },
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrdersApi.java",
                        "content": """
interface OrdersApi {
    @GetMapping("/orders")
    Order load();
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController implements OrdersApi {
    @GetMapping("/orders")
    public Order load() { return orderService.load(); }
}
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    assert [(claim.handler, claim.method, claim.path) for claim in routes] == [
        ("load", "GET", "/orders")
    ]


def test_java_spring_poc_applies_controller_prefix_to_interface_mapping() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {
                    "ref": "repository://prefixed-interface-route",
                    "revision": "fixture-v1",
                },
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrdersApi.java",
                        "content": """
interface OrdersApi {
    @GetMapping("/orders")
    Order load();
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
@RequestMapping("/v1")
class OrderController implements OrdersApi {
    public Order load() { return orderService.load(); }
}
""",
                    },
                ],
            }
        )
    )

    route = next(claim for claim in evidence.claims if claim.kind == "controller_route")
    assert (route.path, route.operation_ref) == ("/v1/orders", "operation://GET/v1/orders")


def test_java_spring_poc_matches_interface_overloads_by_parameter_type() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://interface-overload", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrdersApi.java",
                        "content": """
interface OrdersApi {
    @GetMapping("/orders/{id}")
    Order find(String id);
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController implements OrdersApi {
    public Order find(Integer id) { return integerService.find(id); }

    public Order find(String id) { return stringService.find(id); }
}
""",
                    },
                ],
            }
        )
    )

    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [claim.callee_ref for claim in calls] == ["java://stringService.find"]


def test_java_spring_poc_preserves_container_types_for_interface_overloads() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {
                    "ref": "repository://interface-container-overload",
                    "revision": "fixture-v1",
                },
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrdersApi.java",
                        "content": """
interface OrdersApi {
    @PostMapping("/orders/search")
    Order find(List<OrderFilter> filters);
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController implements OrdersApi {
    public Order find(Set<OrderFilter> filters) { return setService.find(filters); }

    public Order find(List<OrderFilter> filters) { return listService.find(filters); }
}

class OrderFilter { private String status; }
""",
                    },
                ],
            }
        )
    )

    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [claim.callee_ref for claim in calls] == ["java://listService.find"]


def test_java_spring_poc_resolves_inherited_local_interface_routes() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {
                    "ref": "repository://inherited-interface-route",
                    "revision": "fixture-v1",
                },
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/BaseApi.java",
                        "content": """
interface BaseApi {
    @GetMapping("/orders/{id}")
    OrderDto load(String id);
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrdersApi.java",
                        "content": """
@RequestMapping("/v1")
interface OrdersApi extends BaseApi {}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController implements OrdersApi {
    public OrderDto load(String id) { return orderService.load(id); }
}

class OrderDto { private String status; }
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.handler, claim.path) for claim in routes] == [("load", "/v1/orders/{id}")]
    assert [claim.callee_ref for claim in calls] == ["java://orderService.load"]


def test_java_spring_poc_excludes_static_interface_mapping_methods() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://static-interface", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrdersApi.java",
                        "content": """
interface OrdersApi {
    @GetMapping("/static")
    static Order staticOrder() { return staticService.load(); }

    @GetMapping("/live")
    Order live();
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController implements OrdersApi {
    public Order live() { return orderService.load(); }
}
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.handler, claim.path) for claim in routes] == [("live", "/live")]
    assert [claim.callee_ref for claim in calls] == ["java://orderService.load"]


def test_java_spring_poc_does_not_select_an_arbitrary_unannotated_class() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://controller-candidate", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/UnrelatedFile.java",
                        "content": """
class ArbitraryHelper {
    @GetMapping("/fabricated")
    Order fabricated() {
        return arbitraryService.load();
    }
}

class AnotherHelper {}

enum Marker { PRESENT; }
""",
                    }
                ],
            }
        )
    )

    assert not [claim for claim in evidence.claims if claim.kind == "controller_route"]
    assert not [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [claim.values for claim in evidence.claims if claim.kind == "enum_state"] == [
        ["PRESENT"]
    ]


def test_java_spring_poc_recognizes_fully_qualified_spring_mapping_annotations() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://qualified-spring", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/QualifiedController.java",
                        "content": """
@org.springframework.web.bind.annotation.RestController
@org.springframework.web.bind.annotation.RequestMapping("/api")
class QualifiedController {
    @org.springframework.web.bind.annotation.GetMapping("/orders")
    Order load() {
        return orderService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.method, claim.path, claim.handler) for claim in routes] == [
        ("GET", "/api/orders", "load")
    ]
    assert [claim.callee_ref for claim in calls] == ["java://orderService.load"]


def test_java_spring_poc_decodes_java_string_escapes_in_mapping_paths() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://escaped-mapping", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/ItemController.java",
                        "content": """
@RestController
class ItemController {
    @GetMapping("/items/{id:\\\\d+}")
    Item load() { return itemService.load(); }
}
""",
                    }
                ],
            }
        )
    )

    route = next(claim for claim in evidence.claims if claim.kind == "controller_route")
    call = next(claim for claim in evidence.claims if claim.kind == "service_call")
    expected_path = r"/items/{id:\d+}"
    assert (route.path, route.operation_ref) == (
        expected_path,
        f"operation://GET{expected_path}",
    )
    assert call.operation_ref == route.operation_ref


def test_java_spring_poc_analyzes_every_annotated_top_level_controller() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://multiple-controllers", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/PrimaryController.java",
                        "content": """
@RestController
class PrimaryController {
    @GetMapping("/primary")
    Order primary() { return primaryService.load(); }
}

@Controller
class SecondaryController {
    @GetMapping("/secondary")
    Order secondary() { return secondaryService.load(); }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert {(claim.controller_ref, claim.handler, claim.path) for claim in routes} == {
        ("java://PrimaryController", "primary", "/primary"),
        ("java://SecondaryController", "secondary", "/secondary"),
    }
    assert {claim.callee_ref for claim in calls} == {
        "java://primaryService.load",
        "java://secondaryService.load",
    }


def test_java_spring_poc_binds_mapping_to_immediately_following_modified_method() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://method-modifiers", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/ModifierController.java",
                        "content": """
@RestController
class ModifierController {
    @GetMapping("/sync")
    public synchronized Order synchronizedLoad() {
        return syncService.load();
    }

    @GetMapping("/protected")
    protected final Order protectedLoad() {
        return protectedService.load();
    }

    @GetMapping("/package")
    Order packageLoad() {
        return packageService.load();
    }

    @GetMapping("/nullable")
    public @Nullable Order nullableLoad() {
        return nullableService.load();
    }

    @GetMapping("/private")
    private Order privateLoad() {
        return privateService.load();
    }

    public Order unrelated() {
        return unrelatedService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert {(claim.handler, claim.path) for claim in routes} == {
        ("synchronizedLoad", "/sync"),
        ("protectedLoad", "/protected"),
        ("packageLoad", "/package"),
        ("nullableLoad", "/nullable"),
    }
    assert {claim.callee_ref for claim in calls} == {
        "java://syncService.load",
        "java://protectedService.load",
        "java://packageService.load",
        "java://nullableService.load",
    }


def test_java_spring_poc_parses_method_level_request_mapping_methods() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://request-mapping", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/RequestMappingController.java",
                        "content": """
@RestController
@RequestMapping("/api")
class RequestMappingController {
    @RequestMapping(
        path = "/orders",
        method = {RequestMethod.GET, RequestMethod.POST}
    )
    public Order handle() {
        return orderService.handle();
    }

    @GetMapping(path = "/balanced", params = "q=(foo)")
    public Order balanced() {
        return orderService.balanced();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    assert {(claim.method, claim.path, claim.handler) for claim in routes} == {
        ("GET", "/api/orders", "handle"),
        ("POST", "/api/orders", "handle"),
        ("GET", "/api/balanced", "balanced"),
    }


def test_java_spring_poc_includes_explicit_head_options_and_trace_mappings() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://extended-http-methods", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/HealthController.java",
                        "content": """
@RestController
class HealthController {
    @RequestMapping(
        path = "/health",
        method = {RequestMethod.HEAD, RequestMethod.OPTIONS, RequestMethod.TRACE}
    )
    Health health() { return healthService.load(); }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert {claim.method for claim in routes} == {"HEAD", "OPTIONS", "TRACE"}
    assert {claim.operation_ref for claim in calls} == {
        "operation://HEAD/health",
        "operation://OPTIONS/health",
        "operation://TRACE/health",
    }


def test_java_spring_poc_distinguishes_condition_specific_mappings() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://condition-mappings", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/ConditionController.java",
                        "content": """
@RestController
@RequestMapping("/orders")
class ConditionController {
    @GetMapping(params = "view=summary")
    OrderSummaryDto summary() {
        return summaryService.load();
    }

    @GetMapping(
        params = "view=detail",
        headers = "X-FlowTest-View=detail"
    )
    OrderDetailDto detail() {
        return detailService.load();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderSummaryDto.java",
                        "content": """
class OrderSummaryDto {
    private String summary;
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderDetailDto.java",
                        "content": """
class OrderDetailDto {
    private String detail;
}
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    operation_by_handler = {claim.handler: claim.operation_ref for claim in routes}
    calls = {
        claim.callee_ref: claim.operation_ref
        for claim in evidence.claims
        if claim.kind == "service_call"
    }
    fields = {
        claim.field_name: claim.operation_ref
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    }
    assert {(claim.method, claim.path) for claim in routes} == {("GET", "/orders")}
    assert set(operation_by_handler) == {"summary", "detail"}
    assert len(set(operation_by_handler.values())) == 2
    assert calls == {
        "java://summaryService.load": operation_by_handler["summary"],
        "java://detailService.load": operation_by_handler["detail"],
    }
    assert fields == {
        "summary": operation_by_handler["summary"],
        "detail": operation_by_handler["detail"],
    }
    assert all("view=" not in operation_ref for operation_ref in operation_by_handler.values())


def test_java_spring_poc_drops_unresolved_mapping_conditions() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://computed-conditions", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/TenantController.java",
                        "content": """
@RestController
@RequestMapping("/orders")
class TenantController {
    @GetMapping(headers = "X-Tenant=" + TENANT_A)
    Order tenantA() {
        return tenantAService.load();
    }

    @GetMapping(headers = "X-Tenant=" + TENANT_B)
    Order tenantB() {
        return tenantBService.load();
    }

    @GetMapping("/live")
    Order live() {
        return liveService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.handler, claim.path) for claim in routes] == [("live", "/orders/live")]
    assert [claim.callee_ref for claim in calls] == ["java://liveService.load"]
    assert evidence.deterministic is False
    assert "JAVA_POC_INCOMPLETE_MAPPING_CONDITION" in {
        warning.code for warning in evidence.warnings
    }


def test_java_spring_poc_resolves_standard_media_type_mapping_conditions() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://media-type-condition", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/MediaController.java",
                        "content": """
@RestController
class MediaController {
    @GetMapping(path = "/constant", produces = MediaType.APPLICATION_JSON_VALUE)
    Order constant() { return constantService.load(); }

    @GetMapping(path = "/literal", produces = "application/json")
    Order literal() { return literalService.load(); }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    condition_suffixes = {claim.operation_ref.split("#", 1)[1] for claim in routes}
    assert len(routes) == 2
    assert len(condition_suffixes) == 1


def test_java_spring_poc_method_media_conditions_override_type_conditions() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://media-override", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/MediaOverrideController.java",
                        "content": """
@RestController
@RequestMapping(produces = "application/json", headers = "X-Class=1")
class MediaOverrideController {
    @GetMapping(path = "/override", produces = "application/xml", headers = "X-Method=1")
    Order override() { return overrideService.load(); }
}

@RestController
class MediaBaselineController {
    @GetMapping(
        path = "/baseline",
        produces = "application/xml",
        headers = {"X-Class=1", "X-Method=1"}
    )
    Order baseline() { return baselineService.load(); }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    condition_suffixes = {claim.operation_ref.split("#", 1)[1] for claim in routes}
    assert len(routes) == 2
    assert len(condition_suffixes) == 1


def test_java_spring_poc_treats_empty_request_method_array_as_unrestricted() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://empty-methods", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @RequestMapping(path = "/orders", method = {})
    Order allMethods() { return orderService.load(); }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    assert {claim.method for claim in routes} == {
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "TRACE",
    }


def test_java_spring_poc_intersects_class_and_method_mapping_methods() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://class-method", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/ClassMethodController.java",
                        "content": """
@RestController
@RequestMapping(path = "/orders", method = RequestMethod.POST)
class ClassMethodController {
    @RequestMapping("/create")
    public Order create() {
        return orderService.create();
    }

    @GetMapping("/conflict")
    public Order conflict() {
        return orderService.conflict();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.method, claim.path, claim.handler) for claim in routes] == [
        ("POST", "/orders/create", "create")
    ]
    assert [claim.callee_ref for claim in calls] == ["java://orderService.create"]


def test_java_spring_poc_expands_request_mapping_without_method_to_supported_verbs() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://request-mapping-any", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/AnyMethodController.java",
                        "content": """
@RestController
@RequestMapping("/api")
class AnyMethodController {
    @RequestMapping(path = "/orders", params = "method=GET")
    public Order handle() {
        return orderService.handle();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert {(claim.method, claim.path) for claim in routes} == {
        (method, "/api/orders")
        for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE")
    }
    assert {claim.operation_ref for claim in calls} == {claim.operation_ref for claim in routes}
    assert all("#conditions-" in claim.operation_ref for claim in routes)


def test_java_spring_poc_parses_statically_imported_request_method_constants() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://static-request-method", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/StaticMethodController.java",
                        "content": """
import static org.springframework.web.bind.annotation.RequestMethod.GET;

@RestController
class StaticMethodController {
    @RequestMapping(path = "/orders", method = GET)
    public Order load() {
        return orderService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.method, claim.path) for claim in routes] == [("GET", "/orders")]
    assert [claim.operation_ref for claim in calls] == ["operation://GET/orders"]


def test_java_spring_poc_parses_formatted_generic_handler_return_types() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://generic-return", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/GenericController.java",
                        "content": """
class OrderDto {
    private String id;
}

@RestController
class GenericController {
    @GetMapping("/orders")
    public Map<String, OrderDto> load() throws OrderUnavailableException {
        kafkaTemplate.send("orders.loaded", orderService.load());
        return orderService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    response_fields = [
        claim
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    ]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    exceptions = [claim for claim in evidence.claims if claim.kind == "exception"]
    events = [claim for claim in evidence.claims if claim.kind == "kafka_event"]
    assert [(claim.handler, claim.path) for claim in routes] == [("load", "/orders")]
    assert [(claim.dto_type, claim.field_name) for claim in response_fields] == [("OrderDto", "id")]
    assert [claim.callee_ref for claim in calls] == ["java://orderService.load"]
    assert [claim.exception_type for claim in exceptions] == ["OrderUnavailableException"]
    assert [claim.topic_ref for claim in events] == ["kafka://orders.loaded"]


def test_java_spring_poc_does_not_guess_ambiguous_generic_response_dto() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://ambiguous-response", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/PairController.java",
                        "content": """
@RestController
class PairController {
    @GetMapping("/orders")
    Pair<OrderDto, MetadataDto> load() {
        return orderService.load();
    }
}

class OrderDto {
    String orderId;
}

class MetadataDto {
    String cursor;
}
""",
                    }
                ],
            }
        )
    )

    response_fields = [
        claim
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    ]
    assert response_fields == []
    assert [claim.callee_ref for claim in evidence.claims if claim.kind == "service_call"] == [
        "java://orderService.load"
    ]


def test_java_spring_poc_parses_generic_handler_parameters_at_top_level() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://generic-parameter", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    Order create(Pair<Foo, Bar> request) {
        return orderService.create(request);
    }
}

class Pair<T, U> {
    private String pairValue;
}

class Foo {
    private String fooOnly;
}

class Bar {
    @NotNull
    private String barOnly;
}
""",
                    }
                ],
            }
        )
    )

    request_fields = {
        (claim.dto_type, claim.field_name)
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "request"
    }
    constraints = {
        (claim.dto_type, claim.field_name)
        for claim in evidence.claims
        if claim.kind == "bean_validation" and claim.operation_ref is not None
    }
    assert request_fields == {("Pair", "pairValue")}
    assert constraints == set()


def test_java_spring_poc_unwraps_collection_request_body_dto_types() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://collection-request", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    Order create(@RequestBody List<CreateOrderRequest> requests) {
        return orderService.create(requests);
    }
}

class CreateOrderRequest {
    @NotNull
    private OrderStatus status;
}

enum OrderStatus { ACTIVE, INACTIVE }
""",
                    }
                ],
            }
        )
    )

    request_fields = {
        (claim.dto_type, claim.field_name)
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "request"
    }
    constraints = {
        (claim.dto_type, claim.field_name, claim.annotation)
        for claim in evidence.claims
        if claim.kind == "bean_validation" and claim.operation_ref is not None
    }
    states = {
        (claim.dto_type, claim.field_name, tuple(claim.values))
        for claim in evidence.claims
        if claim.kind == "enum_state" and claim.operation_ref is not None
    }
    assert request_fields == {("CreateOrderRequest", "status")}
    assert constraints == {("CreateOrderRequest", "status", "NotNull")}
    assert states == {("CreateOrderRequest", "status", ("ACTIVE", "INACTIVE"))}


def test_java_spring_poc_skips_unresolved_mapping_path_constants() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://mapping-constants", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/MethodConstantController.java",
                        "content": """
@RestController
@RequestMapping("/api")
class MethodConstantController {
    @GetMapping(PATH)
    public Order unresolved() {
        return unresolvedService.load();
    }

    @GetMapping("/live")
    public Order live() {
        return liveService.load();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/BaseConstantController.java",
                        "content": """
@RestController
@RequestMapping(BASE_PATH)
class BaseConstantController {
    @GetMapping("/orders")
    public Order unresolvedBase() {
        return baseService.load();
    }
}
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.handler, claim.path) for claim in routes] == [("live", "/api/live")]
    assert [claim.callee_ref for claim in calls] == ["java://liveService.load"]
    assert evidence.deterministic is False
    assert "JAVA_POC_INCOMPLETE_MAPPING_PATH" in {warning.code for warning in evidence.warnings}


def test_java_spring_poc_resolves_local_mapping_path_constants() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://resolved-mapping-constants", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/Routes.java",
                        "content": """
final class Routes {
    static final String ORDERS = "/orders";
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
@RequestMapping(path = API_PATH)
class OrderController {
    private static final String API_PATH = "/api";

    @GetMapping(value = Routes.ORDERS)
    Order load() { return orderService.load(); }
}
""",
                    },
                ],
            }
        )
    )

    route = next(claim for claim in evidence.claims if claim.kind == "controller_route")
    assert (route.handler, route.path) == ("load", "/api/orders")


def test_java_spring_poc_excludes_framework_injected_parameters_from_request_dtos() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://injected-parameter", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders/search")
    Order search(
        @AuthenticationPrincipal User user,
        @RequestBody OrderFilter filter
    ) {
        return orderService.search(filter);
    }
}

class User { private String tenantId; }
class OrderFilter { private String status; }
""",
                    }
                ],
            }
        )
    )

    request_fields = {
        (claim.dto_type, claim.field_name)
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "request"
    }
    assert request_fields == {("OrderFilter", "status")}


def test_java_spring_poc_rejects_partial_mapping_path_expressions() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://mapping-expression", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/ExpressionController.java",
                        "content": """
@RestController
class ExpressionController {
    @GetMapping("${api.orders-path}")
    Order placeholder() {
        return placeholderService.load();
    }

    @GetMapping("/api/" + VERSION)
    Order concatenated() {
        return concatenatedService.load();
    }

    @GetMapping(path = {"/legacy", "/v" + VERSION})
    Order mixedArray() {
        return mixedService.load();
    }

    @GetMapping("/live")
    Order live() {
        return liveService.load();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/BaseExpressionController.java",
                        "content": """
@RestController
@RequestMapping("/root/" + VERSION)
class BaseExpressionController {
    @GetMapping("/orders")
    Order unresolvedBase() {
        return baseService.load();
    }
}
""",
                    },
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert [(claim.handler, claim.path) for claim in routes] == [("live", "/live")]
    assert [claim.callee_ref for claim in calls] == ["java://liveService.load"]
    assert evidence.deterministic is False
    assert "JAVA_POC_INCOMPLETE_MAPPING_PATH" in {warning.code for warning in evidence.warnings}


def test_java_spring_poc_ignores_dto_fields_and_constraints_in_non_code_text() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://active-dto-fields", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
public class OrderController {
    @PostMapping("/orders")
    public Order create(@RequestBody CreateOrderRequest request) {
        return orderService.create(request);
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/CreateOrderRequest.java",
                        "content": """
public class CreateOrderRequest {
    // @NotBlank(message = "ghost")
    // private String legacyToken;

    @NotBlank(message = "required")
    @Pattern(regexp = "^(foo|bar)$")
    private String name = "NEW";

    static class NestedRequest {
        @NotBlank(message = "nested")
        private String nestedOnly;
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderEntity.java",
                        "content": """
public class OrderEntity {
    private String status = "NEW";
}
""",
                    },
                ],
            }
        )
    )

    request_fields = {
        claim.field_name
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "request"
    }
    constraint_fields = {
        claim.field_name for claim in evidence.claims if claim.kind == "bean_validation"
    }
    constraints = {claim.constraint for claim in evidence.claims if claim.kind == "bean_validation"}
    entity_fields = {claim.field_name for claim in evidence.claims if claim.kind == "table_column"}
    assert request_fields == {"name"}
    assert constraint_fields == {"name"}
    assert entity_fields == {"status"}
    assert '(regexp = "^(foo|bar)$")' in constraints


def test_java_spring_poc_excludes_jackson_ignored_dto_fields_and_getters() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://jackson-ignore", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    OrderDto create(@RequestBody OrderDto request) {
        return orderService.create(request);
    }
}

class OrderDto {
    private String visible;

    @JsonIgnore(false)
    private String explicitlyVisible;

    @JsonIgnore
    private String internalToken;

    private String serverOnly;

    @JsonIgnore
    public String getServerOnly() { return serverOnly; }
}
""",
                    }
                ],
            }
        )
    )

    fields = {
        (claim.direction, claim.field_name)
        for claim in evidence.claims
        if claim.kind == "dto_field"
    }
    assert fields == {
        ("request", "explicitlyVisible"),
        ("request", "visible"),
        ("response", "explicitlyVisible"),
        ("response", "visible"),
    }


def test_java_spring_poc_honors_jackson_property_access_direction() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://jackson-access", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    OrderDto create(@RequestBody OrderDto request) {
        return orderService.create(request);
    }
}

class OrderDto {
    private String visible;

    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    private String password;

    @com.fasterxml.jackson.annotation.JsonProperty(
        access = com.fasterxml.jackson.annotation.JsonProperty.Access.READ_ONLY
    )
    private String generatedId;

    private String getterReadOnly;

    @JsonProperty(access = JsonProperty.Access.READ_ONLY)
    public String getGetterReadOnly() { return getterReadOnly; }
}
""",
                    }
                ],
            }
        )
    )

    request_fields = {
        claim.field_name
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "request"
    }
    response_fields = {
        claim.field_name
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    }
    assert request_fields == {"password", "visible"}
    assert response_fields == {"generatedId", "getterReadOnly", "visible"}


def test_java_spring_poc_honors_explicit_jackson_property_names() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://jackson-names", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/AccountController.java",
                        "content": """
@RestController
class AccountController {
    @PostMapping("/class")
    ClassDto classDto(@RequestBody ClassDto request) { return request; }

    @PostMapping("/record")
    RecordDto recordDto(@RequestBody RecordDto request) { return request; }

    @PostMapping("/accessor")
    AccessorDto accessorDto(@RequestBody AccessorDto request) { return request; }
}

class ClassDto {
    @JsonProperty("login")
    private String userName;

    @JsonProperty(value = "password", access = JsonProperty.Access.WRITE_ONLY)
    private String secret;
}

record RecordDto(@JsonProperty(value = "recordLogin") String userName) {}

class AccessorDto {
    private String userName;

    @JsonProperty("accessorLogin")
    public String getUserName() { return userName; }
}
""",
                    }
                ],
            }
        )
    )

    fields = {
        (claim.dto_type, claim.direction, claim.field_name)
        for claim in evidence.claims
        if claim.kind == "dto_field"
    }
    assert fields == {
        ("AccessorDto", "request", "accessorLogin"),
        ("AccessorDto", "response", "accessorLogin"),
        ("ClassDto", "request", "login"),
        ("ClassDto", "request", "password"),
        ("ClassDto", "response", "login"),
        ("RecordDto", "request", "recordLogin"),
        ("RecordDto", "response", "recordLogin"),
    }


def test_java_spring_poc_preserves_qualified_and_repeated_validation_constraints() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://qualified-validation", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    Order create(CreateOrderRequest request) {
        return orderService.create(request);
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/CreateOrderRequest.java",
                        "content": """
class CreateOrderRequest {
    @jakarta.validation.constraints.NotNull
    private String name;

    @javax.validation.constraints.Pattern(regexp = "^[A-Z]+$")
    @javax.validation.constraints.Pattern(regexp = "^[A-Z0-9]+$")
    private String code;

    private Details details;

    @jakarta.validation.Valid
    public Details getDetails() { return details; }
}
""",
                    },
                ],
            }
        )
    )

    constraints = [claim for claim in evidence.claims if claim.kind == "bean_validation"]
    assert {(claim.field_name, claim.annotation) for claim in constraints} == {
        ("code", "Pattern"),
        ("details", "Valid"),
        ("name", "NotNull"),
    }
    patterns = [claim for claim in constraints if claim.annotation == "Pattern"]
    assert {claim.constraint for claim in patterns} == {
        '(regexp = "^[A-Z]+$")',
        '(regexp = "^[A-Z0-9]+$")',
    }
    assert len(patterns) == 2
    assert len({claim.id for claim in patterns}) == 2


def test_java_spring_poc_parses_every_multi_variable_field_declarator() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://multi-fields", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    Order create(CreateOrderRequest request) { return orderService.create(request); }
}
""",
                    },
                    {
                        "path": "src/main/java/example/CreateOrderRequest.java",
                        "content": """
class CreateOrderRequest {
    private String first, last;
    private int minimum = 1, maximum = 2;
}
""",
                    },
                    {
                        "path": "src/main/java/example/entity/OrderEntity.java",
                        "content": """
class OrderEntity {
    private String first, last;
    private int minimum = 1, maximum = 2;
}
""",
                    },
                ],
            }
        )
    )

    request_fields = {
        (claim.field_name, claim.field_type)
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "request"
    }
    entity_columns = {
        (claim.field_name, claim.column_name)
        for claim in evidence.claims
        if claim.kind == "table_column"
    }
    assert request_fields == {
        ("first", "String"),
        ("last", "String"),
        ("minimum", "int"),
        ("maximum", "int"),
    }
    assert entity_columns == {
        ("first", "first"),
        ("last", "last"),
        ("minimum", "minimum"),
        ("maximum", "maximum"),
    }


def test_java_spring_poc_excludes_static_dto_and_entity_fields() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://static-fields", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
public class OrderController {
    @GetMapping("/orders")
    public OrderDto getOrder() {
        return orderService.getOrder();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderDto.java",
                        "content": """
public class OrderDto {
    private static final long serialVersionUID = 1L;
    private String status;
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderEntity.java",
                        "content": """
public class OrderEntity {
    private static final String TABLE_NAME = "orders";
    private String status;
}
""",
                    },
                ],
            }
        )
    )

    response_fields = {
        claim.field_name
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    }
    entity_fields = {claim.field_name for claim in evidence.claims if claim.kind == "table_column"}
    assert response_fields == {"status"}
    assert entity_fields == {"status"}


def test_java_spring_poc_infers_all_instance_field_visibilities() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://field-visibilities", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @GetMapping("/orders")
    OrderDto getOrder() {
        return orderService.getOrder();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderDto.java",
                        "content": """
class OrderDto {
    public String publicStatus;
    protected String protectedStatus;
    String packageStatus;
    private String privateStatus;
    public static String PUBLIC_SAMPLE;
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderEntity.java",
                        "content": """
class OrderEntity {
    public String publicColumn;
    protected String protectedColumn;
    String packageColumn;
    private String privateColumn;
    protected static String PROTECTED_SAMPLE;
}
""",
                    },
                ],
            }
        )
    )

    response_fields = {
        claim.field_name
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    }
    entity_fields = {claim.field_name for claim in evidence.claims if claim.kind == "table_column"}
    assert response_fields == {
        "publicStatus",
        "protectedStatus",
        "packageStatus",
        "privateStatus",
    }
    assert entity_fields == {
        "publicColumn",
        "protectedColumn",
        "packageColumn",
        "privateColumn",
    }


def test_java_spring_poc_parses_whitespace_in_class_field_generic_types() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://generic-fields", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
public class OrderController {
    @GetMapping("/orders")
    public OrderDto getOrder() {
        return orderService.getOrder();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderDto.java",
                        "content": """
public class OrderDto {
    private Map<String, OrderDto> orders;
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderEntity.java",
                        "content": """
public class OrderEntity {
    private Map<String, OrderDto> orders;
}
""",
                    },
                ],
            }
        )
    )

    response_fields = {
        (claim.field_name, claim.field_type)
        for claim in evidence.claims
        if claim.kind == "dto_field" and claim.direction == "response"
    }
    entity_fields = {claim.field_name for claim in evidence.claims if claim.kind == "table_column"}
    assert response_fields == {("orders", "Map<String, OrderDto>")}
    assert entity_fields == {"orders"}


def test_java_spring_poc_preserves_supported_long_validation_arguments() -> None:
    long_pattern = "x" * 340
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://long-validation", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
public class OrderController {
    @PostMapping("/orders")
    public Order create(@RequestBody CreateOrderRequest request) {
        return orderService.create(request);
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/CreateOrderRequest.java",
                        "content": f"""
public class CreateOrderRequest {{
    @Pattern(regexp = "{long_pattern}")
    private String code;
}}
""",
                    },
                ],
            }
        )
    )

    constraints = [claim.constraint for claim in evidence.claims if claim.kind == "bean_validation"]
    assert constraints == [f'(regexp = "{long_pattern}")']


def test_java_spring_poc_discovers_every_supported_getter_constraint() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://getter-validation", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
public class OrderController {
    @PostMapping("/orders")
    public Order create(@RequestBody CreateOrderRequest request) {
        return orderService.create(request);
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/CreateOrderRequest.java",
                        "content": """
public class CreateOrderRequest {
    private BigDecimal amount;

    @Positive
    @DecimalMin(value = "0.01")
    @Valid
    public BigDecimal getAmount() {
        return amount;
    }
}
""",
                    },
                ],
            }
        )
    )

    annotations = {
        claim.annotation
        for claim in evidence.claims
        if claim.kind == "bean_validation" and claim.field_name == "amount"
    }
    assert annotations == {"Positive", "DecimalMin", "Valid"}


def test_java_spring_poc_does_not_inherit_annotations_from_preceding_getters() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://member-boundaries", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    Order create(CreateOrderRequest request) { return orderService.create(request); }
}
""",
                    },
                    {
                        "path": "src/main/java/example/CreateOrderRequest.java",
                        "content": """
class CreateOrderRequest {
    private String name;

    @NotNull
    public String getName() { return name; }

    private String status;
}
""",
                    },
                    {
                        "path": "src/main/java/example/entity/OrderEntity.java",
                        "content": """
class OrderEntity {
    private String displayName;

    @Column(name = "display_name")
    public String getDisplayName() { return displayName; }

    private String status;
}
""",
                    },
                ],
            }
        )
    )

    constraints = {
        (claim.field_name, claim.annotation)
        for claim in evidence.claims
        if claim.kind == "bean_validation"
    }
    entity_columns = {
        claim.field_name: claim.column_name
        for claim in evidence.claims
        if claim.kind == "table_column"
    }
    assert constraints == {("name", "NotNull")}
    assert entity_columns["status"] == "status"


def test_java_spring_poc_expands_all_mapping_paths() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://multi-path-routes", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
@RequestMapping(path = {"/api", "/compat"})
public class OrderController {
    @GetMapping({"/current", "/legacy"})
    public Order load() {
        return orderService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = {
        (claim.handler, claim.path) for claim in evidence.claims if claim.kind == "controller_route"
    }
    assert routes == {
        ("load", "/api/current"),
        ("load", "/api/legacy"),
        ("load", "/compat/current"),
        ("load", "/compat/legacy"),
    }
    call_operations = {
        claim.operation_ref for claim in evidence.claims if claim.kind == "service_call"
    }
    assert call_operations == {
        "operation://GET/api/current",
        "operation://GET/api/legacy",
        "operation://GET/compat/current",
        "operation://GET/compat/legacy",
    }


def test_java_spring_poc_parses_mapping_arrays_with_uri_template_braces() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://template-path-array", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/TemplateController.java",
                        "content": """
@RestController
class TemplateController {
    @GetMapping({"/orders/{id}", "/legacy/{id}"})
    public Order load() {
        return orderService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    calls = [claim for claim in evidence.claims if claim.kind == "service_call"]
    assert {(claim.handler, claim.path) for claim in routes} == {
        ("load", "/orders/{id}"),
        ("load", "/legacy/{id}"),
    }
    assert {claim.operation_ref for claim in calls} == {
        "operation://GET/orders/{id}",
        "operation://GET/legacy/{id}",
    }


def test_java_spring_poc_ignores_route_claims_in_non_code_text() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://active-calls", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
public class OrderController {
    @GetMapping("/orders")
    public Order load() {
        String sample = "stringService.delete()";
        // commentService.delete();
        /*
         * blockRepository.delete();
         * throw new GhostException();
         * kafkaTemplate.send("ghost.topic");
         */
        return liveService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    calls = {
        claim.callee_ref
        for claim in evidence.claims
        if claim.kind in {"service_call", "feign_call"}
    }
    assert calls == {"java://liveService.load"}
    assert not [claim for claim in evidence.claims if claim.kind == "exception"]
    assert not [claim for claim in evidence.claims if claim.kind == "kafka_event"]


def test_java_spring_poc_parses_only_top_level_enum_constants() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://enum-constants", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderStatus.java",
                        "content": """
public enum OrderStatus {
    // SHADOW_STATE must not become evidence.
    @JsonProperty("ACTIVE_CODE")
    ACTIVE("A") {
        @Override
        public String code() { return "A"; }
    },
    INACTIVE("I");

    private final String code;
}
""",
                    }
                ],
            }
        )
    )

    states = [claim for claim in evidence.claims if claim.kind == "enum_state"]
    assert len(states) == 1
    assert states[0].values == ["ACTIVE", "INACTIVE"]


def test_java_spring_poc_keeps_same_named_structural_claims_from_distinct_sources() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://same-named-enums", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/alpha/Status.java",
                        "content": "package alpha; public enum Status { ACTIVE, INACTIVE; }",
                    },
                    {
                        "path": "src/main/java/beta/Status.java",
                        "content": "package beta; public enum Status { OPEN, CLOSED; }",
                    },
                ],
            }
        )
    )

    states = [claim for claim in evidence.claims if claim.kind == "enum_state"]
    assert len(states) == 2
    assert len({claim.id for claim in states}) == 2
    assert len({claim.enum_ref for claim in states}) == 2
    assert {tuple(claim.values) for claim in states} == {
        ("ACTIVE", "INACTIVE"),
        ("OPEN", "CLOSED"),
    }


def test_java_spring_poc_infers_entities_only_from_top_level_classes_or_records() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://nested-entity-types", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/entity/Order.java",
                        "content": """
public class Order {
    private String id;

    enum Status { ACTIVE, INACTIVE; }
    interface HelperRepository {}
    static class Detail {}
}
""",
                    }
                ],
            }
        )
    )

    entities = [claim for claim in evidence.claims if claim.kind == "entity"]
    states = [claim for claim in evidence.claims if claim.kind == "enum_state"]
    assert [claim.class_name for claim in entities] == ["Order"]
    assert [(claim.enum_ref.split("/")[2], claim.values) for claim in states] == [
        ("Status", ["ACTIVE", "INACTIVE"])
    ]


def test_java_spring_poc_reports_claim_quota_truncation() -> None:
    routes = "\n".join(
        f"""
    @GetMapping("/items/{index}")
    public Order item{index}() {{
        return orderService.load();
    }}
"""
        for index in range(13)
    )
    snapshot = JavaSourceSnapshot.model_validate(
        {
            "provider": {"name": "java-spring-poc", "version": "0.1.0"},
            "source": {"ref": "repository://route-overflow", "revision": "fixture-v1"},
            "subject_ref": SUBJECT_REF,
            "files": [
                {
                    "path": "src/main/java/example/OrderController.java",
                    "content": f"@RestController\npublic class OrderController {{\n{routes}\n}}",
                }
            ],
        }
    )

    evidence = JavaSpringPocProvider().analyze(snapshot)

    assert len([claim for claim in evidence.claims if claim.kind == "controller_route"]) == 12
    assert evidence.deterministic is False
    assert any(
        warning.code == "JAVA_POC_INCOMPLETE_BUDGET" and "不完整" in warning.message
        for warning in evidence.warnings
    )


def test_java_spring_poc_removes_claims_for_truncated_routes() -> None:
    routes = "\n".join(
        f"""
    @GetMapping("/items/{index}")
    Dto{index} item{index}() {{
        return item{index}Service.load();
    }}
"""
        for index in range(13)
    )
    dtos = "\n".join(f"class Dto{index} {{ private String value{index}; }}" for index in range(13))
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://dependent-overflow", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": (
                            f"{dtos}\n@RestController\n"
                            f"public class OrderController {{\n{routes}\n}}"
                        ),
                    }
                ],
            }
        )
    )

    route_refs = {
        claim.operation_ref for claim in evidence.claims if claim.kind == "controller_route"
    }
    dto_claims = [claim for claim in evidence.claims if claim.kind == "dto_field"]
    assert len(route_refs) == 12
    assert len(dto_claims) == 12
    assert {claim.operation_ref for claim in dto_claims} <= route_refs


def test_java_spring_poc_reports_enum_value_truncation() -> None:
    constants = ",\n".join(f"STATE_{index:03d}" for index in range(101))
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://enum-overflow", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/LargeState.java",
                        "content": f"public enum LargeState {{\n{constants};\n}}",
                    }
                ],
            }
        )
    )

    states = [claim for claim in evidence.claims if claim.kind == "enum_state"]
    assert len(states) == 1
    assert len(states[0].values) == 100
    assert states[0].deterministic is False
    assert any(
        warning.code == "JAVA_POC_INCOMPLETE_BUDGET" and "不完整" in warning.message
        for warning in evidence.warnings
    )


def test_java_spring_poc_ignores_kafka_listeners_in_non_code_text() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://active-listeners", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderListener.java",
                        "content": """
public class OrderListener {
    private static final String SAMPLE = "@KafkaListener(\"string-ghost\")";

    // @KafkaListener("comment-ghost")
    @KafkaListener(topics = {"orders.real", "orders.retry"}, groupId = "billing")
    public void consume() {}

    @KafkaListener("orders.legacy")
    public void consumeLegacy() {}
}
""",
                    }
                ],
            }
        )
    )

    consumed_topics = {
        claim.topic_ref
        for claim in evidence.claims
        if claim.kind == "kafka_event" and claim.direction == "consume"
    }
    assert consumed_topics == {
        "kafka://orders.real",
        "kafka://orders.retry",
        "kafka://orders.legacy",
    }


def test_java_spring_poc_recognizes_fully_qualified_kafka_listener_annotation() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://qualified-listener", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderListener.java",
                        "content": """
class OrderListener {
    @org.springframework.kafka.annotation.KafkaListener("orders.qualified")
    void consume() {}
}
""",
                    }
                ],
            }
        )
    )

    consumed_topics = {
        claim.topic_ref
        for claim in evidence.claims
        if claim.kind == "kafka_event" and claim.direction == "consume"
    }
    assert consumed_topics == {"kafka://orders.qualified"}


def test_java_spring_poc_rejects_partial_kafka_topic_expressions() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://computed-topics", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    Order publish() {
        kafkaTemplate.send("orders-" + tenant, event);
        kafkaTemplate.send("${orders.topic}", event);
        kafkaTemplate.send("orders.literal", event);
        return orderService.load();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderListener.java",
                        "content": """
class OrderListener {
    @KafkaListener("${orders.topic}")
    void placeholder() {}

    @KafkaListener("orders-" + TENANT)
    void computedPositional() {}

    @KafkaListener(topics = "billing-" + TENANT)
    void computedNamed() {}

    @KafkaListener(topics = {"orders.valid", "orders.retry"})
    void literals() {}
}
""",
                    },
                ],
            }
        )
    )

    produced_topics = {
        claim.topic_ref
        for claim in evidence.claims
        if claim.kind == "kafka_event" and claim.direction == "produce"
    }
    consumed_topics = {
        claim.topic_ref
        for claim in evidence.claims
        if claim.kind == "kafka_event" and claim.direction == "consume"
    }
    assert produced_topics == {"kafka://orders.literal"}
    assert consumed_topics == {"kafka://orders.valid", "kafka://orders.retry"}
    assert evidence.deterministic is False
    assert "JAVA_POC_INCOMPLETE_KAFKA_TOPIC" in {warning.code for warning in evidence.warnings}


def test_java_spring_poc_decodes_java_string_escapes_in_kafka_producer_topics() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {
                    "ref": "repository://escaped-producer-topic",
                    "revision": "fixture-v1",
                },
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    Order publish() {
        kafkaTemplate.send("\\u006frders", event);
        return orderService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    produced_topics = [
        claim.topic_ref
        for claim in evidence.claims
        if claim.kind == "kafka_event" and claim.direction == "produce"
    ]
    assert produced_topics == ["kafka://orders"]


def test_java_spring_poc_recognizes_domain_named_kafka_template_fields() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://named-kafka-template", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    private final KafkaTemplate<String, OrderEvent> orderEvents;

    @PostMapping("/orders")
    Order publish() {
        orderEvents.send("orders.domain", event);
        return orderService.load();
    }
}
""",
                    }
                ],
            }
        )
    )

    produced_topics = {
        claim.topic_ref
        for claim in evidence.claims
        if claim.kind == "kafka_event" and claim.direction == "produce"
    }
    assert produced_topics == {"kafka://orders.domain"}


def test_java_spring_poc_parses_mapping_attributes_annotated_parameters_and_nested_dtos() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://spring-signatures", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
@RequestMapping("/api")
public class OrderController {
    @GetMapping(produces = "application/json", path = "/orders/{id}")
    public ResponseEntity<List<OrderDto>> getOrder(
        @PathVariable("id") String id,
        @RequestParam(required = false) String projection
    ) {
        return orderService.getOrder(id, projection);
    }

    @GetMapping(produces = "application/json")
    public OrderDto listOrders() {
        return orderService.listOrders();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderDto.java",
                        "content": """
package example;
public class OrderDto {
    private String orderId;
}
""",
                    },
                ],
            }
        )
    )

    routes = {
        (claim.handler, claim.path) for claim in evidence.claims if claim.kind == "controller_route"
    }
    assert routes == {
        ("getOrder", "/api/orders/{id}"),
        ("listOrders", "/api"),
    }
    assert any(
        claim.kind == "dto_field"
        and claim.direction == "response"
        and claim.dto_type == "OrderDto"
        and claim.field_name == "orderId"
        for claim in evidence.claims
    )


def test_java_spring_poc_rejects_ambiguous_simple_dto_names() -> None:
    files = [
        {
            "path": "src/main/java/example/SharedController.java",
            "content": """
@RestController
public class SharedController {
    @GetMapping("/shared")
    public SharedDto getShared() {
        return service.getShared();
    }
}
""",
        },
        {
            "path": "src/main/java/alpha/SharedDto.java",
            "content": "package alpha; public class SharedDto { private String alphaValue; }",
        },
        {
            "path": "src/main/java/beta/SharedDto.java",
            "content": "package beta; public class SharedDto { private String betaValue; }",
        },
    ]

    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://ambiguous-dtos", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": files,
            }
        )
    )
    reversed_evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://ambiguous-dtos", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": list(reversed(files)),
            }
        )
    )

    for result in (evidence, reversed_evidence):
        assert any(claim.kind == "controller_route" for claim in result.claims)
        assert not any(
            claim.kind == "dto_field" and claim.dto_type == "SharedDto" for claim in result.claims
        )
        assert any(
            warning.code == "JAVA_POC_INCOMPLETE_AMBIGUOUS_TYPE"
            and "SharedDto" in warning.message
            and "不完整" in warning.message
            for warning in result.warnings
        )


def test_java_spring_poc_binds_enum_states_to_route_dto_fields() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://route-enum-state", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @PostMapping("/orders")
    OrderDto create(CreateOrderRequest request) {
        return orderService.create(request);
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/CreateOrderRequest.java",
                        "content": """
class CreateOrderRequest {
    private RequestStatus status;
}
""",
                    },
                    {
                        "path": "src/main/java/example/OrderDto.java",
                        "content": """
class OrderDto {
    private ResponseStatus status;
}
""",
                    },
                    {
                        "path": "src/main/java/example/RequestStatus.java",
                        "content": "enum RequestStatus { REQUESTED, RETRIED; }",
                    },
                    {
                        "path": "src/main/java/example/ResponseStatus.java",
                        "content": "enum ResponseStatus { CREATED, PAID; }",
                    },
                ],
            }
        )
    )

    scoped_states = [
        claim
        for claim in evidence.claims
        if claim.kind == "enum_state" and claim.operation_ref is not None
    ]
    assert {
        (
            claim.operation_ref,
            claim.direction,
            claim.dto_type,
            claim.field_name,
            tuple(claim.values),
        )
        for claim in scoped_states
    } == {
        (
            "operation://POST/orders",
            "request",
            "CreateOrderRequest",
            "status",
            ("REQUESTED", "RETRIED"),
        ),
        (
            "operation://POST/orders",
            "response",
            "OrderDto",
            "status",
            ("CREATED", "PAID"),
        ),
    }
    assert len({claim.id for claim in scoped_states}) == 2

    mapping = derive_entity_mapping(
        _mapping_inputs(adapt_java_evidence(evidence), "directional-state")
    )
    state_candidates = [
        candidate for candidate in mapping.candidates if candidate.kind.value == "operation_state"
    ]
    assert len(state_candidates) == 2
    assert len({candidate.source_ref for candidate in state_candidates}) == 2
    assert not [
        conflict for conflict in mapping.conflicts if conflict.kind.value == "operation_state"
    ]


def test_java_spring_poc_honors_explicit_jpa_table_names() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://jpa-table-name", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/entity/CustomerAccountEntity.java",
                        "content": """
@Entity
@Table(name = "customer_accounts")
class CustomerAccountEntity {
    private String id;
}
""",
                    }
                ],
            }
        )
    )

    entity = next(claim for claim in evidence.claims if claim.kind == "entity")
    columns = [claim for claim in evidence.claims if claim.kind == "table_column"]
    assert entity.table_ref == "table://customer_accounts"
    assert [(claim.table_ref, claim.field_name, claim.column_name) for claim in columns] == [
        ("table://customer_accounts", "id", "id")
    ]


def test_java_spring_poc_resolves_jpa_table_and_column_name_constants() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://jpa-name-constants", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/entity/ArchivedOrderEntity.java",
                        "content": """
@Entity
@Table(name = TABLE_NAME, schema = SchemaNames.APPLICATION)
class ArchivedOrderEntity {
    private static final String TABLE_NAME = "orders";

    @Column(name = Columns.STATUS)
    private String state;
}

final class SchemaNames {
    static final String APPLICATION = "application";
}

final class Columns {
    static final String STATUS = "order_status";
}
""",
                    }
                ],
            }
        )
    )

    entity = next(
        claim
        for claim in evidence.claims
        if claim.kind == "entity" and claim.class_name == "ArchivedOrderEntity"
    )
    columns = [
        claim
        for claim in evidence.claims
        if claim.kind == "table_column" and claim.entity_ref == entity.entity_ref
    ]
    assert entity.table_ref == "table://application/orders"
    assert [(claim.field_name, claim.column_name) for claim in columns] == [
        ("state", "order_status")
    ]


def test_java_spring_poc_marks_unresolved_jpa_names_incomplete_without_guessing() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://unresolved-jpa-names", "revision": "v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/model/Entities.java",
                        "content": """
@Entity
@Table(name = UNKNOWN_TABLE)
class WrongEntity {
    private String id;
}

@Entity
@Table(name = "orders")
class OrderEntity {
    @Column(name = UNKNOWN_COLUMN)
    private String status;
}
""",
                    }
                ],
            }
        )
    )

    entities = {claim.class_name: claim for claim in evidence.claims if claim.kind == "entity"}
    columns = [claim for claim in evidence.claims if claim.kind == "table_column"]
    assert entities["WrongEntity"].table_ref is None
    assert not [
        claim for claim in columns if claim.entity_ref == entities["OrderEntity"].entity_ref
    ]
    assert evidence.deterministic is False
    warning_codes = {warning.code for warning in evidence.warnings}
    assert {"JAVA_POC_INCOMPLETE_JPA_TABLE", "JAVA_POC_INCOMPLETE_JPA_COLUMN"} <= warning_codes


def test_java_spring_poc_recognizes_annotated_jpa_entities() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://annotated-entity", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/model/Customer.java",
                        "content": """
@jakarta.persistence.Entity
@jakarta.persistence.Table(name = "customers")
class Customer {
    private String id;
}
""",
                    }
                ],
            }
        )
    )

    entities = [claim for claim in evidence.claims if claim.kind == "entity"]
    columns = [claim for claim in evidence.claims if claim.kind == "table_column"]
    assert [(claim.class_name, claim.table_ref) for claim in entities] == [
        ("Customer", "table://customers")
    ]
    assert [(claim.field_name, claim.column_name) for claim in columns] == [("id", "id")]


def test_java_spring_poc_honors_explicit_jpa_column_names() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://jpa-column-name", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/entity/CustomerEntity.java",
                        "content": """
@Entity
class CustomerEntity {
    @Column(name = "customer_code")
    private String code;
}
""",
                    }
                ],
            }
        )
    )

    columns = [claim for claim in evidence.claims if claim.kind == "table_column"]
    assert [(claim.field_name, claim.column_name) for claim in columns] == [
        ("code", "customer_code")
    ]


def test_java_spring_poc_excludes_transient_entity_fields() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://transient-fields", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/entity/CustomerEntity.java",
                        "content": """
@Entity
class CustomerEntity {
    private transient String javaCache;

    @Transient
    private String jpaCache;

    private String status;
}
""",
                    }
                ],
            }
        )
    )

    columns = [claim for claim in evidence.claims if claim.kind == "table_column"]
    assert [(claim.field_name, claim.column_name) for claim in columns] == [("status", "status")]


def test_java_spring_poc_marks_jpa_property_access_incomplete() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://property-access", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/entity/CustomerEntity.java",
                        "content": """
@Entity
@jakarta.persistence.Access(jakarta.persistence.AccessType.PROPERTY)
class CustomerEntity {
    private String code;

    @Column(name = "customer_code")
    public String getCode() { return code; }
}
""",
                    },
                    {
                        "path": "src/main/java/example/entity/AccountEntity.java",
                        "content": """
@Entity
class AccountEntity {
    private String id;

    @javax.persistence.Id
    public String getId() { return id; }
}
""",
                    },
                    {
                        "path": "src/main/java/example/model/FieldAccessEntity.java",
                        "content": """
@Entity
@Access(AccessType.FIELD)
class FieldAccessEntity {
    @Id
    private String id;
}
""",
                    },
                ],
            }
        )
    )

    assert {claim.class_name for claim in evidence.claims if claim.kind == "entity"} == {
        "AccountEntity",
        "CustomerEntity",
        "FieldAccessEntity",
    }
    assert [
        (claim.field_name, claim.column_name)
        for claim in evidence.claims
        if claim.kind == "table_column"
    ] == [("id", "id")]
    assert any(
        warning.code == "JAVA_POC_INCOMPLETE_PROPERTY_ACCESS"
        and "AccountEntity" in warning.message
        and "CustomerEntity" in warning.message
        and "不完整" in warning.message
        for warning in evidence.warnings
    )


def test_java_spring_poc_preserves_explicit_jpa_table_schemas() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://jpa-table-schema", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/entity/OrderEntity.java",
                        "content": """
@Entity
@Table(name = "orders", schema = "sales")
class OrderEntity {
    private String id;
}
""",
                    }
                ],
            }
        )
    )

    entity = next(claim for claim in evidence.claims if claim.kind == "entity")
    columns = [claim for claim in evidence.claims if claim.kind == "table_column"]
    assert entity.table_ref == "table://sales/orders"
    assert {claim.table_ref for claim in columns} == {"table://sales/orders"}


def test_java_spring_poc_marks_inherited_type_analysis_incomplete() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://inherited-fields", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController {
    @GetMapping("/orders")
    OrderDto load() {
        return orderService.load();
    }
}
""",
                    },
                    {
                        "path": "src/main/java/example/BaseDto.java",
                        "content": "class BaseDto { protected String tenantId; }",
                    },
                    {
                        "path": "src/main/java/example/OrderDto.java",
                        "content": "class OrderDto extends BaseDto { private String status; }",
                    },
                    {
                        "path": "src/main/java/example/entity/BaseEntity.java",
                        "content": "class BaseEntity { protected String id; }",
                    },
                    {
                        "path": "src/main/java/example/entity/OrderEntity.java",
                        "content": (
                            "class OrderEntity extends BaseEntity { private String status; }"
                        ),
                    },
                ],
            }
        )
    )

    assert any(
        warning.code == "JAVA_POC_INCOMPLETE_INHERITANCE"
        and "OrderDto" in warning.message
        and "OrderEntity" in warning.message
        and "不完整" in warning.message
        for warning in evidence.warnings
    )
    assert evidence.deterministic is False


def test_java_spring_poc_marks_inherited_controller_routes_incomplete() -> None:
    evidence = JavaSpringPocProvider().analyze(
        JavaSourceSnapshot.model_validate(
            {
                "provider": {"name": "java-spring-poc", "version": "0.1.0"},
                "source": {"ref": "repository://inherited-routes", "revision": "fixture-v1"},
                "subject_ref": SUBJECT_REF,
                "files": [
                    {
                        "path": "src/main/java/example/OrderController.java",
                        "content": """
@RestController
class OrderController extends BaseOrderController {
    @GetMapping("/own")
    Order own() { return orderService.own(); }
}

class BaseOrderController {
    @GetMapping("/inherited")
    Order inherited() { return orderService.inherited(); }
}
""",
                    }
                ],
            }
        )
    )

    routes = [claim for claim in evidence.claims if claim.kind == "controller_route"]
    assert [(claim.handler, claim.path) for claim in routes] == [("own", "/own")]
    assert evidence.deterministic is False
    assert any(
        warning.code == "JAVA_POC_INCOMPLETE_INHERITANCE"
        and "OrderController" in warning.message
        and "控制器父类路由" in warning.message
        for warning in evidence.warnings
    )


def test_ruoyi_full_golden_target_poc_without_execution() -> None:
    target = cast(dict[str, Any], json.loads((FIXTURE_ROOT / "ruoyi-target.json").read_text()))
    if not RUOYI_ROOT.exists():
        pytest.skip("本地 RuoYi Golden Target 未提供; CI 使用固定 small-spring Fixture")
    paths = cast(list[str], target["poc_files"])
    snapshot = JavaSourceSnapshot.model_validate(
        {
            "provider": {"name": "java-spring-poc", "version": "0.1.0"},
            "source": {
                "ref": str(target["source_ref"]),
                "revision": str(target["source_revision"]),
            },
            "subject_ref": SUBJECT_REF,
            "files": [
                {"path": relative_path, "content": (RUOYI_ROOT / relative_path).read_text()}
                for relative_path in paths
            ],
        }
    )

    evidence = JavaSpringPocProvider().analyze(snapshot)
    claim_kinds = {claim.kind for claim in evidence.claims}

    assert target["execute_analyzed_code"] is False
    assert snapshot.execute_analyzed_code is False
    assert set(cast(list[str], target["expected_claim_kinds"])) <= claim_kinds
    assert any(
        claim.kind == "controller_route"
        and claim.method == target["expected_route"]["method"]
        and claim.path == target["expected_route"]["path"]
        for claim in evidence.claims
    )
    assert any(
        claim.kind == "entity" and claim.table_ref == target["expected_table_ref"]
        for claim in evidence.claims
    )


def _mapping_inputs(envelope: ExternalEvidenceEnvelope, prefix: str) -> list[MappingEvidenceInput]:
    return [
        MappingEvidenceInput(
            evidence_ref=f"evidence://{prefix}/{index}",
            finding=finding,
            confidence=min(finding.confidence, envelope.confidence),
            deterministic=finding.deterministic and envelope.deterministic,
        )
        for index, finding in enumerate(envelope.findings)
    ]


def _database_envelope_with_distribution_update(
    update: dict[str, Any],
    *,
    nullable: bool | None = None,
) -> dict[str, Any]:
    source_payload = _database_submission()
    if nullable is not None:
        source_payload["tables"][0]["columns"][1]["nullable"] = nullable
    envelope = adapt_database_evidence(DatabaseEvidenceSubmission.model_validate(source_payload))
    finding_index, finding = next(
        (index, finding)
        for index, finding in enumerate(envelope.findings)
        if isinstance(finding.structured_data, DatabaseExternalEvidenceStructuredData)
        and isinstance(finding.structured_data.claim, ExternalDatabaseColumnClaim)
        and finding.structured_data.claim.name == "status"
    )
    structured_data = cast(DatabaseExternalEvidenceStructuredData, finding.structured_data)
    claim = cast(ExternalDatabaseColumnClaim, structured_data.claim)
    assert claim.observed_distribution is not None
    distribution = claim.observed_distribution.model_copy(update=update)
    changed_claim = claim.model_copy(update={"observed_distribution": distribution})
    changed_structured_data = structured_data.model_copy(update={"claim": changed_claim})
    provisional = finding.model_copy(
        update={
            "structured_data": changed_structured_data,
            "semantic_fingerprint": "0" * 64,
        }
    )
    changed_finding = provisional.model_copy(
        update={"semantic_fingerprint": finding_semantic_fingerprint(provisional)}
    )
    findings = list(envelope.findings)
    findings[finding_index] = changed_finding
    return envelope.model_copy(update={"findings": findings}).model_dump(mode="json")


def _java_submission() -> dict[str, Any]:
    operation_ref = "operation://POST/api/orders"
    common = {"confidence": 0.96, "deterministic": True}
    return {
        "schema_version": "flowtest-java-evidence-v1",
        "provider": {"name": "external-code-mcp", "version": "2.1.0"},
        "source": {"ref": "repository://orders-service", "revision": "a1b2c3d4"},
        "subject_ref": SUBJECT_REF,
        "claims": [
            {
                **common,
                "id": "route-create",
                "kind": "controller_route",
                "source_path": "src/OrderController.java:20",
                "operation_ref": operation_ref,
                "controller_ref": "java://OrderController",
                "handler": "create",
                "method": "POST",
                "path": "/api/orders",
            },
            {
                **common,
                "id": "request-product",
                "kind": "dto_field",
                "source_path": "src/CreateOrderRequest.java:4",
                "operation_ref": operation_ref,
                "direction": "request",
                "dto_type": "CreateOrderRequest",
                "field_name": "productId",
                "field_type": "String",
            },
            {
                **common,
                "id": "response-id",
                "kind": "dto_field",
                "source_path": "src/OrderDto.java:3",
                "operation_ref": operation_ref,
                "direction": "response",
                "dto_type": "OrderDto",
                "field_name": "id",
                "field_type": "String",
            },
            {
                **common,
                "id": "validation-quantity",
                "kind": "bean_validation",
                "source_path": "src/CreateOrderRequest.java:5",
                "operation_ref": operation_ref,
                "dto_type": "CreateOrderRequest",
                "field_name": "quantity",
                "annotation": "Max",
                "constraint": "maximum=10",
            },
            {
                **common,
                "id": "service-create",
                "kind": "service_call",
                "source_path": "src/OrderController.java:22",
                "operation_ref": operation_ref,
                "caller_ref": "java://OrderController.create",
                "callee_ref": "java://OrderService.create",
            },
            {
                **common,
                "id": "feign-inventory",
                "kind": "feign_call",
                "source_path": "src/OrderService.java:30",
                "operation_ref": operation_ref,
                "caller_ref": "java://OrderService.create",
                "callee_ref": "feign://inventory/reserve",
            },
            {
                **common,
                "id": "repository-save",
                "kind": "mapper_repository",
                "source_path": "src/OrderRepository.java:8",
                "operation_ref": operation_ref,
                "repository_ref": "java://OrderRepository",
                "method_ref": "java://OrderRepository.save",
                "entity_ref": "entity://Order",
            },
            {
                **common,
                "id": "entity-order",
                "kind": "entity",
                "source_path": "src/Order.java:4",
                "entity_ref": "entity://Order",
                "class_name": "Order",
                "table_ref": "table://public.orders",
                "operation_refs": [operation_ref],
            },
            {
                **common,
                "id": "column-product",
                "kind": "table_column",
                "source_path": "src/Order.java:8",
                "entity_ref": "entity://Order",
                "table_ref": "table://public.orders",
                "field_name": "productId",
                "column_name": "product_id",
            },
            {
                **common,
                "id": "state-order",
                "kind": "enum_state",
                "source_path": "src/OrderStatus.java:3",
                "operation_ref": operation_ref,
                "enum_ref": "java://OrderStatus",
                "field_name": "status",
                "values": ["created", "cancelled"],
            },
            {
                **common,
                "id": "exception-order",
                "kind": "exception",
                "source_path": "src/OrderService.java:40",
                "operation_ref": operation_ref,
                "exception_type": "OrderNotFoundException",
                "outcome": "not_found",
            },
            {
                **common,
                "id": "event-order",
                "kind": "kafka_event",
                "source_path": "src/OrderService.java:45",
                "operation_ref": operation_ref,
                "direction": "produce",
                "topic_ref": "kafka://orders.created",
                "event_type": "OrderCreated",
            },
        ],
        "confidence": 0.96,
        "deterministic": True,
        "redactions": [],
        "warnings": [],
    }


def _add_archived_order_entity(payload: dict[str, Any]) -> None:
    payload["claims"].append(
        {
            "id": "entity-archived-order",
            "kind": "entity",
            "source_path": "src/ArchivedOrder.java:4",
            "confidence": 0.96,
            "deterministic": True,
            "entity_ref": "entity://ArchivedOrder",
            "class_name": "ArchivedOrder",
            "table_ref": "table://public.archived_orders",
            "operation_refs": ["operation://POST/api/orders"],
        }
    )


def _database_submission() -> dict[str, Any]:
    return {
        "schema_version": "flowtest-database-evidence-v1",
        "provider": {"name": "external-database-mcp", "version": "3.0.0"},
        "source": {"ref": "database-profile://orders", "revision": "schema-v1"},
        "subject_ref": SUBJECT_REF,
        "tables": [
            {
                "schema_name": "public",
                "name": "orders",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "uuid",
                        "nullable": False,
                        "primary_key": True,
                        "unique": True,
                        "masked_example": "***0001",
                    },
                    {
                        "name": "status",
                        "data_type": "varchar",
                        "nullable": False,
                        "check_expression": "status IN ('created', 'cancelled')",
                        "observed_distribution": {
                            "row_count": 1000,
                            "distinct_count": 2,
                            "null_ratio": 0,
                            "enum_candidates": ["created", "cancelled"],
                        },
                        "masked_example": "***ated",
                    },
                    {
                        "name": "product_id",
                        "data_type": "uuid",
                        "nullable": False,
                        "foreign_key": "public.products.id",
                        "masked_example": "***1001",
                    },
                    {
                        "name": "customer_id",
                        "data_type": "uuid",
                        "nullable": False,
                        "foreign_key": "public.customers.id",
                        "masked_example": "***2001",
                    },
                ],
            }
        ],
        "confidence": 0.99,
        "deterministic": True,
        "redactions": [],
        "warnings": [],
    }


def _two_operation_java_submission() -> dict[str, Any]:
    common = {"confidence": 0.9, "deterministic": True}
    claims: list[dict[str, Any]] = []
    for suffix, path, table in (
        ("current", "/api/orders", "orders"),
        ("archive", "/api/order-archives", "order_archives"),
    ):
        operation_ref = f"operation://GET{path}"
        claims.extend(
            [
                {
                    **common,
                    "id": f"route-{suffix}",
                    "kind": "controller_route",
                    "source_path": f"src/{suffix}/OrderController.java:10",
                    "operation_ref": operation_ref,
                    "controller_ref": f"java://{suffix}/OrderController",
                    "handler": f"get{suffix.title()}",
                    "method": "GET",
                    "path": path,
                },
                {
                    **common,
                    "id": f"field-{suffix}",
                    "kind": "dto_field",
                    "source_path": "src/SharedOrderDto.java:3",
                    "operation_ref": operation_ref,
                    "direction": "response",
                    "dto_type": "SharedOrderDto",
                    "field_name": "id",
                    "field_type": "String",
                },
                {
                    **common,
                    "id": f"entity-{suffix}",
                    "kind": "entity",
                    "source_path": f"src/{suffix}/OrderEntity.java:3",
                    "entity_ref": f"entity://{suffix}/Order",
                    "class_name": table,
                    "table_ref": f"table://public/{table}",
                    "operation_refs": [operation_ref],
                },
            ]
        )
    return {
        "schema_version": "flowtest-java-evidence-v1",
        "provider": {"name": "external-code-mcp", "version": "2.1.0"},
        "source": {"ref": "repository://orders-service", "revision": "two-operations"},
        "subject_ref": SUBJECT_REF,
        "claims": claims,
        "confidence": 0.9,
        "deterministic": True,
        "redactions": [],
        "warnings": [],
    }


def _two_table_database_submission() -> dict[str, Any]:
    return {
        "schema_version": "flowtest-database-evidence-v1",
        "provider": {"name": "external-database-mcp", "version": "3.0.0"},
        "source": {"ref": "database-profile://orders", "revision": "two-tables"},
        "subject_ref": SUBJECT_REF,
        "tables": [
            {
                "schema_name": "public",
                "name": table,
                "columns": [
                    {
                        "name": "id",
                        "data_type": "uuid",
                        "nullable": False,
                        "primary_key": True,
                        "masked_example": "***0001",
                    }
                ],
            }
            for table in ("orders", "order_archives")
        ],
        "confidence": 0.9,
        "deterministic": True,
        "redactions": [],
        "warnings": [],
    }
