from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_readiness_reports_dependencies() -> None:
    transport = ASGITransport(app=app)
    patches = (
        patch("app.api.v1.endpoints.health.check_database", new=AsyncMock()),
        patch("app.api.v1.endpoints.health.check_redis", new=AsyncMock()),
        patch("app.api.v1.endpoints.health.check_storage", new=AsyncMock()),
    )
    with patches[0], patches[1], patches[2]:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok", "storage": "ok"},
    }


async def test_readiness_returns_503_when_dependency_fails() -> None:
    transport = ASGITransport(app=app)
    with (
        patch(
            "app.api.v1.endpoints.health.check_database",
            new=AsyncMock(side_effect=ConnectionError("offline")),
        ),
        patch("app.api.v1.endpoints.health.check_redis", new=AsyncMock()),
        patch("app.api.v1.endpoints.health.check_storage", new=AsyncMock()),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["database"] == "error"
