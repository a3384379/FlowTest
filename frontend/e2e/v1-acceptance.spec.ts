import { expect, test } from '@playwright/test'

import { authenticate } from './support/auth'

test('V1.0 项目治理与脱敏报告主路径', async ({ page }) => {
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
  const pilotProject = results.items.find(
    (item) => item.resource_type === 'project' && item.title.startsWith('S11 V1 Pilot '),
  )
  expect(pilotProject).toBeDefined()
  if (!pilotProject) throw new Error('全局搜索未返回 S11 V1 Pilot 项目')
  await page
    .locator('.ant-select-dropdown:visible')
    .getByText(pilotProject.title, { exact: true })
    .click()
  await page.waitForURL((url) => `${url.pathname}${url.search}` === pilotProject.path)
  const governancePath = new URL(pilotProject.path, page.url()).pathname
  await expect(
    page.getByRole('main').getByText(pilotProject.title, { exact: true }).first(),
  ).toBeVisible()

  await page.getByRole('link', { name: '项目管理' }).click()
  await expect(page.getByRole('heading', { name: '项目治理' })).toBeVisible()
  await expect(page).toHaveURL((url) => url.pathname === governancePath && url.search === '')
  const governanceUrl = page.url()
  await page.reload()
  await expect(page).toHaveURL(governanceUrl)
  await expect(page.getByRole('heading', { name: '项目治理' })).toBeVisible()
  await expect(
    page.getByRole('main').getByText(pilotProject.title, { exact: true }).first(),
  ).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('当前身份：系统管理员')).toBeVisible()
  await expect(page.getByLabel('保留天数')).toHaveValue('90')
  await expect(page.getByLabel('允许域名（每行一个）')).toHaveValue('mock-target')
  await expect(page.getByLabel('允许私网 CIDR（每行一个）')).toHaveValue('172.16.0.0/12')
  await expect(page.getByText('api.created').first()).toBeVisible()

  await page.getByText('质量总览', { exact: true }).click()
  await expect(page).toHaveURL(/\/projects\/[^/]+\/dashboard$/)
  await expect(page.getByRole('heading', { name: '质量指挥中心' })).toBeVisible()
  await expect(page.getByText(/^当前查看：S11 V1 Pilot /)).toBeVisible()

  await page.getByText('测试报告', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '测试报告' })).toBeVisible()
  const businessExecution = page.getByRole('row', { name: /V1 登录下单流程/ })
  await expect(businessExecution).toContainText('8/8 通过')
  await businessExecution.getByRole('button', { name: '详情' }).click()
  const report = page.getByRole('dialog', { name: '执行报告详情' })
  await expect(report).toContainText('V1 登录下单流程')
  await expect(report).toContainText('登录')
  await expect(report).toContainText('查询用户')
  await expect(report).toContainText('创建订单')
  await expect(page.locator('body')).not.toContainText('mock-token')
  await page.keyboard.press('Escape')
  await expect(report).toBeHidden()

  for (const [menu, heading] of [
    ['接口管理', '接口管理'],
    ['流程编排', '流程编排'],
    ['任务执行', '任务执行'],
  ] as const) {
    await page.getByText(menu, { exact: true }).click()
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
})
