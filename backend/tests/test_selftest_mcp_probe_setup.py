"""Only real public ASGI APIs provision fixture identities; no business SQL counts."""

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.selftest.io import HarnessError, read_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_governance_contracts import Fixture
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_negative_contracts import FixtureIdentity
from scripts.selftest.mcp_probe_reader import ProbeReader
from scripts.selftest.mcp_probe_setup import (
    PreparedFixture,
    _observer,
    _prepare_claimed,
    _retained_binding,
    authority,
    configure,
    provision,
)
from test_tasking_api import ADMIN_EMAIL, ADMIN_PASSWORD
from test_tasking_api import tasking_context as tasking_context

from app.core.self_test_probes import NegativeProbeGrant
from app.core.self_tests import SelfTestSettings, get_self_test_settings
from app.main import app


def binding() -> StackBinding:
    return StackBinding(
        project_name="flowtest-selftest-" + "1" * 12,
        nonce="2" * 32,
        runner_url="http://owned.test",
        target_url="http://target.test",
        observer_url="http://observer.test",
        private_subnet="172.18.0.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image="mock",
        fixture_image_digest="sha256:" + "b" * 64,
        source_digest="c" * 64,
        dependency_digest="d" * 64,
        runner_container_id="e" * 64,
        target_container_id="f" * 64,
        observer_container_id="0" * 64,
        runner_volume="owned-runner",
        target_volume="owned-target",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("account_delay", [0.0, 1.0])
async def test_public_fixture_provision_separate_reviewer_revocation_expiry_and_scoped_inventory(
    tasking_context, monkeypatch, tmp_path, account_delay
):
    from scripts.selftest import mcp_probe_setup

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    original_api = mcp_probe_setup.ProbeAPI

    class API(original_api):
        def __init__(self, url, budget, token="", organization=None):
            super().__init__(url, budget, token, organization, transport=transport)

        async def request(
            self, method, path, payload=None, *, idempotency_key=None, allow_status=()
        ):
            if method == "POST" and path.endswith("/service-accounts"):
                await asyncio.sleep(account_delay)
            return await super().request(
                method, path, payload, idempotency_key=idempotency_key, allow_status=allow_status
            )

    monkeypatch.setattr(mcp_probe_setup, "ProbeAPI", API)
    original_login = mcp_probe_setup._login

    async def login(url, budget, email, password, *, new_actor=False):
        if email == "selftest-a@example.com":
            email, password = ADMIN_EMAIL, ADMIN_PASSWORD
        return await original_login(url, budget, email, password, new_actor=new_actor)

    monkeypatch.setattr(mcp_probe_setup, "_login", login)
    monkeypatch.setattr(
        mcp_probe_setup,
        "private_environment",
        lambda _: {"FLOWTEST_SELFTEST_RUNNER_PASSWORD": ADMIN_PASSWORD},
    )
    now = datetime.now(UTC)
    nonce = uuid4().hex
    budget = ProtocolHttpBudget(
        tmp_path / "budget.sqlite3", nonce, (now + timedelta(seconds=600)).timestamp()
    )
    actual = await provision(binding(), tmp_path, tmp_path, nonce, budget)
    assert actual.fixture.identity.organization_a != actual.fixture.identity.organization_b
    assert actual.fixture.governance.owner_user_id != actual.fixture.governance.reviewer_user_id
    assert len(actual.fixture.machine_ids) == 6
    frozen = authority(
        binding(), actual.fixture, "1" * 64, nonce, now, now + timedelta(seconds=600)
    )
    identity = _observer(tmp_path, frozen)
    grant = NegativeProbeGrant.model_validate(
        {
            **frozen.model_dump(mode="json", exclude={"probe_id", "fixtures"}),
            "id": nonce,
            "fixtures": [r.model_dump(mode="json") for r in frozen.fixtures],
            "principal_id": identity.principal.id,
            "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
        }
    )
    config = SelfTestSettings(principals=(identity.principal,), probe_grants=(grant,))
    app.dependency_overrides[get_self_test_settings] = lambda: config
    reader = ProbeReader(
        binding().runner_url, identity.token(), nonce, frozen, budget.reserve, transport=transport
    )
    try:
        snapshot = await reader.snapshot()
        assert not snapshot.resources and snapshot.pages[0].total == 0
        assert snapshot.pages[0].snapshot_digest
    finally:
        await reader.close()
    raw = read_json(tmp_path / "fixture-resources.json")
    assert not {"token", "password", "authorization"} & set(raw)
    assert all(
        value not in str(raw)
        for value in (*actual.tokens.values(), actual.writer_token, actual.reviewer_token)
        if value
    )
    assert budget.counts()[0] < 100 and budget.tool_counts() == (0, 0)


@pytest.mark.parametrize("field", ["target_container_id", "runner_volume", "source_digest"])
def test_config_reload_may_only_replace_owned_runner_container(field):
    before = binding()
    allowed = before.model_copy(update={"runner_container_id": "9" * 64})
    _retained_binding(before, allowed)
    altered = allowed.model_copy(update={field: "8" * 64})
    with pytest.raises(HarnessError, match="RESOURCE_DRIFT"):
        _retained_binding(before, altered)


@pytest.mark.asyncio
async def test_unsafe_binding_is_rejected_before_public_fixture_writes(monkeypatch, tmp_path):
    from scripts.selftest import mcp_probe_setup

    (tmp_path / "stack.json").write_text(binding().model_dump_json())

    def rejected(*_):
        raise HarnessError("SYNTHETIC_UNOWNED_BINDING")

    async def forbidden(*_, **__):
        pytest.fail("unsafe binding must not provision public resources")

    monkeypatch.setattr(mcp_probe_setup, "verify_binding", rejected)
    monkeypatch.setattr(mcp_probe_setup, "provision", forbidden)
    with pytest.raises(HarnessError, match="UNOWNED_BINDING"):
        await _prepare_claimed(tmp_path, tmp_path, pack="protocol34", freeze=forbidden)


@pytest.mark.asyncio
async def test_existing_output_is_not_reused_or_rewritten(monkeypatch, tmp_path):
    from scripts.selftest import mcp_probe_run

    marker = tmp_path / "retained.json"
    marker.write_text(json.dumps({"original": True}))

    async def forbidden(*_, **__):
        pytest.fail("existing output must never reach setup")

    monkeypatch.setattr(mcp_probe_run, "_prepare_claimed", forbidden)
    with pytest.raises(FileExistsError):
        await mcp_probe_run.run_deployed(tmp_path, tmp_path, "protocol34")
    assert json.loads(marker.read_text()) == {"original": True}


@pytest.mark.asyncio
async def test_probe_driver_retains_safe_failure_code_without_exception_payload(
    monkeypatch, tmp_path
):
    from scripts.selftest import mcp_probe_run

    async def rejected(*_, **__):
        raise HarnessError("SELFTEST_HTTP_422:SERVICE_ACCOUNT_EXPIRY_INVALID:trace=private-value")

    monkeypatch.setattr(mcp_probe_run, "_prepare_claimed", rejected)
    output = tmp_path / "failed"
    assert await mcp_probe_run.run_deployed(tmp_path, output, "protocol34") == 2
    report = read_json(output / "public/verification.json")
    assert report["findings"][0]["code"] == "SELFTEST_HTTP_422_SERVICE_ACCOUNT_EXPIRY_INVALID"
    assert all("private-value" not in path.read_text() for path in (output / "public").iterdir())


def test_config_reload_preserves_existing_principals_grants_and_other_settings(
    monkeypatch, tmp_path
):
    from scripts.selftest import mcp_probe_setup

    now, nonce = datetime.now(UTC), uuid4().hex
    project_a, project_b, org_a, org_b = (uuid4() for _ in range(4))
    machine = uuid4()
    fixture = PreparedFixture(
        FixtureIdentity(
            project_a=project_a, project_b=project_b, organization_a=org_a, organization_b=org_b
        ),
        Fixture(
            project_id=project_a,
            organization_id=org_a,
            machine_id=machine,
            owner_user_id=uuid4(),
            reviewer_user_id=uuid4(),
        ),
        (machine,),
    )
    frozen = authority(binding(), fixture, "1" * 64, nonce, now, now + timedelta(seconds=600))
    identity = _observer(tmp_path, frozen)
    existing = identity.principal.model_copy(
        update={"id": "retained-principal", "issuer": "other", "subject": "retained"}
    )
    private = {
        "FLOWTEST_SELFTEST_PRINCIPALS": json.dumps([existing.model_dump(mode="json")]),
        "FLOWTEST_SELFTEST_PROBE_GRANTS": "[]",
        "FLOWTEST_SELFTEST_BINDINGS": "retained-owned-bindings",
        "FLOWTEST_SELFTEST_EXTRA_TEMPLATES": "retained-templates",
    }
    passed = []
    monkeypatch.setattr(mcp_probe_setup, "private_environment", lambda _: private.copy())

    def reload(before, directory, state, settings):
        passed.append(settings)
        return before.model_copy(update={"runner_container_id": "9" * 64})

    monkeypatch.setattr(mcp_probe_setup, "_configure", reload)
    monkeypatch.setattr(mcp_probe_setup, "verify_binding", lambda *_: None)
    updated = configure(binding(), tmp_path, tmp_path, frozen, identity, nonce)
    assert updated.runner_container_id == "9" * 64
    settings = passed[0]
    principals = json.loads(settings["FLOWTEST_SELFTEST_PRINCIPALS"])
    assert [row["id"] for row in principals] == ["retained-principal", identity.principal.id]
    assert settings["FLOWTEST_SELFTEST_BINDINGS"] == private["FLOWTEST_SELFTEST_BINDINGS"]
    assert (
        settings["FLOWTEST_SELFTEST_EXTRA_TEMPLATES"]
        == private["FLOWTEST_SELFTEST_EXTRA_TEMPLATES"]
    )
    grant = json.loads(settings["FLOWTEST_SELFTEST_PROBE_GRANTS"])[0]
    assert grant["manifest_digest"] == frozen.manifest_digest
    assert grant["nonce_hash"] == hashlib.sha256(nonce.encode()).hexdigest()
