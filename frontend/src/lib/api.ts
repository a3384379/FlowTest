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
}

export type Project = {
  id: string
  name: string
  description: string
  role: 'owner' | 'editor' | 'viewer' | null
}

export type Environment = {
  id: string
  project_id: string
  name: string
  base_url: string
  variables: Record<string, string>
  headers: Record<string, string>
}

export type ApiDefinition = {
  id: string
  project_id: string
  folder_id: string | null
  name: string
  description: string
  current_version: number
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
  purpose: 'upload' | 'response'
  created_at: string
}

export type ImportChange = 'added' | 'changed' | 'deleted' | 'unchanged'

export type ImportItem = {
  import_key: string
  name: string
  method: string
  path: string
  change: ImportChange
  definition_id: string
  version: number
}

export type ImportRun = {
  id: string
  project_id: string
  source_type: 'openapi3' | 'swagger2' | 'postman'
  source_name: string
  source_sha256: string
  added: number
  changed: number
  deleted: number
  unchanged: number
  results: ImportItem[]
  created_at: string
}

export type ExecutionDetail = {
  execution: Execution
  assertions: AssertionResult[]
}

export type WorkflowNode = {
  id: string
  type: 'start' | 'api' | 'extract' | 'assert' | 'condition' | 'delay' | 'dataset' | 'end'
  name: string
  position: { x: number; y: number }
  config: Record<string, unknown>
}

export type WorkflowDefinition = {
  schema_version: string
  nodes: WorkflowNode[]
  edges: Array<{
    id: string
    source: string
    target: string
    condition: string | null
    mappings: unknown[]
  }>
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

export type WorkflowExecution = {
  id: string
  workflow_id: string
  workflow_version_id: string
  environment_id: string
  status: 'running' | 'passed' | 'failed' | 'cancelled'
  snapshot: Record<string, unknown>
  context: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  cancel_requested_at: string | null
  started_at: string
  completed_at: string | null
}

export type WorkflowNodeExecution = {
  id: string
  node_id: string
  node_type: string
  name: string
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'cancelled'
  attempts: number
  output: unknown
  error_code: string | null
  error_message: string | null
}

export type WorkflowExecutionDetail = {
  execution: WorkflowExecution
  nodes: WorkflowNodeExecution[]
}

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const message = error.response?.data?.error?.message
    return typeof message === 'string' ? message : error.message
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}
