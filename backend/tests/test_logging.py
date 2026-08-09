from app.core.logging import redact


def test_sensitive_values_are_redacted_recursively() -> None:
    payload = {
        "username": "tester",
        "password": "hidden",
        "headers": {"Authorization": "Bearer secret", "X-Trace-ID": "trace"},
        "api_key": "key-value",
        "items": [{"token": "secret"}],
    }

    assert redact(payload) == {
        "username": "tester",
        "password": "***",
        "headers": {"Authorization": "***", "X-Trace-ID": "trace"},
        "api_key": "***",
        "items": [{"token": "***"}],
    }


def test_composite_names_and_sensitive_extract_values_are_redacted() -> None:
    assert redact(
        {
            "session_token": "private",
            "accessToken": "private",
            "variable": "order_secret",
            "value": "private",
            "safe_value": "visible",
        }
    ) == {
        "session_token": "***",
        "accessToken": "***",
        "variable": "order_secret",
        "value": "***",
        "safe_value": "visible",
    }
