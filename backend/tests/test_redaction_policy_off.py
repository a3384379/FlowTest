from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.core.logging import redact
from app.core.redaction import (
    RedactionMode,
    RedactionPolicy,
    get_redaction_policy,
    persisted_redaction_policy,
    reset_redaction_policy,
    set_redaction_policy,
)
from app.domain.ai import sanitize_ai_input
from app.domain.canonical_contracts import (
    contains_sensitive_contract_value,
    sanitize_contract_payload,
)
from app.domain.evidence import DataProfile
from app.domain.evidence_adapters import DatabaseColumnEvidence
from app.domain.flow_spec_security import contains_sensitive_flow_spec_value
from app.domain.test_contexts import ExternalDatabaseColumnClaim, is_sensitive_identifier
from app.importers.contracts import imported_value
from app.services.executions import _redact_request_url, _redact_response_headers


def _policy(mode: RedactionMode):
    return set_redaction_policy(RedactionPolicy(mode=mode, source="test", policy_version=1))


def test_off_does_not_scan_or_transform_sensitive_values() -> None:
    token = _policy(RedactionMode.OFF)
    try:
        payload = {"Authorization": "Bearer synthetic-token", "password": "plain"}
        assert redact(payload) is payload
        assert is_sensitive_identifier("password") is False
        assert contains_sensitive_contract_value(payload) is False
        assert _redact_request_url("https://example.test/items?token=plain") == (
            "https://example.test/items?token=plain"
        )
        assert _redact_response_headers({"Set-Cookie": "session=plain"}) == {
            "Set-Cookie": "session=plain"
        }
        assert imported_value("Authorization", "Bearer synthetic-token") == (
            "Bearer synthetic-token"
        )
        sanitized = sanitize_ai_input(schema_document=None, metadata=payload, sample=payload)
        assert sanitized.redacted_paths == ()
        assert sanitized.payload["metadata"] == payload
        assert json.dumps(sanitized.payload, ensure_ascii=False).count("synthetic-token") == 2
    finally:
        reset_redaction_policy(token)


def test_on_preserves_explicit_redaction_behavior() -> None:
    token = _policy(RedactionMode.ON)
    try:
        payload = {"Authorization": "Bearer synthetic-token", "password": "plain"}
        assert redact(payload) == {"Authorization": "***", "password": "***"}
        assert is_sensitive_identifier("password") is True
        assert contains_sensitive_contract_value(payload) is True
        assert imported_value("Authorization", "Bearer synthetic-token").startswith("{{secret.")
        assert imported_value("Authorization", "{{secret.IMPORTED_TOKEN}}") == (
            "{{secret.IMPORTED_TOKEN}}"
        )
        assert imported_value("Authorization", "secret://payments/token") == (
            "secret://payments/token"
        )
        sanitized = sanitize_ai_input(schema_document=None, metadata=payload, sample=None)
        assert sanitized.redacted_paths
        assert "synthetic-token" not in json.dumps(sanitized.payload, ensure_ascii=False)
    finally:
        reset_redaction_policy(token)


def test_off_contract_sanitizer_keeps_examples_and_enum_values() -> None:
    token = _policy(RedactionMode.OFF)
    try:
        payload = {
            "operation": "orders.get",
            "method": "GET",
            "path": "/orders",
            "parameters": [
                {
                    "name": "authorization",
                    "location": "header",
                    "schema": {"type": "string", "example": "Bearer synthetic-token"},
                    "example": "Bearer synthetic-token",
                }
            ],
            "responses": {},
        }
        result = sanitize_contract_payload(payload)
        assert result.redacted_count == 0
        assert result.payload["parameters"][0]["example"] == "Bearer synthetic-token"
        schema = result.payload["parameters"][0]["schema"]
        assert schema["example"] == "Bearer synthetic-token"
    finally:
        reset_redaction_policy(token)


def test_off_flow_spec_security_gate_does_not_block_sensitive_literals() -> None:
    token = _policy(RedactionMode.OFF)
    try:
        from app.domain.flow_spec import FlowSpec, FlowSpecNode, validate_flow_spec

        spec = FlowSpec(
            nodes=[
                FlowSpecNode(
                    id="start",
                    kind="start",
                    name="开始",
                    config={"password": "plain-token"},
                )
            ]
        )
        assert contains_sensitive_flow_spec_value(spec) is False
        assert not any(
            item.code == "SECRET_LITERAL_FORBIDDEN" for item in validate_flow_spec(spec).issues
        )
    finally:
        reset_redaction_policy(token)


def test_off_keeps_database_examples_unmodified() -> None:
    token = _policy(RedactionMode.OFF)
    try:
        profile = DataProfile.model_validate(
            {
                "source_ref": "db://profiles/public",
                "revision": "schema-47",
                "entity": "profiles",
                "columns": [
                    {
                        "name": "email",
                        "data_type": "varchar",
                        "nullable": False,
                        "masked_example": "alice@example.test",
                    }
                ],
            }
        )
        claim = ExternalDatabaseColumnClaim.model_validate(
            {
                "schema_name": "public",
                "table_name": "profiles",
                "name": "email",
                "data_type": "varchar",
                "nullable": False,
                "masked_example": "alice@example.test",
            }
        )
        adapter_column = DatabaseColumnEvidence.model_validate(
            {
                "name": "email",
                "data_type": "varchar",
                "nullable": False,
                "masked_example": "alice@example.test",
            }
        )
        assert profile.columns[0].masked_example == "alice@example.test"
        assert claim.masked_example == "alice@example.test"
        assert adapter_column.masked_example == "alice@example.test"
    finally:
        reset_redaction_policy(token)


def test_persisted_policy_does_not_follow_later_installation_changes() -> None:
    class QueuedRecord:
        redaction_mode = "on"
        redaction_policy_version = 7

    policy = persisted_redaction_policy(QueuedRecord())
    assert policy == RedactionPolicy(mode=RedactionMode.ON, source="execution", policy_version=7)


def test_policy_without_request_context_uses_installation_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "redaction_mode", "on")
    monkeypatch.setattr(settings, "redaction_policy_version", 9)
    assert get_redaction_policy() == RedactionPolicy(
        mode=RedactionMode.ON,
        source="installation",
        policy_version=9,
    )
