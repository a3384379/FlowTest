"""Fresh review projects and least-privilege CI evidence reader; credentials stay in H."""

import asyncio
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args
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
from scripts.selftest.review_boundary_contracts import (
    ReviewAction,
    ReviewManifest,
    ReviewScenario,
    ReviewScope,
    ReviewTransport,
)

PACK_PATH = ROOT / "selftest/packs/mcp-review-recovery-v1/pack.json"


@dataclass(frozen=True, repr=False)
class PreparedReview:
    binding: StackBinding
    manifest: ReviewManifest
    authority: ProbeAuthority
    issued: Provisioned
    observer: AgentIdentity
    budget: ProtocolHttpBudget
    ci_token: str


async def scope_for(
    binding: StackBinding,
    issued: Provisioned,
    nonce: str,
    budget: ProtocolHttpBudget,
    deadline: datetime,
) -> tuple[Provisioned, ReviewScope, str]:
    project, org = issued.fixture.identity.project_a, issued.fixture.identity.organization_a
    api = ProbeAPI(binding.runner_url, budget, issued.tokens["human"], str(org))
    try:
        await api.object(
            "PUT",
            f"/projects/{project}/security-policy",
            {
                "enabled": True,
                "allowed_hosts": ["mock-target"],
                "allowed_private_cidrs": [binding.private_subnet],
            },
        )
        writer, token = await _account(
            api,
            org,
            "review-" + nonce[:12],
            [
                "project:read",
                "project:write",
                "mcp:read",
                "mcp:write",
                "mcp:flow:propose",
                "mcp:contract:import",
                "mcp:evidence:write",
                "mcp:preview:execute",
            ],
        )
        environments = [
            await api.object(
                "POST",
                f"/projects/{project}/environments",
                {
                    "name": "审核边界" + kind,
                    "classification": kind,
                    "base_url": binding.fixture_internal_url,
                },
            )
            for kind in ("test", "production")
        ]
        service = await api.object(
            "POST",
            f"/projects/{project}/services",
            {"name": "审核边界合成服务", "service_key": "review_fixture"},
        )
        for environment in environments:
            await api.object(
                "POST",
                f"/projects/{project}/environments/{environment['id']}/service-endpoints",
                {
                    "service_id": service["id"],
                    "variant": "default",
                    "base_url": binding.fixture_internal_url,
                },
            )
        for environment in environments:
            await api.object(
                "PATCH",
                f"/projects/{project}/environments/{environment['id']}",
                {"default_service_id": service["id"]},
            )
        ci = await api.object(
            "POST",
            f"/projects/{project}/service-tokens",
            {
                "name": "审核边界独立只读执行证据",
                "scopes": ["read:execution"],
                "expires_at": deadline.isoformat(),
            },
        )
        updated = replace(
            issued,
            writer_token=token,
            fixture=replace(
                issued.fixture,
                governance=issued.fixture.governance.model_copy(update={"machine_id": writer}),
                machine_ids=(*issued.fixture.machine_ids, writer),
            ),
        )
        scope = ReviewScope(
            project_id=project,
            fixture_environment_id=UUID(text_value(environments[0]["id"])),
            fixture_service_id=UUID(text_value(service["id"])),
            production_environment_id=UUID(text_value(environments[1]["id"])),
        )
        return updated, scope, text_value(ci["token"])
    finally:
        await api.close()


async def prepare(directory: Path, output: Path) -> PreparedReview:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    installation = Installation.model_validate(read_json(directory / "installation.json"))
    if installation.binding_nonce != binding.nonce:
        raise HarnessError("SELFTEST_REVIEW_EXISTING_INSTALLATION_REQUIRED")
    with bootstrap_lock(directory, binding.nonce):
        started, nonce = datetime.now(UTC), secrets.token_hex(16)
        deadline = started + timedelta(seconds=600)
        budget = ProtocolHttpBudget(output / "private-budget.sqlite3", nonce, deadline.timestamp())
        async with asyncio.timeout(600):
            issued = await provision(binding, directory, output, nonce, budget)
            issued, scope, ci_token = await scope_for(binding, issued, nonce, budget, deadline)
            raw = read_json(PACK_PATH)
            if raw["actions"] != list(get_args(ReviewAction)):
                raise HarnessError("SELFTEST_REVIEW_PACK_ACTION_SET_CHANGED")
            manifest = ReviewManifest(
                batch_key=output.name,
                nonce=nonce,
                pack_digest=canonical_digest(raw),
                source_digest=binding.source_digest,
                scope=scope,
                writer_machine_id=issued.fixture.governance.machine_id,
                reviewer_id=issued.fixture.governance.reviewer_user_id,
                created_at=started,
                expires_at=deadline,
                scenarios=tuple(
                    ReviewScenario(
                        scenario_id="REVIEW-" + action + "-" + transport,
                        action=action,
                        transport=transport,
                    )
                    for transport in get_args(ReviewTransport)
                    for action in get_args(ReviewAction)
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
            observer = _observer(output, frozen)
            write_json(output / "public/manifest.json", manifest)
            write_json(output / "public/authority.json", frozen)
            updated = await configure_owned(binding, directory, output, frozen, observer, nonce)
        return PreparedReview(updated, manifest, frozen, issued, observer, budget, ci_token)
