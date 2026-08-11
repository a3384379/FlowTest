from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_session
from app.core.security import password_service
from app.domain.capabilities import (
    CapabilityCategory,
    CapabilityManifest,
    NetworkAccess,
    NetworkPolicy,
    PluginManifest,
    RunnerType,
)
from app.domain.network import OutboundNetworkPolicy
from app.engine.capabilities import (
    CapabilityRegistry,
    LegacyNodeAdapter,
    builtin_capability_registry,
    capability_snapshot,
)
from app.engine.contracts import NodeType, WorkflowDefinition, WorkflowNode
from app.engine.events import ExecutionEvent, ExecutionEventType
from app.engine.results import NodeAssertion, NodeMetric, NodeResult, normalize_node_result
from app.engine.scheduler import ExecutionContext, WorkflowScheduler
from app.main import app
from app.models import Base
from app.models.access import User
from app.runner.contracts import (
    RunnerIdentity,
    RunnerLease,
    RunnerProgress,
    RunnerTaskEnvelope,
)
from app.services.workflow_runtime import WorkflowNodeExecutor

ADMIN_EMAIL = "capability-admin@example.com"
ADMIN_PASSWORD = "capability-admin-password!"
USER_EMAIL = "capability-user@example.com"
USER_PASSWORD = "capability-user-password!"


@pytest.fixture
async def capability_client() -> AsyncIterator[AsyncClient]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add_all(
            [
                _user(ADMIN_EMAIL, ADMIN_PASSWORD, system_admin=True),
                _user(USER_EMAIL, USER_PASSWORD, system_admin=False),
            ]
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await test_engine.dispose()


def test_capability_manifest_validates_schema_network_and_hash() -> None:
    manifest = _manifest()
    restored = CapabilityManifest.model_validate_json(manifest.model_dump_json())

    assert restored.schema_hash == manifest.schema_hash
    assert len(manifest.schema_hash) == 64
    assert manifest.network_policy.access is NetworkAccess.DENIED

    with pytest.raises(ValidationError, match="Invalid input JSON Schema"):
        _manifest(input_schema={"type": "definitely-not-a-json-schema-type"})
    with pytest.raises(ValidationError, match="Denied network policy"):
        NetworkPolicy(access="denied", protocols=("https",))
    with pytest.raises(ValidationError, match="must declare protocols"):
        NetworkPolicy(access="project_allowlist")
    with pytest.raises(ValidationError, match="must be unique"):
        NetworkPolicy(access="project_allowlist", protocols=("HTTPS", "https"))


def test_plugin_manifest_enforces_digest_ownership_and_sandbox() -> None:
    digest = f"sha256:{'a' * 64}"
    capability = _manifest(plugin_id="vendor.echo", plugin_digest=digest)
    plugin = PluginManifest(
        id="vendor.echo",
        version="1.0.0",
        display_name="Echo",
        oci_repository="ghcr.io/flowtest/echo",
        oci_digest=digest,
        signature_identity="https://github.com/flowtest/plugins/.github/workflows/release.yml",
        capabilities=(capability,),
    )

    assert plugin.capabilities[0].plugin_digest == digest
    with pytest.raises(ValidationError, match="explicit OCI registry"):
        plugin.model_copy(update={"oci_repository": "echo"}).model_dump()
        PluginManifest.model_validate({**plugin.model_dump(), "oci_repository": "echo"})
    with pytest.raises(ValidationError, match="pin the owning plugin"):
        PluginManifest.model_validate(
            {
                **plugin.model_dump(),
                "capabilities": [_manifest().model_dump()],
            }
        )
    with pytest.raises(ValidationError, match="cannot be disabled"):
        PluginManifest.model_validate({**plugin.model_dump(), "read_only_root_filesystem": False})


def test_registry_and_legacy_adapter_pin_every_v2_node() -> None:
    manifests = builtin_capability_registry.list()
    assert len(manifests) == 12
    assert builtin_capability_registry.require("http.request", "2.0.0").runner_type == "general"
    with pytest.raises(ValueError, match="Unknown capability"):
        builtin_capability_registry.require("grpc.unary", "3.0.0")
    with pytest.raises(ValueError, match="Duplicate capability"):
        CapabilityRegistry((manifests[0], manifests[0]))

    adapter = LegacyNodeAdapter()
    for node_type in NodeType:
        if node_type is NodeType.CAPABILITY:
            continue
        invocation = adapter.compile(_node("legacy", node_type, {}))
        assert invocation.source == "legacy"
        assert builtin_capability_registry.get(
            invocation.capability_id, invocation.capability_version
        )


@pytest.mark.asyncio
async def test_legacy_and_v3_nodes_run_together_with_unified_results() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node_payload("start", "start", {}),
                {
                    **_node_payload("wait", "capability", {}),
                    "capability_id": "flow.delay",
                    "capability_version": "2.0.0",
                    "configuration": {"seconds": 0},
                    "bindings": [],
                },
                _node_payload("end", "end", {}),
            ],
            "edges": [
                {"id": "start-wait", "source": "start", "target": "wait"},
                {"id": "wait-end", "source": "wait", "target": "end"},
            ],
        }
    )
    async with httpx.AsyncClient() as client:
        executor = WorkflowNodeExecutor(
            client,
            {},
            definition,
            OutboundNetworkPolicy((), ()),
        )
        result = await WorkflowScheduler(executor).run(
            definition,
            context=ExecutionContext(runtime_variables={"region": "cn"}),
        )

    assert result.status == "passed"
    assert [record.status for record in result.records] == ["passed", "passed", "passed"]
    assert result.records[1].node_type is NodeType.CAPABILITY
    assert result.records[1].result.status == "passed"
    snapshot = capability_snapshot(
        definition.nodes[1],
        registry=builtin_capability_registry,
    )
    assert snapshot["source"] == "v3"
    assert snapshot["capability_id"] == "flow.delay"
    assert len(str(snapshot["schema_hash"])) == 64


@pytest.mark.asyncio
async def test_scheduler_preserves_terminal_node_result_status() -> None:
    class ResultExecutor:
        async def execute(self, node: WorkflowNode, context: ExecutionContext) -> NodeResult:
            del context
            if node.id == "request":
                return NodeResult.failed(code="REMOTE_FAILURE", message="远端能力执行失败")
            return NodeResult.passed({"node": node.id})

    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node_payload("start", "start", {}),
                _node_payload(
                    "request",
                    "api",
                    {"api_definition_id": str(uuid4())},
                ),
                _node_payload("end", "end", {}),
            ],
            "edges": [
                {"id": "start-request", "source": "start", "target": "request"},
                {"id": "request-end", "source": "request", "target": "end"},
            ],
        }
    )

    result = await WorkflowScheduler(ResultExecutor()).run(definition)

    request = next(record for record in result.records if record.node_id == "request")
    assert result.status == "failed"
    assert request.status == "failed"
    assert request.error_code == "REMOTE_FAILURE"


def test_capability_node_contract_rejects_partial_or_unknown_adapters() -> None:
    with pytest.raises(ValidationError, match="must pin"):
        WorkflowNode.model_validate(_node_payload("broken", "capability", {}))
    with pytest.raises(ValidationError, match="legacy config"):
        WorkflowNode.model_validate(
            {
                **_node_payload("broken", "capability", {"seconds": 1}),
                "capability_id": "flow.delay",
                "capability_version": "2.0.0",
                "configuration": {"seconds": 1},
                "bindings": [],
            }
        )
    unknown = WorkflowNode.model_validate(
        {
            **_node_payload("unknown", "capability", {}),
            "capability_id": "vendor.unknown",
            "capability_version": "1.0.0",
            "configuration": {},
            "bindings": [],
        }
    )
    with pytest.raises(ValueError, match="no legacy adapter"):
        LegacyNodeAdapter().as_legacy_node(unknown)


def test_node_result_event_and_runner_contracts_are_explicit() -> None:
    result = NodeResult(
        status="passed",
        output={"id": 42},
        assertions=(NodeAssertion(name="状态码", passed=True, expected=200, actual=200),),
        metrics=(NodeMetric(name="duration", value=12.5, unit="ms"),),
        redacted_paths=("headers.authorization",),
    )
    assert normalize_node_result(result) is result
    assert normalize_node_result({"ok": True}).output == {"ok": True}
    failed = NodeResult.failed(code="NETWORK_ERROR", message="连接失败", retryable=True)
    assert failed.error and failed.error.retryable
    skipped = NodeResult(
        status="skipped",
        error={"code": "BRANCH_NOT_SELECTED", "message": "条件分支未被选择"},
    )
    assert skipped.error and skipped.error.code == "BRANCH_NOT_SELECTED"
    with pytest.raises(ValidationError, match="terminal"):
        NodeResult(status="running")
    with pytest.raises(ValidationError, match="must include an error"):
        NodeResult(status="failed")
    with pytest.raises(ValidationError, match="cannot include an error"):
        NodeResult(
            status="passed",
            error={"code": "IMPOSSIBLE", "message": "成功终态不得携带错误"},
        )

    execution_id = uuid4()
    event = ExecutionEvent(
        type=ExecutionEventType.NODE_RESULT,
        execution_id=execution_id,
        emitted_at=datetime.now(UTC),
        node_id="api",
        attempt=2,
        attempts=2,
        fencing_token=7,
        node_status="passed",
        result=result,
    )
    assert ExecutionEvent.model_validate_json(event.model_dump_json()).fencing_token == 7
    with pytest.raises(ValidationError, match="must identify a node"):
        ExecutionEvent(
            type="node.result",
            execution_id=execution_id,
            emitted_at=datetime.now(UTC),
            node_status="passed",
        )
    with pytest.raises(ValidationError, match="must match"):
        ExecutionEvent(
            type="node.result",
            execution_id=execution_id,
            emitted_at=datetime.now(UTC),
            node_id="api",
            node_status="failed",
            result=result,
        )
    with pytest.raises(ValidationError, match="UTC offset"):
        ExecutionEvent(
            type="execution.started",
            execution_id=execution_id,
            emitted_at=datetime.now(),
        )

    identity = RunnerIdentity(
        runner_id=uuid4(),
        pool_id=uuid4(),
        runner_type=RunnerType.GENERAL,
        labels=("arm64", "local"),
    )
    task = RunnerTaskEnvelope(
        task_id=uuid4(),
        execution_id=execution_id,
        node_id="api",
        attempt=1,
        fencing_token=7,
        capability_id="http.request",
        capability_version="2.0.0",
        schema_hash="a" * 64,
        snapshot={"configuration": {}},
        available_at=datetime.now(UTC),
    )
    lease = RunnerLease(
        lease_id=uuid4(),
        task=task,
        runner_id=identity.runner_id,
        acquired_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    progress = RunnerProgress(
        lease_id=lease.lease_id,
        fencing_token=lease.task.fencing_token,
        progress_percent=50,
        message="执行中",
    )
    assert progress.fencing_token == lease.task.fencing_token
    with pytest.raises(ValidationError, match="after acquisition"):
        RunnerLease(
            lease_id=uuid4(),
            task=task,
            runner_id=identity.runner_id,
            acquired_at=lease.acquired_at,
            expires_at=lease.acquired_at,
        )
    with pytest.raises(ValidationError, match="UTC offset"):
        RunnerTaskEnvelope.model_validate({**task.model_dump(), "available_at": datetime.now()})


@pytest.mark.asyncio
async def test_capability_api_auth_flags_admin_and_manifest_validation(
    capability_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anonymous = await capability_client.get("/api/v1/capabilities")
    assert anonymous.status_code == 401

    admin_headers = await _login_headers(capability_client, ADMIN_EMAIL, ADMIN_PASSWORD)
    user_headers = await _login_headers(capability_client, USER_EMAIL, USER_PASSWORD)
    flags = await capability_client.get("/api/v1/v3/features", headers=admin_headers)
    assert flags.status_code == 200
    assert flags.json() == {
        "capability_sdk": False,
        "plugin_registry": False,
        "runner_fabric": False,
    }

    capabilities = await capability_client.get(
        "/api/v1/capabilities?page=1&page_size=5",
        headers=user_headers,
    )
    assert capabilities.status_code == 200
    assert capabilities.json()["total"] == 12
    assert len(capabilities.json()["items"]) == 5
    first = capabilities.json()["items"][0]
    detail = await capability_client.get(
        f"/api/v1/capabilities/{first['id']}/versions/{first['version']}",
        headers=user_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["schema_hash"] == first["schema_hash"]
    missing = await capability_client.get(
        "/api/v1/capabilities/grpc.unary/versions/3.0.0",
        headers=user_headers,
    )
    assert missing.status_code == 404

    assert (await capability_client.get("/api/v1/plugins", headers=user_headers)).status_code == 403
    plugins = await capability_client.get("/api/v1/plugins", headers=admin_headers)
    pools = await capability_client.get("/api/v1/runner-pools", headers=admin_headers)
    assert plugins.status_code == 200 and plugins.json()["total"] == 0
    assert pools.status_code == 200 and pools.json()["total"] == 0

    disabled = await capability_client.post(
        "/api/v1/plugins/manifests/validate",
        headers=admin_headers,
        json={"manifest": _plugin_payload()},
    )
    assert disabled.status_code == 409
    monkeypatch.setattr(settings, "feature_plugin_registry_enabled", True)
    valid = await capability_client.post(
        "/api/v1/plugins/manifests/validate",
        headers=admin_headers,
        json={"manifest": _plugin_payload()},
    )
    assert valid.status_code == 200
    assert valid.json()["valid"] is True
    invalid = await capability_client.post(
        "/api/v1/plugins/manifests/validate",
        headers=admin_headers,
        json={"manifest": {"id": "bad"}},
    )
    assert invalid.status_code == 422


def _manifest(**updates: object) -> CapabilityManifest:
    values: dict[str, object] = {
        "id": "vendor.echo",
        "version": "1.0.0",
        "category": CapabilityCategory.INTEGRATION,
        "display_name": "Echo",
        "input_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        },
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        },
        "configuration_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        },
    }
    values.update(updates)
    return CapabilityManifest.model_validate(values)


def _plugin_payload() -> dict[str, object]:
    digest = f"sha256:{'b' * 64}"
    capability = _manifest(plugin_id="vendor.echo", plugin_digest=digest)
    return {
        "id": "vendor.echo",
        "version": "1.0.0",
        "display_name": "Echo",
        "oci_repository": "ghcr.io/flowtest/echo",
        "oci_digest": digest,
        "signature_identity": "https://github.com/flowtest/plugins/.github/workflows/release.yml",
        "capabilities": [capability.model_dump(mode="json")],
    }


def _node(node_id: str, node_type: NodeType, config: dict[str, Any]) -> WorkflowNode:
    return WorkflowNode.model_validate(_node_payload(node_id, node_type.value, config))


def _node_payload(node_id: str, node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": node_id,
        "position": {"x": 0, "y": 0},
        "config": config,
    }


def _user(email: str, password: str, *, system_admin: bool) -> User:
    return User(
        email=email,
        display_name=email.split("@", maxsplit=1)[0],
        password_hash=password_service.hash(password),
        is_active=True,
        is_system_admin=system_admin,
        requires_password_change=False,
    )


async def _login_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
