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
