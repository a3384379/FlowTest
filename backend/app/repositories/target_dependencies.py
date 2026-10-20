from dataclasses import replace
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import Row, Select, SQLColumnExpression, Text, func, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.api_assets import JsonValue
from app.domain.target_dependencies import (
    DependencyAPI,
    DependencyAPIVersion,
    DependencyCaseRef,
    DependencyCaseVersion,
    DependencyEndpoint,
    DependencyEnvironment,
    DependencyPlan,
    DependencyPlanItem,
    DependencyReleasePolicy,
    DependencyService,
    DependencySuiteVersion,
    DependencyWorkflow,
    DependencyWorkflowVersion,
    TargetDependencyCatalog,
)
from app.domain.target_preview import (
    PreviewAPIChange,
    PreviewEndpointChange,
    PreviewEnvironmentChange,
    TargetPreviewCommand,
)
from app.models.api_assets import APIDefinition, APIVersion, Environment
from app.models.release_gate import ReleasePolicy
from app.models.service_targets import Service, ServiceEndpoint
from app.models.tasking import TestPlan, TestPlanItem
from app.models.test_assets import (
    TestCase,
    TestCaseVersion,
    TestSuite,
    TestSuiteVersion,
    TestSuiteVersionItem,
)
from app.models.workflows import Workflow, WorkflowVersion


class TargetDependencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(
        self, project_id: UUID, command: TargetPreviewCommand
    ) -> TargetDependencyCatalog:
        truncated: list[str] = []
        change = command.change
        api_hint = change.api_id if isinstance(change, PreviewAPIChange) else command.api_id
        service_hint = change.service_id if not isinstance(change, PreviewEndpointChange) else None
        endpoint_hint = change.endpoint_id if isinstance(change, PreviewEndpointChange) else None
        environment_hint = (
            change.environment_id
            if isinstance(change, PreviewEnvironmentChange)
            else command.environment_id
        )
        apis = await self._rows(
            select(
                APIDefinition.id,
                APIDefinition.name,
                APIDefinition.current_version,
                APIDefinition.is_active,
            )
            .where(APIDefinition.project_id == project_id)
            .order_by(APIDefinition.id != api_hint, APIDefinition.id),
            "接口目录",
            truncated,
        )
        api_versions = await self._rows(
            select(APIVersion.api_definition_id, APIVersion.version, APIVersion.service_id)
            .join(APIDefinition)
            .where(APIDefinition.project_id == project_id)
            .order_by(APIVersion.api_definition_id != api_hint, APIVersion.id),
            "接口版本",
            truncated,
            20000,
        )
        endpoints = await self._rows(
            select(
                ServiceEndpoint.id,
                ServiceEndpoint.environment_id,
                ServiceEndpoint.service_id,
                ServiceEndpoint.variant,
            )
            .where(ServiceEndpoint.project_id == project_id)
            .order_by(ServiceEndpoint.id != endpoint_hint, ServiceEndpoint.id),
            "地址目录",
            truncated,
            20000,
        )
        candidate_endpoint = next((item for item in endpoints if item[0] == endpoint_hint), None)
        if candidate_endpoint is not None:
            _endpoint_id, environment_hint, service_hint, _variant = candidate_endpoint
        environments = await self._rows(
            select(Environment.id, Environment.default_service_id)
            .where(Environment.project_id == project_id)
            .order_by(Environment.id != environment_hint, Environment.id),
            "环境目录",
            truncated,
        )
        services = await self._rows(
            select(Service.id, Service.service_key)
            .where(Service.project_id == project_id)
            .order_by(Service.id != service_hint, Service.id),
            "服务目录",
            truncated,
        )
        workflows = await self._definitions(
            select(Workflow).where(Workflow.project_id == project_id).order_by(Workflow.id),
            Workflow.id,
            Workflow.draft_definition,
            "流程目录",
            truncated,
        )
        workflow_versions = await self._definitions(
            select(WorkflowVersion)
            .join(Workflow)
            .where(Workflow.project_id == project_id)
            .order_by(WorkflowVersion.id),
            WorkflowVersion.id,
            WorkflowVersion.definition,
            "流程版本",
            truncated,
        )
        cases = await self._definitions(
            select(TestCaseVersion)
            .join(TestCase)
            .where(TestCase.project_id == project_id)
            .order_by(TestCaseVersion.id),
            TestCaseVersion.id,
            TestCaseVersion.definition,
            "用例版本",
            truncated,
        )
        suites = await self._rows(
            select(TestSuiteVersion.id, TestSuiteVersion.test_suite_id, TestSuiteVersion.version)
            .join(TestSuite)
            .where(TestSuite.project_id == project_id)
            .order_by(TestSuiteVersion.id),
            "套件版本",
            truncated,
            20000,
        )
        suite_items = await self._rows(
            select(
                TestSuiteVersionItem.test_suite_version_id,
                TestSuiteVersionItem.test_case_id,
                TestSuiteVersionItem.test_case_version,
            )
            .join(TestSuiteVersion)
            .join(TestSuite)
            .where(TestSuite.project_id == project_id)
            .order_by(TestSuiteVersionItem.position, TestSuiteVersionItem.id),
            "套件成员",
            truncated,
            20000,
        )
        plans = await self._rows(
            select(
                TestPlan.id,
                TestPlan.name,
                TestPlan.enabled,
                TestPlan.schedule_interval_seconds,
                TestPlan.schedule_cron,
            )
            .where(TestPlan.project_id == project_id)
            .order_by(TestPlan.id),
            "测试计划",
            truncated,
        )
        plan_items = await self._rows(
            select(
                TestPlanItem.test_plan_id,
                TestPlanItem.target_type,
                TestPlanItem.target_id,
                TestPlanItem.target_version,
                TestPlanItem.workflow_id,
                TestPlanItem.workflow_version,
                TestPlanItem.environment_id,
            )
            .join(TestPlan)
            .where(TestPlan.project_id == project_id)
            .order_by(TestPlanItem.position, TestPlanItem.id),
            "计划成员",
            truncated,
            20000,
        )
        policies = await self._rows(
            select(ReleasePolicy.id, ReleasePolicy.name)
            .where(ReleasePolicy.project_id == project_id, ReleasePolicy.enabled.is_(True))
            .order_by(ReleasePolicy.id),
            "发布策略",
            truncated,
        )
        return TargetDependencyCatalog(
            apis=tuple(
                DependencyAPI(identifier, name, version, active)
                for identifier, name, version, active in apis
            ),
            api_versions=tuple(
                DependencyAPIVersion(identifier, version, service_id)
                for identifier, version, service_id in api_versions
            ),
            environments=tuple(
                DependencyEnvironment(identifier, service_id)
                for identifier, service_id in environments
            ),
            services=tuple(DependencyService(identifier, key) for identifier, key in services),
            endpoints=tuple(
                DependencyEndpoint(identifier, environment_id, service_id, variant)
                for identifier, environment_id, service_id, variant in endpoints
            ),
            workflows=tuple(
                DependencyWorkflow(
                    item.id, item.name, item.archived_at is not None, item.draft_definition
                )
                for item in workflows
            ),
            workflow_versions=tuple(
                DependencyWorkflowVersion(item.workflow_id, item.version, item.definition)
                for item in workflow_versions
            ),
            case_versions=tuple(
                DependencyCaseVersion(item.test_case_id, item.version, item.definition)
                for item in cases
            ),
            suite_versions=_suite_versions(
                tuple(
                    (identifier, DependencySuiteVersion(owner_id, version, ()))
                    for identifier, owner_id, version in suites
                ),
                tuple(
                    (identifier, DependencyCaseRef(case_id, version))
                    for identifier, case_id, version in suite_items
                ),
            ),
            plans=_plans(
                tuple(
                    DependencyPlan(
                        identifier, name, enabled, interval is not None or cron is not None, ()
                    )
                    for identifier, name, enabled, interval, cron in plans
                ),
                tuple(
                    (
                        identifier,
                        DependencyPlanItem(
                            cast(Literal["workflow", "case", "suite"], kind),
                            target_id,
                            target_version,
                            workflow_id,
                            workflow_version,
                            environment_id,
                        ),
                    )
                    for (
                        identifier,
                        kind,
                        target_id,
                        target_version,
                        workflow_id,
                        workflow_version,
                        environment_id,
                    ) in plan_items
                ),
            ),
            release_policies=tuple(
                DependencyReleasePolicy(identifier, name) for identifier, name in policies
            ),
            truncated=tuple(truncated),
        )

    async def _definitions[T](
        self,
        query: Select[tuple[T]],
        identifier: SQLColumnExpression[UUID],
        definition: SQLColumnExpression[dict[str, JsonValue]],
        label: str,
        truncated: list[str],
    ) -> list[T]:
        metadata = (
            await self._session.execute(
                query.with_only_columns(
                    identifier,
                    func.length(sql_cast(definition, Text)),
                ).limit(501)
            )
        ).all()
        identifiers, skipped = _bounded_definitions(
            [(key, int(size or 0)) for key, size in metadata[:500]]
        )
        if len(metadata) > 500 or skipped:
            truncated.append(label)
        if not identifiers:
            return []
        return list((await self._session.scalars(query.where(identifier.in_(identifiers)))).all())

    async def _rows[T: tuple[object, ...]](
        self, query: Select[T], label: str, truncated: list[str], limit: int = 2000
    ) -> list[Row[T]]:
        rows = list((await self._session.execute(query.limit(limit + 1))).all())
        if len(rows) > limit:
            truncated.append(label)
        return rows[:limit]


def _suite_versions(
    suites: tuple[tuple[UUID, DependencySuiteVersion], ...],
    items: tuple[tuple[UUID, DependencyCaseRef], ...],
) -> tuple[DependencySuiteVersion, ...]:
    members: dict[UUID, list[DependencyCaseRef]] = {}
    for identifier, member in items:
        members.setdefault(identifier, []).append(member)
    return tuple(
        replace(suite, cases=tuple(members.get(identifier, []))) for identifier, suite in suites
    )


def _plans(
    plans: tuple[DependencyPlan, ...], items: tuple[tuple[UUID, DependencyPlanItem], ...]
) -> tuple[DependencyPlan, ...]:
    members: dict[UUID, list[DependencyPlanItem]] = {}
    for identifier, member in items:
        members.setdefault(identifier, []).append(member)
    return tuple(replace(plan, items=tuple(members.get(plan.id, []))) for plan in plans)


def _bounded_definitions(metadata: list[tuple[UUID, int]]) -> tuple[list[UUID], bool]:
    identifiers: list[UUID] = []
    remaining = 1_000_000
    skipped = False
    for identifier, size in metadata:
        if size > 100_000 or size > remaining:
            skipped = True
            continue
        identifiers.append(identifier)
        remaining -= size
    return identifiers, skipped
