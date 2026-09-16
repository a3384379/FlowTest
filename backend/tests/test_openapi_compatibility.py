import json
from pathlib import Path

import pytest

from app.domain.api_assets import BodyKind
from app.domain.canonical_contracts import sanitize_contract_payload
from app.domain.canonical_schemas import CanonicalSchemaValidationError, CanonicalSchemaValidator
from app.importers.document import ImportDocumentError, parse_import_document

FIXTURE = Path(__file__).parent / "fixtures/importers/swagger2-compatibility.yaml"


def parse(schema, version="3.1.0", **extra):
    document = {
        "openapi": version,
        "paths": {
            "/test": {
                "post": {"requestBody": {"content": {"application/json": {"schema": schema}}}}
            }
        },
        **extra,
    }
    return parse_import_document(json.dumps(document).encode())[1][0]


def test_real_minimal_regression_and_stable_output():
    _, operations = parse_import_document(FIXTURE.read_bytes())
    _, repeated = parse_import_document(FIXTURE.read_bytes())
    assert len(operations) == 8
    assert [o.content_fingerprint for o in operations] == [o.content_fingerprint for o in repeated]
    assert [o.import_key for o in operations] == [o.import_key for o in repeated]
    for operation in operations:
        contract = operation.canonical_contract
        assert contract is not None
        sanitize_contract_payload(contract.model_dump(mode="json", by_alias=True))
    first, second, upload = operations[:3]
    for operation, definition in [
        (first, "JscpcoChargeRentBillItemDataFeeStandardDto"),
        (second, "JscpcoChargeRentBillItemData"),
    ]:
        diagnostic = next(d for d in operation.diagnostics if d.keyword == "description")
        assert (
            diagnostic.source_path
            == f"#/definitions/{definition}/properties/assetFeeTypeName/description"
        )
        assert diagnostic.method == "POST"
        assert diagnostic.endpoint == operation.request.path
        assert diagnostic.code == "SCHEMA_TEXT_WHITESPACE_NORMALIZED"
        assert diagnostic.severity == "WARNING"
    assert (
        first.diagnostics[0].canonical_path
        == "$.request_body.schema.properties.itemDataList.items.properties."
        "assetFeeTypeName.description"
    )
    body = upload.canonical_contract.request_body
    assert body.content_type == "multipart/form-data"
    assert body.schema_ == {
        "type": "object",
        "properties": {
            "file": {"type": "string", "format": "binary"},
            "name": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["file"],
    }
    assert upload.request.body_kind == BodyKind.MULTIPART
    assert set(upload.request.body["fields"]) == {"name", "description"}
    assert any(d.code == "PATH_PARAMETER_MISMATCH" for d in operations[-2].diagnostics)
    assert any(d.code == "GET_WITH_BODY" for d in operations[-1].diagnostics)


@pytest.mark.parametrize(
    ("collection", "style", "explode"),
    [
        ("multi", "form", True),
        ("csv", "form", False),
        ("ssv", "spaceDelimited", False),
        ("tsv", "tabDelimited", False),
        ("pipes", "pipeDelimited", False),
    ],
)
def test_swagger_array_serialization(collection, style, explode):
    document = {
        "swagger": "2.0",
        "paths": {
            "/test": {
                "get": {
                    "parameters": [
                        {
                            "in": "query",
                            "name": "ids",
                            "type": "array",
                            "items": {"type": "integer"},
                            "collectionFormat": collection,
                        }
                    ]
                }
            }
        },
    }
    operation = parse_import_document(json.dumps(document).encode())[1][0]
    parameter = operation.canonical_contract.parameters[0]
    assert parameter.schema_["type"] == "array"
    assert (parameter.style, parameter.explode) == (style, explode)


@pytest.mark.parametrize(
    "media",
    [
        "application/json",
        "application/vnd.test+json",
        "multipart/form-data",
        "application/x-www-form-urlencoded",
    ],
)
def test_openapi30_media_and_components(media):
    document = {
        "openapi": "3.0.3",
        "components": {
            "schemas": {
                "上传": {
                    "type": "object",
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            },
            "requestBodies": {
                "Body": {"content": {media: {"schema": {"$ref": "#/components/schemas/上传"}}}}
            },
            "parameters": {
                "Q": {
                    "in": "query",
                    "name": "q",
                    "schema": {"type": "array", "items": {"type": "string"}},
                    "style": "form",
                    "explode": True,
                }
            },
            "responses": {
                "OK": {
                    "description": "ok",
                    "content": {media: {"schema": {"type": "string", "nullable": True}}},
                }
            },
        },
        "paths": {
            "/upload": {
                "post": {
                    "parameters": [{"$ref": "#/components/parameters/Q"}],
                    "requestBody": {"$ref": "#/components/requestBodies/Body"},
                    "responses": {"200": {"$ref": "#/components/responses/OK"}},
                }
            }
        },
    }
    operation = parse_import_document(json.dumps(document).encode())[1][0]
    contract = operation.canonical_contract
    assert contract.request_body.content_type == media
    assert contract.request_body.schema_["properties"]["file"]["format"] == "binary"
    assert contract.parameters[0].explode is True
    assert contract.responses["200"].schema_["nullable"] is True
    assert operation.request.body_kind != BodyKind.NONE


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("prefixItems", [{"type": "string"}]),
        ("unevaluatedProperties", False),
        ("if", {"required": ["a"]}),
        ("then", {"required": ["b"]}),
        ("else", {"required": ["c"]}),
        ("dependentSchemas", {"a": {"type": "object"}}),
        ("dependentRequired", {"a": ["b"]}),
        ("contains", {"type": "string"}),
        ("minContains", 1),
        ("maxContains", 2),
        ("contentEncoding", "base64"),
        ("contentMediaType", "image/png"),
    ],
)
def test_openapi31_unsupported_is_partial_with_diagnostics(keyword, value):
    operation = parse({"type": ["string", "null"], keyword: value})
    assert operation.canonical_contract.request_body.schema_["type"] == ["string", "null"]
    assert operation.canonical_contract.completeness == "partial"
    assert any(
        d.keyword == keyword and d.source_dialect == "OPENAPI_3_1" for d in operation.diagnostics
    )


def test_composition_const_defs_and_vendor_annotations():
    operation = parse(
        {
            "$defs": {"Value": {"const": "fixed"}},
            "allOf": [
                {
                    "$ref": "#/paths/~1test/post/requestBody/content/"
                    "application~1json/schema/$defs/Value"
                },
                {"anyOf": [{"type": "string"}, {"type": "null"}]},
                {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                {"not": {"type": "boolean"}},
            ],
            "x-generator": {"name": "test"},
        }
    )
    schema = operation.canonical_contract.request_body.schema_
    assert schema["allOf"][0] == {"const": "fixed"}
    assert "x-generator" not in schema
    assert any(d.keyword == "x-generator" for d in operation.diagnostics)


@pytest.mark.parametrize(
    "reference",
    ["#/definitions/中文«PageInfo«XXX»»", "https://example.test/schema.json", "#/missing"],
)
def test_cycles_remote_missing_refs_are_diagnosed(reference):
    document = {
        "swagger": "2.0",
        "definitions": {
            "中文«PageInfo«XXX»»": {"type": "object", "properties": {"child": {"$ref": reference}}}
        },
        "paths": {
            "/test": {
                "post": {
                    "parameters": [{"in": "body", "name": "body", "schema": {"$ref": reference}}]
                }
            }
        },
    }
    operation = parse_import_document(json.dumps(document).encode())[1][0]
    assert operation.canonical_contract.completeness == "partial"
    assert any(d.keyword == "$ref" for d in operation.diagnostics)


def test_bad_schema_does_not_block_other_operations():
    document = {
        "openapi": "3.1.0",
        "paths": {
            "/bad": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "invalid",
                                    "pattern": "(a+)+",
                                    "description": "a\x00b",
                                }
                            }
                        }
                    }
                }
            },
            **{f"/good/{i}": {"get": {}} for i in range(300)},
        },
    }
    operations = parse_import_document(json.dumps(document).encode())[1]
    assert len(operations) == 301
    assert operations[0].canonical_contract.completeness == "partial"
    with pytest.raises(CanonicalSchemaValidationError):
        CanonicalSchemaValidator().validate({"description": "a\nb"})


def test_swagger_legacy_message():
    with pytest.raises(ImportDocumentError, match=r"Legacy Swagger 1\.x"):
        parse_import_document(b'{"swaggerVersion":"1.2"}')


@pytest.mark.parametrize(
    "fields, expected",
    [
        ([{"name": "name", "type": "string"}], "application/x-www-form-urlencoded"),
        ([{"name": "file", "type": "file", "required": True}], "multipart/form-data"),
    ],
)
def test_swagger_form_variants_and_inherited_consumes(fields, expected):
    document = {
        "swagger": "2.0",
        "consumes": [expected],
        "produces": ["application/xml"],
        "securityDefinitions": {"auth": {"type": "basic"}},
        "security": [{"auth": []}],
        "paths": {
            "/form": {
                "post": {
                    "parameters": [{"in": "formData", **f} for f in fields],
                    "responses": {"200": {"schema": {"type": "file"}}},
                }
            }
        },
    }
    operation = parse_import_document(json.dumps(document).encode())[1][0]
    contract = operation.canonical_contract
    assert contract.request_body.content_type == expected
    assert contract.auth.kind == "basic"
    assert contract.responses["200"].content_type == "application/xml"
    assert contract.responses["200"].schema_ == {"type": "string", "format": "binary"}
    assert not any(d.code == "CONTENT_TYPE_DEFAULTED" for d in operation.diagnostics)


def test_swagger_constraints_api_key_and_discriminator():
    document = {
        "swagger": "2.0",
        "securityDefinitions": {"key": {"type": "apiKey", "in": "query", "name": "key"}},
        "security": [{"key": []}],
        "definitions": {
            "中文«PageInfo«XXX»»": {
                "type": "object",
                "discriminator": "kind",
                "additionalProperties": {"type": "integer"},
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["a", "b"],
                        "default": "a",
                        "readOnly": True,
                    },
                    "number": {
                        "type": "number",
                        "minimum": 0,
                        "exclusiveMinimum": True,
                        "maximum": 10,
                    },
                },
            }
        },
        "paths": {
            "/test": {
                "post": {
                    "parameters": [
                        {
                            "in": "body",
                            "name": "body",
                            "schema": {"$ref": "#/definitions/中文«PageInfo«XXX»»"},
                        }
                    ]
                }
            }
        },
    }
    operation = parse_import_document(json.dumps(document).encode())[1][0]
    contract = operation.canonical_contract
    assert contract.auth.kind == "api_key"
    schema = contract.request_body.schema_
    assert schema["discriminator"] == {"propertyName": "kind"}
    assert schema["additionalProperties"] == {"type": "integer"}
    assert schema["properties"]["number"] == {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": 10,
    }
    assert schema["properties"]["kind"]["default"] == "a"


@pytest.mark.parametrize(
    "collection, expected",
    [
        ("multi", ["1", "2"]),
        ("csv", ["1,2"]),
        ("ssv", ["1 2"]),
        ("tsv", ["1\t2"]),
        ("pipes", ["1|2"]),
    ],
)
def test_query_array_executable_examples(collection, expected):
    document = {
        "swagger": "2.0",
        "paths": {
            "/array": {
                "get": {
                    "parameters": [
                        {
                            "in": "query",
                            "name": "ids",
                            "type": "array",
                            "items": {"type": "integer"},
                            "default": [1, 2],
                            "collectionFormat": collection,
                        }
                    ]
                }
            }
        },
    }
    operation = parse_import_document(json.dumps(document).encode())[1][0]
    assert [q.value for q in operation.request.query_parameters] == expected


def test_schema_budget_and_yaml_cycles():
    with pytest.raises(ImportDocumentError, match="预算"):
        parse({"type": "object", "properties": {f"p{i}": {} for i in range(501)}})
    with pytest.raises(ImportDocumentError, match="预算"):
        parse_import_document(b"openapi: 3.1.0\npaths: &p\n  child: *p")


def test_boolean_refs_and_ref_siblings():
    operation = parse(
        {
            "$defs": {"No": False},
            "$ref": "#/paths/~1test/post/requestBody/content/application~1json/schema/$defs/No",
            "description": "deny",
        }
    )
    assert operation.canonical_contract.request_body.schema_["allOf"][0] == {"not": {}}


def test_operation_contract_failure_preserves_other_operations():
    document = {
        "openapi": "3.0.3",
        "paths": {
            "/bad": {"get": {"responses": {"200": {"description": "x" * 2001}}}},
            "/ok": {"get": {}},
        },
    }
    operations = parse_import_document(json.dumps(document).encode())[1]
    assert len(operations) == 2
    assert operations[0].canonical_contract.completeness == "partial"
    assert any(d.code == "OPERATION_CONTRACT_PARTIAL" for d in operations[0].diagnostics)
    assert operations[1].canonical_contract.completeness == "complete"


def test_unsafe_property_only_affects_its_operation():
    operation = parse(
        {"type": "object", "properties": {"bad\x00name": {}, "ok": {"type": "string"}}}
    )
    assert operation.canonical_contract.request_body.schema_["properties"] == {
        "ok": {"type": "string"}
    }
    assert operation.canonical_contract.completeness == "partial"


def test_required_composition_is_retained():
    operation = parse(
        {"allOf": [{"required": ["kind"]}, {"properties": {"kind": {"type": "string"}}}]}
    )
    assert operation.canonical_contract.request_body.schema_["allOf"][0]["required"] == ["kind"]


def test_yaml_non_json_default_is_local_diagnostic():
    document = b"""openapi: 3.1.0
paths:
  /date:
    post:
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                date: {type: string, default: 2026-09-15}
                name: {type: string}
"""
    operation = parse_import_document(document)[1][0]
    assert operation.canonical_contract.request_body.schema_["properties"] == {
        "date": {"type": "string"},
        "name": {"type": "string"},
    }
    assert any(d.code == "SOURCE_VALUE_NOT_JSON" for d in operation.diagnostics)


@pytest.mark.parametrize("schema", [{}, True, {"$ref": "#/missing"}])
def test_empty_or_unresolved_body_keeps_media_type(schema):
    operation = parse(schema)
    assert operation.canonical_contract.request_body is not None
    assert operation.canonical_contract.request_body.content_type == "application/json"
    assert operation.canonical_contract.request_body.schema_ == {}


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
def test_both_openapi_composition_versions(version):
    operation = parse(
        {
            "allOf": [
                {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                {"oneOf": [{"type": "string"}, {"type": "number"}]},
                {"not": {"type": "boolean"}},
            ]
        },
        version=version,
    )
    assert len(operation.canonical_contract.request_body.schema_["allOf"]) == 3
    assert operation.canonical_contract.completeness == "complete"


def test_acyclic_schema_beyond_old_twelve_level_limit():
    schema = {"type": "string", "description": "leaf"}
    for _ in range(16):
        schema = {"type": "object", "properties": {"child": schema}}
    operation = parse(schema)
    result = operation.canonical_contract.request_body.schema_
    for _ in range(16):
        result = result["properties"]["child"]
    assert result == {"type": "string", "description": "leaf"}


@pytest.mark.parametrize("reference", ["https://example.test/base.json", "#/missing"])
def test_openapi31_unresolved_ref_retains_local_siblings(reference):
    operation = parse({"$ref": reference, "type": "string", "maxLength": 10})
    assert operation.canonical_contract.request_body.schema_ == {"type": "string", "maxLength": 10}
    assert operation.canonical_contract.completeness == "partial"
    assert any(d.keyword == "$ref" for d in operation.diagnostics)


def test_openapi31_cyclic_ref_retains_siblings():
    operation = parse(
        {"$ref": "#/components/schemas/Base", "maxLength": 10},
        components={"schemas": {"Base": {"$ref": "#/components/schemas/Base", "type": "string"}}},
    )
    schema = operation.canonical_contract.request_body.schema_
    assert schema == {"allOf": [{"type": "string"}, {"maxLength": 10}]}
    assert operation.canonical_contract.completeness == "partial"


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
@pytest.mark.parametrize(
    "serialization,expected",
    [
        ({}, ["1", "2"]),
        ({"style": "form"}, ["1", "2"]),
        ({"explode": False}, ["1,2"]),
        ({"style": "form", "explode": False}, ["1,2"]),
        ({"style": "spaceDelimited"}, ["1 2"]),
        ({"style": "pipeDelimited"}, ["1|2"]),
    ],
)
def test_openapi_query_array_default_serialization(version, serialization, expected):
    document = {
        "openapi": version,
        "paths": {
            "/array": {
                "get": {
                    "parameters": [
                        {
                            "in": "query",
                            "name": "ids",
                            "schema": {"type": "array", "items": {"type": "integer"}},
                            "example": [1, 2],
                            **serialization,
                        }
                    ]
                }
            }
        },
    }
    operation = parse_import_document(json.dumps(document).encode())[1][0]
    assert [q.value for q in operation.request.query_parameters] == expected
