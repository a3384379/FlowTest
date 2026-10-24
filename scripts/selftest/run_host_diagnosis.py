"""Opt-in post-run diagnosis. A fresh signed task is required; default is NOT_RUN."""

from __future__ import annotations

import argparse
import asyncio
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
from mcp.shared.exceptions import MCPError
from mcp.types import Tool
from pydantic import TypeAdapter
from scripts.selftest.agent_endpoints import verify_agent_endpoints
from scripts.selftest.host_diagnosis import (
    DiagnosisConfig,
    DiagnosisGateway,
    DiagnosisOutput,
    diagnosis_prompt,
    diagnosis_task,
    execute_diagnosis,
    frozen_failure,
    retained_failure,
)
from scripts.selftest.host_launch import HostDeployment, HostReadiness, launch_plan, readiness
from scripts.selftest.host_product_generate import SessionUpstream
from scripts.selftest.host_prompts import read_skill
from scripts.selftest.host_runtime_config import approved_grant, private_file
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.product_agent import load_runtime
from scripts.selftest.product_agent_client import ProductAgentConfig
from scripts.selftest.run import _protocol


def _deployment(config: DiagnosisConfig, directory: Path) -> HostDeployment:
    runtime = config.runtime
    grant = approved_grant(runtime)
    task = diagnosis_task(config, grant)
    for path in (runtime.credential_home, runtime.workspace):
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not path.is_dir()
            or stat.S_IMODE(path.stat().st_mode) & 0o077
        ):
            raise HarnessError("HOST_DIAGNOSIS_PRIVATE_DEPLOYMENT_REQUIRED")
    if any(runtime.workspace.iterdir()):
        raise HarnessError("HOST_WORKSPACE_INVALID")
    return HostDeployment(
        runtime.host_id,
        runtime.cli_executable,
        runtime.cli_version,
        runtime.credential_home,
        runtime.workspace,
        runtime.relay_executable,
        directory / "relay.sock",
        read_skill(runtime.skill_directory).digest,
        task.authorized_data_digest,
        grant.authorization.task_digest,
        runtime.tool_isolation_attestation,
        runtime.provider_cap_verified,
        grant.authorization.policy_digest,
        runtime.relay_prefix_args,
    )


async def run(args: argparse.Namespace) -> int:
    if args.host_config is None:
        write_json(
            args.output_dir / "diagnosis.json",
            {
                "status": "NOT_RUN",
                "reason_codes": ["HOST_AUTHORIZATION_PENDING"],
                "actual_tool_calls": 0,
                "actual_model_calls": 0,
            },
        )
        return 2
    config = DiagnosisConfig.model_validate_json(private_file(args.host_config))
    grant = approved_grant(config.runtime)
    deadline = min(
        grant.authorization.expires_at,
        datetime.now(UTC) + timedelta(seconds=grant.authorization.budget.wall_seconds),
    )
    task = diagnosis_task(config, grant)
    deployment = _deployment(config, args.output_dir)
    status = readiness(grant, deployment)
    if not args.run_authorized or status.status != "ready":
        write_json(
            args.output_dir / "diagnosis.json",
            {
                "status": "NOT_RUN",
                "reason_codes": list(status.reason_codes or ("HOST_EXECUTION_NOT_REQUESTED",)),
                "actual_tool_calls": 0,
                "actual_model_calls": 0,
            },
        )
        return 2
    if args.agent_config is None or args.directory is None:
        raise HarnessError("HOST_DEPLOYMENT_AGENT_CONFIGURATION_REQUIRED")
    if args.output_dir.exists():
        raise HarnessError("HOST_DIAGNOSIS_OUTPUT_MUST_BE_NEW")
    stack = StackBinding.model_validate(read_json(args.directory / "stack.json"))
    verify_agent_endpoints(stack, args.directory)
    agent = ProductAgentConfig.model_validate(read_json(args.agent_config))
    runtime, boot = load_runtime(args.agent_config, "harness", stack)
    agent.verify(stack, boot)
    if agent.project_id != task.project_id:
        raise HarnessError("HOST_DIAGNOSIS_PROJECT_CHANGED")
    if (
        config.attempt_directory
        != agent.harness.private_key_file.parent / "host-diagnosis-attempts"
    ):
        raise HarnessError("HOST_DIAGNOSIS_ATTEMPT_ROOT_CHANGED")
    args.output_dir.mkdir(mode=0o700, parents=True)
    frozen_failure(config, task)
    reader = PublicAPI(
        stack.runner_url, runtime.writer_token, str(boot.installation.organization_id)
    )
    try:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise HarnessError("HOST_DIAGNOSIS_DEADLINE_EXCEEDED")
        async with asyncio.timeout(remaining):
            await retained_failure(reader, task)
            return await _authorized(
                args, config, deployment, stack, boot.credentials.mcp_token, reader, deadline
            )
    except TimeoutError:
        raise HarnessError("HOST_DIAGNOSIS_DEADLINE_EXCEEDED") from None
    finally:
        await reader.close()


async def _authorized(
    args: argparse.Namespace,
    config: DiagnosisConfig,
    deployment: HostDeployment,
    stack: StackBinding,
    token: str,
    reader: PublicAPI,
    deadline: datetime,
) -> int:
    grant = approved_grant(config.runtime)
    task = diagnosis_task(config, grant)
    skill = read_skill(config.runtime.skill_directory)
    prompt = diagnosis_prompt(task, "\n\n".join(part.text for part in skill.parts))
    schema = args.output_dir / "diagnosis-summary.schema.json"
    write_json(schema, DiagnosisOutput.model_json_schema())
    plan = launch_plan(
        grant,
        deployment,
        prompt=prompt,
        schema=schema,
        output=args.output_dir / "model-summary.json",
        deadline=deadline,
    )
    if isinstance(plan, HostReadiness):
        raise HarnessError("HOST_DIAGNOSIS_LAUNCH_NOT_READY")
    async with _protocol(
        stack, "stdio", token, task.batch_key, args.output_dir / "upstream"
    ) as client:
        tools = TypeAdapter(tuple[Tool, ...]).validate_python(
            read_json(args.output_dir / "upstream/mcp-catalog.json")["tools"]
        )
        gateway = DiagnosisGateway(
            task=task,
            grant=grant,
            attempt_id=uuid4(),
            catalog=tools,
            upstream=SessionUpstream(client.session),
            directory=args.output_dir,
            deadline=deadline,
        )
        receipt = await execute_diagnosis(
            plan,
            prompt=prompt,
            gateway=gateway,
            config=config,
            directory=args.output_dir,
            reader=reader,
        )
    # Artifacts are write-protected from the model workspace and are checked again after its exit.
    frozen_failure(config, task)
    return 0 if receipt.status == "diagnosed" else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-config", type=Path)
    parser.add_argument("--agent-config", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-authorized", action="store_true")
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except (HarnessError, OSError, ValueError, httpx.HTTPError, MCPError, jwt.PyJWTError) as error:
        write_json(
            args.output_dir / "failure.json",
            {
                "status": "blocked",
                "reason": str(error)
                if isinstance(error, HarnessError)
                else "HOST_DIAGNOSIS_SAFE_FAILURE",
            },
        )
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
