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
