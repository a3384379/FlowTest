import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }

test('S28 Git 变更经显式映射形成可解释推荐集合与覆盖矩阵', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/')
  await authenticate(page)
  const token = await accessTokenFromSession(page.request)
  const project = await createImpactProject(page.request, token)
  const contract = await createOpenApiContract(page.request, token, project.id)

  await page.goto(`/projects/${project.id}/impact`)
  await expect(page.getByRole('heading', { name: '变更影响分析' })).toBeVisible()
  await expect(page.getByText('确定性映射，不执行仓库命令')).toBeVisible()

  await page.getByRole('button', { name: /登记资产映射/ }).click()
  const mappingDialog = page.getByRole('dialog', { name: '登记影响资产映射' })
  await mappingDialog.getByLabel('来源选择器').fill('frontend/src/App.tsx')
  await mappingDialog.getByLabel('关联平台资产').click()
  await page
    .getByText(/OpenAPI 契约 · s28-browser\.json/)
    .last()
    .click()
  const mapped = page.waitForResponse(
    (item) => item.url().endsWith('/impact/mappings') && item.request().method() === 'POST',
  )
  await mappingDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  expect((await mapped).status()).toBe(201)
  const mappingRow = page.getByRole('row').filter({ hasText: 'frontend/src/App.tsx' })
  await expect(mappingRow).toContainText('s28-browser.json')

  await page.getByRole('button', { name: /新建影响分析/ }).click()
  const analysisDialog = page.getByRole('dialog', { name: '新建变更影响分析' })
  await analysisDialog.getByLabel('分析名称').fill('S28 浏览器影响分析')
  await analysisDialog.getByLabel('来源引用').fill('playwright/s28')
  await analysisDialog
    .getByLabel('标准 Git unified diff')
    .fill(
      'diff --git a/frontend/src/App.tsx b/frontend/src/App.tsx\n' +
        '--- a/frontend/src/App.tsx\n' +
        '+++ b/frontend/src/App.tsx\n' +
        '@@ -1 +1 @@\n' +
        '-old\n' +
        '+new\n',
    )
  const analyzed = page.waitForResponse(
    (item) => item.url().endsWith('/impact/runs') && item.request().method() === 'POST',
  )
  await analysisDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  expect((await analyzed).status()).toBe(201)

  await expect(page.getByText('S28 浏览器影响分析 · playwright/s28')).toBeVisible()
  await expect(page.getByText('frontend/src/App.tsx 命中 frontend/src/App.tsx')).toBeVisible()
  await expect(page.getByText('s28-browser.json').first()).toBeVisible()
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  await expect(
    page.getByRole('row').filter({ hasText: 'frontend/src/App.tsx' }).first(),
  ).toContainText('已覆盖')
  await expect(page.getByText('证据已保存', { exact: true })).toBeVisible()
  expect(contract.id).toBeTruthy()
})

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createImpactProject(request: APIRequestContext, token: string): Promise<Identified> {
  const response = await request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `S28 浏览器 ${Date.now()}`, description: 'S28 Playwright' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Identified
}

async function createOpenApiContract(
  request: APIRequestContext,
  token: string,
  projectId: string,
): Promise<Identified> {
  const response = await request.post(`/api/v1/projects/${projectId}/contract-runs`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: {
      source_name: 's28-browser.json',
      document: {
        name: 's28-browser.json',
        mimeType: 'application/json',
        buffer: Buffer.from(openApiDocument()),
      },
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Identified
}

function openApiDocument(): string {
  return JSON.stringify({
    openapi: '3.0.3',
    info: { title: 'S28 浏览器契约', version: '1.0.0' },
    paths: {
      '/orders': {
        post: {
          operationId: 'createOrder',
          responses: { '200': { description: 'ok' } },
        },
      },
    },
  })
}
