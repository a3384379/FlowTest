import json
import warnings
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import schemathesis
from hypothesis.errors import HypothesisException, NonInteractiveExampleWarning
from pydantic import JsonValue
from schemathesis.core import NOT_SET
from schemathesis.generation import GenerationMode
from schemathesis.specs.openapi.schemas import OpenApiSchema
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.contracts import (
    ContractOperation,
    ContractSchemaError,
    breaking_changes,
    contract_operations,
    document_sha256,
    load_contract_document,
    schema_coverage,
)
from app.importers.contracts import sanitize_imported_json
from app.models.access import User
from app.models.contracts import ContractRun, GeneratedContractCase
from app.repositories.contracts import ContractRepository
from app.services.audit import AuditService
from app.services.projects import ProjectService

MAX_EDITED_DEFINITION_BYTES = 256 * 1024


class ContractService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._contracts = ContractRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_run(
        self,
        *,
        actor: User,
        project_id: UUID,
        source_name: str,
        content: bytes,
        baseline_run_id: UUID | None,
    ) -> ContractRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        document = _load_document(content)
        try:
            operations = contract_operations(document)
        except ContractSchemaError as error:
            raise AppError(
                code="CONTRACT_SCHEMA_INVALID", message=str(error), status_code=422
            ) from error
        _validate_with_schemathesis(content)
        normalized_source = source_name.strip()[:255] or "openapi.yaml"
        baseline = await self._resolve_baseline(
            project_id=project_id,
            source_name=normalized_source,
            baseline_run_id=baseline_run_id,
        )
        baseline_operations = (
            contract_operations(cast(dict[str, JsonValue], baseline.schema_document))
            if baseline
            else ()
        )
        changes = breaking_changes(baseline_operations, operations)
        summary = _diff_summary(baseline_operations, operations)
        run = ContractRun(
            project_id=project_id,
            baseline_run_id=baseline.id if baseline else None,
            source_name=normalized_source,
            source_type="openapi3" if "openapi" in document else "swagger2",
            source_sha256=document_sha256(document),
            status="completed",
            schema_document=document,
            diff_summary=summary,
            breaking_changes=[item.as_json() for item in changes],
            coverage=schema_coverage(operations),
            generated_case_count=0,
            created_by_id=actor.id,
        )
        self._contracts.add_run(run)
        await self._session.flush()
        generated = _generate_cases(run=run, operations=operations, content=content)
        self._contracts.add_cases(generated)
        run.generated_case_count = len(generated)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="contract.run_created",
            resource_type="contract_run",
            resource_id=run.id,
            details={
                "source_name": normalized_source,
                "baseline_run_id": str(run.baseline_run_id) if run.baseline_run_id else None,
                "breaking_count": len(changes),
                "generated_case_count": len(generated),
            },
        )
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def list_runs(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[ContractRun], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._contracts.list_runs(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get_run(self, *, actor: User, project_id: UUID, run_id: UUID) -> ContractRun:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._get_project_run(project_id, run_id)

    async def list_generated_cases(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        review_status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[GeneratedContractCase], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        await self._get_project_run(project_id, run_id)
        return await self._contracts.list_cases(
            run_id=run_id,
            review_status=review_status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def review_case(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        case_id: UUID,
        accept: bool,
        name: str | None,
        definition: dict[str, JsonValue] | None,
        note: str,
    ) -> GeneratedContractCase:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        await self._get_project_run(project_id, run_id)
        model = await self._contracts.get_case_for_update(case_id)
        if model is None or model.contract_run_id != run_id:
            raise AppError(
                code="GENERATED_CASE_NOT_FOUND", message="契约生成用例不存在", status_code=404
            )
        if model.review_status != "pending":
            raise AppError(
                code="GENERATED_CASE_ALREADY_REVIEWED",
                message="契约生成用例已经完成审核",
                status_code=409,
            )
        if name is not None:
            model.name = name.strip()
        if definition is not None:
            if not accept:
                raise AppError(
                    code="GENERATED_CASE_EDIT_REJECTED",
                    message="拒绝用例时不能修改定义",
                    status_code=422,
                )
            model.definition = _reviewed_definition(definition)
        else:
            model.definition = {**model.definition, "confirmed": accept}
        model.review_status = "accepted" if accept else "rejected"
        model.review_note = note.strip()
        model.reviewed_by_id = actor.id
        model.reviewed_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action=f"contract.generated_case_{model.review_status}",
            resource_type="generated_contract_case",
            resource_id=model.id,
            details={"contract_run_id": str(run_id), "operation_key": model.operation_key},
        )
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def _resolve_baseline(
        self, *, project_id: UUID, source_name: str, baseline_run_id: UUID | None
    ) -> ContractRun | None:
        if baseline_run_id is None:
            return await self._contracts.latest_run(project_id=project_id, source_name=source_name)
        return await self._get_project_run(project_id, baseline_run_id)

    async def _get_project_run(self, project_id: UUID, run_id: UUID) -> ContractRun:
        model = await self._contracts.get_run(run_id)
        if model is None or model.project_id != project_id:
            raise AppError(code="CONTRACT_RUN_NOT_FOUND", message="契约运行不存在", status_code=404)
        return model


def _load_document(content: bytes) -> dict[str, JsonValue]:
    try:
        return load_contract_document(content)
    except ContractSchemaError as error:
        raise AppError(
            code="CONTRACT_SCHEMA_INVALID", message=str(error), status_code=422
        ) from error


def _validate_with_schemathesis(content: bytes) -> None:
    try:
        schemathesis.openapi.from_file(content.decode("utf-8"))
    except Exception as error:
        raise AppError(
            code="CONTRACT_SCHEMA_INVALID",
            message="Schemathesis 无法加载该 OpenAPI 文档",
            status_code=422,
            details={"validator": "schemathesis"},
        ) from error


def _generate_cases(
    *, run: ContractRun, operations: tuple[ContractOperation, ...], content: bytes
) -> list[GeneratedContractCase]:
    schema = schemathesis.openapi.from_file(content.decode("utf-8"))
    cases: list[GeneratedContractCase] = []
    for operation in operations:
        cases.append(_boundary_case(run, operation))
        cases.append(_strategy_case(run, operation, schema, GenerationMode.POSITIVE, "property"))
        cases.append(_strategy_case(run, operation, schema, GenerationMode.NEGATIVE, "negative"))
    return cases


def _strategy_case(
    run: ContractRun,
    operation: ContractOperation,
    schema: OpenApiSchema,
    mode: GenerationMode,
    kind: str,
) -> GeneratedContractCase:
    request: dict[str, JsonValue]
    try:
        api_operation = schema[operation.path][operation.method]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NonInteractiveExampleWarning)
            case = api_operation.as_strategy(generation_mode=mode).example()
        request = _serialize_schemathesis_case(case)
    except (HypothesisException, KeyError, TypeError, ValueError):
        request = {
            "method": operation.method,
            "path": operation.path,
            "generation_fallback": True,
        }
    return _case_model(run, operation, kind, request)


def _boundary_case(run: ContractRun, operation: ContractOperation) -> GeneratedContractCase:
    required = operation.request_signature.get("required", [])
    types = operation.request_signature.get("types", {})
    request: dict[str, JsonValue] = {
        "method": operation.method,
        "path": operation.path,
        "required_fields": required,
        "field_types": types,
        "boundary_policy": "minimum/maximum/minLength/maxLength",
    }
    return _case_model(run, operation, "boundary", request)


def _case_model(
    run: ContractRun,
    operation: ContractOperation,
    kind: str,
    request: dict[str, JsonValue],
) -> GeneratedContractCase:
    safe_request = sanitize_imported_json(cast(JsonValue, request))
    definition: dict[str, JsonValue] = {
        "schema_sha256": run.source_sha256,
        "operation_key": operation.key,
        "generation": {
            "engine": "schemathesis",
            "engine_version": schemathesis.__version__,
            "kind": kind,
        },
        "request": safe_request,
        "checks": [
            "not_a_server_error",
            "status_code_conformance",
            "response_schema_conformance",
        ],
        "confirmed": False,
    }
    return GeneratedContractCase(
        contract_run_id=run.id,
        operation_key=operation.key,
        operation_id=operation.operation_id,
        method=operation.method,
        path=operation.path,
        generation_kind=kind,
        name=f"{operation.operation_id} · {_kind_label(kind)}"[:200],
        definition=definition,
        review_status="pending",
        review_note="",
        reviewed_by_id=None,
        reviewed_at=None,
    )


def _serialize_schemathesis_case(case: object) -> dict[str, JsonValue]:
    body = getattr(case, "body", NOT_SET)
    request: dict[str, object] = {
        "method": getattr(case, "method", ""),
        "path": getattr(getattr(case, "operation", None), "path", ""),
        "path_parameters": getattr(case, "path_parameters", None) or {},
        "query": getattr(case, "query", None) or {},
        "headers": getattr(case, "headers", None) or {},
        "cookies": getattr(case, "cookies", None) or {},
        "body": None if body is NOT_SET else body,
        "media_type": getattr(case, "media_type", None),
    }
    return cast(dict[str, JsonValue], _json_safe(request))


def _json_safe(value: object) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(json.dumps(value)))
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)


def _reviewed_definition(definition: dict[str, JsonValue]) -> dict[str, JsonValue]:
    safe = sanitize_imported_json(cast(JsonValue, definition))
    if not isinstance(safe, dict):
        raise AppError(
            code="GENERATED_CASE_DEFINITION_INVALID",
            message="用例定义必须是对象",
            status_code=422,
        )
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_EDITED_DEFINITION_BYTES:
        raise AppError(
            code="GENERATED_CASE_DEFINITION_TOO_LARGE",
            message="用例定义超过 256 KB 上限",
            status_code=413,
        )
    required_keys = {"schema_sha256", "operation_key", "generation", "request", "checks"}
    if not required_keys.issubset(safe):
        raise AppError(
            code="GENERATED_CASE_DEFINITION_INVALID",
            message="用例定义缺少必要字段",
            status_code=422,
        )
    if not isinstance(safe["generation"], dict) or not isinstance(safe["request"], dict):
        raise AppError(
            code="GENERATED_CASE_DEFINITION_INVALID",
            message="用例生成信息和请求必须是对象",
            status_code=422,
        )
    checks = safe["checks"]
    if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
        raise AppError(
            code="GENERATED_CASE_DEFINITION_INVALID",
            message="用例检查项必须是字符串列表",
            status_code=422,
        )
    return {**safe, "confirmed": True}


def _diff_summary(
    baseline: tuple[ContractOperation, ...], current: tuple[ContractOperation, ...]
) -> dict[str, JsonValue]:
    old = {item.key: item for item in baseline}
    new = {item.key: item for item in current}
    shared = old.keys() & new.keys()
    changed = sum(
        old[key].request_signature != new[key].request_signature
        or old[key].response_signature != new[key].response_signature
        for key in shared
    )
    return {
        "added": len(new.keys() - old.keys()),
        "changed": changed,
        "deleted": len(old.keys() - new.keys()),
        "unchanged": len(shared) - changed,
    }


def _kind_label(kind: str) -> str:
    return {"boundary": "边界", "property": "属性", "negative": "异常"}.get(kind, kind)
