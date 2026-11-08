"""Owned Full/Compact engine acceptance; this is not complete release acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field
from scripts.selftest.bootstrap_journal import bootstrap_lock
from scripts.selftest.contracts import Contract
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    object_value,
    objects_value,
    read_json,
    write_json,
)
from scripts.selftest.local_stack import (
    ROOT,
    BuildReceipt,
    StackBinding,
    StackOwnership,
    _docker,
    _new_environment,
    _verify_binding_identity,
    _verify_labels,
    _verify_published_port,
    _verify_removed,
    private_environment,
    verify_binding,
)

Profile = Literal["full", "compact"]
COMPOSE = ROOT / "deploy/selftest/profile-compose.yaml"


class DependencyImages(Contract):
    postgres: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    redis: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    minio: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ProfileContainer(Contract):
    role: str = Field(
        pattern=r"^(runner|target)(-postgres|-redis|-minio|-worker|-worker-data|-migrate)?$|^(mock-target|observer)$"
    )
    container_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ProfileProof(Contract):
    schema_version: Literal["flowtest-selftest-profile-v1"] = "flowtest-selftest-profile-v1"
    project_name: str
    nonce: str
    runtime_profile: Profile
    compose_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependencies: DependencyImages
    containers: tuple[ProfileContainer, ...] = Field(min_length=14, max_length=16)


def _compose(
    directory: Path,
    project: str,
    profile: Profile,
    arguments: list[str],
    *,
    timeout: int = 60,
) -> str:
    active = ["--profile", "full"] if profile == "full" else []
    return _docker(
        [
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(directory / "private.env"),
            "--file",
            str(COMPOSE),
            *active,
            *arguments,
        ],
        timeout=timeout,
        log_path=(directory / f"profile-{arguments[0]}.log")
        if arguments[0] in {"up", "down"}
        else None,
    )


def _image(reference: str) -> str:
    return _docker(["image", "inspect", reference, "--format", "{{.Id}}"])


def _roles(profile: Profile) -> tuple[str, ...]:
    suffixes: tuple[str, ...] = ("", "-postgres", "-redis", "-minio", "-migrate", "-worker")
    if profile == "full":
        suffixes = (*suffixes, "-worker-data")
    return (
        *tuple(f"{side}{suffix}" for side in ("runner", "target") for suffix in suffixes),
        "mock-target",
        "observer",
    )


def _networks(role: str) -> tuple[str, ...]:
    if role == "observer":
        return "management", "observer-control"
    if role == "mock-target":
        return ("execution",)
    side = role.split("-", 1)[0]
    if role.endswith(("-postgres", "-redis", "-minio", "-migrate")):
        return (f"{side}-data",)
    if role in {"runner", "target"}:
        return "execution", f"{side}-data", f"{side}-control"
    return "execution", f"{side}-data"


def _mount(role: str) -> tuple[str, str] | None:
    side = role.split("-", 1)[0]
    if role in {"observer", "mock-target"}:
        return "fixture-journal", "/journal"
    if role.endswith("-postgres"):
        return f"{side}-data", "/var/lib/postgresql/data"
    if role.endswith("-redis"):
        return f"{side}-queue", "/data"
    if role.endswith("-minio"):
        return f"{side}-artifacts", "/data"
    return None


def _command(role: str, profile: Profile) -> tuple[str, ...] | None:
    if role.endswith("-migrate"):
        return "alembic", "upgrade", "head"
    if "-worker" in role:
        queues = (
            "data"
            if role.endswith("-worker-data")
            else "general,celery"
            if profile == "full"
            else "general,celery,data"
        )
        command: tuple[str, ...] = (
            "celery",
            "-A",
            "app.tasking.celery_app.celery_app",
            "worker",
            "--loglevel=WARNING",
            "--concurrency=1",
            f"--queues={queues}",
            f"--hostname={role}@%h",
        )
        if not role.endswith("-worker-data"):
            command += ("--beat", "--schedule=/tmp/flowtest-selftest-beat")
        return command
    if role in {"runner", "target"}:
        return (
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",  # noqa: S104 -- container only; published listener is loopback-bound.
            "--port",
            "8000",
            "--no-access-log",
        )
    return None


def _environment(inspection: JsonObject) -> dict[str, str]:
    values = object_value(inspection["Config"])["Env"]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise HarnessError("SELFTEST_PROFILE_ENVIRONMENT_INVALID")
    return dict(str(value).split("=", 1) for value in values if "=" in str(value))


def _verify_target_auth_environment(
    role: str, environment: dict[str, str], private: dict[str, str]
) -> None:
    if role.split("-", 1)[0] == "target" and not role.endswith(("-postgres", "-redis", "-minio")):
        from scripts.selftest.target_auth_policy import verify_target_token_environment

        verify_target_token_environment(environment, private)


def _target_binding_environment(role: str, private: dict[str, str]) -> dict[str, str]:
    if role == "target" and "FLOWTEST_SELFTEST_TARGET_BINDINGS" in private:
        return {"FLOWTEST_SELFTEST_BINDINGS": private["FLOWTEST_SELFTEST_TARGET_BINDINGS"]}
    return {}


def _verify_environment(
    role: str, inspection: JsonObject, binding: StackBinding, private: dict[str, str]
) -> None:
    environment = _environment(inspection)
    _verify_target_auth_environment(role, environment, private)
    if role == "observer":
        if (
            environment.get("FLOWTEST_SELFTEST_OBSERVER_TOKEN")
            != private["FLOWTEST_SELFTEST_OBSERVER_TOKEN"]
        ):
            raise HarnessError("SELFTEST_PROFILE_OBSERVER_CREDENTIAL_MISMATCH")
        return
    if "FLOWTEST_SELFTEST_OBSERVER_TOKEN" in environment:
        raise HarnessError("SELFTEST_OBSERVER_CREDENTIAL_EXPOSED")
    side = role.split("-", 1)[0]
    if role in {"mock-target"} or role.endswith(("-postgres", "-redis", "-minio")):
        return
    key = side.upper()
    expected = {
        "FLOWTEST_RUNTIME_PROFILE": binding.runtime_profile,
        "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH": "1" if side == "target" else "0",
        "FLOWTEST_SECRET_KEY": private[f"FLOWTEST_SELFTEST_{key}_KEY"],
        "FLOWTEST_DATA_ENCRYPTION_KEY": private[f"FLOWTEST_SELFTEST_{key}_ENCRYPTION_KEY"],
        "FLOWTEST_DATABASE_URL": f"postgresql+asyncpg://flowtest:{private[f'FLOWTEST_SELFTEST_{key}_DB_PASSWORD']}@{side}-postgres:5432/flowtest",
        "FLOWTEST_REDIS_URL": f"redis://{side}-redis:6379/0",
        "FLOWTEST_CELERY_BROKER_URL": f"redis://{side}-redis:6379/1",
        "FLOWTEST_CELERY_RESULT_BACKEND": f"redis://{side}-redis:6379/2",
        "FLOWTEST_S3_ENDPOINT_URL": f"http://{side}-minio:9000",
        "FLOWTEST_S3_SECRET_KEY": private[f"FLOWTEST_SELFTEST_{key}_S3_PASSWORD"],
    }
    if role == "runner":
        for name in ("BINDINGS", "PRINCIPALS", "EXTRA_TEMPLATES", "PROBE_GRANTS"):
            setting = f"FLOWTEST_SELFTEST_{name}"
            if environment.get(setting, "[]") != private.get(setting, "[]"):
                raise HarnessError("SELFTEST_PROFILE_PRODUCT_CONFIGURATION_MISMATCH")
        if "FLOWTEST_SELFTEST_CORS_ORIGINS" in private:
            expected["FLOWTEST_CORS_ORIGINS"] = private["FLOWTEST_SELFTEST_CORS_ORIGINS"]
    expected.update(_target_binding_environment(role, private))
    if any(environment.get(name) != value for name, value in expected.items()):
        raise HarnessError("SELFTEST_PROFILE_INSTANCE_CONFIGURATION_MISMATCH")


def _inspection(identifier: str) -> JsonObject:
    return object_value(json.loads(_docker(["inspect", identifier, "--format", "{{json .}}"])))


def _verify_container(
    binding: StackBinding, container: ProfileContainer, private: dict[str, str]
) -> JsonObject:
    inspected = _inspection(container.container_id)
    config, state = object_value(inspected["Config"]), object_value(inspected["State"])
    labels = object_value(config["Labels"])
    _verify_labels(binding, labels)
    if (
        labels.get("com.docker.compose.service") != container.role
        or inspected["Image"] != container.image_digest
    ):
        raise HarnessError("SELFTEST_PROFILE_CONTAINER_IDENTITY_MISMATCH")
    if container.role.endswith("-migrate"):
        if state.get("ExitCode") != 0 or state.get("Status") != "exited":
            raise HarnessError("SELFTEST_PROFILE_MIGRATION_NOT_COMPLETED")
    elif state.get("Running") is not True:
        raise HarnessError("SELFTEST_PROFILE_CONTAINER_NOT_RUNNING")
    profile: Profile = "full" if binding.runtime_profile == "full" else "compact"
    command = _command(container.role, profile)
    if command is not None and config.get("Cmd") != list(command):
        raise HarnessError("SELFTEST_PROFILE_COMMAND_MISMATCH")
    _verify_environment(container.role, inspected, binding, private)
    networks = object_value(object_value(inspected["NetworkSettings"])["Networks"])
    if set(networks) != {f"{binding.project_name}_{name}" for name in _networks(container.role)}:
        raise HarnessError("SELFTEST_PROFILE_CONTAINER_NETWORK_MISMATCH")
    _verify_mounts(binding, container.role, inspected)
    url = {
        "runner": binding.runner_url,
        "target": binding.target_url,
        "observer": binding.observer_url,
    }.get(container.role)
    if url is not None:
        _verify_published_port(
            inspected, url, "8081/tcp" if container.role == "observer" else "8000/tcp"
        )
    elif any(object_value(object_value(inspected["NetworkSettings"])["Ports"]).values()):
        raise HarnessError("SELFTEST_PROFILE_PRIVATE_SERVICE_PUBLISHED")
    return inspected


def _verify_mounts(binding: StackBinding, role: str, inspection: JsonObject) -> None:
    mounts, expected = objects_value(inspection["Mounts"]), _mount(role)
    if expected is None:
        if mounts:
            raise HarnessError("SELFTEST_PROFILE_UNEXPECTED_MOUNT")
        return
    name, destination = expected
    if len(mounts) != 1 or (
        mounts[0].get("Type"),
        mounts[0].get("Name"),
        mounts[0].get("Destination"),
    ) != ("volume", f"{binding.project_name}_{name}", destination):
        raise HarnessError("SELFTEST_PROFILE_STORAGE_MISMATCH")


def verify_profile_binding(binding: StackBinding, directory: Path, private: dict[str, str]) -> None:
    proof = ProfileProof.model_validate(read_json(directory / "profile-proof.json"))
    if (
        proof.project_name,
        proof.nonce,
        proof.runtime_profile,
        proof.compose_digest,
    ) != (
        binding.project_name,
        binding.nonce,
        binding.runtime_profile,
        hashlib.sha256(COMPOSE.read_bytes()).hexdigest(),
    ):
        raise HarnessError("SELFTEST_PROFILE_PROOF_MISMATCH")
    if {entry.role for entry in proof.containers} != set(_roles(proof.runtime_profile)) or len(
        {entry.container_id for entry in proof.containers}
    ) != len(proof.containers):
        raise HarnessError("SELFTEST_PROFILE_RESOURCE_SET_MISMATCH")
    identities = {entry.role: entry.container_id for entry in proof.containers}
    if tuple(identities[role] for role in ("runner", "target", "observer")) != (
        binding.runner_container_id,
        binding.target_container_id,
        binding.observer_container_id,
    ):
        raise HarnessError("SELFTEST_PROFILE_BINDING_CONTAINER_MISMATCH")
    images = proof.dependencies.model_dump()
    inspections: dict[str, JsonObject] = {}
    for entry in proof.containers:
        expected = next(
            (value for key, value in images.items() if entry.role.endswith("-" + key)),
            binding.fixture_image_digest
            if entry.role in {"observer", "mock-target"}
            else binding.candidate_image_digest,
        )
        if entry.image_digest != expected:
            raise HarnessError("SELFTEST_PROFILE_IMAGE_MISMATCH")
        inspections[entry.container_id] = _verify_container(binding, entry, private)
    _verify_networks(binding, proof, inspections)
    _verify_volumes(binding, proof)


def _verify_networks(
    binding: StackBinding, proof: ProfileProof, inspections: dict[str, JsonObject]
) -> None:
    names = {name for entry in proof.containers for name in _networks(entry.role)}
    for name in names:
        inspected = object_value(
            json.loads(
                _docker(
                    [
                        "network",
                        "inspect",
                        f"{binding.project_name}_{name}",
                        "--format",
                        "{{json .}}",
                    ]
                )
            )
        )
        _verify_labels(binding, object_value(inspected["Labels"]))
        if inspected["Internal"] is not (not name.endswith("-control")):
            raise HarnessError("SELFTEST_PROFILE_NETWORK_ISOLATION_MISMATCH")
        expected = {
            entry.container_id
            for entry in proof.containers
            if name in _networks(entry.role)
            and object_value(inspections[entry.container_id]["State"]).get("Running") is True
        }
        if set(object_value(inspected.get("Containers", {}))) != expected:
            raise HarnessError("SELFTEST_PROFILE_NETWORK_MEMBERSHIP_MISMATCH")
        if (
            name == "execution"
            and objects_value(object_value(inspected["IPAM"])["Config"])[0].get("Subnet")
            != binding.private_subnet
        ):
            raise HarnessError("SELFTEST_PROFILE_SUBNET_MISMATCH")


def _verify_volumes(binding: StackBinding, proof: ProfileProof) -> None:
    names = {mount[0] for entry in proof.containers if (mount := _mount(entry.role)) is not None}
    if (binding.runner_volume, binding.target_volume) != (
        f"{binding.project_name}_runner-data",
        f"{binding.project_name}_target-data",
    ):
        raise HarnessError("SELFTEST_PROFILE_VOLUME_BINDING_MISMATCH")
    for name in names:
        inspection = object_value(
            json.loads(
                _docker(
                    [
                        "volume",
                        "inspect",
                        f"{binding.project_name}_{name}",
                        "--format",
                        "{{json .}}",
                    ]
                )
            )
        )
        _verify_labels(binding, object_value(inspection["Labels"]))


def start(
    directory: Path,
    source_stack_directory: Path,
    profile: Profile,
    *,
    postgres_image: str = "postgres:17.6-alpine",
    redis_image: str = "redis:8.2.1-alpine",
    minio_image: str = (
        "cgr.dev/chainguard/minio@sha256:"
        "bd014394a80898e68c149f2311fdf8d5a2c2f3bb2c33b9327ae6d02b4b065ae1"
    ),
    target_access_token_minutes: int = 15,
) -> StackBinding:
    source = StackBinding.model_validate(read_json(source_stack_directory / "stack.json"))
    verify_binding(source, source_stack_directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    project, nonce = f"flowtest-selftest-{uuid4().hex[:12]}", secrets.token_hex(16)
    dependencies = DependencyImages(
        postgres=_image(postgres_image),
        redis=_image(redis_image),
        minio=_image(minio_image),
    )
    environment = _new_environment(
        source.candidate_image,
        project,
        nonce,
        target_access_token_minutes=target_access_token_minutes,
    )
    environment.update(
        {
            "FLOWTEST_SELFTEST_PROFILE": profile,
            "FLOWTEST_SELFTEST_CANDIDATE_IMAGE": source.candidate_image_digest,
            "FLOWTEST_SELFTEST_FIXTURE_IMAGE": source.fixture_image_digest,
            "FLOWTEST_SELFTEST_WORKER_QUEUES": "general,celery"
            if profile == "full"
            else "general,celery,data",
        }
    )
    if source.candidate_source is not None:
        environment["FLOWTEST_SELFTEST_BUILD_ROOT"] = source.candidate_source
    for name, identity in dependencies.model_dump().items():
        environment[f"FLOWTEST_SELFTEST_{name.upper()}_IMAGE"] = identity
    for side in ("RUNNER", "TARGET"):
        for kind in ("DB", "S3"):
            environment[f"FLOWTEST_SELFTEST_{side}_{kind}_PASSWORD"] = secrets.token_hex(24)
    write_json(
        directory / "ownership.json",
        StackOwnership(project_name=project, nonce=nonce).model_dump(mode="json"),
    )
    _create_private_environment(directory / "private.env", environment)
    (directory / "profile-compose.frozen.yaml").write_bytes(COMPOSE.read_bytes())
    receipt = BuildReceipt(
        source_digest=source.source_digest,
        candidate_source=source.candidate_source,
        dependency_digest=source.dependency_digest,
        candidate_image_digest=source.candidate_image_digest,
        fixture_image_digest=source.fixture_image_digest,
    )
    write_json(directory / "build-receipt.json", receipt.model_dump(mode="json"))
    _compose(
        directory,
        project,
        profile,
        ["up", "--detach", "--wait", "--wait-timeout", "180"],
        timeout=240,
    )
    return _freeze(directory, source, project, nonce, profile, dependencies, environment)


def _create_private_environment(path: Path, environment: dict[str, str]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("".join(f"{key}={value}\n" for key, value in environment.items()))
        output.flush()
        os.fsync(output.fileno())


def _freeze(
    directory: Path,
    source: StackBinding,
    project: str,
    nonce: str,
    profile: Profile,
    dependencies: DependencyImages,
    environment: dict[str, str],
) -> StackBinding:
    containers = []
    for role in _roles(profile):
        identifier = _compose(directory, project, profile, ["ps", "--all", "--quiet", role])
        inspected = _inspection(identifier)
        containers.append(
            ProfileContainer(
                role=role,
                container_id=str(inspected["Id"]),
                image_digest=str(inspected["Image"]),
            )
        )
    identifiers = {entry.role: entry.container_id for entry in containers}
    proof = ProfileProof(
        project_name=project,
        nonce=nonce,
        runtime_profile=profile,
        compose_digest=hashlib.sha256(COMPOSE.read_bytes()).hexdigest(),
        dependencies=dependencies,
        containers=tuple(containers),
    )
    binding = source.model_copy(
        update={
            "project_name": project,
            "nonce": nonce,
            "runtime_profile": profile,
            "runner_url": f"http://127.0.0.1:{environment['FLOWTEST_SELFTEST_RUNNER_PORT']}",
            "target_url": f"http://127.0.0.1:{environment['FLOWTEST_SELFTEST_TARGET_PORT']}",
            "observer_url": f"http://127.0.0.1:{environment['FLOWTEST_SELFTEST_OBSERVER_PORT']}",
            "private_subnet": environment["FLOWTEST_SELFTEST_SUBNET"],
            "candidate_image": source.candidate_image_digest,
            "fixture_image": source.fixture_image_digest,
            "runner_container_id": identifiers["runner"],
            "target_container_id": identifiers["target"],
            "observer_container_id": identifiers["observer"],
            "runner_volume": f"{project}_runner-data",
            "target_volume": f"{project}_target-data",
        }
    )
    write_json(directory / "profile-proof.json", proof.model_dump(mode="json"))
    write_json(directory / "stack.json", binding.model_dump(mode="json"))
    from scripts.selftest.target_auth_policy import freeze_target_auth_policy

    freeze_target_auth_policy(directory, project, nonce, environment)
    verify_binding(binding, directory)
    return binding


def stop(directory: Path) -> None:
    ownership = StackOwnership.model_validate(read_json(directory / "ownership.json"))
    with bootstrap_lock(directory, ownership.nonce):
        if not (directory / "private.env").exists() and (directory / "cleanup.json").exists():
            _verify_removed(ownership.project_name)
            return
        private = private_environment(directory)
        if private.get("FLOWTEST_SELFTEST_STACK_NONCE") != ownership.nonce:
            raise HarnessError("SELFTEST_BINDING_NONCE_MISMATCH")
        profile = private.get("FLOWTEST_SELFTEST_PROFILE")
        if profile not in {"full", "compact"}:
            raise HarnessError("SELFTEST_PROFILE_REQUIRED")
        _verify_owned_for_cleanup(ownership)
        _compose(
            directory,
            ownership.project_name,
            "full" if profile == "full" else "compact",
            ["down", "--volumes", "--timeout", "15"],
            timeout=90,
        )
        _verify_removed(ownership.project_name)
        write_json(
            directory / "cleanup.json",
            {
                "project_name": ownership.project_name,
                "status": "completed",
            },
        )
        (directory / "private.env").unlink()


def _verify_owned_for_cleanup(ownership: StackOwnership) -> None:
    inventories = (
        ("container", ["ps", "--all", "--quiet"]),
        ("volume", ["volume", "ls", "--quiet"]),
        ("network", ["network", "ls", "--quiet"]),
    )
    for kind, command in inventories:
        identifiers = _docker(
            [
                *command,
                "--filter",
                f"label=com.docker.compose.project={ownership.project_name}",
            ]
        ).splitlines()
        for identifier in identifiers:
            arguments = (
                ["inspect", identifier] if kind == "container" else [kind, "inspect", identifier]
            )
            inspected = object_value(json.loads(_docker([*arguments, "--format", "{{json .}}"])))
            labels = (
                object_value(object_value(inspected["Config"])["Labels"])
                if kind == "container"
                else object_value(inspected["Labels"])
            )
            if labels.get("dev.flowtest.selftest.nonce") != ownership.nonce:
                raise HarnessError("SELFTEST_RESOURCE_OWNERSHIP_MISMATCH")


def main() -> None:
    parser = argparse.ArgumentParser(description="隔离 Full/Compact 原生引擎验收栈")
    parser.add_argument("action", choices=("start", "verify", "stop"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source-stack-directory", type=Path)
    parser.add_argument("--profile", choices=("full", "compact"), default="compact")
    parser.add_argument("--target-access-token-minutes", type=int, choices=range(1, 61), default=15)
    arguments = parser.parse_args()
    if arguments.action == "start":
        if arguments.source_stack_directory is None:
            parser.error("start 需要 --source-stack-directory")
        start(
            arguments.directory,
            arguments.source_stack_directory,
            arguments.profile,
            target_access_token_minutes=arguments.target_access_token_minutes,
        )
    elif arguments.action == "stop":
        stop(arguments.directory)
    else:
        binding = StackBinding.model_validate(read_json(arguments.directory / "stack.json"))
        _verify_binding_identity(binding, arguments.directory)
        verify_binding(binding, arguments.directory)


if __name__ == "__main__":
    main()
