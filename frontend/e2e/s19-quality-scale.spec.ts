import { expect, test } from '@playwright/test'

import { authenticate } from './support/auth'

test('S19 质量门禁与 Cron 计划配置主路径', async ({ page }) => {
  test.setTimeout(60_000)
  const suffix = Date.now().toString()

  await page.goto('/')
  await authenticate(page)
  const search = page.getByLabel('全局搜索')
  const searchResponse = page.waitForResponse(
    (response) => response.url().includes('/api/v1/search?') && response.status() === 200,
  )
  await search.fill('S11 V1 Pilot')
  const results = (await (await searchResponse).json()) as {
    items: Array<{ path: string; resource_type: string; title: string }>
  }
  const project = results.items.find(
    (item) => item.resource_type === 'project' && item.title.startsWith('S11 V1 Pilot '),
  )
  expect(project).toBeDefined()
  if (!project) throw new Error('全局搜索未返回 S11 V1 Pilot 项目')
  await page
    .locator('.ant-select-dropdown:visible')
    .getByText(project.title, { exact: true })
    .click()
  await page.waitForURL((url) => `${url.pathname}${url.search}` === project.path)
  await expect(
    page.getByRole('main').getByText(project.title, { exact: true }).first(),
  ).toBeVisible()

  await page.getByRole('link', { name: '质量中心' }).click()
  await expect(page).toHaveURL(/\/quality$/)
  await expect(page.getByRole('heading', { name: '质量中心' })).toBeVisible()

  await page.getByRole('button', { name: /新建门禁/ }).click()
  const dialog = page.getByRole('dialog', { name: '新建质量门禁' })
  await dialog.getByLabel('门禁名称').fill(`S19 Gate ${suffix}`)
  await dialog.getByLabel('最低通过率').fill('95')
  const created = page.waitForResponse(
    (response) =>
      response.url().includes('/quality-gates') && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: '确 定' }).click()
  expect((await created).status()).toBe(201)
  await expect(page.getByRole('row').filter({ hasText: `S19 Gate ${suffix}` })).toContainText('95%')

  await page.getByRole('link', { name: '任务执行' }).click()
  await page.getByRole('button', { name: /新建计划/ }).click()
  const planDialog = page.getByRole('dialog', { name: '新建测试计划' })
  const scheduleMode = planDialog.getByLabel('调度方式')
  await scheduleMode.click()
  await page.locator('.ant-select-dropdown:visible').getByText('Cron', { exact: true }).click()
  await expect(scheduleMode).toHaveAttribute('aria-expanded', 'false')
  await expect(planDialog.getByLabel('Cron 表达式')).toBeVisible()
  await expect(planDialog.getByText('Asia/Shanghai', { exact: true })).toBeVisible()
  await expect(planDialog.getByLabel(/队列优先级/)).toHaveValue('5')
  await planDialog.getByRole('button', { name: '取 消' }).click()
})
