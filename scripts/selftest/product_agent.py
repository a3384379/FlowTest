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
    lease_body,
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
            target_cleanup = _target_cleanup_client(scope, stack, boot)
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
            if role == "harness" and await _reconcile_ready(machine, batch, state_directory):
                return 1
            recover_staged = (
                role == "harness"
                and batch.phase in {"generating", "awaiting_review"}
                and (state_directory / str(batch.id) / "materialized-receipt.json").is_file()
            )
            actionable = (role == "harness" and (batch.phase == "pending" or recover_staged)) or (
                role == "observer" and batch.phase == "running"
            )
            if actionable and not _host_ready(batch, host_config, state_directory):
                continue
            if role == "harness" and (batch.phase == "pending" or recover_staged):
                task = (
                    await _resume_staged(machine, batch, state_directory)
                    if recover_staged
                    else await claim(
                        machine,
                        config.project_id,
                        batch.id,
                        batch.revision,
                        state_directory,
                    )
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


def _target_cleanup_client(
    scope: AsyncExitStack, stack: StackBinding, boot: BootstrapResult
) -> PublicAPI | None:
    if not boot.credentials.target_cleanup_token:
        return None
    client = PublicAPI(
        stack.target_url,
        boot.credentials.target_cleanup_token,
        str(boot.installation.target_organization_id),
    )
    scope.push_async_callback(client.close)
    return client


async def _resume_staged(
    machine: PublicAPI, batch: BatchResponse, directory: Path
) -> AgentTaskResponse:
    task = _owned_staged_task(batch, directory)
    path = directory / str(batch.id) / "private-lease.json"
    renewed = AgentTaskResponse.model_validate(
        await machine.object(
            "POST",
            f"{agent_root(batch.project_id)}/runs/{batch.id}/lease",
            object_value(lease_body(task).model_dump(mode="json")),
        )
    )
    write_json(path, renewed)
    return renewed


def _owned_staged_task(batch: BatchResponse, directory: Path) -> AgentTaskResponse:
    from scripts.selftest.product_agent_client import staged_receipt

    task_directory = directory / str(batch.id)
    path = task_directory / "private-lease.json"
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise HarnessError("SELFTEST_AGENT_RUNTIME_FILE_PERMISSIONS")
    task = AgentTaskResponse.model_validate(read_json(path))
    if (
        task.task_id != batch.id
        or task.project_id != batch.project_id
        or task.binding_id != batch.binding_id
        or task.batch is None
        or task.batch.manifest_digest != batch.manifest_digest
        or staged_receipt(task, task_directory) is None
    ):
        raise HarnessError("SELFTEST_MATERIALIZED_LOCAL_RECEIPT_CHANGED")
    return task


async def _reconcile_ready(machine: PublicAPI, batch: BatchResponse, directory: Path) -> bool:
    from scripts.selftest.product_agent_client import finalize_materialization

    task_directory = directory / str(batch.id)
    if (
        batch.phase != "ready"
        or not (task_directory / "materialized-finalization.json").is_file()
        or (task_directory / "materialized-acknowledged.json").exists()
    ):
        return False
    task = _owned_staged_task(batch, directory)
    result = await finalize_materialization(machine, task, task_directory)
    if result.id != batch.id or result.resource_digest != batch.resource_digest:
        raise HarnessError("SELFTEST_MATERIALIZED_LOCAL_RECEIPT_CHANGED")
    return True


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
