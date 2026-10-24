"""Strict mocked inventory checks; real profile acceptance is recorded separately."""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import profile_stack as profile  # noqa: E402
from scripts.selftest.io import HarnessError, write_json  # noqa: E402
from scripts.selftest.local_stack import StackBinding  # noqa: E402


def _fixture(tmp_path: Path, monkeypatch, kind: profile.Profile = "compact"):
    project, nonce = "flowtest-selftest-123456789abc", "a" * 32
    ids = {role: hashlib.sha256(role.encode()).hexdigest() for role in profile._roles(kind)}
    images = profile.DependencyImages(
        postgres="sha256:" + "1" * 64, redis="sha256:" + "2" * 64, minio="sha256:" + "3" * 64
    )
    binding = StackBinding(
        project_name=project,
        nonce=nonce,
        runtime_profile=kind,
        runner_url="http://127.0.0.1:43001",
        target_url="http://127.0.0.1:43002",
        observer_url="http://127.0.0.1:43003",
        private_subnet="172.27.9.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "4" * 64,
        fixture_image="fixture",
        fixture_image_digest="sha256:" + "5" * 64,
        source_digest="source",
        dependency_digest="dependencies",
        runner_container_id=ids["runner"],
        target_container_id=ids["target"],
        observer_container_id=ids["observer"],
        runner_volume=project + "_runner-data",
        target_volume=project + "_target-data",
    )
    private = {
        "FLOWTEST_SELFTEST_OBSERVER_TOKEN": "private-observer",
        "FLOWTEST_SELFTEST_STACK_NONCE": nonce,
        "FLOWTEST_SELFTEST_PROFILE": kind,
    }
    for side in ("RUNNER", "TARGET"):
        for name in ("KEY", "ENCRYPTION_KEY", "DB_PASSWORD", "S3_PASSWORD"):
            private[f"FLOWTEST_SELFTEST_{side}_{name}"] = side + name
    inventory, containers = {}, []
    for role, identifier in ids.items():
        side, key = role.split("-", 1)[0], role.split("-", 1)[0].upper()
        image = next(
            (value for name, value in images.model_dump().items() if role.endswith("-" + name)),
            binding.fixture_image_digest
            if role in {"mock-target", "observer"}
            else binding.candidate_image_digest,
        )
        environment = {}
        if role == "observer":
            environment["FLOWTEST_SELFTEST_OBSERVER_TOKEN"] = private[
                "FLOWTEST_SELFTEST_OBSERVER_TOKEN"
            ]
        elif role not in {"mock-target"} and not role.endswith(("-postgres", "-redis", "-minio")):
            environment = {
                "FLOWTEST_RUNTIME_PROFILE": kind,
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
        networks = {project + "_" + name: {} for name in profile._networks(role)}
        mount = profile._mount(role)
        mounts = (
            []
            if mount is None
            else [{"Type": "volume", "Name": project + "_" + mount[0], "Destination": mount[1]}]
        )
        published = {"runner": 43001, "target": 43002, "observer": 43003}
        ports = (
            {}
            if role not in published
            else {
                "8081/tcp" if role == "observer" else "8000/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": str(published[role])}
                ]
            }
        )
        inventory[identifier] = {
            "Id": identifier,
            "Image": image,
            "Config": {
                "Labels": {
                    "com.docker.compose.project": project,
                    "com.docker.compose.service": role,
                    "dev.flowtest.selftest.nonce": nonce,
                },
                "Cmd": list(profile._command(role, kind) or ()),
                "Env": [name + "=" + value for name, value in environment.items()],
            },
            "State": {
                "Running": not role.endswith("-migrate"),
                "Status": "exited" if role.endswith("-migrate") else "running",
                "ExitCode": 0,
            },
            "Mounts": mounts,
            "NetworkSettings": {"Networks": networks, "Ports": ports},
        }
        containers.append(
            profile.ProfileContainer(role=role, container_id=identifier, image_digest=image)
        )
    proof = profile.ProfileProof(
        project_name=project,
        nonce=nonce,
        runtime_profile=kind,
        compose_digest=hashlib.sha256(profile.COMPOSE.read_bytes()).hexdigest(),
        dependencies=images,
        containers=tuple(containers),
    )
    write_json(tmp_path / "profile-proof.json", proof)
    names = {name for role in ids for name in profile._networks(role)}
    for name in names:
        inventory[project + "_" + name] = {
            "Labels": {"com.docker.compose.project": project, "dev.flowtest.selftest.nonce": nonce},
            "Internal": not name.endswith("-control"),
            "IPAM": {"Config": [{"Subnet": binding.private_subnet}]},
            "Containers": {
                identifier: {}
                for role, identifier in ids.items()
                if name in profile._networks(role) and not role.endswith("-migrate")
            },
        }
    for role in ids:
        if mount := profile._mount(role):
            inventory["volume:" + project + "_" + mount[0]] = {
                "Labels": {
                    "com.docker.compose.project": project,
                    "dev.flowtest.selftest.nonce": nonce,
                }
            }

    def docker(arguments: list[str], **kwargs) -> str:
        key = (
            "volume:" + arguments[2]
            if arguments[:2] == ["volume", "inspect"]
            else arguments[2]
            if arguments[:2] == ["network", "inspect"]
            else arguments[1]
        )
        return json.dumps(inventory[key])

    monkeypatch.setattr(profile, "_docker", docker)
    return binding, private, inventory, ids


@pytest.mark.parametrize("kind", ["full", "compact"])
def test_profile_inventory_accepts_exact_separate_native_topology(
    tmp_path, monkeypatch, kind
) -> None:
    binding, private, _, ids = _fixture(tmp_path, monkeypatch, kind)
    profile.verify_profile_binding(binding, tmp_path, private)
    assert ("runner-worker-data" in ids) is (kind == "full")
    assert ("target-worker-data" in ids) is (kind == "full")
    command = profile._command("runner-worker", kind)
    assert command is not None
    assert command[-4:] == (
        "--queues=general,celery" if kind == "full" else "--queues=general,celery,data",
        "--hostname=runner-worker@%h",
        "--beat",
        "--schedule=/tmp/flowtest-selftest-beat",
    )


@pytest.mark.parametrize("kind", ["full", "compact"])
@pytest.mark.parametrize("setting", ["BINDINGS", "PRINCIPALS", "EXTRA_TEMPLATES", "PROBE_GRANTS"])
def test_profile_product_settings_are_checked_against_actual_runner_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: profile.Profile, setting: str
) -> None:
    binding, private, inventory, ids = _fixture(tmp_path, monkeypatch, kind)
    name = f"FLOWTEST_SELFTEST_{setting}"
    private[name] = '[{"id":"owned-binding"}]'
    with pytest.raises(HarnessError, match="SELFTEST_PROFILE_PRODUCT_CONFIGURATION_MISMATCH"):
        profile.verify_profile_binding(binding, tmp_path, private)
    inventory[ids["runner"]]["Config"]["Env"].append(name + "=" + private[name])
    profile.verify_profile_binding(binding, tmp_path, private)


@pytest.mark.parametrize("kind", ["full", "compact"])
def test_profile_target_recursion_depth_is_verified_from_actual_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: profile.Profile
) -> None:
    binding, private, inventory, ids = _fixture(tmp_path, monkeypatch, kind)
    inventory[ids["target"]]["Config"]["Env"] = [
        value.replace("FIXTURE_RUN_DEPTH=1", "FIXTURE_RUN_DEPTH=0")
        for value in inventory[ids["target"]]["Config"]["Env"]
    ]
    with pytest.raises(HarnessError, match="SELFTEST_PROFILE_INSTANCE_CONFIGURATION_MISMATCH"):
        profile.verify_profile_binding(binding, tmp_path, private)


@pytest.mark.parametrize("kind", ["full", "compact"])
@pytest.mark.parametrize("drift", [False, True])
def test_product_configuration_recreates_only_runner_and_retains_other_owned_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: profile.Profile,
    drift: bool,
) -> None:
    from scripts.selftest import product_profile_setup as activation

    binding, private, _, _ = _fixture(tmp_path, monkeypatch, kind)
    previous = profile.ProfileProof.model_validate_json(
        (tmp_path / "profile-proof.json").read_bytes()
    )
    state = tmp_path / "configuration"
    state.mkdir()
    commands: list[list[str]] = []
    checked: list[StackBinding] = []
    monkeypatch.setattr(
        activation, "verify_binding", lambda model, directory: checked.append(model)
    )
    monkeypatch.setattr(activation, "_replace_private_environment", lambda path, env: None)
    monkeypatch.setattr(
        activation, "_compose", lambda directory, project, shape, args, **kw: commands.append(args)
    )

    def freeze(*args, **kwargs):
        containers = tuple(
            item.model_copy(update={"container_id": "f" * 64})
            if item.role == "runner" or (drift and item.role == "target")
            else item
            for item in previous.containers
        )
        write_json(
            tmp_path / "profile-proof.json", previous.model_copy(update={"containers": containers})
        )
        return binding.model_copy(update={"runner_container_id": "f" * 64})

    monkeypatch.setattr(activation, "_freeze", freeze)
    if drift:
        with pytest.raises(HarnessError, match="SELFTEST_PRODUCT_RECONFIGURATION_RESOURCE_DRIFT"):
            activation.configure_profile_runner(binding, tmp_path, state, private)
        assert checked == [binding]
    else:
        updated = activation.configure_profile_runner(binding, tmp_path, state, private)
        assert (
            updated.runtime_profile == kind
            and updated.target_container_id == binding.target_container_id
        )
        assert updated.runner_container_id == "f" * 64
        assert checked == [binding, updated]
    assert commands == [
        [
            "up",
            "--detach",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "120",
            "runner",
        ]
    ]
    assert (
        profile.ProfileProof.model_validate_json((state / "profile-proof.before.json").read_bytes())
        == previous
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "observer_network",
        "foreign_member",
        "db_sharing",
        "queue_sharing",
        "s3_sharing",
        "observer_token",
        "worker_queue",
        "migration_failure",
        "wrong_image",
        "foreign_volume",
        "public_private_service",
    ],
)
def test_profile_inventory_rejects_cross_domain_drift_before_privileged_requests(
    tmp_path, monkeypatch, tamper
) -> None:
    binding, private, inventory, ids = _fixture(tmp_path, monkeypatch)
    target = inventory[ids["target"]]
    if tamper == "observer_network":
        inventory[ids["observer"]]["NetworkSettings"]["Networks"][
            binding.project_name + "_execution"
        ] = {}
    elif tamper == "foreign_member":
        inventory[binding.project_name + "_runner-data"]["Containers"]["foreign"] = {}
    elif tamper in {"db_sharing", "queue_sharing", "s3_sharing"}:
        name = {
            "db_sharing": "FLOWTEST_DATABASE_URL",
            "queue_sharing": "FLOWTEST_CELERY_BROKER_URL",
            "s3_sharing": "FLOWTEST_S3_ENDPOINT_URL",
        }[tamper]
        target["Config"]["Env"] = [
            value.replace("target-", "runner-") if value.startswith(name + "=") else value
            for value in target["Config"]["Env"]
        ]
    elif tamper == "observer_token":
        inventory[ids["runner-worker"]]["Config"]["Env"].append(
            "FLOWTEST_SELFTEST_OBSERVER_TOKEN=leaked"
        )
    elif tamper == "worker_queue":
        inventory[ids["runner-worker"]]["Config"]["Cmd"][-2] = "--queues=unrelated"
    elif tamper == "migration_failure":
        inventory[ids["target-migrate"]]["State"]["ExitCode"] = 1
    elif tamper == "wrong_image":
        inventory[ids["runner-postgres"]]["Image"] = "sha256:" + "0" * 64
    elif tamper == "foreign_volume":
        inventory["volume:" + binding.runner_volume]["Labels"]["dev.flowtest.selftest.nonce"] = (
            "foreign"
        )
    else:
        inventory[ids["runner-redis"]]["NetworkSettings"]["Ports"] = {
            "6379/tcp": [{"HostIp": "0.0.0.0", "HostPort": "6379"}]
        }
    with pytest.raises(HarnessError):
        profile.verify_profile_binding(binding, tmp_path, private)


def test_profile_compose_keeps_both_instance_dependencies_private_and_observer_separate() -> None:
    document = yaml.safe_load(profile.COMPOSE.read_text())
    services = document["services"]
    assert len(services) == 16
    for side in ("runner", "target"):
        for name in ("postgres", "redis", "minio"):
            service = services[side + "-" + name]
            assert service["networks"] == [side + "-data"] and "ports" not in service
        assert services[side + "-worker-data"]["profiles"] == ["full"]
        assert "OBSERVER_TOKEN" not in str(services[side]["environment"])
        assert "OBSERVER_TOKEN" not in str(services[side + "-worker"]["environment"])
    assert set(services["observer"]["networks"]) == {"management", "observer-control"}
    assert services["mock-target"]["networks"] == ["execution"]


def test_private_configuration_is_created_exclusively_with_owner_permissions(tmp_path) -> None:
    path = tmp_path / "private.env"
    profile._create_private_environment(path, {"SYNTHETIC": "value"})
    assert path.stat().st_mode & 0o077 == 0
    assert path.read_text() == "SYNTHETIC=value\n"
    with pytest.raises(FileExistsError):
        profile._create_private_environment(path, {"SYNTHETIC": "replacement"})
    assert path.read_text() == "SYNTHETIC=value\n"


def test_cleanup_refuses_foreign_nonce_before_any_down_command(tmp_path, monkeypatch) -> None:
    project, nonce = "flowtest-selftest-123456789abc", "a" * 32
    write_json(tmp_path / "ownership.json", {"project_name": project, "nonce": nonce})
    profile._create_private_environment(
        tmp_path / "private.env",
        {
            "FLOWTEST_SELFTEST_STACK_NONCE": nonce,
            "FLOWTEST_SELFTEST_PROFILE": "compact",
        },
    )

    def docker(arguments: list[str], **kwargs) -> str:
        if arguments[0] == "inspect":
            return json.dumps({"Config": {"Labels": {"dev.flowtest.selftest.nonce": "foreign"}}})
        return "foreign-container"

    downs = []
    monkeypatch.setattr(profile, "_docker", docker)
    monkeypatch.setattr(profile, "_compose", lambda *args, **kwargs: downs.append(args))
    with pytest.raises(HarnessError, match="SELFTEST_RESOURCE_OWNERSHIP_MISMATCH"):
        profile.stop(tmp_path)
    assert downs == [] and (tmp_path / "private.env").exists()
    assert not (tmp_path / "cleanup.json").exists()


def test_exact_owned_cleanup_is_idempotent_and_removes_private_material_only_after_confirmation(
    tmp_path, monkeypatch
) -> None:
    project, nonce = "flowtest-selftest-123456789abc", "a" * 32
    write_json(tmp_path / "ownership.json", {"project_name": project, "nonce": nonce})
    profile._create_private_environment(
        tmp_path / "private.env",
        {
            "FLOWTEST_SELFTEST_STACK_NONCE": nonce,
            "FLOWTEST_SELFTEST_PROFILE": "compact",
        },
    )
    downs, confirmations = [], []
    monkeypatch.setattr(profile, "_verify_owned_for_cleanup", lambda ownership: None)
    monkeypatch.setattr(profile, "_compose", lambda *args, **kwargs: downs.append(args))
    monkeypatch.setattr(profile, "_verify_removed", lambda name: confirmations.append(name))
    profile.stop(tmp_path)
    profile.stop(tmp_path)
    assert len(downs) == 1 and confirmations == [project, project]
    assert not (tmp_path / "private.env").exists()
    assert json.loads((tmp_path / "cleanup.json").read_text())["status"] == "completed"


def test_profile_cleanup_receipt_is_accepted_by_native_api_disposal(tmp_path, monkeypatch) -> None:
    from scripts.selftest import native_api_pack
    from test_selftest_native_api_disposal import pending_result
    from test_selftest_verification import COLLECTED

    binding, result = pending_result(tmp_path, monkeypatch)
    binding = binding.model_copy(update={"runtime_profile": "compact"})
    write_json(tmp_path / "stack.json", binding)
    private = profile.private_environment(tmp_path)
    private["FLOWTEST_SELFTEST_PROFILE"] = "compact"
    path = tmp_path / "private.env"
    path.write_text("".join(f"{key}={value}\n" for key, value in private.items()))
    monkeypatch.setattr(profile, "_verify_owned_for_cleanup", lambda value: None)
    monkeypatch.setattr(profile, "_compose", lambda *args, **kwargs: "")
    removals = []
    monkeypatch.setattr(profile, "_verify_removed", removals.append)
    monkeypatch.setattr(native_api_pack, "_verify_removed", removals.append)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(COLLECTED)

    monkeypatch.setattr(native_api_pack, "datetime", Clock)
    profile.stop(tmp_path)
    assert json.loads((tmp_path / "cleanup.json").read_text()) == {
        "project_name": binding.project_name,
        "status": "completed",
    }
    sealed = native_api_pack.finalize_disposable_cleanup(
        result, binding=binding, stack_directory=tmp_path, output_dir=tmp_path / "finalized"
    )
    assert sealed.report.batch_verdict == "passed" and sealed.report.exit_code == 0
    assert removals == [binding.project_name, binding.project_name]
