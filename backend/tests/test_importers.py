import json

import pytest

from app.domain.api_assets import AuthKind, BodyKind, HttpMethod
from app.importers.contracts import ImportSourceType
from app.importers.document import ImportDocumentError, parse_import_document


def test_openapi3_yaml_parses_operations_auth_and_request_bodies() -> None:
    document = b"""
openapi: 3.0.3
info: {title: Sample, version: 1.0.0}
components:
  securitySchemes:
    bearerAuth: {type: http, scheme: bearer}
security: [{bearerAuth: []}]
paths:
  /users/{user_id}:
    get:
      summary: Query user
      parameters:
        - {in: path, name: user_id, required: true, schema: {type: string}}
        - {in: query, name: verbose, example: 'true'}
      responses: {'200': {description: ok}}
  /orders:
    post:
      operationId: createOrder
      security: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                product: {type: string}
                amount: {type: integer}
      responses: {'201': {description: created}}
"""

    source_type, operations = parse_import_document(document)

    assert source_type is ImportSourceType.OPENAPI3
    assert len(operations) == 2
    query_user = operations[0]
    assert query_user.request.method is HttpMethod.GET
    assert query_user.request.path == "/users/{{user_id}}"
    assert query_user.request.query_parameters[0].value == "true"
    assert query_user.request.auth_kind is AuthKind.BEARER
    assert query_user.request.auth_config["token"] == "{{secret.bearerAuth}}"
    assert query_user.canonical_contract is not None
    assert [
        (parameter.location, parameter.name, parameter.required)
        for parameter in query_user.canonical_contract.parameters
    ] == [("path", "user_id", True), ("query", "verbose", False)]
    assert query_user.canonical_contract.responses["200"].description == "ok"
    assert operations[1].request.body_kind is BodyKind.JSON
    assert operations[1].request.body == {"product": "", "amount": 0}
    assert operations[1].request.auth_kind is AuthKind.NONE
    assert operations[1].canonical_contract is not None
    assert operations[1].canonical_contract.request_body is not None
    assert operations[1].canonical_contract.request_body.schema_["properties"] == {
        "product": {"type": "string"},
        "amount": {"type": "integer"},
    }


def test_openapi_servers_become_request_target_base_urls() -> None:
    openapi = {
        "openapi": "3.0.3",
        "info": {"title": "Targeted API", "version": "1.0.0"},
        "servers": [
            {
                "url": "https://{region}.example.com/{version}",
                "variables": {
                    "region": {"default": "api"},
                    "version": {"default": "v1"},
                },
            }
        ],
        "paths": {"/orders": {"get": {"summary": "List orders"}}},
    }

    _, operations = parse_import_document(json.dumps(openapi).encode())

    assert operations[0].target_base_url == "https://api.example.com/v1"

    swagger = {
        "swagger": "2.0",
        "info": {"title": "Legacy API", "version": "1.0.0"},
        "schemes": ["http"],
        "host": "legacy.example.com",
        "basePath": "/v2",
        "paths": {"/orders": {"get": {"summary": "List orders"}}},
    }
    _, swagger_operations = parse_import_document(
        json.dumps(swagger).encode(), ImportSourceType.SWAGGER2
    )

    assert swagger_operations[0].target_base_url == "http://legacy.example.com/v2"


def test_swagger2_and_postman_documents_are_supported() -> None:
    swagger = {
        "swagger": "2.0",
        "info": {"title": "Legacy", "version": "1"},
        "basePath": "/v1",
        "securityDefinitions": {"basicAuth": {"type": "basic"}},
        "paths": {
            "/upload": {
                "post": {
                    "summary": "Upload",
                    "security": [{"basicAuth": []}],
                    "consumes": ["multipart/form-data"],
                    "parameters": [{"name": "file", "in": "formData", "type": "file"}],
                }
            }
        },
    }
    source_type, operations = parse_import_document(
        json.dumps(swagger).encode(), ImportSourceType.SWAGGER2
    )
    assert source_type is ImportSourceType.SWAGGER2
    assert operations[0].request.path == "/v1/upload"
    assert operations[0].request.body_kind is BodyKind.MULTIPART
    assert operations[0].request.auth_kind is AuthKind.BASIC

    postman = {
        "info": {
            "name": "Collection",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {
            "type": "apikey",
            "apikey": [
                {"key": "key", "value": "X-Key"},
                {"key": "value", "value": "embedded-secret"},
            ],
        },
        "item": [
            {
                "name": "Create order",
                "request": {
                    "method": "POST",
                    "url": "{{baseUrl}}/orders?dry_run=true",
                    "body": {
                        "mode": "raw",
                        "raw": '{"amount": 2}',
                        "options": {"language": "json"},
                    },
                },
            }
        ],
    }
    source_type, operations = parse_import_document(json.dumps(postman).encode())
    assert source_type is ImportSourceType.POSTMAN
    assert operations[0].request.path == "/orders"
    assert operations[0].request.query_parameters[0].name == "dry_run"
    assert operations[0].request.body == {"amount": 2}
    assert operations[0].request.auth_kind is AuthKind.API_KEY
    assert operations[0].request.auth_config["value"] == "{{secret.IMPORTED_API_KEY}}"


def test_import_fingerprints_distinguish_identity_from_content() -> None:
    first = _one_openapi("Original")
    changed = _one_openapi("Changed")

    _, first_operations = parse_import_document(first)
    _, changed_operations = parse_import_document(changed)

    assert first_operations[0].import_key == changed_operations[0].import_key
    assert first_operations[0].content_fingerprint != changed_operations[0].content_fingerprint


def test_curl_import_redacts_credentials_and_never_accepts_shell_options() -> None:
    source_type, operations = parse_import_document(
        b"curl -u tester:password -H 'Authorization: Bearer token' https://api.example.com/users"
    )

    assert source_type is ImportSourceType.CURL
    request = operations[0].request
    assert request.auth_config["password"] == "{{secret.IMPORTED_PASSWORD}}"
    assert request.headers["Authorization"] == "{{secret.IMPORTED_AUTHORIZATION}}"

    with pytest.raises(ImportDocumentError, match="暂不支持"):
        parse_import_document(
            b"curl https://api.example.com --output /tmp/exfiltrated",
            ImportSourceType.CURL,
        )


@pytest.mark.parametrize(
    "content",
    [
        b"curl https://one.example.com https://two.example.com",
        b"curl --request TRACE https://api.example.com",
        b"curl 'https://api.example.com",
        b"not-curl https://api.example.com",
    ],
)
def test_malformed_curl_commands_are_rejected(content: bytes) -> None:
    with pytest.raises(ImportDocumentError):
        parse_import_document(content, ImportSourceType.CURL)


@pytest.mark.parametrize("content", [b"[]", b"not: [valid"])
def test_invalid_documents_are_rejected(content: bytes) -> None:
    with pytest.raises(ImportDocumentError):
        parse_import_document(content)


def _one_openapi(summary: str) -> bytes:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Sample", "version": "1"},
            "paths": {"/users": {"get": {"summary": summary}}},
        }
    ).encode()
