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
  type TestPlanRunDetail,
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

export type CreatePlanItemInput = {
  targetType: TestPlanTargetType
  targetId: string
  targetVersion: number
  environmentId: string | null
  maxRetries: number
}

export type CreateTestPlanInput = {
  name: string
  items: CreatePlanItemInput[]
  intervalSeconds: number | null
  cronExpression: string | null
  timezone: string
  priority: number
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
  if (!input.items.length || input.items.length > 100) throw new Error('测试计划需要1至100个执行项')
  if (input.items.some((item) => !Number.isInteger(item.targetVersion) || item.targetVersion < 1))
    throw new Error('每个执行项都必须选择已发布的固定版本')
  const response = await apiClient.post<CreatedTestPlan>(`/projects/${projectId}/test-plans`, {
    name: input.name,
    enabled: true,
    schedule_interval_seconds: input.intervalSeconds,
    schedule_cron: input.cronExpression,
    schedule_timezone: input.timezone,
    queue_priority: input.priority,
    items: input.items.map((item) => ({
      target_type: item.targetType,
      target_id: item.targetId,
      target_version: item.targetVersion,
      environment_id: item.targetType === 'workflow' ? item.environmentId : null,
      max_retries: item.maxRetries,
    })),
  })
  return response.data
}

export async function getTestPlan(projectId: string, planId: string): Promise<TestPlan> {
  const plan = (await apiClient.get<TestPlan>(`/projects/${projectId}/test-plans/${planId}`)).data
  if (plan.id !== planId || plan.project_id !== projectId)
    throw new Error('计划详情不属于当前项目或计划')
  return plan
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

export type UpdateTestPlanInput = Pick<
  TestPlan,
  | 'name'
  | 'description'
  | 'enabled'
  | 'schedule_interval_seconds'
  | 'schedule_cron'
  | 'schedule_timezone'
  | 'queue_priority'
>

export async function updateTestPlan(
  projectId: string,
  planId: string,
  input: Partial<UpdateTestPlanInput>,
): Promise<TestPlan> {
  return (await apiClient.patch<TestPlan>(`/projects/${projectId}/test-plans/${planId}`, input))
    .data
}

export async function getTestPlanRun(projectId: string, runId: string): Promise<TestPlanRunDetail> {
  const detail = (
    await apiClient.get<TestPlanRunDetail>(`/projects/${projectId}/test-plan-runs/${runId}`)
  ).data
  if (detail.run.id !== runId || detail.run.project_id !== projectId)
    throw new Error('运行详情不属于当前项目或运行')
  return detail
}

export async function revokeServiceToken(projectId: string, tokenId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/service-tokens/${tokenId}`)
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
