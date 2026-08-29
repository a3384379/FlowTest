import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type IssuedServiceAccount = { token: string }
type Organization = { id: string }
type Project = { id: string }
type MappingCandidate = {
  id: string
  kind: string
  selection_status: string
  evidence_refs: string[]
}
type MappingConflict = { candidate_ids: string[] }
type AdapterResponse = {
  context: {
    id: string
    status: string
    current_revision: number
    revision: { snapshot: { conflict_snapshot: { conflicts: unknown[] } } }
  }
  entity_mapping: {
    candidates: MappingCandidate[]
    conflicts: MappingConflict[]
  }
}

test('S52 Java/DB Evidence 形成可追溯候选并显式暴露歧义', async ({ page }) => {
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
      name: `S52 E2E ${suffix}`,
      description: 'S52 Evidence Adapter Compose 验证',
      organization_id: organizationId,
    },
  })
  expect(projectResponse.status()).toBe(201)
  const project = (await projectResponse.json()) as Project
  const account = await createServiceAccount(
    page.request,
    organizationId,
    userHeaders,
    `s52-evidence-${suffix}`,
  )
  const evidenceHeaders = { Authorization: `Bearer ${account.token}` }

  const begunResponse = await page.request.post('/api/v1/mcp/evidence/contexts', {
    headers: evidenceHeaders,
    data: {
      project_id: project.id,
      name: 'S52 Evidence Adapter Context',
      objective: '验证 Java 与数据库证据驱动实体映射候选',
      required_evidence: ['repository', 'data_profile'],
    },
  })
  expect(begunResponse.status(), await begunResponse.text()).toBe(201)
  const contextId = ((await begunResponse.json()) as { id: string }).id

  const javaResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${contextId}/java-evidence`,
    {
      headers: evidenceHeaders,
      data: { evidence: javaEvidence(project.id) },
    },
  )
  expect(javaResponse.status(), await javaResponse.text()).toBe(201)
  expect(((await javaResponse.json()) as AdapterResponse).context.status).toBe('incomplete')

  const databaseResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${contextId}/database-evidence`,
    {
      headers: evidenceHeaders,
      data: { evidence: databaseEvidence(project.id, 'orders', 'orders') },
    },
  )
  expect(databaseResponse.status(), await databaseResponse.text()).toBe(201)
  const ready = (await databaseResponse.json()) as AdapterResponse
  expect(ready.context.status).toBe('ready')
  expect(new Set(ready.entity_mapping.candidates.map((candidate) => candidate.kind))).toEqual(
    new Set([
      'operation_entity',
      'request_field_column',
      'response_field_column',
      'operation_state',
    ]),
  )
  expect(ready.entity_mapping.conflicts).toEqual([])
  expect(
    ready.entity_mapping.candidates.every(
      (candidate) =>
        candidate.selection_status === 'proposed' && candidate.evidence_refs.length > 0,
    ),
  ).toBe(true)

  const inspectedResponse = await page.request.get(
    `/api/v1/mcp/evidence/contexts/${contextId}/entity-mapping`,
    { headers: evidenceHeaders },
  )
  expect(inspectedResponse.ok()).toBeTruthy()
  expect(await inspectedResponse.json()).toEqual(ready.entity_mapping)

  const writeSqlLiteral = 'DROP TABLE orders'
  const unsafeDatabase = databaseEvidence(project.id, 'unsafe-orders', 'unsafe_orders')
  unsafeDatabase.tables[0].columns[0].check_expression = writeSqlLiteral
  const unsafeResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${contextId}/database-evidence`,
    {
      headers: evidenceHeaders,
      data: { evidence: unsafeDatabase },
    },
  )
  expect(unsafeResponse.status()).toBe(422)
  expect(await unsafeResponse.text()).not.toContain(writeSqlLiteral)

  const ambiguousResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${contextId}/database-evidence`,
    {
      headers: evidenceHeaders,
      data: {
        evidence: databaseEvidence(project.id, 'archived-orders', 'archived_orders'),
      },
    },
  )
  expect(ambiguousResponse.status(), await ambiguousResponse.text()).toBe(201)
  const ambiguous = (await ambiguousResponse.json()) as AdapterResponse
  expect(ambiguous.context.status).toBe('conflicted')
  expect(ambiguous.context.revision.snapshot.conflict_snapshot.conflicts.length).toBeGreaterThan(0)
  expect(ambiguous.entity_mapping.conflicts.length).toBeGreaterThan(0)
  const conflictedIds = new Set(
    ambiguous.entity_mapping.conflicts.flatMap((conflict) => conflict.candidate_ids),
  )
  expect(
    ambiguous.entity_mapping.candidates
      .filter((candidate) => conflictedIds.has(candidate.id))
      .every((candidate) => candidate.selection_status === 'proposed'),
  ).toBe(true)
})

async function refreshAccessToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createServiceAccount(
  request: APIRequestContext,
  organizationId: string,
  headers: { Authorization: string },
  key: string,
): Promise<IssuedServiceAccount> {
  const response = await request.post(`/api/v1/organizations/${organizationId}/service-accounts`, {
    headers,
    data: {
      name: key,
      account_key: key,
      scopes: ['mcp:evidence:write'],
      metadata: {},
    },
  })
  expect(response.status()).toBe(201)
  return (await response.json()) as IssuedServiceAccount
}

function javaEvidence(projectId: string) {
  const operationRef = 'operation://POST/api/orders'
  return {
    schema_version: 'flowtest-java-evidence-v1',
    provider: { name: 'e2e-code-mcp', version: '1.0.0' },
    source: { ref: 'repository://e2e-orders', revision: 'e2e-java-v1' },
    subject_ref: `flowtest://projects/${projectId}/operations/orders`,
    claims: [
      {
        id: 'route-create',
        kind: 'controller_route',
        source_path: 'src/OrderController.java:20',
        operation_ref: operationRef,
        controller_ref: 'java://OrderController',
        handler: 'create',
        method: 'POST',
        path: '/api/orders',
        confidence: 1,
        deterministic: true,
      },
      {
        id: 'request-product',
        kind: 'dto_field',
        source_path: 'src/CreateOrderRequest.java:4',
        operation_ref: operationRef,
        direction: 'request',
        dto_type: 'CreateOrderRequest',
        field_name: 'productId',
        field_type: 'String',
        confidence: 1,
        deterministic: true,
      },
      {
        id: 'response-id',
        kind: 'dto_field',
        source_path: 'src/OrderDto.java:3',
        operation_ref: operationRef,
        direction: 'response',
        dto_type: 'OrderDto',
        field_name: 'id',
        field_type: 'String',
        confidence: 1,
        deterministic: true,
      },
      {
        id: 'entity-order',
        kind: 'entity',
        source_path: 'src/Order.java:4',
        entity_ref: 'entity://Order',
        class_name: 'Order',
        table_ref: 'table://public/orders',
        operation_refs: [operationRef],
        confidence: 1,
        deterministic: true,
      },
      {
        id: 'entity-archived-order',
        kind: 'entity',
        source_path: 'src/ArchivedOrder.java:4',
        entity_ref: 'entity://ArchivedOrder',
        class_name: 'ArchivedOrder',
        table_ref: 'table://public/archived_orders',
        operation_refs: [operationRef],
        confidence: 1,
        deterministic: true,
      },
    ],
    confidence: 1,
    deterministic: true,
  }
}

function databaseEvidence(projectId: string, sourceKey: string, tableName: string) {
  return {
    schema_version: 'flowtest-database-evidence-v1',
    provider: { name: 'e2e-database-mcp', version: '1.0.0' },
    source: { ref: `database-profile://${sourceKey}`, revision: 'e2e-schema-v1' },
    subject_ref: `flowtest://projects/${projectId}/operations/orders`,
    tables: [
      {
        schema_name: 'public',
        name: tableName,
        columns: [
          {
            name: 'id',
            data_type: 'uuid',
            nullable: false,
            primary_key: true,
            unique: true,
            masked_example: '***0001',
            check_expression: undefined as string | undefined,
          },
          {
            name: 'product_id',
            data_type: 'uuid',
            nullable: false,
            masked_example: '***1001',
          },
          {
            name: 'status',
            data_type: 'varchar',
            nullable: false,
            enum_values: ['created', 'cancelled'],
            check_expression: "status IN ('created', 'cancelled')",
            masked_example: '***ated',
          },
        ],
      },
    ],
    confidence: 1,
    deterministic: true,
  }
}
