import pytest

from app.core.config import settings
from app.core.redaction import (
    RedactionMode,
    RedactionPolicy,
    reset_redaction_policy,
    set_redaction_policy,
)
from app.domain import network


@pytest.fixture(autouse=True)
def deterministic_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests independent from host DNS while exercising the real guard."""

    async def resolve_public(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("1.1.1.1",)

    monkeypatch.setattr(network, "resolve_host", resolve_public)


@pytest.fixture(autouse=True)
def legacy_redaction_policy(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Run pre-OFF characterization cases under their explicit ON policy."""

    if request.node.get_closest_marker("redaction_on") is None:
        yield
        return
    monkeypatch.setattr(settings, "redaction_mode", "on")
    monkeypatch.setattr(settings, "redaction_policy_version", 1)
    token = set_redaction_policy(
        RedactionPolicy(mode=RedactionMode.ON, source="test", policy_version=1)
    )
    try:
        yield
    finally:
        reset_redaction_policy(token)
