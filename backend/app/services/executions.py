import json
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
from app.services.api_assets import APIAssetService, PreparedRequest
from app.services.projects import ProjectService

SENSITIVE_RESPONSE_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization", "set-cookie", "x-api-key"}
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

        if _serialized_body_size(raw_request.body) > settings.inline_body_limit_bytes:
            return await self._fail_execution(
                execution,
                code="REQUEST_TOO_LARGE",
                message="请求体超过 2 MB 内联上限",
                elapsed_ms=0,
            )

        owned_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(follow_redirects=False)
        started = perf_counter()
        try:
            response = await _send_request(
                client,
                raw_request,
                body_kind=BodyKind(version.body_kind),
                timeout_seconds=timeout_seconds,
            )
            elapsed_ms = (perf_counter() - started) * 1000
            return await self._complete(
                execution=execution,
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

    async def _complete(
        self,
        *,
        execution: APICallExecution,
        response: httpx.Response,
        elapsed_ms: float,
        specs: tuple[AssertionSpec, ...],
    ) -> tuple[APICallExecution, list[AssertionResult]]:
        response_size = len(response.content)
        if response_size > settings.inline_body_limit_bytes:
            return await self._fail_execution(
                execution,
                code="RESPONSE_TOO_LARGE",
                message="响应体超过 2 MB 内联保存上限",
                elapsed_ms=elapsed_ms,
                response_status=response.status_code,
                response_size=response_size,
            )
        body = _response_body(response)
        headers = dict(response.headers)
        outcomes = evaluate_assertions(
            ResponseSnapshot(
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                headers=headers,
                body=body,
            ),
            specs,
        )
        execution.response_status = response.status_code
        execution.response_headers = _redact_response_headers(headers)
        execution.response_body = cast(JsonValue, redact(body))
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
