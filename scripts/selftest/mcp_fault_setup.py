"""Public fixture preparation for faults; no bootstrap, DB access or model dispatch."""

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
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import StackBinding, verify_binding
from scripts.selftest.mcp_fault_contracts import (
    FaultManifest,
    FaultPack,
    FaultScenario,
    FrozenCall,
    InactiveFixture,
)
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_probe_contracts import ProbeAuthority
from scripts.selftest.mcp_probe_setup import (
    ProbeAPI,
    Provisioned,
    _account,
    _login,
    _observer,
    authority,
    configure,
    provision,
)
from scripts.selftest.product_agent_client import AgentIdentity

ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "selftest/packs/mcp-transport-fault-v1/pack.json"


def arguments(project: UUID, batch: str, scenario: FaultScenario) -> tuple[str, JsonObject]:
    if scenario.fault == "unknown_mutation":
        return "flowtest.propose_test_design", {
            "project_id": str(project),
            "idempotency_key": batch + ":" + scenario.scenario_id,
            "dry_run": False,
            "title": "一次未知结果故障提案",
            "confidence": 1.0,
            "risk_level": "low",
            "test_cases": [],
            "design": {
                "intent": {
                    "key": "synthetic.governance",
                    "objective": "合成治理验证, 不执行发布运行",
                    "acceptance_criteria": ["只允许已批准草稿"],
                },
                "oracles": [
                    {
                        "id": "status",
                        "kind": "status",
                        "expression": "$.status",
                        "operator": "equals",
                        "expected": 200,
                        "confidence": 1.0,
                    }
                ],
            },
        }
    body: JsonObject = (
        {"expected_contract_version": "x" * 81} if scenario.fault == "oversized_field" else {}
    )
    return "flowtest.inspect_connection", {"request": body}


@dataclass(frozen=True, repr=False)
class PreparedFault:
    binding: StackBinding
    directory: Path
    state: Path
    manifest: FaultManifest
    authority: ProbeAuthority
    fixture: Provisioned
    observer: AgentIdentity
    inactive_token: str
    inactive_fixture: InactiveFixture
    budget: ProtocolHttpBudget


async def inactive_creator(
    binding: StackBinding,
    issued: Provisioned,
    nonce: str,
    budget: ProtocolHttpBudget,
    state: Path,
) -> tuple[Provisioned, UUID, UUID, str, InactiveFixture]:
    owner = ProbeAPI(binding.runner_url, budget, issued.tokens["human"])
    fixture = issued.fixture
    organization = fixture.identity.organization_a
    password = secrets.token_urlsafe(30)
    email = f"fault-inactive-{nonce[:12]}@example.com"
    try:
        owner.set_organization(str(organization))
        user = await owner.object(
            "POST",
            "/users",
            {"email": email, "password": password, "display_name": "故障专属停用创建者"},
        )
        user_id = UUID(text_value(user["id"]))
        await owner.object(
            "PUT",
            f"/organizations/{organization}/members/{user_id}",
            {"user_id": str(user_id), "role": "owner"},
        )
        token, actual = await _login(binding.runner_url, budget, email, password, new_actor=True)
        if user_id != actual:
            raise HarnessError("SELFTEST_FAULT_INACTIVE_CREATOR_IDENTITY_MISMATCH")
        creator = ProbeAPI(binding.runner_url, budget, token)
        try:
            machine, machine_token = await _account(
                creator, organization, "fault-inactive-" + nonce[:12], ["mcp:read"]
            )
        finally:
            await creator.close()
        changed = await owner.object("PATCH", f"/users/{user_id}", {"is_active": False})
        if changed.get("is_active") is not False or changed.get("id") != str(user_id):
            raise HarnessError("SELFTEST_FAULT_INACTIVE_CREATOR_NOT_DISABLED")
        listed = objects_value(
            await owner.request("GET", f"/organizations/{organization}/service-accounts")
        )
        matching = [row for row in listed if row.get("id") == str(machine)]
        if (
            len(matching) != 1
            or matching[0].get("created_by_id") != str(user_id)
            or matching[0].get("enabled") is not True
            or matching[0].get("revoked_at") is not None
        ):
            raise HarnessError("SELFTEST_FAULT_INACTIVE_MACHINE_STATE_MISMATCH")
        proof = InactiveFixture(
            creator_id=user_id,
            machine_id=machine,
            creator_is_active=False,
            machine_enabled=True,
            machine_revoked=False,
            user_response_digest=canonical_digest(changed),
            account_response_digest=canonical_digest(matching[0]),
            mechanism="public_user_patch_and_service_account_list",
        )
        write_json(state / "inactive-fixture-receipt.json", proof)
        updated = replace(
            issued, fixture=replace(fixture, machine_ids=(*fixture.machine_ids, machine))
        )
        return updated, user_id, machine, machine_token, proof
    finally:
        await owner.close()


async def _prepare(directory: Path, state: Path) -> PreparedFault:
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    installation = Installation.model_validate(read_json(directory / "installation.json"))
    if installation.binding_nonce != binding.nonce:
        raise HarnessError("SELFTEST_FAULT_EXISTING_INSTALLATION_REQUIRED")
    started = datetime.now(UTC)
    deadline = started + timedelta(seconds=600)
    nonce = secrets.token_hex(16)
    budget = ProtocolHttpBudget(state / "private/http-budget.sqlite3", nonce, deadline.timestamp())
    write_json(
        state / "setup-intent.json",
        {
            "nonce": nonce,
            "issued_at": started.isoformat(),
            "expires_at": deadline.isoformat(),
            "cleanup": "requires_owned_stack_disposal",
        },
    )
    async with asyncio.timeout(600):
        issued = await provision(binding, directory, state, nonce, budget)
        issued, creator, machine, inactive_token, inactive_proof = await inactive_creator(
            binding, issued, nonce, budget, state
        )
        raw = read_json(PACK_PATH)
        pack = FaultPack.model_validate(raw)
        project = issued.fixture.identity.project_a
        calls = tuple(
            FrozenCall(
                scenario_id=row.scenario_id,
                tool_name=arguments(project, state.name, row)[0],
                arguments_digest=canonical_digest(arguments(project, state.name, row)[1]),
            )
            for row in pack.scenarios
        )
        manifest = FaultManifest(
            batch_key=state.name,
            nonce=nonce,
            pack_digest=canonical_digest(raw),
            source_digest=binding.source_digest,
            created_at=started,
            expires_at=deadline,
            project_id=project,
            owner_user_id=issued.fixture.governance.owner_user_id,
            writer_machine_id=issued.fixture.governance.machine_id,
            inactive_creator_id=creator,
            inactive_machine_id=machine,
            scenarios=pack.scenarios,
            calls=calls,
        )
        frozen = authority(
            binding,
            issued.fixture,
            canonical_digest(manifest.model_dump(mode="json")),
            nonce,
            started,
            deadline,
        )
        identity = _observer(state, frozen)
        write_json(state / "public/manifest.json", manifest)
        write_json(state / "public/authority.json", frozen)
        task = asyncio.create_task(
            asyncio.to_thread(configure, binding, directory, state, frozen, identity, nonce)
        )
        try:
            updated = await asyncio.shield(task)
        except asyncio.CancelledError:
            # Recreate must finish before the cross-process ownership lock is
            # released; timeout cannot leave a background settings mutation.
            await task
            raise
    return PreparedFault(
        updated,
        directory,
        state,
        manifest,
        frozen,
        issued,
        identity,
        inactive_token,
        inactive_proof,
        budget,
    )


async def prepare(directory: Path, state: Path) -> PreparedFault:
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    # This is the same cross-process ownership lock as all public fixture setup.
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    with bootstrap_lock(directory, binding.nonce):
        return await _prepare(directory, state)
