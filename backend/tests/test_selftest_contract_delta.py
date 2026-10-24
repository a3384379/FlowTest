"""Real SDK adapters, public review APIs and native execution; ASGI only."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
import respx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.bootstrap import Installation  # noqa: E402
from scripts.selftest.contract_delta import DeltaJourney  # noqa: E402
from scripts.selftest.contract_delta_contracts import DeltaManifest, DeltaPack  # noqa: E402
from scripts.selftest.contracts import (  # noqa: E402
    Builds,
    FixtureBudgetScope,
    RequiredDisposal,
    canonical_digest,
)
from scripts.selftest.io import PublicAPI, read_json  # noqa: E402
from scripts.selftest.mcp_protocol_runner import ProtocolClient  # noqa: E402
from scripts.selftest.run_contract_delta import observe  # noqa: E402
from test_selftest_fixed_baseline import RunningAPI, _dependencies, _fixture_apps  # noqa: E402
from test_tasking_api import _login_headers  # noqa: E402
from test_tasking_api import tasking_context as tasking_context  # noqa: E402

from app.main import app  # noqa: E402
from app.mcp.client import MCPReadGatewayClient  # noqa: E402
from app.mcp.server import create_mcp_server  # noqa: E402


@pytest.fixture
def pack():
    return DeltaPack.model_validate(read_json(ROOT / "selftest/packs/contract-delta-v1/pack.json"))


@pytest.mark.asyncio
async def test_real_mcp_contract_v1_v2_review_publish_native_runs_and_slot_boundaries(
    tasking_context, tmp_path, pack
):
    context = tasking_context
    headers = await _login_headers(context.client)
    token = headers["Authorization"].split(" ")[1]
    api = RunningAPI(context, token)
    project, environment, service = await _dependencies(api)
    detail = await api.object("GET", "/projects/" + project)
    organization = detail["organization_id"]
    account = await api.object(
        "POST",
        f"/organizations/{organization}/service-accounts",
        {
            "name": "delta-fixture",
            "account_key": "delta_fixture",
            "scopes": [
                "mcp:read",
                "mcp:contract:import",
                "mcp:flow:propose",
                "mcp:evidence:write",
                "mcp:write",
            ],
        },
    )
    actor = UUID(jwt.decode(token, options={"verify_signature": False})["sub"])
    installation = Installation(
        binding_nonce="owned-delta",
        organization_id=organization,
        project_id=project,
        reviewer_id=actor,
        reviewer_email="fixture@example.com",
        mcp_account_id=account["id"],
        target_project_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.com",
        fixture_environment_id=environment,
        target_environment_id=environment,
        fixture_service_id=service,
        target_service_id=service,
    )
    now = datetime.now(UTC)
    frozen = DeltaManifest(
        pack_digest=canonical_digest(pack.model_dump(mode="json")),
        binding_fingerprint="a" * 64,
        binding_nonce="owned-delta",
        batch_key="delta_fixture",
        nonce="nonce_delta_0000000001",
        builds=Builds(runner="runner", target="target", fixture="f" * 64, verifier="verifier"),
        installation=installation,
        created_at=now,
        expires_at=now + timedelta(seconds=600),
        scope=FixtureBudgetScope(
            parent_batch_key="delta_fixture",
            nonce="nonce_delta_0000000001",
            limit=500,
            expires_at=(now + timedelta(seconds=600)).timestamp(),
        ),
        required_disposal=RequiredDisposal(
            project_name="owned",
            target_container_id="b" * 64,
            target_volume="owned_target",
            target_image="target",
            binding_nonce="owned-delta",
        ),
    )

    class CountedTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner, self.requests = httpx.ASGITransport(app=app), 0

        async def handle_async_request(self, request):
            self.requests += 1
            return await self.inner.handle_async_request(request)

    transport = CountedTransport()
    async with MCPReadGatewayClient(
        base_url="http://test", token=account["token"], transport=transport
    ) as gateway:
        server = create_mcp_server(client=gateway)

        class Session:
            protocol_version = "2026-07-28"

            async def call_tool(self, name, arguments, read_timeout_seconds):
                before = transport.requests
                result = await server.call_tool(name, arguments)
                assert transport.requests - before <= 3
                return result

        client = ProtocolClient(Session(), "stdio", frozen.batch_key + "-v1", tmp_path)
        tools = await server.list_tools()
        client.tools = frozenset(t.name for t in tools)
        client.tool_schemas = {t.name: t.input_schema for t in tools}
        client.catalog_digest = canonical_digest(
            [t.model_dump(mode="json", by_alias=True) for t in tools]
        )
        read_token = await api.object(
            "POST",
            f"/projects/{project}/service-tokens",
            {"name": "独立delta执行读取", "scopes": ["read:execution"]},
        )
        reader = PublicAPI(
            "http://test", read_token["token"], transport=httpx.ASGITransport(app=app)
        )
        business, admin = _fixture_apps(tmp_path)
        observer = PublicAPI(
            "http://observer",
            "synthetic-observer-token-only-for-tests-0001",
            api_prefix="",
            transport=httpx.ASGITransport(app=admin),
        )
        target_client = httpx.AsyncClient(
            base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
        )

        async def target(request):
            reply = await target_client.request(
                request.method,
                request.url.path,
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(
                reply.status_code, content=reply.content, headers=dict(reply.headers)
            )

        try:
            with respx.mock as routes:
                routes.route(host="fixed-fixture.example").mock(side_effect=target)
                journey = DeltaJourney(
                    frozen, pack, client, api, api, reader, api, observer, tmp_path / "journey"
                )
                evidence, report = await journey.run()
            assert report.exit_code == 2, report.model_dump_json(indent=2)
            assert report.findings == ("OWNED_ASSET_DISPOSAL_PENDING",)
            assert len(report.scenarios) == 7 and all(
                row.status == "matched" for row in report.scenarios
            )
            assert [phase.asset.api_source.api_version for phase in evidence.phases] == [1, 2]
            assert [row.observation.execution.status for row in evidence.observations] == [
                "passed",
                "passed",
            ]
            assert evidence.journal.request_count == 2
            assert len({phase.manifest.batch_key for phase in evidence.phases}) == 2
            assert observe(tmp_path / "journey") == 2
            independently_read = read_json(tmp_path / "journey/verification.json")
            assert independently_read["findings"] == ["OWNED_ASSET_DISPOSAL_PENDING"]
            assert all(row["status"] == "matched" for row in independently_read["scenarios"])
        finally:
            await target_client.aclose()
            await reader.close()
            await observer.close()
    await api.close()
