import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }

test('S17 Credential、只读节点拒绝与规则化 Mock 主路径', async ({ page }) => {
  test.setTimeout(90_000)
  const suffix = Date.now().toString()

  await page.goto('/')
  await authenticate(page)
  const accessToken = await accessTokenFromSession(page.request)
  const project = await firstProject(page.request, accessToken)

  await page.getByRole('link', { name: '数据与 Mock' }).click()
  await expect(page.getByRole('heading', { name: '数据与 Mock' })).toBeVisible()
  const credential = await createCredential(page, suffix)
  await rejectUnsafeSqlWorkflow(page.request, accessToken, project.id, credential.id, suffix)
  await createAndDispatchMock(page, suffix)
})

async function createCredential(page: Page, suffix: string): Promise<Identified> {
  const credentialName = `S17 只读库 ${suffix}`
  await page.getByLabel('名称').fill(credentialName)
  await page.getByLabel('Host').fill('postgres')
  await page.getByLabel('数据库').fill('flowtest')
  await page.getByLabel('用户名').fill('flowtest')
  await page.getByLabel('密码/访问密钥').fill(`not-visible-${suffix}`)
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/credentials') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /加密保存/ }).click()
  const response = await created
  expect(response.ok(), await response.text()).toBeTruthy()
  await expect(page.getByRole('row').filter({ hasText: credentialName })).toBeVisible()
  await expect(page.locator('body')).not.toContainText(`not-visible-${suffix}`)
  return (await response.json()) as Identified
}

async function createAndDispatchMock(page: Page, suffix: string) {
  const serviceName = `S17 用户 Mock ${suffix}`
  const slug = `s17-user-${suffix}`
  await page.getByRole('tab', { name: 'Mock 服务' }).click()
  await page.getByPlaceholder('用户服务 Mock').fill(serviceName)
  await page.getByPlaceholder('user-service').fill(slug)
  const serviceCreated = page.waitForResponse(
    (response) =>
      response.url().endsWith('/mock-services') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /新\s*建/ }).click()
  expect((await serviceCreated).ok()).toBeTruthy()
  await expect(page.getByText(`/api/v1/mock/${slug}/`)).toBeVisible()

  const routeCard = page.locator('.ant-card').filter({ hasText: '新增路由规则' })
  await routeCard.getByLabel('名称').fill('查询用户')
  await routeCard.getByLabel('路径').fill('/users/{user_id}')
  await routeCard.getByLabel('响应模板（JSON）').fill('{"id":"{{path.user_id}}"}')
  const routeCreated = page.waitForResponse(
    (response) =>
      response.url().includes('/mock-services/') &&
      response.url().endsWith('/routes') &&
      response.request().method() === 'POST',
  )
  await routeCard.getByRole('button', { name: '保存路由' }).click()
  expect((await routeCreated).ok()).toBeTruthy()
  await expect(page.getByRole('row').filter({ hasText: '查询用户' })).toBeVisible()

  const dispatched = await page.request.get(`/api/v1/mock/${slug}/users/42`)
  expect(dispatched.ok(), await dispatched.text()).toBeTruthy()
  expect(await dispatched.json()).toEqual({ id: '42' })
  await page.getByRole('tab', { name: '请求日志' }).click()
  await expect(page.getByRole('row').filter({ hasText: '/users/42' })).toBeVisible({
    timeout: 10_000,
  })
}

async function rejectUnsafeSqlWorkflow(
  request: APIRequestContext,
  token: string,
  projectId: string,
  credentialId: string,
  suffix: string,
) {
  const workflow = await request.post(`/api/v1/projects/${projectId}/workflows`, {
    headers: authorization(token),
    data: {
      name: `S17 非法 SQL ${suffix}`,
      description: '验证发布阶段拒绝写入 SQL',
      definition: {
        schema_version: '1.0',
        variables: {},
        nodes: [
          { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 0 }, config: {} },
          {
            id: 'sql',
            type: 'sql',
            name: '危险写入',
            position: { x: 240, y: 0 },
            config: {
              credential_id: credentialId,
              query: 'DELETE FROM users',
              parameters: {},
              timeout_seconds: 30,
            },
          },
          { id: 'end', type: 'end', name: '结束', position: { x: 480, y: 0 }, config: {} },
        ],
        edges: [
          { id: 'start-sql', source: 'start', target: 'sql', condition: null, mappings: [] },
          { id: 'sql-end', source: 'sql', target: 'end', condition: null, mappings: [] },
        ],
        settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
      },
    },
  })
  expect(workflow.ok(), await workflow.text()).toBeTruthy()
  const workflowId = ((await workflow.json()) as Identified).id
  const published = await request.post(
    `/api/v1/projects/${projectId}/workflows/${workflowId}/versions`,
    { headers: authorization(token) },
  )
  expect(published.status()).toBe(422)
  expect((await published.json()).error.code).toBe('UNSAFE_DATA_NODE')
}

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function firstProject(request: APIRequestContext, token: string): Promise<Identified> {
  const response = await request.get('/api/v1/projects?page=1&page_size=1', {
    headers: authorization(token),
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const body = (await response.json()) as { items: Identified[] }
  expect(body.items.length).toBeGreaterThan(0)
  return body.items[0]
}

function authorization(token: string) {
  return { Authorization: `Bearer ${token}` }
}
