from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.capabilities import CapabilityManifest, PluginManifest
from app.engine.capabilities import builtin_capability_registry
from app.models.access import User
from app.models.capabilities import Plugin, Runner, RunnerPool
from app.repositories.capabilities import CapabilityRepository


@dataclass(frozen=True, slots=True)
class CapabilityView:
    manifest: CapabilityManifest
    source: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class RunnerPoolView:
    pool: RunnerPool
    runners: tuple[Runner, ...]


class CapabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = CapabilityRepository(session)

    async def list_capabilities(
        self, *, actor: User, search: str = ""
    ) -> tuple[CapabilityView, ...]:
        del actor
        builtins = tuple(
            CapabilityView(
                manifest=manifest,
                source="builtin",
                enabled=_builtin_enabled(manifest),
            )
            for manifest in builtin_capability_registry.list()
        )
        plugin_records = await self._repository.list_plugin_capabilities()
        plugins: list[CapabilityView] = []
        for record in plugin_records:
            try:
                manifest = CapabilityManifest.model_validate(record.manifest)
            except ValidationError as error:
                raise AppError(
                    code="CAPABILITY_MANIFEST_INVALID",
                    message="已安装能力的 Manifest 无效",
                    status_code=500,
                ) from error
            plugins.append(
                CapabilityView(
                    manifest=manifest,
                    source="plugin",
                    enabled=record.enabled and settings.feature_plugin_registry_enabled,
                )
            )
        return tuple(
            item
            for item in (*builtins, *plugins)
            if _matches_inventory(
                search, item.manifest.id, item.manifest.display_name, item.manifest.version
            )
        )

    async def get_capability(
        self,
        *,
        actor: User,
        capability_id: str,
        version: str,
    ) -> CapabilityView:
        capabilities = await self.list_capabilities(actor=actor)
        for capability in capabilities:
            if capability.manifest.id == capability_id and capability.manifest.version == version:
                return capability
        raise AppError(code="CAPABILITY_NOT_FOUND", message="能力版本不存在", status_code=404)

    async def list_plugins(self, *, actor: User, search: str = "") -> list[Plugin]:
        self._require_system_admin(actor)
        return [
            item
            for item in await self._repository.list_plugins()
            if _matches_inventory(search, item.plugin_key, item.display_name, item.version)
        ]

    async def list_runner_pools(
        self, *, actor: User, search: str = ""
    ) -> tuple[RunnerPoolView, ...]:
        self._require_system_admin(actor)
        context = get_tenant_context()
        pools = await self._repository.list_runner_pools(
            organization_id=context.organization_id if context else None
        )
        views: list[RunnerPoolView] = []
        for pool in pools:
            if not _matches_inventory(search, pool.name, pool.runner_type, pool.network_zone):
                continue
            views.append(
                RunnerPoolView(
                    pool=pool,
                    runners=tuple(await self._repository.list_runners(pool.id)),
                )
            )
        return tuple(views)

    async def get_plugin(self, *, actor: User, plugin_id: UUID) -> Plugin:
        plugins = await self.list_plugins(actor=actor)
        for plugin in plugins:
            if plugin.id == plugin_id:
                return plugin
        raise AppError(code="PLUGIN_NOT_FOUND", message="插件不存在", status_code=404)

    async def get_runner_pool(self, *, actor: User, pool_id: UUID) -> RunnerPoolView:
        pools = await self.list_runner_pools(actor=actor)
        for pool in pools:
            if pool.pool.id == pool_id:
                return pool
        raise AppError(code="RUNNER_POOL_NOT_FOUND", message="Runner Pool 不存在", status_code=404)

    @staticmethod
    def validate_plugin_manifest(*, actor: User, payload: object) -> PluginManifest:
        CapabilityService._require_system_admin(actor)
        if not settings.feature_plugin_registry_enabled:
            raise AppError(
                code="PLUGIN_REGISTRY_DISABLED",
                message="插件注册能力尚未启用",
                status_code=409,
            )
        try:
            return PluginManifest.model_validate(payload)
        except ValidationError as error:
            raise AppError(
                code="INVALID_PLUGIN_MANIFEST",
                message="插件 Manifest 无效",
                status_code=422,
                details={"errors": error.errors(include_url=False)},
            ) from error

    @staticmethod
    def _require_system_admin(actor: User) -> None:
        if not actor.is_system_admin:
            raise AppError(
                code="SYSTEM_ADMIN_REQUIRED",
                message="需要系统管理员权限",
                status_code=403,
            )


def _builtin_enabled(manifest: CapabilityManifest) -> bool:
    if manifest.version == "1.0.0" and manifest.id.startswith("flow.control."):
        return True
    if manifest.version == "3.0.0" and manifest.id.startswith(("kafka.", "websocket.")):
        return (
            settings.feature_capability_sdk_enabled
            and settings.feature_multi_protocol_enabled
            and settings.feature_event_protocols_enabled
        )
    if manifest.version == "3.0.0" and manifest.id in {"graphql.request", "grpc.call"}:
        return settings.feature_capability_sdk_enabled and settings.feature_multi_protocol_enabled
    return settings.feature_capability_sdk_enabled


def _matches_inventory(search: str, *values: str) -> bool:
    needle = search.strip().casefold()
    return not needle or any(needle in value.casefold() for value in values)
