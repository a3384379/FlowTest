from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentClassification(StrEnum):
    UNCLASSIFIED = "unclassified"
    TEST = "test"
    SANDBOX = "sandbox"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def allows_preview(self) -> bool:
        return self in {self.TEST, self.SANDBOX}


class WorkflowRunPurpose(StrEnum):
    STANDARD = "standard"
    PREVIEW = "preview"


class PreviewBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_nodes: int = Field(default=100, ge=1, le=100)
    max_requests: int = Field(default=50, ge=1, le=50)
    max_dataset_rows: int = Field(default=20, ge=1, le=20)
    max_parallelism: int = Field(default=5, ge=1, le=5)
    max_runtime_seconds: int = Field(default=600, ge=1, le=600)


MCP_PREVIEW_EXECUTE_SCOPE = "mcp:preview:execute"
MCP_SANDBOX_PREVIEW_SERVER_VERSION = "s55-sandbox-preview-v1"
