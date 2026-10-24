"""Independent viewer reads the complete owned native inventory and fixed version relationships."""

from __future__ import annotations

from uuid import UUID

from scripts.selftest.fixed_baseline import FixedInstallation
from scripts.selftest.initialization_contracts import InstallationInventory
from scripts.selftest.io import object_value, objects_value, text_value
from scripts.selftest.security_boundary_http import BoundaryAPI


async def inventory(api: BoundaryAPI, project: UUID) -> InstallationInventory:
    values: dict[str, tuple[UUID, ...]] = {}
    complete = True
    default_service_id = None
    kinds = (
        "apis",
        "workflows",
        "test-cases",
        "test-suites",
        "test-plans",
        "test-plan-runs",
        "workflow-executions",
        "environments",
        "services",
    )
    for kind in kinds:
        raw = await api.request("GET", f"/projects/{project}/{kind}?page=1&page_size=100")
        if isinstance(raw, list):
            rows = objects_value(raw)
            complete = complete and len(rows) < 100
        else:
            page = object_value(raw)
            rows = objects_value(page["items"])
            complete = complete and page["total"] == len(rows) and len(rows) < 100
        if kind == "services":
            defaults = [
                UUID(text_value(row["id"])) for row in rows if row["service_key"] == "default"
            ]
            complete = complete and len(defaults) <= 1
            default_service_id = defaults[0] if len(defaults) == 1 else None
        ids = tuple(sorted((UUID(text_value(row["id"])) for row in rows), key=str))
        complete = complete and len(ids) == len(set(ids))
        values[kind] = ids
    return InstallationInventory(
        project_id=project,
        api_ids=values["apis"],
        workflow_ids=values["workflows"],
        case_ids=values["test-cases"],
        suite_ids=values["test-suites"],
        plan_ids=values["test-plans"],
        run_ids=values["test-plan-runs"],
        execution_ids=values["workflow-executions"],
        environment_ids=values["environments"],
        service_ids=values["services"],
        default_service_id=default_service_id,
        complete=complete,
    )


async def mapping_matches(api: BoundaryAPI, installed: FixedInstallation) -> bool:
    if len(installed.assets) != 1:
        return False
    asset = installed.assets[0]
    root = f"/projects/{installed.project_id}"
    source = await api.object("GET", root + f"/apis/{asset.api_id}?version={asset.api_version}")
    version = object_value(source["version"])
    if (
        version["contract_fingerprint"] != asset.api_fingerprint
        or version["api_definition_id"] != str(asset.api_id)
        or version["version"] != asset.api_version
        or object_value(source["definition"])["service_id"] != str(installed.service_id)
    ):
        return False
    workflows = objects_value(
        await api.request("GET", root + f"/workflows/{asset.workflow_id}/versions")
    )
    cases = objects_value(await api.request("GET", root + f"/test-cases/{asset.case_id}/versions"))
    suites = objects_value(
        await api.request("GET", root + f"/test-suites/{installed.suite_id}/versions")
    )
    if len(workflows) != 1 or len(cases) != 1 or len(suites) != 1:
        return False
    if (
        workflows[0]["id"] != str(asset.workflow_version_id)
        or workflows[0]["fingerprint"] != asset.workflow_fingerprint
        or workflows[0]["version"] != asset.workflow_version
        or cases[0]["fingerprint"] != asset.case_fingerprint
        or cases[0]["version"] != asset.case_version
    ):
        return False
    definition = object_value(cases[0]["definition"])
    if (
        definition["workflow_id"] != str(asset.workflow_id)
        or definition["workflow_version"] != asset.workflow_version
        or definition["environment_id"] != str(installed.environment_id)
    ):
        return False
    plan = await api.object("GET", root + f"/test-plans/{installed.plan_id}")
    items = objects_value(plan["items"])
    return (
        suites[0]["version"] == installed.suite_version
        and object_value(suites[0]["definition"])["items"]
        == [
            {
                "test_case_id": str(asset.case_id),
                "test_case_version": asset.case_version,
            }
        ]
        and len(items) == 1
        and items[0]["target_type"] == "suite"
        and items[0]["target_id"] == str(installed.suite_id)
        and items[0]["target_version"] == installed.suite_version
        and items[0]["max_retries"] == 0
    )
