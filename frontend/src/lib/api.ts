import axios from 'axios'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
  withCredentials: true,
})

let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

export type Page<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type User = {
  id: string
  email: string
  display_name: string
  is_active: boolean
  is_system_admin: boolean
  requires_password_change: boolean
  oidc_provider: string | null
  oidc_subject: string | null
  last_login_at: string | null
}

export type Project = {
  id: string
  name: string
  description: string
  role: 'owner' | 'editor' | 'viewer' | null
}

export type DashboardTrendPoint = {
  date: string
  total: number
  passed: number
  failed: number
  running: number
}

export type DashboardSummary = {
  project_count: number
  api_count: number
  workflow_count: number
  today_total: number
  today_passed: number
  today_failed: number
  pass_rate: number
  trend: DashboardTrendPoint[]
}

export type RecentExecution = {
  id: string
  project_id: string
  project_name: string
  kind: 'api' | 'workflow'
  target_id: string
  target_name: string
  status: string
  started_at: string
  completed_at: string | null
  duration_ms: number | null
}

export type Environment = {
  id: string
  project_id: string
  name: string
  base_url: string
  default_service_id?: string | null
  variables: Record<string, string>
  headers: Record<string, string>
}

export type ApiDefinition = {
  id: string
  project_id: string
  folder_id: string | null
  service_id?: string | null
  name: string
  description: string
  current_version: number
  is_active: boolean
}

export type AssertionResult = {
  id: string
  kind: string
  target: string | null
  expected: unknown
  actual: unknown
  passed: boolean
  message: string
}

export type Execution = {
  id: string
  status: 'running' | 'passed' | 'failed' | 'error'
  request_method: string
  request_url: string
  request_headers: Record<string, string>
  request_body: unknown
  target_snapshot?: Record<string, unknown>
  response_status: number | null
  response_headers: Record<string, string>
  response_body: unknown
  response_artifact_id: string | null
  elapsed_ms: number | null
  error_code: string | null
  error_message: string | null
  started_at: string
}

export type Artifact = {
  id: string
  project_id: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  purpose: 'upload' | 'response' | 'report'
  created_at: string
}

export type ImportChange = 'added' | 'changed' | 'deleted' | 'unchanged'

export type ImportItem = {
  import_key: string
  name: string
  method: string
  path: string
  change: ImportChange
  definition_id: string | null
  version: number
  server_url?: string | null
}

export type RequestService = {
  id: string
  project_id: string
  service_key: string
  name: string
  description: string
  owner_team: string | null
  service_type: 'http' | 'https' | 'grpc' | 'graphql' | 'other'
  enabled: boolean
  created_by_id: string
  created_at: string
  updated_at: string
}

export type ServiceEndpoint = {
  id: string
  project_id: string
  environment_id: string
  service_id: string
  variant: string
  base_url: string
  enabled: boolean
  connect_timeout_ms: number
  read_timeout_ms: number
  tls_verify: boolean
  proxy_ref: string | null
  headers: Record<string, string>
  variables?: Record<string, string>
  secret_refs: string[]
  health_check_path: string | null
  health_expected_status: number | null
  revision: number
  created_by_id: string
  created_at: string
  updated_at: string
}

export type ImportRun = {
  id: string
  project_id: string
  source_kind: 'file' | 'url'
  source_key: string
  source_type: 'openapi3' | 'swagger2' | 'postman' | 'har' | 'curl' | 'bruno' | 'excel'
  source_name: string
  source_url: string | null
  document_url: string | null
  source_sha256: string
  added: number
  changed: number
  deleted: number
  unchanged: number
  results: ImportItem[]
  status: 'preview' | 'applied'
  applied_keys: string[]
  applied_at: string | null
  created_at: string
}

export type ProjectCapability =
  'read' | 'edit' | 'execute' | 'manage_members' | 'manage_security' | 'view_audit'

export type ProjectPermission = {
  effective_role: 'system_admin' | 'owner' | 'editor' | 'viewer'
  capabilities: ProjectCapability[]
  matrix: Record<'owner' | 'editor' | 'viewer', ProjectCapability[]>
}

export type ProjectSecurityPolicy = {
  enabled: boolean
  allowed_hosts: string[]
  allowed_private_cidrs: string[]
}

export type ProjectRetentionPolicy = {
  retention_days: number
  maximum_days: number
}

export type AuditLog = {
  id: string
  actor_user_id: string | null
  project_id: string
  action: string
  resource_type: string
  resource_id: string | null
  details: Record<string, unknown>
  created_at: string
}

export type ProjectMember = {
  id: string
  project_id: string
  user_id: string
  role: 'owner' | 'editor' | 'viewer'
  created_at: string
  updated_at: string
}

export type Team = {
  id: string
  name: string
  description: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type TeamMember = {
  id: string
  team_id: string
  user_id: string
  created_at: string
  updated_at: string
}

export type ProjectTeamGrant = {
  id: string
  project_id: string
  team_id: string
  role: 'editor' | 'viewer'
  created_by_id: string
  created_at: string
  updated_at: string
}

export type Folder = {
  id: string
  project_id: string
  parent_id: string | null
  name: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type ProjectConfiguration = {
  project_id: string
  variables: Record<string, string>
  headers: Record<string, string>
}

export type SecretMetadata = {
  id: string
  project_id: string
  environment_id: string | null
  name: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type Credential = {
  id: string
  project_id: string
  name: string
  kind: 'postgresql' | 'mysql' | 'redis' | 'grpc_mtls'
  host: string
  port: number
  database_name: string
  username: string
  secret_provider: 'local' | 'vault_kv_v2'
  tls_enabled: boolean
  created_by_id: string
  created_at: string
  updated_at: string
}

export type MockService = {
  id: string
  project_id: string
  name: string
  slug: string
  description: string
  is_enabled: boolean
  created_by_id: string
  created_at: string
  updated_at: string
}

export type MockRoute = {
  id: string
  mock_service_id: string
  name: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  path_pattern: string
  query_conditions: Record<string, string>
  header_conditions: Record<string, string>
  response_status: number
  response_headers: Record<string, string>
  response_body: unknown
  delay_ms: number
  scenario: string | null
  priority: number
  is_enabled: boolean
  created_by_id: string
  created_at: string
  updated_at: string
}

export type MockRequestLog = {
  id: string
  mock_service_id: string
  mock_route_id: string | null
  method: string
  path: string
  query_parameters: Record<string, string>
  headers: Record<string, string>
  body: unknown
  matched: boolean
  scenario: string | null
  response_status: number
  duration_ms: number
  created_at: string
}

export type ApiRequestParameter = {
  name: string
  value: string
  enabled: boolean
}

export type ApiVersion = {
  id: string
  api_definition_id: string
  version: number
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  path: string
  query_parameters: ApiRequestParameter[]
  headers: Record<string, string>
  variables?: Record<string, string>
  body_kind: 'none' | 'json' | 'raw' | 'form' | 'multipart'
  body: unknown
  auth_kind: 'none' | 'bearer' | 'basic' | 'api_key'
  auth_config: Record<string, string>
  extraction_rules: Array<{
    name: string
    kind: 'jsonpath' | 'jmespath' | 'header'
    expression: string
  }>
  assertions: Array<{
    kind: string
    operator: string
    target: string | null
    expected: unknown
  }>
  created_at: string
}

export type ApiDetail = {
  definition: ApiDefinition
  version: ApiVersion
}

export type ExecutionDetail = {
  execution: Execution
  assertions: AssertionResult[]
}

export type WorkflowNode = {
  id: string
  type:
    | 'start'
    | 'api'
    | 'extract'
    | 'assert'
    | 'condition'
    | 'delay'
    | 'dataset'
    | 'subflow'
    | 'for_each'
    | 'sql'
    | 'redis'
    | 'capability'
    | 'end'
  name: string
  position: { x: number; y: number }
  config: Record<string, unknown>
  capability_id?: string
  capability_version?: string
  configuration?: Record<string, unknown>
  bindings?: Array<{ input: string; expression: string }>
}

export type WorkflowFieldMapping = {
  source: { node_id: string; path: string }
  transform: { kind: 'identity' | 'template'; template: string }
  target: {
    node_id: string
    location: 'query' | 'header' | 'body' | 'variable'
    key: string
  }
}

export type WorkflowEdge = {
  id: string
  source: string
  target: string
  condition: 'true' | 'false' | null
  mappings: WorkflowFieldMapping[]
}

export type WorkflowDefinition = {
  schema_version: string
  variables: Record<string, string>
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  settings: {
    fail_fast: boolean
    concurrency: number
    default_timeout_seconds: number
  }
}

export type Workflow = {
  id: string
  project_id: string
  folder_id: string | null
  name: string
  description: string
  draft_definition: WorkflowDefinition
  draft_revision: number
  current_version: number | null
  created_at: string
  updated_at: string
}

export type WorkflowVersion = {
  id: string
  workflow_id: string
  version: number
  definition: WorkflowDefinition
  fingerprint: string
  published_at: string
}

export type WorkflowVersionDiff = {
  from_version: number
  to_version: number
  changes: Array<{ path: string; before: unknown; after: unknown }>
}

export type WorkflowDebugResult = {
  status: 'running' | 'passed' | 'failed' | 'cancelled'
  mode: 'breakpoint' | 'replay'
  target_node_id: string
  context: Record<string, unknown>
  nodes: Array<{
    node_id: string
    node_type: string
    name: string
    status: WorkflowNodeExecution['status']
    attempts: number
    output: unknown
    result: Record<string, unknown>
    error_code: string | null
    error_message: string | null
    started_at: string | null
    completed_at: string
  }>
}

export type WorkflowExecution = {
  id: string
  project_id: string
  workflow_id: string
  workflow_version_id: string
  environment_id: string
  triggered_by_id: string
  parent_execution_id: string | null
  dataset_row_index: number | null
  status: 'running' | 'passed' | 'failed' | 'cancelled'
  snapshot: Record<string, unknown>
  context: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  cancel_requested_at: string | null
  started_at: string
  completed_at: string | null
}

export type NodeResult = {
  status: 'passed' | 'failed' | 'skipped' | 'cancelled'
  output: unknown
  assertions: Array<{
    name: string
    passed: boolean
    expected: unknown
    actual: unknown
    message: string
  }>
  metrics: Array<{ name: string; value: number; unit: string; labels: Record<string, string> }>
  artifacts: Array<{
    artifact_id: string
    name: string
    content_type: string
    size_bytes: number
    sha256: string
  }>
  trace: { trace_id: string; span_id: string } | null
  observations?: WorkflowNodeObservation[]
  redacted_paths: string[]
  error: {
    code: string
    message: string
    details: Record<string, unknown>
    retryable: boolean
  } | null
}

export type WorkflowNodeObservation = {
  kind: 'http'
  attempt: number
  request: {
    method: string
    url: string
    headers: Record<string, string>
    body: unknown
  }
  response: {
    status_code: number
    headers: Record<string, string>
    body: unknown
    size_bytes: number
  } | null
  mappings: Array<{
    source_node_id: string
    source_path: string
    target_location: string
    target_key: string
    value: unknown
  }>
  duration_ms: number
  started_at: string
  completed_at: string
  error_code: string | null
  error_message: string | null
}

export type WorkflowNodeExecution = {
  id: string
  node_id: string
  node_type: string
  name: string
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'cancelled'
  attempts: number
  output: unknown
  result?: NodeResult | null
  error_code: string | null
  error_message: string | null
  started_at?: string | null
  completed_at?: string
}

export type WorkflowExecutionDetail = {
  execution: WorkflowExecution
  nodes: WorkflowNodeExecution[]
  children: WorkflowExecution[]
}

export type TestPlanItem = {
  id: string
  target_type: 'workflow' | 'case' | 'suite'
  target_id: string
  target_version: number
  workflow_id: string | null
  environment_id: string | null
  workflow_version: number | null
  position: number
  max_retries: number
  runtime_variables: Record<string, string>
  runtime_headers: Record<string, string>
}

export type TestCaseDefinition = {
  workflow_id: string
  workflow_version: number | null
  environment_id: string
  runtime_variables: Record<string, string>
  runtime_headers: Record<string, string>
}

export type TestCase = {
  id: string
  project_id: string
  folder_id: string | null
  name: string
  description: string
  tags: string[]
  is_template: boolean
  draft_definition: TestCaseDefinition
  current_version: number | null
  created_by_id: string
  created_at: string
  updated_at: string
}

export type TestCaseVersion = {
  id: string
  test_case_id: string
  version: number
  definition: TestCaseDefinition & { workflow_version: number }
  fingerprint: string
  change_note: string
  created_by_id: string
  created_at: string
}

export type TestSuiteItem = {
  test_case_id: string
  test_case_version: number | null
}

export type TestSuite = {
  id: string
  project_id: string
  folder_id: string | null
  name: string
  description: string
  tags: string[]
  draft_definition: { items: TestSuiteItem[] }
  current_version: number | null
  created_by_id: string
  created_at: string
  updated_at: string
}

export type TestSuiteVersion = {
  id: string
  test_suite_id: string
  version: number
  definition: { items: Array<TestSuiteItem & { test_case_version: number }> }
  fingerprint: string
  change_note: string
  created_by_id: string
  created_at: string
}

export type VersionDiff = {
  from_version: number
  to_version: number
  changes: Array<{ path: string; before: unknown; after: unknown }>
}

export type ContractRun = {
  id: string
  project_id: string
  baseline_run_id: string | null
  source_name: string
  source_type: 'openapi3' | 'swagger2'
  source_sha256: string
  status: 'completed' | 'failed'
  diff_summary: { added: number; changed: number; deleted: number; unchanged: number }
  breaking_changes: Array<{
    code: string
    severity: 'breaking'
    operation_key: string
    path: string
    message: string
    before: unknown
    after: unknown
  }>
  coverage: {
    operations_total: number
    operations_generated: number
    operation_coverage_percent: number
    request_fields_total: number
    response_fields_total: number
    schema_fields_total: number
    schema_fields_covered: number
    schema_coverage_percent: number
  }
  generated_case_count: number
  provider_service_id: string | null
  provider_version: string | null
  created_by_id: string
  created_at: string
  updated_at: string
}

export type GeneratedContractCase = {
  id: string
  contract_run_id: string
  operation_key: string
  operation_id: string
  method: string
  path: string
  generation_kind: 'example' | 'boundary' | 'property' | 'negative'
  name: string
  definition: Record<string, unknown>
  review_status: 'pending' | 'accepted' | 'rejected'
  review_note: string
  reviewed_by_id: string | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
}

export type TestPlan = {
  id: string
  project_id: string
  name: string
  description: string
  enabled: boolean
  schedule_interval_seconds: number | null
  schedule_cron: string | null
  schedule_timezone: string
  queue_priority: number
  next_run_at: string | null
  created_by_id: string
  created_at: string
  updated_at: string
  items: TestPlanItem[]
}

export type CreatedTestPlan = TestPlan & { webhook_secret: string }

export type TestPlanRun = {
  id: string
  project_id: string
  test_plan_id: string
  requested_by_id: string
  status: 'queued' | 'running' | 'passed' | 'failed' | 'cancelled'
  trigger_type: 'manual' | 'schedule' | 'ci' | 'webhook'
  queue_priority: number
  queue_name: 'general' | 'data' | 'ai'
  baseline_run_id: string | null
  quality_summary: Record<string, unknown>
  cancel_requested_at: string | null
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  created_at: string
}

export type ServiceToken = {
  id: string
  project_id: string
  name: string
  token_prefix: string
  scopes: Array<'execute:workflow' | 'execute:test-plan'>
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export type CreatedServiceToken = ServiceToken & { token: string }

export type FailureCategory =
  | 'assertion'
  | 'timeout'
  | 'network'
  | 'http_client'
  | 'http_server'
  | 'configuration'
  | 'cancelled'
  | 'runtime'
  | 'none'

export type ReportExecution = {
  id: string
  workflow_id: string
  workflow_name: string
  workflow_version: number
  status: 'running' | 'passed' | 'failed' | 'cancelled'
  failure_category: FailureCategory
  total_nodes: number
  passed_nodes: number
  failed_nodes: number
  skipped_nodes: number
  duration_ms: number | null
  started_at: string
  completed_at: string | null
}

export type ReportNode = {
  id: string
  node_id: string
  node_type: string
  name: string
  status: WorkflowNodeExecution['status']
  attempts: number
  duration_ms: number | null
  observations?: WorkflowNodeObservation[]
  request: unknown
  response: unknown
  extraction: unknown
  assertion: unknown
  input_mappings: unknown
  error_code: string | null
  error_message: string | null
}

export type ReportExecutionDetail = {
  summary: ReportExecution
  nodes: ReportNode[]
  context: Record<string, unknown>
  dataset_children: ReportExecution[]
}

export type ReportTrend = {
  points: Array<{
    date: string
    total: number
    passed: number
    failed: number
    cancelled: number
    pass_rate: number
    average_duration_ms: number
  }>
  failures: Array<{ category: FailureCategory; count: number }>
}

export type NotificationEvent = 'workflow.completed' | 'test_plan.completed'

export type NotificationWebhook = {
  id: string
  project_id: string
  name: string
  url: string
  events: NotificationEvent[]
  enabled: boolean
  created_by_id: string
  created_at: string
  updated_at: string
}

export type CreatedNotificationWebhook = NotificationWebhook & { secret: string }

export type NotificationDelivery = {
  id: string
  webhook_id: string
  event_type: NotificationEvent
  resource_id: string
  status: 'pending' | 'delivered' | 'failed'
  attempt?: number
  response_status: number | null
  error_message: string | null
  delivered_at: string | null
  created_at: string
}

export type ExecutionEvent = {
  sequence: number
  type: 'execution.started' | 'node.status' | 'node.result' | 'execution.completed'
  execution_id: string
  emitted_at: string
  node_id: string | null
  node_name: string | null
  node_type: string | null
  node_status: WorkflowNodeExecution['status'] | null
  result?: NodeResult | null
  attempt: number
  attempts: number
  error_code: string | null
  error_message: string | null
  execution_status: WorkflowExecution['status'] | null
}

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const message = error.response?.data?.error?.message
    return typeof message === 'string' ? message : error.message
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}
