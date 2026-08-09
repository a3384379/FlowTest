import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import SENSITIVE_KEYS, redact
from app.domain.api_assets import BodyKind, JsonValue
from app.domain.assertions import (
    AssertionOutcome,
    AssertionSpec,
    ResponseSnapshot,
    evaluate_assertions,
)
from app.domain.execution import ExecutionStatus
from app.models.access import User
from app.models.executions import APICallExecution, AssertionResult
from app.repositories.executions import ExecutionRepository
from app.schemas.api_assets import MultipartBody
from app.services.api_assets import APIAssetService, PreparedRequest
from app.services.artifacts import ArtifactService
from app.services.projects import ProjectService

SENSITIVE_RESPONSE_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization", "set-cookie", "x-api-key"}
)


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    field: str
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class PreparedMultipart:
    fields: dict[str, str]
    files: tuple[PreparedUpload, ...]

    @property
    def size_bytes(self) -> int:
        return sum(len(item.content) for item in self.files) + sum(
            len(name.encode()) + len(value.encode()) for name, value in self.fields.items()
        )


class ExecutionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session = session
        self._repository = ExecutionRepository(session)
        self._assets = APIAssetService(session)
        self._artifacts = ArtifactService(session)
        self._projects = ProjectService(session)
        self._http_client = http_client

    async def execute(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition_id: UUID,
        environment_id: UUID,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        body_override: JsonValue,
        use_body_override: bool,
        timeout_seconds: int,
        assertions: tuple[AssertionSpec, ...],
    ) -> tuple[APICallExecution, list[AssertionResult]]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        _definition, version = await self._assets.get_detail(
            actor=actor,
            project_id=project_id,
            definition_id=definition_id,
        )
        raw_request = await self._assets.preview(
            actor=actor,
            project_id=project_id,
            definition_id=definition_id,
            environment_id=environment_id,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
            body_override=body_override,
            use_body_override=use_body_override,
            redact=False,
        )
        redacted_request = await self._assets.preview(
            actor=actor,
            project_id=project_id,
            definition_id=definition_id,
            environment_id=environment_id,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
            body_override=body_override,
            use_body_override=use_body_override,
            redact=True,
        )
        body_kind = BodyKind(version.body_kind)
        multipart = (
            await self._prepare_multipart(project_id=project_id, body=raw_request.body)
            if body_kind is BodyKind.MULTIPART
            else None
        )
        execution = APICallExecution(
            project_id=project_id,
            api_definition_id=definition_id,
            api_version_id=version.id,
            environment_id=environment_id,
            triggered_by_id=actor.id,
            status=ExecutionStatus.RUNNING.value,
            request_method=raw_request.method.value,
            request_url=_redact_request_url(redacted_request.url),
            request_headers=cast(
                dict[str, str],
                redact({header.name: header.value for header in redacted_request.headers}),
            ),
            request_body=cast(JsonValue, redact(redacted_request.body)),
            response_status=None,
            response_headers={},
            response_body=None,
            response_artifact_id=None,
            response_size_bytes=None,
            elapsed_ms=None,
            error_code=None,
            error_message=None,
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        self._repository.add(execution)
        await self._session.commit()
        await self._session.refresh(execution)

        request_size = (
            multipart.size_bytes
            if multipart is not None
            else _serialized_body_size(raw_request.body)
        )
        request_limit = (
            settings.artifact_limit_bytes
            if body_kind is BodyKind.MULTIPART
            else settings.inline_body_limit_bytes
        )
        if request_size > request_limit:
            return await self._fail_execution(
                execution,
                code="REQUEST_TOO_LARGE",
                message="请求体超过允许的大小上限",
                elapsed_ms=0,
            )

        owned_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(follow_redirects=False)
        started = perf_counter()
        try:
            response = await _send_request(
                client,
                raw_request,
                body_kind=body_kind,
                timeout_seconds=timeout_seconds,
                multipart=multipart,
            )
            elapsed_ms = (perf_counter() - started) * 1000
            return await self._complete(
                execution=execution,
                actor=actor,
                project_id=project_id,
                response=response,
                elapsed_ms=elapsed_ms,
                specs=assertions,
            )
        except httpx.TimeoutException:
            return await self._fail_execution(
                execution,
                code="REQUEST_TIMEOUT",
                message=f"请求在 {timeout_seconds} 秒后超时",
                elapsed_ms=(perf_counter() - started) * 1000,
            )
        except httpx.HTTPError:
            return await self._fail_execution(
                execution,
                code="NETWORK_ERROR",
                message="无法连接目标服务",
                elapsed_ms=(perf_counter() - started) * 1000,
            )
        finally:
            if owned_client:
                await client.aclose()

    async def list_executions(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[APICallExecution], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_for_project(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get_execution(
        self, *, actor: User, project_id: UUID, execution_id: UUID
    ) -> tuple[APICallExecution, list[AssertionResult]]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        execution = await self._repository.get(execution_id)
        if execution is None or execution.project_id != project_id:
            raise AppError(code="EXECUTION_NOT_FOUND", message="执行记录不存在", status_code=404)
        assertions = await self._repository.list_assertions(execution.id)
        return execution, assertions

    async def _prepare_multipart(self, *, project_id: UUID, body: JsonValue) -> PreparedMultipart:
        payload = MultipartBody.model_validate(body)
        files: list[PreparedUpload] = []
        for reference in payload.files:
            loaded = await self._artifacts.load(
                project_id=project_id,
                artifact_id=reference.artifact_id,
            )
            files.append(
                PreparedUpload(
                    field=reference.field,
                    filename=loaded.artifact.filename,
                    content_type=loaded.artifact.content_type,
                    content=loaded.content,
                )
            )
        return PreparedMultipart(fields=payload.fields, files=tuple(files))

    async def _complete(
        self,
        *,
        execution: APICallExecution,
        actor: User,
        project_id: UUID,
        response: httpx.Response,
        elapsed_ms: float,
        specs: tuple[AssertionSpec, ...],
    ) -> tuple[APICallExecution, list[AssertionResult]]:
        response_size = len(response.content)
        if response_size > settings.artifact_limit_bytes:
            return await self._fail_execution(
                execution,
                code="RESPONSE_TOO_LARGE",
                message="响应体超过 50 MB 上限",
                elapsed_ms=elapsed_ms,
                response_status=response.status_code,
                response_size=response_size,
            )
        headers = dict(response.headers)
        content_type = _content_type(headers)
        content_sha256 = hashlib.sha256(response.content).hexdigest()
        body, artifact_id = await self._persist_response_body(
            actor=actor,
            project_id=project_id,
            response=response,
            content_type=content_type,
        )
        outcomes = evaluate_assertions(
            ResponseSnapshot(
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                headers=headers,
                body=body,
                content_size=response_size,
                content_sha256=content_sha256,
                content_type=content_type,
            ),
            specs,
        )
        execution.response_status = response.status_code
        execution.response_headers = _redact_response_headers(headers)
        execution.response_body = cast(JsonValue, redact(body))
        execution.response_artifact_id = artifact_id
        execution.response_size_bytes = response_size
        execution.elapsed_ms = elapsed_ms
        execution.status = (
            ExecutionStatus.PASSED.value
            if all(outcome.passed for outcome in outcomes)
            else ExecutionStatus.FAILED.value
        )
        execution.completed_at = datetime.now(UTC)
        results = [self._assertion_result(execution.id, outcome) for outcome in outcomes]
        for result in results:
            self._repository.add(result)
        await self._session.commit()
        await self._session.refresh(execution)
        for result in results:
            await self._session.refresh(result)
        return execution, results

    async def _persist_response_body(
        self,
        *,
        actor: User,
        project_id: UUID,
        response: httpx.Response,
        content_type: str,
    ) -> tuple[JsonValue, UUID | None]:
        if not response.content:
            return None, None
        if len(response.content) <= settings.inline_body_limit_bytes and _is_inline(content_type):
            return _response_body(response), None
        artifact = await self._artifacts.store_response(
            actor=actor,
            project_id=project_id,
            filename=_response_filename(response.headers),
            content_type=content_type,
            content=response.content,
        )
        return (
            {
                "artifact_id": str(artifact.id),
                "filename": artifact.filename,
                "content_type": artifact.content_type,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
            },
            artifact.id,
        )

    async def _fail_execution(
        self,
        execution: APICallExecution,
        *,
        code: str,
        message: str,
        elapsed_ms: float,
        response_status: int | None = None,
        response_size: int | None = None,
    ) -> tuple[APICallExecution, list[AssertionResult]]:
        execution.status = ExecutionStatus.ERROR.value
        execution.error_code = code
        execution.error_message = message
        execution.elapsed_ms = elapsed_ms
        execution.response_status = response_status
        execution.response_size_bytes = response_size
        execution.completed_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(execution)
        return execution, []

    @staticmethod
    def _assertion_result(execution_id: UUID, outcome: AssertionOutcome) -> AssertionResult:
        return AssertionResult(
            execution_id=execution_id,
            kind=outcome.spec.kind.value,
            operator=outcome.spec.operator.value,
            target=outcome.spec.target,
            expected=outcome.spec.expected,
            actual=outcome.actual,
            passed=outcome.passed,
            message=outcome.message,
        )


async def _send_request(
    client: httpx.AsyncClient,
    request: PreparedRequest,
    *,
    body_kind: BodyKind,
    timeout_seconds: int,
    multipart: PreparedMultipart | None = None,
) -> httpx.Response:
    headers = {header.name: header.value for header in request.headers}
    timeout = httpx.Timeout(timeout_seconds)
    if body_kind is BodyKind.JSON:
        return await client.request(
            request.method.value,
            request.url,
            headers=headers,
            json=request.body,
            timeout=timeout,
        )
    if body_kind is BodyKind.RAW:
        content = request.body if isinstance(request.body, str) else str(request.body or "")
        return await client.request(
            request.method.value,
            request.url,
            headers=headers,
            content=content,
            timeout=timeout,
        )
    if body_kind is BodyKind.FORM:
        form = request.body if isinstance(request.body, dict) else {}
        return await client.request(
            request.method.value,
            request.url,
            headers=headers,
            data=form,
            timeout=timeout,
        )
    if body_kind is BodyKind.MULTIPART:
        if multipart is None:
            raise ValueError("Multipart request requires prepared files")
        multipart_headers = {
            name: value for name, value in headers.items() if name.lower() != "content-type"
        }
        files = [
            (item.field, (item.filename, item.content, item.content_type))
            for item in multipart.files
        ]
        return await client.request(
            request.method.value,
            request.url,
            headers=multipart_headers,
            data=multipart.fields,
            files=files,
            timeout=timeout,
        )
    return await client.request(
        request.method.value,
        request.url,
        headers=headers,
        timeout=timeout,
    )


def _response_body(response: httpx.Response) -> JsonValue:
    if not response.content:
        return None
    try:
        return cast(JsonValue, response.json())
    except ValueError:
        return response.text


def _content_type(headers: dict[str, str]) -> str:
    return headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()


def _is_inline(content_type: str) -> bool:
    return (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml", "application/javascript"}
        or content_type.endswith("+json")
        or content_type.endswith("+xml")
    )


def _response_filename(headers: httpx.Headers) -> str:
    disposition = headers.get("content-disposition", "")
    encoded_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.IGNORECASE)
    if encoded_match:
        from urllib.parse import unquote

        return unquote(encoded_match.group(1))
    match = re.search(r'filename="?([^";]+)', disposition, flags=re.IGNORECASE)
    return match.group(1).strip() if match else "response.bin"


def _redact_response_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: "***" if name.lower() in SENSITIVE_RESPONSE_HEADERS else value
        for name, value in headers.items()
    }


def _redact_request_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (name, "***" if name.lower() in SENSITIVE_KEYS else value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _serialized_body_size(body: JsonValue) -> int:
    if body is None:
        return 0
    if isinstance(body, str):
        return len(body.encode())
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
