import { createHash, randomUUID } from 'node:crypto'

import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

type IssuedServiceAccount = { token: string }
type Organization = { id: string }
type Project = { id: string }
type TestContext = {
  id: string
  status: string
  current_revision: number
  revision: { id: string; fingerprint: string }
}
type FlowProposal = {
  dry_run: boolean
  status: string
  change_set_id: string | null
  context_fingerprint: string
}

test('S49 Context、Evidence 与 Draft Proposal 受控闭环', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)

  const accessToken = await refreshAccessToken(page.request)
  const userHeaders = { Authorization: `Bearer ${accessToken}` }
  const organizationsResponse = await page.request.get('/api/v1/organizations', {
    headers: userHeaders,
  })
  expect(organizationsResponse.ok()).toBeTruthy()
  const organizations = (await organizationsResponse.json()) as Organization[]
  expect(organizations.length).toBeGreaterThan(0)
  const organizationId = organizations[0].id
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`

  const projectResponse = await page.request.post('/api/v1/projects', {
    headers: userHeaders,
    data: {
      name: `S49 E2E ${suffix}`,
      description: 'S49 Context/Evidence Compose 验证',
      organization_id: organizationId,
    },
  })
  expect(projectResponse.status()).toBe(201)
  const project = (await projectResponse.json()) as Project

  const combined = await createServiceAccount(
    page.request,
    organizationId,
    userHeaders,
    `s49-combined-${suffix}`,
    ['mcp:evidence:write', 'mcp:flow:propose'],
  )
  const legacy = await createServiceAccount(
    page.request,
    organizationId,
    userHeaders,
    `s49-legacy-${suffix}`,
    ['mcp:write'],
  )
  const contextPayload = {
    project_id: project.id,
    name: 'S49 Compose Context',
    objective: '验证版本化证据和只进入 Draft 的 FlowSpec 提案',
    required_evidence: ['contract'],
  }

  const legacyAttempt = await page.request.post('/api/v1/mcp/evidence/contexts', {
    headers: bearerHeaders(legacy.token),
    data: contextPayload,
  })
  expect(legacyAttempt.status()).toBe(403)

  const sensitiveContextLiteral = 'password=s49-raw-context-secret'
  const sensitiveContextAttempt = await page.request.post('/api/v1/mcp/evidence/contexts', {
    headers: bearerHeaders(combined.token),
    data: { ...contextPayload, objective: sensitiveContextLiteral },
  })
  expect(sensitiveContextAttempt.status()).toBe(422)
  expect(await sensitiveContextAttempt.text()).not.toContain(sensitiveContextLiteral)

  const begunResponse = await page.request.post('/api/v1/mcp/evidence/contexts', {
    headers: bearerHeaders(combined.token),
    data: contextPayload,
  })
  expect(begunResponse.status()).toBe(201)
  const begun = (await begunResponse.json()) as TestContext
  expect(begun.status).toBe('collecting')
  expect(begun.current_revision).toBe(1)

  const leakedLiteral = 'Bearer s49-raw-secret-value'
  const unsafeResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${begun.id}/evidence`,
    {
      headers: bearerHeaders(combined.token),
      data: {
        envelope: evidenceEnvelope(project.id, `Authorization: ${leakedLiteral}`),
      },
    },
  )
  expect(unsafeResponse.status()).toBe(422)
  expect(await unsafeResponse.text()).not.toContain(leakedLiteral)

  const evidenceResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${begun.id}/evidence`,
    {
      headers: bearerHeaders(combined.token),
      data: {
        envelope: evidenceEnvelope(
          project.id,
          'Create 返回的标识会绑定到 Query 请求，并由 Contract Revision 约束。',
        ),
      },
    },
  )
  expect(evidenceResponse.status()).toBe(201)
  const ready = (await evidenceResponse.json()) as TestContext
  expect(ready.status).toBe('ready')
  expect(ready.current_revision).toBe(2)
  expect(ready.revision.fingerprint).not.toBe(begun.revision.fingerprint)

  const requirementsResponse = await page.request.get(
    `/api/v1/mcp/evidence/contexts/${begun.id}/requirements`,
    { headers: bearerHeaders(combined.token) },
  )
  expect(requirementsResponse.ok()).toBeTruthy()
  expect(await requirementsResponse.json()).toMatchObject({ complete: true, missing: [] })

  const proposalPayload = {
    project_id: project.id,
    context_id: ready.id,
    context_revision_id: ready.revision.id,
    spec: {
      schema_version: 'flowtest-flow-spec-v1',
      name: 'S49 E2E Draft',
      nodes: [
        { id: 'start', kind: 'start', name: 'Start' },
        { id: 'end', kind: 'end', name: 'End' },
      ],
      edges: [{ id: 'start-end', source: 'start', target: 'end' }],
    },
  }
  const missingKey = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: bearerHeaders(combined.token),
    data: proposalPayload,
  })
  expect(missingKey.status()).toBe(422)

  const previewResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: {
      ...bearerHeaders(combined.token),
      'Idempotency-Key': `s49-preview-${suffix}`,
    },
    data: proposalPayload,
  })
  expect(previewResponse.status()).toBe(202)
  const preview = (await previewResponse.json()) as FlowProposal
  expect(preview).toMatchObject({ dry_run: true, status: 'preview', change_set_id: null })

  const persistedPayload = { ...proposalPayload, dry_run: false }
  const invalidProjectResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: {
      ...bearerHeaders(combined.token),
      'Idempotency-Key': `s49-invalid-project-${suffix}`,
    },
    data: { ...persistedPayload, project_id: randomUUID() },
  })
  expect(invalidProjectResponse.status()).toBe(404)
  expect(await invalidProjectResponse.json()).toMatchObject({
    error: { code: 'TEST_CONTEXT_NOT_FOUND' },
  })

  const proposalHeaders = {
    ...bearerHeaders(combined.token),
    'Idempotency-Key': `s49-draft-${suffix}`,
  }
  const proposedResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: proposalHeaders,
    data: persistedPayload,
  })
  expect(proposedResponse.status()).toBe(202)
  const proposed = (await proposedResponse.json()) as FlowProposal
  expect(proposed.status).toBe('draft')
  expect(proposed.change_set_id).not.toBeNull()
  expect(proposed.context_fingerprint).toBe(ready.revision.fingerprint)

  const repeatedResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: proposalHeaders,
    data: persistedPayload,
  })
  expect(repeatedResponse.status()).toBe(202)
  expect(((await repeatedResponse.json()) as FlowProposal).change_set_id).toBe(
    proposed.change_set_id,
  )

  const closedResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${begun.id}/close`,
    { headers: bearerHeaders(combined.token) },
  )
  expect(closedResponse.ok()).toBeTruthy()
  expect((await closedResponse.json()) as TestContext).toMatchObject({ status: 'closed' })
})

async function refreshAccessToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createServiceAccount(
  request: APIRequestContext,
  organizationId: string,
  headers: Record<string, string>,
  key: string,
  scopes: string[],
): Promise<IssuedServiceAccount> {
  const response = await request.post(`/api/v1/organizations/${organizationId}/service-accounts`, {
    headers,
    data: { name: key, account_key: key, scopes, metadata: {} },
  })
  expect(response.status()).toBe(201)
  return (await response.json()) as IssuedServiceAccount
}

function bearerHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` }
}

function evidenceEnvelope(projectId: string, statement: string): JsonValue {
  const sourceRef = 'contract://payments'
  const sourceRevision = 'contract-v1'
  const subjectRef = `flowtest://projects/${projectId}/operations/create-payment`
  const finding = {
    id: 'contract-binding',
    kind: 'binding',
    semantic_role: 'normative',
    source_ref: sourceRef,
    source_revision: sourceRevision,
    subject_ref: subjectRef,
    source_path: '$.responses.201.id',
    source_content: 'interface_description',
    content_role: 'untrusted_data',
    statement,
    confidence: 0.98,
    deterministic: true,
  }
  return {
    schema_version: 'flowtest-external-evidence-v1',
    provider: { type: 'contract', name: 'contract-reader', version: '1.0.0' },
    source: { ref: sourceRef, revision: sourceRevision },
    subject_ref: subjectRef,
    findings: [{ ...finding, semantic_fingerprint: fingerprint(finding) }],
    redactions: [],
    warnings: [],
    confidence: 0.98,
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
        .map(([key, child]) => [key, canonical(child)]),
    )
  }
  return value
}
