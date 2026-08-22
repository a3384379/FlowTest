from base64 import b64encode
from dataclasses import dataclass, field, replace
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.api_assets import (
    REDACTED_VALUE,
    APIVersionSpec,
    AuthKind,
    HttpMethod,
    JsonValue,
    QueryParameterSpec,
    render_json,
    render_template,
)
from app.domain.scopes import HeaderScope, ResolvedValue, VariableScope
from app.models.access import Folder, User
from app.models.api_assets import APIDefinition, APIVersion, Environment, Secret
from app.models.service_targets import Service, ServiceEndpoint
from app.repositories.access import ProjectRepository
from app.repositories.api_assets import APIAssetRepository
from app.repositories.service_targets import ServiceTargetRepository
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.request_targets import RequestTargetResolver

SYSTEM_HEADERS = {"User-Agent": "FlowTest/0.1", "Accept": "*/*"}


@dataclass(frozen=True, slots=True)
class PreparedHeader:
    name: str
    value: str
    source: HeaderScope


@dataclass(frozen=True, slots=True)
class PreparedVariable:
    name: str
    value: str
    source: VariableScope
    secret: bool


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    method: HttpMethod
    url: str
    headers: tuple[PreparedHeader, ...]
    body: JsonValue
    variables: tuple[PreparedVariable, ...]
    target_snapshot: dict[str, JsonValue] = field(default_factory=dict)


class APIAssetService:
    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._assets = APIAssetRepository(session)
        self._projects = ProjectRepository(session)
        self._project_service = ProjectService(session)
        self._targets = ServiceTargetRepository(session)
        self._target_resolver = RequestTargetResolver(session, secrets=secrets)
        self._audit = AuditService(session)
        self._secrets = secrets

    async def get_project_configuration(
        self, *, actor: User, project_id: UUID
    ) -> tuple[dict[str, str], dict[str, str]]:
        access = await self._project_service.authorize(
            actor=actor, project_id=project_id, editing=False
        )
        return access.project.variables, access.project.headers

    async def update_project_configuration(
        self,
        *,
        actor: User,
        project_id: UUID,
        variables: dict[str, str],
        headers: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        access = await self._project_service.authorize(
            actor=actor, project_id=project_id, editing=True
        )
        _validate_headers(headers)
        access.project.variables = variables
        access.project.headers = headers
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="project.configuration_updated",
            resource_type="project",
            resource_id=project_id,
        )
        await self._session.commit()
        return variables, headers

    async def list_environments(self, *, actor: User, project_id: UUID) -> list[Environment]:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._assets.list_environments(project_id)

    async def create_environment(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        base_url: str,
        variables: dict[str, str],
        headers: dict[str, str],
    ) -> Environment:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_name = name.strip()
        await self._ensure_environment_name(project_id=project_id, name=normalized_name)
        _validate_headers(headers)
        environment = Environment(
            project_id=project_id,
            name=normalized_name,
            base_url=base_url.rstrip("/"),
            variables=variables,
            headers=headers,
            created_by_id=actor.id,
        )
        self._assets.add(environment)
        await self._session.flush()
        default_service = await self._ensure_default_service(
            project_id=project_id,
            actor_id=actor.id,
        )
        environment.default_service_id = default_service.id
        self._targets.add(
            ServiceEndpoint(
                project_id=project_id,
                environment_id=environment.id,
                service_id=default_service.id,
                variant="default",
                base_url=base_url.rstrip("/"),
                created_by_id=actor.id,
            )
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="environment.created",
            resource_type="environment",
            resource_id=environment.id,
        )
        await self._session.commit()
        await self._session.refresh(environment)
        return environment

    async def update_environment(
        self,
        *,
        actor: User,
        project_id: UUID,
        environment_id: UUID,
        name: str | None,
        base_url: str | None,
        default_service_id: UUID | None,
        change_default_service: bool,
        variables: dict[str, str] | None,
        headers: dict[str, str] | None,
    ) -> Environment:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=True)
        environment = await self._get_environment(project_id, environment_id)
        if name is not None:
            normalized_name = name.strip()
            await self._ensure_environment_name(
                project_id=project_id,
                name=normalized_name,
                excluding_id=environment_id,
            )
            environment.name = normalized_name
        if base_url is not None:
            previous_base_url = environment.base_url
            environment.base_url = base_url.rstrip("/")
            await self._sync_default_endpoint(
                environment=environment,
                previous_base_url=previous_base_url,
            )
        if variables is not None:
            environment.variables = variables
        if headers is not None:
            _validate_headers(headers)
            environment.headers = headers
        if change_default_service:
            await self._change_default_service(
                project_id=project_id,
                environment=environment,
                service_id=default_service_id,
            )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="environment.updated",
            resource_type="environment",
            resource_id=environment.id,
        )
        await self._session.commit()
        await self._session.refresh(environment)
        return environment

    async def list_secrets(self, *, actor: User, project_id: UUID) -> list[Secret]:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._assets.list_secrets(project_id)

    async def write_secret(
        self,
        *,
        actor: User,
        project_id: UUID,
        environment_id: UUID | None,
        name: str,
        value: str,
    ) -> Secret:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=True)
        if environment_id is not None:
            await self._get_environment(project_id, environment_id)
        associated_data = _secret_associated_data(project_id, environment_id, name)
        encrypted = self._secrets.encrypt(value, associated_data=associated_data)
        stored = await self._assets.find_secret(
            project_id=project_id,
            environment_id=environment_id,
            name=name,
        )
        action = "secret.updated"
        if stored is None:
            stored = Secret(
                project_id=project_id,
                environment_id=environment_id,
                name=name,
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                created_by_id=actor.id,
            )
            self._assets.add(stored)
            action = "secret.created"
        else:
            stored.ciphertext = encrypted.ciphertext
            stored.nonce = encrypted.nonce
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action=action,
            resource_type="secret",
            resource_id=stored.id,
            details={
                "name": name,
                "environment_id": str(environment_id) if environment_id else None,
            },
        )
        await self._session.commit()
        await self._session.refresh(stored)
        return stored

    async def list_definitions(
        self,
        *,
        actor: User,
        project_id: UUID,
        page: int,
        page_size: int,
        search: str | None = None,
        method: str | None = None,
    ) -> tuple[list[APIDefinition], int]:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._assets.list_definitions(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
            search=search,
            method=method,
        )

    async def create_definition(
        self,
        *,
        actor: User,
        project_id: UUID,
        folder_id: UUID | None,
        service_id: UUID | None,
        name: str,
        description: str,
        request: APIVersionSpec,
    ) -> tuple[APIDefinition, APIVersion]:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=True)
        await self._validate_folder(project_id=project_id, folder_id=folder_id)
        await self._validate_service(project_id=project_id, service_id=service_id)
        definition = APIDefinition(
            project_id=project_id,
            folder_id=folder_id,
            service_id=service_id,
            name=name.strip(),
            description=description.strip(),
            current_version=1,
            is_active=True,
            created_by_id=actor.id,
        )
        self._assets.add(definition)
        await self._session.flush()
        version = self._version_model(
            definition_id=definition.id,
            version=1,
            actor_id=actor.id,
            request=request,
        )
        self._assets.add(version)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="api.created",
            resource_type="api_definition",
            resource_id=definition.id,
        )
        await self._session.commit()
        await self._session.refresh(definition)
        await self._session.refresh(version)
        return definition, version

    async def create_version(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition_id: UUID,
        request: APIVersionSpec,
    ) -> APIVersion:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=True)
        definition = await self._get_definition(project_id, definition_id)
        next_version = definition.current_version + 1
        version = self._version_model(
            definition_id=definition.id,
            version=next_version,
            actor_id=actor.id,
            request=request,
        )
        self._assets.add(version)
        definition.current_version = next_version
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="api.version_created",
            resource_type="api_definition",
            resource_id=definition.id,
            details={"version": next_version},
        )
        await self._session.commit()
        await self._session.refresh(version)
        return version

    async def update_definition(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition_id: UUID,
        name: str | None,
        description: str | None,
        folder_id: UUID | None,
        change_folder: bool,
        service_id: UUID | None,
        change_service: bool,
    ) -> APIDefinition:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=True)
        definition = await self._get_definition(project_id, definition_id)
        if name is not None:
            definition.name = name.strip()
        if description is not None:
            definition.description = description.strip()
        if change_folder:
            await self._validate_folder(project_id=project_id, folder_id=folder_id)
            definition.folder_id = folder_id
        if change_service:
            await self._validate_service(project_id=project_id, service_id=service_id)
            definition.service_id = service_id
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="api.updated",
            resource_type="api_definition",
            resource_id=definition.id,
        )
        await self._session.commit()
        await self._session.refresh(definition)
        return definition

    async def list_versions(
        self, *, actor: User, project_id: UUID, definition_id: UUID
    ) -> list[APIVersion]:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=False)
        await self._get_definition(project_id, definition_id)
        return await self._assets.list_versions(definition_id)

    async def get_detail(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition_id: UUID,
        version: int | None = None,
    ) -> tuple[APIDefinition, APIVersion]:
        await self._project_service.authorize(actor=actor, project_id=project_id, editing=False)
        definition = await self._get_definition(project_id, definition_id)
        selected_version = version or definition.current_version
        api_version = await self._assets.get_version(
            definition_id=definition_id, version=selected_version
        )
        if api_version is None:
            raise AppError(code="API_VERSION_NOT_FOUND", message="API 版本不存在", status_code=404)
        return definition, api_version

    async def preview(
        self,
        *,
        actor: User,
        project_id: UUID,
        definition_id: UUID,
        environment_id: UUID,
        runtime_variables: dict[str, str],
        runtime_headers: dict[str, str],
        body_override: JsonValue,
        use_body_override: bool,
        query_parameters_override: tuple[QueryParameterSpec, ...] | None = None,
        headers_override: dict[str, str] | None = None,
        service_override: str | None = None,
        endpoint_variant: str | None = None,
        redact: bool = True,
        version_number: int | None = None,
        workflow_variables: dict[str, str] | None = None,
        dataset_variables: dict[str, str] | None = None,
    ) -> PreparedRequest:
        _definition, api_version = await self.get_detail(
            actor=actor,
            project_id=project_id,
            definition_id=definition_id,
            version=version_number,
        )
        environment = await self._get_environment(project_id, environment_id)
        target = await self._target_resolver.resolve(
            actor=actor,
            project_id=project_id,
            environment=environment,
            definition=_definition,
            version=api_version,
            path=api_version.path,
            node_service_override=service_override,
            endpoint_variant=endpoint_variant,
            runtime_variables=runtime_variables,
            runtime_headers=runtime_headers,
            workflow_variables=workflow_variables or {},
            dataset_variables=dataset_variables or {},
        )
        variables = target.variables
        try:
            query_parameters = (
                query_parameters_override
                if query_parameters_override is not None
                else tuple(
                    QueryParameterSpec(
                        name=str(item["name"]),
                        value=str(item["value"]),
                        enabled=bool(item.get("enabled", True)),
                    )
                    for item in api_version.query_parameters
                )
            )
            query = [
                (
                    render_template(item.name, variables),
                    render_template(item.value, variables),
                )
                for item in query_parameters
                if item.enabled
            ]
            api_headers = (
                {}
                if headers_override is None
                else {
                    name: render_template(value, variables)
                    for name, value in headers_override.items()
                }
            )
            _apply_auth(
                api_version.auth_kind,
                api_version.auth_config,
                api_headers,
                query,
                variables,
            )
            if headers_override is not None:
                target = replace(
                    target,
                    headers={
                        key: value
                        for key, value in target.headers.items()
                        if HeaderScope(value.source) is not HeaderScope.API
                    },
                )
            target = self._target_resolver.finalize(
                target,
                api_headers=api_headers,
                query=query,
            )
            selected_body = (
                body_override if use_body_override else cast(JsonValue, api_version.body)
            )
            rendered_body = render_json(selected_body, variables)
        except ValueError as error:
            raise AppError(
                code="UNRESOLVED_VARIABLE", message=str(error), status_code=422
            ) from error
        prepared_headers = tuple(
            PreparedHeader(
                name=resolved.name or key,
                value=resolved.value,
                source=HeaderScope(resolved.source),
            )
            for key, resolved in target.headers.items()
        )
        secret_variable_names = {f"secret.{name}" for name in target.secret_values}
        prepared = PreparedRequest(
            method=api_version.http_method,
            url=target.effective_url,
            headers=prepared_headers,
            body=rendered_body,
            variables=tuple(
                PreparedVariable(
                    name=name,
                    value=resolved.value,
                    source=VariableScope(resolved.source),
                    secret=name in secret_variable_names,
                )
                for name, resolved in variables.items()
            ),
        )
        redacted_request = _redacted_request(
            prepared,
            secret_values=target.secret_values,
            auth_kind=AuthKind(api_version.auth_kind),
            auth_config=api_version.auth_config,
        )
        target_snapshot = target.snapshot(
            method=prepared.method,
            body=redacted_request.body,
        )
        target_snapshot = cast(
            dict[str, JsonValue],
            _redact_json(cast(JsonValue, target_snapshot), tuple(target.secret_values.values())),
        )
        target_snapshot["resolved_url"] = redacted_request.url
        target_snapshot["headers"] = {
            item.name: {"value": item.value, "source": item.source.value}
            for item in redacted_request.headers
        }
        target_snapshot["variables"] = {
            item.name: {"value": item.value, "source": item.source.value}
            for item in redacted_request.variables
        }
        target_snapshot["body"] = redacted_request.body
        prepared = replace(prepared, target_snapshot=target_snapshot)
        if not redact:
            return prepared
        return replace(redacted_request, target_snapshot=target_snapshot)

    async def _load_secret_values(
        self, *, project_id: UUID, environment_id: UUID
    ) -> dict[str, str]:
        secrets = await self._assets.secrets_for_environment(
            project_id=project_id, environment_id=environment_id
        )
        values: dict[str, str] = {}
        for stored in secrets:
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

    async def _get_environment(self, project_id: UUID, environment_id: UUID) -> Environment:
        environment = await self._assets.get_environment(environment_id)
        if environment is None or environment.project_id != project_id:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        return environment

    async def _ensure_environment_name(
        self, *, project_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        if await self._assets.find_environment_by_name(
            project_id=project_id,
            name=name,
            excluding_id=excluding_id,
        ):
            raise AppError(
                code="ENVIRONMENT_NAME_EXISTS", message="环境名称已存在", status_code=409
            )

    async def _get_definition(self, project_id: UUID, definition_id: UUID) -> APIDefinition:
        definition = await self._assets.get_definition(definition_id)
        if definition is None or definition.project_id != project_id or not definition.is_active:
            raise AppError(code="API_NOT_FOUND", message="API 不存在", status_code=404)
        return definition

    async def _validate_folder(self, *, project_id: UUID, folder_id: UUID | None) -> None:
        if folder_id is None:
            return
        folder = await self._session.get(Folder, folder_id)
        if folder is None or folder.project_id != project_id:
            raise AppError(code="FOLDER_NOT_FOUND", message="目录不存在", status_code=404)

    @staticmethod
    def _version_model(
        *, definition_id: UUID, version: int, actor_id: UUID, request: APIVersionSpec
    ) -> APIVersion:
        _validate_headers(request.headers)
        return APIVersion(
            api_definition_id=definition_id,
            version=version,
            method=request.method.value,
            path=request.path,
            query_parameters=[
                {"name": item.name, "value": item.value, "enabled": item.enabled}
                for item in request.query_parameters
            ],
            headers=request.headers,
            variables=request.variables,
            body_kind=request.body_kind.value,
            body=request.body,
            auth_kind=request.auth_kind.value,
            auth_config=request.auth_config,
            extraction_rules=[
                {
                    "name": rule.name,
                    "kind": rule.kind.value,
                    "expression": rule.expression,
                }
                for rule in request.extraction_rules
            ],
            assertions=[
                {
                    "kind": assertion.kind,
                    "operator": assertion.operator,
                    "target": assertion.target,
                    "expected": assertion.expected,
                }
                for assertion in request.assertions
            ],
            created_by_id=actor_id,
        )

    async def _ensure_default_service(self, *, project_id: UUID, actor_id: UUID) -> Service:
        service = await self._targets.find_service_by_key(
            project_id=project_id,
            service_key="default",
        )
        if service is not None:
            return service
        service = Service(
            project_id=project_id,
            service_key="default",
            name="Default Service",
            description="Legacy Environment base_url compatibility target",
            service_type="http",
            created_by_id=actor_id,
        )
        self._targets.add(service)
        await self._session.flush()
        return service

    async def _validate_service(self, *, project_id: UUID, service_id: UUID | None) -> None:
        if service_id is None:
            return
        service = await self._targets.get_service(service_id)
        if service is None or service.project_id != project_id:
            raise AppError(code="SERVICE_NOT_FOUND", message="Service 不存在", status_code=404)

    async def _sync_default_endpoint(
        self,
        *,
        environment: Environment,
        previous_base_url: str,
    ) -> None:
        service_id = environment.default_service_id
        if service_id is None:
            return
        endpoint = await self._targets.find_endpoint(
            environment_id=environment.id,
            service_id=service_id,
            variant="default",
        )
        if endpoint is not None and endpoint.base_url == previous_base_url:
            endpoint.base_url = environment.base_url
            endpoint.revision += 1

    async def _change_default_service(
        self,
        *,
        project_id: UUID,
        environment: Environment,
        service_id: UUID | None,
    ) -> None:
        if service_id is None:
            environment.default_service_id = None
            return
        service = await self._targets.get_service(service_id)
        if service is None or service.project_id != project_id:
            raise AppError(code="SERVICE_NOT_FOUND", message="Service 不存在", status_code=404)
        endpoint = await self._targets.find_endpoint(
            environment_id=environment.id,
            service_id=service.id,
            variant="default",
        )
        if endpoint is None:
            raise AppError(
                code="SERVICE_ENDPOINT_NOT_FOUND",
                message="默认 Service 尚未配置 default Endpoint",
                status_code=422,
            )
        environment.default_service_id = service.id


def _apply_auth(
    auth_kind: str,
    auth_config: dict[str, str],
    headers: dict[str, str],
    query: list[tuple[str, str]],
    variables: dict[str, ResolvedValue],
) -> None:
    if auth_kind == AuthKind.NONE.value:
        return
    if auth_kind == AuthKind.BEARER.value:
        token = render_template(auth_config.get("token", ""), variables)
        headers["Authorization"] = f"Bearer {token}"
        return
    if auth_kind == AuthKind.BASIC.value:
        username = render_template(auth_config.get("username", ""), variables)
        password = render_template(auth_config.get("password", ""), variables)
        encoded = b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return
    name = auth_config.get("name", "X-API-Key")
    value = render_template(auth_config.get("value", ""), variables)
    if auth_config.get("in", "header") == "query":
        query.append((name, value))
    else:
        headers[name] = value


def _redacted_request(
    prepared: PreparedRequest,
    *,
    secret_values: dict[str, str],
    auth_kind: AuthKind,
    auth_config: dict[str, str],
) -> PreparedRequest:
    secrets = tuple(secret_values.values())
    api_key_name = auth_config.get("name", "X-API-Key").lower()
    redacted_headers = tuple(
        PreparedHeader(
            name=header.name,
            value=(
                REDACTED_VALUE
                if header.name.lower() == "authorization"
                or (auth_kind is AuthKind.API_KEY and header.name.lower() == api_key_name)
                else _redact_text(header.value, secrets)
            ),
            source=header.source,
        )
        for header in prepared.headers
    )
    prepared_variables = tuple(
        PreparedVariable(
            name=variable.name,
            value=REDACTED_VALUE if variable.secret else _redact_text(variable.value, secrets),
            source=variable.source,
            secret=variable.secret,
        )
        for variable in prepared.variables
    )
    return PreparedRequest(
        method=prepared.method,
        url=_redact_url(prepared.url, secrets, auth_kind=auth_kind, auth_config=auth_config),
        headers=redacted_headers,
        body=_redact_json(prepared.body, secrets),
        variables=prepared_variables,
        target_snapshot=prepared.target_snapshot,
    )


def _redact_json(value: JsonValue, secrets: tuple[str, ...]) -> JsonValue:
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, list):
        return [_redact_json(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_json(item, secrets) for key, item in value.items()}
    return value


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTED_VALUE)
    return redacted


def _redact_url(
    url: str,
    secrets: tuple[str, ...],
    *,
    auth_kind: AuthKind,
    auth_config: dict[str, str],
) -> str:
    redacted = _redact_text(url, secrets)
    if auth_kind is not AuthKind.API_KEY or auth_config.get("in", "header") != "query":
        return redacted
    api_key_name = auth_config.get("name", "X-API-Key").lower()
    parsed = urlsplit(redacted)
    query = [
        (name, REDACTED_VALUE if name.lower() == api_key_name else value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _secret_associated_data(project_id: UUID, environment_id: UUID | None, name: str) -> bytes:
    environment = str(environment_id) if environment_id is not None else "project"
    return f"{project_id}:{environment}:{name}".encode()


def _validate_headers(headers: dict[str, str]) -> None:
    for name in headers:
        if not name.strip() or any(character in name for character in "\r\n:"):
            raise AppError(code="INVALID_HEADER_NAME", message="Header 名称不合法", status_code=422)
