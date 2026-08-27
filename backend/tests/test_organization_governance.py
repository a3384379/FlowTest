from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.governance import (
    DEFAULT_QUOTA_POLICIES,
    QuotaDimension,
    QuotaMode,
    QuotaRule,
    parse_quota_policies,
)
from app.models.governance import OrganizationGovernance
from app.services.organization_governance import OrganizationQuotaService


def test_quota_domain_contract_parses_invalid_persisted_values_safely() -> None:
    rule = QuotaRule(mode=QuotaMode.HARD_LIMIT, limit=10, warn_at=5)
    assert rule.evaluate(10).blocked is False
    assert rule.evaluate(11).blocked is True
    assert rule.evaluate(5).warning is True
    with pytest.raises(ValueError):
        rule.evaluate(-1)

    parsed = parse_quota_policies(
        {
            **DEFAULT_QUOTA_POLICIES,
            "project_count": {"mode": "hard_limit", "limit": "invalid"},
            "user_count": {"mode": "not-a-mode", "limit": 1},
        }
    )
    assert parsed[QuotaDimension.PROJECT_COUNT.value] == QuotaRule()
    assert parsed[QuotaDimension.USER_COUNT.value] == QuotaRule()
    assert set(parsed) == {dimension.value for dimension in QuotaDimension}


@pytest.mark.asyncio
async def test_quota_service_evaluates_all_dimensions_and_hard_blocks() -> None:
    organization_id = uuid4()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 0
    session.get.return_value = OrganizationGovernance(
        organization_id=organization_id,
        quota_policies=dict(DEFAULT_QUOTA_POLICIES),
        runner_policy={},
    )
    service = OrganizationQuotaService(session)

    assert (
        await service.enforce(organization_id=None, dimension=QuotaDimension.PROJECT_COUNT) is None
    )
    for dimension in QuotaDimension:
        decision = await service.enforce(organization_id=organization_id, dimension=dimension)
        assert decision is not None
        assert decision.dimension == dimension.value
        assert decision.mode is QuotaMode.OBSERVE

    session.get.return_value.quota_policies = {
        **DEFAULT_QUOTA_POLICIES,
        "project_count": {"mode": "hard_limit", "limit": 1, "warn_at": 1},
    }
    session.scalar.return_value = 1
    with pytest.raises(AppError) as error:
        await service.enforce(
            organization_id=organization_id,
            dimension=QuotaDimension.PROJECT_COUNT,
        )
    assert error.value.code == "ORGANIZATION_QUOTA_EXCEEDED"
    assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_quota_service_validates_runner_governance_policy() -> None:
    organization_id = uuid4()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 0
    session.get.return_value = OrganizationGovernance(
        organization_id=organization_id,
        quota_policies=dict(DEFAULT_QUOTA_POLICIES),
        runner_policy={
            "allowed_runner_types": ["general"],
            "allowed_runtimes": ["docker"],
            "max_pools": 1,
            "registration_requires_approval": False,
        },
    )
    service = OrganizationQuotaService(session)

    await service.validate_runner_pool(
        organization_id=None, runner_type="unknown", runtime="unknown"
    )
    with pytest.raises(AppError) as runner_type_error:
        await service.validate_runner_pool(
            organization_id=organization_id, runner_type="unknown", runtime="docker"
        )
    assert runner_type_error.value.code == "RUNNER_TYPE_NOT_ALLOWED"

    with pytest.raises(AppError) as runtime_error:
        await service.validate_runner_pool(
            organization_id=organization_id, runner_type="general", runtime="kubernetes"
        )
    assert runtime_error.value.code == "RUNNER_RUNTIME_NOT_ALLOWED"

    session.scalar.return_value = 1
    with pytest.raises(AppError) as pool_error:
        await service.validate_runner_pool(
            organization_id=organization_id, runner_type="general", runtime="docker"
        )
    assert pool_error.value.code == "RUNNER_POOL_QUOTA_EXCEEDED"
