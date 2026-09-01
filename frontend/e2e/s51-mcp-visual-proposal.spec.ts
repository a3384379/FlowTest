import { createHash } from 'node:crypto'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { authenticate } from './support/auth'

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

type Organization = { id: string }
type Project = { id: string }
type Service = { id: string }
type IssuedServiceAccount = { token: string }
type ApiDetail = {
  definition: { id: string }
  version: { contract_fingerprint: string }
}
type TestContext = {
  id: string
  status: string
  revision: { id: string; fingerprint: string }
}
type IntegrationPlan = {
  plan_fingerprint: string
  operations: Array<{ ref: string; service_ref: string }>
}
type Compilation = {
  importable: boolean
  flow_spec: Record<string, JsonValue>
  flow_spec_fingerprint: string
}
type FlowProposal = {
  dry_run: boolean
  status: string
  change_set_id: string | null
}
type ProposalInspection = {
  status: string
  review_status: string
  applied: boolean
  integration_plan: IntegrationPlan
}
type WorkflowDefinition = {
  schema_version: string
  variables: Record<string, JsonValue>
  nodes: Array<Record<string, JsonValue>>
  edges: Array<Record<string, JsonValue>>
  settings: Record<string, JsonValue>
}
type VisualProposal = {
  proposed_definition: WorkflowDefinition
}
type Workflow = {
  id: string
  name: string
  draft_revision: number
  current_version: number | null
  draft_definition: WorkflowDefinition
}
type PageResponse<T> = { items: T[]; total: number }

test('S51 MCP Draft 可视化审阅后只应用到 Workflow Draft', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)

  const accessToken = await refreshAccessToken(page.request)
  const userHeaders = { Authorization: `Bearer ${accessToken}` }
  const organizationId = await firstOrganizationId(page.request, userHeaders)
  // Decimal millisecond timestamps can look like phone/card literals to the
  // proposal security scanner. Base36 keeps the fixture unique without
  // introducing deliberately sensitive-looking test data.
  const suffix = `${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`
  const project = await createProject(page.request, organizationId, suffix, userHeaders)
  const account = await createServiceAccount(
    page.request,
    organizationId,
    userHeaders,
    `s51-planner-${suffix}`,
  )
  const mcpHeaders = { Authorization: `Bearer ${account.token}` }
  const service = await createService(page.request, project.id, suffix, userHeaders)
  const api = await createApi(page.request, project.id, service.id, suffix, userHeaders)
  const context = await createReadyContext(page.request, project.id, mcpHeaders)
  const plan = await createPlan(page.request, project.id, api.definition.id, context, mcpHeaders)

  const validationResponse = await page.request.post('/api/v1/mcp/flow/plans/validate', {
    headers: mcpHeaders,
    data: { plan },
  })
  expect(validationResponse.ok()).toBeTruthy()
  expect(await validationResponse.json()).toMatchObject({ valid: true })
  const compilationResponse = await page.request.post('/api/v1/mcp/flow/plans/compile', {
    headers: mcpHeaders,
    data: { plan },
  })
  expect(compilationResponse.ok()).toBeTruthy()
  const compilation = (await compilationResponse.json()) as Compilation
  expect(compilation.importable).toBeTruthy()
  expect(compilation.flow_spec_fingerprint).toHaveLength(64)
  const diagnosticsResponse = await page.request.post('/api/v1/mcp/flow/plans/diagnostics', {
    headers: mcpHeaders,
    data: { plan },
  })
  expect(diagnosticsResponse.ok()).toBeTruthy()
  expect(await diagnosticsResponse.json()).toMatchObject({
    plan_fingerprint: plan.plan_fingerprint,
    importable: true,
  })

  const operation = plan.operations[0]
  const proposalPayload = {
    project_id: project.id,
    context_id: context.id,
    context_revision_id: context.revision.id,
    spec: compilation.flow_spec,
    integration_plan: plan,
    compilation,
    service_mappings: { [operation.service_ref]: service.id },
    operation_mappings: { [operation.ref]: api.definition.id },
    operation_version_mappings: { [operation.ref]: 1 },
  }
  const previewResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: { ...mcpHeaders, 'Idempotency-Key': `s51-preview-${suffix}` },
    data: proposalPayload,
  })
  expect(previewResponse.status()).toBe(202)
  expect((await previewResponse.json()) as FlowProposal).toMatchObject({
    dry_run: true,
    status: 'preview',
    change_set_id: null,
  })
  const emptyChangeSets = await page.request.get(
    `/api/v1/projects/${project.id}/flow-specs/change-sets`,
    { headers: userHeaders },
  )
  expect(((await emptyChangeSets.json()) as PageResponse<unknown>).total).toBe(0)

  const draftHeaders = {
    ...mcpHeaders,
    'Idempotency-Key': `s51-draft-${suffix}`,
  }
  const draftResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: draftHeaders,
    data: { ...proposalPayload, dry_run: false },
  })
  expect(draftResponse.status()).toBe(202)
  const draft = (await draftResponse.json()) as FlowProposal
  expect(draft).toMatchObject({ dry_run: false, status: 'draft' })
  expect(draft.change_set_id).not.toBeNull()
  const repeatedResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: draftHeaders,
    data: { ...proposalPayload, dry_run: false },
  })
  expect(((await repeatedResponse.json()) as FlowProposal).change_set_id).toBe(draft.change_set_id)

  const inspectionResponse = await page.request.get(
    `/api/v1/mcp/flow/proposals/${draft.change_set_id}`,
    { headers: mcpHeaders, params: { project_id: project.id } },
  )
  expect(inspectionResponse.ok()).toBeTruthy()
  expect((await inspectionResponse.json()) as ProposalInspection).toMatchObject({
    status: 'draft',
    review_status: 'pending',
    applied: false,
    integration_plan: { plan_fingerprint: plan.plan_fingerprint },
  })
  const visualResponse = await page.request.get(
    `/api/v1/projects/${project.id}/flow-specs/change-sets/${draft.change_set_id}/visual-proposal`,
    { headers: userHeaders },
  )
  expect(visualResponse.ok()).toBeTruthy()
  const visual = (await visualResponse.json()) as VisualProposal

  await reviewAndApplyInUI(page, project.id)

  const workflowsResponse = await page.request.get(`/api/v1/projects/${project.id}/workflows`, {
    headers: userHeaders,
    params: { page: 1, page_size: 100 },
  })
  const workflows = (await workflowsResponse.json()) as PageResponse<Workflow>
  expect(workflows.total).toBe(1)
  expect(workflows.items[0]).toMatchObject({ draft_revision: 1, current_version: null })
  expect(workflows.items[0].draft_definition).toEqual(visual.proposed_definition)
  const executionsResponse = await page.request.get(
    `/api/v1/projects/${project.id}/workflow-executions`,
    {
      headers: userHeaders,
      params: { workflow_id: workflows.items[0].id, page: 1, page_size: 20 },
    },
  )
  expect(((await executionsResponse.json()) as PageResponse<unknown>).total).toBe(0)
})

async function reviewAndApplyInUI(page: Page, projectId: string): Promise<void> {
  await page.goto(`/projects/${projectId}/workflows`)
  await expect(page.getByRole('heading', { name: '流程编排' })).toBeVisible()
  await page.getByRole('button', { name: 'MCP 流程提案' }).click()
  const dialog = page.getByRole('dialog', { name: 'Flow Proposal 可视化审核' })
  await expect(dialog.getByText('提案模式')).toBeVisible()
  await expect(dialog.getByText('证据 / 置信度')).toBeVisible()
  await expect(dialog.getByText('映射差异 / 人工检查')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '发布版本' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '运行', exact: true })).toHaveCount(0)
  const apply = dialog.getByRole('button', { name: '应用到工作流草稿' })
  await expect(apply).toBeDisabled()
  await dialog.getByRole('button', { name: '接受' }).click()
  await expect(apply).toBeEnabled()
  await apply.click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('草稿 r1')).toBeVisible()
  await expect(page.getByText('未发布')).toBeVisible()
  await expect(page.getByText('暂无执行记录')).toBeVisible()
}

async function refreshAccessToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function firstOrganizationId(
  request: APIRequestContext,
  headers: Record<string, string>,
): Promise<string> {
  const response = await request.get('/api/v1/organizations', { headers })
  expect(response.ok()).toBeTruthy()
  const organizations = (await response.json()) as Organization[]
  expect(organizations.length).toBeGreaterThan(0)
  return organizations[0].id
}

async function createProject(
  request: APIRequestContext,
  organizationId: string,
  suffix: string,
  headers: Record<string, string>,
): Promise<Project> {
  const response = await request.post('/api/v1/projects', {
    headers,
    data: {
      name: `S51 E2E ${suffix}`,
      description: 'S51 MCP 可视化流程提案 Compose 验证',
      organization_id: organizationId,
    },
  })
  expect(response.status()).toBe(201)
  return (await response.json()) as Project
}

async function createServiceAccount(
  request: APIRequestContext,
  organizationId: string,
  headers: Record<string, string>,
  accountKey: string,
): Promise<IssuedServiceAccount> {
  const response = await request.post(`/api/v1/organizations/${organizationId}/service-accounts`, {
    headers,
    data: {
      name: accountKey,
      account_key: accountKey,
      scopes: ['mcp:evidence:write', 'mcp:flow:propose'],
      metadata: {},
    },
  })
  expect(response.status()).toBe(201)
  return (await response.json()) as IssuedServiceAccount
}

async function createService(
  request: APIRequestContext,
  projectId: string,
  suffix: string,
  headers: Record<string, string>,
): Promise<Service> {
  const response = await request.post(`/api/v1/projects/${projectId}/services`, {
    headers,
    data: { service_key: `s51-orders-${suffix}`, name: `S51 Orders ${suffix}` },
  })
  expect(response.status()).toBe(201)
  return (await response.json()) as Service
}

async function createApi(
  request: APIRequestContext,
  projectId: string,
  serviceId: string,
  suffix: string,
  headers: Record<string, string>,
): Promise<ApiDetail> {
  const response = await request.post(`/api/v1/projects/${projectId}/apis`, {
    headers,
    data: {
      name: `S51 Health ${suffix}`,
      service_id: serviceId,
      request: { method: 'GET', path: '/health', body_kind: 'none' },
    },
  })
  expect(response.status()).toBe(201)
  const api = (await response.json()) as ApiDetail
  expect(api.version.contract_fingerprint).toHaveLength(64)
  return api
}

async function createReadyContext(
  request: APIRequestContext,
  projectId: string,
  headers: Record<string, string>,
): Promise<TestContext> {
  const begunResponse = await request.post('/api/v1/mcp/evidence/contexts', {
    headers,
    data: {
      project_id: projectId,
      name: 'S51 Visual Proposal Context',
      objective: '编译并可视化审核健康检查集成流程',
      required_evidence: ['contract'],
    },
  })
  expect(begunResponse.status(), await begunResponse.text()).toBe(201)
  const begun = (await begunResponse.json()) as TestContext
  const evidenceResponse = await request.post(
    `/api/v1/mcp/evidence/contexts/${begun.id}/evidence`,
    {
      headers,
      data: {
        envelope: evidenceEnvelope(projectId),
      },
    },
  )
  expect(evidenceResponse.status(), await evidenceResponse.text()).toBe(201)
  const ready = (await evidenceResponse.json()) as TestContext
  expect(ready.status).toBe('ready')
  expect(ready.revision.fingerprint).not.toBe(begun.revision.fingerprint)
  return ready
}

async function createPlan(
  request: APIRequestContext,
  projectId: string,
  definitionId: string,
  context: TestContext,
  headers: Record<string, string>,
): Promise<IntegrationPlan> {
  const response = await request.post('/api/v1/mcp/flow/plans', {
    headers,
    data: {
      project_id: projectId,
      context_id: context.id,
      context_revision_id: context.revision.id,
      actors: [
        {
          id: 'operator',
          role: 'integration tester',
          evidence_refs: ['context://s51/operator'],
        },
      ],
      preconditions: [],
      target_environment: {
        key: 's51',
        source_ref: 'environment://s51',
        evidence_refs: ['environment://s51/revision/1'],
      },
      operations: [{ definition_id: definitionId }],
      cleanup_requirements: [],
    },
  })
  expect(response.ok()).toBeTruthy()
  const plan = (await response.json()) as IntegrationPlan
  expect(plan.plan_fingerprint).toHaveLength(64)
  expect(plan.operations).toHaveLength(1)
  return plan
}

function evidenceEnvelope(projectId: string): JsonValue {
  const sourceRef = 'contract://orders/health'
  const sourceRevision = 'contract-v1'
  const subjectRef = `flowtest://projects/${projectId}/operations/health`
  const finding = {
    id: 'health-contract',
    kind: 'operation',
    semantic_role: 'normative',
    source_ref: sourceRef,
    source_revision: sourceRevision,
    subject_ref: subjectRef,
    source_path: '$.responses.200',
    source_content: 'interface_description',
    content_role: 'untrusted_data',
    statement: 'Health operation returns status 200.',
    confidence: 0.99,
    deterministic: true,
  }
  return {
    schema_version: 'flowtest-external-evidence-v1',
    provider: { type: 'contract', name: 's51-contract-reader', version: '1.0.0' },
    source: { ref: sourceRef, revision: sourceRevision },
    subject_ref: subjectRef,
    findings: [{ ...finding, semantic_fingerprint: fingerprint(finding) }],
    redactions: [],
    warnings: [],
    confidence: 0.99,
    deterministic: true,
  }
}

function fingerprint(value: JsonValue): string {
  return createHash('sha256')
    .update(JSON.stringify(canonical(value)))
    .digest('hex')
}

function canonical(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(canonical)
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonical(item)]),
    )
  }
  return value
}
