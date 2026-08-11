from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.core.errors import AppError
from app.services.oidc import OIDCConfiguration, OIDCIdentity, validate_https_endpoint


class HttpOIDCProvider:
    def __init__(self, configuration: OIDCConfiguration) -> None:
        self._configuration = configuration

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        discovery = await self._load_discovery()
        authorization_endpoint = _required_string(discovery, "authorization_endpoint")
        validate_https_endpoint(authorization_endpoint, production=self._configuration.production)
        query = urlencode(
            {
                "client_id": self._configuration.client_id,
                "redirect_uri": self._configuration.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._configuration.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        separator = "&" if "?" in authorization_endpoint else "?"
        return f"{authorization_endpoint}{separator}{query}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> OIDCIdentity:
        discovery = await self._load_discovery()
        token_endpoint = _required_string(discovery, "token_endpoint")
        validate_https_endpoint(token_endpoint, production=self._configuration.production)
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._configuration.redirect_uri,
            "code_verifier": code_verifier,
        }
        auth: tuple[str, str] | None = None
        if self._configuration.client_secret:
            auth = (self._configuration.client_id, self._configuration.client_secret)
        else:
            form["client_id"] = self._configuration.client_id
        token_payload = await self._post_form(token_endpoint, form=form, auth=auth)
        id_token = _required_string(token_payload, "id_token")
        claims = await self._decode_id_token(id_token, discovery=discovery)
        access_token = _optional_string(token_payload, "access_token")
        needs_userinfo = (
            _optional_string(claims, "email") is None
            or claims.get("email_verified") is not True
            or _optional_string(claims, "name") is None
        )
        if needs_userinfo and access_token is not None:
            userinfo = await self._load_userinfo(discovery, access_token=access_token)
            if _identity_string(userinfo, "sub") != _identity_string(claims, "sub"):
                raise _identity_invalid()
            for key in ("email", "email_verified", "name"):
                if key in userinfo:
                    claims[key] = userinfo[key]
        return OIDCIdentity(
            subject=_identity_string(claims, "sub"),
            email=_identity_string(claims, "email"),
            display_name=_optional_string(claims, "name") or "",
            email_verified=claims.get("email_verified") is True,
            nonce=_identity_string(claims, "nonce"),
        )

    async def _load_discovery(self) -> dict[str, Any]:
        discovery_url = validate_https_endpoint(
            f"{self._configuration.issuer_url}/.well-known/openid-configuration",
            production=self._configuration.production,
        )
        payload = await self._get_json(discovery_url)
        if _required_string(payload, "issuer").rstrip("/") != self._configuration.issuer_url:
            raise _provider_invalid()
        return payload

    async def _decode_id_token(
        self,
        id_token: str,
        *,
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.InvalidTokenError as error:
            raise _identity_invalid() from error
        algorithm = header.get("alg")
        if (
            not isinstance(algorithm, str)
            or algorithm not in self._configuration.allowed_algorithms
        ):
            raise _identity_invalid()
        jwks_uri = _required_string(discovery, "jwks_uri")
        validate_https_endpoint(jwks_uri, production=self._configuration.production)
        jwks = await self._get_json(jwks_uri)
        key = _select_jwk(jwks, kid=header.get("kid"), algorithm=algorithm)
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=[algorithm],
                audience=self._configuration.client_id,
                issuer=self._configuration.issuer_url,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            )
        except jwt.InvalidTokenError as error:
            raise _identity_invalid() from error
        return claims

    async def _load_userinfo(
        self,
        discovery: dict[str, Any],
        *,
        access_token: str,
    ) -> dict[str, Any]:
        endpoint = _required_string(discovery, "userinfo_endpoint")
        validate_https_endpoint(endpoint, production=self._configuration.production)
        return await self._get_json(endpoint, headers={"Authorization": f"Bearer {access_token}"})

    async def _get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self._configuration.request_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return _json_object(response)
        except (httpx.HTTPError, ValueError) as error:
            raise _provider_unavailable() from error

    async def _post_form(
        self,
        url: str,
        *,
        form: dict[str, str],
        auth: tuple[str, str] | None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self._configuration.request_timeout_seconds,
                follow_redirects=False,
            ) as client:
                if auth is None:
                    response = await client.post(url, data=form)
                else:
                    response = await client.post(url, data=form, auth=auth)
                response.raise_for_status()
                return _json_object(response)
        except (httpx.HTTPError, ValueError) as error:
            raise _provider_unavailable() from error


def _json_object(response: httpx.Response) -> dict[str, Any]:
    value = response.json()
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object")
    return value


def _select_jwk(jwks: dict[str, Any], *, kid: object, algorithm: str) -> Any:
    raw_keys = jwks.get("keys")
    if not isinstance(raw_keys, list):
        raise _identity_invalid()
    candidates = [
        key
        for key in raw_keys
        if isinstance(key, dict)
        and (kid is None or key.get("kid") == kid)
        and key.get("use", "sig") == "sig"
        and key.get("alg", algorithm) == algorithm
    ]
    if len(candidates) != 1:
        raise _identity_invalid()
    try:
        return jwt.PyJWK.from_dict(candidates[0], algorithm=algorithm).key
    except (jwt.PyJWKError, KeyError, ValueError) as error:
        raise _identity_invalid() from error


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise _provider_invalid()
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _identity_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise _identity_invalid()
    return value


def _provider_invalid() -> AppError:
    return AppError(code="OIDC_PROVIDER_INVALID", message="OIDC 服务配置无效", status_code=503)


def _provider_unavailable() -> AppError:
    return AppError(
        code="OIDC_PROVIDER_UNAVAILABLE", message="OIDC 服务暂时不可用", status_code=503
    )


def _identity_invalid() -> AppError:
    return AppError(code="OIDC_IDENTITY_INVALID", message="OIDC 身份校验失败", status_code=401)
