import { readFileSync } from 'node:fs'

import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Organization = { id: string }
type Project = { id: string }
type Service = { id: string }
type ApiDetail = {
  definition: { id: string }
  version: { contract_fingerprint: string }
}
type FlowSpecOperation = {
  ref: string
  method: string
  path: string
  contract_fingerprint: string
}
type CompiledFlowSpec = {
  operations: FlowSpecOperation[]
  nodes: Array<{ id: string; kind: string }>
  edges: Array<{
    id: string
    source: string
    target: string
    mappings: Array<{ target: { location: string; key: string } }>
  }>
}
type ChangeSet = {
  id: string
  status: string
  review_status: string
  validation: { valid: boolean }
}
type AppliedFlow = { workflow_id: string; draft_revision: number; fingerprint: string }
type Workflow = { draft_definition: { nodes: Array<{ id: string; type: string }> } }

test('S50 Golden Plan 编译产物可审核并创建 Workflow Draft', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)

  const accessToken = await refreshAccessToken(page.request)
  const headers = { Authorization: `Bearer ${accessToken}` }
  const organizationsResponse = await page.request.get('/api/v1/organizations', { headers })
  expect(organizationsResponse.ok()).toBeTruthy()
  const organizations = (await organizationsResponse.json()) as Organization[]
  expect(organizations.length).toBeGreaterThan(0)
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`
  const projectResponse = await page.request.post('/api/v1/projects', {
    headers,
    data: {
      name: `S50 E2E ${suffix}`,
      description: 'S50 Login Create Query compiled FlowSpec',
      organization_id: organizations[0].id,
    },
  })
  expect(projectResponse.status()).toBe(201)
  const project = (await projectResponse.json()) as Project
  const serviceResponse = await page.request.post(`/api/v1/projects/${project.id}/services`, {
    headers,
    data: { service_key: 'orders', name: `S50 Orders ${suffix}` },
  })
  expect(serviceResponse.status()).toBe(201)
  const service = (await serviceResponse.json()) as Service

  const spec = loadGoldenFlowSpec()
  const operationMappings: Record<string, string> = {}
  const operationVersionMappings: Record<string, number> = {}
  for (const operation of spec.operations) {
    const apiResponse = await page.request.post(`/api/v1/projects/${project.id}/apis`, {
      headers,
      data: {
        name: `S50 ${operation.ref} ${suffix}`,
        service_id: service.id,
        request: { method: operation.method, path: operation.path, body_kind: 'none' },
      },
    })
    expect(apiResponse.status()).toBe(201)
    const api = (await apiResponse.json()) as ApiDetail
    expect(api.version.contract_fingerprint).toHaveLength(64)
    operation.contract_fingerprint = api.version.contract_fingerprint
    operationMappings[operation.ref] = api.definition.id
    operationVersionMappings[operation.ref] = 1
  }

  const validatedResponse = await page.request.post(
    `/api/v1/projects/${project.id}/flow-specs/validate`,
    { headers, data: { spec } },
  )
  expect(validatedResponse.status()).toBe(200)
  expect((await validatedResponse.json()) as { validation: { valid: boolean } }).toMatchObject({
    validation: { valid: true },
  })

  const importResponse = await page.request.post(
    `/api/v1/projects/${project.id}/flow-specs/imports`,
    {
      headers,
      data: {
        spec,
        source_ref: 'golden://s50/login-create-query',
        service_mappings: { orders: service.id },
        operation_mappings: operationMappings,
        operation_version_mappings: operationVersionMappings,
      },
    },
  )
  expect(importResponse.status()).toBe(201)
  const changeSet = (await importResponse.json()) as ChangeSet
  expect(changeSet).toMatchObject({
    status: 'draft',
    review_status: 'pending',
    validation: { valid: true },
  })

  const reviewedResponse = await page.request.post(
    `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSet.id}/review`,
    { headers, data: { accept: true, note: 'S50 Golden 编译证据已人工确认' } },
  )
  expect(reviewedResponse.status()).toBe(200)
  expect((await reviewedResponse.json()) as ChangeSet).toMatchObject({
    status: 'accepted',
    review_status: 'accepted',
  })
  const appliedResponse = await page.request.post(
    `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSet.id}/apply`,
    { headers },
  )
  expect(appliedResponse.status()).toBe(200)
  const applied = (await appliedResponse.json()) as AppliedFlow
  expect(applied.draft_revision).toBe(1)
  expect(applied.fingerprint).toHaveLength(64)

  const workflowResponse = await page.request.get(
    `/api/v1/projects/${project.id}/workflows/${applied.workflow_id}`,
    { headers },
  )
  expect(workflowResponse.ok()).toBeTruthy()
  const workflow = (await workflowResponse.json()) as Workflow
  const nodeTypes = new Set(workflow.draft_definition.nodes.map((node) => node.type))
  expect(nodeTypes.has('api')).toBeTruthy()
  expect(nodeTypes.has('extract')).toBeTruthy()
  expect(nodeTypes.has('assert')).toBeTruthy()
  expect(spec.edges.some((edge) => edge.mappings.length > 0)).toBeTruthy()
})

async function refreshAccessToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

function loadGoldenFlowSpec(): CompiledFlowSpec {
  const fixture = new URL(
    '../../backend/tests/fixtures/v6_golden/login-create-query.compiled.flowspec-v1.json',
    import.meta.url,
  )
  return JSON.parse(readFileSync(fixture, 'utf8')) as CompiledFlowSpec
}
