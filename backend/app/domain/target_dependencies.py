"""Project-owned metadata used to explain an unsaved routing candidate."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.domain.api_assets import JsonValue
from app.domain.target_preview import TargetPreviewCommand


@dataclass(frozen=True, slots=True)
class DependencyAPI:
    id: UUID
    name: str
    current_version: int
    active: bool


@dataclass(frozen=True, slots=True)
class DependencyAPIVersion:
    api_id: UUID
    version: int
    service_id: UUID | None


@dataclass(frozen=True, slots=True)
class DependencyEnvironment:
    id: UUID
    default_service_id: UUID | None


@dataclass(frozen=True, slots=True)
class DependencyService:
    id: UUID
    key: str


@dataclass(frozen=True, slots=True)
class DependencyEndpoint:
    id: UUID
    environment_id: UUID
    service_id: UUID
    variant: str


@dataclass(frozen=True, slots=True)
class DependencyWorkflow:
    id: UUID
    name: str
    archived: bool
    draft: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DependencyWorkflowVersion:
    workflow_id: UUID
    version: int
    definition: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DependencyCaseVersion:
    case_id: UUID
    version: int
    definition: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DependencyCaseRef:
    case_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class DependencySuiteVersion:
    suite_id: UUID
    version: int
    cases: tuple[DependencyCaseRef, ...]


@dataclass(frozen=True, slots=True)
class DependencyPlanItem:
    kind: Literal["workflow", "case", "suite"]
    target_id: UUID
    target_version: int
    workflow_id: UUID | None
    workflow_version: int | None
    environment_id: UUID | None


@dataclass(frozen=True, slots=True)
class DependencyPlan:
    id: UUID
    name: str
    enabled: bool
    scheduled: bool
    items: tuple[DependencyPlanItem, ...]


@dataclass(frozen=True, slots=True)
class DependencyReleasePolicy:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class TargetDependencyCatalog:
    apis: tuple[DependencyAPI, ...]
    api_versions: tuple[DependencyAPIVersion, ...]
    environments: tuple[DependencyEnvironment, ...]
    services: tuple[DependencyService, ...]
    endpoints: tuple[DependencyEndpoint, ...]
    workflows: tuple[DependencyWorkflow, ...]
    workflow_versions: tuple[DependencyWorkflowVersion, ...]
    case_versions: tuple[DependencyCaseVersion, ...]
    suite_versions: tuple[DependencySuiteVersion, ...]
    plans: tuple[DependencyPlan, ...]
    release_policies: tuple[DependencyReleasePolicy, ...]
    truncated: tuple[str, ...] = ()


class TargetDependencyReader(Protocol):
    async def load(
        self, project_id: UUID, command: TargetPreviewCommand
    ) -> TargetDependencyCatalog: ...


@dataclass(frozen=True, slots=True)
class CandidateDependencyItem:
    id: UUID
    name: str
    reason: str
    available: bool = True


@dataclass(frozen=True, slots=True)
class CandidateDependencyDiagnostic:
    code: str
    message: str
    resource_id: UUID | None = None
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateDependencyPreview:
    scope_kind: Literal["service", "endpoint", "environment_default", "api_binding"]
    scope_id: UUID
    complete: bool
    diagnostics: tuple[CandidateDependencyDiagnostic, ...]
    affected_apis: tuple[CandidateDependencyItem, ...] = ()
    affected_workflows: tuple[CandidateDependencyItem, ...] = ()
    affected_test_plans: tuple[CandidateDependencyItem, ...] = ()
    affected_scheduled_runs: tuple[CandidateDependencyItem, ...] = ()
    affected_release_gates: tuple[CandidateDependencyItem, ...] = ()
