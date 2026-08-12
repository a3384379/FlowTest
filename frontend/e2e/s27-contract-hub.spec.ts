import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }

test('S27 OpenAPI 与 Pact 形成服务依赖、提供方验证和安全发布判断闭环', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/')
  await authenticate(page)
  const token = await accessTokenFromSession(page.request)
  const project = await createContractProject(page.request, token)
  await allowComposeTarget(page.request, token, project.id)
  const suffix = Date.now()
  const consumerName = `S27 浏览器 Consumer ${suffix}`
  const providerName = `S27 浏览器 Provider ${suffix}`

  await page.goto(`/projects/${project.id}/contracts`)
  await expect(page.getByRole('heading', { name: '契约中心' })).toBeVisible()
  await expect(page.getByText('Pact 文档按不可信输入处理')).toBeVisible()

  await page.getByRole('button', { name: '导入 Pact' }).click()
  const pactDialog = page.getByRole('dialog', { name: '导入 Pact 文档' })
  await pactDialog.locator('input[type="file"]').setInputFiles({
    name: 's27-browser-pact.json',
    mimeType: 'application/json',
    buffer: Buffer.from(pactDocument(consumerName, providerName)),
  })
  await pactDialog.getByLabel('消费者版本').fill('web-browser-1')
  const pactImported = page.waitForResponse(
    (item) =>
      item.url().endsWith(`/projects/${project.id}/contract-hub/pacts`) && item.status() === 201,
  )
  await page.locator('.ant-modal:visible .ant-modal-footer .ant-btn-primary').click()
  await pactImported

  await expect(page.getByText(`Consumer · web-browser-1`)).toBeVisible()
  await expect(page.getByText(providerName)).toBeVisible()
  await page.getByRole('button', { name: '执行提供方验证' }).click()
  const verifyDialog = page.getByRole('dialog', { name: '执行提供方验证' })
  await verifyDialog.getByLabel('Pact 契约').click()
  await page.getByText(`${consumerName} web-browser-1 → ${providerName}`).click()
  await verifyDialog.getByLabel('提供方版本').fill('1.0.0')
  await verifyDialog.getByLabel('Provider Origin').fill('http://mock-target:8080')
  const verified = page.waitForResponse(
    (item) => item.url().endsWith('/verify') && item.request().method() === 'POST',
  )
  await verifyDialog.getByRole('button', { name: '执行验证' }).click()
  expect((await verified).status()).toBe(201)

  await page.getByRole('button', { name: '导入 OpenAPI' }).click()
  const openapiDialog = page.getByRole('dialog', { name: '导入并绑定 OpenAPI' })
  await openapiDialog.locator('input[type="file"]').setInputFiles({
    name: 's27-browser-openapi.json',
    mimeType: 'application/json',
    buffer: Buffer.from(openapiDocument(providerName)),
  })
  await openapiDialog.getByLabel('提供方服务').click()
  await page.getByText(providerName, { exact: true }).last().click()
  await openapiDialog.locator('input').last().fill('1.0.0')
  const openapiImported = page.waitForResponse(
    (item) => item.url().endsWith(`/projects/${project.id}/contract-runs`) && item.status() === 201,
  )
  await page.locator('.ant-modal:visible .ant-modal-footer .ant-btn-primary').click()
  await openapiImported

  await page.getByRole('combobox', { name: '提供方服务', exact: true }).click()
  await page.getByText(providerName, { exact: true }).last().click()
  await expect(page.getByRole('columnheader', { name: `${providerName} 1.0.0` })).toBeVisible()
  await expect(page.getByText('通过', { exact: true }).first()).toBeVisible()
  await page.getByLabel('待发布提供方版本').fill('1.0.0')
  const checked = page.waitForResponse(
    (item) => item.url().endsWith('/deployment-checks') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '判断是否可安全发布' }).click()
  expect((await checked).status()).toBe(201)
  await expect(page.getByText('可安全发布', { exact: true })).toBeVisible()

  await page.getByRole('tab', { name: /Pact/ }).click()
  await expect(page.getByText(`${consumerName} → ${providerName}`)).toBeVisible()
  await page.getByRole('tab', { name: /OpenAPI/ }).click()
  await expect(page.getByText(`${providerName} · 1.0.0`)).toBeVisible()
})

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createContractProject(
  request: APIRequestContext,
  token: string,
): Promise<Identified> {
  const response = await request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `S27 浏览器 ${Date.now()}`, description: 'S27 Playwright' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Identified
}

async function allowComposeTarget(
  request: APIRequestContext,
  token: string,
  projectId: string,
): Promise<void> {
  const response = await request.put(`/api/v1/projects/${projectId}/security-policy`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { allowed_hosts: ['mock-target'], allowed_private_cidrs: ['172.16.0.0/12'] },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

function pactDocument(consumer: string, provider: string): string {
  return JSON.stringify({
    consumer: { name: consumer },
    provider: { name: provider },
    interactions: [
      {
        description: '浏览器验证健康状态',
        request: { method: 'GET', path: '/health' },
        response: { status: 200, body: { status: 'ok' } },
      },
    ],
    metadata: { pactSpecification: { version: '3.0.0' } },
  })
}

function openapiDocument(provider: string): string {
  return JSON.stringify({
    openapi: '3.0.3',
    info: { title: provider, version: '1.0.0' },
    paths: {
      '/health': {
        get: {
          operationId: 'getHealth',
          responses: {
            '200': {
              description: 'Healthy',
              content: {
                'application/json': {
                  schema: {
                    type: 'object',
                    required: ['status'],
                    properties: { status: { type: 'string' } },
                  },
                },
              },
            },
          },
        },
      },
    },
  })
}
