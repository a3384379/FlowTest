from fastapi import APIRouter

from app.api.v1.endpoints.api_assets import router as api_assets_router
from app.api.v1.endpoints.artifacts import router as artifacts_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.executions import router as executions_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.imports import router as imports_router
from app.api.v1.endpoints.projects import router as projects_router
from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(workflows_router, tags=["workflows"])
api_router.include_router(executions_router, tags=["executions"])
api_router.include_router(imports_router, tags=["imports"])
api_router.include_router(artifacts_router, tags=["files"])
api_router.include_router(api_assets_router, tags=["api-assets"])
api_router.include_router(users_router, tags=["users"])
api_router.include_router(projects_router, tags=["projects"])
