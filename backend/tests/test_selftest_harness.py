"""Harness unit checks; mocked transport and Docker inventory are not E2E evidence."""

import hashlib
import ipaddress
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import bootstrap as bootstrap_module  # noqa: E402
from scripts.selftest import local_stack  # noqa: E402
from scripts.selftest.bootstrap import (  # noqa: E402
    Installation,
    _observer_credential,
    _validate_viewer,
    _viewer_credentials,
)
from scripts.selftest.bootstrap_journal import BootstrapJournal, bootstrap_lock  # noqa: E402
from scripts.selftest.io import HarnessError, PublicAPI, write_json  # noqa: E402
from scripts.selftest.local_stack import StackBinding  # noqa: E402


async def test_public_api_prefix_and_organization_header_are_exact() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "value"})

    api = PublicAPI(
        "http://isolated.example", "private-token", transport=httpx.MockTransport(respond)
    )
    observer = PublicAPI(
        "http://observer.example/", api_prefix="", transport=httpx.MockTransport(respond)
    )
    try:
        api.set_organization("organization-1")
        await api.object("GET", "/projects")
        await observer.object("GET", "/selftest/journal")
    finally:
        await api.close()
        await observer.close()
    assert requests[0].url.path == "/api/v1/projects"
    assert requests[0].headers["X-Organization-ID"] == "organization-1"
    assert requests[1].url.path == "/selftest/journal"
    assert "Authorization" not in requests[1].headers


async def test_completed_bootstrap_phase_resumes_without_duplicate_post_or_credentials(
    tmp_path: Path,
) -> None:
    resource_id = str(uuid4())
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json={
                "id": resource_id,
                "token": "response-token-must-not-be-recorded",
            },
        )

    api = PublicAPI("http://isolated.example", transport=httpx.MockTransport(respond))
    payload = {"name": "resource", "password": "payload-password-must-not-be-recorded"}
    try:
        original = await BootstrapJournal(tmp_path, "nonce-1").create(
            api, "project", "/projects", payload
        )
        resumed = await BootstrapJournal(tmp_path, "nonce-1").create(
            api, "project", "/projects", payload, read_prefix="/projects"
        )
    finally:
        await api.close()
    assert original == resumed == {"id": resource_id}
    assert methods == ["POST", "GET"]
    content = (tmp_path / "bootstrap-journal.json").read_text()
    assert "payload-password" not in content and "response-token" not in content
    assert (tmp_path / "bootstrap-journal.json").stat().st_mode & 0o077 == 0


async def test_unknown_create_response_stops_instead_of_creating_again(tmp_path: Path) -> None:
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("synthetic unknown server completion", request=request)

    api = PublicAPI("http://isolated.example", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(httpx.ReadTimeout):
            await BootstrapJournal(tmp_path, "nonce-1").create(
                api, "project", "/projects", {"name": "one"}
            )
        with pytest.raises(HarnessError, match="UNKNOWN_RESULT_NEEDS_REVIEW"):
            await BootstrapJournal(tmp_path, "nonce-1").create(
                api, "project", "/projects", {"name": "one"}
            )
    finally:
        await api.close()
    assert attempts == 1


async def test_partial_installation_resumes_remaining_phase_and_conflicts_fail_closed(
    tmp_path: Path,
) -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(201, json={"id": str(uuid4())})

    api = PublicAPI("http://isolated.example", transport=httpx.MockTransport(respond))
    try:
        first = await BootstrapJournal(tmp_path, "nonce-1").create(
            api, "project", "/projects", {"name": "one"}
        )
        resumed = BootstrapJournal(tmp_path, "nonce-1")
        assert await resumed.create(api, "project", "/projects", {"name": "one"}) == first
        await resumed.create(api, "environment", "/environments", {"name": "two"})
        with pytest.raises(HarnessError, match="PHASE_CONFLICT"):
            await resumed.create(api, "project", "/projects", {"name": "changed"})
    finally:
        await api.close()
    assert requests == ["/api/v1/projects", "/api/v1/environments"]


def test_concurrent_installer_is_rejected_and_lock_is_released(tmp_path: Path) -> None:
    with (
        bootstrap_lock(tmp_path, "nonce-1"),
        pytest.raises(HarnessError, match="IN_PROGRESS_OR_NEEDS_REVIEW"),
        bootstrap_lock(tmp_path, "nonce-1"),
    ):
        pytest.fail("second installer acquired active lock")
    with bootstrap_lock(tmp_path, "nonce-1"):
        assert (tmp_path / ".bootstrap.lock").is_dir()


async def test_observer_credential_is_scoped_rotated_and_never_saved(tmp_path: Path) -> None:
    ids = [str(uuid4()), str(uuid4())]
    calls: list[tuple[str, str]] = []
    minted = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal minted
        calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": ids[0]})
        assert json.loads(request.content)["scopes"] == ["read:execution"]
        token_id = ids[minted]
        minted += 1
        return httpx.Response(201, json={"id": token_id, "token": f"private-observer-{minted}"})

    installed = Installation(
        binding_nonce="nonce-1",
        organization_id=uuid4(),
        project_id=uuid4(),
        reviewer_id=uuid4(),
        reviewer_email="reviewer@example.com",
        mcp_account_id=uuid4(),
        target_project_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.com",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
    )
    api = PublicAPI(
        "http://isolated.example", "bootstrap-private", transport=httpx.MockTransport(respond)
    )
    try:
        assert await _observer_credential(api, installed, tmp_path) == "private-observer-1"
        assert await _observer_credential(api, installed, tmp_path) == "private-observer-2"
    finally:
        await api.close()
    assert [method for method, _ in calls] == ["POST", "DELETE", "POST"]
    assert calls[1][1].endswith(ids[0])
    assert "private-observer" not in (tmp_path / "observer-credential-lease.json").read_text()


def binding_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[StackBinding, dict[str, Any]]:
    project, nonce = "flowtest-selftest-abcdef123456", "a" * 32
    monkeypatch.setattr(local_stack, "source_digest", lambda: "source")
    private = {
        "FLOWTEST_SELFTEST_STACK_NONCE": nonce,
        "FLOWTEST_SELFTEST_OBSERVER_TOKEN": "observer-private",
    }
    for role in ("RUNNER", "TARGET"):
        for suffix in ("KEY", "ENCRYPTION_KEY", "PASSWORD"):
            private[f"FLOWTEST_SELFTEST_{role}_{suffix}"] = f"{role}-{suffix}-private"
    environment = tmp_path / "private.env"
    environment.write_text("".join(f"{key}={value}\n" for key, value in private.items()))
    environment.chmod(0o600)
    write_json(tmp_path / "ownership.json", {"project_name": project, "nonce": nonce})
    binding = StackBinding(
        project_name=project,
        nonce=nonce,
        runner_url="http://127.0.0.1:19001",
        target_url="http://127.0.0.1:19002",
        observer_url="http://127.0.0.1:19003",
        private_subnet="172.29.30.0/24",
        candidate_image="candidate",
        candidate_image_digest="candidate-digest",
        fixture_image="fixture",
        fixture_image_digest="fixture-digest",
        source_digest="source",
        dependency_digest=hashlib.sha256((ROOT / "backend/uv.lock").read_bytes()).hexdigest(),
        runner_container_id="runner",
        target_container_id="target",
        observer_container_id="observer",
        runner_volume=f"{project}_runner-data",
        target_volume=f"{project}_target-data",
    )
    inspections: dict[str, Any] = {}
    labels = {"com.docker.compose.project": project, "dev.flowtest.selftest.nonce": nonce}
    for role, port in (
        ("runner", "19001"),
        ("target", "19002"),
        ("observer", "19003"),
        ("mock-target", None),
    ):
        key = role.upper()
        encryption = private.get(f"FLOWTEST_SELFTEST_{key}_ENCRYPTION_KEY", "")
        env = [
            f"FLOWTEST_SECRET_KEY={private.get(f'FLOWTEST_SELFTEST_{key}_KEY', '')}",
            f"FLOWTEST_DATA_ENCRYPTION_KEY={encryption}",
        ]
        if role in {"runner", "target"}:
            env.append("FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH=" + ("1" if role == "target" else "0"))
        if role == "observer":
            env.append("FLOWTEST_SELFTEST_OBSERVER_TOKEN=observer-private")
        journal = role in {"observer", "mock-target"}
        inspections[role] = {
            "Image": "fixture-digest" if journal else "candidate-digest",
            "Config": {"Labels": {**labels, "com.docker.compose.service": role}, "Env": env},
            "State": {"Running": True},
            "NetworkSettings": {
                "Networks": {
                    f"{project}_{'management' if role == 'observer' else 'execution'}": {},
                    **({f"{project}_{role}-control": {}} if role != "mock-target" else {}),
                },
                "Ports": {}
                if port is None
                else {
                    "8081/tcp" if role == "observer" else "8000/tcp": [
                        {"HostIp": "127.0.0.1", "HostPort": port}
                    ]
                },
            },
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": f"{project}_{'fixture-journal' if journal else role + '-data'}",
                    "Destination": "/journal" if journal else "/data",
                }
            ],
        }

    def docker(arguments: list[str], **_kwargs: Any) -> str:
        if arguments[0] == "ps":
            return "mock-target"
        if arguments[0] == "inspect":
            return json.dumps(inspections[arguments[1]])
        if arguments[0] == "volume":
            return json.dumps({"Labels": labels})
        control = arguments[2].endswith("-control")
        control_role = arguments[2].removeprefix(f"{project}_").removesuffix("-control")
        members = (
            {control_role}
            if control
            else {"observer"}
            if arguments[2].endswith("_management")
            else {"runner", "target", "mock-target"}
        )
        return json.dumps(
            {
                "Labels": labels,
                "Internal": not control,
                "IPAM": {"Config": [{"Subnet": binding.private_subnet}]},
                "Containers": {member: {} for member in members},
            }
        )

    monkeypatch.setattr(local_stack, "_docker", docker)
    return binding, inspections


def test_actual_owned_isolated_binding_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, _ = binding_fixture(tmp_path, monkeypatch)
    local_stack.verify_binding(binding, tmp_path)


@pytest.mark.parametrize("setting", ["BINDINGS", "PRINCIPALS", "EXTRA_TEMPLATES", "PROBE_GRANTS"])
def test_runner_settings_must_match_actual_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    _, inspections = binding_fixture(tmp_path, monkeypatch)
    private = local_stack.private_environment(tmp_path)
    name = f"FLOWTEST_SELFTEST_{setting}"
    private[name] = '[{"id":"owned-grant"}]'
    with pytest.raises(HarnessError, match="SELFTEST_PRODUCT_CONFIGURATION_MISMATCH"):
        local_stack._verify_private_configuration("runner", inspections["runner"], private)
    inspections["runner"]["Config"]["Env"].append(name + "=" + private[name])
    local_stack._verify_private_configuration("runner", inspections["runner"], private)


def test_target_fixture_depth_cannot_be_removed_from_actual_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, inspections = binding_fixture(tmp_path, monkeypatch)
    inspections["target"]["Config"]["Env"] = [
        value
        for value in inspections["target"]["Config"]["Env"]
        if not value.startswith("FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH=")
    ]
    with pytest.raises(HarnessError, match="SELFTEST_CONTAINER_KEY_BINDING_MISMATCH"):
        local_stack.verify_binding(binding, tmp_path)


async def test_existing_installation_adds_two_distinct_viewers_once_without_persisting_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, _ = binding_fixture(tmp_path, monkeypatch)
    binding = binding.model_copy(
        update={"runner_url": "http://runner", "target_url": "http://target"}
    )
    installed = Installation(
        binding_nonce=binding.nonce,
        organization_id=uuid4(),
        project_id=uuid4(),
        reviewer_id=uuid4(),
        reviewer_email="reviewer@example.com",
        mcp_account_id=uuid4(),
        target_project_id=uuid4(),
        target_organization_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.com",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
    )
    created: dict[str, str] = {}
    passwords: list[str] = []
    roles: list[str] = []
    posts: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        organization = (
            installed.organization_id if host == "runner" else installed.target_organization_id
        )
        assert request.headers["X-Organization-ID"] == str(organization)
        if request.method == "POST":
            assert request.url.path == "/api/v1/users"
            payload = json.loads(request.content)
            assert payload.get("is_system_admin", False) is False
            passwords.append(payload["password"])
            posts.append(host)
            created[host] = str(uuid4())
            return httpx.Response(201, json={"id": created[host]})
        if request.method == "PUT":
            payload = json.loads(request.content)
            roles.append(payload["role"])
            assert payload["role"] == (
                "member" if "/organizations/" in request.url.path else "viewer"
            )
            return httpx.Response(200, json={"id": created[host]})
        assert request.headers["Authorization"] == f"Bearer private-viewer-{host}"
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": created[host], "is_system_admin": False})
        assert request.url.path.endswith("/permissions")
        return httpx.Response(200, json={"effective_role": "viewer"})

    transport = httpx.MockTransport(respond)
    a = PublicAPI("http://runner", "admin-a", str(installed.organization_id), transport=transport)
    b = PublicAPI(
        "http://target", "admin-b", str(installed.target_organization_id), transport=transport
    )
    original_api = PublicAPI

    def viewer_api(base: str, token: str, organization: str) -> PublicAPI:
        return original_api(base, token, organization, transport=transport)

    async def viewer_login(base: str, _email: str, password: str) -> tuple[str, str]:
        return f"private-viewer-{httpx.URL(base).host}", password

    monkeypatch.setattr(bootstrap_module, "PublicAPI", viewer_api)
    monkeypatch.setattr(bootstrap_module, "login", viewer_login)
    journal = BootstrapJournal(tmp_path, binding.nonce)
    private = local_stack.private_environment(tmp_path)
    try:
        first, a_token, b_token = await _viewer_credentials(
            a, b, binding, private, journal, installed
        )
        second, _, _ = await _viewer_credentials(a, b, binding, private, journal, first)
    finally:
        await a.close()
        await b.close()
    assert first == second
    assert first.capture_viewer_id != first.reviewer_id
    assert first.target_viewer_id != first.target_user_id
    assert posts == ["runner", "target"]
    assert roles == ["member", "viewer"] * 4
    assert a_token == "private-viewer-runner" and b_token == "private-viewer-target"
    write_json(tmp_path / "installation.json", first)
    persisted = (tmp_path / "installation.json").read_text() + (
        tmp_path / "bootstrap-journal.json"
    ).read_text()
    assert all(secret not in persisted for secret in [*passwords, a_token, b_token])
    assert (tmp_path / "installation.json").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("change", ["admin", "owner", "wrong_user"])
async def test_observer_viewer_validation_rejects_privileged_or_changed_identity(
    change: str,
) -> None:
    user_id, project_id = str(uuid4()), uuid4()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(
                200,
                json={
                    "id": str(uuid4()) if change == "wrong_user" else user_id,
                    "is_system_admin": change == "admin",
                },
            )
        return httpx.Response(
            200, json={"effective_role": "owner" if change == "owner" else "viewer"}
        )

    viewer = PublicAPI("http://runner", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(HarnessError, match="OBSERVER_VIEWER_IDENTITY_INVALID"):
            await _validate_viewer(viewer, user_id, project_id)
    finally:
        await viewer.close()


def test_subnet_selection_excludes_actual_broad_docker_networks() -> None:
    occupied = tuple(ipaddress.ip_network(value) for value in ("172.16.0.0/12", "10.240.0.0/24"))
    assert local_stack.choose_private_subnet(occupied) == "10.240.1.0/24"


def test_subnet_inventory_reads_ipam_and_does_not_use_random_overlapping_subnet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def docker(arguments: list[str], **_kwargs: Any) -> str:
        if arguments[:2] == ["network", "ls"]:
            return "network-1\nnetwork-2"
        return json.dumps(
            [{"Subnet": "172.16.0.0/12" if arguments[2] == "network-1" else "10.240.0.0/24"}]
        )

    monkeypatch.setattr(local_stack, "_docker", docker)
    assert local_stack.available_private_subnet() == "10.240.1.0/24"


def test_resume_rejects_existing_container_before_changing_owned_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _binding, _ = binding_fixture(tmp_path, monkeypatch)
    original = (tmp_path / "private.env").read_bytes()
    with pytest.raises(HarnessError, match="PARTIAL_STACK_NEEDS_REVIEW"):
        local_stack.resume(tmp_path)
    assert (tmp_path / "private.env").read_bytes() == original
    assert not (tmp_path / "stack.json").exists()


def test_resume_does_not_overwrite_failed_build_evidence(tmp_path: Path) -> None:
    (tmp_path / "build-resume-1.log").write_text("failed build before startup")
    assert local_stack._next_resume_attempt(tmp_path) == 2


def test_refresh_rebuilds_only_verified_owned_stack_preserving_installation_and_volumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, inspections = binding_fixture(tmp_path, monkeypatch)
    write_json(tmp_path / "stack.json", binding)
    receipt = local_stack.BuildReceipt.model_validate(
        {key: getattr(binding, key) for key in local_stack.BuildReceipt.model_fields}
    )
    write_json(tmp_path / "build-receipt.json", receipt)
    (tmp_path / "installation.json").write_text("installed-identities")
    updated = binding.model_copy(
        update={"source_digest": "new-source", "candidate_image_digest": "new-image"}
    )
    monkeypatch.setattr(local_stack, "source_digest", lambda: "new-source")
    calls: list[list[str]] = []

    def build(*_args: object) -> local_stack.BuildReceipt:
        return receipt.model_copy(
            update={"source_digest": "new-source", "candidate_image_digest": "new-image"}
        )

    def compose(_project: str, _env: Path, arguments: list[str], **_kwargs: Any) -> str:
        calls.append(arguments)
        inspections["runner"]["Image"] = "new-image"
        inspections["target"]["Image"] = "new-image"
        return ""

    monkeypatch.setattr(local_stack, "_build_images", build)
    monkeypatch.setattr(local_stack, "_compose", compose)
    monkeypatch.setattr(local_stack, "_binding", lambda *_args: updated)
    assert local_stack.refresh(tmp_path) == updated
    assert calls == [["up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "120"]]
    assert (tmp_path / "installation.json").read_text() == "installed-identities"
    assert updated.runner_volume == binding.runner_volume
    assert updated.target_volume == binding.target_volume
    assert (
        json.loads((tmp_path / "resume-1.json").read_text())["previous_binding"]["source_digest"]
        == "source"
    )


def test_refresh_cannot_skip_same_a_b_identity_or_image_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, inspections = binding_fixture(tmp_path, monkeypatch)
    write_json(tmp_path / "stack.json", binding)
    monkeypatch.setattr(local_stack, "source_digest", lambda: "new-source")
    inspections["runner"]["Image"] = "foreign-image"
    with pytest.raises(HarnessError, match="CONTAINER_BUILD_MISMATCH"):
        local_stack.refresh(tmp_path)
    assert not (tmp_path / "resume-1.json").exists()


@pytest.mark.parametrize(
    "network", ["execution", "management", "runner-control", "target-control", "observer-control"]
)
def test_no_foreign_container_can_share_any_owned_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, network: str
) -> None:
    binding, _ = binding_fixture(tmp_path, monkeypatch)
    original = local_stack._docker

    def docker(arguments: list[str], **kwargs: Any) -> str:
        raw = original(arguments, **kwargs)
        if arguments[:3] == ["network", "inspect", f"{binding.project_name}_{network}"]:
            value = json.loads(raw)
            value["Containers"]["foreign-container"] = {}
            return json.dumps(value)
        return raw

    monkeypatch.setattr(local_stack, "_docker", docker)
    with pytest.raises(HarnessError, match="NETWORK_MEMBERSHIP_MISMATCH"):
        local_stack.verify_binding(binding, tmp_path)


@pytest.mark.parametrize(
    "change", ["image", "nonce", "network", "volume", "published", "credentials", "a_equals_b"]
)
def test_unsafe_or_drifted_binding_is_rejected_before_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    binding, inspections = binding_fixture(tmp_path, monkeypatch)
    runner = inspections["runner"]
    if change == "image":
        runner["Image"] = "other-image"
    elif change == "nonce":
        runner["Config"]["Labels"]["dev.flowtest.selftest.nonce"] = "b" * 32
    elif change == "network":
        runner["NetworkSettings"]["Networks"]["daily-network"] = {}
    elif change == "volume":
        runner["Mounts"][0]["Name"] = "personal-data"
    elif change == "published":
        binding = binding.model_copy(update={"runner_url": "https://production.example.com"})
    elif change == "credentials":
        runner["Config"]["Env"].append("FLOWTEST_SELFTEST_OBSERVER_TOKEN=observer-private")
    else:
        binding = binding.model_copy(update={"target_container_id": binding.runner_container_id})
    with pytest.raises(HarnessError):
        local_stack.verify_binding(binding, tmp_path)


async def test_negative_execution_actor_is_distinct_from_observer_and_has_writeonly_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, _ = binding_fixture(tmp_path, monkeypatch)
    installed = Installation(
        binding_nonce=binding.nonce,
        organization_id=uuid4(),
        project_id=uuid4(),
        reviewer_id=uuid4(),
        reviewer_email="reviewer@example.com",
        mcp_account_id=uuid4(),
        target_project_id=uuid4(),
        target_organization_id=uuid4(),
        target_user_id=uuid4(),
        target_email="target@example.com",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
        target_viewer_id=uuid4(),
        target_viewer_email="observer@example.com",
    )
    denied_id = str(uuid4())
    passwords: list[str] = []
    roles: list[str] = []
    secrets: list[dict[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/api/v1/users"
            passwords.append(json.loads(request.content)["password"])
            return httpx.Response(201, json={"id": denied_id})
        if request.url.path.endswith("/secrets"):
            secrets.append(json.loads(request.content))
            return httpx.Response(200, json={"name": secrets[-1]["name"]})
        if request.method == "PUT":
            roles.append(json.loads(request.content)["role"])
            return httpx.Response(200, json={"id": denied_id})
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(200, json={"id": denied_id, "is_system_admin": False})
        return httpx.Response(200, json={"effective_role": "viewer"})

    a = PublicAPI("http://runner", transport=httpx.MockTransport(respond))
    b = PublicAPI("http://target", transport=httpx.MockTransport(respond))

    def viewer_api(base: str, token: str, organization: str) -> PublicAPI:
        assert token == "private-negative-execution-token"
        assert organization == str(installed.target_organization_id)
        return PublicAPI(base, token, organization, transport=httpx.MockTransport(respond))

    async def actor_login(base: str, email: str, password: str) -> tuple[str, str]:
        assert base == binding.target_url
        assert email.startswith("denied-actor-") and email != installed.target_viewer_email
        return "private-negative-execution-token", password

    monkeypatch.setattr(bootstrap_module, "PublicAPI", viewer_api)
    monkeypatch.setattr(bootstrap_module, "login", actor_login)
    private = local_stack.private_environment(tmp_path)
    journal = BootstrapJournal(tmp_path, binding.nonce)
    try:
        first = await bootstrap_module._denied_actor(a, b, binding, private, journal, installed)
        second = await bootstrap_module._denied_actor(a, b, binding, private, journal, first)
    finally:
        await a.close()
        await b.close()
    assert first == second
    assert first.denied_user_id != installed.target_viewer_id
    assert len(passwords) == 1
    assert passwords[0] != bootstrap_module._viewer_password(private, "TARGET")
    assert roles == ["member", "viewer"] * 2
    assert [item["name"] for item in secrets] == ["SELFTEST_B_DENIED_PASSWORD"] * 2
    content = (tmp_path / "bootstrap-journal.json").read_text()
    assert passwords[0] not in content
    assert "private-negative-execution-token" not in content
    assert str(first.denied_user_id) in content
