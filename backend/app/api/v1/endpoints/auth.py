from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.api.dependencies import AuthenticatedUser, SessionDependency
from app.core.config import settings
from app.core.errors import AppError
from app.schemas.access import (
    AccessTokenResponse,
    LoginRequest,
    LoginResponse,
    PasswordChange,
    UserResponse,
)
from app.services.auth import AuthService, TokenPair

router = APIRouter(prefix="/auth")
REFRESH_COOKIE_NAME = "flowtest_refresh"


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest, response: Response, session: SessionDependency
) -> LoginResponse:
    pair = await AuthService(session).login(email=payload.email, password=payload.password)
    _set_refresh_cookie(response, pair.refresh_token)
    return _login_response(pair)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_access_token(
    response: Response,
    session: SessionDependency,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> AccessTokenResponse:
    if refresh_token is None:
        raise AppError(code="INVALID_REFRESH_TOKEN", message="登录状态已失效", status_code=401)
    pair = await AuthService(session).rotate(refresh_token)
    _set_refresh_cookie(response, pair.refresh_token)
    return AccessTokenResponse(
        access_token=pair.access_token,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: SessionDependency,
    current_user: AuthenticatedUser,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    await AuthService(session).logout(refresh_token, actor_user_id=current_user.id)
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )


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


def _login_response(pair: TokenPair) -> LoginResponse:
    return LoginResponse(
        access_token=pair.access_token,
        expires_in=settings.access_token_minutes * 60,
        user=UserResponse.model_validate(pair.user),
    )
