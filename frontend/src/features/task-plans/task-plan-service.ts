import {
  apiClient,
  type CreatedServiceToken,
  type CreatedTestPlan,
  type Environment,
  type Page,
  type Project,
  type ServiceToken,
  type TestPlan,
  type TestPlanRun,
  type Workflow,
} from '../../lib/api'

export type CreateTestPlanInput = {
  name: string
  workflowId: string
  environmentId: string
  intervalSeconds: number | null
  maxRetries: number
}

export async function listTaskProjects(): Promise<Page<Project>> {
  const response = await apiClient.get<Page<Project>>('/projects', {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function listTaskWorkflows(projectId: string): Promise<Page<Workflow>> {
  const response = await apiClient.get<Page<Workflow>>(`/projects/${projectId}/workflows`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function listTaskEnvironments(projectId: string): Promise<Environment[]> {
  const response = await apiClient.get<Environment[]>(`/projects/${projectId}/environments`)
  return response.data
}

export async function listTestPlans(projectId: string): Promise<Page<TestPlan>> {
  const response = await apiClient.get<Page<TestPlan>>(`/projects/${projectId}/test-plans`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function createTestPlan(
  projectId: string,
  input: CreateTestPlanInput,
): Promise<CreatedTestPlan> {
  const response = await apiClient.post<CreatedTestPlan>(`/projects/${projectId}/test-plans`, {
    name: input.name,
    enabled: true,
    schedule_interval_seconds: input.intervalSeconds,
    items: [
      {
        workflow_id: input.workflowId,
        environment_id: input.environmentId,
        max_retries: input.maxRetries,
      },
    ],
  })
  return response.data
}

export async function runTestPlan(projectId: string, planId: string): Promise<TestPlanRun> {
  const response = await apiClient.post<TestPlanRun>(
    `/projects/${projectId}/test-plans/${planId}/runs`,
    undefined,
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  )
  return response.data
}

export async function listTestPlanRuns(projectId: string): Promise<Page<TestPlanRun>> {
  const response = await apiClient.get<Page<TestPlanRun>>(`/projects/${projectId}/test-plan-runs`, {
    params: { page: 1, page_size: 50 },
  })
  return response.data
}

export async function cancelTestPlanRun(projectId: string, runId: string): Promise<TestPlanRun> {
  const response = await apiClient.post<TestPlanRun>(
    `/projects/${projectId}/test-plan-runs/${runId}/cancel`,
  )
  return response.data
}

export async function listServiceTokens(projectId: string): Promise<ServiceToken[]> {
  const response = await apiClient.get<ServiceToken[]>(`/projects/${projectId}/service-tokens`)
  return response.data
}

export async function createServiceToken(projectId: string): Promise<CreatedServiceToken> {
  const response = await apiClient.post<CreatedServiceToken>(
    `/projects/${projectId}/service-tokens`,
    {
      name: `CI Token ${new Date().toLocaleDateString('zh-CN')}`,
      scopes: ['execute:workflow', 'execute:test-plan'],
    },
  )
  return response.data
}
