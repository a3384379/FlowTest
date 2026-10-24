"""Independent deployment grants for negative-only governance observations."""

import asyncio
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import get_args
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_test_probes import NegativeProbeGrant, ProbeFixture
from app.core.self_tests import SelfTestPrincipal, SelfTestSettings
from app.domain.self_tests import document_digest
from app.models.access import Project, User
from app.models.organizations import ServiceAccount
from app.schemas.self_test_probes import ProbeInventory, ProbeKind, ProbeResource
from app.schemas.self_tests import BuildIdentity, Digest, Reason, SelfTestDTO
from app.services.self_test_access import self_test_error, token_digest
from app.services.self_test_probe_designs import enrich_designs
from app.services.self_test_probe_rows import probe_rows


@dataclass(frozen=True)
class ProbeSnapshot:
    total: int
    rows: tuple[ProbeResource, ...]
    reasons: tuple[Reason, ...] = ()


class SnapshotIdentity(SelfTestDTO):
    probe_id: UUID
    binding_id: UUID
    binding_fingerprint: Digest
    manifest_digest: Digest
    source_digest: Digest
    runtime_profile: str
    builds: BuildIdentity
    covered_projects: tuple[ProbeFixture, ...]
    total: int
    rows: tuple[ProbeResource, ...]
    reasons: tuple[Reason, ...]


class NegativeProbeService:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session, self.config = session, config

    async def inventory(
        self,
        principal: SelfTestPrincipal,
        identifier: UUID,
        nonce: str,
        manifest_digest: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> ProbeInventory:
        grant = self._grant(principal, identifier, nonce, manifest_digest)
        snapshot = await self._snapshot(grant)
        digest = document_digest(
            SnapshotIdentity(
                probe_id=grant.id,
                binding_id=grant.binding_id,
                binding_fingerprint=grant.binding_fingerprint,
                manifest_digest=grant.manifest_digest,
                source_digest=grant.source_digest,
                runtime_profile=grant.runtime_profile,
                builds=grant.builds,
                covered_projects=grant.fixtures,
                total=snapshot.total,
                rows=snapshot.rows,
                reasons=snapshot.reasons,
            )
        )
        offset = self._offset(cursor, digest, len(snapshot.rows))
        if datetime.now(UTC) >= grant.expires_at:
            raise self_test_error("SELFTEST_PROBE_EXPIRED", "探针授权已过期", 403)
        page = snapshot.rows[offset : offset + page_size]
        has_more = offset + len(page) < len(snapshot.rows)
        return ProbeInventory(
            probe_id=grant.id,
            binding_id=grant.binding_id,
            binding_fingerprint=grant.binding_fingerprint,
            manifest_digest=grant.manifest_digest,
            source_digest=grant.source_digest,
            runtime_profile=grant.runtime_profile,
            builds=grant.builds,
            covered_projects=grant.fixtures,
            covered_kinds=get_args(ProbeKind),
            items=page,
            total=snapshot.total,
            complete=not snapshot.reasons,
            reason_codes=snapshot.reasons,
            snapshot_digest=digest,
            next_cursor=f"{digest}.{offset + len(page)}" if has_more else None,
            has_more=has_more,
            observed_at=datetime.now(UTC),
            expires_at=grant.expires_at,
        )

    def _grant(
        self,
        principal: SelfTestPrincipal,
        identifier: UUID,
        nonce: str,
        manifest_digest: str,
    ) -> NegativeProbeGrant:
        grant = next((item for item in self.config.probe_grants if item.id == identifier), None)
        if grant is None or not grant.enabled:
            raise self_test_error("SELFTEST_PROBE_NOT_FOUND", "探针未登记或已撤销", 404)
        projects = {fixture.project_id for fixture in grant.fixtures}
        allowed = (
            principal.id == grant.principal_id
            and set(principal.capabilities) == {"verify"}
            and set(principal.allowed_project_ids) == projects
            and set(principal.allowed_binding_ids) == {grant.binding_id}
        )
        if not allowed:
            raise self_test_error("SELFTEST_PROBE_FORBIDDEN", "外部身份没有此探针权限", 403)
        if not hmac.compare_digest(
            token_digest(nonce), grant.nonce_hash
        ) or not hmac.compare_digest(manifest_digest, grant.manifest_digest):
            raise self_test_error(
                "SELFTEST_PROBE_IDENTITY_MISMATCH", "探针 nonce 或清单不匹配", 403
            )
        if not grant.issued_at <= datetime.now(UTC) < grant.expires_at:
            raise self_test_error("SELFTEST_PROBE_EXPIRED", "探针授权未生效或已过期", 403)
        return grant

    async def _fixtures(self, grant: NegativeProbeGrant) -> None:
        expected = {item.project_id: item.organization_id for item in grant.fixtures}
        actual = {
            identifier: organization
            for identifier, organization in (
                await self.session.execute(
                    select(Project.id, Project.organization_id).where(Project.id.in_(expected))
                )
            ).all()
        }
        users = set(
            (
                await self.session.scalars(
                    select(User.id).where(
                        User.id.in_((grant.owner_user_id, grant.reviewer_user_id))
                    )
                )
            ).all()
        )
        machines = {
            identifier: organization
            for identifier, organization in (
                await self.session.execute(
                    select(ServiceAccount.id, ServiceAccount.organization_id).where(
                        ServiceAccount.id.in_(grant.machine_account_ids)
                    )
                )
            ).all()
        }
        valid = (
            actual == expected
            and users == {grant.owner_user_id, grant.reviewer_user_id}
            and set(machines) == set(grant.machine_account_ids)
            and set(machines.values()) <= set(expected.values())
        )
        if not valid:
            raise self_test_error(
                "SELFTEST_PROBE_FIXTURE_MISMATCH", "探针项目或角色归属已变化", 403
            )

    async def _snapshot(self, grant: NegativeProbeGrant) -> ProbeSnapshot:
        try:
            async with asyncio.timeout(5):
                await self._fixtures(grant)
                return await self._bounded_snapshot(grant)
        except TimeoutError:
            return ProbeSnapshot(0, (), ("SELFTEST_PROBE_QUERY_UNAVAILABLE",))
        except ValidationError:
            return ProbeSnapshot(0, (), ("SELFTEST_PROBE_PROJECTION_INVALID",))

    async def _bounded_snapshot(self, grant: NegativeProbeGrant) -> ProbeSnapshot:
        total, rows = await probe_rows(self.session, tuple(f.project_id for f in grant.fixtures))
        if total > 500:
            return ProbeSnapshot(total, (), ("SELFTEST_PROBE_RESOURCE_LIMIT",))
        if len(rows) != total:
            return ProbeSnapshot(total, (), ("SELFTEST_PROBE_SNAPSHOT_CHANGED",))
        enriched = await enrich_designs(self.session, rows)
        if enriched is None:
            return ProbeSnapshot(total, (), ("SELFTEST_PROBE_CONTENT_LIMIT",))
        # Count complete response DTO overhead conservatively too; page responses are smaller.
        size = sum(len(row.model_dump_json().encode()) for row in enriched) + 16384
        if size > 262144:
            return ProbeSnapshot(total, (), ("SELFTEST_PROBE_RESPONSE_LIMIT",))
        return ProbeSnapshot(total, enriched)

    @staticmethod
    def _offset(cursor: str | None, digest: str, total: int) -> int:
        if cursor is None:
            return 0
        previous, _, offset = cursor.partition(".")
        if previous != digest:
            raise self_test_error("SELFTEST_PROBE_SNAPSHOT_CHANGED", "探针分页快照已变化", 409)
        position = int(offset)
        if not 0 < position < total:
            raise self_test_error("SELFTEST_PROBE_CURSOR_INVALID", "探针分页游标无效", 422)
        return position
