import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }
type ExecutionDetail = {
  execution: { status: string; context: Record<string, unknown> }
  nodes: Array<{
    node_id: string
    status: string
    output: Record<string, unknown> | null
  }>
}

test('S53 Login → Create → Query → DB Read 与跨系统断言真实执行', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/')
  await authenticate(page)

  const token = await accessTokenFromSession(page.request)
  const headers = authorization(token)
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`
  const project = await createProject(page.request, headers, suffix)
  await allowComposeBackend(page.request, headers, project.id)
  const environment = await createEnvironment(page.request, headers, project.id, suffix)
  await storeAccessToken(page.request, headers, project.id, environment.id, token)
  const credential = await createDatabaseCredential(page.request, headers, project.id, suffix)

  const loginApi = await createApi(page.request, headers, project.id, {
    name: `S53 Login ${suffix}`,
    method: 'GET',
    path: '/api/v1/auth/me',
  })
  const createApiId = await createApi(page.request, headers, project.id, {
    name: `S53 Create ${suffix}`,
    method: 'POST',
    path: `/api/v1/projects/${project.id}/services`,
    body: {
      service_key: 's53-placeholder',
      name: 'S53 placeholder',
      description: 'S53 runtime data oracle acceptance',
      service_type: 'http',
      enabled: true,
    },
  })
  const queryApi = await createApi(page.request, headers, project.id, {
    name: `S53 Query ${suffix}`,
    method: 'GET',
    path: `/api/v1/projects/${project.id}/services`,
  })
  const workflow = await createWorkflow(page.request, headers, project.id, suffix, {
    loginApi,
    createApi: createApiId,
    queryApi,
    credentialId: credential.id,
  })

  const published = await page.request.post(
    `/api/v1/projects/${project.id}/workflows/${workflow.id}/versions`,
    { headers },
  )
  expect(published.ok(), await published.text()).toBeTruthy()
  const started = await page.request.post(
    `/api/v1/projects/${project.id}/workflows/${workflow.id}/executions`,
    { headers, data: { environment_id: environment.id } },
  )
  expect(started.status(), await started.text()).toBe(202)
  const execution = (await started.json()) as Identified
  const detail = await waitForExecution(page.request, headers, project.id, execution.id)

  expect(detail.execution.status).toBe('passed')
  const nodes = new Map(detail.nodes.map((node) => [node.node_id, node]))
  expect(nodes.get('login')?.status).toBe('passed')
  expect(nodes.get('create')?.status).toBe('passed')
  expect(nodes.get('query')?.status).toBe('passed')
  expect(nodes.get('db-read')?.status).toBe('passed')
  expect(nodes.get('assert-cross-api')?.output).toMatchObject({ passed: true })
  expect(nodes.get('assert-db-row')?.output).toMatchObject({ passed: true })
  expect(nodes.get('assert-db-id')?.output).toMatchObject({ passed: true })
  expect(JSON.stringify(detail)).not.toContain(token)
})

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createProject(
  request: APIRequestContext,
  headers: { Authorization: string },
  suffix: string,
): Promise<Identified> {
  const response = await request.post('/api/v1/projects', {
    headers,
    data: { name: `S53 E2E ${suffix}`, description: 'S53 Data/Oracle Compose acceptance' },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function allowComposeBackend(
  request: APIRequestContext,
  headers: { Authorization: string },
  projectId: string,
): Promise<void> {
  const response = await request.put(`/api/v1/projects/${projectId}/security-policy`, {
    headers,
    data: { allowed_hosts: ['backend'], allowed_private_cidrs: ['172.16.0.0/12'] },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

async function createEnvironment(
  request: APIRequestContext,
  headers: { Authorization: string },
  projectId: string,
  suffix: string,
): Promise<Identified> {
  const response = await request.post(`/api/v1/projects/${projectId}/environments`, {
    headers,
    data: { name: `S53 Target ${suffix}`, base_url: 'http://backend:8000' },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function storeAccessToken(
  request: APIRequestContext,
  headers: { Authorization: string },
  projectId: string,
  environmentId: string,
  token: string,
): Promise<void> {
  const response = await request.put(`/api/v1/projects/${projectId}/secrets`, {
    headers,
    data: { name: 's53_access_token', value: token, environment_id: environmentId },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  expect(await response.text()).not.toContain(token)
}

async function createDatabaseCredential(
  request: APIRequestContext,
  headers: { Authorization: string },
  projectId: string,
  suffix: string,
): Promise<Identified> {
  const response = await request.post('/api/v1/credentials', {
    headers,
    data: {
      project_id: projectId,
      name: `S53 PostgreSQL ${suffix}`,
      kind: 'postgresql',
      host: 'postgres',
      port: 5432,
      database_name: process.env.POSTGRES_DB ?? 'flowtest',
      username: process.env.POSTGRES_USER ?? 'flowtest',
      secret: process.env.POSTGRES_PASSWORD ?? 'flowtest',
      tls_enabled: false,
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function createApi(
  request: APIRequestContext,
  headers: { Authorization: string },
  projectId: string,
  input: { name: string; method: 'GET' | 'POST'; path: string; body?: Record<string, unknown> },
): Promise<string> {
  const response = await request.post(`/api/v1/projects/${projectId}/apis`, {
    headers,
    data: {
      name: input.name,
      request: {
        method: input.method,
        path: input.path,
        body_kind: input.body === undefined ? 'none' : 'json',
        body: input.body,
        auth: { kind: 'bearer', values: { token: '{{secret.s53_access_token}}' } },
      },
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return ((await response.json()) as { definition: Identified }).definition.id
}

async function createWorkflow(
  request: APIRequestContext,
  headers: { Authorization: string },
  projectId: string,
  suffix: string,
  resources: {
    loginApi: string
    createApi: string
    queryApi: string
    credentialId: string
  },
): Promise<Identified> {
  const node = (id: string, type: string, config: Record<string, unknown> = {}) => ({
    id,
    type,
    name: id,
    position: { x: 0, y: 0 },
    config,
  })
  const nodes = [
    node('start', 'start', { synthetic_variables: { 'synthetic.service_key': 'unique_string' } }),
    node('login', 'api', { api_definition_id: resources.loginApi }),
    node('create', 'api', { api_definition_id: resources.createApi }),
    node('extract-id', 'extract', {
      source_node_id: 'create',
      expression: 'body.id',
      variable: 'created.service_id',
    }),
    node('query', 'api', { api_definition_id: resources.queryApi }),
    node('assert-cross-api', 'assert', {
      source_node_id: 'query',
      expression: 'body[0].id',
      expected_source_node_id: 'create',
      expected_expression: 'body.id',
    }),
    node('db-read', 'sql', {
      credential_id: resources.credentialId,
      query: 'SELECT "id" FROM "services" WHERE "id" = :service_id LIMIT 2',
      parameters: { service_id: '{{created.service_id}}' },
      timeout_seconds: 30,
    }),
    node('assert-db-row', 'assert', {
      source_node_id: 'db-read',
      expression: 'rows[0]',
      operator: 'exists',
    }),
    node('assert-db-id', 'assert', {
      source_node_id: 'db-read',
      expression: 'rows[0].id',
      expected_source_node_id: 'query',
      expected_expression: 'body[0].id',
    }),
    node('end', 'end'),
  ]
  const chain = nodes.map((item) => item.id)
  const edges = chain.slice(0, -1).map((source, index) => ({
    id: `${source}-${chain[index + 1]}`,
    source,
    target: chain[index + 1],
    condition: null,
    mappings: [],
  }))
  edges.push({
    id: 'start-create-data',
    source: 'start',
    target: 'create',
    condition: null,
    mappings: [
      syntheticBodyMapping('service_key', 'a-s53-{{value}}'),
      syntheticBodyMapping('name', 'S53 {{value}}'),
    ],
  })
  const response = await request.post(`/api/v1/projects/${projectId}/workflows`, {
    headers,
    data: {
      name: `S53 Data Oracle ${suffix}`,
      description: 'Login, Create, Query, DB Read, Cross-API Assert and DB Assert',
      definition: { schema_version: '1.0', variables: {}, nodes, edges },
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

function syntheticBodyMapping(key: string, template: string) {
  return {
    source: { node_id: 'start', path: 'variables."synthetic.service_key"' },
    transform: { kind: 'template', template },
    target: { node_id: 'create', location: 'body', key },
  }
}

async function waitForExecution(
  request: APIRequestContext,
  headers: { Authorization: string },
  projectId: string,
  executionId: string,
): Promise<ExecutionDetail> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await request.get(
      `/api/v1/projects/${projectId}/workflow-executions/${executionId}`,
      { headers },
    )
    expect(response.ok(), await response.text()).toBeTruthy()
    const detail = (await response.json()) as ExecutionDetail
    if (detail.execution.status !== 'running' && detail.execution.status !== 'queued') {
      return detail
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error('S53 workflow execution did not reach a terminal state')
}

function authorization(token: string) {
  return { Authorization: `Bearer ${token}` }
}
