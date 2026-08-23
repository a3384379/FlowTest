from __future__ import annotations

import re
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.test_design import TestDesignDocument, fingerprint_design
from app.domain.test_engineering import OperationContract, TestEngineeringEngine
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
        return OperationContract(
            operation=_operation_name(definition),
            method=version.method,
            path=urlsplit(version.path).path or "/",
            service=service_key,
            auth={"required": version.auth_kind != "none"},
            request=_request_schema(version),
            responses={},
            source_ref=f"api-definition://{definition.id}/version/{version.version}",
            revision=str(version.version),
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
    properties: dict[str, JsonValue] = {}
    required: list[JsonValue] = []
    for parameter in version.query_parameters:
        name = parameter.get("name")
        if not isinstance(name, str):
            continue
        properties[name] = {
            "type": cast(JsonValue, parameter.get("type", "string")),
        }
        if parameter.get("required") is True:
            required.append(name)
    if isinstance(version.body, dict):
        for name, value in sorted(version.body.items()):
            properties[str(name)] = _inferred_schema(cast(JsonValue, value))
    return {
        "type": "object",
        "required": required,
        "properties": properties,
    }


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
