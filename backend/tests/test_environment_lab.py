import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.runner.environment as environment_runner
from app.api.dependencies import get_environment_dispatcher
from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.domain.environment_lab import (
    EnvironmentEndpoint,
    EnvironmentRuntimeError,
    EnvironmentSeedDefinition,
    EnvironmentSeedEvidence,
    EnvironmentTemplateManifest,
    ProvisionedEnvironment,
)
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.environment_lab import EnvironmentInstance, EnvironmentTemplateVersion
from app.runner.environment import ControlledDockerEnvironmentRuntime
from app.services.environment_lab import (
    EnvironmentReconciliationService,
    EnvironmentRunCoordinator,
    EnvironmentTemplateSigner,
)
from app.tasking.dispatch import EnvironmentTaskDispatcher

ADMIN_EMAIL = "environment-admin@example.com"
ADMIN_PASSWORD = "environment-password-123!"
USER_EMAIL = "environment-user@example.com"
USER_PASSWORD = "environment-user-password-123!"
FIXTURE_IMAGE = (
    "nginxinc/nginx-unprivileged:1.31.3-alpine3.24@sha256:"
    "334d92979f15aaecd5dd50af5105e1230e2bb70765d45b1e2f964e7c5eda81c3"
)


@dataclass(slots=True)
class RecordingEnvironmentQueue:
    provision_ids: list[UUID] = field(default_factory=list)
    cleanup_ids: list[UUID] = field(default_factory=list)
    reject_provision: bool = False

    def start_environment_provision(self, instance_id: UUID) -> None:
        if self.reject_provision:
            raise RuntimeError("queue unavailable")
        self.provision_ids.append(instance_id)

    def start_environment_cleanup(self, instance_id: UUID) -> None:
        self.cleanup_ids.append(instance_id)


@dataclass(slots=True)
class FakeEnvironmentRuntime:
    provision_error: EnvironmentRuntimeError | None = None
    cleanup_error: RuntimeError | None = None
    wait_forever: bool = False
    provisioned: list[UUID] = field(default_factory=list)
    cleaned: list[UUID] = field(default_factory=list)
    seeded: list[str] = field(default_factory=list)

    async def provision(
        self, instance_id: UUID, manifest: EnvironmentTemplateManifest
    ) -> ProvisionedEnvironment:
        self.provisioned.append(instance_id)
        if self.wait_forever:
            await asyncio.sleep(60)
        if self.provision_error is not None:
            raise self.provision_error
        return ProvisionedEnvironment(
            runtime_name=f"flowtest-env-{instance_id.hex}",
            endpoints=(
                EnvironmentEndpoint(
                    service=manifest.services[0].name,
                    url="http://environment-docker:49152",
                    internal_port=manifest.services[0].internal_port,
                ),
            ),
            evidence={"engine": "fake"},
        )

    async def apply_seeds(
        self,
        provisioned: ProvisionedEnvironment,
        seeds: tuple[EnvironmentSeedDefinition, ...],
    ) -> tuple[EnvironmentSeedEvidence, ...]:
        self.seeded.append(provisioned.runtime_name)
        return tuple(
            EnvironmentSeedEvidence(
                profile=seed.profile,
                service=seed.service,
                path=seed.path,
                status_code=200,
            )
            for seed in seeds
        )

    async def cleanup(self, instance_id: UUID) -> None:
        self.cleaned.append(instance_id)
        if self.cleanup_error is not None:
            raise self.cleanup_error


@dataclass(slots=True)
class EnvironmentTestContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    queue: RecordingEnvironmentQueue


@pytest.fixture
async def environment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[EnvironmentTestContext]:
    monkeypatch.setattr(settings, "feature_environment_lab_enabled", True)
    monkeypatch.setattr(settings, "environment_image_allowlist", [FIXTURE_IMAGE])
    monkeypatch.setattr(settings, "environment_max_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "environment_provision_timeout_seconds", 30)
    monkeypatch.setattr(settings, "environment_cleanup_timeout_seconds", 10)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all(
            [
                User(
                    email=ADMIN_EMAIL,
                    display_name="Environment administrator",
                    password_hash=password_service.hash(ADMIN_PASSWORD),
                    is_active=True,
                    is_system_admin=True,
                    requires_password_change=False,
                ),
                User(
                    email=USER_EMAIL,
                    display_name="Environment user",
                    password_hash=password_service.hash(USER_PASSWORD),
                    is_active=True,
                    is_system_admin=False,
                    requires_password_change=False,
                ),
            ]
        )
        await session.commit()

    queue = RecordingEnvironmentQueue()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_environment_dispatcher] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield EnvironmentTestContext(client=client, sessions=sessions, queue=queue)
    app.dependency_overrides.clear()
    await engine.dispose()


def test_environment_manifest_is_canonical_and_rejects_unsafe_contracts() -> None:
    manifest = _manifest()
    assert manifest.sha256 == _manifest().sha256
    assert manifest.images == frozenset({FIXTURE_IMAGE})
    assert "script" not in manifest.canonical_json

    invalid_payloads = [
        _manifest_payload(environment=[{"name": "API_TOKEN", "value": "hidden"}]),
        _manifest_payload(read_only_root_filesystem=False),
        _manifest_payload(depends_on=["web"]),
        _manifest_payload(depends_on=["missing"]),
        {**_manifest_payload(), "script": "docker compose up"},
        {**_manifest_payload(), "default_ttl_seconds": 600, "maximum_ttl_seconds": 60},
        {
            **_manifest_payload(),
            "seeds": [{"profile": "http_get_v1", "service": "missing", "path": "/"}],
        },
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            EnvironmentTemplateManifest.model_validate(payload)

    cyclic = _manifest_payload()
    cyclic_services = cast(list[dict[str, object]], cyclic["services"])
    cyclic["services"] = [
        {**cyclic_services[0], "name": "web", "depends_on": ["api"]},
        {**cyclic_services[0], "name": "api", "depends_on": ["web"]},
    ]
    with pytest.raises(ValidationError, match="cycle"):
        EnvironmentTemplateManifest.model_validate(cyclic)

    with pytest.raises(ValidationError, match="require a path"):
        _manifest(health_check={"kind": "http"})
    with pytest.raises(ValidationError, match="cannot declare a path"):
        _manifest(health_check={"kind": "tcp", "path": "/"})

    signer = EnvironmentTemplateSigner("signing-key")
    signature = signer.sign(template_key="fixture.web", version=1, manifest_sha256=manifest.sha256)
    assert signer.verify(
        template_key="fixture.web",
        version=1,
        manifest_sha256=manifest.sha256,
        signature=signature,
    )
    assert not signer.verify(
        template_key="fixture.web",
        version=2,
        manifest_sha256=manifest.sha256,
        signature=signature,
    )


@pytest.mark.asyncio
async def test_environment_api_admin_version_idempotency_lifecycle(
    environment_context: EnvironmentTestContext,
) -> None:
    context = environment_context
    admin_headers = await _login_headers(context.client, ADMIN_EMAIL, ADMIN_PASSWORD)
    user_headers = await _login_headers(context.client, USER_EMAIL, USER_PASSWORD)
    project_id = await _create_project(context.client, admin_headers)

    forbidden = await context.client.post(
        "/api/v1/environment-templates",
        headers=user_headers,
        json=_template_payload(),
    )
    assert forbidden.status_code == 403

    rejected = await context.client.post(
        "/api/v1/environment-templates",
        headers=admin_headers,
        json=_template_payload(image=_other_image()),
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "ENVIRONMENT_IMAGE_NOT_ALLOWED"

    created = await context.client.post(
        "/api/v1/environment-templates",
        headers=admin_headers,
        json=_template_payload(),
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["version"] == 1
    assert template["signature_algorithm"] == "hmac-sha256-v1"
    assert len(template["signature"]) == 64

    duplicate = await context.client.post(
        "/api/v1/environment-templates",
        headers=admin_headers,
        json=_template_payload(),
    )
    assert duplicate.status_code == 409

    listed = await context.client.get("/api/v1/environment-templates", headers=user_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    missing_key = await context.client.post(
        f"/api/v1/projects/{project_id}/environment-instances",
        headers=admin_headers,
        json={"template_version_id": template["id"], "ttl_seconds": 120},
    )
    assert missing_key.status_code == 422

    too_long = await context.client.post(
        f"/api/v1/projects/{project_id}/environment-instances",
        headers={**admin_headers, "Idempotency-Key": "environment-too-long"},
        json={"template_version_id": template["id"], "ttl_seconds": 3601},
    )
    assert too_long.status_code == 422

    provisioned = await context.client.post(
        f"/api/v1/projects/{project_id}/environment-instances",
        headers={**admin_headers, "Idempotency-Key": "environment-first"},
        json={"template_version_id": template["id"], "ttl_seconds": 120},
    )
    assert provisioned.status_code == 202, provisioned.text
    instance_id = UUID(provisioned.json()["id"])
    assert context.queue.provision_ids == [instance_id]
    repeated = await context.client.post(
        f"/api/v1/projects/{project_id}/environment-instances",
        headers={**admin_headers, "Idempotency-Key": "environment-first"},
        json={"template_version_id": template["id"], "ttl_seconds": 120},
    )
    assert repeated.status_code == 202
    assert repeated.json()["id"] == str(instance_id)
    assert context.queue.provision_ids == [instance_id]

    runtime = FakeEnvironmentRuntime()
    await EnvironmentRunCoordinator(context.sessions, runtime).provision(instance_id)
    ready = await context.client.get(
        f"/api/v1/projects/{project_id}/environment-instances/{instance_id}",
        headers=admin_headers,
    )
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["endpoints"][0]["service"] == "web"
    assert ready.json()["seed_evidence"][0]["status_code"] == 200
    assert runtime.cleaned == [instance_id]

    page = await context.client.get(
        f"/api/v1/projects/{project_id}/environment-instances",
        headers=admin_headers,
    )
    assert page.status_code == 200
    assert page.json()["total"] == 1
    missing = await context.client.get(
        f"/api/v1/projects/{project_id}/environment-instances/{UUID(int=0)}",
        headers=admin_headers,
    )
    assert missing.status_code == 404

    cleanup = await context.client.post(
        f"/api/v1/projects/{project_id}/environment-instances/{instance_id}/cleanup",
        headers=admin_headers,
    )
    assert cleanup.status_code == 202
    assert cleanup.json()["status"] == "cancelled"
    assert context.queue.cleanup_ids == [instance_id]
    await EnvironmentRunCoordinator(context.sessions, runtime).cleanup(instance_id)
    await EnvironmentRunCoordinator(context.sessions, runtime).cleanup(instance_id)
    cleaned = await context.client.get(
        f"/api/v1/projects/{project_id}/environment-instances/{instance_id}",
        headers=admin_headers,
    )
    assert cleaned.json()["cleanup_status"] == "completed"
    assert runtime.cleaned.count(instance_id) == 2

    versioned = await context.client.post(
        f"/api/v1/environment-templates/{template['template_id']}/versions",
        headers=admin_headers,
        json={"manifest": _manifest_payload(default_ttl_seconds=300)},
    )
    assert versioned.status_code == 201
    assert versioned.json()["version"] == 2
    disabled = await context.client.post(
        f"/api/v1/environment-templates/{template['template_id']}/disable",
        headers=admin_headers,
    )
    assert disabled.status_code == 204
    disabled_again = await context.client.post(
        f"/api/v1/environment-templates/{template['template_id']}/disable",
        headers=admin_headers,
    )
    assert disabled_again.status_code == 204
    user_list = await context.client.get("/api/v1/environment-templates", headers=user_headers)
    assert user_list.json()["total"] == 0
    admin_list = await context.client.get("/api/v1/environment-templates", headers=admin_headers)
    assert admin_list.json()["total"] == 2
    blocked_version = await context.client.post(
        f"/api/v1/environment-templates/{template['template_id']}/versions",
        headers=admin_headers,
        json={"manifest": _manifest_payload()},
    )
    assert blocked_version.status_code == 409


@pytest.mark.asyncio
async def test_environment_signature_queue_and_runner_failures_are_stable(
    environment_context: EnvironmentTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = environment_context
    headers = await _login_headers(context.client, ADMIN_EMAIL, ADMIN_PASSWORD)
    project_id = await _create_project(context.client, headers)
    template = await _create_template(context.client, headers)

    context.queue.reject_provision = True
    unavailable = await _queue_instance(
        context.client,
        headers,
        project_id,
        template["id"],
        "environment-unavailable",
    )
    assert unavailable.status_code == 503
    context.queue.reject_provision = False

    tampered_id = await _queue_instance_id(
        context,
        headers,
        project_id,
        template["id"],
        "environment-tampered",
    )
    async with context.sessions() as session:
        tampered = await session.get(EnvironmentInstance, tampered_id)
        assert tampered is not None
        tampered.signature = "0" * 64
        await session.commit()
    tamper_runtime = FakeEnvironmentRuntime()
    await EnvironmentRunCoordinator(context.sessions, tamper_runtime).provision(tampered_id)
    tampered_response = await _get_instance(context.client, headers, project_id, tampered_id)
    assert tampered_response["status"] == "failed"
    assert tampered_response["error_code"] == "ENVIRONMENT_TEMPLATE_SIGNATURE_INVALID"
    assert tamper_runtime.provisioned == []
    assert tamper_runtime.cleaned == [tampered_id]

    failed_id = await _queue_instance_id(
        context,
        headers,
        project_id,
        template["id"],
        "environment-runtime-error",
    )
    failed_runtime = FakeEnvironmentRuntime(
        provision_error=EnvironmentRuntimeError(
            "ENVIRONMENT_RUNTIME_FAILED", "受控环境 Runner 执行失败"
        )
    )
    await EnvironmentRunCoordinator(context.sessions, failed_runtime).provision(failed_id)
    failed = await _get_instance(context.client, headers, project_id, failed_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "ENVIRONMENT_RUNTIME_FAILED"
    assert failed["cleanup_status"] == "completed"

    timeout_id = await _queue_instance_id(
        context,
        headers,
        project_id,
        template["id"],
        "environment-timeout",
    )
    monkeypatch.setattr(settings, "environment_provision_timeout_seconds", 0)
    await EnvironmentRunCoordinator(
        context.sessions, FakeEnvironmentRuntime(wait_forever=True)
    ).provision(timeout_id)
    timed_out = await _get_instance(context.client, headers, project_id, timeout_id)
    assert timed_out["error_code"] == "ENVIRONMENT_PROVISION_TIMEOUT"
    monkeypatch.setattr(settings, "environment_provision_timeout_seconds", 30)

    cleanup_id = await _queue_instance_id(
        context,
        headers,
        project_id,
        template["id"],
        "environment-cleanup-failure",
    )
    cancelled = await context.client.post(
        f"/api/v1/projects/{project_id}/environment-instances/{cleanup_id}/cleanup",
        headers=headers,
    )
    assert cancelled.status_code == 202
    cleanup_runtime = FakeEnvironmentRuntime(cleanup_error=RuntimeError("cleanup failed"))
    await EnvironmentRunCoordinator(context.sessions, cleanup_runtime).cleanup(cleanup_id)
    cleanup_failed = await _get_instance(context.client, headers, project_id, cleanup_id)
    assert cleanup_failed["cleanup_status"] == "failed"
    assert cleanup_failed["cleanup_error_code"] == "ENVIRONMENT_CLEANUP_FAILED"

    async with context.sessions() as session:
        version = await session.get(EnvironmentTemplateVersion, UUID(str(template["id"])))
        assert version is not None
        version.signature = "f" * 64
        await session.commit()
    invalid_list = await context.client.get("/api/v1/environment-templates", headers=headers)
    assert invalid_list.status_code == 409


@pytest.mark.asyncio
async def test_environment_redelivery_reconciliation_and_disabled_flag(
    environment_context: EnvironmentTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = environment_context
    headers = await _login_headers(context.client, ADMIN_EMAIL, ADMIN_PASSWORD)
    project_id = await _create_project(context.client, headers)
    template = await _create_template(context.client, headers)
    instance_id = await _queue_instance_id(
        context,
        headers,
        project_id,
        template["id"],
        "environment-redelivery",
    )
    async with context.sessions() as session:
        instance = await session.get(EnvironmentInstance, instance_id)
        assert instance is not None
        instance.status = "provisioning"
        initial_fencing = instance.fencing_token
        await session.commit()
    runtime = FakeEnvironmentRuntime()
    await EnvironmentRunCoordinator(context.sessions, runtime).provision(instance_id)
    recovered = await _get_instance(context.client, headers, project_id, instance_id)
    assert recovered["status"] == "ready"
    assert recovered["fencing_token"] == initial_fencing + 1
    assert runtime.cleaned == [instance_id]

    async with context.sessions() as session:
        instance = await session.get(EnvironmentInstance, instance_id)
        assert instance is not None
        instance.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    reconcile_queue = RecordingEnvironmentQueue()
    async with context.sessions() as session:
        count = await EnvironmentReconciliationService(session).dispatch_due(reconcile_queue)
    assert count == 1
    assert reconcile_queue.cleanup_ids == [instance_id]
    await EnvironmentRunCoordinator(context.sessions, runtime).cleanup(instance_id)
    expired = await _get_instance(context.client, headers, project_id, instance_id)
    assert expired["status"] == "expired"
    assert expired["cleanup_status"] == "completed"

    monkeypatch.setattr(settings, "feature_environment_lab_enabled", False)
    disabled = await context.client.get("/api/v1/environment-templates", headers=headers)
    assert disabled.status_code == 409


@pytest.mark.asyncio
async def test_controlled_docker_runtime_uses_fixed_arguments_and_cleans_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        requests.append(await reader.read(4096))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    calls: list[tuple[str, ...]] = []

    async def fake_docker(*arguments: str, timeout_seconds: int, check: bool = True) -> str:
        del timeout_seconds, check
        calls.append(arguments)
        if arguments[:1] == ("port",):
            return f"0.0.0.0:{port}"
        if "--quiet" in arguments:
            return "resource-id\n"
        return ""

    monkeypatch.setattr(environment_runner, "_run_docker", fake_docker)
    monkeypatch.setattr(settings, "environment_runtime_host", "127.0.0.1")
    instance_id = UUID("76b7d901-0d99-4bd6-8c40-d35e8d83a5d1")
    runtime = ControlledDockerEnvironmentRuntime()
    try:
        provisioned = await runtime.provision(instance_id, _manifest())
        evidence = await runtime.apply_seeds(provisioned, _manifest().seeds)
        await runtime.cleanup(instance_id)
    finally:
        server.close()
        await server.wait_closed()

    assert provisioned.runtime_name == f"flowtest-env-{instance_id.hex}"
    assert provisioned.endpoints[0].url == f"http://127.0.0.1:{port}"
    assert evidence[0].status_code == 200
    assert len(requests) >= 2
    run_call = next(call for call in calls if call[:1] == ("run",))
    assert "--read-only" in run_call
    assert run_call[run_call.index("--security-opt") + 1] == "no-new-privileges"
    assert run_call[run_call.index("--cap-drop") + 1] == "ALL"
    assert "--volume" not in run_call
    assert "--privileged" not in run_call
    assert not any(argument.startswith("/") for argument in run_call[-1:])
    assert any(call[:2] == ("network", "create") for call in calls)
    assert any(call[:2] == ("image", "pull") for call in calls)
    assert not any(call[:1] == ("compose",) for call in calls)
    assert any(call[:1] == ("ps",) for call in calls)
    assert any(call[:2] == ("network", "rm") for call in calls)
    assert any(call[:2] == ("volume", "rm") for call in calls)

    with pytest.raises(EnvironmentRuntimeError) as missing:
        environment_runner._published_port("missing")
    assert missing.value.code == "ENVIRONMENT_ENDPOINT_MISSING"
    with pytest.raises(EnvironmentRuntimeError) as invalid:
        environment_runner._published_port("0.0.0.0:70000")
    assert invalid.value.code == "ENVIRONMENT_ENDPOINT_INVALID"


@pytest.mark.asyncio
async def test_fixed_docker_command_maps_failure_and_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "docker"
    executable.write_text("#!/bin/sh\nprintf '%s' 'ok'\n", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")
    assert await environment_runner._run_docker("version", timeout_seconds=2) == "ok"

    executable.write_text("#!/bin/sh\nprintf '%s' 'hidden' >&2\nexit 1\n", encoding="utf-8")
    with pytest.raises(EnvironmentRuntimeError) as failed:
        await environment_runner._run_docker("version", timeout_seconds=2)
    assert failed.value.code == "ENVIRONMENT_RUNTIME_FAILED"
    assert await environment_runner._run_docker("version", timeout_seconds=2, check=False) == ""

    executable.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    with pytest.raises(EnvironmentRuntimeError) as timed_out:
        await environment_runner._run_docker("version", timeout_seconds=1)
    assert timed_out.value.code == "ENVIRONMENT_RUNTIME_TIMEOUT"


def test_environment_dispatcher_protocol_is_explicit() -> None:
    assert callable(EnvironmentTaskDispatcher.start_environment_cleanup)
    assert callable(EnvironmentTaskDispatcher.start_environment_provision)


def _manifest(*, health_check: dict[str, object] | None = None) -> EnvironmentTemplateManifest:
    return EnvironmentTemplateManifest.model_validate(_manifest_payload(health_check=health_check))


def _manifest_payload(
    *,
    image: str = FIXTURE_IMAGE,
    environment: list[dict[str, str]] | None = None,
    depends_on: list[str] | None = None,
    health_check: dict[str, object] | None = None,
    read_only_root_filesystem: bool = True,
    default_ttl_seconds: int = 120,
) -> dict[str, object]:
    return {
        "services": [
            {
                "name": "web",
                "image": image,
                "internal_port": 8080,
                "environment": environment or [{"name": "NGINX_PORT", "value": "8080"}],
                "depends_on": depends_on or [],
                "health_check": health_check
                or {
                    "kind": "http",
                    "path": "/",
                    "expected_status": 200,
                    "interval_seconds": 0.1,
                    "timeout_seconds": 1,
                    "maximum_attempts": 2,
                },
                "cpu_millicores": 250,
                "memory_megabytes": 128,
                "pids_limit": 64,
                "user_id": 101,
                "group_id": 101,
                "read_only_root_filesystem": read_only_root_filesystem,
                "drop_all_capabilities": True,
                "no_new_privileges": True,
            }
        ],
        "seeds": [{"profile": "http_get_v1", "service": "web", "path": "/"}],
        "default_ttl_seconds": default_ttl_seconds,
        "maximum_ttl_seconds": 3600,
    }


def _template_payload(*, image: str = FIXTURE_IMAGE) -> dict[str, object]:
    return {
        "template_key": "fixture.web",
        "display_name": "受控 Web 环境",
        "description": "S26 fixture",
        "manifest": _manifest_payload(image=image),
    }


def _other_image() -> str:
    return "example.invalid/platform/rejected@sha256:" + "a" * 64


async def _login_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Environment project", "description": "S26"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_template(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    response = await client.post(
        "/api/v1/environment-templates",
        headers=headers,
        json=_template_payload(),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


async def _queue_instance(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    template_version_id: object,
    idempotency_key: str,
) -> Response:
    return await client.post(
        f"/api/v1/projects/{project_id}/environment-instances",
        headers={**headers, "Idempotency-Key": idempotency_key},
        json={"template_version_id": template_version_id, "ttl_seconds": 120},
    )


async def _queue_instance_id(
    context: EnvironmentTestContext,
    headers: dict[str, str],
    project_id: str,
    template_version_id: object,
    idempotency_key: str,
) -> UUID:
    response = await _queue_instance(
        context.client,
        headers,
        project_id,
        template_version_id,
        idempotency_key,
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


async def _get_instance(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    instance_id: UUID,
) -> dict[str, object]:
    response = await client.get(
        f"/api/v1/projects/{project_id}/environment-instances/{instance_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())
