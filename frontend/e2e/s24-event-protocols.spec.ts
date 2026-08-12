import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }

test('S24 Kafka Registry 与 WebSocket 真实调试主路径', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/')
  await authenticate(page)
  const token = await accessTokenFromSession(page.request)
  const project = await createEventProject(page.request, token)
  await createEventSource(page.request, token, project.id, 'kafka')
  await createEventSource(page.request, token, project.id, 'websocket')
  await registerOrderSchema(page.request)

  await page.goto(`/projects/${project.id}/protocols`)
  await expect(page.getByRole('heading', { name: '多协议接口工作台' })).toBeVisible()
  await page.getByText('Kafka', { exact: true }).click()
  await expect(page.getByText('禁止 AdminClient、自动提交和无界消费')).toBeVisible()
  await importRegistrySchema(page)
  await runKafkaExchange(page)

  await page.getByText('WebSocket', { exact: true }).click()
  await expect(page.getByText('连接固定到同一 Runner，丢失后从 Connect 重试')).toBeVisible()
  await runWebSocketExchange(page)
})

async function importRegistrySchema(page: Page) {
  await page.getByRole('button', { name: /导入消息 Schema/ }).click()
  await page.getByLabel('名称').fill(`S24 Order Schema ${Date.now()}`)
  await page.getByLabel('Subject').fill('flowtest.orders-value')
  const response = page.waitForResponse(
    (item) => item.url().includes('/schemas/import') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '校验并保存' }).click()
  const imported = await response
  expect(imported.ok(), await imported.text()).toBeTruthy()
}

async function runKafkaExchange(page: Page) {
  await page.getByLabel('Kafka Schema').click()
  await page.getByText(/S24 Order Schema/).click()
  const produced = page.waitForResponse(
    (item) => item.url().endsWith('/kafka/produce') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Produce' }).click()
  expect((await produced).ok()).toBeTruthy()
  const consumed = page.waitForResponse(
    (item) => item.url().endsWith('/kafka/consume') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /Consume/ }).click()
  expect((await consumed).ok()).toBeTruthy()
  await page.getByText('Exchange', { exact: true }).click()
  await expect(page.locator('.protocol-result')).toContainText('"auto_commit": false')
  await expect(page.locator('.protocol-result')).toContainText('order-42')
}

async function runWebSocketExchange(page: Page) {
  const exchanged = page.waitForResponse(
    (item) => item.url().endsWith('/websocket/exchange') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /Connect.*Send.*Await.*Close/ }).click()
  expect((await exchanged).ok()).toBeTruthy()
  await page.getByText('Exchange', { exact: true }).click()
  await expect(page.locator('.protocol-result')).toContainText('"operation": "exchange"')
  await expect(page.locator('.protocol-result')).toContainText('order-42')
}

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createEventProject(request: APIRequestContext, token: string): Promise<Identified> {
  const headers = { Authorization: `Bearer ${token}` }
  const response = await request.post('/api/v1/projects', {
    headers,
    data: { name: `S24 浏览器 ${Date.now()}`, description: 'S24 Playwright' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const project = (await response.json()) as Identified
  const policy = await request.put(`/api/v1/projects/${project.id}/security-policy`, {
    headers,
    data: {
      allowed_hosts: ['mock-target', 'redpanda'],
      allowed_private_cidrs: ['172.16.0.0/12'],
    },
  })
  expect(policy.ok(), await policy.text()).toBeTruthy()
  return project
}

async function createEventSource(
  request: APIRequestContext,
  token: string,
  projectId: string,
  kind: 'kafka' | 'websocket',
) {
  const response = await request.post('/api/v1/event-sources', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      project_id: projectId,
      kind,
      name: kind === 'kafka' ? 'S24 Redpanda' : 'S24 WebSocket Echo',
      bootstrap_servers: kind === 'kafka' ? ['redpanda:9092'] : undefined,
      schema_registry_url: kind === 'kafka' ? 'http://redpanda:8081' : undefined,
      websocket_url: kind === 'websocket' ? 'ws://mock-target:8080/ws/echo' : undefined,
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

async function registerOrderSchema(request: APIRequestContext) {
  const schema = JSON.stringify({
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    type: 'object',
    required: ['id'],
    properties: { id: { type: 'string' } },
    additionalProperties: false,
  })
  const response = await request.post(
    'http://localhost:8081/subjects/flowtest.orders-value/versions',
    { data: { schemaType: 'JSON', schema } },
  )
  expect(response.ok(), await response.text()).toBeTruthy()
}
