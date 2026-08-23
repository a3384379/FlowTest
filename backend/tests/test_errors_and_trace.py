from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError
from app.main import app


@app.get("/_test/error")
async def raise_test_error() -> None:
    raise AppError(code="TEST_ERROR", message="测试错误", status_code=409)


async def test_trace_id_is_preserved() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/live", headers={"X-Trace-ID": "test-trace"})

    assert response.status_code == 200
    assert response.headers["X-Trace-ID"] == "test-trace"


async def test_error_envelope_contains_trace_id() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_test/error", headers={"X-Trace-ID": "error-trace"})

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "TEST_ERROR",
            "message": "测试错误",
            "details": None,
            "trace_id": "error-trace",
        }
    }


async def test_validation_error_does_not_echo_sensitive_input() -> None:
    transport = ASGITransport(app=app)
    marker = "sensitive-password-marker"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            headers={"X-Trace-ID": "validation-trace"},
            json={"email": "admin@flowtest.dev", "password": [marker]},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["trace_id"] == "validation-trace"
    assert payload["error"]["details"][0]["input"] == "***"
    assert marker not in response.text


async def test_unknown_api_error_uses_standard_envelope() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/does-not-exist",
            headers={"X-Trace-ID": "not-found-trace"},
        )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "资源不存在",
            "details": None,
            "trace_id": "not-found-trace",
        }
    }
