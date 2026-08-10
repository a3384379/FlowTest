from pydantic import BaseModel, ConfigDict


class RetentionCleanupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    projects_scanned: int
    api_executions_deleted: int
    workflow_executions_deleted: int
    test_plan_runs_deleted: int
    notification_deliveries_deleted: int
    mock_request_logs_deleted: int
    artifacts_deleted: int
    storage_failures: int
    idempotency_records_deleted: int
    import_previews_deleted: int
    refresh_sessions_deleted: int
