"""Source normalization regressions; no external business endpoints are contacted."""

import json

import pytest
import yaml

from app.importers.contracts import ImportSourceType
from app.importers.document import ImportDocumentError, parse_import_document


def load(document, **kwargs):
    return parse_import_document(json.dumps(document).encode(), **kwargs)[1]


def spec(version="3.2.0", operation=None):
    return {
        "openapi": version,
        "info": {"version": "1"},
        "paths": {"/items": {"post": operation or {}}},
    }


@pytest.mark.parametrize("version", ["3.0.4", "3.1.1", "3.2.0", "3.2.7"])
def test_version_families_and_json_yaml_equivalence(version):
    doc = spec(
        version,
        {
            "requestBody": {
                "content": {
                    "application/json": {"schema": {"type": "string", "description": "a\nb"}}
                }
            }
        },
    )
    first = load(doc)[0]
    second = parse_import_document(yaml.safe_dump(doc).encode())[1][0]
    assert first.content_fingerprint == second.content_fingerprint
    assert first.diagnostics[0].source_dialect == "OPENAPI_" + version[:3].replace(".", "_")


@pytest.mark.parametrize("version", ["3.9.0", "4.0.0"])
@pytest.mark.parametrize("requested_type", [ImportSourceType.AUTO, ImportSourceType.OPENAPI3])
def test_unknown_version_rejected_even_with_explicit_format(version, requested_type):
    with pytest.raises(ImportDocumentError, match="版本"):
        load(spec(version), requested_type=requested_type)


def test_explicit_format_must_match_document_header():
    with pytest.raises(ImportDocumentError):
        load(spec(), requested_type=ImportSourceType.SWAGGER2)


def test_legacy_slash_refs_are_distinguished_from_missing_models():
    name = "查询线下收款/退款渠道的实体类"
    missing = [
        "DetailProcessRuleDto",
        "Integer",
        "JshCommunityFeeBillDetailProcessRuleRecordPo",
        "List",
        "ParseFormulaDto",
    ]
    references = [f"#/definitions/{name}"] * 9 + [f"#/definitions/{n}" for n in missing]
    doc = {
        "swagger": "2.0",
        "info": {"version": "1"},
        "definitions": {name: {"type": "string"}},
        "paths": {
            f"/item/{i}": {
                "post": {"parameters": [{"name": "body", "in": "body", "schema": {"$ref": ref}}]}
            }
            for i, ref in enumerate(references)
        },
    }
    operations = load(doc)
    assert len(operations) == 14
    assert (
        sum(d.code == "LEGACY_REF_ESCAPING_REPAIRED" for o in operations for d in o.diagnostics)
        == 9
    )
    assert sum(d.code == "REF_NOT_FOUND" for o in operations for d in o.diagnostics) == 5
    assert all(o.canonical_contract.completeness == "partial" for o in operations[9:])


def test_swagger_missing_scheme_uses_http_document_context():
    doc = {
        "swagger": "2.0",
        "info": {"version": "1"},
        "host": "api.test",
        "basePath": "/v2",
        "paths": {"/items": {"get": {}}},
    }
    operation = load(doc, document_url="http://docs.test/gateway/v2/api-docs")[0]
    assert operation.target_base_url == "http://api.test/v2"
    assert any(d.code == "SERVER_SCHEME_FROM_SOURCE" for d in operation.diagnostics)
    without_source = load(doc)[0]
    assert without_source.target_base_url is None
    assert any(d.code == "SERVER_REQUIRES_CONFIGURATION" for d in without_source.diagnostics)


def test_openapi32_ref_siblings_and_exclusive_boundaries():
    doc = spec(
        operation={
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Base", "maximum": 10}
                    }
                }
            }
        }
    )
    doc["components"] = {"schemas": {"Base": {"type": "number", "exclusiveMinimum": 1}}}
    schema = load(doc)[0].canonical_contract.request_body.schema_
    assert schema == {"allOf": [{"type": "number", "exclusiveMinimum": 1}, {"maximum": 10}]}


def test_effective_parameters_preserve_query_case_and_override_headers():
    doc = spec(
        operation={
            "parameters": [
                {"name": "id", "in": "query", "example": "operation", "schema": {"type": "string"}},
                {"name": "x-name", "in": "header", "example": "new", "schema": {"type": "string"}},
            ]
        }
    )
    doc["paths"]["/items"]["parameters"] = [
        {"name": "id", "in": "query", "example": "path", "schema": {"type": "string"}},
        {"name": "ID", "in": "query", "example": "capital", "schema": {"type": "string"}},
        {"name": "X-Name", "in": "header", "example": "old", "schema": {"type": "string"}},
    ]
    operation = load(doc)[0]
    assert [(p.name, p.value) for p in operation.request.query_parameters] == [
        ("id", "operation"),
        ("ID", "capital"),
    ]
    assert operation.request.headers["x-name"] == "new"
    assert "X-Name" not in operation.request.headers
    assert len(operation.canonical_contract.parameters) == 3


def test_media_selection_agrees_and_is_order_independent():
    content = {
        "text/plain": {"schema": {"type": "string"}, "example": "text"},
        "application/json": {"schema": {"type": "object"}, "example": {"message": "json"}},
    }
    first = load(spec(operation={"requestBody": {"content": content}}))[0]
    second = load(
        spec(operation={"requestBody": {"content": dict(reversed(list(content.items())))}})
    )[0]
    assert first.request.body == {"message": "json"}
    assert (
        first.request.headers["Content-Type"] == first.canonical_contract.request_body.content_type
    )
    assert first.content_fingerprint == second.content_fingerprint


def test_response_ranges_are_diagnosed_as_partial():
    operation = load(spec(operation={"responses": {"2XX": {"description": "success"}}}))[0]
    assert operation.canonical_contract.completeness == "partial"
    assert any(d.code == "RESPONSE_RANGE_UNSUPPORTED" for d in operation.diagnostics)


def test_path_item_ref_and_relative_operation_server():
    doc = spec()
    doc["paths"] = {"/items": {"$ref": "#/components/pathItems/Items"}}
    doc["components"] = {
        "pathItems": {
            "Items": {
                "post": {
                    "servers": [
                        {"url": "/gateway/{version}", "variables": {"version": {"default": "v2"}}}
                    ]
                }
            }
        }
    }
    operation = load(doc, document_url="http://docs.test/openapi.json")[0]
    assert operation.target_base_url == "http://docs.test/gateway/v2"


@pytest.mark.parametrize(
    "collection,expected",
    [
        ("multi", [("ids", "a"), ("ids", "b")]),
        ("csv", [("ids", "a,b")]),
        ("ssv", [("ids", "a b")]),
        ("tsv", [("ids", "a\tb")]),
        ("pipes", [("ids", "a|b")]),
    ],
)
@pytest.mark.asyncio
async def test_runtime_array_reaches_mock_http_wire(collection, expected):
    import httpx

    from app.domain.import_execution import render_import_query
    from app.domain.scopes import ResolvedValue, VariableScope

    doc = {
        "swagger": "2.0",
        "info": {"version": "1"},
        "paths": {
            "/items": {
                "get": {
                    "parameters": [
                        {
                            "name": "ids",
                            "in": "query",
                            "type": "array",
                            "items": {"type": "string"},
                            "collectionFormat": collection,
                        }
                    ]
                }
            }
        },
    }
    operation = load(doc)[0]
    params = render_import_query(
        operation.request.query_parameters,
        {"ids": ResolvedValue('["a","b"]', VariableScope.RUNTIME)},
        operation.canonical_contract.model_dump(mode="json", by_alias=True),
    )
    seen = []

    def handler(request):
        seen.extend(request.url.params.multi_items())
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await client.get("http://mock.invalid/items", params=params)
    assert seen == expected


def test_complex_query_array_requires_configuration():
    from app.domain.import_execution import serialize_array

    with pytest.raises(ValueError, match="人工配置"):
        serialize_array('[{"id":1}]', {"style": "form", "explode": True})


def test_imported_base_path_is_joined_once_without_losing_gateway():
    from app.domain.import_execution import imported_execution_path
    from app.services.request_targets import join_service_path

    contract = {"warnings": ["import_base_path=/v2"]}
    for base, expected in [
        ("http://mock.invalid/gateway/v2", "/gateway/v2/items"),
        ("http://mock.invalid/gateway", "/gateway/v2/items"),
    ]:
        path = imported_execution_path(base, "/v2/items", contract)
        assert join_service_path(base, path) == "http://mock.invalid" + expected
    assert imported_execution_path("http://mock.invalid/v2", "/v2/items", {}) == "/v2/items"


def test_security_combinations_are_partial_and_not_pretended_configured():
    doc = spec(operation={"security": [{"A": [], "B": []}]})
    doc["components"] = {
        "securitySchemes": {name: {"type": "http", "scheme": "bearer"} for name in ["A", "B"]}
    }
    operation = load(doc)[0]
    assert operation.canonical_contract.completeness == "partial"
    assert operation.request.auth_kind.value == "none"
    assert "SECURITY_REQUIRES_CONFIGURATION" in operation.canonical_contract.warnings
    doc["paths"]["/items"]["post"]["security"] = []
    assert not load(doc)[0].canonical_contract.auth.required


@pytest.mark.parametrize("schema,expected", [({}, {}), (True, {}), (False, {"not": {}})])
def test_empty_and_boolean_response_schemas_remain_present(schema, expected):
    operation = load(
        spec(
            operation={
                "responses": {
                    "200": {"content": {"application/json": {"schema": schema}}},
                    "204": {"description": "no body"},
                }
            }
        )
    )[0]
    assert operation.canonical_contract.responses["200"].schema_ == expected
    assert operation.canonical_contract.responses["204"].schema_ is None


def test_diagnostic_metadata_does_not_change_import_fingerprint():
    operation = load(spec())[0]
    original = operation.content_fingerprint
    operation.canonical_contract.warnings.extend(["NEW_DIAGNOSTIC", "import_base_path=/v2"])
    assert operation.content_fingerprint == original


@pytest.mark.parametrize(
    "media_type,expected",
    [
        ("application/json", b'{"name":"demo"}'),
        ("application/vnd.demo+json", b'{"name":"demo"}'),
        ("application/x-www-form-urlencoded", b"name=demo"),
    ],
)
@pytest.mark.asyncio
async def test_selected_media_reaches_executor_wire(media_type, expected):
    import httpx

    from app.domain.scopes import HeaderScope
    from app.services.api_assets import PreparedHeader, PreparedRequest
    from app.services.executions import _send_request

    operation = load(
        spec(
            operation={
                "requestBody": {
                    "content": {
                        media_type: {"schema": {"type": "object"}, "example": {"name": "demo"}}
                    }
                }
            }
        )
    )[0]
    seen = []

    def handler(request):
        seen.append((request.headers["content-type"], request.content))
        return httpx.Response(200)

    prepared = PreparedRequest(
        operation.request.method,
        "http://mock.invalid/items",
        tuple(PreparedHeader(k, v, HeaderScope.API) for k, v in operation.request.headers.items()),
        operation.request.body,
        (),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _send_request(
            client, prepared, body_kind=operation.request.body_kind, timeout_seconds=1
        )
    assert seen == [(operation.canonical_contract.request_body.content_type, expected)]


def test_swagger_form_media_matches_contract_with_multiple_consumes():
    document = {
        "swagger": "2.0",
        "info": {"version": "1"},
        "consumes": ["multipart/form-data", "application/x-www-form-urlencoded"],
        "paths": {
            "/items": {
                "post": {"parameters": [{"name": "name", "in": "formData", "type": "string"}]}
            }
        },
    }
    operation = load(document)[0]
    assert operation.request.body_kind.value == "form"
    assert (
        operation.canonical_contract.request_body.content_type
        == "application/x-www-form-urlencoded"
    )
