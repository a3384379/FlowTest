import { expect, test, type APIRequestContext } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }

test('S25 声明式性能场景经过发布、独立队列、阈值与产物闭环', async ({ page }) => {
  test.setTimeout(150_000)
  await page.goto('/')
  await authenticate(page)
  const token = await accessTokenFromSession(page.request)
  const project = await createPerformanceProject(page.request, token)

  await page.goto(`/projects/${project.id}/performance`)
  await expect(page.getByRole('heading', { name: '性能实验室' })).toBeVisible()
  await page.getByRole('button', { name: /新建性能场景/ }).click()
  const dialog = page.getByRole('dialog', { name: '新建声明式性能场景' })
  await dialog.getByLabel('场景名称').fill(`S25 浏览器性能 ${Date.now()}`)
  await dialog.getByLabel('目标 URL').fill('http://mock-target:8080/health')
  await dialog.getByRole('spinbutton', { name: 'VU' }).fill('1')
  await dialog.getByRole('spinbutton', { name: '持续时间（秒）' }).fill('1')
  await dialog.getByRole('spinbutton', { name: 'P95 上限（ms）' }).fill('5000')
  await dialog.getByRole('spinbutton', { name: '失败率上限（0~1）' }).fill('0')
  const created = page.waitForResponse(
    (item) =>
      item.url().endsWith(`/projects/${project.id}/performance-scenarios`) &&
      item.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: '确 定' }).click()
  expect((await created).ok()).toBeTruthy()

  const published = page.waitForResponse(
    (item) => item.url().endsWith('/publish') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '发布' }).click()
  expect((await published).ok()).toBeTruthy()

  const queued = page.waitForResponse(
    (item) => item.url().endsWith('/runs') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /运行/ }).click()
  expect((await queued).status()).toBe(202)
  await expect(page.getByText('通过', { exact: true }).first()).toBeVisible({ timeout: 120_000 })
  await page.getByRole('button', { name: /展开行|Expand row/ }).click()
  await expect(page.getByText('http_req_duration p(95)<5000')).toBeVisible()
  await expect(page.getByText('原始指标已保存至 MinIO')).toBeVisible()
})

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createPerformanceProject(
  request: APIRequestContext,
  token: string,
): Promise<Identified> {
  const headers = { Authorization: `Bearer ${token}` }
  const response = await request.post('/api/v1/projects', {
    headers,
    data: { name: `S25 浏览器 ${Date.now()}`, description: 'S25 Playwright' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const project = (await response.json()) as Identified
  const policy = await request.put(`/api/v1/projects/${project.id}/security-policy`, {
    headers,
    data: {
      allowed_hosts: ['mock-target'],
      allowed_private_cidrs: ['172.16.0.0/12'],
    },
  })
  expect(policy.ok(), await policy.text()).toBeTruthy()
  return project
}
