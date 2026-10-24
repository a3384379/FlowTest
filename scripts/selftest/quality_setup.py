"""Fresh synthetic quality projects and exact scoped observer grant; owner stays in H."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from scripts.selftest.bootstrap import Installation
from scripts.selftest.bootstrap_journal import bootstrap_lock
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, read_json, text_value, write_json
from scripts.selftest.local_stack import ROOT, StackBinding, verify_binding
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_setup import (
    ProbeAPI,
    Provisioned,
    _account,
    _observer,
    authority,
    configure_owned,
    provision,
)
from scripts.selftest.product_agent_client import AgentIdentity
from scripts.selftest.quality_boundaries import boundary_requests
from scripts.selftest.quality_contracts import (
    QualityCall,
    QualityManifest,
    QualityPack,
    QualityScope,
)

PACK_PATH = ROOT / "selftest/packs/mcp-quality-boundaries-v1/pack.json"


@dataclass(frozen=True, repr=False)
class PreparedQuality:
    binding: StackBinding
    directory: Path
    output: Path
    manifest: QualityManifest
    authority: ProbeAuthority
    issued: Provisioned
    observer: AgentIdentity
    sentinel: str
    budget: ProtocolHttpBudget


async def _scope(
    binding: StackBinding,
    issued: Provisioned,
    nonce: str,
    budget: ProtocolHttpBudget,
) -> tuple[Provisioned, QualityScope, str]:
    fixture = issued.fixture
    project, organization = fixture.identity.project_a, fixture.identity.organization_a
    api = ProbeAPI(binding.runner_url, budget, issued.tokens["human"], str(organization))
    try:
        writer, token = await _account(
            api,
            organization,
            "quality-" + nonce[:12],
            [
                "project:read",
                "project:write",
                "mcp:read",
                "mcp:write",
                "mcp:flow:propose",
                "mcp:evidence:write",
                "mcp:contract:import",
                "mcp:test-plan:propose",
            ],
        )
        base = f"/projects/{project}"
        environments = []
        for classification in ("test", "production"):
            environments.append(
                await api.object(
                    "POST",
                    base + "/environments",
                    {
                        "name": "质量边界" + classification,
                        "classification": classification,
                        "base_url": binding.fixture_internal_url,
                    },
                )
            )
        service = await api.object(
            "POST",
            base + "/services",
            {
                "name": "质量边界合成服务",
                "service_key": "quality_fixture",
            },
        )
        reference = "quality_probe_credential"
        for environment in environments:
            await api.object(
                "POST",
                base + f"/environments/{environment['id']}/service-endpoints",
                {
                    "service_id": service["id"],
                    "variant": "default",
                    "base_url": binding.fixture_internal_url,
                    "secret_refs": [reference] if environment is environments[0] else [],
                },
            )
        sentinel = "synthetic-quality-private-" + secrets.token_hex(16)
        metadata = await api.object(
            "PUT",
            base + "/secrets",
            {
                "environment_id": environments[0]["id"],
                "name": reference,
                "value": sentinel,
            },
        )
        if "value" in metadata or "encrypted_value" in metadata:
            raise HarnessError("SELFTEST_QUALITY_SECRET_NOT_WRITEONLY")
        updated = replace(
            issued,
            writer_token=token,
            fixture=replace(
                fixture,
                governance=fixture.governance.model_copy(update={"machine_id": writer}),
                machine_ids=(*fixture.machine_ids, writer),
            ),
        )
        scope = QualityScope(
            project_id=project,
            fixture_environment_id=UUID(text_value(environments[0]["id"])),
            production_environment_id=UUID(text_value(environments[1]["id"])),
            fixture_service_id=UUID(text_value(service["id"])),
            credential_ref=reference,
        )
        return updated, scope, sentinel
    finally:
        await api.close()


async def prepare(directory: Path, output: Path) -> PreparedQuality:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    installed = Installation.model_validate(read_json(directory / "installation.json"))
    if installed.binding_nonce != binding.nonce:
        raise HarnessError("SELFTEST_QUALITY_EXISTING_INSTALLATION_REQUIRED")
    with bootstrap_lock(directory, binding.nonce):
        started, nonce = datetime.now(UTC), secrets.token_hex(16)
        deadline = started + timedelta(seconds=600)
        budget = ProtocolHttpBudget(
            output / "private/http-budget.sqlite3", nonce, deadline.timestamp()
        )
        write_json(
            output / "setup-intent.json",
            {
                "nonce": nonce,
                "created_at": started.isoformat(),
                "expires_at": deadline.isoformat(),
                "cleanup": "requires_owned_stack_disposal",
            },
        )
        async with asyncio.timeout(600):
            issued = await provision(binding, directory, output, nonce, budget)
            issued, scope, sentinel = await _scope(binding, issued, nonce, budget)
            raw = read_json(PACK_PATH)
            pack = QualityPack.model_validate(raw)
            manifest = QualityManifest(
                batch_key=output.name,
                nonce=nonce,
                pack_digest=canonical_digest(raw),
                source_digest=binding.source_digest,
                scope=scope,
                writer_machine_id=issued.fixture.governance.machine_id,
                reader_machine_id=issued.fixture.machine_ids[0],
                created_at=started,
                expires_at=deadline,
                scenarios=pack.scenarios,
                calls=tuple(
                    QualityCall(
                        scenario_id=row.scenario_id,
                        tool_name=name,
                        arguments_digest=canonical_digest(arguments),
                    )
                    for row in pack.scenarios
                    if row.action in {"scope", "target", "credential_ref"}
                    for name, arguments in boundary_requests(
                        scope, output.name + "-" + row.transport, row.action
                    )
                ),
            )
            frozen = authority(
                binding,
                issued.fixture,
                canonical_digest(manifest.model_dump(mode="json")),
                nonce,
                started,
                deadline,
            )
            identity = _observer(output, frozen)
            write_json(output / "public/manifest.json", manifest)
            write_json(output / "public/authority.json", frozen)
            updated = await configure_owned(binding, directory, output, frozen, identity, nonce)
        return PreparedQuality(
            updated, directory, output, manifest, frozen, issued, identity, sentinel, budget
        )
