import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "FlowTest API",
        "version": "3.0.0-beta.3-dev.29",
    }


@pytest.mark.asyncio
async def test_v2_features_are_disabled_by_default() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/features")

    assert response.status_code == 200
    assert response.json() == {
        "teams": False,
        "test_assets": False,
        "advanced_workflows": False,
        "data_nodes": False,
        "contract_testing": False,
        "quality_center": False,
        "oidc": False,
        "ai": False,
        "multi_protocol": False,
        "event_protocols": False,
        "performance_lab": False,
    }


@pytest.mark.asyncio
async def test_metrics_endpoint_uses_prometheus_text_format() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/health")
        response = await client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "flowtest_http_requests_total" in response.text
    assert 'path="/api/v1/health"' in response.text
