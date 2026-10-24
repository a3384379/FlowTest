"""External deployment-bound H/O worker; the HTTP application never starts processes."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Literal

import jwt
from scripts.selftest.agent_endpoints import verify_agent_endpoints
from scripts.selftest.bootstrap import BootstrapResult
from scripts.selftest.failures import failure_codes
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    object_value,
    read_json,
    write_json,
)
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.product_agent_client import (
    AgentRuntime,
    ProductAgentConfig,
    agent_api,
    agent_root,
    claim,
    keep_lease,
    register,
)
from scripts.selftest.product_evidence import TaskEvidenceReader
from scripts.selftest.product_fixed import install_task, observe_fixed, prepare_task

from app.schemas.self_tests import AgentTaskList, AgentTaskResponse, BatchResponse


def _host_ready(batch: BatchResponse, path: Path | None, directory: Path) -> bool:
    if batch.generation_mode != "host_llm_mcp":
        return True
    from scripts.selftest.host_runtime_config import approved_grant, load_config

    reason = "HOST_AUTHORIZATION_PENDING"
    if path is not None:
        try:
            grant = approved_grant(load_config(path))
            if (
                grant.authorization.project_id == batch.project_id
                and grant.authorization.batch_key == batch.batch_key
                and grant.authorization.policy_digest == batch.policy_digest
            ):
                return True
            reason = "HOST_AUTHORIZATION_TASK_MISMATCH"
        except (HarnessError, OSError, ValueError, jwt.PyJWTError):
            reason = "HOST_CONFIGURATION_OR_AUTHORIZATION_INVALID"
    write_json(
        directory / str(batch.id) / "host-not-run.json",
        {"status": "NOT_RUN", "reason_codes": [reason], "stage": "agent_dispatch"},
    )
    return False


async def arm_target_lifecycle(
    task: AgentTaskResponse, stack: StackBinding, boot: BootstrapResult, directory: Path
) -> None:
    from scripts.selftest.product_resource_cleanup import arm_owned_lifecycle

    token = boot.credentials.target_cleanup_token
    if not token:
        await arm_owned_lifecycle(task, None, directory)
        return
    target = PublicAPI(stack.target_url, token, str(boot.installation.target_organization_id))
    try:
        await arm_owned_lifecycle(task, target, directory)
    finally:
        await target.close()


async def _generate(
    machine: PublicAPI,
    writer: PublicAPI,
    observer: PublicAPI,
    *,
    task: AgentTaskResponse,
    stack: StackBinding,
    boot: BootstrapResult,
    directory: Path,
    installation_directory: Path,
    review_mode: Literal["human", "ci_fixture", "ui_fixture"],
    host_config: Path | None,
    quality_agent: ProductAgentConfig | None = None,
) -> None:
    await arm_target_lifecycle(task, stack, boot, directory)
    if task.task_kind == "preparation":
        await prepare_task(
            machine,
            observer,
            task,
            directory=directory,
            installation_directory=installation_directory,
            asset_reader=writer,
        )
    elif task.batch is not None and task.batch.generation_mode == "host_llm_mcp":
        from scripts.selftest.host_product_generate import (
            generate_task as host_generate,
        )
        from scripts.selftest.host_runtime_config import load_config

        if host_config is None:
            raise HarnessError("HOST_AUTHORIZATION_PENDING")
        await host_generate(
            machine,
            writer,
            observer,
            task=task,
            stack=stack,
            boot=boot,
            directory=directory,
            config=load_config(host_config),
            quality_root=None
            if quality_agent is None
            else quality_agent.harness.private_key_file.parent,
            quality_verifier=None if quality_agent is None else quality_agent.observer.principal,
        )
    else:
        from scripts.selftest.product_mcp import generate_task

        await generate_task(
            machine,
            writer,
            observer,
            task=task,
            stack=stack,
            boot=boot,
            directory=directory,
            review_mode=review_mode,
        )


async def _observe(
    machine: PublicAPI,
    writer: PublicAPI,
    reader: TaskEvidenceReader,
    observer: PublicAPI,
    *,
    task: AgentTaskResponse,
    stack: StackBinding,
    boot: BootstrapResult,
    directory: Path,
    host_config: Path | None,
    quality_agent: ProductAgentConfig | None = None,
) -> None:
    if task.batch is None:
        raise HarnessError("SELFTEST_AGENT_BATCH_MISSING")
    if task.batch.batch_kind == "fixed_baseline":
        await observe_fixed(machine, writer, reader, observer, task, directory)
    elif task.batch.generation_mode == "host_llm_mcp":
        from scripts.selftest.host_product_observe import observe_task as host_observe
        from scripts.selftest.host_runtime_config import (
            approved_grant,
            approved_task,
            load_config,
        )

        if host_config is None:
            raise HarnessError("HOST_AUTHORIZATION_PENDING")
        config = load_config(host_config)
        grant = approved_grant(config)
        await host_observe(
            machine,
            reader,
            observer,
            task=task,
            stack=stack,
            boot=boot,
            directory=directory,
            grant=grant,
            frozen_task=approved_task(config, grant),
            quality_root=None
            if quality_agent is None
            else quality_agent.harness.private_key_file.parent,
            quality_signer=None if quality_agent is None else quality_agent.observer,
            host_config=config,
        )
    else:
        from scripts.selftest.product_mcp import observe_task

        await observe_task(
            machine,
            writer,
            reader,
            observer,
            task=task,
            stack=stack,
            boot=boot,
            directory=directory,
        )


def load_runtime(
    config_path: Path, role: Literal["harness", "observer"], stack: StackBinding
) -> tuple[AgentRuntime, BootstrapResult]:
    runtime_path = config_path.parent / f"{role}-runtime.json"
    if runtime_path.is_symlink() or runtime_path.stat().st_mode & 0o077:
        raise HarnessError("SELFTEST_AGENT_RUNTIME_FILE_PERMISSIONS")
    runtime = AgentRuntime.model_validate(read_json(runtime_path))
    return runtime, runtime.bootstrap_result(role, stack)


async def poll(
    *,
    stack_directory: Path,
    state_directory: Path,
    config_path: Path,
    role: Literal["harness", "observer"],
    review_mode: Literal["human", "ci_fixture", "ui_fixture"] = "human",
    host_config: Path | None = None,
) -> int:
    stack = StackBinding.model_validate(read_json(stack_directory / "stack.json"))
    verify_agent_endpoints(stack, stack_directory)
    config = ProductAgentConfig.model_validate(read_json(config_path))
    runtime, boot = load_runtime(config_path, role, stack)
    config.verify(stack, boot)
    installation = boot.installation
    identity = config.observer if role == "observer" else config.harness
    state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with AsyncExitStack() as scope:
        machine = agent_api(stack, identity)
        writer = PublicAPI(
            stack.runner_url,
            boot.credentials.reviewer_token,
            str(installation.organization_id),
        )
        observer = PublicAPI(stack.observer_url, runtime.fixture_management_token, api_prefix="")
        for api in (machine, writer, observer):
            scope.push_async_callback(api.close)
        await register(machine, config, observer=role == "observer")
        tasks = AgentTaskList.model_validate(
            await machine.object("GET", agent_root(config.project_id) + "/tasks")
        )
        if role == "harness":
            target_cleanup = None
            if boot.credentials.target_cleanup_token:
                target_cleanup = PublicAPI(
                    stack.target_url,
                    boot.credentials.target_cleanup_token,
                    str(installation.target_organization_id),
                )
                scope.push_async_callback(target_cleanup.close)
            from scripts.selftest.product_watchdog import run_expired_watchdogs

            await run_expired_watchdogs(
                machine,
                tasks.batches,
                state_directory,
                writer=writer,
                observer=observer,
                target_cleanup=target_cleanup,
            )
            for item in tasks.installations:
                if item.status == "queued":
                    task = await claim(
                        machine,
                        config.project_id,
                        item.id,
                        item.revision,
                        state_directory,
                        installation=True,
                    )
                    async with keep_lease(machine, task):
                        await install_task(
                            machine,
                            writer,
                            task=task,
                            installation=installation,
                            directory=state_directory / str(item.id),
                        )
                    return 1
        for batch in tasks.batches:
            actionable = (role == "harness" and batch.phase == "pending") or (
                role == "observer" and batch.phase == "running"
            )
            if actionable and not _host_ready(batch, host_config, state_directory):
                continue
            if role == "harness" and batch.phase == "pending":
                task = await claim(
                    machine,
                    config.project_id,
                    batch.id,
                    batch.revision,
                    state_directory,
                )
                async with keep_lease(machine, task):
                    await _generate(
                        machine,
                        writer,
                        observer,
                        task=task,
                        stack=stack,
                        boot=boot,
                        directory=state_directory / str(batch.id),
                        installation_directory=state_directory / str(batch.installation_id),
                        review_mode=review_mode,
                        host_config=host_config,
                        quality_agent=config,
                    )
                return 1
            if role == "observer" and batch.phase == "running":
                task = await claim(
                    machine,
                    config.project_id,
                    batch.id,
                    batch.revision,
                    state_directory,
                )
                reader = TaskEvidenceReader(stack.runner_url, identity.token(), task)
                scope.push_async_callback(reader.close)
                async with keep_lease(machine, task):
                    await _observe(
                        machine,
                        writer,
                        reader,
                        observer,
                        task=task,
                        stack=stack,
                        boot=boot,
                        directory=state_directory / str(batch.id),
                        host_config=host_config,
                        quality_agent=config,
                    )
                return 1
    return 0


async def _main(arguments: argparse.Namespace) -> int:
    async with asyncio.timeout(arguments.timeout_seconds):
        while True:
            count = await poll(
                stack_directory=arguments.directory,
                state_directory=arguments.state_directory,
                config_path=arguments.config,
                role=arguments.role,
                review_mode=arguments.review_mode,
                host_config=arguments.host_config,
            )
            if arguments.once:
                return 0
            if count == 0:
                await asyncio.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="运行部署登记的外部自测 H/O 代理")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--role", choices=("harness", "observer"), required=True)
    parser.add_argument(
        "--review-mode", choices=("human", "ci_fixture", "ui_fixture"), default="human"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--host-config", type=Path)
    parser.add_argument("--timeout-seconds", type=int, choices=range(30, 1801), default=600)
    arguments = parser.parse_args()
    try:
        result = asyncio.run(_main(arguments))
    except Exception as error:
        write_json(
            arguments.state_directory / "agent-failure.json",
            object_value({"status": "blocked", "reason_codes": list(failure_codes(error))}),
        )
        print("自测代理停止: " + ",".join(failure_codes(error)))
        result = 2
    raise SystemExit(result)


if __name__ == "__main__":
    main()
