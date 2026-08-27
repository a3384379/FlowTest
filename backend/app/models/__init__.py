"""SQLAlchemy persistence models."""

from app.models.access import (
    AuditLog,
    Folder,
    OIDCLoginTransaction,
    Project,
    ProjectMember,
    ProjectTeamGrant,
    RefreshSession,
    Team,
    TeamMember,
    User,
)
from app.models.ai import AIChangeItem, AIChangeSet, AIJob, AISuggestion
from app.models.api_assets import APIDefinition, APIVersion, Environment, Secret
from app.models.artifacts import Artifact
from app.models.base import Base
from app.models.capabilities import Capability, Plugin, Runner, RunnerPool
from app.models.change_regression import (
    ChangeRegressionRun,
    ChangeRegressionStage,
    SemanticGapWaiver,
)
from app.models.contracts import (
    ContractRun,
    DeploymentCompatibilityCheck,
    GeneratedContractCase,
    PactContractVersion,
    PactProviderVerification,
    ServiceCatalogEntry,
)
from app.models.data_sources import Credential, MockRequestLog, MockRoute, MockService
from app.models.durable_execution import ExecutionCheckpoint, ExecutionCommand
from app.models.environment_lab import (
    EnvironmentInstance,
    EnvironmentTemplate,
    EnvironmentTemplateVersion,
)
from app.models.executions import APICallExecution, AssertionResult
from app.models.governance import IdempotencyRecord, OrganizationGovernance, OrganizationKeyVersion
from app.models.impact import CoverageSnapshot, ImpactAssetMapping, ImpactRun, TestSelection
from app.models.imports import ImportRun
from app.models.organizations import Organization, OrganizationMember, ServiceAccount
from app.models.performance import PerformanceGateEvaluation, PerformanceRun, PerformanceScenario
from app.models.protocols import EventSource, SchemaArtifact
from app.models.quality import FlakyRecord, QualityGate, QualityGateEvaluation
from app.models.quality_intelligence import FailureCluster, ReleaseRisk
from app.models.release_gate import ReleaseDecision, ReleasePolicy
from app.models.reporting import NotificationDelivery, NotificationWebhook
from app.models.runner_fabric import (
    RunnerEvent,
    RunnerLeaseRecord,
    RunnerRegistrationToken,
    RunnerTask,
)
from app.models.service_targets import Service, ServiceEndpoint
from app.models.tasking import ServiceToken, TestPlan, TestPlanItem, TestPlanRun, TestPlanRunItem
from app.models.test_assets import (
    TestCase,
    TestCaseVersion,
    TestSuite,
    TestSuiteVersion,
    TestSuiteVersionItem,
)
from app.models.test_design import ChangeSetApproval, TestDesign
from app.models.workflows import Workflow, WorkflowExecution, WorkflowNodeExecution, WorkflowVersion

__all__ = [
    "AIChangeItem",
    "AIChangeSet",
    "AIJob",
    "AISuggestion",
    "APICallExecution",
    "APIDefinition",
    "APIVersion",
    "Artifact",
    "AssertionResult",
    "AuditLog",
    "Base",
    "Capability",
    "ChangeRegressionRun",
    "ChangeRegressionStage",
    "ChangeSetApproval",
    "ContractRun",
    "CoverageSnapshot",
    "Credential",
    "DeploymentCompatibilityCheck",
    "Environment",
    "EnvironmentInstance",
    "EnvironmentTemplate",
    "EnvironmentTemplateVersion",
    "EventSource",
    "ExecutionCheckpoint",
    "ExecutionCommand",
    "FailureCluster",
    "FlakyRecord",
    "Folder",
    "GeneratedContractCase",
    "IdempotencyRecord",
    "ImpactAssetMapping",
    "ImpactRun",
    "ImportRun",
    "MockRequestLog",
    "MockRoute",
    "MockService",
    "NotificationDelivery",
    "NotificationWebhook",
    "OIDCLoginTransaction",
    "Organization",
    "OrganizationGovernance",
    "OrganizationKeyVersion",
    "OrganizationMember",
    "PactContractVersion",
    "PactProviderVerification",
    "PerformanceGateEvaluation",
    "PerformanceRun",
    "PerformanceScenario",
    "Plugin",
    "Project",
    "ProjectMember",
    "ProjectTeamGrant",
    "QualityGate",
    "QualityGateEvaluation",
    "RefreshSession",
    "ReleaseDecision",
    "ReleasePolicy",
    "ReleaseRisk",
    "Runner",
    "RunnerEvent",
    "RunnerLeaseRecord",
    "RunnerPool",
    "RunnerRegistrationToken",
    "RunnerTask",
    "SchemaArtifact",
    "Secret",
    "SemanticGapWaiver",
    "Service",
    "ServiceAccount",
    "ServiceCatalogEntry",
    "ServiceEndpoint",
    "ServiceToken",
    "Team",
    "TeamMember",
    "TestCase",
    "TestCaseVersion",
    "TestDesign",
    "TestPlan",
    "TestPlanItem",
    "TestPlanRun",
    "TestPlanRunItem",
    "TestSelection",
    "TestSuite",
    "TestSuiteVersion",
    "TestSuiteVersionItem",
    "User",
    "Workflow",
    "WorkflowExecution",
    "WorkflowNodeExecution",
    "WorkflowVersion",
]
