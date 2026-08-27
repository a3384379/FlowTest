import httpx
import pytest

from app.core.errors import AppError
from app.domain.network import OutboundNetworkPolicy
from app.http.imports import HttpImportDocumentFetcher
from app.services.outbound import OutboundRequestGuard


async def _public_address(_hostname: str, _port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _fetcher(
    handler: httpx.MockTransport,
    *,
    peer_address: str = "93.184.216.34",
) -> HttpImportDocumentFetcher:
    return HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=_public_address),
        transport=handler,
        peer_address_provider=lambda _response: peer_address,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "peer_address",
    ("127.0.0.1", "169.254.1.10", "10.0.0.10", "1.1.1.1"),
)
async def test_url_fetcher_rejects_connected_peer_that_differs_from_validated_dns(
    peer_address: str,
) -> None:
    fetcher = _fetcher(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"openapi": "3.0.3"})),
        peer_address=peer_address,
    )

    with pytest.raises(AppError) as rejected:
        await fetcher.fetch(
            url="https://api.example.com/openapi.json",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=4096,
        )

    assert rejected.value.code == "DNS_REBINDING_BLOCKED"


@pytest.mark.asyncio
async def test_url_fetcher_revalidates_connected_peer_after_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/docs":
            return httpx.Response(302, headers={"Location": "/openapi.json"})
        return httpx.Response(200, json={"openapi": "3.0.3"})

    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=_public_address),
        transport=httpx.MockTransport(handler),
        peer_address_provider=lambda response: (
            "127.0.0.1" if response.request.url.path == "/openapi.json" else "93.184.216.34"
        ),
    )

    with pytest.raises(AppError) as rejected:
        await fetcher.fetch(
            url="https://api.example.com/docs",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=4096,
        )

    assert rejected.value.code == "DNS_REBINDING_BLOCKED"


@pytest.mark.asyncio
async def test_url_fetcher_blocks_redirect_to_private_network_before_request() -> None:
    requested_hosts: list[str] = []

    async def addresses(hostname: str, _port: int) -> tuple[str, ...]:
        return ("10.0.0.10",) if hostname == "private.example.com" else ("93.184.216.34",)

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(
            302,
            headers={"Location": "https://private.example.com/openapi.json"},
        )

    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=addresses),
        transport=httpx.MockTransport(handler),
        peer_address_provider=lambda _response: "93.184.216.34",
    )

    with pytest.raises(AppError) as rejected:
        await fetcher.fetch(
            url="https://api.example.com/docs",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=4096,
        )

    assert rejected.value.code == "OUTBOUND_REQUEST_BLOCKED"
    assert requested_hosts == ["api.example.com"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rebound_path",
    ("/swagger-initializer.js", "/v3/api-docs/swagger-config", "/v3/api-docs"),
)
async def test_url_fetcher_revalidates_swagger_discovery_assets_and_final_document(
    rebound_path: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/docs":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text='<script src="/swagger-initializer.js"></script>',
            )
        if request.url.path == "/swagger-initializer.js":
            return httpx.Response(
                200,
                text="SwaggerUIBundle({configUrl: '/v3/api-docs/swagger-config'});",
            )
        if request.url.path == "/v3/api-docs/swagger-config":
            return httpx.Response(200, json={"url": "/v3/api-docs"})
        return httpx.Response(200, json={"openapi": "3.0.3"})

    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=_public_address),
        transport=httpx.MockTransport(handler),
        peer_address_provider=lambda response: (
            "10.0.0.10" if response.request.url.path == rebound_path else "93.184.216.34"
        ),
    )

    with pytest.raises(AppError) as rejected:
        await fetcher.fetch(
            url="https://api.example.com/docs",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=8192,
        )

    assert rejected.value.code == "DNS_REBINDING_BLOCKED"


@pytest.mark.asyncio
async def test_url_fetcher_allows_matching_private_peer_from_explicit_cidr() -> None:
    async def private_address(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("10.0.0.10",)

    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=private_address),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"openapi": "3.0.3"})
        ),
        peer_address_provider=lambda _response: "10.0.0.10",
    )

    fetched = await fetcher.fetch(
        url="https://private.example.com/openapi.json",
        network_policy=OutboundNetworkPolicy(allowed_private_cidrs=("10.0.0.0/24",)),
        maximum_bytes=4096,
    )

    assert fetched.resolved_url == "https://private.example.com/openapi.json"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata_peer",
    ("169.254.169.254", "::ffff:169.254.169.254", "fd00:ec2::254"),
)
async def test_url_fetcher_blocks_metadata_peer_when_policy_is_disabled(
    metadata_peer: str,
) -> None:
    async def metadata_address(_hostname: str, _port: int) -> tuple[str, ...]:
        return (metadata_peer,)

    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=metadata_address),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        peer_address_provider=lambda _response: metadata_peer,
    )

    with pytest.raises(AppError) as rejected:
        await fetcher.fetch(
            url="http://metadata.internal/openapi.json",
            network_policy=OutboundNetworkPolicy(enabled=False),
            maximum_bytes=4096,
        )

    assert rejected.value.code == "OUTBOUND_REQUEST_BLOCKED"


@pytest.mark.asyncio
async def test_url_fetcher_normalizes_ipv4_mapped_peer_address() -> None:
    fetcher = _fetcher(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"openapi": "3.0.3"})),
        peer_address="::ffff:93.184.216.34",
    )

    fetched = await fetcher.fetch(
        url="https://api.example.com/openapi.json",
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=4096,
    )

    assert fetched.resolved_url == "https://api.example.com/openapi.json"


@pytest.mark.asyncio
async def test_url_fetcher_validates_ipv6_connected_peers() -> None:
    async def ipv6_address(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("2606:4700:4700::1111",)

    success = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=ipv6_address),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"openapi": "3.0.3"})
        ),
        peer_address_provider=lambda _response: "2606:4700:4700::1111",
    )
    fetched = await success.fetch(
        url="https://ipv6.example.com/openapi.json",
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=4096,
    )
    assert fetched.resolved_url == "https://ipv6.example.com/openapi.json"

    rebound = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=ipv6_address),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        peer_address_provider=lambda _response: "::1",
    )
    with pytest.raises(AppError) as rejected:
        await rebound.fetch(
            url="https://ipv6.example.com/openapi.json",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=4096,
        )
    assert rejected.value.code == "DNS_REBINDING_BLOCKED"


@pytest.mark.asyncio
async def test_url_fetcher_fails_closed_when_connected_peer_is_unavailable() -> None:
    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=_public_address),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
    )

    with pytest.raises(AppError) as rejected:
        await fetcher.fetch(
            url="https://api.example.com/openapi.json",
            network_policy=OutboundNetworkPolicy(),
            maximum_bytes=4096,
        )

    assert rejected.value.code == "OUTBOUND_PEER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_url_fetcher_reads_default_peer_from_httpx_network_stream() -> None:
    class NetworkStream:
        def get_extra_info(self, name: str) -> tuple[str, int] | None:
            return ("93.184.216.34", 443) if name == "server_addr" else None

    fetcher = HttpImportDocumentFetcher(
        request_timeout_seconds=2,
        guard=OutboundRequestGuard(resolver=_public_address),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"openapi": "3.0.3"},
                extensions={"network_stream": NetworkStream()},
            )
        ),
    )

    fetched = await fetcher.fetch(
        url="https://api.example.com/openapi.json",
        network_policy=OutboundNetworkPolicy(),
        maximum_bytes=4096,
    )

    assert fetched.resolved_url == "https://api.example.com/openapi.json"
