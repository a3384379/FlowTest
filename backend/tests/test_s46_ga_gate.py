from pathlib import Path

import httpx
import pytest

from app.domain.mcp_read import MCPReadEnvelope
from app.domain.runtime_profiles import (
    RuntimeFeature,
    RuntimeProfile,
    WorkerTopology,
    describe_runtime_profile,
)
from app.main import app
from app.mcp.client import MCPReadGatewayClient
from app.mcp.server import create_mcp_server


def test_runtime_profile_compatibility_matrix_is_explicit() -> None:
    expected = {
        RuntimeProfile.FULL: (WorkerTopology.ISOLATED, set()),
        RuntimeProfile.COMPACT: (
            WorkerTopology.CONSOLIDATED,
            {RuntimeFeature.PERFORMANCE_LAB, RuntimeFeature.ENVIRONMENT_LAB},
        ),
        RuntimeProfile.STANDALONE: (
            WorkerTopology.IN_PROCESS,
            {RuntimeFeature.PERFORMANCE_LAB, RuntimeFeature.ENVIRONMENT_LAB},
        ),
    }

    for profile, (topology, unavailable) in expected.items():
        description = describe_runtime_profile(profile)
        assert description.worker_topology is topology
        assert set(description.unavailable_features) == unavailable


def test_public_api_contract_stays_on_v1() -> None:
    route_paths = set(app.openapi()["paths"])
    assert {
        "/api/v1/live",
        "/api/v1/ready",
        "/api/v1/runtime-profile",
        "/api/v1/auth/login",
        "/api/v1/mcp/read/projects",
    } <= route_paths
    assert not any(path.startswith("/api/v2") for path in route_paths)


def test_ga_release_documents_and_current_migration_are_present() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    required = (
        repository_root / "docs/release/s46-ga-gate.md",
        repository_root / "docs/release/s46-compatibility-matrix.md",
        repository_root / "docs/operations/s46-failure-injection.md",
        repository_root / "backend/migrations/versions/20260823_0040_s45_change_regression.py",
    )
    assert all(path.is_file() for path in required)
    migration = required[-1].read_text(encoding="utf-8")
    assert 'revision: str = "20260823_0040"' in migration
    assert 'down_revision: str | None = "20260822_0039"' in migration


@pytest.mark.asyncio
async def test_mcp_red_team_surface_has_no_uncontrolled_mutation_tools() -> None:
    envelope = MCPReadEnvelope(
        data={"items": [], "total": 0, "page": 1, "page_size": 20},
        evidence_refs=[],
        confidence=1.0,
        redactions=[],
        trace_id="s46-red-team",
        warnings=[],
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope.model_dump(mode="json"))

    async with MCPReadGatewayClient(
        base_url="http://gateway",
        token="ftsa_red_team",
        transport=httpx.MockTransport(handler),
    ) as gateway:
        server = create_mcp_server(client=gateway)
        tools = await server.list_tools()
        names = {tool.name for tool in tools}

    assert "flowtest.propose_test_design" in names
    assert all(
        not any(
            marker in name
            for marker in ("publish", "execute", "delete", "credential", "permission", "shell")
        )
        for name in names
    )
    assert names == {
        "flowtest.analyze_test_coverage",
        "flowtest.begin_test_context",
        "flowtest.close_test_context",
        "flowtest.compile_integration_flowspec",
        "flowtest.diff_flowspec",
        "flowtest.discover_services",
        "flowtest.explain_compiler_diagnostics",
        "flowtest.export_flowspec",
        "flowtest.generate_test_design",
        "flowtest.ingest_database_evidence",
        "flowtest.ingest_external_evidence",
        "flowtest.ingest_java_evidence",
        "flowtest.inspect_change_impact",
        "flowtest.inspect_context_requirements",
        "flowtest.inspect_contract",
        "flowtest.inspect_data_profile",
        "flowtest.inspect_entity_mapping",
        "flowtest.inspect_flow",
        "flowtest.inspect_flow_proposal",
        "flowtest.inspect_project",
        "flowtest.inspect_run_evidence",
        "flowtest.inspect_source_evidence",
        "flowtest.inspect_test_context",
        "flowtest.inspect_test_evidence",
        "flowtest.list_projects",
        "flowtest.plan_integration_test",
        "flowtest.propose_flow_draft",
        "flowtest.propose_test_design",
        "flowtest.validate_flowspec",
        "flowtest.validate_integration_plan",
    }
