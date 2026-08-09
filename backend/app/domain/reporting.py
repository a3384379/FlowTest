from enum import StrEnum


class FailureCategory(StrEnum):
    ASSERTION = "assertion"
    TIMEOUT = "timeout"
    NETWORK = "network"
    HTTP_CLIENT = "http_client"
    HTTP_SERVER = "http_server"
    CONFIGURATION = "configuration"
    CANCELLED = "cancelled"
    RUNTIME = "runtime"
    NONE = "none"


class NotificationEvent(StrEnum):
    WORKFLOW_COMPLETED = "workflow.completed"
    TEST_PLAN_COMPLETED = "test_plan.completed"


def classify_failure(*, status: str, error_code: str | None) -> FailureCategory:
    if status == "passed":
        return FailureCategory.NONE
    if status == "cancelled":
        return FailureCategory.CANCELLED
    normalized = (error_code or "").upper()
    if "ASSERT" in normalized:
        return FailureCategory.ASSERTION
    if "TIMEOUT" in normalized:
        return FailureCategory.TIMEOUT
    if "NETWORK" in normalized or "DNS" in normalized:
        return FailureCategory.NETWORK
    if "4XX" in normalized:
        return FailureCategory.HTTP_CLIENT
    if "5XX" in normalized:
        return FailureCategory.HTTP_SERVER
    if any(
        marker in normalized
        for marker in ("INVALID", "UNSUPPORTED", "MAPPING", "EXTRACT", "NOT_FOUND")
    ):
        return FailureCategory.CONFIGURATION
    return FailureCategory.RUNTIME
