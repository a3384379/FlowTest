import hashlib
import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from app.core.errors import AppError
from app.domain.network import OutboundNetworkPolicy
from app.importers.sources import (
    FetchedImportDocument,
    ImportDocumentOption,
    ImportUrlDiscovery,
)
from app.services.outbound import OutboundRequestGuard

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 3
MAX_DISCOVERY_ASSETS = 8
MAX_DISCOVERY_DOCUMENTS = 20
DISCOVERY_ASSET_LIMIT_BYTES = 2 * 1024 * 1024
HTML_PREFIXES = (b"<!doctype html", b"<html")
CONFIG_URL_PATTERN = re.compile(
    r"(?:[\"']?configUrl[\"']?)\s*:\s*(?P<quote>[\"'])(?P<url>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
URL_PATTERN = re.compile(
    r"(?:^|[,{]\s*)(?:[\"']?url[\"']?)\s*:\s*"
    r"(?P<quote>[\"'])(?P<url>.*?)(?P=quote)",
    re.IGNORECASE | re.MULTILINE,
)
NAME_PATTERN = re.compile(
    r"(?:^|[,\s])(?:[\"']?name[\"']?)\s*:\s*"
    r"(?P<quote>[\"'])(?P<name>.*?)(?P=quote)",
    re.IGNORECASE | re.MULTILINE,
)
OBJECT_PATTERN = re.compile(r"\{(?P<body>[^{}]{0,4096})\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class _RetrievedResource:
    content: bytes
    resolved_url: str
    content_type: str


@dataclass(frozen=True, slots=True)
class _CandidateSeed:
    name: str | None
    url: str


PeerAddressProvider = Callable[[httpx.Response], str | None]


class _SwaggerScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []
        self.inline_scripts: list[str] = []
        self._inline_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        source = next((value for name, value in attrs if name.lower() == "src"), None)
        if source:
            self.sources.append(source)
        else:
            self._inline_parts = []

    def handle_data(self, data: str) -> None:
        if self._inline_parts is not None:
            self._inline_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._inline_parts is None:
            return
        self.inline_scripts.append("".join(self._inline_parts))
        self._inline_parts = None


class HttpImportDocumentFetcher:
    def __init__(
        self,
        *,
        request_timeout_seconds: float,
        guard: OutboundRequestGuard | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        peer_address_provider: PeerAddressProvider | None = None,
    ) -> None:
        self._timeout = request_timeout_seconds
        self._guard = guard or OutboundRequestGuard()
        self._transport = transport
        self._peer_address_provider = peer_address_provider or _httpx_peer_address

    async def discover(
        self,
        *,
        url: str,
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
    ) -> ImportUrlDiscovery:
        try:
            async with self._client() as client:
                discovery, _resource = await self._discover(
                    client=client,
                    url=url,
                    network_policy=network_policy,
                    maximum_bytes=maximum_bytes,
                )
                return discovery
        except httpx.TimeoutException as error:
            raise _timeout_error() from error
        except httpx.HTTPError as error:
            raise _fetch_error() from error

    async def fetch(
        self,
        *,
        url: str,
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
        document_id: str | None = None,
    ) -> FetchedImportDocument:
        try:
            async with self._client() as client:
                discovery, direct_resource = await self._discover(
                    client=client,
                    url=url,
                    network_policy=network_policy,
                    maximum_bytes=maximum_bytes,
                )
                selected = _select_document(discovery, document_id)
                resource = direct_resource or await self._retrieve(
                    client=client,
                    url=selected.url,
                    network_policy=network_policy,
                    maximum_bytes=maximum_bytes,
                )
                if _is_html(resource):
                    raise AppError(
                        code="IMPORT_URL_DOCUMENT_INVALID",
                        message="Swagger UI 配置指向的地址仍是网页, 未找到原始接口文档",
                        status_code=422,
                    )
                return FetchedImportDocument(
                    content=resource.content,
                    source_page_url=discovery.source_url,
                    resolved_url=resource.resolved_url,
                    source_name=_source_name(resource.resolved_url, selected.name),
                    document_id=selected.id,
                    discovered_from_page=discovery.source_kind == "swagger_ui",
                )
        except httpx.TimeoutException as error:
            raise _timeout_error() from error
        except httpx.HTTPError as error:
            raise _fetch_error() from error

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
        )

    async def _discover(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
    ) -> tuple[ImportUrlDiscovery, _RetrievedResource | None]:
        resource = await self._retrieve(
            client=client,
            url=url,
            network_policy=network_policy,
            maximum_bytes=maximum_bytes,
        )
        if not _is_html(resource):
            option = _document_option(None, resource.resolved_url)
            return (
                ImportUrlDiscovery(
                    source_url=_sanitized_url(resource.resolved_url),
                    source_kind="document",
                    documents=(option,),
                ),
                resource,
            )
        options = await self._discover_html_documents(
            client=client,
            resource=resource,
            network_policy=network_policy,
            maximum_bytes=maximum_bytes,
        )
        if not options:
            raise AppError(
                code="IMPORT_URL_DOCUMENT_NOT_FOUND",
                message="未能从 Swagger UI 页面发现 OpenAPI 文档地址",
                status_code=422,
            )
        return (
            ImportUrlDiscovery(
                source_url=_sanitized_url(resource.resolved_url),
                source_kind="swagger_ui",
                documents=options,
            ),
            None,
        )

    async def _discover_html_documents(
        self,
        *,
        client: httpx.AsyncClient,
        resource: _RetrievedResource,
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
    ) -> tuple[ImportDocumentOption, ...]:
        parser = _SwaggerScriptParser()
        parser.feed(resource.content.decode("utf-8", errors="replace"))
        document_seeds: list[_CandidateSeed] = []
        config_urls: list[str] = []
        for inline_script in parser.inline_scripts:
            seeds, configs = _script_candidates(inline_script, resource.resolved_url)
            document_seeds.extend(seeds)
            config_urls.extend(configs)
        for script_url in _interesting_script_urls(parser.sources, resource.resolved_url):
            script_resource = await self._retrieve(
                client=client,
                url=script_url,
                network_policy=network_policy,
                maximum_bytes=min(maximum_bytes, DISCOVERY_ASSET_LIMIT_BYTES),
            )
            seeds, configs = _script_candidates(
                script_resource.content.decode("utf-8", errors="replace"),
                script_resource.resolved_url,
            )
            document_seeds.extend(seeds)
            config_urls.extend(configs)
        fallback = not document_seeds and not config_urls
        if fallback:
            config_urls.extend(_fallback_discovery_urls(resource.resolved_url))
        document_seeds.extend(
            await self._config_document_seeds(
                client=client,
                config_urls=config_urls,
                network_policy=network_policy,
                maximum_bytes=maximum_bytes,
                ignore_not_found=fallback,
            )
        )
        return _deduplicated_options(document_seeds)

    async def _config_document_seeds(
        self,
        *,
        client: httpx.AsyncClient,
        config_urls: list[str],
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
        ignore_not_found: bool,
    ) -> list[_CandidateSeed]:
        seeds: list[_CandidateSeed] = []
        for config_url in _deduplicate(config_urls)[:MAX_DISCOVERY_ASSETS]:
            try:
                resource = await self._retrieve(
                    client=client,
                    url=config_url,
                    network_policy=network_policy,
                    maximum_bytes=min(maximum_bytes, DISCOVERY_ASSET_LIMIT_BYTES),
                )
            except AppError as error:
                if ignore_not_found and error.details == {"status_code": 404}:
                    continue
                raise
            seeds.extend(_json_config_candidates(resource.content, resource.resolved_url))
        return seeds

    async def _retrieve(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
    ) -> _RetrievedResource:
        current_url = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            validated_addresses = await self._guard.enforce(current_url, network_policy)
            async with client.stream(
                "GET",
                current_url,
                headers={
                    "Accept": (
                        "application/json, application/yaml, application/x-yaml, "
                        "text/yaml, text/html, text/plain;q=0.9"
                    )
                },
            ) as response:
                _validate_connected_peer(
                    self._peer_address_provider(response),
                    validated_addresses,
                )
                if response.status_code in REDIRECT_STATUSES:
                    current_url = _redirect_target(
                        current_url,
                        response.headers.get("location"),
                        redirect_count,
                    )
                    continue
                if response.status_code != 200:
                    raise AppError(
                        code="IMPORT_URL_FETCH_FAILED",
                        message=f"接口文档地址返回 HTTP {response.status_code}",
                        status_code=422,
                        details={"status_code": response.status_code},
                    )
                return _RetrievedResource(
                    content=await _read_limited(response, maximum_bytes),
                    resolved_url=str(response.url),
                    content_type=response.headers.get("content-type", ""),
                )
        raise AppError(
            code="IMPORT_URL_TOO_MANY_REDIRECTS",
            message=f"接口文档地址重定向超过 {MAX_REDIRECTS} 次",
            status_code=422,
        )


def _httpx_peer_address(response: httpx.Response) -> str | None:
    """Read the connected socket address exposed by HTTPX's network stream."""

    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return None
    server_address = get_extra_info("server_addr")
    if (
        not isinstance(server_address, tuple)
        or not server_address
        or not isinstance(server_address[0], str)
    ):
        return None
    return server_address[0]


def _validate_connected_peer(
    peer_address: str | None,
    validated_addresses: tuple[str, ...],
) -> None:
    try:
        if peer_address is None:
            raise ValueError("missing peer address")
        peer = _canonical_address(ipaddress.ip_address(peer_address))
        validated = {
            _canonical_address(ipaddress.ip_address(value)) for value in validated_addresses
        }
    except ValueError as error:
        raise AppError(
            code="OUTBOUND_PEER_UNAVAILABLE",
            message="无法验证接口文档地址的实际连接端",
            status_code=422,
        ) from error
    if _is_metadata_address(peer):
        raise AppError(
            code="OUTBOUND_REQUEST_BLOCKED",
            message="接口文档地址不能连接云元数据服务",
            status_code=422,
        )
    if peer not in validated:
        raise AppError(
            code="DNS_REBINDING_BLOCKED",
            message="接口文档地址的实际连接端与安全校验结果不一致",
            status_code=422,
        )


def _is_metadata_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return address in {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("fd00:ec2::254"),
    }


def _canonical_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _script_candidates(script: str, base_url: str) -> tuple[list[_CandidateSeed], list[str]]:
    seeds: list[_CandidateSeed] = []
    for object_match in OBJECT_PATTERN.finditer(script):
        body = object_match.group("body")
        url_match = URL_PATTERN.search("{" + body)
        if url_match is None:
            continue
        name_match = NAME_PATTERN.search(" " + body)
        candidate_url = _resolved_http_url(
            base_url,
            _decoded_js_value(url_match.group("url"), url_match.group("quote")),
        )
        if candidate_url:
            name = name_match.group("name") if name_match else None
            seeds.append(_CandidateSeed(name=name, url=candidate_url))
    for match in URL_PATTERN.finditer(script):
        candidate_url = _resolved_http_url(
            base_url,
            _decoded_js_value(match.group("url"), match.group("quote")),
        )
        if candidate_url:
            seeds.append(_CandidateSeed(name=None, url=candidate_url))
    configs = [
        candidate
        for match in CONFIG_URL_PATTERN.finditer(script)
        if (
            candidate := _resolved_http_url(
                base_url,
                _decoded_js_value(match.group("url"), match.group("quote")),
            )
        )
    ]
    return seeds, configs


def _json_config_candidates(content: bytes, base_url: str) -> list[_CandidateSeed]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("openapi"), str) or isinstance(payload.get("swagger"), str):
        return [_CandidateSeed(name=None, url=base_url)]
    seeds: list[_CandidateSeed] = []
    if isinstance(payload.get("url"), str):
        url = _resolved_http_url(base_url, payload["url"])
        if url:
            seeds.append(_CandidateSeed(name=None, url=url))
    groups = payload.get("urls")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("url"), str):
                continue
            url = _resolved_http_url(base_url, group["url"])
            if url:
                name = group.get("name") if isinstance(group.get("name"), str) else None
                seeds.append(_CandidateSeed(name=name, url=url))
    return seeds


def _interesting_script_urls(sources: list[str], base_url: str) -> list[str]:
    urls: list[str] = []
    for source in sources:
        filename = PurePosixPath(urlsplit(source).path).name.lower()
        if not any(marker in filename for marker in ("initializer", "swagger-ui-init")):
            continue
        resolved = _resolved_http_url(base_url, source)
        if resolved:
            urls.append(resolved)
    return _deduplicate(urls)[:MAX_DISCOVERY_ASSETS]


def _fallback_discovery_urls(page_url: str) -> list[str]:
    relative_paths = (
        "v3/api-docs/swagger-config",
        "/v3/api-docs/swagger-config",
        "v3/api-docs",
        "/v3/api-docs",
        "openapi.json",
        "/openapi.json",
        "v2/api-docs",
        "/v2/api-docs",
    )
    page_directory = urljoin(page_url, "./")
    return _deduplicate([urljoin(page_directory, path) for path in relative_paths])


def _deduplicated_options(seeds: list[_CandidateSeed]) -> tuple[ImportDocumentOption, ...]:
    by_url: dict[str, _CandidateSeed] = {}
    for seed in seeds:
        existing = by_url.get(seed.url)
        if existing is None or (not existing.name and seed.name):
            by_url[seed.url] = seed
    return tuple(
        _document_option(seed.name, seed.url)
        for seed in list(by_url.values())[:MAX_DISCOVERY_DOCUMENTS]
    )


def _document_option(name: str | None, url: str) -> ImportDocumentOption:
    normalized_name = (name or _resource_name(url)).strip()[:255] or "OpenAPI 文档"
    return ImportDocumentOption(
        id=hashlib.sha256(_canonical_url(url).encode()).hexdigest(),
        name=normalized_name,
        url=url,
        display_url=_sanitized_url(url),
    )


def _select_document(
    discovery: ImportUrlDiscovery, document_id: str | None
) -> ImportDocumentOption:
    if document_id is not None:
        selected = next(
            (document for document in discovery.documents if document.id == document_id),
            None,
        )
        if selected is None:
            raise AppError(
                code="IMPORT_URL_DOCUMENT_SELECTION_INVALID",
                message="选择的接口文档已失效, 请重新解析地址",
                status_code=409,
            )
        return selected
    if len(discovery.documents) == 1:
        return discovery.documents[0]
    raise AppError(
        code="IMPORT_URL_DOCUMENT_SELECTION_REQUIRED",
        message="该 Swagger UI 包含多份接口文档, 请先选择要导入的分组",
        status_code=422,
    )


def _redirect_target(current_url: str, location: str | None, redirect_count: int) -> str:
    if location is None:
        raise AppError(
            code="IMPORT_URL_REDIRECT_INVALID",
            message="接口文档地址返回了无效重定向",
            status_code=422,
        )
    if redirect_count >= MAX_REDIRECTS:
        raise AppError(
            code="IMPORT_URL_TOO_MANY_REDIRECTS",
            message=f"接口文档地址重定向超过 {MAX_REDIRECTS} 次",
            status_code=422,
        )
    return urljoin(current_url, location)


async def _read_limited(response: httpx.Response, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > maximum_bytes:
            raise AppError(
                code="IMPORT_TOO_LARGE",
                message="导入文档超过 50 MB 上限",
                status_code=413,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _is_html(resource: _RetrievedResource) -> bool:
    prefix = resource.content.lstrip()[:64].lower()
    return prefix.startswith(HTML_PREFIXES) or (
        "text/html" in resource.content_type.lower() and prefix.startswith(b"<")
    )


def _resolved_http_url(base_url: str, value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    resolved = urljoin(base_url, normalized)
    parsed = urlsplit(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _decoded_js_value(value: str, quote: str) -> str:
    if quote == '"':
        try:
            decoded = json.loads(f'"{value}"')
            return decoded if isinstance(decoded, str) else value
        except json.JSONDecodeError:
            pass
    return value.replace("\\/", "/").replace("\\'", "'").replace('\\"', '"')


def _source_name(url: str, document_name: str) -> str:
    hostname = urlsplit(url).hostname or "remote"
    return f"{hostname}/{document_name}"[:255]


def _resource_name(url: str) -> str:
    parsed = urlsplit(url)
    return unquote(PurePosixPath(parsed.path).name) or "openapi-document"


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    default_port = 443 if scheme == "https" else 80
    port = f":{parsed.port}" if parsed.port is not None and parsed.port != default_port else ""
    return urlunsplit((scheme, f"{hostname}{port}", parsed.path or "/", parsed.query, ""))


def _sanitized_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme.lower(), f"{hostname}{port}", parsed.path, "", ""))[:2048]


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _timeout_error() -> AppError:
    return AppError(code="IMPORT_URL_TIMEOUT", message="获取接口文档超时", status_code=504)


def _fetch_error() -> AppError:
    return AppError(
        code="IMPORT_URL_FETCH_FAILED",
        message="无法获取接口文档, 请确认地址可由 FlowTest 服务端访问",
        status_code=422,
    )
