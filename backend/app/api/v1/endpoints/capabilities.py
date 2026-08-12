from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.config import settings
from app.schemas.capabilities import (
    CapabilityResponse,
    PluginManifestValidationRequest,
    PluginManifestValidationResponse,
    PluginResponse,
    RunnerPoolResponse,
    RunnerResponse,
    V3FeatureFlagsResponse,
)
from app.schemas.common import Page
from app.services.capabilities import CapabilityService, CapabilityView

router = APIRouter()


@router.get("/v3/features", response_model=V3FeatureFlagsResponse)
async def get_v3_feature_flags(current_user: CurrentUser) -> V3FeatureFlagsResponse:
    del current_user
    return V3FeatureFlagsResponse(
        capability_sdk=settings.feature_capability_sdk_enabled,
        plugin_registry=settings.feature_plugin_registry_enabled,
        runner_fabric=settings.feature_runner_fabric_enabled,
        multi_protocol=settings.feature_multi_protocol_enabled,
        event_protocols=settings.feature_event_protocols_enabled,
        performance_lab=settings.feature_performance_lab_enabled,
        environment_lab=settings.feature_environment_lab_enabled,
        contract_hub=settings.feature_contract_hub_enabled,
        impact_engine=settings.feature_impact_engine_enabled,
        quality_intelligence=settings.feature_quality_intelligence_enabled,
        pact_broker=bool(settings.pact_broker_base_url),
    )


@router.get("/capabilities", response_model=Page[CapabilityResponse])
async def list_capabilities(
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[CapabilityResponse]:
    capabilities = await CapabilityService(session).list_capabilities(actor=current_user)
    start = (page - 1) * page_size
    selected = capabilities[start : start + page_size]
    return Page(
        items=[_capability_response(item) for item in selected],
        total=len(capabilities),
        page=page,
        page_size=page_size,
    )


@router.get(
    "/capabilities/{capability_id}/versions/{version}",
    response_model=CapabilityResponse,
)
async def get_capability(
    capability_id: str,
    version: str,
    session: SessionDependency,
    current_user: CurrentUser,
) -> CapabilityResponse:
    capability = await CapabilityService(session).get_capability(
        actor=current_user,
        capability_id=capability_id,
        version=version,
    )
    return _capability_response(capability)


@router.get("/plugins", response_model=Page[PluginResponse])
async def list_plugins(
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[PluginResponse]:
    plugins = await CapabilityService(session).list_plugins(actor=current_user)
    start = (page - 1) * page_size
    selected = plugins[start : start + page_size]
    return Page(
        items=[PluginResponse.model_validate(item) for item in selected],
        total=len(plugins),
        page=page,
        page_size=page_size,
    )


@router.post("/plugins/manifests/validate", response_model=PluginManifestValidationResponse)
async def validate_plugin_manifest(
    payload: PluginManifestValidationRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> PluginManifestValidationResponse:
    manifest = CapabilityService(session).validate_plugin_manifest(
        actor=current_user,
        payload=payload.manifest,
    )
    return PluginManifestValidationResponse(manifest=manifest)


@router.get("/runner-pools", response_model=Page[RunnerPoolResponse])
async def list_runner_pools(
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[RunnerPoolResponse]:
    pools = await CapabilityService(session).list_runner_pools(actor=current_user)
    start = (page - 1) * page_size
    selected = pools[start : start + page_size]
    return Page(
        items=[
            RunnerPoolResponse(
                id=view.pool.id,
                name=view.pool.name,
                runner_type=view.pool.runner_type,
                network_zone=view.pool.network_zone,
                labels=view.pool.labels,
                max_concurrency=view.pool.max_concurrency,
                enabled=view.pool.enabled,
                runners=[RunnerResponse.model_validate(item) for item in view.runners],
            )
            for view in selected
        ],
        total=len(pools),
        page=page,
        page_size=page_size,
    )


def _capability_response(view: CapabilityView) -> CapabilityResponse:
    manifest = view.manifest
    return CapabilityResponse(
        id=manifest.id,
        version=manifest.version,
        category=manifest.category.value,
        display_name=manifest.display_name,
        description=manifest.description,
        runner_type=manifest.runner_type.value,
        network_access=manifest.network_policy.access.value,
        schema_hash=manifest.schema_hash,
        source=view.source,
        enabled=view.enabled,
        plugin_id=manifest.plugin_id,
        plugin_digest=manifest.plugin_digest,
        manifest=manifest,
    )
