import { expect, test } from '@playwright/test'

import { authenticate } from './support/auth'

test('S29 Worker 故障转移在执行面显示递增 Fence、唯一终态与 Drain 恢复', async ({ page }) => {
  test.setTimeout(120_000)
  await page.context().clearCookies()
  await page.goto('/')
  await authenticate(page)
  await page.getByRole('link', { name: '分布式执行面' }).click()

  await expect(page.getByRole('heading', { name: '分布式执行面' })).toBeVisible()
  await expect(page.getByText('PostgreSQL 是任务、Lease 与 Fence 的唯一真相源')).toBeVisible()
  await expect(page.getByText('Runner Lease 已过期并触发 Fence').first()).toBeVisible()
  await expect(page.getByText('Runner Lease 已写入唯一终态').first()).toBeVisible()

  const recoveredWorker = page
    .getByRole('row')
    .filter({ hasText: /s29-b-/ })
    .first()
  await expect(recoveredWorker).toContainText('Drain')
  const resumed = page.waitForResponse(
    (response) =>
      response.url().includes('/execution-fabric/runners/') &&
      response.url().endsWith('/actions') &&
      response.request().method() === 'POST',
  )
  await recoveredWorker.getByRole('button', { name: /恢\s*复/ }).click()
  expect((await resumed).status()).toBe(200)
  await expect(recoveredWorker).toContainText('在线')

  const expand = recoveredWorker.getByRole('button', { name: '展开行' })
  await expand.click()
  await expect(page.getByText('PostgreSQL 单调递增')).toBeVisible()
  await expect(page.getByText('10 秒')).toBeVisible()

  await page.getByRole('button', { name: '新建 Worker Pool' }).click()
  const dialog = page.getByRole('dialog', { name: '新建 Worker Pool' })
  const poolName = `S29 浏览器池 ${Date.now()}`
  await dialog.getByLabel('Pool 名称').fill(poolName)
  await dialog.getByLabel('网络区').fill('browser-e2e')
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/execution-fabric/pools') && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: '创建 Pool' }).click()
  expect((await created).status()).toBe(201)

  const registrationButton = page.getByRole('button', {
    name: `${poolName} · 签发注册令牌`,
  })
  await expect(registrationButton).toBeVisible()
  const issued = page.waitForResponse(
    (response) =>
      response.url().endsWith('/registration-tokens') && response.request().method() === 'POST',
  )
  await registrationButton.click()
  expect((await issued).status()).toBe(201)
  const tokenDialog = page.getByRole('dialog', { name: '一次性 Runner 注册令牌' })
  await expect(tokenDialog.getByText('令牌只显示一次')).toBeVisible()
  await expect(tokenDialog.locator('code')).toContainText('ftrreg_')
})
