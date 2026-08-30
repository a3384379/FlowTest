"""Application resolver for all HTTP request targets.

The resolver is intentionally the only application boundary that combines
Environment, Service, ServiceEndpoint and API target metadata.  Callers receive
typed domain data and never need to know which persistence model supplied it.
"""

from collections.abc import Sequence
from dataclasses import replace
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.api_assets import TEMPLATE_PATTERN, build_variables, render_template
from app.domain.network import OutboundNetworkPolicy
from app.domain.request_targets import ResolvedRequestTarget
from app.domain.scopes import HeaderScope, ResolvedValue
from app.domain.test_engineering import canonical_contract_service_key
from app.models.access import Project, User
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.service_targets import Service
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository

SYSTEM_HEADERS = {"User-Agent": "FlowTest/0.1", "Accept": "*/*"}


class RequestTargetResolver:
    """Resolve and finalize a request target using the S38 precedence rules."""

    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._targets = ServiceTargetRepository(session)
        self._assets = APIAssetRepository(session)
        self._secrets = secrets

    async def resolve(
        self,
        *,
        actor: User,
        project_id: UUID,
        environment: Environment,
        definition: APIDefinition,
        version: APIVersion,
        path: str,
        node_service_override: str | None,
        endpoint_variant: str | None,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        workflow_variables: dict[str, str],
        dataset_variables: dict[str, str],
        api_headers_override: dict[str, str] | None = None,
    ) -> ResolvedRequestTarget:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        service = await self._select_service(
            project_id=project_id,
            environment=environment,
            definition=definition,
            version=version,
            node_service_override=node_service_override,
        )
        endpoint = None
        endpoint_variables: dict[str, str] = {}
        endpoint_headers: dict[str, str] = {}
        endpoint_secret_refs: tuple[str, ...] = ()
        base_url = environment.base_url
        variant = endpoint_variant or "default"
        revision = 0
        endpoint_id: UUID | None = None
        connect_timeout_ms = 5000
        read_timeout_ms = 30000
        tls_verify = True
        proxy_ref: str | None = None
        if service is not None:
            endpoint = await self._targets.find_endpoint(
                environment_id=environment.id,
                service_id=service.id,
                variant=variant,
            )
            if endpoint is None:
                raise AppError(
                    code="SERVICE_ENDPOINT_NOT_FOUND",
                    message="当前环境没有配置该 Service 的 Endpoint Variant",
                    status_code=422,
                    details={"service_key": service.service_key, "variant": variant},
                )
            if not endpoint.enabled:
                raise AppError(
                    code="SERVICE_ENDPOINT_DISABLED",
                    message="当前 Service Endpoint 已停用",
                    status_code=422,
                )
            base_url = endpoint.base_url
            endpoint_variables = dict(endpoint.variables)
            endpoint_headers = dict(endpoint.headers)
            endpoint_secret_refs = tuple(endpoint.secret_refs)
            revision = endpoint.revision
            endpoint_id = endpoint.id
            connect_timeout_ms = endpoint.connect_timeout_ms
            read_timeout_ms = endpoint.read_timeout_ms
            tls_verify = endpoint.tls_verify
            proxy_ref = endpoint.proxy_ref

        selected_api_headers = (
            dict(version.headers) if api_headers_override is None else api_headers_override
        )
        api_secret_refs = _secret_refs_from_values(
            version.path,
            version.query_parameters,
            selected_api_headers,
            version.variables,
            version.body,
            version.auth_config,
        )
        allowed_secret_refs = tuple(sorted(set(endpoint_secret_refs) | set(api_secret_refs)))
        secret_values = await self._load_secret_values(
            project_id=project_id,
            environment_id=environment.id,
            allowed_refs=allowed_secret_refs,
        )
        variables = build_variables(
            global_values={},
            project_values=project.variables,
            environment_values={
                **environment.variables,
                **{f"secret.{name}": value for name, value in secret_values.items()},
            },
            service_endpoint_values=endpoint_variables,
            api_values=dict(version.variables),
            workflow_values=workflow_variables,
            dataset_values=dataset_variables,
            runtime_values=runtime_variables,
        )
        try:
            resolved_base_url = render_template(base_url, variables).rstrip("/")
            resolved_path = render_template(path, variables).lstrip("/")
            headers = self._render_headers(
                {
                    HeaderScope.SYSTEM: SYSTEM_HEADERS,
                    HeaderScope.PROJECT: project.headers,
                    HeaderScope.ENVIRONMENT: environment.headers,
                    HeaderScope.SERVICE_ENDPOINT: endpoint_headers,
                    HeaderScope.API: selected_api_headers,
                    HeaderScope.RUNTIME: runtime_headers,
                },
                variables,
            )
        except ValueError as error:
            raise AppError(
                code="UNRESOLVED_VARIABLE", message=str(error), status_code=422
            ) from error
        service_id = service.id if service is not None else None
        service_key = service.service_key if service is not None else "legacy"
        service_name = service.name if service is not None else "Legacy Environment Base URL"
        policy = OutboundNetworkPolicy(
            allowed_hosts=tuple(project.outbound_allowed_hosts),
            allowed_private_cidrs=tuple(project.outbound_allowed_private_cidrs),
            enabled=project.outbound_policy_enabled,
        ).normalized()
        return ResolvedRequestTarget(
            environment_id=environment.id,
            environment_key=environment.name,
            environment_name=environment.name,
            service_id=service_id,
            service_key=service_key,
            service_name=service_name,
            endpoint_id=endpoint_id,
            endpoint_variant=variant,
            endpoint_revision=revision,
            base_url=resolved_base_url,
            path=resolved_path,
            effective_url=f"{resolved_base_url}/{resolved_path}",
            headers=headers,
            variables=variables,
            secret_refs=allowed_secret_refs,
            connect_timeout_ms=connect_timeout_ms,
            read_timeout_ms=read_timeout_ms,
            tls_verify=tls_verify,
            proxy_ref=proxy_ref,
            outbound_policy={
                "enabled": policy.enabled,
                "allowed_hosts": list(policy.allowed_hosts),
                "allowed_private_cidrs": list(policy.allowed_private_cidrs),
            },
            secret_values=secret_values,
        )

    @staticmethod
    def finalize(
        target: ResolvedRequestTarget,
        *,
        api_headers: dict[str, str],
        query: Sequence[tuple[str, str]],
        suppressed_headers: Sequence[str] = (),
        suppressed_query_parameters: Sequence[str] = (),
        suppressed_cookies: Sequence[str] = (),
    ) -> ResolvedRequestTarget:
        headers = dict(target.headers)
        for name, value in api_headers.items():
            existing = headers.get(name.lower())
            if existing is not None and HeaderScope(existing.source) is HeaderScope.RUNTIME:
                continue
            headers[name.lower()] = ResolvedValue(
                value=value,
                source=HeaderScope.API,
                name=name,
            )
        suppressed_header_keys = {name.lower() for name in suppressed_headers}
        headers = {
            name: value for name, value in headers.items() if name not in suppressed_header_keys
        }
        if suppressed_cookies and "cookie" in headers:
            cookie_value = _suppress_cookies(
                headers["cookie"].value,
                suppressed_cookies,
            )
            if cookie_value:
                headers["cookie"] = replace(headers["cookie"], value=cookie_value)
            else:
                headers.pop("cookie", None)
        parsed = urlsplit(target.effective_url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query_pairs.extend(query)
        suppressed_query = set(suppressed_query_parameters)
        query_pairs = [(name, value) for name, value in query_pairs if name not in suppressed_query]
        effective_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query_pairs), parsed.fragment)
        )
        return replace(target, headers=headers, effective_url=effective_url)

    async def _select_service(
        self,
        *,
        project_id: UUID,
        environment: Environment,
        definition: APIDefinition,
        version: APIVersion,
        node_service_override: str | None,
    ) -> Service | None:
        service: Service | None = None
        if node_service_override:
            service = await self._targets.find_service_by_key(
                project_id=project_id,
                service_key=node_service_override,
            )
            if service is None:
                raise AppError(code="SERVICE_NOT_FOUND", message="Service 不存在", status_code=404)
        elif version_service_key := canonical_contract_service_key(version.canonical_contract):
            service = await self._targets.find_service_by_key(
                project_id=project_id,
                service_key=version_service_key,
            )
            if service is None:
                raise AppError(code="SERVICE_NOT_FOUND", message="Service 不存在", status_code=404)
        elif definition.service_id is not None:
            service = await self._targets.get_service(definition.service_id)
        elif environment.default_service_id is not None:
            service = await self._targets.get_service(environment.default_service_id)
        if service is not None:
            if service.project_id != project_id:
                raise AppError(code="SERVICE_NOT_FOUND", message="Service 不存在", status_code=404)
            if not service.enabled:
                raise AppError(code="SERVICE_DISABLED", message="Service 已停用", status_code=422)
        return service

    async def _load_secret_values(
        self,
        *,
        project_id: UUID,
        environment_id: UUID,
        allowed_refs: tuple[str, ...],
    ) -> dict[str, str]:
        secrets = await self._assets.secrets_for_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        allowed = set(allowed_refs)
        values: dict[str, str] = {}
        for stored in secrets:
            if stored.name not in allowed:
                continue
            associated_data = _secret_associated_data(
                project_id,
                stored.environment_id,
                stored.name,
            )
            values[stored.name] = self._secrets.decrypt(
                EncryptedValue(ciphertext=stored.ciphertext, nonce=stored.nonce),
                associated_data=associated_data,
            )
        return values

    @staticmethod
    def _render_headers(
        layers: dict[HeaderScope, dict[str, str]],
        variables: dict[str, ResolvedValue],
    ) -> dict[str, ResolvedValue]:
        resolved: dict[str, ResolvedValue] = {}
        for scope in HeaderScope:
            for name, value in layers.get(scope, {}).items():
                resolved[name.lower()] = ResolvedValue(
                    value=render_template(value, variables),
                    source=scope,
                    name=name,
                )
        return resolved


def _secret_associated_data(project_id: UUID, environment_id: UUID | None, name: str) -> bytes:
    environment = str(environment_id) if environment_id is not None else "project"
    return f"{project_id}:{environment}:{name}".encode()


def _secret_refs_from_values(*values: object) -> tuple[str, ...]:
    refs: set[str] = set()
    for value in values:
        _collect_secret_refs(value, refs)
    return tuple(sorted(refs))


def _collect_secret_refs(value: object, refs: set[str]) -> None:
    if isinstance(value, str):
        for name in TEMPLATE_PATTERN.findall(value):
            if name.startswith("secret.") and len(name) > len("secret."):
                refs.add(name.removeprefix("secret."))
        return
    if isinstance(value, dict):
        for child in value.values():
            _collect_secret_refs(child, refs)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _collect_secret_refs(child, refs)


def _suppress_cookies(value: str, names: Sequence[str]) -> str:
    cookie = SimpleCookie()
    try:
        cookie.load(value)
    except CookieError as error:
        raise ValueError("Cookie header cannot be safely parsed for suppression") from error
    if value.strip() and not cookie:
        raise ValueError("Cookie header cannot be safely parsed for suppression")
    suppressed = set(names)
    return "; ".join(
        f"{name}={morsel.coded_value}" for name, morsel in cookie.items() if name not in suppressed
    )
