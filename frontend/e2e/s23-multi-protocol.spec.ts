import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }

test('S23 GraphQL、gRPC Reflection 与真实调试主路径', async ({ page }) => {
  test.setTimeout(90_000)
  await page.goto('/')
  await authenticate(page)
  const token = await accessTokenFromSession(page.request)
  const project = await createProtocolProject(page.request, token)

  await page.goto(`/projects/${project.id}/protocols`)
  await expect(page.getByRole('heading', { name: '多协议接口工作台' })).toBeVisible()
  await importGraphqlSchema(page)
  await executeGraphql(page)
  await page.getByText('gRPC', { exact: true }).click()
  await importGrpcReflection(page)
  await executeGrpc(page)
})

async function importGraphqlSchema(page: import('@playwright/test').Page) {
  const name = `S23 GraphQL ${Date.now()}`
  await page.getByRole('button', { name: /导入协议 Schema/ }).click()
  await page.getByLabel('名称').fill(name)
  const response = page.waitForResponse(
    (item) => item.url().endsWith('/api/v1/graphql/schemas') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '校验并保存' }).click()
  expect((await response).ok()).toBeTruthy()
  await expect(page.getByRole('row').filter({ hasText: name })).toBeVisible()
}

async function executeGraphql(page: import('@playwright/test').Page) {
  await page.getByLabel('GraphQL Endpoint').fill('http://mock-target:8080/graphql')
  const response = page.waitForResponse(
    (item) => item.url().endsWith('/api/v1/graphql/execute') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /执行 GraphQL/ }).click()
  expect((await response).ok()).toBeTruthy()
  await page.getByText('响应', { exact: true }).click()
  await expect(page.locator('.protocol-result')).toContainText('测试用户')
}

async function importGrpcReflection(page: import('@playwright/test').Page) {
  const name = `S23 gRPC ${Date.now()}`
  await page.getByRole('button', { name: /导入协议 Schema/ }).click()
  await page.getByLabel('名称').fill(name)
  await page.getByLabel('导入格式').click()
  await page.getByText('Server Reflection（TLS）', { exact: true }).click()
  await page.getByLabel('Schema 内容').fill('grpc-target:50051')
  await page.getByText('明文', { exact: true }).click()
  const response = page.waitForResponse(
    (item) =>
      item.url().endsWith('/api/v1/grpc/descriptors/reflection') &&
      item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '校验并保存' }).click()
  const imported = await response
  expect(imported.ok(), await imported.text()).toBeTruthy()
  const importedRow = page.getByRole('row').filter({ hasText: name })
  await expect(importedRow).toBeVisible()
  await expect(importedRow.getByRole('cell', { name: 'Reflection', exact: true })).toBeVisible()
}

async function executeGrpc(page: import('@playwright/test').Page) {
  await page.getByLabel('gRPC Endpoint').fill('grpc-target:50051')
  await page.getByRole('tabpanel', { name: '请求' }).getByText('明文', { exact: true }).click()
  const response = page.waitForResponse(
    (item) => item.url().endsWith('/api/v1/grpc/execute') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /执行 gRPC/ }).click()
  expect((await response).ok()).toBeTruthy()
  await page.getByText('响应流', { exact: true }).click()
  await expect(page.locator('.protocol-result')).toContainText('测试用户')
}

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createProtocolProject(
  request: APIRequestContext,
  token: string,
): Promise<Identified> {
  const headers = { Authorization: `Bearer ${token}` }
  const response = await request.post('/api/v1/projects', {
    headers,
    data: { name: `S23 浏览器 ${Date.now()}`, description: 'S23 Playwright' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const project = (await response.json()) as Identified
  const policy = await request.put(`/api/v1/projects/${project.id}/security-policy`, {
    headers,
    data: {
      allowed_hosts: ['mock-target', 'grpc-target'],
      allowed_private_cidrs: ['172.16.0.0/12'],
    },
  })
  expect(policy.ok(), await policy.text()).toBeTruthy()
  return project
}
