from __future__ import annotations

import re
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.test_design import TestDesignDocument, fingerprint_design
from app.domain.test_engineering import (
    ContractAuth,
    ContractParameter,
    ContractRequestBody,
    OperationContract,
    TestEngineeringEngine,
)
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.schemas.test_engineering import TestEngineeringGenerateRequest
from app.services.projects import ProjectService


class TestEngineeringService:
    def __init__(self, session: AsyncSession) -> None:
        self._projects = ProjectService(session)
        self._assets = APIAssetRepository(session)
        self._targets = ServiceTargetRepository(session)

    async def generate(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: TestEngineeringGenerateRequest,
    ) -> tuple[TestDesignDocument, str]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        contract = payload.contract
        if payload.api_definition_id is not None:
            contract = await self.contract_for_api(
                project_id=project_id, definition_id=payload.api_definition_id
            )
        if contract is None:
            raise AppError(
                code="TEST_ENGINEERING_SOURCE_REQUIRED",
                message="必须提供 API 定义或类型化 Contract",
                status_code=422,
            )
        design = TestEngineeringEngine().generate(
            contract=contract,
            policy=payload.generation_policy,
            additional_evidence=payload.additional_evidence,
        )
        return design, fingerprint_design(design)

    async def contract_for_api(self, *, project_id: UUID, definition_id: UUID) -> OperationContract:
        definition = await self._assets.get_definition(definition_id)
        if definition is None or definition.project_id != project_id:
            raise AppError(
                code="API_DEFINITION_NOT_FOUND", message="API 定义不存在", status_code=404
            )
        version = await self._assets.get_version(
            definition_id=definition.id, version=definition.current_version
        )
        if version is None:
            raise AppError(code="API_VERSION_NOT_FOUND", message="API 版本不存在", status_code=404)
        service_key = await self._service_key(project_id, definition)
        if version.canonical_contract:
            try:
                stored = OperationContract.model_validate(version.canonical_contract)
            except ValueError as error:
                raise AppError(
                    code="API_CANONICAL_CONTRACT_INVALID",
                    message="API 版本的 canonical contract 无法解析",
                    status_code=409,
                ) from error
            return stored.model_copy(
                update={
                    "service": service_key,
                    "source_ref": (
                        stored.source_ref
                        or f"api-definition://{definition.id}/version/{version.version}"
                    ),
                    "revision": stored.revision or str(version.version),
                    "completeness": version.contract_completeness,
                }
            )
        body_schema = _request_schema(version)
        return OperationContract(
            operation=_operation_name(definition),
            method=version.method,
            path=urlsplit(version.path).path or "/",
            service=service_key,
            auth=ContractAuth(
                required=version.auth_kind != "none",
                kind=version.auth_kind,
                location=(
                    version.auth_config.get("in")
                    if version.auth_config.get("in") in {"header", "query", "cookie"}
                    else ("header" if version.auth_kind != "none" else None)
                ),
                name=version.auth_config.get("name"),
            ),
            parameters=_version_parameters(version),
            request_body=(ContractRequestBody(schema=body_schema) if body_schema else None),
            request=body_schema,
            responses={},
            source_ref=f"api-definition://{definition.id}/version/{version.version}",
            revision=str(version.version),
            completeness="legacy_partial",
        )

    async def _service_key(self, project_id: UUID, definition: APIDefinition) -> str | None:
        if definition.service_id is None:
            return None
        service = await self._targets.get_service(definition.service_id)
        if service is None or service.project_id != project_id:
            raise AppError(
                code="SERVICE_NOT_FOUND", message="API 关联的 Service 不存在", status_code=404
            )
        return service.service_key


def _operation_name(definition: APIDefinition) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.:]", "_", definition.name).strip("_")
    if not normalized or (not normalized[0].isalpha() and normalized[0] != "_"):
        normalized = f"api_{normalized}"
    return normalized[:240]


def _request_schema(version: APIVersion) -> dict[str, JsonValue]:
    if isinstance(version.body, dict):
        return _inferred_schema(cast(JsonValue, version.body))
    return {}


def _version_parameters(version: APIVersion) -> list[ContractParameter]:
    parameters = [
        ContractParameter(
            name=str(item["name"]),
            location="query",
            required=item.get("required") is True,
            schema={"type": cast(JsonValue, item.get("type", "string"))},
        )
        for item in version.query_parameters
        if isinstance(item.get("name"), str)
    ]
    parameters.extend(
        ContractParameter(
            name=name,
            location="header",
            schema={"type": "string"},
        )
        for name in sorted(version.headers)
    )
    parameters.extend(
        ContractParameter(name=name, location="path", required=True, schema={"type": "string"})
        for name in re.findall(r"\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}", version.path)
    )
    return parameters


def _inferred_schema(value: JsonValue) -> dict[str, JsonValue]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        return {"type": "array"}
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {str(key): _inferred_schema(child) for key, child in value.items()},
        }
    return {"type": "string"}
