import { navigateMenu } from './support/navigation'
import { expect, test } from '@playwright/test'

import { authenticate } from './support/auth'

test('S19 质量门禁与 Cron 计划配置主路径', async ({ page }) => {
  test.setTimeout(60_000)
  const suffix = Date.now().toString()

  await page.goto('/')
  await authenticate(page)
  const projectName = `S19 浏览器验收 ${suffix}`
  const refresh = await page.request.post('/api/v1/auth/refresh', {
    headers: { 'X-Requested-With': 'FlowTest' },
  })
  expect(refresh.ok()).toBeTruthy()
  const authentication: { access_token: string } = await refresh.json()
  const createdProject = await page.request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${authentication.access_token}` },
    data: { name: projectName, description: 'S19 独立浏览器验收' },
  })
  expect(createdProject.ok(), await createdProject.text()).toBeTruthy()
  const search = page.getByLabel('全局搜索')
  const searchResponse = page.waitForResponse(
    (response) => response.url().includes('/api/v1/search?') && response.status() === 200,
  )
  await search.fill(projectName)
  const results = (await (await searchResponse).json()) as {
    items: Array<{ path: string; resource_type: string; title: string }>
  }
  const project = results.items.find(
    (item) => item.resource_type === 'project' && item.title === projectName,
  )
  expect(project).toBeDefined()
  if (!project) throw new Error('全局搜索未返回本次独立验收项目')
  await page
    .locator('.ant-select-dropdown:visible')
    .getByText(project.title, { exact: true })
    .click()
  await page.waitForURL((url) => `${url.pathname}${url.search}` === project.path)
  await expect(
    page.getByRole('main').getByText(project.title, { exact: true }).first(),
  ).toBeVisible()

  await navigateMenu(page, '质量中心')
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

  await navigateMenu(page, '任务执行')
  await page.getByRole('button', { name: /新建计划/ }).click()
  const planDialog = page.getByRole('dialog', { name: '新建测试计划' })
  await expect(planDialog.getByRole('button', { name: '创建计划', exact: true })).toBeInViewport({
    ratio: 1,
  })
  const scheduleMode = planDialog.getByLabel('调度方式')
  await scheduleMode.click()
  const cronOption = page.locator('.ant-select-dropdown:visible').getByText('Cron', { exact: true })
  await expect(cronOption).toBeInViewport({ ratio: 1 })
  await cronOption.click()
  await expect(scheduleMode).toHaveAttribute('aria-expanded', 'false')
  await expect(planDialog.getByLabel('Cron 表达式')).toBeVisible()
  await expect(planDialog.getByText('Asia/Shanghai', { exact: true })).toBeVisible()
  await expect(planDialog.getByLabel(/队列优先级/)).toHaveValue('5')
  await planDialog.getByRole('button', { name: '取 消' }).click()
})
