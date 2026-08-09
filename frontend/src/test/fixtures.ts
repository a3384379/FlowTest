import type {
  ApiDefinition,
  Environment,
  ExecutionDetail,
  Project,
  User,
  Workflow,
  WorkflowDefinition,
  WorkflowExecutionDetail,
  WorkflowVersion,
} from '../lib/api'

export const user: User = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'admin@flowtest.dev',
  display_name: 'FlowTest 管理员',
  is_active: true,
  is_system_admin: true,
  requires_password_change: false,
}

export const project: Project = {
  id: '00000000-0000-4000-8000-000000000010',
  name: '订单服务',
  description: '订单接口测试',
  role: 'owner',
}

export const environment: Environment = {
  id: '00000000-0000-4000-8000-000000000020',
  project_id: project.id,
  name: '本地测试',
  base_url: 'http://mock-target:8080',
  variables: {},
  headers: {},
}

export const apiDefinition: ApiDefinition = {
  id: '00000000-0000-4000-8000-000000000030',
  project_id: project.id,
  folder_id: null,
  name: '查询当前用户',
  description: '',
  current_version: 1,
}

export const executionDetail: ExecutionDetail = {
  execution: {
    id: '00000000-0000-4000-8000-000000000040',
    status: 'passed',
    request_method: 'GET',
    request_url: 'http://mock-target:8080/users/me',
    request_headers: { Authorization: '***' },
    request_body: null,
    response_status: 200,
    response_headers: { 'content-type': 'application/json' },
    response_body: { id: 7, name: '测试用户' },
    response_artifact_id: null,
    elapsed_ms: 18.2,
    error_code: null,
    error_message: null,
    started_at: '2026-08-09T08:00:00Z',
  },
  assertions: [
    {
      id: '00000000-0000-4000-8000-000000000050',
      kind: 'status_code',
      target: null,
      expected: 200,
      actual: 200,
      passed: true,
      message: '状态码等于 200',
    },
  ],
}

export const workflowDefinition: WorkflowDefinition = {
  schema_version: '1.0',
  variables: {},
  nodes: [
    { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 0 }, config: {} },
    {
      id: 'api',
      type: 'api',
      name: '查询用户',
      position: { x: 100, y: 0 },
      config: { api_definition_id: apiDefinition.id, max_retries: 1 },
    },
    { id: 'end', type: 'end', name: '结束', position: { x: 200, y: 0 }, config: {} },
  ],
  edges: [
    { id: 'start-api', source: 'start', target: 'api', condition: null, mappings: [] },
    { id: 'api-end', source: 'api', target: 'end', condition: null, mappings: [] },
  ],
  settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
}

export const workflow: Workflow = {
  id: '00000000-0000-4000-8000-000000000060',
  project_id: project.id,
  folder_id: null,
  name: '用户查询流程',
  description: '固定版本工作流',
  draft_definition: workflowDefinition,
  draft_revision: 1,
  current_version: 1,
  created_at: '2026-08-09T08:00:00Z',
  updated_at: '2026-08-09T08:00:00Z',
}

export const workflowVersion: WorkflowVersion = {
  id: '00000000-0000-4000-8000-000000000061',
  workflow_id: workflow.id,
  version: 2,
  definition: workflowDefinition,
  fingerprint: 'a'.repeat(64),
  published_at: '2026-08-09T08:01:00Z',
}

export const workflowExecutionDetail: WorkflowExecutionDetail = {
  execution: {
    id: '00000000-0000-4000-8000-000000000070',
    project_id: project.id,
    workflow_id: workflow.id,
    workflow_version_id: workflowVersion.id,
    environment_id: environment.id,
    triggered_by_id: user.id,
    parent_execution_id: null,
    dataset_row_index: null,
    status: 'passed',
    snapshot: { workflow: { version: 2 } },
    context: {},
    error_code: null,
    error_message: null,
    cancel_requested_at: null,
    started_at: '2026-08-09T08:02:00Z',
    completed_at: '2026-08-09T08:02:01Z',
  },
  nodes: [
    {
      id: '00000000-0000-4000-8000-000000000071',
      node_id: 'start',
      node_type: 'start',
      name: '开始',
      status: 'passed',
      attempts: 1,
      output: null,
      error_code: null,
      error_message: null,
    },
    {
      id: '00000000-0000-4000-8000-000000000072',
      node_id: 'api',
      node_type: 'api',
      name: '查询用户',
      status: 'passed',
      attempts: 2,
      output: { status_code: 200 },
      error_code: null,
      error_message: null,
    },
  ],
  children: [],
}

export const workflowRunningExecution = {
  ...workflowExecutionDetail.execution,
  status: 'running' as const,
  snapshot: { workflow: { version: 2, definition: workflowDefinition } },
  completed_at: null,
}
