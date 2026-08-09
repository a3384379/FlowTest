import json
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit

from app.domain.api_assets import APIVersionSpec, AuthKind, BodyKind, HttpMethod, QueryParameterSpec
from app.importers.contracts import ImportedOperation, imported_value


class HttpFormatError(ValueError):
    """Raised when a HAR, cURL, or Bruno document is malformed."""


@dataclass(slots=True)
class _CurlState:
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body_text: str | None = None
    auth: tuple[AuthKind, dict[str, str]] = (AuthKind.NONE, {})


def parse_har(document: Mapping[str, object]) -> tuple[ImportedOperation, ...]:
    log = _mapping(document.get("log"), "HAR 缺少 log")
    entries = _sequence(log.get("entries"), "HAR 缺少 entries")
    return tuple(_har_operation(entry, index) for index, entry in enumerate(entries, start=1))


def parse_curl(content: bytes) -> tuple[ImportedOperation, ...]:
    try:
        command = content.decode("utf-8-sig").strip()
    except UnicodeDecodeError as error:
        raise HttpFormatError("cURL 文件必须使用 UTF-8 编码") from error
    try:
        tokens = shlex.split(command.replace("\\\n", " "))
    except ValueError as error:
        raise HttpFormatError("cURL 命令引号不完整") from error
    if not tokens or tokens[0].lower() != "curl":
        raise HttpFormatError("文件不是 cURL 命令")
    state = _CurlState()
    index = 1
    while index < len(tokens):
        index = _consume_curl_token(tokens, index, state)
    return (
        _url_operation(
            "cURL import",
            state.method,
            state.url,
            state.headers,
            state.body_text,
            state.auth,
        ),
    )


def _consume_curl_token(tokens: list[str], index: int, state: _CurlState) -> int:
    option = tokens[index]
    value = _next(tokens, index, option) if option.startswith("-") else option
    if option in {"-X", "--request"}:
        state.method = value.upper()
    elif option in {"-H", "--header"}:
        name, header_value = _header(value)
        state.headers[name] = imported_value(name, header_value)
    elif option in {"-d", "--data", "--data-raw", "--data-binary", "--json"}:
        state.body_text = value
        state.headers.update({"Content-Type": "application/json"} if option == "--json" else {})
        state.method = "POST" if state.method == "GET" else state.method
    elif option in {"-u", "--user"}:
        username, _, password = value.partition(":")
        state.auth = (
            AuthKind.BASIC,
            {"username": username, "password": imported_value("password", password)},
        )
    elif option == "--url":
        state.url = value
    elif option.startswith("-"):
        raise HttpFormatError(f"暂不支持的 cURL 参数: {option}")
    elif state.url:
        raise HttpFormatError("cURL 命令包含多个 URL")
    else:
        state.url = value
    return index + (2 if option.startswith("-") else 1)


def parse_bruno(
    content: bytes, document: Mapping[str, object] | None
) -> tuple[ImportedOperation, ...]:
    if document is not None and document.get("bruno"):
        items = _sequence(document.get("items"), "Bruno 集合缺少 items")
        return tuple(_bruno_json_operation(item, index) for index, item in enumerate(items, 1))
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HttpFormatError("Bruno 文件必须使用 UTF-8 编码") from error
    meta = re.search(r"meta\s*\{(?P<body>.*?)\}", text, re.DOTALL)
    request = re.search(
        r"(?P<method>get|post|put|patch|delete)\s*\{(?P<body>.*?)\}",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if request is None:
        raise HttpFormatError("Bruno 文件缺少 HTTP 请求块")
    name_match = re.search(r"^\s*name:\s*(.+)$", meta.group("body") if meta else "", re.MULTILINE)
    url_match = re.search(r"^\s*url:\s*(.+)$", request.group("body"), re.MULTILINE)
    if url_match is None:
        raise HttpFormatError("Bruno 请求缺少 URL")
    headers = _bruno_block_mapping(text, "headers")
    body_match = re.search(r"body:json\s*\{(?P<body>.*?)\}\s*(?:\n\w|$)", text, re.DOTALL)
    body = body_match.group("body").strip() if body_match else None
    return (
        _url_operation(
            name_match.group(1).strip() if name_match else "Bruno import",
            request.group("method").upper(),
            url_match.group(1).strip(),
            headers,
            body,
            (AuthKind.NONE, {}),
        ),
    )


def _har_operation(raw: object, index: int) -> ImportedOperation:
    entry = _mapping(raw, f"HAR entry {index} 不是对象")
    request = _mapping(entry.get("request"), f"HAR entry {index} 缺少 request")
    method = str(request.get("method", "GET")).upper()
    url = str(request.get("url", ""))
    headers: dict[str, str] = {}
    for raw_header in _sequence(request.get("headers", []), "HAR headers 不是数组"):
        header = _mapping(raw_header, "HAR header 不是对象")
        name = str(header.get("name", "")).strip()
        if name:
            headers[name] = imported_value(name, str(header.get("value", "")))
    post_data = request.get("postData")
    body_text: str | None = None
    if isinstance(post_data, Mapping):
        body_text = str(post_data.get("text", "")) or None
    name = str(entry.get("comment") or f"{method} {urlsplit(url).path or '/'}")
    return _url_operation(name, method, url, headers, body_text, (AuthKind.NONE, {}))


def _bruno_json_operation(raw: object, index: int) -> ImportedOperation:
    item = _mapping(raw, f"Bruno item {index} 不是对象")
    request = _mapping(item.get("request"), f"Bruno item {index} 缺少 request")
    headers_raw = _mapping(request.get("headers", {}), "Bruno headers 不是对象")
    headers = {
        str(name): imported_value(str(name), str(value)) for name, value in headers_raw.items()
    }
    body = request.get("body")
    body_text = json.dumps(body, ensure_ascii=False) if body is not None else None
    return _url_operation(
        str(item.get("name") or f"Bruno request {index}"),
        str(request.get("method", "GET")),
        str(request.get("url", "")),
        headers,
        body_text,
        (AuthKind.NONE, {}),
        description=str(item.get("description", "")),
    )


def _url_operation(
    name: str,
    method_value: str,
    url: str,
    headers: dict[str, str],
    body_text: str | None,
    auth: tuple[AuthKind, dict[str, str]],
    *,
    description: str = "",
) -> ImportedOperation:
    try:
        method = HttpMethod(method_value.upper())
    except ValueError as error:
        raise HttpFormatError(f"不支持的 HTTP 方法: {method_value}") from error
    split = urlsplit(url)
    if not split.path and not split.netloc:
        raise HttpFormatError("请求 URL 不能为空")
    path = split.path or "/"
    query = tuple(
        QueryParameterSpec(name=name, value=imported_value(name, value), enabled=True)
        for name, value in parse_qsl(split.query, keep_blank_values=True)
    )
    body_kind = BodyKind.NONE
    body: object = None
    if body_text is not None:
        body_kind = BodyKind.JSON
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            body = body_text
    return ImportedOperation(
        name=name[:200],
        description=description[:4000],
        request=APIVersionSpec(
            method=method,
            path=path,
            query_parameters=query,
            headers=headers,
            body_kind=body_kind,
            body=body,  # type: ignore[arg-type]
            auth_kind=auth[0],
            auth_config=auth[1],
        ),
    )


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise HttpFormatError(message)
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, message: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise HttpFormatError(message)
    return value


def _header(value: str) -> tuple[str, str]:
    name, separator, header_value = value.partition(":")
    if not separator or not name.strip():
        raise HttpFormatError(f"Header 格式无效: {value}")
    return name.strip(), header_value.strip()


def _next(tokens: list[str], index: int, option: str) -> str:
    if index + 1 >= len(tokens):
        raise HttpFormatError(f"cURL 参数 {option} 缺少值")
    return tokens[index + 1]


def _bruno_block_mapping(text: str, block_name: str) -> dict[str, str]:
    match = re.search(rf"{re.escape(block_name)}\s*\{{(?P<body>.*?)\}}", text, re.DOTALL)
    if match is None:
        return {}
    result: dict[str, str] = {}
    for line in match.group("body").splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip():
            result[name.strip()] = imported_value(name.strip(), value.strip())
    return result
