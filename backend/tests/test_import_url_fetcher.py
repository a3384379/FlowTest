import httpx
import pytest

from app.core.errors import AppError
from app.domain.network import OutboundNetworkPolicy
from app.http.imports import HttpImportDocumentFetcher
from app.services.outbound import OutboundRequestGuard


async def _public_address(_hostname: str, _port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _fetcher(handler: httpx.MockTransport) -> HttpImportDocumentFetcher:
    return HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=_public_address),
        transport=handler,
    )


@pytest.mark.asyncio
async def test_url_fetcher_revalidates_redirect_and_reads_document() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/docs":
            return httpx.Response(302, headers={"Location": "/openapi.json"})
        return httpx.Response(
            200,
            json={"openapi": "3.0.3", "info": {"title": "Demo"}, "paths": {}},
        )

    fetched = await _fetcher(httpx.MockTransport(handler)).fetch(
        url="https://api.example.com/docs",
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=4096,
    )

    assert requested_paths == ["/docs", "/openapi.json"]
    assert fetched.resolved_url == "https://api.example.com/openapi.json"
    assert fetched.source_name == "api.example.com/openapi.json"
    assert fetched.discovered_from_page is False
    assert b'"openapi":"3.0.3"' in fetched.content


@pytest.mark.asyncio
async def test_url_fetcher_discovers_fastapi_inline_configuration() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/docs":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text=("<!doctype html><script>SwaggerUIBundle({url: '/openapi.json'});</script>"),
            )
        return httpx.Response(
            200,
            json={"openapi": "3.1.0", "info": {"title": "FastAPI"}, "paths": {}},
        )

    fetcher = _fetcher(httpx.MockTransport(handler))
    discovery = await fetcher.discover(
        url="https://api.example.com/docs",
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=4096,
    )
    assert discovery.source_kind == "swagger_ui"
    assert discovery.source_url == "https://api.example.com/docs"
    assert [(item.name, item.display_url) for item in discovery.documents] == [
        ("openapi.json", "https://api.example.com/openapi.json")
    ]

    fetched = await fetcher.fetch(
        url="https://api.example.com/docs",
        document_id=discovery.documents[0].id,
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=4096,
    )
    assert requested_paths == ["/docs", "/docs", "/openapi.json"]
    assert fetched.discovered_from_page is True
    assert fetched.document_id == discovery.documents[0].id


@pytest.mark.asyncio
async def test_url_fetcher_discovers_springdoc_groups_without_exposing_queries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/swagger-ui/index.html":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text='<script src="./swagger-initializer.js"></script>',
            )
        if request.url.path == "/swagger-ui/swagger-initializer.js":
            return httpx.Response(
                200,
                text="SwaggerUIBundle({configUrl: '/v3/api-docs/swagger-config'});",
            )
        if request.url.path == "/v3/api-docs/swagger-config":
            return httpx.Response(
                200,
                json={
                    "urls": [
                        {"name": "用户服务", "url": "/v3/api-docs/users?token=private"},
                        {"name": "订单服务", "url": "/v3/api-docs/orders"},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"openapi": "3.0.3", "info": {"title": "Group"}, "paths": {}},
        )

    fetcher = _fetcher(httpx.MockTransport(handler))
    discovery = await fetcher.discover(
        url="https://api.example.com/swagger-ui/index.html",
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=8192,
    )

    assert discovery.source_kind == "swagger_ui"
    assert [(item.name, item.display_url) for item in discovery.documents] == [
        ("用户服务", "https://api.example.com/v3/api-docs/users"),
        ("订单服务", "https://api.example.com/v3/api-docs/orders"),
    ]
    assert all("private" not in item.display_url for item in discovery.documents)
    fetched = await fetcher.fetch(
        url="https://api.example.com/swagger-ui/index.html",
        document_id=discovery.documents[1].id,
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=8192,
    )
    assert fetched.source_name == "api.example.com/订单服务"
    assert fetched.resolved_url == "https://api.example.com/v3/api-docs/orders"


@pytest.mark.asyncio
async def test_url_fetcher_falls_back_to_knife4j_swagger_config() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/service/doc.html":
            return httpx.Response(200, headers={"Content-Type": "text/html"}, text="<html></html>")
        if request.url.path == "/v3/api-docs/swagger-config":
            return httpx.Response(200, json={"url": "/v3/api-docs"})
        return httpx.Response(404)

    discovery = await _fetcher(httpx.MockTransport(handler)).discover(
        url="https://api.example.com/service/doc.html",
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=8192,
    )

    assert requested_paths[:3] == [
        "/service/doc.html",
        "/service/v3/api-docs/swagger-config",
        "/v3/api-docs/swagger-config",
    ]
    assert [(item.name, item.display_url) for item in discovery.documents] == [
        ("api-docs", "https://api.example.com/v3/api-docs")
    ]


@pytest.mark.asyncio
async def test_url_fetcher_rejects_unrecognized_html_and_large_documents() -> None:
    html_fetcher = _fetcher(
        httpx.MockTransport(lambda _request: httpx.Response(200, text="<html>Swagger UI</html>"))
    )
    with pytest.raises(AppError) as html_error:
        await html_fetcher.fetch(
            url="https://api.example.com/docs",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=4096,
        )
    assert html_error.value.code == "IMPORT_URL_DOCUMENT_NOT_FOUND"

    large_fetcher = _fetcher(
        httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 9))
    )
    with pytest.raises(AppError) as large_error:
        await large_fetcher.fetch(
            url="https://api.example.com/openapi.json",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=8,
        )
    assert large_error.value.code == "IMPORT_TOO_LARGE"


@pytest.mark.asyncio
async def test_url_fetcher_blocks_loopback_before_request() -> None:
    requested = False

    async def loopback(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("127.0.0.1",)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, json={})

    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=loopback),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AppError) as error:
        await fetcher.fetch(
            url="http://localhost/openapi.json",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=4096,
        )
    assert error.value.code == "OUTBOUND_REQUEST_BLOCKED"
    assert requested is False
