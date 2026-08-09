import pytest

from app.domain import network


@pytest.fixture(autouse=True)
def deterministic_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests independent from host DNS while exercising the real guard."""

    async def resolve_public(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("1.1.1.1",)

    monkeypatch.setattr(network, "resolve_host", resolve_public)
