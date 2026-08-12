import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_ai_job_dispatcher
from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.domain.ai import REDACTED, AIInputError, sanitize_ai_input
from app.http.ai import OpenAICompatibleConfiguration, OpenAICompatibleProvider
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.ai import AISuggestion
from app.services.ai import AIJobRunner, AIProviderError, AIProviderResult

ADMIN_EMAIL = "ai-admin@example.com"
ADMIN_PASSWORD = "ai-password-123!"


@dataclass(slots=True)
class FakeAIQueue:
    job_ids: list[UUID] = field(default_factory=list)

    def start_ai_job(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


class FailingAIQueue:
    def start_ai_job(self, job_id: UUID) -> None:
        raise RuntimeError(f"queue rejected {job_id}")


@dataclass(slots=True)
class AIEnvironment:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    queue: FakeAIQueue


@pytest.fixture
async def ai_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AIEnvironment]:
    monkeypatch.setattr(settings, "feature_ai_enabled", True)
    monkeypatch.setattr(settings, "ai_base_url", "https://ai-gateway.example/v1")
    monkeypatch.setattr(settings, "ai_model", "flowtest-eval-model")
    monkeypatch.setattr(settings, "ai_api_key", "provider-key-must-not-leak")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="AI administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    queue = FakeAIQueue()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_ai_job_dispatcher] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield AIEnvironment(client=client, sessions=sessions, queue=queue)
    app.dependency_overrides.clear()
    await engine.dispose()


def test_ai_input_redacts_sensitive_metadata_and_schema_examples() -> None:
    secret = "super-secret-password"
    bearer = "Bearer abcdefghijklmnopqrstuvwxyz"
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature123"
    sanitized = sanitize_ai_input(
        schema_document={
            "type": "object",
            "properties": {
                "password": {
                    "type": "string",
                    "format": "password",
                    "example": secret,
                }
            },
        },
        metadata={
            "Authorization": bearer,
            "nested": {"clientSecret": secret, "message": f"token={jwt}"},
        },
        sample={"cookie": "session=private", "safe": "visible"},
    )
    encoded = json.dumps(sanitized.payload, ensure_ascii=False)
    assert secret not in encoded
    assert bearer not in encoded
    assert jwt not in encoded
    assert sanitized.payload["metadata"] == {
        "Authorization": REDACTED,
        "nested": {"clientSecret": REDACTED, "message": f"token={REDACTED}"},
    }
    schema = cast(dict[str, JsonValue], sanitized.payload["schema"])
    properties = cast(dict[str, JsonValue], schema["properties"])
    password_schema = cast(dict[str, JsonValue], properties["password"])
    assert password_schema["type"] == "string"
    assert password_schema["example"] == REDACTED
    assert sanitized.sample_included is True
    assert sanitized.redacted_paths


def test_ai_input_rejects_excessive_depth() -> None:
    nested: JsonValue = "leaf"
    for _ in range(40):
        nested = {"child": nested}
    with pytest.raises(AIInputError, match="深度"):
        sanitize_ai_input(schema_document=None, metadata={"nested": nested}, sample=None)


def test_ai_redaction_evaluation_set() -> None:
    evaluation_path = Path(__file__).parent / "fixtures" / "ai_redaction_evaluation.json"
    cases = cast(list[dict[str, JsonValue]], json.loads(evaluation_path.read_text()))
    assert len(cases) >= 3
    for case in cases:
        sanitized = sanitize_ai_input(
            schema_document=None,
            metadata=cast(dict[str, JsonValue], case["metadata"]),
            sample=case["sample"],
        )
        encoded = json.dumps(sanitized.payload, ensure_ascii=False, sort_keys=True)
        for forbidden in cast(list[str], case["forbidden"]):
            assert forbidden not in encoded, str(case["name"])
        for required in cast(list[str], case["required"]):
            assert required in encoded, str(case["name"])


@pytest.mark.asyncio
async def test_ai_job_requires_human_acceptance_before_creating_workflow(
    ai_environment: AIEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ai_environment.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers)
    created = await client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={
            "project_id": project_id,
            "job_type": "workflow_draft",
            "schema_document": {"openapi": "3.1.0", "paths": {}},
            "metadata": {"Authorization": "Bearer must-not-reach-provider"},
        },
    )
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["status"] == "pending"
    assert "sanitized_input" not in job
    assert ai_environment.queue.job_ids == [UUID(job["id"])]

    provider = FakeProvider(_workflow_suggestions())
    async with ai_environment.sessions() as session:
        completed = await AIJobRunner(session, provider).run(UUID(job["id"]))
    assert completed.status == "completed"
    assert provider.seen_input is not None
    assert "must-not-reach-provider" not in json.dumps(provider.seen_input)

    before_accept = await client.get(
        f"/api/v1/projects/{project_id}/workflows?page=1&page_size=100",
        headers=headers,
    )
    assert before_accept.status_code == 200
    assert before_accept.json()["total"] == 0

    suggestions = await client.get(f"/api/v1/ai/jobs/{job['id']}/suggestions", headers=headers)
    assert suggestions.status_code == 200
    suggestion = suggestions.json()[0]
    assert suggestion["review_status"] == "pending"

    original_commit = AsyncSession.commit
    commit_count = 0

    async def tracked_commit(session: AsyncSession) -> None:
        nonlocal commit_count
        commit_count += 1
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", tracked_commit)
    accepted = await client.post(
        f"/api/v1/ai/suggestions/{suggestion['id']}/accept",
        headers=headers,
        json={"note": "结构已人工确认"},
    )
    assert accepted.status_code == 200, accepted.text
    assert commit_count == 1
    reviewed = accepted.json()
    assert reviewed["review_status"] == "accepted"
    assert reviewed["accepted_resource_type"] == "workflow"
    assert reviewed["accepted_resource_id"]

    workflows = await client.get(
        f"/api/v1/projects/{project_id}/workflows?page=1&page_size=100",
        headers=headers,
    )
    assert workflows.status_code == 200
    assert workflows.json()["total"] == 1
    assert workflows.json()["items"][0]["current_version"] is None

    repeated = await client.post(
        f"/api/v1/ai/suggestions/{suggestion['id']}/accept",
        headers=headers,
        json={},
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "AI_SUGGESTION_ALREADY_REVIEWED"


@pytest.mark.asyncio
async def test_ai_status_job_listing_and_disabled_gate(
    ai_environment: AIEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ai_environment.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers, name="AI status project")

    status_response = await client.get(
        "/api/v1/ai/status", headers=headers, params={"project_id": project_id}
    )
    assert status_response.status_code == 200
    assert status_response.json() == {
        "enabled": True,
        "model": "flowtest-eval-model",
        "sample_sharing_enabled": False,
    }

    created = await _create_ai_job(client, headers, project_id)
    listed = await client.get(
        "/api/v1/ai/jobs",
        headers=headers,
        params={"project_id": project_id, "page": 1, "page_size": 10},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    fetched = await client.get(f"/api/v1/ai/jobs/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]
    missing = await client.get(f"/api/v1/ai/jobs/{uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "AI_JOB_NOT_FOUND"

    monkeypatch.setattr(settings, "feature_ai_enabled", False)
    disabled = await client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={
            "project_id": project_id,
            "job_type": "assertion_suggestions",
            "metadata": {"operation": "GET /health"},
        },
    )
    assert disabled.status_code == 503
    assert disabled.json()["error"]["code"] == "AI_DISABLED"


@pytest.mark.asyncio
async def test_ai_queue_and_provider_failures_are_durable_and_idempotent(
    ai_environment: AIEnvironment,
) -> None:
    client = ai_environment.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers, name="AI failure project")

    app.dependency_overrides[get_ai_job_dispatcher] = lambda: FailingAIQueue()
    queue_failure = await client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={
            "project_id": project_id,
            "job_type": "assertion_suggestions",
            "metadata": {"operation": "GET /queue"},
        },
    )
    assert queue_failure.status_code == 503
    assert queue_failure.json()["error"]["code"] == "AI_QUEUE_UNAVAILABLE"
    app.dependency_overrides[get_ai_job_dispatcher] = lambda: ai_environment.queue

    listed = await client.get("/api/v1/ai/jobs", headers=headers, params={"project_id": project_id})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["status"] == "failed"
    assert listed.json()["items"][0]["error_code"] == "AI_QUEUE_UNAVAILABLE"

    created = await _create_ai_job(client, headers, project_id)
    async with ai_environment.sessions() as session:
        failed = await AIJobRunner(session, ErrorProvider()).run(UUID(str(created["id"])))
        repeated = await AIJobRunner(session, FakeProvider(_assertion_suggestions())).run(
            UUID(str(created["id"]))
        )
        with pytest.raises(AppError, match="AI 任务不存在"):
            await AIJobRunner(session, FakeProvider(_assertion_suggestions())).run(uuid4())
    assert failed.status == "failed"
    assert failed.error_code == "AI_GATEWAY_UNAVAILABLE"
    assert repeated.status == "failed"


@pytest.mark.asyncio
async def test_ai_sample_requires_project_opt_in_and_is_redacted(
    ai_environment: AIEnvironment,
) -> None:
    client = ai_environment.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers, name="AI sample project")
    request = {
        "project_id": project_id,
        "job_type": "failure_analysis",
        "metadata": {"status": 500},
        "sample": {"password": "sample-secret", "error": "upstream failed"},
    }
    denied = await client.post("/api/v1/ai/jobs", headers=headers, json=request)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "AI_SAMPLE_SHARING_DISABLED"

    enabled = await client.put(
        f"/api/v1/ai/projects/{project_id}/settings",
        headers=headers,
        json={"sample_sharing_enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["sample_sharing_enabled"] is True

    accepted = await client.post("/api/v1/ai/jobs", headers=headers, json=request)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["sample_included"] is True
    provider = FakeProvider(
        {
            "suggestions": [
                {
                    "type": "failure_analysis",
                    "title": "上游错误",
                    "content": {"category": "upstream", "confidence": 0.8},
                }
            ]
        }
    )
    async with ai_environment.sessions() as session:
        await AIJobRunner(session, provider).run(UUID(accepted.json()["id"]))
    assert provider.seen_input is not None
    serialized = json.dumps(provider.seen_input)
    assert "sample-secret" not in serialized
    assert REDACTED in serialized


@pytest.mark.asyncio
async def test_only_project_owner_can_submit_opted_in_samples(
    ai_environment: AIEnvironment,
) -> None:
    client = ai_environment.client
    owner_headers = await _login_headers(client)
    project_id = await _create_project(client, owner_headers, name="AI owner-only sample project")
    enabled = await client.put(
        f"/api/v1/ai/projects/{project_id}/settings",
        headers=owner_headers,
        json={"sample_sharing_enabled": True},
    )
    assert enabled.status_code == 200
    editor = await _create_user(client, owner_headers, "ai-editor@example.com")
    membership = await client.put(
        f"/api/v1/projects/{project_id}/members/{editor['id']}",
        headers=owner_headers,
        json={"user_id": editor["id"], "role": "editor"},
    )
    assert membership.status_code == 200
    editor_headers = await _login_user_headers(
        client, "ai-editor@example.com", "initial-password-123!"
    )
    denied = await client.post(
        "/api/v1/ai/jobs",
        headers=editor_headers,
        json={
            "project_id": project_id,
            "job_type": "failure_analysis",
            "metadata": {"status": 500},
            "sample": {"error": "safe after redaction"},
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "AI_SAMPLE_OWNER_REQUIRED"


@pytest.mark.asyncio
async def test_ai_review_rejects_invalid_transitions_and_oversized_edits(
    ai_environment: AIEnvironment,
) -> None:
    client = ai_environment.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers, name="AI review constraints project")
    created = await _create_ai_job(client, headers, project_id, job_type="failure_analysis")
    provider = FakeProvider(_failure_suggestions())
    async with ai_environment.sessions() as session:
        await AIJobRunner(session, provider).run(UUID(str(created["id"])))

    suggestions = (
        await client.get(f"/api/v1/ai/jobs/{created['id']}/suggestions", headers=headers)
    ).json()
    rejected_edit = await client.post(
        f"/api/v1/ai/suggestions/{suggestions[0]['id']}/reject",
        headers=headers,
        json={"content": {"category": "edited"}},
    )
    assert rejected_edit.status_code == 422
    assert rejected_edit.json()["error"]["code"] == "AI_REJECT_EDIT_FORBIDDEN"
    rejected = await client.post(
        f"/api/v1/ai/suggestions/{suggestions[0]['id']}/reject",
        headers=headers,
        json={"note": "人工判断不准确"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "rejected"
    too_large = await client.post(
        f"/api/v1/ai/suggestions/{suggestions[1]['id']}/accept",
        headers=headers,
        json={"content": {"analysis": "x" * (256 * 1024)}},
    )
    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "AI_REVIEW_TOO_LARGE"
    missing = await client.post(
        f"/api/v1/ai/suggestions/{uuid4()}/reject", headers=headers, json={}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "AI_SUGGESTION_NOT_FOUND"

    pending = await _create_ai_job(client, headers, project_id)
    async with ai_environment.sessions() as session:
        pending_suggestion = AISuggestion(
            job_id=UUID(str(pending["id"])),
            position=0,
            suggestion_type="assertion",
            title="pending suggestion",
            content={"status_code": 200},
            review_status="pending",
        )
        session.add(pending_suggestion)
        await session.commit()
        await session.refresh(pending_suggestion)
        pending_suggestion_id = pending_suggestion.id
    premature = await client.post(
        f"/api/v1/ai/suggestions/{pending_suggestion_id}/accept", headers=headers, json={}
    )
    assert premature.status_code == 409
    assert premature.json()["error"]["code"] == "AI_JOB_NOT_COMPLETED"


@pytest.mark.asyncio
async def test_ai_accepts_valid_test_case_and_rejects_invalid_drafts(
    ai_environment: AIEnvironment,
) -> None:
    client = ai_environment.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers, name="AI asset draft project")
    environment = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={"name": "AI environment", "base_url": "https://example.com"},
    )
    assert environment.status_code == 201, environment.text
    workflow = await client.post(
        f"/api/v1/projects/{project_id}/workflows",
        headers=headers,
        json={
            "name": "AI source workflow",
            "definition": _workflow_definition(),
        },
    )
    assert workflow.status_code == 201, workflow.text
    created = await _create_ai_job(client, headers, project_id, job_type="schema_cases")
    provider = FakeProvider(_test_case_suggestions(workflow.json()["id"], environment.json()["id"]))
    async with ai_environment.sessions() as session:
        await AIJobRunner(session, provider).run(UUID(str(created["id"])))
    suggestions = (
        await client.get(f"/api/v1/ai/jobs/{created['id']}/suggestions", headers=headers)
    ).json()
    accepted = await client.post(
        f"/api/v1/ai/suggestions/{suggestions[0]['id']}/accept", headers=headers, json={}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted_resource_type"] == "test_case"
    cases = await client.get(
        f"/api/v1/projects/{project_id}/test-cases?page=1&page_size=20", headers=headers
    )
    assert cases.status_code == 200
    assert cases.json()["total"] == 1
    invalid_case = await client.post(
        f"/api/v1/ai/suggestions/{suggestions[1]['id']}/accept",
        headers=headers,
        json={"content": {"definition": {}, "tags": "not-a-list"}},
    )
    assert invalid_case.status_code == 422
    assert invalid_case.json()["error"]["code"] == "AI_TEST_CASE_DRAFT_INVALID"

    workflow_job = await _create_ai_job(client, headers, project_id, job_type="workflow_draft")
    async with ai_environment.sessions() as session:
        await AIJobRunner(session, FakeProvider(_workflow_suggestions())).run(
            UUID(str(workflow_job["id"]))
        )
    workflow_suggestion = (
        await client.get(f"/api/v1/ai/jobs/{workflow_job['id']}/suggestions", headers=headers)
    ).json()[0]
    invalid_workflow = await client.post(
        f"/api/v1/ai/suggestions/{workflow_suggestion['id']}/accept",
        headers=headers,
        json={"content": {"definition": {}, "folder_id": "invalid-uuid"}},
    )
    assert invalid_workflow.status_code == 422
    assert invalid_workflow.json()["error"]["code"] == "AI_WORKFLOW_DRAFT_INVALID"


@pytest.mark.asyncio
async def test_invalid_provider_output_fails_safely_without_leaking_details(
    ai_environment: AIEnvironment,
) -> None:
    client = ai_environment.client
    headers = await _login_headers(client)
    project_id = await _create_project(client, headers, name="Invalid output project")
    created = await client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={
            "project_id": project_id,
            "job_type": "assertion_suggestions",
            "metadata": {"operation": "GET /users"},
        },
    )
    assert created.status_code == 202
    provider = FakeProvider(
        {
            "suggestions": [
                {
                    "type": "workflow",
                    "title": "not allowed for this job",
                    "content": {"provider_secret": "do-not-store"},
                }
            ]
        }
    )
    async with ai_environment.sessions() as session:
        failed = await AIJobRunner(session, provider).run(UUID(created.json()["id"]))
    assert failed.status == "failed"
    assert failed.error_code == "AI_RESPONSE_INVALID"
    assert "do-not-store" not in (failed.error_message or "")
    suggestions = await client.get(
        f"/api/v1/ai/jobs/{created.json()['id']}/suggestions", headers=headers
    )
    assert suggestions.status_code == 200
    assert suggestions.json() == []


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_provider_uses_strict_schema_and_parses_usage() -> None:
    route = respx.post("https://gateway.example/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "suggestions": [
                                        {
                                            "type": "assertion",
                                            "title": "状态码断言",
                                            "content": {"status_code": 200},
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfiguration(
            base_url="https://gateway.example/v1",
            model="test-model",
            api_key="gateway-secret",
            timeout_seconds=5,
        )
    )
    result = await provider.generate(
        job_type="assertion_suggestions",
        sanitized_input={"metadata": {"operation": "GET /users"}, "schema": {}},
        output_schema={"type": "object"},
    )
    assert result.token_usage["total_tokens"] == 15
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer gateway-secret"
    body = json.loads(request.content)
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "gateway-secret" not in request.content.decode()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (Response(503), "AI_GATEWAY_REJECTED"),
        (Response(200, json={"choices": []}), "AI_RESPONSE_INVALID"),
        (
            Response(
                200,
                json={"choices": [{"message": {"content": "[]"}}]},
            ),
            "AI_RESPONSE_INVALID",
        ),
    ],
)
async def test_openai_compatible_provider_rejects_gateway_and_malformed_responses(
    response: Response,
    expected_code: str,
) -> None:
    respx.post("https://gateway.example/v1/chat/completions").mock(return_value=response)
    with pytest.raises(AIProviderError) as captured:
        await _openai_provider().generate(
            job_type="assertion_suggestions",
            sanitized_input={"metadata": {"operation": "GET /users"}},
            output_schema={"type": "object"},
        )
    assert captured.value.code == expected_code


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_provider_maps_network_errors() -> None:
    respx.post("https://gateway.example/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    with pytest.raises(AIProviderError) as captured:
        await _openai_provider().generate(
            job_type="assertion_suggestions",
            sanitized_input={"metadata": {"operation": "GET /users"}},
            output_schema={"type": "object"},
        )
    assert captured.value.code == "AI_GATEWAY_UNAVAILABLE"


@dataclass(slots=True)
class FakeProvider:
    payload: dict[str, JsonValue]
    seen_input: dict[str, JsonValue] | None = None

    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        assert job_type
        assert output_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        self.seen_input = sanitized_input
        return AIProviderResult(
            payload=self.payload,
            token_usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        )


class ErrorProvider:
    async def generate(
        self,
        *,
        job_type: str,
        sanitized_input: dict[str, JsonValue],
        output_schema: dict[str, JsonValue],
    ) -> AIProviderResult:
        raise AIProviderError("AI_GATEWAY_UNAVAILABLE", "AI 网关暂时不可用")


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _login_user_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    login = response.json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    if login["user"]["requires_password_change"]:
        changed = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={
                "current_password": password,
                "new_password": "changed-password-123!",
            },
        )
        assert changed.status_code == 204, changed.text
    return headers


async def _create_user(
    client: AsyncClient, headers: dict[str, str], email: str
) -> dict[str, JsonValue]:
    response = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": email,
            "display_name": "AI editor",
            "password": "initial-password-123!",
            "is_system_admin": False,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, JsonValue], response.json())


async def _create_project(
    client: AsyncClient, headers: dict[str, str], *, name: str = "AI project"
) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "description": "AI review tests"},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def _create_ai_job(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    job_type: str = "assertion_suggestions",
) -> dict[str, JsonValue]:
    response = await client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={
            "project_id": project_id,
            "job_type": job_type,
            "metadata": {"operation": "GET /users"},
        },
    )
    assert response.status_code == 202, response.text
    return cast(dict[str, JsonValue], response.json())


def _workflow_suggestions() -> dict[str, JsonValue]:
    return {
        "suggestions": [
            {
                "type": "workflow",
                "title": "AI 建议工作流",
                "content": {
                    "name": "AI 建议工作流",
                    "description": "人工接受后创建的草稿",
                    "definition": {
                        "schema_version": "1.0",
                        "nodes": [
                            {
                                "id": "start",
                                "type": "start",
                                "name": "开始",
                                "position": {"x": 0, "y": 0},
                                "config": {},
                            },
                            {
                                "id": "end",
                                "type": "end",
                                "name": "结束",
                                "position": {"x": 240, "y": 0},
                                "config": {},
                            },
                        ],
                        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
                    },
                },
            }
        ]
    }


def _workflow_definition() -> dict[str, JsonValue]:
    return {
        "schema_version": "1.0",
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "name": "开始",
                "position": {"x": 0, "y": 0},
                "config": {},
            },
            {
                "id": "end",
                "type": "end",
                "name": "结束",
                "position": {"x": 240, "y": 0},
                "config": {},
            },
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
    }


def _assertion_suggestions() -> dict[str, JsonValue]:
    return {
        "suggestions": [
            {
                "type": "assertion",
                "title": "状态码断言",
                "content": {"status_code": 200},
            }
        ]
    }


def _failure_suggestions() -> dict[str, JsonValue]:
    return {
        "suggestions": [
            {
                "type": "failure_analysis",
                "title": "上游错误",
                "content": {"category": "upstream", "confidence": 0.8},
            },
            {
                "type": "failure_analysis",
                "title": "网络抖动",
                "content": {"category": "network", "confidence": 0.6},
            },
        ]
    }


def _test_case_suggestions(workflow_id: str, environment_id: str) -> dict[str, JsonValue]:
    valid_content: dict[str, JsonValue] = {
        "name": "AI 建议测试用例",
        "description": "人工接受后创建",
        "tags": ["ai-reviewed"],
        "definition": {
            "workflow_id": workflow_id,
            "environment_id": environment_id,
            "runtime_variables": {},
            "runtime_headers": {},
        },
    }
    return {
        "suggestions": [
            {"type": "test_case", "title": "有效用例", "content": valid_content},
            {"type": "test_case", "title": "待编辑用例", "content": valid_content},
        ]
    }


def _openai_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        OpenAICompatibleConfiguration(
            base_url="https://gateway.example/v1",
            model="test-model",
            api_key="gateway-secret",
            timeout_seconds=5,
        )
    )
