import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.core.config import Settings, settings
from app.domain.access import ProjectCapability, ProjectRole
from app.domain.network import OutboundNetworkPolicy, OutboundPolicyError, validate_outbound_url
from app.domain.runtime_profiles import RuntimeProfile
from app.middleware import rate_limit as rate_limit_middleware
from app.services.rate_limit import RedisRateLimiter


def test_fixed_role_capability_matrix() -> None:
    assert ProjectRole.OWNER.capabilities == frozenset(ProjectCapability)
    assert ProjectRole.EDITOR.capabilities == {
        ProjectCapability.READ,
        ProjectCapability.EDIT,
        ProjectCapability.EXECUTE,
    }
    assert ProjectRole.VIEWER.capabilities == {ProjectCapability.READ}
    assert not ProjectRole.EDITOR.allows(ProjectCapability.MANAGE_SECURITY)
    assert not ProjectRole.VIEWER.allows(ProjectCapability.EXECUTE)


def test_production_rejects_local_credentials_and_insecure_cookies() -> None:
    with pytest.raises(ValidationError, match="生产环境"):
        Settings(_env_file=None, environment="production")

    configured = Settings(
        _env_file=None,
        environment="production",
        secret_key="production-signing-key-with-more-than-32-bytes",
        bootstrap_admin_password="production-admin-password",
        data_encryption_key="eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=",
        s3_secret_key="production-object-storage-secret",
        secure_cookies=True,
    )
    assert configured.secure_cookies

    with pytest.raises(ValidationError, match="生产环境"):
        Settings(
            _env_file=None,
            environment="production",
            secret_key="production-signing-key-with-more-than-32-bytes",
            bootstrap_admin_password="admin",
            data_encryption_key="eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=",
            s3_secret_key="production-object-storage-secret",
            secure_cookies=True,
        )


def test_retention_default_does_not_exceed_system_limit() -> None:
    with pytest.raises(ValidationError, match="默认保留天数"):
        Settings(_env_file=None, retention_default_days=31, retention_max_days=30)


def test_environment_lab_requires_exact_digest_allowlist() -> None:
    with pytest.raises(ValidationError, match="镜像白名单"):
        Settings(_env_file=None, feature_environment_lab_enabled=True)
    with pytest.raises(ValidationError, match="OCI Digest"):
        Settings(
            _env_file=None,
            feature_environment_lab_enabled=True,
            environment_image_allowlist=["registry.example/fixture@sha256:not-a-digest"],
        )

    image = f"registry.example/fixture@sha256:{'a' * 64}"
    configured = Settings(
        _env_file=None,
        feature_environment_lab_enabled=True,
        environment_image_allowlist=[image],
    )
    assert configured.environment_image_allowlist == [image]


def test_compact_runtime_profile_rejects_missing_worker_runtimes() -> None:
    configured = Settings(_env_file=None, runtime_profile="compact")
    assert configured.runtime_profile is RuntimeProfile.COMPACT

    with pytest.raises(ValidationError, match=r"compact.*performance_lab"):
        Settings(
            _env_file=None,
            runtime_profile="compact",
            feature_performance_lab_enabled=True,
        )
    with pytest.raises(ValidationError, match=r"compact.*environment_lab"):
        Settings(
            _env_file=None,
            runtime_profile="compact",
            feature_environment_lab_enabled=True,
            environment_image_allowlist=[f"registry.example/fixture@sha256:{'a' * 64}"],
        )


def test_public_mock_dispatch_is_rate_limited_for_every_http_method() -> None:
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": method,
                "scheme": "https",
                "path": "/api/v1/mock/contracts/users/42",
                "raw_path": b"/api/v1/mock/contracts/users/42",
                "query_string": b"",
                "headers": [],
                "client": ("203.0.113.1", 50000),
                "server": ("flowtest.example.com", 443),
            }
        )
        assert rate_limit_middleware._rule(request) == (
            "mock-dispatch",
            settings.execution_rate_limit_per_minute,
        )


def test_runner_control_plane_uses_dedicated_rate_limit() -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/runner-control/leases/claim",
            "raw_path": b"/api/v1/runner-control/leases/claim",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer runner-token")],
            "client": ("203.0.113.1", 50000),
            "server": ("flowtest.example.com", 443),
        }
    )

    assert rate_limit_middleware._rule(request) == (
        "runner-control",
        settings.runner_control_rate_limit_per_minute,
    )


@pytest.mark.asyncio
async def test_outbound_policy_blocks_ssrf_and_allows_explicit_private_cidr() -> None:
    async def public(_host: str, _port: int) -> tuple[str, ...]:
        return ("1.1.1.1",)

    addresses = await validate_outbound_url(
        "https://api.example.com/users",
        OutboundNetworkPolicy(allowed_hosts=("*.example.com",)),
        resolver=public,
    )
    assert addresses == ("1.1.1.1",)

    with pytest.raises(OutboundPolicyError, match="允许列表"):
        await validate_outbound_url(
            "https://evil.example.net",
            OutboundNetworkPolicy(allowed_hosts=("*.example.com",)),
            resolver=public,
        )

    async def private(_host: str, _port: int) -> tuple[str, ...]:
        return ("10.20.30.40",)

    with pytest.raises(OutboundPolicyError, match="未授权的私有网络"):
        await validate_outbound_url(
            "http://internal.example.com",
            OutboundNetworkPolicy(),
            resolver=private,
        )
    assert await validate_outbound_url(
        "http://internal.example.com",
        OutboundNetworkPolicy(allowed_private_cidrs=("10.20.0.0/16",)),
        resolver=private,
    ) == ("10.20.30.40",)

    async def metadata(_host: str, _port: int) -> tuple[str, ...]:
        return ("169.254.169.254",)

    with pytest.raises(OutboundPolicyError, match="禁止访问"):
        await validate_outbound_url(
            "http://metadata.internal",
            OutboundNetworkPolicy(allowed_private_cidrs=("169.254.0.0/16",)),
            resolver=metadata,
        )


@pytest.mark.asyncio
async def test_outbound_policy_rejects_credentials_and_mixed_dns_answers() -> None:
    async def mixed(_host: str, _port: int) -> tuple[str, ...]:
        return ("1.1.1.1", "127.0.0.1")

    with pytest.raises(OutboundPolicyError, match="用户凭据"):
        await validate_outbound_url(
            "https://user:password@example.com",
            OutboundNetworkPolicy(),
            resolver=mixed,
        )
    with pytest.raises(OutboundPolicyError, match="禁止访问"):
        await validate_outbound_url(
            "https://example.com",
            OutboundNetworkPolicy(),
            resolver=mixed,
        )


@pytest.mark.asyncio
async def test_disabled_outbound_policy_allows_localhost_and_preserves_peer_resolution() -> None:
    async def localhost(_host: str, _port: int) -> tuple[str, ...]:
        return ("127.0.0.1", "::1")

    assert await validate_outbound_url(
        "http://localhost:8080/openapi.json",
        OutboundNetworkPolicy(enabled=False),
        resolver=localhost,
    ) == ("127.0.0.1", "::1")


class FakeRateClient:
    def __init__(self, results: list[list[int]]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, tuple[object, ...]]] = []

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        self.calls.append((script, numkeys, keys_and_args))
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_rate_limiter_exposes_remaining_and_retry_after() -> None:
    fake = FakeRateClient([[1, 60], [3, 42]])
    limiter = RedisRateLimiter(fake)

    allowed = await limiter.check(key="user", limit=2, window_seconds=60)
    blocked = await limiter.check(key="user", limit=2, window_seconds=60)

    assert allowed.allowed and allowed.remaining == 1
    assert not blocked.allowed and blocked.remaining == 0 and blocked.retry_after == 42
    assert fake.calls[0][2] == ("flowtest:rate:user", 60)
