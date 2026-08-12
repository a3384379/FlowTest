import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }

test('S26 管理员签名模板经过版本化、独立 Runner、Seed 与幂等清理闭环', async ({ page }) => {
  test.setTimeout(240_000)
  await page.goto('/')
  await authenticate(page)
  const token = await accessTokenFromSession(page.request)
  const project = await createEnvironmentProject(page.request, token)
  const uniqueSuffix = Date.now()
  const templateKey = `playwright.web-${uniqueSuffix}`
  const displayName = `S26 浏览器环境 ${uniqueSuffix}`

  await page.goto(`/projects/${project.id}/environments`)
  await expect(page.getByRole('heading', { name: '环境实验室' })).toBeVisible()
  await page.getByRole('button', { name: /注册环境模板/ }).click()
  const registerDialog = page.getByRole('dialog', { name: '注册管理员签名环境模板' })
  await registerDialog.getByLabel('模板标识').fill(templateKey)
  await registerDialog.getByLabel('显示名称').fill(displayName)
  const registered = page.waitForResponse(
    (item) => item.url().endsWith('/environment-templates') && item.request().method() === 'POST',
  )
  await registerDialog.getByRole('button', { name: '确 定' }).click()
  expect((await registered).status()).toBe(201)
  const templateRow = page.getByRole('row').filter({ hasText: templateKey })
  await expect(templateRow).toContainText(displayName)

  await templateRow.getByRole('button', { name: '新建版本' }).click()
  const versionDialog = page.getByRole('dialog', { name: `为 ${displayName} 创建签名版本` })
  const versioned = page.waitForResponse(
    (item) => item.url().endsWith('/versions') && item.request().method() === 'POST',
  )
  await versionDialog.getByRole('button', { name: '确 定' }).click()
  expect((await versioned).status()).toBe(201)
  const versionRow = page
    .getByRole('row')
    .filter({ hasText: templateKey })
    .filter({ hasText: 'v2' })
  await expect(versionRow).toContainText(displayName)

  await page.getByLabel('模板版本').click()
  await page.getByText(`${displayName} · v2`).click()
  const queued = page.waitForResponse(
    (item) =>
      item.url().endsWith(`/projects/${project.id}/environment-instances`) &&
      item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Provision' }).click()
  expect((await queued).status()).toBe(202)
  await expect(page.getByText('已就绪', { exact: true })).toBeVisible({ timeout: 180_000 })
  const readyRow = page.getByRole('row').filter({ hasText: '已就绪' })
  await readyRow.getByRole('button', { name: /展开行|Expand row/ }).click()
  await expect(page.getByText(/environment-docker:/)).toBeVisible()

  await readyRow.getByRole('button', { name: /清理/ }).click()
  const cleaned = page.waitForResponse(
    (item) => item.url().endsWith('/cleanup') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '确 定' }).click()
  expect((await cleaned).status()).toBe(202)
  await expect(page.getByText('已完成', { exact: true })).toBeVisible({ timeout: 180_000 })
})

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createEnvironmentProject(
  request: APIRequestContext,
  token: string,
): Promise<Identified> {
  const response = await request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `S26 浏览器 ${Date.now()}`, description: 'S26 Playwright' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Identified
}
