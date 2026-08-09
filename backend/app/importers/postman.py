from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import parse_qsl, urlsplit

from app.domain.api_assets import (
    APIVersionSpec,
    AuthKind,
    BodyKind,
    HttpMethod,
    JsonValue,
    QueryParameterSpec,
)
from app.importers.contracts import ImportedOperation, empty_request, imported_value


def parse_postman(document: Mapping[str, object]) -> tuple[ImportedOperation, ...]:
    inherited_auth = _mapping(document.get("auth"))
    operations: list[ImportedOperation] = []
    _walk_items(_sequence(document.get("item")), inherited_auth, operations)
    return tuple(operations)


def _walk_items(
    items: list[object],
    inherited_auth: Mapping[str, object],
    operations: list[ImportedOperation],
) -> None:
    for raw_item in items:
        item = _mapping(raw_item)
        children = _sequence(item.get("item"))
        if children:
            _walk_items(children, _mapping(item.get("auth")) or inherited_auth, operations)
            continue
        request = _mapping(item.get("request"))
        parsed = _parse_request(request, inherited_auth)
        if parsed is None:
            continue
        operations.append(
            ImportedOperation(
                name=(_text(item.get("name")) or f"{parsed.method.value} {parsed.path}")[:200],
                description=_description(request.get("description")),
                request=parsed,
            )
        )


def _parse_request(
    request: Mapping[str, object], inherited_auth: Mapping[str, object]
) -> APIVersionSpec | None:
    method_text = _text(request.get("method")).upper()
    if method_text not in HttpMethod._value2member_map_:
        return None
    method = HttpMethod(method_text)
    path, query = _url(request.get("url"))
    headers = {
        _text(header.get("key")): imported_value(
            _text(header.get("key")), _text(header.get("value"))
        )
        for raw_header in _sequence(request.get("header"))
        if (header := _mapping(raw_header)) and not bool(header.get("disabled"))
    }
    headers = {name: value for name, value in headers.items() if name}
    body_kind, body = _body(_mapping(request.get("body")))
    auth_kind, auth_config = _auth(_mapping(request.get("auth")) or inherited_auth)
    return replace(
        empty_request(method=method, path=path),
        query_parameters=tuple(query),
        headers=headers,
        body_kind=body_kind,
        body=body,
        auth_kind=auth_kind,
        auth_config=auth_config,
    )


def _url(raw_url: object) -> tuple[str, list[QueryParameterSpec]]:
    url = _text(raw_url) if isinstance(raw_url, str) else _text(_mapping(raw_url).get("raw"))
    without_base = _strip_postman_base(url)
    parsed = urlsplit(without_base)
    path = parsed.path or "/"
    query = [
        QueryParameterSpec(name=name, value=imported_value(name, value))
        for name, value in parse_qsl(parsed.query)
    ]
    if not query and isinstance(raw_url, Mapping):
        query = _postman_query(_sequence(_mapping(raw_url).get("query")))
    return path, query


def _strip_postman_base(url: str) -> str:
    if url.startswith("{{") and "}}" in url:
        return url.split("}}", 1)[1] or "/"
    parsed = urlsplit(url)
    if parsed.scheme and parsed.netloc:
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return url


def _postman_query(values: list[object]) -> list[QueryParameterSpec]:
    result: list[QueryParameterSpec] = []
    for raw_value in values:
        value = _mapping(raw_value)
        name = _text(value.get("key"))
        if name:
            result.append(
                QueryParameterSpec(
                    name=name,
                    value=imported_value(name, _text(value.get("value"))),
                    enabled=not bool(value.get("disabled")),
                )
            )
    return result


def _body(body: Mapping[str, object]) -> tuple[BodyKind, JsonValue]:
    mode = _text(body.get("mode"))
    if mode == "raw":
        raw = _text(body.get("raw"))
        language = _text(_mapping(body.get("options")).get("language"))
        if language == "json":
            import json

            try:
                return BodyKind.JSON, json.loads(raw)
            except json.JSONDecodeError:
                return BodyKind.RAW, raw
        return BodyKind.RAW, raw
    if mode == "urlencoded":
        return BodyKind.FORM, _key_values(_sequence(body.get("urlencoded")))
    if mode == "formdata":
        return BodyKind.MULTIPART, {
            "fields": _key_values(_sequence(body.get("formdata"))),
            "files": [],
        }
    return BodyKind.NONE, None


def _key_values(values: list[object]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for raw_value in values:
        value = _mapping(raw_value)
        if value.get("type") == "file" or bool(value.get("disabled")):
            continue
        name = _text(value.get("key"))
        if name:
            result[name] = _text(value.get("value"))
    return result


def _auth(auth: Mapping[str, object]) -> tuple[AuthKind, dict[str, str]]:
    kind = _text(auth.get("type"))
    values = _auth_values(_sequence(auth.get(kind)))
    if kind == "bearer":
        return AuthKind.BEARER, {"token": "{{secret.IMPORTED_BEARER_TOKEN}}"}
    if kind == "basic":
        return AuthKind.BASIC, {
            "username": "{{secret.IMPORTED_BASIC_USERNAME}}",
            "password": "{{secret.IMPORTED_BASIC_PASSWORD}}",
        }
    if kind == "apikey":
        return AuthKind.API_KEY, {
            "name": values.get("key", "X-API-Key"),
            "value": "{{secret.IMPORTED_API_KEY}}",
            "in": values.get("in", "header"),
        }
    return AuthKind.NONE, {}


def _auth_values(values: list[object]) -> dict[str, str]:
    return {
        _text(item.get("key")): _text(item.get("value"))
        for raw_item in values
        if (item := _mapping(raw_item)) and _text(item.get("key"))
    }


def _description(value: object) -> str:
    if isinstance(value, str):
        return value[:4000]
    return _text(_mapping(value).get("content"))[:4000]


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(key, str)}


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
