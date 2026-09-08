import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_s58_failure_repair_api import failure_repair_api as failure_repair_api
from test_s60_continuous_mcp import _account

from app.domain.api_assets import HttpMethod
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.governance import IdempotencyRecord
from app.models.imports import ImportRun
from app.schemas.mcp_contract_import import (
    MCPCommitContractImportRequest,
    MCPContractOperation,
    MCPPreviewContractImportRequest,
)
from app.services import mcp_contract_import as contract_import_module
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


@pytest.mark.asyncio
async def test_mcp_contract_import_rolls_back_business_write_before_receipt_failure(
    failure_repair_api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = failure_repair_api
    _, token = await _account(fixture, ["mcp:contract:import"])
    headers = {"Authorization": f"Bearer {token}"}
    async with fixture["sessions"]() as session:
        environment = await session.get(Environment, fixture["environment_id"])
        assert environment is not None and environment.default_service_id is not None
        service_id = environment.default_service_id
    preview = await fixture["client"].post(
        "/api/v1/mcp/contracts/preview",
        headers=headers,
        json={
            "project_id": str(fixture["project_id"]),
            "source_kind": "operations",
            "operations": [
                {
                    "name": "Atomic contract",
                    "method": "POST",
                    "path": "/s61-atomic-contract",
                    "responses": {"201": {"description": "created"}},
                }
            ],
            "persist": True,
            "service_id": str(service_id),
            "environment_id": str(fixture["environment_id"]),
        },
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    operation_key = preview_body["items"][0]["import_key"]
    commit_payload = {
        "project_id": str(fixture["project_id"]),
        "preview_id": preview_body["preview_id"],
        "preview_sha256": preview_body["source_sha256"],
        "selected_operations": [operation_key],
        "service_id": str(service_id),
        "environment_id": str(fixture["environment_id"]),
    }
    original_response = contract_import_module._commit_response
    attempts = 0

    def fail_once(**kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected failure after business flush")
        return original_response(**kwargs)

    monkeypatch.setattr(contract_import_module, "_commit_response", fail_once)
    idempotency_headers = {**headers, "Idempotency-Key": "s61-import-atomic-v1"}
    failed = await fixture["client"].post(
        "/api/v1/mcp/contracts/commit",
        headers=idempotency_headers,
        json=commit_payload,
    )
    assert failed.status_code == 500
    async with fixture["sessions"]() as session:
        run = await session.get(ImportRun, UUID(preview_body["preview_id"]))
        imported = await session.scalar(
            select(func.count())
            .select_from(APIVersion)
            .join(APIDefinition, APIDefinition.id == APIVersion.api_definition_id)
            .where(
                APIDefinition.project_id == fixture["project_id"],
                APIVersion.path == "/s61-atomic-contract",
            )
        )
        receipts = await session.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.idempotency_key == "s61-import-atomic-v1")
        )
        assert run is not None and run.status == "preview"
        assert imported == 0
        assert receipts == 0

    retried = await fixture["client"].post(
        "/api/v1/mcp/contracts/commit",
        headers=idempotency_headers,
        json=commit_payload,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "applied"
    mismatch = await fixture["client"].post(
        "/api/v1/mcp/contracts/commit",
        headers=idempotency_headers,
        json={**commit_payload, "endpoint_variant": "other"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
