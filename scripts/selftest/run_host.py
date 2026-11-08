"""Deployment-only real host entrypoint. Default invocation is a non-executing NOT_RUN check."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Literal

import httpx
import jwt
from mcp.shared.exceptions import MCPError
from scripts.selftest.agent_endpoints import verify_agent_endpoints
from scripts.selftest.host_launch import readiness
from scripts.selftest.host_product_generate import generate_task
from scripts.selftest.host_product_observe import observe_task
from scripts.selftest.host_runtime_config import (
    approved_grant,
    approved_runtime,
    approved_task,
    load_config,
    private_file,
)
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.product_agent import arm_target_lifecycle, load_runtime
from scripts.selftest.product_agent_client import (
    ProductAgentConfig,
    agent_api,
    agent_root,
    claim,
    keep_lease,
    lease_body,
    register,
)
from scripts.selftest.product_evidence import TaskEvidenceReader

from app.schemas.self_tests import AgentTaskList, AgentTaskResponse


async def poll_host(
    *,
    stack_directory: Path,
    state_directory: Path,
    agent_config: Path,
    host_config: Path,
    role: Literal["harness", "observer"],
    resume_known_review: bool = False,
) -> int:
    config = load_config(host_config)
    grant = approved_grant(config)
    stack = StackBinding.model_validate(read_json(stack_directory / "stack.json"))
    verify_agent_endpoints(stack, stack_directory)
    agent = ProductAgentConfig.model_validate(read_json(agent_config))
    runtime, boot = load_runtime(agent_config, role, stack)
    agent.verify(stack, boot)
    identity = agent.harness if role == "harness" else agent.observer
    async with AsyncExitStack() as scope:
        machine = agent_api(stack, identity)
        observer = PublicAPI(stack.observer_url, runtime.fixture_management_token, api_prefix="")
        for api in (machine, observer):
            scope.push_async_callback(api.close)
        await register(machine, agent, observer=role == "observer")
        tasks = AgentTaskList.model_validate(
            await machine.object("GET", agent_root(agent.project_id) + "/tasks")
        )
        for batch in tasks.batches:
            if (
                batch.batch_key != grant.authorization.batch_key
                or batch.generation_mode != "host_llm_mcp"
            ):
                continue
            expected = "pending" if role == "harness" else "running"
            if (
                resume_known_review
                and role == "harness"
                and batch.phase in {"generating", "awaiting_review"}
            ):
                saved = AgentTaskResponse.model_validate_json(
                    private_file(state_directory / str(batch.id) / "private-lease.json")
                )
                task = AgentTaskResponse.model_validate(
                    await machine.object(
                        "POST",
                        f"{agent_root(agent.project_id)}/runs/{batch.id}/lease",
                        lease_body(saved).model_dump(mode="json"),
                    )
                )
            elif batch.phase == expected:
                task = await claim(
                    machine, agent.project_id, batch.id, batch.revision, state_directory
                )
            else:
                continue
            directory = state_directory / str(batch.id)
            async with keep_lease(machine, task):
                if role == "observer":
                    task_reader = TaskEvidenceReader(stack.runner_url, identity.token(), task)
                    scope.push_async_callback(task_reader.close)
                    await observe_task(
                        machine,
                        task_reader,
                        observer,
                        task=task,
                        stack=stack,
                        boot=boot,
                        directory=directory,
                        grant=grant,
                        frozen_task=approved_task(config, grant),
                        quality_root=agent.harness.private_key_file.parent,
                        quality_signer=agent.observer,
                        host_config=config,
                    )
                else:
                    reader = PublicAPI(
                        stack.runner_url,
                        runtime.writer_token,
                        str(boot.installation.organization_id),
                    )
                    scope.push_async_callback(reader.close)
                    if not resume_known_review:
                        await arm_target_lifecycle(task, stack, boot, directory)
                    await generate_task(
                        machine,
                        reader,
                        observer,
                        task=task,
                        stack=stack,
                        boot=boot,
                        directory=directory,
                        config=config,
                        resume_known_review=resume_known_review,
                        quality_root=agent.harness.private_key_file.parent,
                        quality_verifier=agent.observer.principal,
                    )
            return 1
    return 0


async def _main(args: argparse.Namespace) -> int:
    if args.host_config is None:
        write_json(
            args.output,
            {
                "status": "NOT_RUN",
                "reason_codes": ["HOST_AUTHORIZATION_PENDING"],
                "actual_model_calls": 0,
            },
        )
        return 2
    config = load_config(args.host_config)
    if args.role == "observer" and args.run_authorized:
        approved_grant(config)
        from scripts.selftest.host_launch import HostReadiness

        status = HostReadiness("ready", ())
    else:
        grant, deployment, _ = approved_runtime(config, args.state_directory)
        status = readiness(grant, deployment)
    if not args.run_authorized or status.status != "ready":
        write_json(
            args.output,
            {
                "status": "NOT_RUN",
                "reason_codes": list(status.reason_codes or ("HOST_EXECUTION_NOT_REQUESTED",)),
                "actual_model_calls": 0,
            },
        )
        return 2
    if args.agent_config is None or args.directory is None:
        raise HarnessError("HOST_DEPLOYMENT_AGENT_CONFIGURATION_REQUIRED")
    return await poll_host(
        stack_directory=args.directory,
        state_directory=args.state_directory,
        agent_config=args.agent_config,
        host_config=args.host_config,
        role=args.role,
        resume_known_review=args.resume_known_review,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-config", type=Path)
    parser.add_argument("--agent-config", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument(
        "--state-directory", type=Path, default=Path(".flowtest-host-state").absolute()
    )
    parser.add_argument("--output", type=Path, default=Path("host-not-run.json"))
    parser.add_argument("--role", choices=("harness", "observer"), default="harness")
    parser.add_argument("--run-authorized", action="store_true")
    parser.add_argument("--resume-known-review", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(_main(args))
    except (
        HarnessError,
        OSError,
        ValueError,
        jwt.PyJWTError,
        httpx.HTTPError,
        MCPError,
        ExceptionGroup,
    ) as error:
        code = (
            str(error).split(":")[0]
            if isinstance(error, HarnessError)
            else "HOST_CONFIGURATION_OR_STATE_INVALID"
        )
        write_json(
            args.output, {"status": "blocked", "reason_codes": [code], "billed_cost": "unknown"}
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
