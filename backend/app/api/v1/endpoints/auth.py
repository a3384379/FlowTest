from typing import Annotated

from fastapi import APIRouter, Cookie, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.dependencies import AuthenticatedUser, OIDCProviderDependency, SessionDependency
from app.core.config import settings
from app.core.errors import AppError
from app.schemas.access import (
    AccessTokenResponse,
    LoginRequest,
    LoginResponse,
    OIDCStatusResponse,
    PasswordChange,
    UserResponse,
)
from app.services.auth import AuthService, TokenPair
from app.services.oidc import OIDCConfiguration, OIDCService

router = APIRouter(prefix="/auth")
REFRESH_COOKIE_NAME = "flowtest_refresh"


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest, response: Response, session: SessionDependency, request: Request
) -> LoginResponse:
    _check_auth_origin(request, allow_json=True)
    pair = await AuthService(session).login(email=payload.email, password=payload.password)
    _set_refresh_cookie(response, pair.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return _login_response(pair)


@router.get("/oidc/status", response_model=OIDCStatusResponse)
async def oidc_status() -> OIDCStatusResponse:
    return OIDCStatusResponse(
        enabled=settings.feature_oidc_enabled,
        provider=settings.oidc_provider_name if settings.feature_oidc_enabled else None,
    )


@router.get("/oidc/login", response_class=RedirectResponse)
async def oidc_login(
    session: SessionDependency,
    provider: OIDCProviderDependency,
) -> RedirectResponse:
    login_start = await OIDCService(
        session,
        provider=provider,
        configuration=OIDCConfiguration.from_settings(settings),
    ).start_login()
    return RedirectResponse(
        login_start.authorization_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )


@router.get("/oidc/callback", response_class=RedirectResponse)
async def oidc_callback(
    session: SessionDependency,
    provider: OIDCProviderDependency,
    state_value: str = Query(alias="state", min_length=1, max_length=512),
    code: str = Query(min_length=1, max_length=4096),
) -> RedirectResponse:
    pair = await OIDCService(
        session,
        provider=provider,
        configuration=OIDCConfiguration.from_settings(settings),
    ).complete_login(state=state_value, code=code)
    response = RedirectResponse(
        settings.oidc_frontend_success_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _set_refresh_cookie(response, pair.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_access_token(
    response: Response,
    session: SessionDependency,
    request: Request,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> AccessTokenResponse:
    _check_auth_origin(request)
    if refresh_token is None:
        raise AppError(code="INVALID_REFRESH_TOKEN", message="登录状态已失效", status_code=401)
    pair = await AuthService(session).rotate(refresh_token)
    _set_refresh_cookie(response, pair.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return AccessTokenResponse(
        access_token=pair.access_token,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: SessionDependency,
    request: Request,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    _check_auth_origin(request)
    await AuthService(session).logout(refresh_token)
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=UserResponse)
async def me(current_user: AuthenticatedUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange,
    session: SessionDependency,
    current_user: AuthenticatedUser,
) -> None:
    await AuthService(session).change_password(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )


def _check_auth_origin(request: Request, *, allow_json: bool = False) -> None:
    origin = request.headers.get("origin")
    if origin is not None:
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        if origin == same_origin or origin in settings.cors_origins:
            return
    elif request.headers.get("x-requested-with") == "FlowTest" or (
        allow_json
        and request.headers.get("content-type", "").split(";", 1)[0] == "application/json"
    ):
        return
    raise AppError(code="CSRF_VALIDATION_FAILED", message="请求来源不可信", status_code=403)


def _login_response(pair: TokenPair) -> LoginResponse:
    return LoginResponse(
        access_token=pair.access_token,
        expires_in=settings.access_token_minutes * 60,
        user=UserResponse.model_validate(pair.user),
    )
