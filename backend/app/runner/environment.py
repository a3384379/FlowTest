import asyncio
import os
from uuid import UUID

import httpx

from app.core.config import settings
from app.domain.environment_lab import (
    EnvironmentEndpoint,
    EnvironmentRuntimeError,
    EnvironmentSeedDefinition,
    EnvironmentSeedEvidence,
    EnvironmentServiceDefinition,
    EnvironmentTemplateManifest,
    HealthCheckKind,
    ProvisionedEnvironment,
    SeedProfile,
)


class ControlledDockerEnvironmentRuntime:
    """Runs typed templates with fixed Docker CLI operations; no user command is accepted."""

    async def provision(
        self, instance_id: UUID, manifest: EnvironmentTemplateManifest
    ) -> ProvisionedEnvironment:
        runtime_name = _runtime_name(instance_id)
        network_name = _network_name(runtime_name)
        await _create_network(instance_id, runtime_name, network_name)
        for service in _ordered_services(manifest.services):
            await _start_service(instance_id, runtime_name, network_name, service)
        endpoints = await self._resolve_endpoints(runtime_name, manifest)
        await self._wait_until_healthy(manifest, endpoints)
        return ProvisionedEnvironment(
            runtime_name=runtime_name,
            endpoints=endpoints,
            evidence={
                "manifest_sha256": manifest.sha256,
                "network_scope": "isolated_dind_bridge",
                "orchestrator": "controlled_docker_cli_v1",
                "service_count": len(manifest.services),
            },
        )

    async def apply_seeds(
        self,
        provisioned: ProvisionedEnvironment,
        seeds: tuple[EnvironmentSeedDefinition, ...],
    ) -> tuple[EnvironmentSeedEvidence, ...]:
        endpoints = {endpoint.service: endpoint for endpoint in provisioned.endpoints}
        evidence: list[EnvironmentSeedEvidence] = []
        async with httpx.AsyncClient(follow_redirects=False) as client:
            for seed in seeds:
                endpoint = endpoints[seed.service]
                if seed.profile is not SeedProfile.HTTP_GET_V1:
                    raise EnvironmentRuntimeError(
                        "ENVIRONMENT_SEED_PROFILE_UNSUPPORTED",
                        "环境 Seed Profile 不受支持",
                    )
                try:
                    response = await client.get(
                        f"{endpoint.url}{seed.path}",
                        timeout=settings.environment_health_request_timeout_seconds,
                    )
                except httpx.HTTPError as error:
                    raise EnvironmentRuntimeError(
                        "ENVIRONMENT_SEED_FAILED",
                        "环境预定义 Seed 执行失败",
                    ) from error
                if response.status_code >= 400:
                    raise EnvironmentRuntimeError(
                        "ENVIRONMENT_SEED_FAILED",
                        "环境预定义 Seed 返回失败状态",
                    )
                evidence.append(
                    EnvironmentSeedEvidence(
                        profile=seed.profile,
                        service=seed.service,
                        path=seed.path,
                        status_code=response.status_code,
                    )
                )
        return tuple(evidence)

    async def cleanup(self, instance_id: UUID) -> None:
        runtime_name = _runtime_name(instance_id)
        filters = ("container", "network", "volume")
        for resource in filters:
            identifiers = await _resource_identifiers(resource, runtime_name)
            if not identifiers:
                continue
            await _remove_resources(resource, identifiers)

    async def _resolve_endpoints(
        self,
        runtime_name: str,
        manifest: EnvironmentTemplateManifest,
    ) -> tuple[EnvironmentEndpoint, ...]:
        endpoints: list[EnvironmentEndpoint] = []
        for service in manifest.services:
            output = await _run_docker(
                "port",
                _container_name(runtime_name, service.name),
                f"{service.internal_port}/tcp",
                timeout_seconds=30,
            )
            port = _published_port(output)
            endpoints.append(
                EnvironmentEndpoint(
                    service=service.name,
                    url=f"http://{settings.environment_runtime_host}:{port}",
                    internal_port=service.internal_port,
                )
            )
        return tuple(endpoints)

    async def _wait_until_healthy(
        self,
        manifest: EnvironmentTemplateManifest,
        endpoints: tuple[EnvironmentEndpoint, ...],
    ) -> None:
        by_name = {endpoint.service: endpoint for endpoint in endpoints}
        for service in _ordered_services(manifest.services):
            await _wait_for_service(service, by_name[service.name])


async def _create_network(instance_id: UUID, runtime_name: str, network_name: str) -> None:
    await _run_docker(
        "network",
        "create",
        "--driver",
        "bridge",
        "--label",
        f"flowtest.environment.instance={instance_id}",
        "--label",
        f"flowtest.environment.runtime={runtime_name}",
        network_name,
        timeout_seconds=30,
    )


async def _start_service(
    instance_id: UUID,
    runtime_name: str,
    network_name: str,
    service: EnvironmentServiceDefinition,
) -> None:
    await _run_docker(
        "image",
        "pull",
        service.image,
        timeout_seconds=settings.environment_provision_timeout_seconds,
    )
    arguments = _service_arguments(instance_id, runtime_name, network_name, service)
    await _run_docker(
        "run",
        *arguments,
        service.image,
        timeout_seconds=settings.environment_provision_timeout_seconds,
    )


def _service_arguments(
    instance_id: UUID,
    runtime_name: str,
    network_name: str,
    service: EnvironmentServiceDefinition,
) -> tuple[str, ...]:
    arguments = [
        "--detach",
        "--name",
        _container_name(runtime_name, service.name),
        "--network",
        network_name,
        "--network-alias",
        service.name,
        "--publish",
        f"0:{service.internal_port}",
        "--user",
        f"{service.user_id}:{service.group_id}",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(service.pids_limit),
        "--cpus",
        f"{service.cpu_millicores / 1000:.3f}",
        "--memory",
        f"{service.memory_megabytes}m",
        "--restart",
        "no",
        "--stop-timeout",
        "5",
        "--tmpfs",
        "/tmp:size=64m,mode=1777",  # noqa: S108 - isolated container tmpfs
        "--label",
        f"flowtest.environment.instance={instance_id}",
        "--label",
        f"flowtest.environment.runtime={runtime_name}",
        "--label",
        f"flowtest.environment.service={service.name}",
    ]
    for variable in service.environment:
        arguments.extend(("--env", f"{variable.name}={variable.value}"))
    return tuple(arguments)


async def _wait_for_service(
    service: EnvironmentServiceDefinition, endpoint: EnvironmentEndpoint
) -> None:
    check = service.health_check
    for attempt in range(check.maximum_attempts):
        if await _health_check_passes(service, endpoint):
            return
        if attempt + 1 < check.maximum_attempts:
            await asyncio.sleep(check.interval_seconds)
    raise EnvironmentRuntimeError(
        "ENVIRONMENT_HEALTH_CHECK_FAILED",
        f"环境服务 {service.name} 健康检查失败",
    )


async def _health_check_passes(
    service: EnvironmentServiceDefinition, endpoint: EnvironmentEndpoint
) -> bool:
    check = service.health_check
    if check.kind is HealthCheckKind.TCP:
        return await _tcp_health_check(endpoint, check.timeout_seconds)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.get(
                f"{endpoint.url}{check.path}",
                timeout=check.timeout_seconds,
            )
    except httpx.HTTPError:
        return False
    return response.status_code == check.expected_status


async def _tcp_health_check(endpoint: EnvironmentEndpoint, timeout_seconds: float) -> bool:
    host, port_text = endpoint.url.removeprefix("http://").rsplit(":", 1)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port_text)),
            timeout=timeout_seconds,
        )
        del reader
    except (OSError, TimeoutError, ValueError):
        return False
    writer.close()
    await writer.wait_closed()
    return True


async def _resource_identifiers(resource: str, runtime_name: str) -> tuple[str, ...]:
    noun = "ps" if resource == "container" else f"{resource} ls"
    arguments = noun.split()
    output = await _run_docker(
        *arguments,
        "--quiet",
        "--filter",
        f"label=flowtest.environment.runtime={runtime_name}",
        timeout_seconds=30,
    )
    return tuple(line.strip() for line in output.splitlines() if line.strip())


async def _remove_resources(resource: str, identifiers: tuple[str, ...]) -> None:
    command = {
        "container": ("rm", "--force", "--volumes"),
        "network": ("network", "rm"),
        "volume": ("volume", "rm", "--force"),
    }[resource]
    await _run_docker(
        *command,
        *identifiers,
        timeout_seconds=settings.environment_cleanup_timeout_seconds,
    )


async def _run_docker(
    *arguments: str,
    timeout_seconds: int,
    check: bool = True,
) -> str:
    environment = os.environ.copy()
    process = await asyncio.create_subprocess_exec(
        "docker",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as error:
        process.kill()
        await process.communicate()
        raise EnvironmentRuntimeError(
            "ENVIRONMENT_RUNTIME_TIMEOUT",
            "受控环境 Runner 命令超时",
        ) from error
    if check and process.returncode != 0:
        del stderr
        raise EnvironmentRuntimeError(
            "ENVIRONMENT_RUNTIME_FAILED",
            "受控环境 Runner 执行失败",
        )
    return stdout.decode(errors="replace").strip()


def _published_port(output: str) -> int:
    try:
        port = int(output.splitlines()[0].rsplit(":", 1)[1])
    except (IndexError, ValueError) as error:
        raise EnvironmentRuntimeError(
            "ENVIRONMENT_ENDPOINT_MISSING",
            "环境服务未返回发布端口",
        ) from error
    if not 1 <= port <= 65535:
        raise EnvironmentRuntimeError(
            "ENVIRONMENT_ENDPOINT_INVALID",
            "环境服务发布端口无效",
        )
    return port


def _ordered_services(
    services: tuple[EnvironmentServiceDefinition, ...],
) -> tuple[EnvironmentServiceDefinition, ...]:
    remaining = {service.name: service for service in services}
    ordered: list[EnvironmentServiceDefinition] = []
    while remaining:
        selected = next(
            service
            for service in remaining.values()
            if all(dependency not in remaining for dependency in service.depends_on)
        )
        ordered.append(selected)
        remaining.pop(selected.name)
    return tuple(ordered)


def _runtime_name(instance_id: UUID) -> str:
    return f"flowtest-env-{instance_id.hex}"


def _network_name(runtime_name: str) -> str:
    return f"{runtime_name}-network"


def _container_name(runtime_name: str, service_name: str) -> str:
    return f"{runtime_name}-{service_name}"
