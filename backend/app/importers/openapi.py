import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Literal, cast

from pydantic import ValidationError

from app.domain.api_assets import (
    APIVersionSpec,
    AuthKind,
    BodyKind,
    HttpMethod,
    JsonValue,
    QueryParameterSpec,
)
from app.domain.canonical_contracts import sanitize_contract_payload
from app.domain.canonical_schemas import CanonicalSchemaValidationError
from app.domain.test_engineering import (
    ContractAuth,
    ContractParameter,
    ContractRequestBody,
    ContractResponse,
    OperationContract,
)
from app.importers.contracts import (
    ImportedOperation,
    ImportSourceType,
    empty_request,
    imported_value,
)
from app.importers.openapi_adapter import OperationAdapter
from app.importers.openapi_normalization import SourceNormalizer, pointer

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
            normalizer = SourceNormalizer(
                document, method.value, raw_path, _text(raw_operation.get("operationId")) or None
            )
            operation = OperationAdapter(
                normalizer, pointer("#/paths", raw_path) + "/" + method_name
            ).prepare(dict(raw_operation), common_parameters)
            parameters = _sequence(operation.get("parameters"))
            request = _operation_request(
                method=method,
                path=f"{base_path}{raw_path}",
                operation=operation,
                parameters=parameters,
                schemes=schemes,
                default_security=default_security,
                source_type=source_type,
            )
            name = _operation_name(operation, method, raw_path)
            description = _text(operation.get("description")) or _text(operation.get("summary"))
            contract = _operation_contract(
                document=document,
                operation=operation,
                parameters=parameters,
                request=request,
                schemes=schemes,
                default_security=default_security,
                source_type=source_type,
                operation_name=name,
                normalizer=normalizer,
            )
            operations.append(
                ImportedOperation(
                    name=name,
                    description=description,
                    request=request,
                    target_base_url=target_base_url,
                    diagnostics=tuple(normalizer.diagnostics),
                    canonical_contract=contract,
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
            query.extend(_query_values(parameter, name, value))
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


def _operation_contract(
    *,
    document: Mapping[str, object],
    operation: Mapping[str, object],
    parameters: list[object],
    request: APIVersionSpec,
    schemes: Mapping[str, object],
    default_security: list[object],
    source_type: ImportSourceType,
    operation_name: str,
    normalizer: SourceNormalizer,
) -> OperationContract:
    try:
        return _build_operation_contract(
            document=document,
            operation=operation,
            parameters=parameters,
            request=request,
            schemes=schemes,
            default_security=default_security,
            source_type=source_type,
            operation_name=operation_name,
            partial=normalizer.partial,
        )
    except (ValidationError, CanonicalSchemaValidationError):
        normalizer.warn(
            pointer("#/paths", normalizer.endpoint),
            "$",
            "$contract",
            "OPERATION_CONTRACT_PARTIAL",
            "接口契约字段无法满足内部约束, 仅保留方法和路径; 请修正源接口定义",
            loss=True,
        )
        return OperationContract(
            operation=_contract_operation_name(operation_name),
            method=request.method.value,
            path=request.path,
            completeness="partial",
        )


def _build_operation_contract(
    *,
    document: Mapping[str, object],
    operation: Mapping[str, object],
    parameters: list[object],
    request: APIVersionSpec,
    schemes: Mapping[str, object],
    default_security: list[object],
    source_type: ImportSourceType,
    operation_name: str,
    partial: bool = False,
) -> OperationContract:
    contract_parameters = _contract_parameters(document, parameters, source_type)
    request_body = _contract_request_body(document, operation, parameters, source_type)
    auth = _contract_auth(operation, schemes, default_security)
    responses = _contract_responses(document, operation, source_type)
    info = _mapping(document.get("info"))
    revision = _text(info.get("version")) or None
    raw = {
        "operation": _contract_operation_name(operation_name),
        "method": request.method.value,
        "path": request.path,
        "auth": auth.model_dump(mode="json"),
        "parameters": [item.model_dump(mode="json", by_alias=True) for item in contract_parameters],
        "request_body": (
            request_body.model_dump(mode="json", by_alias=True)
            if request_body is not None
            else None
        ),
        "request": request_body.schema_ if request_body is not None else {},
        "responses": {
            status: response.model_dump(mode="json", by_alias=True)
            for status, response in responses.items()
        },
        "source_ref": f"openapi://{_contract_operation_name(operation_name)}",
        "revision": revision,
        "completeness": "partial" if partial else "complete",
    }
    return OperationContract.model_validate(sanitize_contract_payload(raw).payload)


def _contract_parameters(
    document: Mapping[str, object],
    parameters: list[object],
    source_type: ImportSourceType,
) -> list[ContractParameter]:
    result: list[ContractParameter] = []
    for raw_parameter in parameters:
        parameter = _resolved_mapping(document, raw_parameter)
        location = _text(parameter.get("in"))
        name = _text(parameter.get("name"))
        if location not in {"path", "query", "header", "cookie"} or not name:
            continue
        schema = (
            _resolved_schema(document, parameter.get("schema"))
            if source_type is ImportSourceType.OPENAPI3
            else _swagger_parameter_schema(document, parameter)
        )
        result.append(
            ContractParameter(
                name=name,
                location=cast(Literal["path", "query", "header", "cookie"], location),
                required=location == "path" or parameter.get("required") is True,
                schema=schema,
                style=_text(parameter.get("style")) or None,
                explode=(
                    parameter.get("explode") if isinstance(parameter.get("explode"), bool) else None
                ),
                source_ref=f"openapi-parameter://{location}/{name}",
            )
        )
    unique: dict[tuple[str, str], ContractParameter] = {}
    for contract_parameter in result:
        unique[(contract_parameter.location, contract_parameter.name.lower())] = contract_parameter
    return list(unique.values())


def _contract_request_body(
    document: Mapping[str, object],
    operation: Mapping[str, object],
    parameters: list[object],
    source_type: ImportSourceType,
) -> ContractRequestBody | None:
    if source_type is ImportSourceType.OPENAPI3:
        request_body = _resolved_mapping(document, operation.get("requestBody"))
        content = _mapping(request_body.get("content"))
        for media_type in sorted(content, key=lambda value: ("json" not in value, value)):
            media = _mapping(content[media_type])
            schema = _resolved_schema(document, media.get("schema"))
            if "schema" in media:
                return ContractRequestBody(
                    required=request_body.get("required") is True,
                    content_type=media_type,
                    schema=schema,
                )
        return None
    for raw_parameter in parameters:
        parameter = _resolved_mapping(document, raw_parameter)
        if parameter.get("in") == "body":
            return ContractRequestBody(
                required=parameter.get("required") is True,
                schema=_resolved_schema(document, parameter.get("schema")),
                content_type=_swagger_content_type(operation, parameters),
            )
    form = [_mapping(item) for item in parameters if _mapping(item).get("in") == "formData"]
    if form:
        properties = {
            str(item["name"]): _swagger_parameter_schema(document, item)
            for item in form
            if item.get("name")
        }
        required = [
            str(item["name"]) for item in form if item.get("name") and item.get("required") is True
        ]
        return ContractRequestBody(
            required=bool(required),
            content_type=_swagger_content_type(operation, parameters),
            schema={"type": "object", "properties": properties, "required": required},
        )
    return None


def _contract_responses(
    document: Mapping[str, object],
    operation: Mapping[str, object],
    source_type: ImportSourceType,
) -> dict[str, ContractResponse]:
    result: dict[str, ContractResponse] = {}
    for status, raw_response in _mapping(operation.get("responses")).items():
        if re.fullmatch(r"[1-5][0-9]{2}|default", status) is None:
            continue
        response = _resolved_mapping(document, raw_response)
        schema: dict[str, JsonValue] | None = None
        content_type: str | None = None
        if source_type is ImportSourceType.OPENAPI3:
            content = _mapping(response.get("content"))
            for media_type in sorted(content, key=lambda value: ("json" not in value, value)):
                content_type = content_type or media_type
                candidate = _resolved_schema(document, _mapping(content[media_type]).get("schema"))
                if candidate:
                    schema = candidate
                    content_type = media_type
                    break
        else:
            candidate = _resolved_schema(document, response.get("schema"))
            schema = candidate or None
            produces = _sequence(operation.get("produces")) or _sequence(document.get("produces"))
            content_type = _text(produces[0]) if produces else None
        result[status] = ContractResponse(
            description=_text(response.get("description")),
            content_type=content_type,
            schema=schema,
        )
    return result


def _contract_auth(
    operation: Mapping[str, object],
    schemes: Mapping[str, object],
    default_security: list[object],
) -> ContractAuth:
    security = _sequence(operation.get("security")) if "security" in operation else default_security
    if not security or not _mapping(security[0]):
        return ContractAuth()
    scheme_name = next(iter(_mapping(security[0])))
    scheme = _mapping(schemes.get(scheme_name))
    scheme_type = _text(scheme.get("type"))
    http_scheme = _text(scheme.get("scheme")).lower()
    if scheme_type == "apiKey":
        location = _text(scheme.get("in"))
        return ContractAuth(
            required=True,
            kind="api_key",
            location=location if location in {"header", "query", "cookie"} else "header",
            name=_text(scheme.get("name")) or "X-API-Key",
            source_ref=f"openapi-security://{scheme_name}",
        )
    if http_scheme == "bearer":
        return ContractAuth(
            required=True,
            kind="bearer",
            location="header",
            name="Authorization",
            source_ref=f"openapi-security://{scheme_name}",
        )
    if http_scheme == "basic" or scheme_type == "basic":
        return ContractAuth(
            required=True,
            kind="basic",
            location="header",
            name="Authorization",
            source_ref=f"openapi-security://{scheme_name}",
        )
    if scheme_type in {"oauth2", "openIdConnect"}:
        return ContractAuth(
            required=True,
            kind="oauth2",
            location="header",
            name="Authorization",
            source_ref=f"openapi-security://{scheme_name}",
        )
    return ContractAuth(required=True, kind="other", source_ref=f"openapi-security://{scheme_name}")


def _swagger_parameter_schema(
    document: Mapping[str, object], parameter: Mapping[str, object]
) -> dict[str, JsonValue]:
    return _resolved_schema(document, parameter.get("schema"))


def _resolved_mapping(document: Mapping[str, object], value: object) -> Mapping[str, object]:
    mapping = _mapping(value)
    reference = _text(mapping.get("$ref"))
    if not reference.startswith("#/"):
        return mapping
    current: object = document
    for part in reference[2:].split("/"):
        if not isinstance(current, Mapping):
            return mapping
        current = current.get(part.replace("~1", "/").replace("~0", "~"))
    resolved = dict(_mapping(current))
    resolved.update({key: item for key, item in mapping.items() if key != "$ref"})
    return resolved


def _resolved_schema(document: Mapping[str, object], value: object) -> dict[str, JsonValue]:
    # OperationAdapter has normalized every source schema before construction.
    return cast(dict[str, JsonValue], dict(_mapping(value)))


def _contract_operation_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.:-]", "_", value).strip("_")
    if not normalized or (not normalized[0].isalpha() and normalized[0] != "_"):
        normalized = f"operation_{normalized}"
    return normalized[:240]


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
            has_file = has_file or _mapping(parameter.get("schema")).get("format") == "binary"
            if _mapping(parameter.get("schema")).get("format") != "binary":
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


def _swagger_content_type(operation: Mapping[str, object], parameters: list[object]) -> str:
    consumes = _sequence(operation.get("consumes"))
    form = [_mapping(item) for item in parameters if _mapping(item).get("in") == "formData"]
    preferred = "application/json"
    if form:
        has_file = any(_mapping(item.get("schema")).get("format") == "binary" for item in form)
        preferred = "multipart/form-data" if has_file else "application/x-www-form-urlencoded"
    if preferred in consumes:
        return preferred
    return str(consumes[0]) if consumes else preferred


def _query_values(
    parameter: Mapping[str, object], name: str, fallback: str
) -> list[QueryParameterSpec]:
    schema = _mapping(parameter.get("schema"))
    values = parameter.get("example", parameter.get("default", schema.get("default")))
    if not isinstance(values, list):
        return [QueryParameterSpec(name=name, value=imported_value(name, fallback))]
    encoded = [str(value) for value in values]
    style = parameter.get("style") or "form"
    explode = parameter.get("explode", style == "form")
    if explode is not True:
        separator = {"spaceDelimited": " ", "pipeDelimited": "|", "tabDelimited": "\t"}.get(
            str(parameter.get("style")), ","
        )
        encoded = [separator.join(encoded)]
    return [QueryParameterSpec(name=name, value=imported_value(name, value)) for value in encoded]
