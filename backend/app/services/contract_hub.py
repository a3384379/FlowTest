from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.contract_hub import (
    PactBrokerSource,
    PactContractError,
    PactDocument,
    PactTransportError,
    ProviderInteractionVerifier,
    load_pact_document,
    normalize_contract_origin,
    service_key_for_name,
)
from app.models.access import User
from app.models.contracts import (
    ContractRun,
    DeploymentCompatibilityCheck,
    PactContractVersion,
    PactProviderVerification,
    ServiceCatalogEntry,
)
from app.repositories.contract_hub import ContractHubRepository
from app.schemas.contract_hub import (
    CompatibilityCell,
    CompatibilityMatrixResponse,
    CompatibilityRow,
    ContractHubSummaryResponse,
    PactContractResponse,
    ServiceCatalogCreate,
    ServiceGraphEdge,
    ServiceGraphNode,
    ServiceGraphResponse,
)
from app.services.audit import AuditService
from app.services.projects import ProjectService


@dataclass(frozen=True, slots=True)
class PactContractView:
    contract: PactContractVersion
    consumer: ServiceCatalogEntry
    provider: ServiceCatalogEntry


class ContractHubService:
    def __init__(self, session: AsyncSession, *, enabled: bool, broker_available: bool) -> None:
        self._session = session
        self._enabled = enabled
        self._broker_available = broker_available
        self._repository = ContractHubRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create_service(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: ServiceCatalogCreate,
    ) -> ServiceCatalogEntry:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        if await self._repository.find_service_by_key(
            project_id=project_id, service_key=payload.service_key
        ) or await self._repository.find_service_by_name(
            project_id=project_id, display_name=payload.display_name
        ):
            raise AppError(
                code="SERVICE_CATALOG_ENTRY_EXISTS",
                message="服务标识或显示名称已存在",
                status_code=409,
            )
        model = ServiceCatalogEntry(
            project_id=project_id,
            service_key=payload.service_key,
            display_name=payload.display_name,
            description=payload.description,
            created_by_id=actor.id,
        )
        self._repository.add_service(model)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="contract_hub.service_created",
            resource_type="service_catalog_entry",
            resource_id=model.id,
            details={"service_key": model.service_key},
        )
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def list_services(self, *, actor: User, project_id: UUID) -> list[ServiceCatalogEntry]:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_services(project_id=project_id)

    async def import_pact(
        self,
        *,
        actor: User,
        project_id: UUID,
        consumer_version: str,
        source_name: str,
        source_type: str,
        content: bytes,
        expected_consumer: str | None = None,
        expected_provider: str | None = None,
    ) -> PactContractView:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        pact = _load_pact(content)
        if expected_consumer is not None and pact.consumer != expected_consumer:
            raise AppError(
                code="PACT_BROKER_COORDINATE_MISMATCH",
                message="Broker 返回的 Consumer 与请求不一致",
                status_code=422,
            )
        if expected_provider is not None and pact.provider != expected_provider:
            raise AppError(
                code="PACT_BROKER_COORDINATE_MISMATCH",
                message="Broker 返回的 Provider 与请求不一致",
                status_code=422,
            )
        existing = await self._repository.find_pact_by_hash(
            project_id=project_id,
            consumer_version=consumer_version,
            content_sha256=pact.sha256,
        )
        if existing is not None:
            return await self._view(existing)
        consumer = await self._get_or_create_service(actor, project_id, pact.consumer)
        provider = await self._get_or_create_service(actor, project_id, pact.provider)
        model = PactContractVersion(
            project_id=project_id,
            consumer_service_id=consumer.id,
            provider_service_id=provider.id,
            consumer_version=consumer_version.strip(),
            pact_specification_version=pact.specification_version,
            source_type=source_type,
            source_name=source_name.strip()[:255] or "pact.json",
            content_sha256=pact.sha256,
            contract_document=pact.model_dump(mode="json"),
            interaction_count=len(pact.interactions),
            created_by_id=actor.id,
        )
        self._repository.add_pact(model)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="contract_hub.pact_imported",
            resource_type="pact_contract_version",
            resource_id=model.id,
            details={
                "consumer_service_id": str(consumer.id),
                "provider_service_id": str(provider.id),
                "consumer_version": model.consumer_version,
                "source_type": source_type,
                "content_sha256": pact.sha256,
            },
        )
        await self._session.commit()
        await self._session.refresh(model)
        return PactContractView(model, consumer, provider)

    async def import_from_broker(
        self,
        *,
        actor: User,
        project_id: UUID,
        consumer: str,
        provider: str,
        consumer_version: str,
        broker: PactBrokerSource | None,
    ) -> PactContractView:
        self._require_enabled()
        if not self._broker_available or broker is None:
            raise AppError(
                code="PACT_BROKER_DISABLED",
                message="Pact Broker 未配置",
                status_code=409,
            )
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        policy = await self._projects.load_runtime_security_policy(project_id)
        try:
            content = await broker.fetch_pact(
                consumer=consumer,
                provider=provider,
                consumer_version=consumer_version,
                network_policy=policy,
            )
        except PactTransportError as error:
            raise AppError(code=error.code, message=error.message, status_code=502) from error
        return await self.import_pact(
            actor=actor,
            project_id=project_id,
            consumer_version=consumer_version,
            source_name=f"broker:{consumer}:{provider}:{consumer_version}",
            source_type="broker",
            content=content,
            expected_consumer=consumer,
            expected_provider=provider,
        )

    async def list_pacts(self, *, actor: User, project_id: UUID) -> list[PactContractView]:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        contracts = await self._repository.list_pacts(project_id=project_id)
        return [await self._view(item) for item in contracts]

    async def verify_provider(
        self,
        *,
        actor: User,
        project_id: UUID,
        pact_id: UUID,
        provider_version: str,
        target_base_url: str,
        verifier: ProviderInteractionVerifier,
    ) -> PactProviderVerification:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        model = await self._project_pact(project_id, pact_id)
        pact = _stored_pact(model)
        policy = await self._projects.load_runtime_security_policy(project_id)
        try:
            normalized_target = normalize_contract_origin(target_base_url)
            evidence = await verifier.verify(
                target_base_url=normalized_target,
                pact=pact,
                network_policy=policy,
            )
        except PactTransportError as error:
            raise AppError(code=error.code, message=error.message, status_code=422) from error
        results = [
            cast(dict[str, JsonValue], item.model_dump(mode="json"))
            for item in evidence.interaction_results
        ]
        passed_count = sum(item.status == "passed" for item in evidence.interaction_results)
        verification = PactProviderVerification(
            project_id=project_id,
            pact_contract_version_id=model.id,
            provider_version=provider_version.strip(),
            target_base_url=normalized_target,
            status=evidence.status,
            interaction_count=len(evidence.interaction_results),
            passed_count=passed_count,
            failed_count=len(evidence.interaction_results) - passed_count,
            results=results,
            verified_by_id=actor.id,
            created_at=datetime.now(UTC),
        )
        self._repository.add_verification(verification)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="contract_hub.provider_verified",
            resource_type="pact_provider_verification",
            resource_id=verification.id,
            details={
                "pact_contract_version_id": str(model.id),
                "provider_version": verification.provider_version,
                "status": verification.status,
                "failed_count": verification.failed_count,
            },
        )
        await self._session.commit()
        await self._session.refresh(verification)
        return verification

    async def summary(self, *, actor: User, project_id: UUID) -> ContractHubSummaryResponse:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        services = await self._repository.list_services(project_id=project_id)
        openapi_count, pact_count = await self._repository.contract_counts(project_id=project_id)
        pacts = await self._repository.list_pacts(project_id=project_id)
        verifications = await self._repository.list_verifications(project_id=project_id)
        latest = _latest_verifications(verifications)
        pending = sum(item.id not in latest for item in pacts)
        failed = sum(
            item.status == "failed" for item in _latest_verifications_by_version(verifications)
        )
        return ContractHubSummaryResponse(
            service_count=len(services),
            openapi_contract_count=openapi_count,
            pact_contract_count=pact_count,
            pending_verification_count=pending,
            failed_verification_count=failed,
            breaking_change_count=await self._repository.breaking_change_count(
                project_id=project_id
            ),
            broker_available=self._broker_available,
        )

    async def service_graph(self, *, actor: User, project_id: UUID) -> ServiceGraphResponse:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        services = await self._repository.list_services(project_id=project_id)
        pacts = await self._repository.list_pacts(project_id=project_id)
        verifications = await self._repository.list_verifications(project_id=project_id)
        openapi_runs = await self._repository.list_openapi_runs(project_id=project_id)
        latest = _latest_verifications(verifications)
        kinds: dict[UUID, set[str]] = {service.id: set() for service in services}
        edge_contracts: dict[tuple[UUID, UUID], list[PactContractVersion]] = {}
        for pact in pacts:
            kinds[pact.consumer_service_id].add("pact")
            kinds[pact.provider_service_id].add("pact")
            edge_contracts.setdefault(
                (pact.consumer_service_id, pact.provider_service_id), []
            ).append(pact)
        for run in openapi_runs:
            if run.provider_service_id in kinds:
                kinds[run.provider_service_id].add("openapi")
        nodes = [
            ServiceGraphNode(
                id=service.id,
                service_key=service.service_key,
                display_name=service.display_name,
                contract_kinds=cast(list[Literal["openapi", "pact"]], sorted(kinds[service.id])),
            )
            for service in services
        ]
        edges: list[ServiceGraphEdge] = []
        for (consumer_id, provider_id), contracts in edge_contracts.items():
            newest = contracts[0]
            verification = latest.get(newest.id)
            edges.append(
                ServiceGraphEdge(
                    consumer_service_id=consumer_id,
                    provider_service_id=provider_id,
                    pact_contract_count=len(contracts),
                    latest_consumer_version=newest.consumer_version,
                    latest_status=verification.status if verification else "pending",
                )
            )
        return ServiceGraphResponse(nodes=nodes, edges=edges)

    async def compatibility_matrix(
        self,
        *,
        actor: User,
        project_id: UUID,
        provider_service_id: UUID,
    ) -> CompatibilityMatrixResponse:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        provider = await self._project_service(project_id, provider_service_id)
        all_pacts = await self._repository.list_pacts(project_id=project_id)
        pacts = [item for item in all_pacts if item.provider_service_id == provider_service_id]
        latest_contracts = _latest_contract_versions(pacts)
        verifications = await self._repository.list_verifications(
            project_id=project_id,
            pact_ids=[item.id for item in latest_contracts],
        )
        provider_versions = list(dict.fromkeys(item.provider_version for item in verifications))
        services = {
            item.id: item for item in await self._repository.list_services(project_id=project_id)
        }
        rows: list[CompatibilityRow] = []
        for pact in latest_contracts:
            pact_verifications = [
                item for item in verifications if item.pact_contract_version_id == pact.id
            ]
            latest_by_version = _latest_by_provider_version(pact_verifications)
            rows.append(
                CompatibilityRow(
                    pact_contract_version_id=pact.id,
                    consumer_service_id=pact.consumer_service_id,
                    consumer_name=services[pact.consumer_service_id].display_name,
                    consumer_version=pact.consumer_version,
                    cells=[
                        CompatibilityCell(
                            provider_version=version,
                            status=(
                                latest_by_version[version].status
                                if version in latest_by_version
                                else "pending"
                            ),
                            verification_id=(
                                latest_by_version[version].id
                                if version in latest_by_version
                                else None
                            ),
                            verified_at=(
                                latest_by_version[version].created_at
                                if version in latest_by_version
                                else None
                            ),
                        )
                        for version in provider_versions
                    ],
                )
            )
        return CompatibilityMatrixResponse(
            provider_service_id=provider.id,
            provider_name=provider.display_name,
            provider_versions=provider_versions,
            rows=rows,
        )

    async def deployment_check(
        self,
        *,
        actor: User,
        project_id: UUID,
        provider_service_id: UUID,
        provider_version: str,
    ) -> DeploymentCompatibilityCheck:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        provider = await self._project_service(project_id, provider_service_id)
        pacts = [
            item
            for item in await self._repository.list_pacts(project_id=project_id)
            if item.provider_service_id == provider_service_id
        ]
        latest_pacts = _latest_contract_versions(pacts)
        verifications = await self._repository.list_verifications(
            project_id=project_id,
            pact_ids=[item.id for item in latest_pacts],
        )
        blockers: list[dict[str, JsonValue]] = []
        pending: list[dict[str, JsonValue]] = []
        for pact in latest_pacts:
            candidates = [
                item
                for item in verifications
                if item.pact_contract_version_id == pact.id
                and item.provider_version == provider_version
            ]
            latest = candidates[0] if candidates else None
            item = {
                "pact_contract_version_id": str(pact.id),
                "consumer_version": pact.consumer_version,
            }
            if latest is None:
                pending.append({**item, "code": "PACT_VERIFICATION_MISSING"})
            elif latest.status == "failed":
                blockers.append(
                    {
                        **item,
                        "code": "PACT_VERIFICATION_FAILED",
                        "verification_id": str(latest.id),
                    }
                )
        openapi_runs = await self._repository.list_openapi_runs_for_provider(
            project_id=project_id,
            provider_service_id=provider_service_id,
        )
        latest_openapi = _latest_openapi_runs(openapi_runs, provider_version)
        for run in latest_openapi:
            if run.breaking_changes:
                blockers.append(
                    {
                        "code": "OPENAPI_BREAKING_CHANGE",
                        "contract_run_id": str(run.id),
                        "source_name": run.source_name,
                        "breaking_count": len(run.breaking_changes),
                    }
                )
        evaluated_count = len(latest_pacts) + len(latest_openapi)
        decision = (
            "unsafe" if blockers else "unknown" if pending or evaluated_count == 0 else "safe"
        )
        evidence: dict[str, JsonValue] = {
            "provider_name": provider.display_name,
            "provider_version": provider_version,
            "evaluated_contract_count": evaluated_count,
            "blockers": cast(list[JsonValue], blockers),
            "pending": cast(list[JsonValue], pending),
        }
        model = DeploymentCompatibilityCheck(
            project_id=project_id,
            provider_service_id=provider_service_id,
            provider_version=provider_version,
            decision=decision,
            evidence=evidence,
            checked_by_id=actor.id,
        )
        self._repository.add_deployment_check(model)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="contract_hub.deployment_checked",
            resource_type="deployment_compatibility_check",
            resource_id=model.id,
            details={
                "provider_service_id": str(provider_service_id),
                "provider_version": provider_version,
                "decision": decision,
                "blocker_count": len(blockers),
                "pending_count": len(pending),
            },
        )
        await self._session.commit()
        await self._session.refresh(model)
        return model

    async def list_deployment_checks(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[DeploymentCompatibilityCheck], int]:
        self._require_enabled()
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_deployment_checks(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def _get_or_create_service(
        self, actor: User, project_id: UUID, display_name: str
    ) -> ServiceCatalogEntry:
        existing = await self._repository.find_service_by_name(
            project_id=project_id, display_name=display_name
        )
        if existing is not None:
            return existing
        model = ServiceCatalogEntry(
            project_id=project_id,
            service_key=service_key_for_name(display_name),
            display_name=display_name,
            description="由 Pact 导入自动登记",
            created_by_id=actor.id,
        )
        self._repository.add_service(model)
        await self._session.flush()
        return model

    async def _view(self, contract: PactContractVersion) -> PactContractView:
        consumer = await self._repository.get_service(contract.consumer_service_id)
        provider = await self._repository.get_service(contract.provider_service_id)
        if consumer is None or provider is None:
            raise AppError(
                code="PACT_SERVICE_REFERENCE_INVALID",
                message="Pact 服务引用不存在",
                status_code=409,
            )
        return PactContractView(contract, consumer, provider)

    async def _project_pact(self, project_id: UUID, pact_id: UUID) -> PactContractVersion:
        model = await self._repository.get_pact(pact_id)
        if model is None or model.project_id != project_id:
            raise AppError(
                code="PACT_CONTRACT_NOT_FOUND", message="Pact 契约不存在", status_code=404
            )
        return model

    async def _project_service(self, project_id: UUID, service_id: UUID) -> ServiceCatalogEntry:
        model = await self._repository.get_service(service_id)
        if model is None or model.project_id != project_id:
            raise AppError(
                code="SERVICE_CATALOG_ENTRY_NOT_FOUND",
                message="服务目录项不存在",
                status_code=404,
            )
        return model

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise AppError(code="CONTRACT_HUB_DISABLED", message="契约中心未启用", status_code=409)


def pact_response(view: PactContractView) -> PactContractResponse:
    model = view.contract
    return PactContractResponse(
        id=model.id,
        project_id=model.project_id,
        consumer_service_id=view.consumer.id,
        consumer_name=view.consumer.display_name,
        provider_service_id=view.provider.id,
        provider_name=view.provider.display_name,
        consumer_version=model.consumer_version,
        pact_specification_version=model.pact_specification_version,
        source_type=cast(Literal["upload", "broker"], model.source_type),
        source_name=model.source_name,
        content_sha256=model.content_sha256,
        interaction_count=model.interaction_count,
        created_by_id=model.created_by_id,
        created_at=model.created_at,
    )


def _load_pact(content: bytes) -> PactDocument:
    try:
        return load_pact_document(content)
    except (PactContractError, ValidationError) as error:
        raise AppError(code="PACT_CONTRACT_INVALID", message=str(error), status_code=422) from error


def _stored_pact(model: PactContractVersion) -> PactDocument:
    try:
        return PactDocument.model_validate(model.contract_document)
    except ValidationError as error:
        raise AppError(
            code="PACT_CONTRACT_SNAPSHOT_INVALID",
            message="Pact 契约 Snapshot 无效",
            status_code=409,
        ) from error


def _latest_verifications(
    verifications: list[PactProviderVerification],
) -> dict[UUID, PactProviderVerification]:
    result: dict[UUID, PactProviderVerification] = {}
    for item in verifications:
        result.setdefault(item.pact_contract_version_id, item)
    return result


def _latest_by_provider_version(
    verifications: list[PactProviderVerification],
) -> dict[str, PactProviderVerification]:
    result: dict[str, PactProviderVerification] = {}
    for item in verifications:
        result.setdefault(item.provider_version, item)
    return result


def _latest_verifications_by_version(
    verifications: list[PactProviderVerification],
) -> list[PactProviderVerification]:
    result: dict[tuple[UUID, str], PactProviderVerification] = {}
    for item in verifications:
        result.setdefault((item.pact_contract_version_id, item.provider_version), item)
    return list(result.values())


def _latest_contract_versions(
    contracts: list[PactContractVersion],
) -> list[PactContractVersion]:
    result: dict[tuple[UUID, str], PactContractVersion] = {}
    for item in contracts:
        result.setdefault((item.consumer_service_id, item.consumer_version), item)
    return list(result.values())


def _latest_openapi_runs(runs: list[ContractRun], provider_version: str) -> list[ContractRun]:
    result: dict[str, ContractRun] = {}
    for run in runs:
        if run.provider_version not in {None, provider_version}:
            continue
        result.setdefault(run.source_name, run)
    return list(result.values())
