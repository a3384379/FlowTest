import re
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from app.domain.api_assets import (
    APIVersionSpec,
    AuthKind,
    BodyKind,
    HttpMethod,
    JsonValue,
    QueryParameterSpec,
)
from app.importers.contracts import (
    ImportedOperation,
    ImportSourceType,
    empty_request,
    imported_value,
)

HTTP_METHODS = {method.value.lower(): method for method in HttpMethod}


def parse_openapi(
    document: Mapping[str, object], source_type: ImportSourceType
) -> tuple[ImportedOperation, ...]:
    paths = _mapping(document.get("paths"))
    schemes = _security_schemes(document, source_type)
    base_path = _swagger_base_path(document, source_type)
    target_base_url = _server_url(document, source_type)
    default_security = _sequence(document.get("security"))
    operations: list[ImportedOperation] = []
    for raw_path, path_value in paths.items():
        path_item = _mapping(path_value)
        common_parameters = _sequence(path_item.get("parameters"))
        for method_name, method in HTTP_METHODS.items():
            raw_operation = path_item.get(method_name)
            if not isinstance(raw_operation, Mapping):
                continue
            operation = _mapping(raw_operation)
            request = _operation_request(
                method=method,
                path=f"{base_path}{raw_path}",
                operation=operation,
                parameters=common_parameters + _sequence(operation.get("parameters")),
                schemes=schemes,
                default_security=default_security,
                source_type=source_type,
            )
            name = _operation_name(operation, method, raw_path)
            description = _text(operation.get("description")) or _text(operation.get("summary"))
            operations.append(
                ImportedOperation(
                    name=name,
                    description=description,
                    request=request,
                    target_base_url=target_base_url,
                )
            )
    return tuple(operations)


def _operation_request(
    *,
    method: HttpMethod,
    path: str,
    operation: Mapping[str, object],
    parameters: list[object],
    schemes: Mapping[str, object],
    default_security: list[object],
    source_type: ImportSourceType,
) -> APIVersionSpec:
    request = empty_request(method=method, path=_template_path(path))
    query: list[QueryParameterSpec] = []
    headers: dict[str, str] = {}
    for raw_parameter in parameters:
        parameter = _mapping(raw_parameter)
        location = _text(parameter.get("in"))
        name = _text(parameter.get("name"))
        if not name:
            continue
        value = _parameter_value(parameter, name)
        if location == "query":
            query.append(QueryParameterSpec(name=name, value=imported_value(name, value)))
        elif location == "header":
            headers[name] = imported_value(name, value)
    body_kind, body = _body(operation, parameters, source_type)
    auth_kind, auth_config = _auth(operation, schemes, default_security)
    return replace(
        request,
        query_parameters=tuple(query),
        headers=headers,
        body_kind=body_kind,
        body=body,
        auth_kind=auth_kind,
        auth_config=auth_config,
    )


def _body(
    operation: Mapping[str, object],
    parameters: list[object],
    source_type: ImportSourceType,
) -> tuple[BodyKind, JsonValue]:
    if source_type is ImportSourceType.OPENAPI3:
        return _openapi3_body(operation)
    return _swagger_body(operation, parameters)


def _openapi3_body(operation: Mapping[str, object]) -> tuple[BodyKind, JsonValue]:
    request_body = _mapping(operation.get("requestBody"))
    content = _mapping(request_body.get("content"))
    for media_type, raw_media in content.items():
        media = _mapping(raw_media)
        example = _example(media)
        if media_type == "application/json" or media_type.endswith("+json"):
            return BodyKind.JSON, example
        if media_type == "application/x-www-form-urlencoded":
            return BodyKind.FORM, example if isinstance(example, dict) else {}
        if media_type == "multipart/form-data":
            return BodyKind.MULTIPART, {"fields": {}, "files": []}
        if media_type.startswith("text/"):
            return BodyKind.RAW, example if isinstance(example, str) else ""
    return BodyKind.NONE, None


def _swagger_body(
    operation: Mapping[str, object], parameters: list[object]
) -> tuple[BodyKind, JsonValue]:
    consumes = _sequence(operation.get("consumes"))
    form_values: dict[str, JsonValue] = {}
    has_file = False
    for raw_parameter in parameters:
        parameter = _mapping(raw_parameter)
        if parameter.get("in") == "body":
            return BodyKind.JSON, _example(parameter)
        if parameter.get("in") == "formData":
            name = _text(parameter.get("name"))
            if not name:
                continue
            has_file = has_file or parameter.get("type") == "file"
            if not has_file:
                form_values[name] = _parameter_value(parameter, name)
    if has_file or "multipart/form-data" in consumes:
        return BodyKind.MULTIPART, {"fields": form_values, "files": []}
    if form_values:
        return BodyKind.FORM, form_values
    return BodyKind.NONE, None


def _security_schemes(
    document: Mapping[str, object], source_type: ImportSourceType
) -> Mapping[str, object]:
    if source_type is ImportSourceType.SWAGGER2:
        return _mapping(document.get("securityDefinitions"))
    components = _mapping(document.get("components"))
    return _mapping(components.get("securitySchemes"))


def _auth(
    operation: Mapping[str, object],
    schemes: Mapping[str, object],
    default_security: list[object],
) -> tuple[AuthKind, dict[str, str]]:
    security = _sequence(operation.get("security")) if "security" in operation else default_security
    if not security:
        return AuthKind.NONE, {}
    requirement = _mapping(security[0])
    if not requirement:
        return AuthKind.NONE, {}
    scheme_name = next(iter(requirement))
    scheme = _mapping(schemes.get(scheme_name))
    scheme_type = _text(scheme.get("type"))
    http_scheme = _text(scheme.get("scheme")).lower()
    if scheme_type == "http" and http_scheme == "bearer":
        return AuthKind.BEARER, {"token": f"{{{{secret.{scheme_name}}}}}"}
    if (scheme_type == "http" and http_scheme == "basic") or scheme_type == "basic":
        return AuthKind.BASIC, {
            "username": f"{{{{secret.{scheme_name}_USERNAME}}}}",
            "password": f"{{{{secret.{scheme_name}_PASSWORD}}}}",
        }
    if scheme_type == "apiKey":
        return AuthKind.API_KEY, {
            "name": _text(scheme.get("name")) or "X-API-Key",
            "in": _text(scheme.get("in")) or "header",
            "value": f"{{{{secret.{scheme_name}}}}}",
        }
    return AuthKind.NONE, {}


def _example(value: Mapping[str, object]) -> JsonValue:
    if "example" in value:
        return _json_value(value.get("example"))
    schema = _mapping(value.get("schema"))
    if "example" in schema:
        return _json_value(schema.get("example"))
    return _schema_example(schema)


def _schema_example(schema: Mapping[str, object]) -> JsonValue:
    schema_type = _text(schema.get("type"))
    if schema_type == "object":
        return {
            name: _schema_example(_mapping(raw_property))
            for name, raw_property in _mapping(schema.get("properties")).items()
        }
    if schema_type == "array":
        return [_schema_example(_mapping(schema.get("items")))]
    if schema_type in {"integer", "number"}:
        return 0
    if schema_type == "boolean":
        return False
    return ""


def _parameter_value(parameter: Mapping[str, object], name: str) -> str:
    example = parameter.get("example", parameter.get("default"))
    return str(example) if example is not None else f"{{{{{name}}}}}"


def _operation_name(operation: Mapping[str, object], method: HttpMethod, path: str) -> str:
    return (
        _text(operation.get("summary"))
        or _text(operation.get("operationId"))
        or f"{method.value} {path}"
    )[:200]


def _swagger_base_path(document: Mapping[str, object], source_type: ImportSourceType) -> str:
    if source_type is not ImportSourceType.SWAGGER2:
        return ""
    value = _text(document.get("basePath"))
    return value.rstrip("/") if value and value != "/" else ""


def _server_url(document: Mapping[str, object], source_type: ImportSourceType) -> str | None:
    if source_type is ImportSourceType.OPENAPI3:
        servers = _sequence(document.get("servers"))
        if not servers:
            return None
        server = _mapping(servers[0])
        url = _text(server.get("url"))
        variables = _mapping(server.get("variables"))
        for name, raw_variable in variables.items():
            variable = _mapping(raw_variable)
            default = _text(variable.get("default"))
            if default:
                url = url.replace("{" + name + "}", default)
        return url.rstrip("/") or None
    if source_type is not ImportSourceType.SWAGGER2:
        return None
    host = _text(document.get("host"))
    if not host:
        return None
    schemes = _sequence(document.get("schemes"))
    scheme = _text(schemes[0]) if schemes else "https"
    return f"{scheme}://{host}{_swagger_base_path(document, source_type)}".rstrip("/")


def _template_path(path: str) -> str:
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_.-]*)\}", r"{{\1}}", path)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(key, str)}


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _json_value(value: object) -> JsonValue:
    return cast(JsonValue, value)
