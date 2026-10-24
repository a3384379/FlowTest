"""Synthetic SDK→public review→native region execution; no real model or human."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import jwt
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import Builds, RequiredDisposal, canonical_digest  # noqa: E402
from scripts.selftest.io import PublicAPI, write_json  # noqa: E402
from scripts.selftest.mcp_protocol_runner import ProtocolClient  # noqa: E402
from scripts.selftest.native_control import NativeControlJourney  # noqa: E402
from scripts.selftest.native_control_contracts import NativeControlManifest  # noqa: E402
from scripts.selftest.native_control_verify import load_pack, verify  # noqa: E402
from scripts.selftest.run_native_control import observe  # noqa: E402
from test_selftest_fixed_baseline import RunningAPI, _dependencies  # noqa: E402
from test_tasking_api import _login_headers  # noqa: E402
from test_tasking_api import tasking_context as tasking_context  # noqa: E402

from app.main import app  # noqa: E402
from app.mcp.client import MCPReadGatewayClient  # noqa: E402
from app.mcp.server import create_mcp_server  # noqa: E402


@pytest.mark.asyncio
async def test_real_sdk_native4_review_publish_run_branch_records_and_export_refusal(
    tasking_context, tmp_path
):
    context = tasking_context
    headers = await _login_headers(context.client)
    token = headers["Authorization"].split(" ")[1]
    api = RunningAPI(context, token)
    project, environment, _ = await _dependencies(api)
    detail = await api.object("GET", "/projects/" + project)
    account = await api.object(
        "POST",
        f"/organizations/{detail['organization_id']}/service-accounts",
        {
            "name": "native-control",
            "account_key": "native_control",
            "scopes": ["mcp:read", "mcp:flow:propose", "mcp:write"],
        },
    )
    read_token = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "仅本项目执行证据", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", read_token["token"], transport=httpx.ASGITransport(app=app))
    pack = load_pack(ROOT / "selftest/packs/native-control-mcp-v1/pack.json")
    now = datetime.now(UTC)
    frozen = NativeControlManifest(
        batch_key="native_control_fixture",
        nonce="native-control-nonce-0001",
        pack_digest=canonical_digest(pack.model_dump(mode="json")),
        binding_fingerprint="a" * 64,
        binding_nonce="owned-native-control",
        builds=Builds(runner="runner", target="target", fixture="f" * 64, verifier="verifier"),
        project_id=UUID(project),
        environment_id=UUID(environment),
        reviewer_id=UUID(jwt.decode(token, options={"verify_signature": False})["sub"]),
        mcp_account_id=UUID(account["id"]),
        mcp_actor_id=UUID(account["created_by_id"]),
        created_at=now,
        expires_at=now + timedelta(seconds=600),
        required_disposal=RequiredDisposal(
            project_name="owned",
            target_container_id="b" * 64,
            target_volume="owned_runner",
            target_image="runner",
            binding_nonce="owned-native-control",
        ),
    )
    async with MCPReadGatewayClient(
        base_url="http://test", token=account["token"], transport=httpx.ASGITransport(app=app)
    ) as gateway:
        server = create_mcp_server(client=gateway)

        class Session:
            protocol_version = "2026-07-28"

            async def call_tool(self, name, arguments, read_timeout_seconds):
                return await server.call_tool(name, arguments)

        client = ProtocolClient(Session(), "stdio", frozen.batch_key, tmp_path / "protocol")
        tools = await server.list_tools()
        client.tools = frozenset(tool.name for tool in tools)
        client.tool_schemas = {tool.name: tool.input_schema for tool in tools}
        client.catalog_digest = canonical_digest(
            [tool.model_dump(mode="json", by_alias=True) for tool in tools]
        )
        try:
            journey = NativeControlJourney(
                frozen, pack, client, api, reader, api, tmp_path / "journey"
            )
            evidence = await journey.run()
            report = verify(frozen, pack, evidence)
            write_json(tmp_path / "report.json", report)
            assert report.exit_code == 2, report.model_dump_json(indent=2)
            assert report.findings == ("OWNED_ASSET_DISPOSAL_PENDING",)
            assert all(row.status == "matched" for row in report.scenarios), report.model_dump_json(
                indent=2
            )
            assert evidence.execution.status == "passed"
            assert evidence.control_page["total"] == 2
            assert evidence.execution.api_sources == ()
            assert [row.error_code for row in evidence.exports] == [
                "FLOWSPEC_CONTROL_UNSUPPORTED"
            ] * 2
            assert len(evidence.calls) == 2
            assert observe(tmp_path / "journey") == 2
        finally:
            await reader.close()
            await api.close()
