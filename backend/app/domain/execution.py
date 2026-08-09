from enum import StrEnum


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
