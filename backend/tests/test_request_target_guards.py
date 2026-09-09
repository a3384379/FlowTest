from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.services.request_targets import RequestTargetResolver, join_service_path


def test_gateway_prefix_is_preserved() -> None:
    assert (
        join_service_path(
            "http://mock.invalid/jscpco-api/jscpco-charge-manage/", "/bill/invoice/list"
        )
        == "http://mock.invalid/jscpco-api/jscpco-charge-manage/bill/invoice/list"
    )


@pytest.mark.parametrize(
    "path", ["https://fixed.invalid/orders", "//fixed.invalid/orders", "https://[", "///orders"]
)
def test_fixed_urls_require_explicit_migration(path: str) -> None:
    with pytest.raises(AppError, match="相对路径"):
        join_service_path("http://selected.invalid/gateway/", path)


@pytest.mark.asyncio
async def test_missing_explicit_service_never_falls_back() -> None:
    resolver = RequestTargetResolver(AsyncMock())
    resolver._targets = SimpleNamespace(get_service=AsyncMock(return_value=None))
    with pytest.raises(AppError, match="Service"):
        await resolver._select_service(
            project_id=uuid4(),
            environment=SimpleNamespace(default_service_id=None),
            version=SimpleNamespace(service_id=uuid4()),
            node_service_override=None,
        )
