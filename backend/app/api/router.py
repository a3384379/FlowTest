from fastapi import APIRouter

from app.api.v1.endpoints.ai import router as ai_router
from app.api.v1.endpoints.api_assets import router as api_assets_router
from app.api.v1.endpoints.api_exports import router as api_exports_router
from app.api.v1.endpoints.artifacts import router as artifacts_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.capabilities import router as capabilities_router
from app.api.v1.endpoints.contract_hub import router as contract_hub_router
from app.api.v1.endpoints.contracts import router as contracts_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.data_sources import mock_dispatch_router
from app.api.v1.endpoints.data_sources import router as data_sources_router
from app.api.v1.endpoints.environment_lab import router as environment_lab_router
from app.api.v1.endpoints.event_protocols import router as event_protocols_router
from app.api.v1.endpoints.executions import router as executions_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.impact import router as impact_router
from app.api.v1.endpoints.imports import router as imports_router
from app.api.v1.endpoints.maintenance import router as maintenance_router
from app.api.v1.endpoints.performance import router as performance_router
from app.api.v1.endpoints.projects import router as projects_router
from app.api.v1.endpoints.protocols import router as protocols_router
from app.api.v1.endpoints.quality import router as quality_router
from app.api.v1.endpoints.reporting import router as reporting_router
from app.api.v1.endpoints.tasking import router as tasking_router
from app.api.v1.endpoints.teams import router as teams_router
from app.api.v1.endpoints.test_assets import router as test_assets_router
from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.workflow_events import router as workflow_events_router
from app.api.v1.endpoints.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(capabilities_router, tags=["capabilities"])
api_router.include_router(ai_router, tags=["ai"])
api_router.include_router(contracts_router, tags=["contracts"])
api_router.include_router(contract_hub_router, tags=["contract-hub"])
api_router.include_router(dashboard_router, tags=["dashboard"])
api_router.include_router(data_sources_router, tags=["data-sources"])
api_router.include_router(mock_dispatch_router, tags=["mock-dispatch"])
api_router.include_router(workflows_router, tags=["workflows"])
api_router.include_router(workflow_events_router, tags=["workflow-events"])
api_router.include_router(executions_router, tags=["executions"])
api_router.include_router(event_protocols_router, tags=["event-protocols"])
api_router.include_router(environment_lab_router, tags=["environment-lab"])
api_router.include_router(imports_router, tags=["imports"])
api_router.include_router(impact_router, tags=["impact"])
api_router.include_router(maintenance_router, tags=["maintenance"])
api_router.include_router(performance_router, tags=["performance"])
api_router.include_router(artifacts_router, tags=["files"])
api_router.include_router(api_assets_router, tags=["api-assets"])
api_router.include_router(api_exports_router, tags=["api-exports"])
api_router.include_router(users_router, tags=["users"])
api_router.include_router(projects_router, tags=["projects"])
api_router.include_router(protocols_router, tags=["protocols"])
api_router.include_router(quality_router, tags=["quality"])
api_router.include_router(tasking_router, tags=["tasking"])
api_router.include_router(teams_router, tags=["teams"])
api_router.include_router(test_assets_router, tags=["test-assets"])
api_router.include_router(reporting_router, tags=["reports"])
