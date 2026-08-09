import type { ApiDefinition, Environment, ExecutionDetail, Project, User } from '../lib/api'

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
