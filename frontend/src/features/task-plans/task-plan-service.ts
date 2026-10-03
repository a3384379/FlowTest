import {
  apiClient,
  type CreatedServiceToken,
  type CreatedTestPlan,
  type Environment,
  type Page,
  type Project,
  type ServiceToken,
  type TestCase,
  type TestPlan,
  type TestPlanRun,
  type TestSuite,
  type Workflow,
} from '../../lib/api'

export type TestPlanTargetType = 'workflow' | 'case' | 'suite'

export type TestPlanTargetAsset = Pick<Workflow, 'id' | 'project_id' | 'name'> & {
  current_version: number | null
}

const targetCatalogs: Readonly<Record<TestPlanTargetType, string>> = {
  workflow: 'workflows',
  case: 'test-cases',
  suite: 'test-suites',
}

export async function listPlanTargetAssets(
  projectId: string,
  type: TestPlanTargetType,
  page: number,
  search: string,
): Promise<Page<TestPlanTargetAsset>> {
  return (
    await apiClient.get<Page<TestPlanTargetAsset>>(
      `/projects/${projectId}/${targetCatalogs[type]}`,
      { params: { page, page_size: 20, search: search || undefined } },
    )
  ).data
}

export async function getPlanTargetAsset(
  projectId: string,
  type: TestPlanTargetType,
  id: string,
): Promise<TestPlanTargetAsset> {
  return (
    await apiClient.get<TestPlanTargetAsset>(`/projects/${projectId}/${targetCatalogs[type]}/${id}`)
  ).data
}

export type CreateTestPlanInput = {
  name: string
  targetType: TestPlanTargetType
  targetId: string
  targetVersion?: number
  environmentId: string | null
  intervalSeconds: number | null
  cronExpression: string | null
  timezone: string
  priority: number
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

export async function listTaskTestCases(projectId: string): Promise<Page<TestCase>> {
  const response = await apiClient.get<Page<TestCase>>(`/projects/${projectId}/test-cases`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function listTaskTestSuites(projectId: string): Promise<Page<TestSuite>> {
  const response = await apiClient.get<Page<TestSuite>>(`/projects/${projectId}/test-suites`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function listTestPlans(
  projectId: string,
  page = 1,
  pageSize = 100,
): Promise<Page<TestPlan>> {
  const response = await apiClient.get<Page<TestPlan>>(`/projects/${projectId}/test-plans`, {
    params: { page, page_size: pageSize },
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
    schedule_cron: input.cronExpression,
    schedule_timezone: input.timezone,
    queue_priority: input.priority,
    items: [
      {
        target_type: input.targetType,
        target_id: input.targetId,
        target_version: input.targetVersion,
        environment_id: input.environmentId,
        max_retries: input.maxRetries,
      },
    ],
  })
  return response.data
}

export async function runTestPlan(
  projectId: string,
  planId: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<TestPlanRun> {
  const response = await apiClient.post<TestPlanRun>(
    `/projects/${projectId}/test-plans/${planId}/runs`,
    undefined,
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
  return response.data
}

export async function listTestPlanRuns(projectId: string, page = 1): Promise<Page<TestPlanRun>> {
  const response = await apiClient.get<Page<TestPlanRun>>(`/projects/${projectId}/test-plan-runs`, {
    params: { page, page_size: 20 },
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
