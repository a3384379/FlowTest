import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_performance_dispatcher
from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.domain.performance import (
    LoadExecutor,
    PerformanceExecutionResult,
    PerformanceHttpStep,
    PerformanceScenarioDefinition,
    PerformanceThreshold,
    ThresholdOperator,
    metric_value,
    threshold_outcomes,
)
from app.engine.k6_compiler import K6ScenarioCompiler
from app.main import app
from app.models import Base
from app.models.access import User
from app.models.performance import PerformanceRun
from app.runner.k6 import K6ExecutionError, K6ProcessRunner
from app.services.performance import PerformanceRunCoordinator

ADMIN_EMAIL = "performance-admin@example.com"
ADMIN_PASSWORD = "performance-password-123!"


@dataclass(slots=True)
class RecordingPerformanceQueue:
    run_ids: list[UUID] = field(default_factory=list)

    def start_performance_run(self, run_id: UUID) -> None:
        self.run_ids.append(run_id)


@dataclass(slots=True)
class MemoryMetricsStore:
    objects: dict[str, bytes] = field(default_factory=dict)

    async def put(self, *, key: str, content: bytes, content_type: str) -> None:
        assert content_type == "application/x-ndjson"
        self.objects[key] = content


@dataclass(slots=True)
class FakePerformanceExecutor:
    results: list[PerformanceExecutionResult]
    hashes: list[str] = field(default_factory=list)

    async def run(self, scenario, *, timeout_seconds: int) -> PerformanceExecutionResult:
        assert timeout_seconds >= 61
        self.hashes.append(scenario.sha256)
        return self.results.pop(0)


@dataclass(slots=True)
class PerformanceEnvironment:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    queue: RecordingPerformanceQueue


@pytest.fixture
async def performance_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[PerformanceEnvironment]:
    monkeypatch.setattr(settings, "feature_performance_lab_enabled", True)
    monkeypatch.setattr(settings, "performance_max_vus", 100)
    monkeypatch.setattr(settings, "performance_max_duration_seconds", 1800)
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
                display_name="Performance administrator",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()

    queue = RecordingPerformanceQueue()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_performance_dispatcher] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield PerformanceEnvironment(client, sessions, queue)
    app.dependency_overrides.clear()
    await engine.dispose()


def test_declarative_scenario_compiles_fixed_k6_program_without_user_source() -> None:
    definition = _definition(step_name="quote-\"; throw new Error('blocked')")
    compiled = K6ScenarioCompiler().compile(definition)
    repeated = K6ScenarioCompiler().compile(definition)

    assert compiled.sha256 == repeated.sha256
    assert "export default function" in compiled.source
    assert "redirects: 0" in compiled.source
    assert "discardResponseBodies" in compiled.source
    assert '"executor":"constant-vus"' in compiled.source
    assert '"threshold":"p(95)<500"' in compiled.source
    encoded_name = json.dumps(definition.steps[0].name)
    assert encoded_name in compiled.source
    assert "eval(" not in compiled.source

    ramping = PerformanceScenarioDefinition.model_validate(
        {
            "executor": "ramping_vus",
            "steps": [
                {
                    **_step().model_dump(mode="json"),
                    "method": "POST",
                    "body": {"order_id": 7},
                }
            ],
            "thresholds": [
                {
                    **_threshold().model_dump(mode="json"),
                    "abort_on_fail": True,
                    "delay_abort_seconds": 5,
                }
            ],
            "start_vus": 0,
            "stages": [{"duration_seconds": 10, "target_vus": 12}],
            "graceful_stop_seconds": 2,
        }
    )
    ramp_source = K6ScenarioCompiler().compile(ramping).source
    assert '"executor":"ramping-vus"' in ramp_source
    assert '"startVUs":0' in ramp_source
    assert '"delayAbortEval":"5s"' in ramp_source
    assert "application/json" in ramp_source
    assert "order_id" in ramp_source

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PerformanceScenarioDefinition.model_validate(
            {**definition.model_dump(mode="json"), "script": "while (true) {}"}
        )


def test_load_shape_thresholds_and_summary_metrics_are_strict() -> None:
    with pytest.raises(ValidationError, match="constant_vus requires"):
        PerformanceScenarioDefinition(
            executor=LoadExecutor.CONSTANT_VUS,
            steps=(_step(),),
            thresholds=(_threshold(),),
        )
    with pytest.raises(ValidationError, match="ramping_vus requires"):
        PerformanceScenarioDefinition(
            executor=LoadExecutor.RAMPING_VUS,
            steps=(_step(),),
            thresholds=(_threshold(),),
            start_vus=0,
        )
    with pytest.raises(ValidationError, match="cannot declare"):
        PerformanceScenarioDefinition(
            executor=LoadExecutor.CONSTANT_VUS,
            steps=(_step(),),
            thresholds=(_threshold(),),
            vus=1,
            duration_seconds=1,
            start_vus=0,
        )
    with pytest.raises(ValidationError, match="must be unique"):
        PerformanceScenarioDefinition(
            executor=LoadExecutor.CONSTANT_VUS,
            steps=(_step(), _step()),
            thresholds=(_threshold(),),
            vus=1,
            duration_seconds=1,
        )
    with pytest.raises(ValidationError, match="abort delay"):
        PerformanceThreshold(
            metric="http_req_duration",
            aggregation="avg",
            operator=ThresholdOperator.LESS_THAN,
            value=500,
            delay_abort_seconds=2,
        )
    with pytest.raises(ValidationError, match="Sensitive HTTP headers"):
        PerformanceHttpStep(
            **{
                **_step().model_dump(mode="json"),
                "headers": {"Authorization": "Bearer hidden-token-value"},
            }
        )
    with pytest.raises(ValidationError, match="Sensitive URL query"):
        PerformanceHttpStep(
            **{**_step().model_dump(mode="json"), "url": "https://api.example.com?token=hidden"}
        )
    with pytest.raises(ValidationError, match="Sensitive request body"):
        PerformanceHttpStep(**{**_step().model_dump(mode="json"), "body": {"password": "hidden"}})

    summary = _summary(p95=123.4, passed=True)
    assert metric_value(summary, "http_req_duration", "p(95)") == 123.4
    assert metric_value(summary, "missing", "avg") is None
    assert threshold_outcomes(summary)[0].passed is True
    assert threshold_outcomes({}) == ()


@pytest.mark.asyncio
async def test_k6_process_runner_accepts_threshold_exit_and_rejects_missing_summary(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "fake-k6"
    executable.write_text(
        "#!/bin/sh\n"
        "printf '%s' '{\"metrics\":{}}' > flowtest-summary.json\n"
        "printf '%s\\n' '{\"type\":\"Point\"}' > raw-metrics.json\n"
        "printf '%s' 'threshold failed' >&2\n"
        "exit 99\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    result = await K6ProcessRunner(str(executable)).run(
        K6ScenarioCompiler().compile(_definition()), timeout_seconds=5
    )
    assert result.exit_code == 99
    assert result.raw_metrics == b'{"type":"Point"}\n'
    assert result.stderr == "threshold failed"

    missing = tmp_path / "missing-summary"
    missing.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    missing.chmod(0o700)
    with pytest.raises(K6ExecutionError, match="K6_EXECUTION_FAILED"):
        await K6ProcessRunner(str(missing)).run(
            K6ScenarioCompiler().compile(_definition()), timeout_seconds=5
        )

    invalid = tmp_path / "invalid-summary"
    invalid.write_text(
        "#!/bin/sh\nprintf '%s' '[]' > flowtest-summary.json\n",
        encoding="utf-8",
    )
    invalid.chmod(0o700)
    with pytest.raises(K6ExecutionError, match="K6_SUMMARY_INVALID"):
        await K6ProcessRunner(str(invalid)).run(
            K6ScenarioCompiler().compile(_definition()), timeout_seconds=5
        )

    malformed = tmp_path / "malformed-summary"
    malformed.write_text(
        "#!/bin/sh\nprintf '%s' '{' > flowtest-summary.json\n",
        encoding="utf-8",
    )
    malformed.chmod(0o700)
    with pytest.raises(K6ExecutionError, match="K6_SUMMARY_INVALID"):
        await K6ProcessRunner(str(malformed)).run(
            K6ScenarioCompiler().compile(_definition()), timeout_seconds=5
        )

    oversized = tmp_path / "oversized-metrics"
    oversized.write_text(
        "#!/bin/sh\n"
        "printf '%s' '{\"metrics\":{}}' > flowtest-summary.json\n"
        "printf '%s' 'large' > raw-metrics.json\n",
        encoding="utf-8",
    )
    oversized.chmod(0o700)
    with pytest.raises(K6ExecutionError, match="K6_METRICS_TOO_LARGE"):
        await K6ProcessRunner(str(oversized), raw_metrics_limit_bytes=2).run(
            K6ScenarioCompiler().compile(_definition()), timeout_seconds=5
        )

    with pytest.raises(K6ExecutionError, match="K6_UNAVAILABLE"):
        await K6ProcessRunner(str(tmp_path / "does-not-exist")).run(
            K6ScenarioCompiler().compile(_definition()), timeout_seconds=5
        )

    sleepy = tmp_path / "sleepy-k6"
    sleepy.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    sleepy.chmod(0o700)
    with pytest.raises(K6ExecutionError, match="K6_TIMEOUT"):
        await K6ProcessRunner(str(sleepy)).run(
            K6ScenarioCompiler().compile(_definition()), timeout_seconds=1
        )


@pytest.mark.asyncio
async def test_performance_api_version_run_baseline_artifact_and_gate(
    performance_environment: PerformanceEnvironment,
) -> None:
    context = performance_environment
    headers = await _login_headers(context.client)
    project_id = await _create_project(context.client, headers)
    await _create_gate(context.client, headers, project_id)
    created = await context.client.post(
        f"/api/v1/projects/{project_id}/performance-scenarios",
        headers=headers,
        json={
            "name": "订单接口性能",
            "description": "S25",
            "definition": _definition().model_dump(mode="json"),
        },
    )
    assert created.status_code == 201, created.text
    scenario = created.json()
    assert scenario["status"] == "draft"
    assert scenario["target_type"] == "rest"
    draft_run = await context.client.post(
        f"/api/v1/projects/{project_id}/performance-scenarios/{scenario['id']}/runs",
        headers=headers,
    )
    assert draft_run.status_code == 409

    published = await context.client.post(
        f"/api/v1/projects/{project_id}/performance-scenarios/{scenario['id']}/publish",
        headers=headers,
    )
    assert published.status_code == 200
    first_run_id = await _queue_run(context, headers, project_id, scenario["id"])

    executor = FakePerformanceExecutor(
        [
            PerformanceExecutionResult(
                exit_code=0,
                summary=_summary(p95=100, passed=True),
                raw_metrics=b'{"type":"Point","metric":"http_req_duration"}\n',
                stderr="",
            ),
            PerformanceExecutionResult(
                exit_code=0,
                summary=_summary(p95=140, passed=True),
                raw_metrics=b'{"type":"Point","metric":"http_req_duration"}\n',
                stderr="",
            ),
        ]
    )
    storage = MemoryMetricsStore()
    coordinator = PerformanceRunCoordinator(context.sessions, executor, storage)
    await coordinator.run(first_run_id)
    first = await _get_run(context.client, headers, project_id, first_run_id)
    assert first["status"] == "passed"
    assert first["summary"]["http_req_duration_p95_ms"] == 100
    assert first["raw_metrics_artifact_id"] is not None
    assert first["gate_evaluations"][0]["status"] == "passed"
    assert len(storage.objects) == 1

    second_run_id = await _queue_run(context, headers, project_id, scenario["id"])
    await coordinator.run(second_run_id)
    second = await _get_run(context.client, headers, project_id, second_run_id)
    assert second["status"] == "passed"
    assert second["baseline_run_id"] == str(first_run_id)
    assert second["summary"]["p95_regression_percent"] == 40
    assert second["gate_evaluations"][0]["status"] == "failed"
    assert "P95 回归" in second["gate_evaluations"][0]["violations"][0]

    version = await context.client.post(
        f"/api/v1/projects/{project_id}/performance-scenarios/{scenario['id']}/versions",
        headers=headers,
        json={"description": "v2", "definition": _definition(steps=2).model_dump(mode="json")},
    )
    assert version.status_code == 201
    assert version.json()["version"] == 2
    assert version.json()["target_type"] == "http_workflow"
    listed = await context.client.get(
        f"/api/v1/projects/{project_id}/performance-scenarios",
        headers=headers,
    )
    assert listed.json()["total"] == 2


@pytest.mark.asyncio
async def test_failed_threshold_and_snapshot_mismatch_have_stable_errors(
    performance_environment: PerformanceEnvironment,
) -> None:
    context = performance_environment
    headers = await _login_headers(context.client)
    project_id = await _create_project(context.client, headers)
    scenario_id = await _create_published_scenario(context.client, headers, project_id)
    failed_id = await _queue_run(context, headers, project_id, scenario_id)
    executor = FakePerformanceExecutor(
        [
            PerformanceExecutionResult(
                exit_code=99,
                summary=_summary(p95=900, passed=False),
                raw_metrics=b"metrics",
                stderr="threshold crossed",
            )
        ]
    )
    await PerformanceRunCoordinator(context.sessions, executor, MemoryMetricsStore()).run(failed_id)
    failed = await _get_run(context.client, headers, project_id, failed_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "PERFORMANCE_THRESHOLD_FAILED"

    mismatch_id = await _queue_run(context, headers, project_id, scenario_id)
    async with context.sessions() as session:
        run = await session.get(PerformanceRun, mismatch_id)
        assert run is not None
        run.compiled_sha256 = "0" * 64
        await session.commit()
    await PerformanceRunCoordinator(context.sessions, executor, MemoryMetricsStore()).run(
        mismatch_id
    )
    mismatch = await _get_run(context.client, headers, project_id, mismatch_id)
    assert mismatch["status"] == "failed"
    assert mismatch["error_code"] == "PERFORMANCE_SNAPSHOT_MISMATCH"


def _definition(*, steps: int = 1, step_name: str = "订单查询") -> PerformanceScenarioDefinition:
    return PerformanceScenarioDefinition(
        executor=LoadExecutor.CONSTANT_VUS,
        steps=tuple(
            _step(name=step_name if index == 0 else f"step-{index}") for index in range(steps)
        ),
        thresholds=(_threshold(),),
        vus=2,
        duration_seconds=1,
        graceful_stop_seconds=1,
    )


def _step(name: str = "订单查询") -> PerformanceHttpStep:
    return PerformanceHttpStep(
        name=name,
        method="GET",
        url="https://api.example.com/orders/1",
        headers={"Accept": "application/json"},
        expected_statuses=(200,),
    )


def _threshold() -> PerformanceThreshold:
    return PerformanceThreshold(
        metric="http_req_duration",
        aggregation="p(95)",
        operator=ThresholdOperator.LESS_THAN,
        value=500,
    )


def _summary(*, p95: float, passed: bool) -> dict[str, object]:
    return {
        "metrics": {
            "http_req_duration": {
                "values": {"p(95)": p95, "avg": p95 - 10},
                "thresholds": {"p(95)<500": {"ok": passed}},
            },
            "http_reqs": {"values": {"rate": 20.0, "count": 20}},
            "http_req_failed": {"values": {"rate": 0.0}},
        }
    }


async def _login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Performance project", "description": "S25"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_gate(client: AsyncClient, headers: dict[str, str], project_id: str) -> None:
    response = await client.post(
        f"/api/v1/projects/{project_id}/quality-gates",
        headers=headers,
        json={
            "name": "Performance Gate",
            "min_pass_rate": 0,
            "max_failed": 100,
            "max_flaky": 100,
            "max_duration_regression_percent": 20,
            "require_no_breaking_changes": False,
        },
    )
    assert response.status_code == 201, response.text


async def _create_published_scenario(
    client: AsyncClient, headers: dict[str, str], project_id: str
) -> str:
    response = await client.post(
        f"/api/v1/projects/{project_id}/performance-scenarios",
        headers=headers,
        json={"name": "Failure scenario", "definition": _definition().model_dump(mode="json")},
    )
    assert response.status_code == 201, response.text
    scenario_id = str(response.json()["id"])
    published = await client.post(
        f"/api/v1/projects/{project_id}/performance-scenarios/{scenario_id}/publish",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    return scenario_id


async def _queue_run(
    context: PerformanceEnvironment,
    headers: dict[str, str],
    project_id: str,
    scenario_id: str,
) -> UUID:
    response = await context.client.post(
        f"/api/v1/projects/{project_id}/performance-scenarios/{scenario_id}/runs",
        headers=headers,
    )
    assert response.status_code == 202, response.text
    run_id = UUID(response.json()["id"])
    assert context.queue.run_ids[-1] == run_id
    return run_id


async def _get_run(
    client: AsyncClient, headers: dict[str, str], project_id: str, run_id: UUID
) -> dict[str, object]:
    response = await client.get(
        f"/api/v1/projects/{project_id}/performance-runs/{run_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()
