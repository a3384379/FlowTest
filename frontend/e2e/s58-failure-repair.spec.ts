import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }
type Organization = { id: string }
type IssuedServiceAccount = { token: string }
type ReadyContext = { id: string; revision: { id: string } }
type ExecutionDetail = {
  execution: { status: string; error_code: string | null; error_message: string | null }
  nodes: Array<{ node_id: string; status: string; error_code: string | null }>
}
type FlowSpecDocument = {
  edges: Array<{ id: string; mappings: unknown[] }>
}

test('S58 失败诊断创建受限 Repair Proposal 并完成 Re-preview', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/')
  await authenticate(page)

  const token = await refreshAccessToken(page.request)
  const headers = { Authorization: `Bearer ${token}` }
  const suffix = `${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`
  const organizationId = await firstOrganizationId(page.request, headers)
  const project = await createProject(page.request, organizationId, suffix, headers)
  await allowComposeBackend(page.request, project.id, headers)
  const environment = await createEnvironment(page.request, project.id, suffix, headers)
  const api = await createHealthApi(page.request, project.id, suffix, headers)
  const workflow = await createBrokenBindingWorkflow(
    page.request,
    project.id,
    api.id,
    suffix,
    headers,
  )
  await publishWorkflow(page.request, project.id, workflow.id, headers)
  await createReadyContext(page.request, organizationId, project.id, suffix, headers)
  const execution = await startAndWaitForFailure(
    page.request,
    project.id,
    workflow.id,
    environment.id,
    headers,
  )
  expect(execution.execution.error_code).toBe('MAPPING_SOURCE_MISSING')

  await page.goto(`/projects/${project.id}/workflows`)
  await expect(page.getByRole('cell', { name: `S58 Repair ${suffix}` })).toBeVisible()
  await expect(page.getByRole('button', { name: '失败诊断' })).toBeVisible()
  await page.getByRole('button', { name: '失败诊断' }).click()

  const repair = page.getByRole('dialog', { name: '失败诊断与修复 Proposal' })
  await expect(repair.getByText('BAD_TEST', { exact: true })).toBeVisible()
  await expect(repair.getByText('Binding Mapping', { exact: true })).toBeVisible()
  await expect(repair.getByText(/S58 Repair Context/)).toBeVisible()
  const editor = repair.getByLabel('Proposed FlowSpec Patch')
  const proposed = JSON.parse(await editor.inputValue()) as FlowSpecDocument
  const brokenEdge = proposed.edges.find((edge) => edge.id === 'start-api')
  expect(brokenEdge).toBeDefined()
  brokenEdge!.mappings = []
  await editor.fill(JSON.stringify(proposed, null, 2))
  await repair.getByRole('button', { name: '创建 Repair Proposal' }).click()

  const review = page.getByRole('dialog', { name: 'Repair Proposal 可视化审核' })
  await expect(review).toBeVisible()
  await expect(review.getByText(/Repair Proposal 不会自动修改测试/)).toBeVisible()
  const preview = review.getByRole('button', { name: '一次性批准并运行 Sandbox Preview' })
  await expect(preview).toBeDisabled()
  await review.getByRole('button', { name: '接受' }).click()
  await expect(preview).toBeEnabled()
  await preview.click()

  const evidence = review.locator('.ant-card').filter({ hasText: 'Sandbox Preview Evidence' })
  await expect(evidence.getByText('passed', { exact: true }).first()).toBeVisible({
    timeout: 60_000,
  })
})

async function refreshAccessToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function firstOrganizationId(
  request: APIRequestContext,
  headers: Record<string, string>,
): Promise<string> {
  const response = await request.get('/api/v1/organizations', { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as Organization[])[0].id
}

async function createProject(
  request: APIRequestContext,
  organizationId: string,
  suffix: string,
  headers: Record<string, string>,
): Promise<Identified> {
  const response = await request.post('/api/v1/projects', {
    headers,
    data: {
      name: `S58 E2E ${suffix}`,
      description: 'S58 Failure Diagnosis and Repair Proposal Compose acceptance',
      organization_id: organizationId,
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function allowComposeBackend(
  request: APIRequestContext,
  projectId: string,
  headers: Record<string, string>,
): Promise<void> {
  const response = await request.put(`/api/v1/projects/${projectId}/security-policy`, {
    headers,
    data: { allowed_hosts: ['backend'], allowed_private_cidrs: ['172.16.0.0/12'] },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

async function createEnvironment(
  request: APIRequestContext,
  projectId: string,
  suffix: string,
  headers: Record<string, string>,
): Promise<Identified> {
  const response = await request.post(`/api/v1/projects/${projectId}/environments`, {
    headers,
    data: {
      name: `S58 Sandbox ${suffix}`,
      base_url: 'http://backend:8000',
      classification: 'sandbox',
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function createHealthApi(
  request: APIRequestContext,
  projectId: string,
  suffix: string,
  headers: Record<string, string>,
): Promise<Identified> {
  const response = await request.post(`/api/v1/projects/${projectId}/apis`, {
    headers,
    data: {
      name: `S58 Health ${suffix}`,
      request: { method: 'GET', path: '/api/v1/health', body_kind: 'none' },
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return ((await response.json()) as { definition: Identified }).definition
}

async function createBrokenBindingWorkflow(
  request: APIRequestContext,
  projectId: string,
  apiId: string,
  suffix: string,
  headers: Record<string, string>,
): Promise<Identified> {
  const response = await request.post(`/api/v1/projects/${projectId}/workflows`, {
    headers,
    data: {
      name: `S58 Repair ${suffix}`,
      description: 'Missing mapping source repaired by a scoped Binding Patch',
      definition: {
        schema_version: '1.0',
        variables: {},
        nodes: [
          { id: 'start', type: 'start', name: 'Start', position: { x: 0, y: 0 }, config: {} },
          {
            id: 'api',
            type: 'api',
            name: 'Health',
            position: { x: 180, y: 0 },
            config: { api_definition_id: apiId, api_version: 1 },
          },
          { id: 'end', type: 'end', name: 'End', position: { x: 360, y: 0 }, config: {} },
          {
            id: 'cleanup',
            type: 'api',
            name: 'Cleanup health check',
            position: { x: 180, y: 180 },
            config: { api_definition_id: apiId, api_version: 1 },
            phase: 'cleanup',
            run_when: 'always',
            cleanup_for: ['api'],
            best_effort: true,
          },
        ],
        edges: [
          {
            id: 'start-api',
            source: 'start',
            target: 'api',
            condition: null,
            mappings: [
              {
                source: { node_id: 'start', path: 'variables.missing' },
                target: { node_id: 'api', location: 'header', key: 'x-s58-fixture' },
              },
            ],
          },
          { id: 'api-end', source: 'api', target: 'end', condition: null, mappings: [] },
        ],
      },
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function publishWorkflow(
  request: APIRequestContext,
  projectId: string,
  workflowId: string,
  headers: Record<string, string>,
): Promise<void> {
  const response = await request.post(
    `/api/v1/projects/${projectId}/workflows/${workflowId}/versions`,
    { headers },
  )
  expect(response.status(), await response.text()).toBe(200)
}

async function createReadyContext(
  request: APIRequestContext,
  organizationId: string,
  projectId: string,
  suffix: string,
  userHeaders: Record<string, string>,
): Promise<ReadyContext> {
  const accountResponse = await request.post(
    `/api/v1/organizations/${organizationId}/service-accounts`,
    {
      headers: userHeaders,
      data: {
        name: `s58-repair-${suffix}`,
        account_key: `s58-repair-${suffix}`,
        scopes: ['mcp:evidence:write'],
        metadata: {},
      },
    },
  )
  expect(accountResponse.status(), await accountResponse.text()).toBe(201)
  const account = (await accountResponse.json()) as IssuedServiceAccount
  const headers = { Authorization: `Bearer ${account.token}` }
  const contextResponse = await request.post('/api/v1/mcp/evidence/contexts', {
    headers,
    data: {
      project_id: projectId,
      name: `S58 Repair Context ${suffix}`,
      objective: '修复失败执行中的 Binding Mapping',
      required_evidence: ['repository'],
    },
  })
  expect(contextResponse.status(), await contextResponse.text()).toBe(201)
  const context = (await contextResponse.json()) as ReadyContext
  const evidenceResponse = await request.post(
    `/api/v1/mcp/evidence/contexts/${context.id}/java-source-snapshot`,
    {
      headers,
      data: {
        snapshot: {
          source: { ref: 'repository://s58-repair', revision: `source-${suffix}` },
          subject_ref: `flowtest://projects/${projectId}/operations/health`,
          execute_analyzed_code: false,
          files: [
            {
              path: 'src/main/java/example/HealthController.java',
              content:
                'package example; @RestController class HealthController { @GetMapping("/health") String health() { return "ok"; } }',
            },
          ],
        },
      },
    },
  )
  expect(evidenceResponse.status(), await evidenceResponse.text()).toBe(201)
  return ((await evidenceResponse.json()) as { context: ReadyContext }).context
}

async function startAndWaitForFailure(
  request: APIRequestContext,
  projectId: string,
  workflowId: string,
  environmentId: string,
  headers: Record<string, string>,
): Promise<ExecutionDetail> {
  const started = await request.post(
    `/api/v1/projects/${projectId}/workflows/${workflowId}/executions`,
    { headers, data: { environment_id: environmentId } },
  )
  expect(started.status(), await started.text()).toBe(202)
  const execution = (await started.json()) as Identified
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await request.get(
      `/api/v1/projects/${projectId}/workflow-executions/${execution.id}`,
      { headers },
    )
    expect(response.ok(), await response.text()).toBeTruthy()
    const detail = (await response.json()) as ExecutionDetail
    if (!['queued', 'running'].includes(detail.execution.status)) {
      expect(detail.execution.status, JSON.stringify(detail, null, 2)).toBe('failed')
      return detail
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error('S58 failed execution did not reach a terminal state')
}
