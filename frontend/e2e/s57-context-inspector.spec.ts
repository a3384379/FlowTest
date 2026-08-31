import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type IssuedServiceAccount = { token: string }
type Organization = { id: string }
type Project = { id: string }
type ContextResponse = {
  id: string
  revision: { id: string; fingerprint: string }
}
type ProposalResponse = { change_set_id: string }

test('S57 Context Inspector 展示当前证据并深链到既有 Flow Proposal', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)

  const accessToken = await refreshAccessToken(page.request)
  const userHeaders = { Authorization: `Bearer ${accessToken}` }
  const organizationsResponse = await page.request.get('/api/v1/organizations', {
    headers: userHeaders,
  })
  expect(organizationsResponse.ok()).toBeTruthy()
  const organizationId = ((await organizationsResponse.json()) as Organization[])[0].id
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`

  const projectResponse = await page.request.post('/api/v1/projects', {
    headers: userHeaders,
    data: {
      name: `S57 Context Inspector ${suffix}`,
      description: 'S57 Context Inspector Compose 验证',
      organization_id: organizationId,
    },
  })
  expect(projectResponse.status()).toBe(201)
  const project = (await projectResponse.json()) as Project
  const account = await createServiceAccount(
    page.request,
    organizationId,
    userHeaders,
    `s57-context-inspector-${suffix}`,
  )
  const mcpHeaders = { Authorization: `Bearer ${account.token}` }

  const contextResponse = await page.request.post('/api/v1/mcp/evidence/contexts', {
    headers: mcpHeaders,
    data: {
      project_id: project.id,
      name: 'S57 订单上下文',
      objective: '检查 Spring 路由、状态与流程提案',
      required_evidence: ['repository'],
    },
  })
  expect(contextResponse.status(), await contextResponse.text()).toBe(201)
  const context = (await contextResponse.json()) as ContextResponse

  const evidenceResponse = await page.request.post(
    `/api/v1/mcp/evidence/contexts/${context.id}/java-source-snapshot`,
    {
      headers: mcpHeaders,
      data: { snapshot: javaSourceSnapshot(project.id) },
    },
  )
  expect(evidenceResponse.status(), await evidenceResponse.text()).toBe(201)
  const ready = ((await evidenceResponse.json()) as { context: ContextResponse }).context

  const proposalResponse = await page.request.post('/api/v1/mcp/flow/proposals', {
    headers: {
      ...mcpHeaders,
      'Idempotency-Key': `s57-context-proposal-${suffix}`,
    },
    data: {
      project_id: project.id,
      context_id: context.id,
      context_revision_id: ready.revision.id,
      dry_run: false,
      spec: {
        schema_version: 'flowtest-flow-spec-v1',
        name: 'S57 订单流程提案',
        nodes: [
          { id: 'start', kind: 'start', name: 'Start' },
          { id: 'end', kind: 'end', name: 'End' },
        ],
        edges: [{ id: 'start-end', source: 'start', target: 'end' }],
      },
    },
  })
  expect(proposalResponse.status(), await proposalResponse.text()).toBe(202)
  const proposalId = ((await proposalResponse.json()) as ProposalResponse).change_set_id

  await page.goto(`/projects/${project.id}/contexts`)

  await expect(page.getByRole('heading', { name: '上下文检查器' })).toBeVisible()
  await expect(page.getByRole('button', { name: /S57 订单上下文/ })).toBeVisible()
  await expect(
    page.getByRole('cell', { name: 'flowtest-java-spring 1.0.0', exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('cell', { name: /^OrderStatus\// }).first()).toBeVisible()
  await expect(page.getByRole('cell', { name: 'S57 订单流程提案', exact: true })).toBeVisible()

  await page.getByRole('link', { name: /打开 Proposal/ }).click()

  await expect(page).toHaveURL(
    new RegExp(`/projects/${project.id}/workflows\\?proposal=${proposalId}`),
  )
  const dialog = page.getByRole('dialog', { name: '外部 LLM / MCP 可视化流程提案' })
  await expect(dialog).toBeVisible()
  await expect(
    dialog.getByText(`S57 订单流程提案 · 草稿 · ${proposalId.slice(0, 8)}`),
  ).toBeVisible()
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
): Promise<IssuedServiceAccount> {
  const response = await request.post(`/api/v1/organizations/${organizationId}/service-accounts`, {
    headers,
    data: {
      name: key,
      account_key: key,
      scopes: ['mcp:evidence:write', 'mcp:flow:propose'],
      metadata: {},
    },
  })
  expect(response.status()).toBe(201)
  return (await response.json()) as IssuedServiceAccount
}

function javaSourceSnapshot(projectId: string) {
  return {
    source: { ref: 'repository://s57-context-inspector', revision: 'e2e-source-v1' },
    subject_ref: `flowtest://projects/${projectId}/operations/orders`,
    execute_analyzed_code: false,
    files: [
      {
        path: 'src/main/java/example/OrderController.java',
        content: `
package example;
@RestController
@RequestMapping("/api")
public class OrderController {
    @PostMapping("/orders")
    public OrderDto create(@RequestBody CreateOrderRequest request) {
        return new OrderDto();
    }
}
`,
      },
      {
        path: 'src/main/java/example/OrderDtos.java',
        content: `
package example;
class CreateOrderRequest { public OrderStatus status; }
class OrderDto { public String id; public OrderStatus status; }
enum OrderStatus { CREATED, PAID }
`,
      },
    ],
  }
}
