from base64 import urlsafe_b64encode

import pytest
from cryptography.exceptions import InvalidTag

from app.core.encryption import SecretBox
from app.domain.api_assets import merge_headers, render_json, render_template
from app.domain.scopes import HeaderScope, ResolvedValue, VariableScope


def test_secret_box_uses_authenticated_encryption() -> None:
    key = urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    box = SecretBox(key)
    encrypted = box.encrypt("sensitive", associated_data=b"project:secret")

    assert encrypted.ciphertext != b"sensitive"
    assert len(encrypted.nonce) == 12
    assert box.decrypt(encrypted, associated_data=b"project:secret") == "sensitive"
    with pytest.raises(InvalidTag):
        box.decrypt(encrypted, associated_data=b"different")


def test_template_rendering_is_recursive_and_reports_all_missing_names() -> None:
    variables = {
        "tenant": ResolvedValue("commerce", VariableScope.PROJECT),
        "user_id": ResolvedValue("42", VariableScope.RUNTIME),
    }

    assert render_template("/{{ tenant }}/users/{{user_id}}", variables) == "/commerce/users/42"
    assert render_json({"id": "{{user_id}}", "nested": ["{{tenant}}", 1]}, variables) == {
        "id": "42",
        "nested": ["commerce", 1],
    }
    with pytest.raises(ValueError, match="first, second"):
        render_template("{{second}}/{{first}}", variables)


def test_header_merge_is_case_insensitive_and_keeps_winning_source() -> None:
    headers = merge_headers(
        {
            HeaderScope.SYSTEM: {"X-Trace": "system"},
            HeaderScope.PROJECT: {"x-trace": "project"},
            HeaderScope.RUNTIME: {"X-TRACE": "runtime"},
        }
    )

    assert len(headers) == 1
    assert headers["x-trace"].name == "X-TRACE"
    assert headers["x-trace"].value == "runtime"
    assert headers["x-trace"].source is HeaderScope.RUNTIME
