from app.domain.scopes import (
    HeaderScope,
    VariableScope,
    resolve_headers,
    resolve_variables,
)


def test_variable_precedence_and_source() -> None:
    resolved = resolve_variables(
        {
            VariableScope.GLOBAL: {"baseUrl": "https://global", "shared": "global"},
            VariableScope.ENVIRONMENT: {"baseUrl": "https://test", "shared": "test"},
            VariableScope.RUNTIME: {"shared": "runtime"},
        }
    )

    assert resolved["baseUrl"].value == "https://test"
    assert resolved["baseUrl"].source is VariableScope.ENVIRONMENT
    assert resolved["shared"].value == "runtime"
    assert resolved["shared"].source is VariableScope.RUNTIME


def test_header_precedence_and_source() -> None:
    resolved = resolve_headers(
        {
            HeaderScope.SYSTEM: {"Content-Type": "application/json"},
            HeaderScope.PROJECT: {"X-Source": "project"},
            HeaderScope.API: {"X-Source": "api"},
        }
    )

    assert resolved["Content-Type"].source is HeaderScope.SYSTEM
    assert resolved["X-Source"].value == "api"
    assert resolved["X-Source"].source is HeaderScope.API
