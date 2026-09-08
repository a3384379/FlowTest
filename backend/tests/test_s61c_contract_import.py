import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.api_assets import HttpMethod
from app.schemas.mcp_contract_import import (
    MCPCommitContractImportRequest,
    MCPContractOperation,
    MCPPreviewContractImportRequest,
)
from app.services.mcp_contract_import import _operations_document


def test_source_derived_operations_become_an_openapi_document_without_values() -> None:
    operation = MCPContractOperation(
        name="list users",
        method=HttpMethod.GET,
        path="/users/{tenant_id}",
        parameters=[
            {
                "name": "tenant_id",
                "location": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        responses={"200": {"description": "ok", "schema": {"type": "array"}}},
    )
    document = json.loads(_operations_document([operation]))
    assert document["openapi"] == "3.0.3"
    assert document["paths"]["/users/{tenant_id}"]["get"]["parameters"][0]["name"] == "tenant_id"
    assert "value" not in json.dumps(document)


def test_contract_import_sources_are_mutually_exclusive_and_strict() -> None:
    with pytest.raises(ValidationError):
        MCPPreviewContractImportRequest(
            project_id=uuid4(),
            source_kind="document",
            document_name="contract.json",
            document_content="{}",
            source_url="https://example.test/openapi.json",
        )
    with pytest.raises(ValidationError):
        MCPPreviewContractImportRequest(
            project_id=uuid4(),
            source_kind="url",
            source_url="https://example.test/openapi.json?token=secret",
        )
    with pytest.raises(ValidationError):
        MCPCommitContractImportRequest(
            project_id=uuid4(),
            preview_id=uuid4(),
            preview_sha256="0" * 64,
            selected_operations=["same", "same"],
        )
