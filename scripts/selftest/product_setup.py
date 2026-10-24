"""Configure only an explicitly owned disposable A with public H/O deployment identities."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from scripts.selftest.bootstrap import bootstrap
from scripts.selftest.bootstrap_journal import BootstrapJournal
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import (
    StackBinding,
    _binding,
    _compose,
    _replace_private_environment,
    private_environment,
    verify_binding,
)
from scripts.selftest.product_agent_client import AgentIdentity, AgentRuntime, ProductAgentConfig
from scripts.selftest.product_mcp_identity import issue_identity, resolve_identity
from scripts.selftest.product_target_identity import target_cleanup_identity
from scripts.selftest.run import _verifier_digest

from app.core.self_tests import SelfTestBinding, SelfTestPrincipal, SelfTestSettings
from app.schemas.self_tests import BuildIdentity


def deployment_binding_id(nonce: str, builds: BuildIdentity) -> UUID:
    identity = canonical_digest({"nonce": nonce, "builds": builds.model_dump(mode="json")})
    return uuid5(NAMESPACE_URL, f"flowtest-selftest:{identity}")


def _identity(directory: Path, role: str, project: str, binding: str) -> AgentIdentity:
    path = directory / f"{role}-private.pem"
    if path.exists():
        raise HarnessError("SELFTEST_AGENT_SETUP_IDENTITY_ALREADY_EXISTS")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    descriptor = path.open("xb")
    try:
        path.chmod(0o600)
        descriptor.write(payload)
    finally:
        descriptor.close()
    principal = SelfTestPrincipal(
        id=f"local-{role}",
        issuer=f"flowtest-selftest-{role}",
        subject=role,
        audience="flowtest-selftest-api",
        public_key=key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
        allowed_project_ids=(project,),
        allowed_binding_ids=(binding,),
        capabilities=("install", "deterministic_mcp") if role == "H" else ("verify",),
        trusted_verifier=False,
    )
    return AgentIdentity(principal=principal, private_key_file=path.resolve())


async def setup(
    directory: Path, state: Path, *, recover_state: Path | None = None
) -> ProductAgentConfig:
    stack = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(stack, directory)
    if state.exists():
        raise HarnessError("SELFTEST_AGENT_SETUP_DIRECTORY_ALREADY_USED")
    state.mkdir(parents=True, mode=0o700)
    boot = await bootstrap(stack, directory, credential_role="observer")
    installed = boot.installation
    target_organization = installed.target_organization_id
    if target_organization is None:
        raise HarnessError("SELFTEST_AGENT_TARGET_ORGANIZATION_MISSING")
    private = private_environment(directory)
    administrator = PublicAPI(
        stack.runner_url, boot.credentials.admin_token, str(installed.organization_id)
    )
    try:
        account_id, mcp_token = await resolve_identity(
            administrator,
            installed,
            stack,
            directory,
            state,
            recover_state=recover_state,
            factory=PublicAPI,
            encryption_key=private["FLOWTEST_SELFTEST_RUNNER_ENCRYPTION_KEY"],
        )
    finally:
        await administrator.close()
    installed = installed.model_copy(update={"mcp_account_id": account_id})
    builds = BuildIdentity(
        runner=stack.candidate_image_digest,
        target=stack.candidate_image_digest,
        fixture=stack.fixture_image_digest.removeprefix("sha256:"),
        verifier=_verifier_digest(stack.runtime_profile),
    )
    binding_id = deployment_binding_id(stack.nonce, builds)
    fingerprint = canonical_digest(
        {
            "nonce": stack.nonce,
            "subnet": stack.private_subnet,
            "runner_volume": stack.runner_volume,
            "target_volume": stack.target_volume,
            "project": str(installed.project_id),
        }
    )
    binding = SelfTestBinding(
        id=binding_id,
        name="本轮隔离自测 A/B",
        allowed_project_ids=(installed.project_id,),
        runner_instance_id=f"runner-{stack.nonce}",
        target_instance_id=f"target-{stack.nonce}",
        target_display="独立 FlowTest B",
        fixture_display="独立确定性 Mock",
        target_base_url=stack.target_internal_url,
        fixture_base_url=stack.fixture_internal_url,
        target_project_id=installed.target_project_id,
        target_organization_id=installed.target_organization_id,
        target_user_id=installed.target_user_id,
        builds=builds,
        environment_fingerprint=fingerprint,
        isolation_fingerprint=fingerprint,
        non_production=True,
        isolated=True,
        outbound_authorized=True,
        runtime_profile=stack.runtime_profile,
        agent_id="local-H",
        observer_id="local-O",
    )
    harness, observer = (
        _identity(state, role, str(installed.project_id), str(binding_id)) for role in ("H", "O")
    )
    config = ProductAgentConfig(
        project_id=installed.project_id,
        binding=binding,
        harness=harness,
        observer=observer,
        host_id=f"isolated-H-{stack.nonce}",
    )
    public = SelfTestSettings(
        bindings=(binding,), principals=(harness.principal, observer.principal)
    )
    write_json(state / "public-settings.json", public)
    write_json(state / "agent-config.json", config)
    ui_path = directory / "ui-public.json"
    if ui_path.exists():
        origin = read_json(ui_path).get("url")
        if (
            not isinstance(origin, str)
            or re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", origin) is None
        ):
            raise HarnessError("SELFTEST_UI_ORIGIN_INVALID")
        private["FLOWTEST_SELFTEST_CORS_ORIGINS"] = json.dumps([origin])
    for field in ("bindings", "principals", "extra_templates"):
        private[f"FLOWTEST_SELFTEST_{field.upper()}"] = json.dumps(
            public.model_dump(mode="json")[field], ensure_ascii=False, separators=(",", ":")
        )
    write_json(
        state / "configuration-intent.json",
        {
            "status": "pending",
            "public_settings_sha256": hashlib.sha256(
                (state / "public-settings.json").read_bytes()
            ).hexdigest(),
        },
    )
    updated = _configure(stack, directory, state, private)
    verify_binding(updated, directory)
    write_json(directory / "stack.json", updated)
    write_json(
        state / "configuration-receipt.json",
        {
            "status": "completed",
            "binding_fingerprint": canonical_digest(binding.model_dump(mode="json")),
            "project_id": str(installed.project_id),
        },
    )
    target_administrator = PublicAPI(
        stack.target_url, boot.credentials.target_admin_token, str(installed.target_organization_id)
    )
    try:
        target_cleanup_token = await target_cleanup_identity(
            target_administrator,
            stack.target_url,
            project=installed.target_project_id,
            organization=target_organization,
            nonce=stack.nonce,
            initial_password="Cleanup-"
            + hashlib.sha256(
                (private["FLOWTEST_SELFTEST_TARGET_KEY"] + ":product-cleanup").encode()
            ).hexdigest()[:40],
            directory=state,
            journal=BootstrapJournal(directory, stack.nonce),
        )
    finally:
        await target_administrator.close()
    now = datetime.now(UTC)
    write_json(
        state / "harness-runtime.json",
        AgentRuntime(
            role="harness",
            installation=installed,
            issued_at=now,
            expires_at=now + timedelta(hours=2),
            fixture_management_token=private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"],
            writer_token=boot.credentials.reviewer_token,
            mcp_token=mcp_token,
            target_cleanup_token=target_cleanup_token,
        ),
    )
    write_json(
        state / "observer-runtime.json",
        AgentRuntime(
            role="observer",
            installation=installed,
            issued_at=now,
            expires_at=now + timedelta(hours=2),
            fixture_management_token=private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"],
            target_viewer_token=boot.credentials.target_viewer_token,
        ),
    )
    return config


async def _dedicated_mcp_identity(
    administrator: PublicAPI, organization_id: UUID, state: Path
) -> tuple[UUID, str]:
    return await issue_identity(administrator, organization_id, state)


def _configure(
    stack: StackBinding, directory: Path, state: Path, private: dict[str, str]
) -> StackBinding:
    if stack.runtime_profile != "standalone":
        from scripts.selftest.product_profile_setup import configure_profile_runner

        return configure_profile_runner(stack, directory, state, private)
    _replace_private_environment(directory / "private.env", private)
    _compose(
        stack.project_name,
        directory / "private.env",
        [
            "up",
            "--detach",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "120",
            "runner",
        ],
        timeout=180,
        log_path=state / "configure.log",
    )
    return _binding(stack.project_name, stack.nonce, private, directory / "private.env")


def main() -> None:
    parser = argparse.ArgumentParser(description="为本轮显式拥有的隔离栈登记真实产品 H/O")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--recover-state", type=Path)
    args = parser.parse_args()
    asyncio.run(setup(args.directory, args.state_directory, recover_state=args.recover_state))
    print("隔离产品代理已登记, 配置文件位于指定私有状态目录")


if __name__ == "__main__":
    main()
